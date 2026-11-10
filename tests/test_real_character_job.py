"""``model3d.real.make``: the server job that makes a realistic character (services/real_character_job.py), its recipe
(services/real_character_recipe.py) and its doors (routers/model3d_real.py).

A fake server answers the generation tools the job calls and writes real 2:1 painted pictures, so the whole path runs with no GPU.
One test runs the real ``make_character`` (the relief's depth model is made missing, so it is skipped); the others pass a light
``make`` that writes the files a make writes, and every test passes a ``rig`` (a synthetic picture has no face to rig)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from routers.model3d_real import CANCEL, GET, LIST, MAKE, PRESETS, STATUS, command_catalog, command_handlers, create_model3d_real_router
from services import blob_face_relief
from services.blob_builder import BlobTraitsError
from services.character_animation_job import JobStore
from services.character_kit_library import patch_character_kit, read_character_kit_library
from services.flat_rig import FlatRigError
from services.make_gates import note
from services.real_character_job import JOBS_DIR, RealCharacterJobs, RealJobDeps, RealJobError, kit_notes
from services.real_character_recipe import HEAD_PROMPT, characters, latest, presets, resolve_input

WS = "studio"
OUTFIT = "A dark green bomber jacket, a white t-shirt, blue jeans, white sneakers."
FACE = "A woman in her thirties, brown eyes, shoulder-length dark hair."


def _painted(path: Path, seed: str, size=(2048, 1024)) -> None:
    """A picture with real detail (a gradient with noise), different for each seed."""
    rng = np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16))
    width, height = size
    ramp = np.linspace(40, 200, width, dtype=np.float32)[None, :, None] * np.ones((height, 1, 3), dtype=np.float32)
    Image.fromarray(np.clip(ramp + rng.normal(0, 25, (height, width, 3)), 0, 255).astype(np.uint8)).save(path)


class FakeServer:
    """What the job calls through ``LocalMcp.call``. ``refuse`` names parts (body, head) whose next picture fails."""

    def __init__(self, root: Path) -> None:
        self.root, self.calls, self.refuse, self.last = root, [], set(), ""

    def images(self) -> list[dict]:
        return [arguments["input"] for tool, arguments in self.calls if tool == "generation.image"]

    def call(self, tool: str, arguments: dict) -> dict:
        self.calls.append((tool, arguments))
        if tool == "generation.image":
            name = arguments["input"]["output_name"]
            part = next(part for part in ("body", "head") if f"-{part}-" in name)
            if part in self.refuse:
                self.refuse.discard(part)
                return {"_is_error": True, "error": {"code": "insufficient_vram", "message": "insufficient VRAM"}}
            _painted(self.root / f"{name}.png", name)
            self.last = str(self.root / f"{name}.png")
            return {"receipt": {"result": {"job_id": f"gen-{len(self.calls)}", "status": "queued"}}}
        if tool == "jobs.wait":
            return {"result": {"status": "completed", "output_files": [self.last]}}
        return {"result": {"status": "cancelled"}}


class LightMake:
    """Writes what ``make_character`` writes for the job (GLBs named by the intent, the face pose from the head picture) and answers
    the same fields, in a fraction of the time."""

    def __init__(self) -> None:
        self.calls = []

    def __call__(self, root, workspace, name, intent, traits, *, face_kit=True):
        self.calls.append({"intent": intent, "traits": traits, "face_kit": face_kit})
        stamp = hashlib.sha256(intent.encode()).hexdigest()[:16]
        plain, rigged = f"blob-{name}-{stamp}.glb", f"blob-{name}-{stamp}-rigged.glb"
        for file in (plain, rigged):
            (Path(root) / file).write_bytes(b"glTF" + stamp.encode())
        with Image.open(Path(root) / traits["texture_head"]) as head:
            head.convert("RGB").crop((0, 0, 682, 1024)).resize((1024, 1024)).save(Path(root) / f"anime-{name.lower()}-face-pose.png")
        return {"file": plain, "url": f"/api/v1/file/{plain}?workspace={workspace}", "rigged_file": rigged, "rigged_url": f"/api/v1/file/{rigged}?workspace={workspace}",
                "clips": [], "humanoid": {"warnings": [], "confidence": 0.9}, "faceAnchor": {"center": [0, 1.6, 0.05], "radii": [0.08, 0.1, 0.08]},
                "traits": {"family": "anime"}, "name": name, "workspace": workspace, "guide_body_file": f"anime-{name.lower()}-guide-body.png",
                "guide_head_file": f"anime-{name.lower()}-guide-head.png", "texture_file": traits["texture"], "face_pose_file": f"anime-{name.lower()}-face-pose.png",
                "relief": "skipped", "kit_id": None, "poses": [], "preview": None, "face": None, "character": {"gender": traits["gender"], "style": "real"},
                "warnings": [note("relief_skipped", "The face relief was skipped.")]}


class FakeRig:
    """The flat rig as far as the job reads it: it saves the kit (the base untouched) and reports its mouths. ``fail`` raises."""

    def __init__(self) -> None:
        self.calls, self.fail = [], False

    def __call__(self, root, workspace, kit_id, *, base_revision, style):
        self.calls.append({"kit_id": kit_id, "style": style})
        if self.fail:
            raise FlatRigError("mouth_not_found", "Pose base: no mouth found", 422)
        kit = read_character_kit_library(root)["kits"][kit_id]
        kit = {**kit, "provenance": [*kit["provenance"], {"method": "flat-rig", "sources": {"base": kit["base"]["source"]}}]}
        saved = patch_character_kit(root, kit_id, kit, base_revision=base_revision)
        return {"revision": saved["revision"], "character": saved["kits"][kit_id], "review": f"/api/v1/file/kit-{kit_id}-rig-review.png?workspace={workspace}",
                "unwipedPoses": [], "warnings": {"base": ["mouth_small_opening"], "neutral": []}, "style": style,
                "poses": {"base": {"mouthFound": True}, "neutral": {"mouthFound": True}}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(blob_face_relief, "CHECKPOINT", tmp_path / "ckpts" / "depth" / "not_there.pth")
    root = tmp_path / WS
    root.mkdir()
    server, make, rig = FakeServer(root), LightMake(), FakeRig()
    jobs = RealCharacterJobs(RealJobDeps(call=server.call, workspace_dir=lambda _name: str(root), inline=True, make=make, rig=rig))
    return {"root": root, "server": server, "make": make, "rig": rig, "jobs": jobs}


def _make(world, **fields):
    return world["jobs"].start(WS, {"name": "Marta", **fields})


def _first(world):
    return _make(world, gender="woman", outfit_prompt=OUTFIT, face_prompt=FACE, seed=11)


def _steps(job):
    return {step["id"]: step["status"] for step in job["steps"]}


def _kit(world):
    return read_character_kit_library(str(world["root"]))["kits"]["real-marta"]


def test_the_whole_chain_runs_on_the_server_with_the_real_make(tmp_path, monkeypatch):
    monkeypatch.setattr(blob_face_relief, "CHECKPOINT", tmp_path / "not_there.pth")
    root = tmp_path / WS
    root.mkdir()
    server, rig = FakeServer(root), FakeRig()
    jobs = RealCharacterJobs(RealJobDeps(call=server.call, workspace_dir=lambda _name: str(root), inline=True, rig=rig))
    job = jobs.start(WS, {"name": "Marta", "gender": "woman", "skin": "#E3B58F", "outfit_prompt": OUTFIT, "face_prompt": FACE, "seed": 11})
    assert job["status"] == "completed", job.get("error")
    assert _steps(job) == {"guides": "done", "body": "done", "head": "done", "character": "done", "kit": "done"}
    body, head = server.images()
    for picture, part in ((body, "body"), (head, "head")):
        params = picture["params"]
        assert params["image_refs"] == [f"/api/v1/file/anime-marta-guide-{part}.png?workspace={WS}"]
        assert (params["model_type"], params["resolution"], params["video_prompt_type"], params["seed"]) == ("qwen_image_21_turbo", "2048x1024", "KI", 11)
        assert params["num_inference_steps"] == 8 and params["guidance_scale"] == 1.0
    assert OUTFIT in body["params"]["prompt"] and FACE in head["params"]["prompt"] and "pure right profile" in head["params"]["prompt"]
    result = job["result"]
    assert (root / result["rigged_file"]).is_file() and result["kit_id"] == "real-marta" and result["relief"] == "skipped"
    assert {"guide_body_file", "guide_head_file", "face_pose_file", "faceAnchor", "humanoid", "texture_file", "clips"} <= set(result)
    assert [item["code"] for item in result["warnings"]] == ["relief_skipped", "mouth_small_opening"]
    assert result["talk_kit"]["mouthFound"] == {"base": True, "neutral": True} and result["talk_kit"]["review"].endswith("rig-review.png?workspace=studio")
    kits = read_character_kit_library(str(root))["kits"]
    assert set(kits) == {"real-marta"}, "the drawn anime_head kit is not made for a realistic character"
    assert rig.calls == [{"kit_id": "real-marta", "style": {"mouthStyle": "warp"}}]
    recipe_file = root / (Path(result["rigged_file"]).name.removesuffix(".glb") + ".recipe.json")
    stored = json.loads(recipe_file.read_text(encoding="utf-8"))
    assert stored["input"] == {"gender": "woman", "skin": "#E3B58F", "outfit_prompt": OUTFIT, "face_prompt": FACE, "seed": 11,
                               "image_model": "qwen_image_21_turbo", "talk_kit": True, "traits": {}}
    assert stored["traits"]["face_span"] == 40.0 and stored["traits"]["head_join"] == "map" and stored["traits"]["bottom"] == "trousers"
    assert stored["kit_id"] == "real-marta" and stored["pictures"]["head"]["file"] == head["output_name"] + ".png"
    assert stored["prompts"]["head"] == HEAD_PROMPT.format(face=FACE) and result["recipe"]["keys"]["kit"] == stored["pictures"]["head"]["key"]


def test_a_rerun_with_nothing_changed_paints_nothing_and_remakes_nothing(world):
    first = _first(world)
    again = _make(world)
    assert again["status"] == "completed", again.get("error")
    assert _steps(again) == {"guides": "done", "body": "reused", "head": "reused", "character": "reused", "kit": "reused"}
    assert len(world["server"].images()) == 2 and len(world["make"].calls) == 1 and len(world["rig"].calls) == 1
    assert again["result"]["rigged_file"] == first["result"]["rigged_file"] and again["result"]["kit_id"] == "real-marta"
    assert sorted(again["result"]["reused"]) == ["body", "character", "head", "kit"]


def test_a_new_outfit_repaints_only_the_body_and_keeps_the_face_kit(world):
    first = _first(world)
    kit_before = _kit(world)
    changed = _make(world, outfit_prompt="A charcoal business suit, a white shirt, black shoes.")
    assert _steps(changed) == {"guides": "done", "body": "done", "head": "reused", "character": "done", "kit": "reused"}
    assert [item["output_name"].split("-")[2] for item in world["server"].images()] == ["body", "head", "body"]
    assert changed["result"]["rigged_file"] != first["result"]["rigged_file"]
    assert world["make"].calls[-1]["traits"]["texture_head"] == first["result"]["recipe"]["pictures"]["head"]["file"]
    assert len(world["rig"].calls) == 1 and _kit(world) == kit_before
    stored = latest(world["root"], "Marta")
    assert stored["input"]["face_prompt"] == FACE and stored["input"]["seed"] == 11 and stored["input"]["outfit_prompt"].startswith("A charcoal")


def test_a_new_face_repaints_the_head_and_refreshes_the_kit(world):
    first = _first(world)
    old_key = first["result"]["recipe"]["keys"]["head"]
    changed = _make(world, face_prompt="A woman in her sixties, short white hair, green eyes.")
    assert _steps(changed) == {"guides": "done", "body": "reused", "head": "done", "character": "done", "kit": "done"}
    assert [item["output_name"].split("-")[2] for item in world["server"].images()] == ["body", "head", "head"]
    kit = _kit(world)
    made = next(entry for entry in kit["provenance"] if entry["method"] == "real-face-tile")
    new_key = changed["result"]["recipe"]["keys"]["head"]
    assert new_key != old_key and made["headKey"] == new_key and changed["result"]["talk_kit"]["headKey"] == new_key
    assert kit["base"]["source"] == f"/api/v1/file/real-marta-face-{new_key[:10]}.png?workspace={WS}"
    assert (world["root"] / f"real-marta-face-{old_key[:10]}.png").is_file(), "the old face picture stays for the old character"
    assert len(world["rig"].calls) == 2


def test_going_back_to_an_earlier_outfit_reuses_its_picture(world):
    _first(world)
    _make(world, outfit_prompt="Blue work overalls.")
    back = _make(world, outfit_prompt=OUTFIT)
    assert _steps(back)["body"] == "reused" and len(world["server"].images()) == 3


def test_a_failed_picture_fails_the_job_and_the_next_make_keeps_what_was_painted(world):
    world["server"].refuse.add("head")
    failed = _first(world)
    assert failed["status"] == "failed" and failed["errorCode"] == "insufficient_vram"
    assert _steps(failed) == {"guides": "done", "body": "done", "head": "failed", "character": "waiting", "kit": "waiting"}
    assert latest(world["root"], "Marta") is None
    resumed = _first(world)
    assert resumed["status"] == "completed"
    # the refused head, then the head of the second make: the body is not painted again
    assert _steps(resumed)["body"] == "reused" and [item["output_name"].split("-")[2] for item in world["server"].images()] == ["body", "head", "head"]


def test_a_given_picture_is_used_instead_of_painting_one(world):
    _painted(world["root"] / "my-body.png", "mine")
    job = _make(world, gender="woman", texture="/api/v1/file/my-body.png?workspace=studio", face_prompt=FACE)
    assert job["status"] == "completed" and _steps(job)["body"] == "given"
    assert [item["output_name"].split("-")[2] for item in world["server"].images()] == ["head"]
    assert world["make"].calls[0]["traits"]["texture"] == "my-body.png" and job["result"]["recipe"]["pictures"]["body"]["given"] is True
    painted = _make(world, outfit_prompt=OUTFIT)   # a prompt for the body replaces the picture that was given
    assert _steps(painted)["body"] == "done" and "texture" not in latest(world["root"], "Marta")["input"]


def test_a_face_kit_that_cannot_be_rigged_still_completes_the_character_and_is_tried_again(world):
    world["rig"].fail = True
    job = _first(world)
    assert job["status"] == "completed" and _steps(job)["kit"] == "failed"
    assert job["result"]["kit_id"] is None and [item["code"] for item in job["result"]["warnings"]][-1] == "talk_kit_failed"
    world["rig"].fail = False
    again = _make(world)
    assert _steps(again)["kit"] == "done" and again["result"]["kit_id"] == "real-marta" and len(world["make"].calls) == 1


def test_talk_kit_false_makes_no_kit(world):
    job = _make(world, outfit_prompt=OUTFIT, face_prompt=FACE, talk_kit=False)
    assert _steps(job)["kit"] == "skipped" and job["result"]["kit_id"] is None and world["rig"].calls == []
    assert job["result"]["preview"] == f"/api/v1/file/anime-marta-face-pose.png?workspace={WS}"


def test_the_kit_notes_say_what_the_rig_found():
    report = {"warnings": {"base": [], "neutral": ["eyes_low"]}, "mouthFound": {"base": False}, "notices": [{"code": "landmark_models_missing"}]}
    notes = kit_notes(report)
    assert [(item["code"], item.get("pose")) for item in notes] == [("eyes_low", "neutral"), ("mouth_not_found", "base"), ("landmark_models_missing", None)]
    assert kit_notes({"warnings": {"base": ["mouth_not_found"]}, "mouthFound": {"base": False}})[0]["code"] == "mouth_not_found"
    assert len(kit_notes({"warnings": {"base": ["mouth_not_found"]}, "mouthFound": {"base": False}})) == 1


def test_the_input_is_checked_before_anything_is_made(world):
    for fields, code in (({"gender": "woman"}, "prompt_required"), ({"outfit_prompt": OUTFIT, "face_prompt": FACE, "gender": "girl"}, "invalid_gender"),
                         ({"outfit_prompt": OUTFIT, "face_prompt": FACE, "seed": -1}, "invalid_seed"),
                         ({"outfit_prompt": OUTFIT, "face_prompt": FACE, "colour": "red"}, "unknown_field"),
                         ({"outfit_prompt": OUTFIT, "face_prompt": FACE, "traits": {"gender": "man"}}, "invalid_traits"),
                         ({"outfit_prompt": OUTFIT, "face_prompt": FACE, "bottom": "kilt"}, "invalid_bottom"),
                         ({"outfit_prompt": "  ", "face_prompt": FACE}, "invalid_prompt")):
        with pytest.raises(BlobTraitsError) as refused:
            _make(world, **fields)
        assert refused.value.code == code, fields
    with pytest.raises(RealJobError) as missing:
        _make(world, texture="nowhere.png", face_prompt=FACE)
    assert missing.value.code == "texture_missing"
    with pytest.raises(RealJobError) as stale:
        _make(world, outfit_prompt=OUTFIT, face_prompt=FACE, base_revision=99)
    assert stale.value.code == "revision_conflict" and stale.value.status == 409
    assert world["server"].calls == [] and world["make"].calls == []


def test_a_seed_is_drawn_once_for_a_new_character_and_kept():
    effective = resolve_input({"outfit_prompt": OUTFIT, "face_prompt": FACE}, None)
    assert 0 <= effective["seed"] and effective["gender"] == "man" and effective["talk_kit"] is True
    again = resolve_input({"face_prompt": "Another face."}, {"input": effective})
    assert again["seed"] == effective["seed"] and again["outfit_prompt"] == OUTFIT
    cleared = resolve_input({"texture": None, "skin": None}, {"input": {**effective, "texture": "a.png", "skin": "#AA8866"}})
    assert "texture" not in cleared and "skin" not in cleared


def test_the_same_intent_returns_the_same_job_and_other_input_conflicts(world):
    first = world["jobs"].start(WS, {"name": "Marta", "outfit_prompt": OUTFIT, "face_prompt": FACE}, "intent-1")
    again = world["jobs"].start(WS, {"name": "Marta", "outfit_prompt": OUTFIT, "face_prompt": FACE}, "intent-1")
    assert again["jobId"] == first["jobId"] and len(world["server"].images()) == 2
    with pytest.raises(RealJobError) as conflict:
        world["jobs"].start(WS, {"name": "Marta", "outfit_prompt": "Other clothes.", "face_prompt": FACE}, "intent-1")
    assert conflict.value.code == "intent_conflict"


def test_a_job_cut_by_a_restart_reads_as_interrupted_and_a_cancel_of_a_finished_job_changes_nothing(world):
    JobStore(str(world["root"]), JOBS_DIR).save({"jobId": "real-cut", "workspace": WS, "name": "Marta", "slug": "marta", "status": "running",
                                                 "steps": [{"id": "body", "status": "running"}]})
    cut = world["jobs"].status(WS, "real-cut")
    assert cut["status"] == "interrupted" and cut["steps"][0]["status"] == "waiting"
    done = _first(world)
    assert world["jobs"].cancel(WS, done["jobId"])["status"] == "completed"
    with pytest.raises(RealJobError):
        world["jobs"].status(WS, "../escape")


def test_the_recipe_is_listed_and_a_deleted_character_says_it_is_missing(world):
    job = _first(world)
    rows = characters(world["root"])
    assert [(row["name"], row["kit_id"], row["missing"]) for row in rows] == [("Marta", "real-marta", False)]
    assert rows[0]["face_url"].startswith("/api/v1/file/real-marta-face-") and rows[0]["outfit_prompt"] == OUTFIT
    (world["root"] / job["result"]["rigged_file"]).unlink()
    assert characters(world["root"])[0]["missing"] is True


def test_the_prompt_library_has_outfits_and_faces_in_both_languages():
    library = presets()
    for group in ("outfits", "faces"):
        items = library[group]
        assert 6 <= len(items) <= 10 and len({item["id"] for item in items}) == len(items)
        for item in items:
            assert item["label"]["es"] and item["label"]["en"] and item["gender"] in ("any", "man", "woman")
            assert item["prompt"].isascii() and 20 <= len(item["prompt"]) <= 300
    assert {item["gender"] for item in library["faces"]} == {"man", "woman"}


def _client(world):
    app = FastAPI()
    handlers = command_handlers(lambda _name: str(world["root"]), jobs=world["jobs"])
    app.include_router(create_model3d_real_router(handlers))
    return TestClient(app), handlers


def test_the_routes_and_the_mcp_tools_are_one_handler_each(world):
    client, handlers = _client(world)
    assert set(handlers) == {MAKE, STATUS, CANCEL, GET, LIST, PRESETS} == {item["name"] for item in command_catalog()}
    body = {"version": 1, "intent_id": "ui-1", "input": {"workspace": WS, "name": "Marta", "gender": "woman", "outfit_prompt": OUTFIT, "face_prompt": FACE}}
    made = client.post("/api/v1/model3d/real", json=body).json()
    assert made["operation"] == MAKE and made["status"] == "completed" and made["result"]["result"]["kit_id"] == "real-marta"
    followed = client.post("/api/v1/model3d/real/status", json={"version": 1, "input": {"workspace": WS, "job_id": made["result"]["jobId"]}}).json()
    assert followed["result"]["jobId"] == made["result"]["jobId"]
    got = client.post("/api/v1/model3d/real/get", json={"version": 1, "input": {"workspace": WS, "name": "marta"}}).json()["result"]
    assert got["input"]["outfit_prompt"] == OUTFIT and got["missing"] is False and "made" not in got
    listed = client.post("/api/v1/model3d/real/list", json={"version": 1, "input": {"workspace": WS}}).json()["result"]["characters"]
    assert [row["name"] for row in listed] == ["Marta"]
    assert client.post("/api/v1/model3d/real/presets").json()["result"]["outfits"]
    refused = client.post("/api/v1/model3d/real", json={**body, "intent_id": "ui-2", "input": {**body["input"], "name": "Ana", "gender": "girl"}})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "invalid_gender"
    unknown = client.post("/api/v1/model3d/real/get", json={"version": 1, "input": {"workspace": WS, "name": "nobody"}})
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "character_not_found"


def test_the_doors_are_wired_into_the_model3d_catalog_handlers_and_profile():
    from routers.model3d_compose import command_catalog as model3d_catalog, command_handlers as model3d_handlers
    from services.mcp_profiles import PROFILES

    names = {item["name"] for item in model3d_catalog()}
    real = {MAKE, STATUS, CANCEL, GET, LIST, PRESETS}
    assert real <= names and real <= set(PROFILES["series"]["tools"])
    handlers = model3d_handlers(lambda _name: "/nonexistent", ":memory:", lambda: None)
    assert real <= set(handlers)
    make = next(item for item in model3d_catalog() if item["name"] == MAKE)
    assert make["inputSchema"]["required"] == ["version", "input", "intent_id"]
    assert {"outfit_prompt", "face_prompt", "texture", "texture_head", "talk_kit", "traits"} <= set(make["inputSchema"]["properties"]["input"]["properties"])
