"""The server job that makes a character's animation (services/character_animation_job.py) and its HTTP routes.

A fake server answers the tools the job calls (generation.image, jobs.wait, studio.key, jobs.cancel) and writes real pictures, so the
whole path runs: poses, sheet, and the animation saved on the kit as pending."""
import threading
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from routers.character_animation_jobs import create_character_animation_jobs_router
from services.character_animation_job import AnimationJobDeps, AnimationJobError, CharacterAnimationJobs, reference_of
from services.character_kit_library import patch_character_kit, read_character_kit_library, write_character_kit_library

WS = "demo"


def _picture(path: Path, *, keyed: bool, shift: int = 0) -> None:
    pixels = np.zeros((200, 140, 4), dtype=np.uint8) if keyed else np.full((200, 140, 4), (0, 255, 0, 255), dtype=np.uint8)
    pixels[10:40, 45 + shift:75 + shift] = (200, 160, 120, 255)
    pixels[40:110, 38 + shift:82 + shift] = (230, 180, 30, 255)
    pixels[110:200, 50 + shift:62 + shift] = (60, 60, 70, 255)
    Image.fromarray(pixels).save(path)


class FakeServer:
    """What the job calls through ``LocalMcp.call``. ``refuse`` names pose ids whose picture fails."""

    def __init__(self, root: Path) -> None:
        self.root, self.calls, self.refuse, self.during = root, [], set(), None

    def of(self, tool: str) -> list[dict]:
        return [arguments["input"] for name, arguments in self.calls if name == tool]

    def call(self, tool: str, arguments: dict) -> dict:
        self.calls.append((tool, arguments))
        if tool == "generation.image":
            name = arguments["input"]["output_name"]
            if any(f"-{pose}-" in name for pose in self.refuse):
                return {"_is_error": True, "error": {"code": "insufficient_vram", "message": "insufficient VRAM"}}
            _picture(self.root / f"{name}.png", keyed=False)
            return {"receipt": {"result": {"job_id": f"gen-{len(self.calls)}", "status": "queued"}}, "output": f"{name}.png"}
        if tool == "jobs.wait":
            if self.during:
                self.during()
            outputs = [arguments_input["output_name"] + ".png" for arguments_input in self.of("generation.image")]
            return {"result": {"status": "completed", "output_files": [str(self.root / outputs[-1])]}}
        if tool == "studio.key":
            source = arguments["input"]["source"]
            name = f"{Path(source).stem}-key.png"
            _picture(self.root / name, keyed=True, shift=len(self.of("studio.key")) % 5)
            return {"result": {"url": f"/api/v1/file/{name}?workspace={WS}", "file": name}}
        return {"result": {"status": "cancelled"}}


@pytest.fixture
def world(tmp_path):
    (tmp_path / "uploads").mkdir()
    _picture(tmp_path / "hero-key.png", keyed=True)
    base = {"id": "hero-base", "name": "Hero", "source": f"/api/v1/file/hero-key.png?workspace={WS}", "kind": "image",
            "alphaStatus": "transparent", "reviewState": "approved", "workspace": WS}
    write_character_kit_library(str(tmp_path), {"kits": {"hero": {"id": "hero", "name": "Hero", "style": "cutout", "base": base, "identityReference": base,
                                                                  "poses": {}, "mouth": {}, "eyes": {}, "anchors": {}, "provenance": [], "lookNotes": "a detective in a mustard coat"}},
                                                "activeId": "hero"}, base_revision=0)
    server = FakeServer(tmp_path)
    jobs = CharacterAnimationJobs(AnimationJobDeps(call=server.call, workspace_dir=lambda workspace: str(tmp_path),
                                                   uploads_root=lambda: str(tmp_path / "uploads"), inline=True,
                                                   model_defaults=lambda model: {"num_inference_steps": 8, "guidance_scale": 1} if "turbo" in model else {}))
    return tmp_path, server, jobs


def _kit(root: Path) -> dict:
    return read_character_kit_library(str(root))["kits"]["hero"]


def test_an_animation_is_made_from_the_characters_picture_and_saved_pending_for_review(world):
    root, server, jobs = world
    job = jobs.start(WS, "hero", "wave")
    assert job["status"] == "completed" and job["result"]["reviewState"] == "pending" and job["result"]["count"] == 4
    made = _kit(root)["animations"]["wave"]
    assert made["reviewState"] == "pending" and [frame["id"] for frame in made["frames"]] == [take["id"] for take in job["takes"]]
    assert made["sheet"]["count"] == 4 and made["model"] == "qwen_image_21" and made["scaleBy"] == "base" and made["facing"] == "front"
    assert (root / Path(made["sheet"]["source"].split("/")[-1].split("?")[0])).is_file()
    provenance = _kit(root)["provenance"][-1]
    assert provenance["method"] == "character-animation-make" and provenance["animation"] == "wave"
    images = server.of("generation.image")
    assert len(images) == 4 and all(item["params"]["image_refs"] == [f"/api/v1/file/hero-key.png?workspace={WS}"] for item in images)
    assert all(item["params"]["video_prompt_type"] == "I" and item["params"]["model_type"] == "qwen_image_21" for item in images)
    assert "a detective in a mustard coat" in images[0]["params"]["prompt"] and images[0]["params"]["negative_prompt"]
    intents = [arguments["intent_id"] for name, arguments in server.calls if name in ("generation.image", "studio.key")]
    assert len(intents) == len(set(intents)) == 8, "every picture and every key has an intent of its own"
    assert "approved" not in str(made["reviewState"])


def test_a_pose_that_fails_stops_the_job_and_the_next_one_keeps_the_poses_already_made(world):
    root, server, jobs = world
    server.refuse = {"passing"}
    failed = jobs.start(WS, "hero", "walk")
    assert failed["status"] == "failed" and "insufficient VRAM" in failed["error"]
    assert [take["status"] for take in failed["takes"]] == ["ready", "failed", "waiting", "waiting"]
    assert "animations" not in _kit(root), "nothing is saved until every pose is made"
    server.refuse, server.calls = set(), []
    retry = jobs.start(WS, "hero", "walk")
    assert retry["status"] == "completed" and retry["jobId"] != failed["jobId"]
    assert [take["status"] for take in retry["takes"]] == ["reused", "ready", "ready", "ready"]
    assert len(server.of("generation.image")) == 3, "the pose that was made is not made again"
    first = retry["takes"][0]["id"]
    assert not any(call["output_name"] == f"hero-walk-{first}-{retry['jobId'][-6:]}" for call in server.of("generation.image"))


def test_one_pose_of_a_finished_animation_is_made_again_and_the_others_stay(world):
    root, server, jobs = world
    jobs.start(WS, "hero", "wave")
    before = {frame["id"]: frame["source"] for frame in _kit(root)["animations"]["wave"]["frames"]}
    pose = next(iter(before))
    server.calls = []
    job = jobs.start(WS, "hero", "wave", pose=pose)
    assert job["status"] == "completed" and job["remake"] == pose and len(server.of("generation.image")) == 1
    after = {frame["id"]: frame["source"] for frame in _kit(root)["animations"]["wave"]["frames"]}
    assert after[pose] != before[pose] and {key: value for key, value in after.items() if key != pose} == {key: value for key, value in before.items() if key != pose}
    with pytest.raises(AnimationJobError) as error:
        jobs.start(WS, "hero", "walk", pose="contact")
    assert error.value.code == "pose_not_found", "there is nothing made to repeat a pose of"


def test_an_animation_the_author_describes_keeps_their_words_and_one_pose_can_be_made_again_from_them(world):
    root, server, jobs = world
    custom = {"title": "Sonrisa pícara", "view": "bust", "poses": ["una sonrisa torcida", "la misma sonrisa con un guiño"]}
    job = jobs.start(WS, "hero", "sonrisa-picara", custom=custom)
    assert job["status"] == "completed"
    made = _kit(root)["animations"]["sonrisa-picara"]
    assert made["title"] == "Sonrisa pícara" and made["view"] == "bust" and made["scaleBy"] == "face"
    assert [frame["prompt"] for frame in made["frames"]] == custom["poses"]
    prompts = [item["params"]["prompt"] for item in server.of("generation.image")]
    assert "una sonrisa torcida." in prompts[0] and "Close-up portrait" in prompts[0] and server.of("generation.image")[0]["params"]["resolution"] == "1024x1024"
    server.calls = []
    again = jobs.start(WS, "hero", "sonrisa-picara", pose="pose-2")
    assert again["status"] == "completed" and "guiño" in server.of("generation.image")[0]["params"]["prompt"]


def test_what_cannot_be_made_is_refused_before_any_picture_is_asked_for(world):
    root, server, jobs = world
    for kwargs, code in (({"animation_id": "nope"}, "invalid_animation"), ({"animation_id": "wave", "custom": {"title": "x", "view": "bust", "poses": ["a"]}}, "invalid_animation"),
                         ({"animation_id": "mine", "custom": {"title": "x", "view": "bust", "poses": []}}, "invalid_animation")):
        with pytest.raises(AnimationJobError) as error:
            jobs.start(WS, "hero", kwargs.pop("animation_id"), **kwargs)
        assert error.value.code == code
    with pytest.raises(AnimationJobError) as error:
        jobs.start(WS, "ghost", "wave")
    assert error.value.code == "kit_not_found" and error.value.status == 404
    with pytest.raises(AnimationJobError) as error:
        jobs.start(WS, "hero", "wave", model="../etc")
    assert error.value.code == "invalid_model"
    assert not server.calls


def test_a_character_with_no_persistent_picture_cannot_make_poses(world, monkeypatch):
    root, server, jobs = world
    assert reference_of({"base": {"source": "blob:http://x/1"}}) is None and reference_of({}) is None
    monkeypatch.setattr("services.character_animation_job.reference_of", lambda kit: None)
    with pytest.raises(AnimationJobError) as error:
        jobs.start(WS, "hero", "wave")
    assert error.value.code == "no_reference" and not server.calls


def test_a_distilled_model_runs_its_few_steps_without_a_negative_prompt(world):
    root, server, jobs = world
    assert jobs.start(WS, "hero", "nod", model="qwen_image_21_turbo")["status"] == "completed"
    params = server.of("generation.image")[0]["params"]
    assert params["model_type"] == "qwen_image_21_turbo" and params["num_inference_steps"] == 8 and "negative_prompt" not in params
    assert _kit(root)["animations"]["nod"]["model"] == "qwen_image_21_turbo"


def test_a_character_edited_while_its_animation_was_made_keeps_the_edit(world):
    root, server, jobs = world
    original = server.call

    def call(tool, arguments):
        if tool == "studio.key" and len(server.of("studio.key")) == 3:  # the last pose is about to be keyed
            library = read_character_kit_library(str(root))
            patch_character_kit(str(root), "hero", dict(library["kits"]["hero"], name="Hero, renamed"), base_revision=library["revision"], make_active=False)
        return original(tool, arguments)

    jobs.deps.call = call
    assert jobs.start(WS, "hero", "wave")["status"] == "completed"
    kit = _kit(root)
    assert kit["name"] == "Hero, renamed" and kit["animations"]["wave"]["reviewState"] == "pending"


def test_a_job_cancelled_while_a_pose_is_made_stops_and_keeps_what_was_made(world):
    root, server, jobs = world
    state = {"waits": 0}

    def cancel_at_the_second_wait():
        state["waits"] += 1
        if state["waits"] == 2:
            running = next(job for job in jobs.jobs(WS, "hero") if job["status"] == "running")
            jobs.cancel(WS, running["jobId"])

    server.during = cancel_at_the_second_wait
    job = jobs.start(WS, "hero", "wave")
    assert job["status"] == "cancelled" and not job.get("error")
    assert [take["status"] for take in job["takes"]][:2] == ["ready", "waiting"] and "animations" not in _kit(root)
    server.during, server.calls = None, []
    retry = jobs.start(WS, "hero", "wave")
    assert [take["status"] for take in retry["takes"]][0] == "reused" and len(server.of("generation.image")) == 3


def test_a_request_for_an_animation_being_made_returns_that_job_and_a_restart_marks_it_interrupted(world):
    root, server, jobs = world
    release = threading.Event()
    server.during = lambda: release.wait(10)
    jobs.deps.inline = False
    first = jobs.start(WS, "hero", "wave")
    assert jobs.start(WS, "hero", "wave")["jobId"] == first["jobId"]
    assert [item["jobId"] for item in jobs.jobs(WS, "hero")] == [first["jobId"]]
    release.set()
    jobs._threads[first["jobId"]].join(10)
    assert jobs.status(WS, first["jobId"])["status"] == "completed"
    # a job whose file says it is running, in a server that has no thread for it
    stale = jobs._store(WS).load(first["jobId"])
    stale.update(status="running", jobId="anim-stale", takes=[{"id": "a", "status": "generating", "seed": 1}])
    jobs._store(WS).save(stale)
    cut = jobs.status(WS, "anim-stale")
    assert cut["status"] == "interrupted" and "restarted" in cut["error"] and cut["takes"][0]["status"] == "waiting"


def test_the_http_routes_start_follow_and_cancel_a_job_and_say_why_they_refuse(world):
    root, server, jobs = world
    app = FastAPI()
    app.include_router(create_character_animation_jobs_router(jobs))
    client = TestClient(app)
    reply = client.post("/api/v1/character-kits/animations/make", json={"workspace": WS, "kitId": "hero", "animation": "cheer"})
    assert reply.status_code == 200 and reply.json()["job"]["status"] == "completed"
    job_id = reply.json()["job"]["jobId"]
    assert client.get(f"/api/v1/character-kits/animations/jobs/{job_id}", params={"workspace": WS}).json()["job"]["result"]["animation"] == "cheer"
    listed = client.get("/api/v1/character-kits/animations/jobs", params={"workspace": WS, "kitId": "hero"}).json()["jobs"]
    assert [item["jobId"] for item in listed] == [job_id] and "reference" not in listed[0] and "definition" not in listed[0]
    assert client.post(f"/api/v1/character-kits/animations/jobs/{job_id}/cancel", json={"workspace": WS}).json()["job"]["status"] == "completed"
    missing = client.post("/api/v1/character-kits/animations/make", json={"workspace": WS, "kitId": "ghost", "animation": "cheer"})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "kit_not_found"
    assert client.post("/api/v1/character-kits/animations/make", json={"workspace": WS, "kitId": "hero", "animation": "nope"}).status_code == 400
    assert client.get("/api/v1/character-kits/animations/jobs/anim-none", params={"workspace": WS}).status_code == 404
    assert client.get("/api/v1/character-kits/animations/jobs/..%2Fx", params={"workspace": WS}).status_code in (400, 404)
