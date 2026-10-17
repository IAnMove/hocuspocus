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
from services.character_animations import MAX_ANIMATIONS
from services.character_animation_job import AnimationJobDeps, AnimationJobError, CharacterAnimationJobs, reference_of
from services.character_kit_library import patch_character_kit, read_character_kit_library, write_character_kit_library
from services.local_generation import LocalTools, ToolError, payload_of
from services.local_mcp import LocalMcp
from services.studio_key import command_handlers as studio_key_handlers

WS = "demo"


def _picture(path: Path, *, keyed: bool, shift: int = 0) -> None:
    pixels = np.zeros((200, 140, 4), dtype=np.uint8) if keyed else np.full((200, 140, 4), (0, 255, 0, 255), dtype=np.uint8)
    pixels[10:40, 45 + shift:75 + shift] = (200, 160, 120, 255)
    pixels[40:110, 38 + shift:82 + shift] = (230, 180, 30, 255)
    pixels[110:200, 50 + shift:62 + shift] = (60, 60, 70, 255)
    Image.fromarray(pixels).save(path)


def _spoil(path: Path, how: str) -> None:
    """A keyed pose gone wrong: the figure at half the size of the others, or the key left the whole picture opaque."""
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    if how == "small":
        small = image.resize((image.width // 2, image.height // 2), Image.Resampling.NEAREST)
        image = Image.new("RGBA", image.size, (0, 0, 0, 0))
        image.paste(small, (35, 100))
    else:
        image = Image.fromarray(np.full((image.height, image.width, 4), (200, 160, 120, 255), dtype=np.uint8))
    image.save(path)


class FakeServer:
    """What the job calls through ``LocalMcp.call``. ``refuse`` names pose ids whose picture fails."""

    def __init__(self, root: Path) -> None:
        self.root, self.calls, self.refuse, self.during = root, [], set(), None
        self.spoil = {}  # n-th key (1-based) -> "small" (a pose drawn at half the size) | "box" (a key that left a whole rectangle)

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
            if self.spoil.get(len(self.of("studio.key"))):
                _spoil(self.root / name, self.spoil[len(self.of("studio.key"))])
            # The shape the real handler answers (services/studio_key.py ``command_handlers``): an operation envelope that is itself
            # "completed", with the keyed file inside ``result``.
            return {"version": 1, "status": "completed", "operation": "studio.key", "result": {
                "file": name, "url": f"/api/v1/file/{name}?workspace={WS}", "sha256": "0" * 64, "frames": 1, "report": {"transparentShare": 0.77}}}
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


def test_a_kit_at_the_animation_limit_refuses_a_new_animation_before_any_gpu_work(world, monkeypatch):
    root, server, jobs = world
    full = {**_kit(root), "animations": {f"a{index}": {} for index in range(MAX_ANIMATIONS)}}
    monkeypatch.setattr(jobs, "_kit", lambda workspace, kit_id: full)
    with pytest.raises(AnimationJobError) as error:
        jobs.start(WS, "hero", "wave")
    assert error.value.code == "animation_limit" and not server.calls, "the limit is checked before any picture is asked for"
    full["animations"]["wave"] = {"reviewState": "pending"}
    assert jobs._definition(full, "wave", None, None)["id"] == "wave", "an animation the kit already has may be made again"


def test_a_wait_http_error_is_not_a_live_job_and_does_not_hang(world):
    """LocalMcp puts the HTTP status on error.status. Treating that as a generation status used to wait forever."""
    root, server, jobs = world
    original = server.call

    def call(tool, arguments):
        if tool == "jobs.wait":
            server.calls.append((tool, arguments))
            assert len(server.of("jobs.wait")) < 5, "polled again and again after an HTTP error"
            return {"_is_error": True, "error": {"code": "invalid_status", "message": "Status payload must be an object.", "status": 502}}
        return original(tool, arguments)

    jobs.deps.call = call
    failed = jobs.start(WS, "hero", "nod")
    assert failed["status"] == "failed" and failed["errorCode"] == "invalid_status"
    assert "Status payload" in failed["error"]
    assert [take["status"] for take in failed["takes"]][0] == "failed"
    assert len(server.of("jobs.wait")) == 1, "one wait error stops the pose; it does not poll again"


def test_a_wait_that_times_out_with_the_live_job_is_asked_again(world):
    root, server, jobs = world
    original = server.call
    waits = {"n": 0}

    def call(tool, arguments):
        if tool == "jobs.wait":
            waits["n"] += 1
            if waits["n"] == 1:
                return {"status": "running", "job_id": "gen-1", "timed_out": True, "code": "timeout"}
        return original(tool, arguments)

    jobs.deps.call = call
    assert jobs.start(WS, "hero", "nod")["status"] == "completed"
    assert waits["n"] >= 2


def test_a_wait_with_no_status_at_all_is_an_error_not_a_busy_loop(world):
    root, server, jobs = world
    original = server.call

    def call(tool, arguments):
        if tool == "jobs.wait":
            server.calls.append((tool, arguments))
            assert len(server.of("jobs.wait")) < 5, "polled again and again with no status"
            return {"result": {"job_id": "gen-1"}}
        return original(tool, arguments)

    jobs.deps.call = call
    failed = jobs.start(WS, "hero", "nod")
    assert failed["status"] == "failed" and failed["errorCode"] == "no_status"
    assert len(server.of("jobs.wait")) == 1


def test_payload_of_does_not_treat_an_http_error_status_as_a_running_job():
    with pytest.raises(ToolError) as error:
        payload_of({"_is_error": True, "error": {"code": "invalid_status", "message": "Status payload must be an object.", "status": 502}})
    assert error.value.code == "invalid_status"
    live = payload_of({"status": "running", "job_id": "gen-1", "timed_out": True})
    assert live["status"] == "running" and live["timed_out"] is True
    assert payload_of({"result": {"url": "/api/v1/file/a.png", "file": "a.png"}}) == {"url": "/api/v1/file/a.png", "file": "a.png"}
    # The old timeout envelope still names the job.
    assert payload_of({"_is_error": True, "error": {"job_id": "gen-1", "status": "running", "timed_out": True}})["job_id"] == "gen-1"


def test_the_real_studio_key_reply_is_read_as_the_keyed_file(world):
    """Sol 2026-10-15: ``characters.animation.make`` failed with ``studio.key returned no file`` although the key had been written.
    The real ``studio.key`` answers an operation envelope whose own ``status`` is "completed"; reading it as a finished generation job
    hid the file inside ``result``. This one runs the real handler through the real ``LocalMcp``, not a fake reply."""
    root, _server, _jobs = world
    _picture(root / "pose.png", keyed=False)
    mcp = LocalMcp(lambda: studio_key_handlers(lambda workspace: str(root), lambda: str(root / "uploads"), find_model=lambda: None))
    reply = mcp.call("studio.key", {"version": 1, "intent_id": "k-1", "input": {"workspace": WS, "source": "pose.png", "mode": "green"}})
    assert reply["status"] == "completed" and reply["result"]["file"] == "pose-key.png"  # the envelope that used to win
    keyed = LocalTools(mcp.call, WS, str(root)).key("k-2", "pose.png", "green")
    assert keyed.startswith("/api/v1/file/") and "pose-key" in keyed
    # An intent that is asked again answers the stored result, flagged as replayed: still the keyed file.
    again = LocalTools(mcp.call, WS, str(root)).key("k-1", "pose.png", "green")
    assert again == reply["result"]["url"]


def test_a_picture_the_server_could_not_start_is_discarded_from_the_queue_and_the_job_says_to_try_again(world):
    root, server, jobs = world
    original = server.call

    def call(tool, arguments):
        if tool == "generation.image" and arguments["input"]["output_name"].find("-passing-") >= 0:
            server.calls.append((tool, arguments))
            return {"_is_error": True, "error": {"code": "dispatch_uncertain", "status": 503, "message": "Admission is durable; inspect its task before explicitly recovering"}}
        return original(tool, arguments)

    jobs.deps.call = call
    failed = jobs.start(WS, "hero", "walk")
    assert failed["status"] == "failed" and failed["errorCode"] == "dispatch_uncertain" and "GPU may be busy" in failed["error"]
    assert "Admission" not in failed["error"] and [take["status"] for take in failed["takes"]][:2] == ["ready", "failed"]
    discarded = server.of("jobs.discard")
    assert len(discarded) == 1 and discarded[0]["intent_id"].startswith(failed["jobId"]) and discarded[0]["intent_id"].endswith("-passing-image")
    jobs.deps.call = original
    retry = jobs.start(WS, "hero", "walk")
    assert retry["status"] == "completed" and retry["takes"][0]["status"] == "reused", "the pose that was made is kept"


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


def test_a_live_animation_job_is_visible_to_the_workspace_busy_probe_and_a_stale_one_is_not(world):
    root, server, jobs = world
    release = threading.Event()
    server.during = lambda: release.wait(10)
    jobs.deps.inline = False
    job = jobs.start(WS, "hero", "wave")
    try:
        live = jobs.live_jobs(str(root))
        assert len(live) == 1 and live[0]["jobId"] == job["jobId"] and live[0]["workspace"] == WS
        assert live[0]["status"] in ("queued", "running")
        stale = jobs._store(WS).load(job["jobId"])
        stale.update(status="running", jobId="anim-stale")
        jobs._store(WS).save(stale)
        assert all(item["jobId"] != "anim-stale" for item in jobs.live_jobs(str(root)))
        assert jobs._store(WS).load("anim-stale")["status"] == "running", "the probe does not reconcile"
    finally:
        release.set()
        jobs._threads[job["jobId"]].join(10)


def test_the_http_routes_start_follow_and_cancel_a_job_and_say_why_they_refuse(world):
    root, server, jobs = world
    app = FastAPI()
    app.include_router(create_character_animation_jobs_router(jobs), prefix="/api/v1/character-kits")
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


# ----- «Modo un solo disparo» (services/agent_autonomy.py): the agent's review and the job's autoApprove -----

ONE_SHOT = {"agent_autonomy": "one_shot"}


def _mode(jobs, services):
    jobs.deps.services = lambda: services


def test_the_autonomy_setting_is_review_unless_it_says_one_shot():
    from services import agent_autonomy
    assert agent_autonomy.autonomy_of({}) == agent_autonomy.autonomy_of(None) == "review"
    assert agent_autonomy.autonomy_of({"agent_autonomy": "one_shot"}) == "one_shot" and agent_autonomy.autonomy_of({"agent_autonomy": " One_Shot "}) == "one_shot"
    for bad in ("always", "", None, True, 1, ["one_shot"], "one-shot"):
        assert agent_autonomy.autonomy_of({"agent_autonomy": bad}) == "review", bad
    assert agent_autonomy.is_one_shot(ONE_SHOT) and not agent_autonomy.is_one_shot({"agent_autonomy": "review"})


def test_the_services_config_stores_and_returns_the_autonomy_and_anything_else_is_review(monkeypatch):
    from types import SimpleNamespace
    from routers import settings
    wgp = SimpleNamespace(server_config={"services": {}})
    monkeypatch.setattr(settings.settings_store, "wgp", None, raising=False)
    router = settings.create_settings_services_router(
        wgp=wgp, _save_server_config=lambda: None, _effective_llm_routing=lambda services: ("minimax", "m", ""),
        _active_production_profile=lambda: {}, _normalize_production_profile=lambda profile: profile, _PRODUCTION_PROFILE_CONFIG_KEY="profile")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/v1/services-config").json()["agent_autonomy"] == "review", "the default: a person approves"
    assert client.put("/api/v1/services-config", json={"agent_autonomy": "one_shot"}).json()["updated"] == {"agent_autonomy": "one_shot"}
    assert wgp.server_config["services"]["agent_autonomy"] == "one_shot" and client.get("/api/v1/services-config").json()["agent_autonomy"] == "one_shot"
    assert client.put("/api/v1/services-config", json={"agent_autonomy": "yolo"}).json()["updated"] == {"agent_autonomy": "review"}
    assert wgp.server_config["services"]["agent_autonomy"] == "review"


def test_the_core_server_keeps_the_autonomy_too(monkeypatch):
    from services import core_workspace
    store = {"services": {}}
    monkeypatch.setattr(core_workspace, "load_config", lambda: store)
    monkeypatch.setattr(core_workspace, "save_config", lambda data: None)
    assert core_workspace.services_config()["agent_autonomy"] == "review"
    assert core_workspace.merge_services({"agent_autonomy": "one_shot"})["agent_autonomy"] == "one_shot"
    assert core_workspace.merge_services({"agent_autonomy": "whatever"})["agent_autonomy"] == "review"


def _made(world, animation="walk"):
    root, server, jobs = world
    return root, server, jobs, jobs.start(WS, "hero", animation)


def test_in_review_mode_an_agent_cannot_review_and_the_animation_stays_pending(world):
    from services.character_animation_review import AnimationReviewError, review_kit_animation
    root, server, jobs, _job = _made(world)
    for services in (None, {}, {"agent_autonomy": "review"}, {"agent_autonomy": "bogus"}):
        with pytest.raises(AnimationReviewError) as error:
            review_kit_animation(str(root), "hero", "walk", "approve", "looks fine", "agent", services=services)
        assert error.value.code == "agent_review_off" and error.value.status == 403
        assert "Personajes › Animaciones" in str(error.value) and "modo un solo disparo" in str(error.value)
    made = _kit(root)["animations"]["walk"]
    assert made["reviewState"] == "pending" and "reviewedBy" not in made


def test_in_one_shot_an_agent_approves_with_who_and_why_and_a_person_can_revert_it(world):
    from services.character_animation_review import review_kit_animation
    root, server, jobs, _job = _made(world)
    done = review_kit_animation(str(root), "hero", "walk", "approve", "same character, one size", "agent", services=ONE_SHOT)
    assert done["reviewState"] == "approved" and done["reviewedBy"] == "agent"
    made = _kit(root)["animations"]["walk"]
    assert (made["reviewState"], made["reviewedBy"], made["reviewNote"]) == ("approved", "agent", "same character, one size") and made["reviewedAt"].endswith("Z")
    assert made["sheet"] and len(made["frames"]) == 4, "a review touches no picture"
    assert _kit(root)["provenance"][-1] == {"method": "character-animation-review", "animation": "walk", "decision": "approve", "by": "agent"}
    # What the panel does when a person rejects it: the kit is saved with the person's review, and the agent's note goes.
    person = review_kit_animation(str(root), "hero", "walk", "reject", actor="person", services={})
    assert person["reviewedBy"] == "person"
    reverted = _kit(root)["animations"]["walk"]
    assert reverted["reviewState"] == "rejected" and reverted["reviewedBy"] == "person" and "reviewNote" not in reverted


def test_an_agent_cannot_overturn_what_a_person_decided_nor_review_what_does_not_exist(world):
    from services.character_animation_review import AnimationReviewError, review_kit_animation
    root, server, jobs, _job = _made(world)
    review_kit_animation(str(root), "hero", "walk", "approve", actor="person")
    with pytest.raises(AnimationReviewError) as error:
        review_kit_animation(str(root), "hero", "walk", "reject", "no", "agent", services=ONE_SHOT)
    assert error.value.code == "person_decided" and _kit(root)["animations"]["walk"]["reviewState"] == "approved"
    # An approval saved before the reviewer was recorded is a person's too.
    library = read_character_kit_library(str(root))
    old = {key: value for key, value in _kit(root)["animations"]["walk"].items() if key not in {"reviewedBy", "reviewedAt", "reviewNote"}}
    patch_character_kit(str(root), "hero", {**_kit(root), "animations": {"walk": old}}, base_revision=library["revision"], make_active=False)
    with pytest.raises(AnimationReviewError) as error:
        review_kit_animation(str(root), "hero", "walk", "reject", "", "agent", services=ONE_SHOT)
    assert error.value.code == "person_decided"
    for args, code, status in ((("ghost", "walk", "approve"), "kit_not_found", 404), (("hero", "wave", "approve"), "animation_not_found", 404),
                               (("hero", "walk", "maybe"), "invalid_decision", 400)):
        with pytest.raises(AnimationReviewError) as error:
            review_kit_animation(str(root), *args, actor="person")
        assert (error.value.code, error.value.status) == (code, status)
    with pytest.raises(AnimationReviewError) as error:
        review_kit_animation(str(root), "hero", "walk", "approve", "x" * 501, "person")
    assert error.value.code == "note_too_long"


def test_kit_data_from_before_the_reviewer_was_recorded_stays_valid_and_a_review_keeps_the_rest(world):
    root, server, jobs, _job = _made(world)
    made = _kit(root)["animations"]["walk"]
    assert not {"reviewedBy", "reviewNote", "reviewedAt"} & set(made), "a job never records a reviewer"
    library = read_character_kit_library(str(root))
    saved = patch_character_kit(str(root), "hero", {**_kit(root), "animations": {"walk": {**made, "reviewState": "approved"}}}, base_revision=library["revision"],
                                make_active=False)
    assert saved["kits"]["hero"]["animations"]["walk"]["reviewState"] == "approved" and "reviewedBy" not in saved["kits"]["hero"]["animations"]["walk"]


def test_a_rejected_animation_keeps_its_poses_for_a_remake(world):
    from services.character_animation_review import review_kit_animation
    root, server, jobs, _job = _made(world, "wave")
    before = {frame["id"]: frame["source"] for frame in _kit(root)["animations"]["wave"]["frames"]}
    review_kit_animation(str(root), "hero", "wave", "reject", "the hand is missing", "agent", services=ONE_SHOT)
    rejected = _kit(root)["animations"]["wave"]
    assert rejected["reviewState"] == "rejected" and {frame["id"]: frame["source"] for frame in rejected["frames"]} == before
    pose = next(iter(before))
    server.calls = []
    again = jobs.start(WS, "hero", "wave", pose=pose)
    assert again["status"] == "completed" and len(server.of("generation.image")) == 1, "only the pose asked for is made again"
    remade = _kit(root)["animations"]["wave"]
    assert remade["reviewState"] == "pending" and "reviewedBy" not in remade, "a remade animation is reviewed again"
    assert {key: value for key, value in {frame["id"]: frame["source"] for frame in remade["frames"]}.items() if key != pose} == {key: value for key, value in before.items() if key != pose}


def test_auto_approve_approves_a_good_sheet_in_one_shot_and_reports_the_checks(world):
    root, server, jobs = world
    _mode(jobs, ONE_SHOT)
    job = jobs.start(WS, "hero", "walk", auto_approve=True)
    assert job["status"] == "completed" and job["autoApprove"] is True and job["autoApproved"] is True
    assert job["result"]["autoApproved"] is True and job["result"]["reviewState"] == "approved"
    names = [check["id"] for check in job["checks"]]
    assert names == ["cell_count", "cell_size", "filled_cells", "clean_alpha", "silhouette", "ground_line", "scale_spread", "scale_measure"]
    assert all(check["ok"] for check in job["checks"]), job["checks"]
    made = _kit(root)["animations"]["walk"]
    assert made["reviewState"] == "approved" and made["reviewedBy"] == "agent" and made["reviewNote"].startswith("Automatic checks passed (8)")
    assert jobs.status(WS, job["jobId"])["checks"] == job["checks"], "the job store reports them too"


def test_auto_approve_leaves_a_bad_sheet_pending_with_the_failed_checks(world):
    root, server, jobs = world
    _mode(jobs, ONE_SHOT)
    server.spoil = {3: "small"}
    small = jobs.start(WS, "hero", "walk", auto_approve=True)
    assert small["status"] == "completed" and small["autoApproved"] is False
    assert [check["id"] for check in small["checks"] if not check["ok"]] == ["scale_spread"]
    assert next(check for check in small["checks"] if check["id"] == "scale_spread")["value"] < 0.80
    made = _kit(root)["animations"]["walk"]
    assert made["reviewState"] == "pending" and "reviewedBy" not in made and small["result"]["reviewState"] == "pending"
    assert small["reviewNote"].startswith("Automatic checks failed: scale_spread")
    server.spoil, server.calls = {2: "box"}, []
    box = jobs.start(WS, "hero", "walk", auto_approve=True)
    assert box["autoApproved"] is False and "silhouette" in [check["id"] for check in box["checks"] if not check["ok"]]
    assert _kit(root)["animations"]["walk"]["reviewState"] == "pending"


def test_auto_approve_is_ignored_with_a_note_in_review_mode_and_never_by_default(world):
    root, server, jobs = world
    for services in (None, {"agent_autonomy": "review"}):
        _mode(jobs, services)
        job = jobs.start(WS, "hero", "wave", auto_approve=True)
        assert job["status"] == "completed" and job["autoApprove"] is False and "agent_autonomy is review" in job["autoApproveNote"]
        assert "autoApproved" not in job and "checks" not in job
        assert _kit(root)["animations"]["wave"]["reviewState"] == "pending"
    _mode(jobs, ONE_SHOT)
    plain = jobs.start(WS, "hero", "wave")
    assert "autoApprove" not in plain and _kit(root)["animations"]["wave"]["reviewState"] == "pending", "approval is asked for, never assumed"


def test_a_mode_switched_off_while_the_poses_are_made_leaves_the_animation_for_a_person(world):
    root, server, jobs = world
    state = dict(ONE_SHOT)
    jobs.deps.services = lambda: state
    server.during = lambda: state.update(agent_autonomy="review") if len(server.of("studio.key")) == 3 else None
    job = jobs.start(WS, "hero", "walk", auto_approve=True)
    assert job["autoApprove"] is True and job["autoApproved"] is False
    assert _kit(root)["animations"]["walk"]["reviewState"] == "pending" and job["reviewNote"].startswith("Agent review is off")


def test_the_review_route_answers_403_in_review_mode_and_approves_in_one_shot(world):
    from routers.character_animation_review import create_character_animation_review_router
    root, server, jobs = world
    config = {}
    app = FastAPI()
    app.include_router(create_character_animation_review_router(workspace_dir=lambda workspace: str(root), services=lambda: config), prefix="/api/v1/character-kits")
    jobs.start(WS, "hero", "walk")
    client = TestClient(app)
    body = {"workspace": WS, "kitId": "hero", "animation": "walk", "decision": "approve", "note": "ok"}
    refused = client.post("/api/v1/character-kits/animations/review", json=body)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "agent_review_off" and "Personajes › Animaciones" in refused.json()["detail"]["message"]
    assert _kit(root)["animations"]["walk"]["reviewState"] == "pending"
    config.update(ONE_SHOT)
    approved = client.post("/api/v1/character-kits/animations/review", json=body)
    assert approved.status_code == 200 and approved.json()["review"]["reviewedBy"] == "agent" and _kit(root)["animations"]["walk"]["reviewedBy"] == "agent"
    assert client.post("/api/v1/character-kits/animations/review", json={**body, "decision": "maybe"}).status_code == 422
    assert client.post("/api/v1/character-kits/animations/review", json={**body, "actor": "person"}).status_code == 422, "the route has no way to claim to be a person"
    assert client.post("/api/v1/character-kits/animations/review", json={**body, "animation": "wave"}).json()["detail"]["code"] == "animation_not_found"


def test_the_make_route_passes_auto_approve_and_the_review_route_and_the_job_share_one_function(world, monkeypatch):
    import routers.character_animation_review as review_router
    import services.character_animation_job as job_module
    import services.character_animation_review as review_module
    assert review_router.review_kit_animation is review_module.review_kit_animation is job_module.review_kit_animation
    root, server, jobs = world
    _mode(jobs, ONE_SHOT)
    app = FastAPI()
    app.include_router(create_character_animation_jobs_router(jobs), prefix="/api/v1/character-kits")
    calls = []
    original = review_module.review_kit_animation
    monkeypatch.setattr(job_module, "review_kit_animation", lambda *args, **kwargs: calls.append((args, kwargs)) or original(*args, **kwargs))
    reply = TestClient(app).post("/api/v1/character-kits/animations/make", json={"workspace": WS, "kitId": "hero", "animation": "walk", "autoApprove": True})
    assert reply.json()["job"]["autoApproved"] is True
    assert len(calls) == 1 and calls[0][0][3:6] == ("approve", calls[0][0][4], "agent"), "the job's approval is the agent's review, through the shared function"
