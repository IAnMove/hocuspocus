"""Simulated MCP waits for the game image tool."""
from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from services.game_generators.base import GenContext
from services.game_tools import GameToolError, file_ref, image, model3d


class Fake:
    def __init__(self, waits):
        self.waits = list(waits)
        self.calls = []

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        if tool == "generation.image":
            return {"receipt": {"result": {"job_id": "job-1"}}}
        if tool == "jobs.wait":
            return self.waits.pop(0)
        if tool == "jobs.resume":
            return {"version": 1, "status": "completed", "result": {"status": "queued", "started": True}}
        raise AssertionError(tool)


def _ctx(tmp_path, fake) -> GenContext:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    game = {"id": "bosque", "style": {}, "assets": []}
    asset = {"id": "heroe", "kind": "character", "spec": {}}
    return GenContext(
        workspace="bosque",
        game=game,
        asset=asset,
        attempt_id="a1",
        call=fake,
        loopback=lambda tool, args: {},
        workspace_dir=lambda name: str(workspace),
        cancelled=lambda: False,
        log=lambda message: None,
    )


def test_image_retries_jobs_wait_until_completed(tmp_path):
    fake = Fake([
        {"status": "running", "timed_out": True},
        {"status": "completed", "output_files": ["hero.png"]},
    ])
    found = image(_ctx(tmp_path, fake), "still", prompt="knight", negative="text", resolution="768x1024", seed=7)
    assert found == ["hero.png"]
    waits = [tool for tool, _args in fake.calls if tool == "jobs.wait"]
    assert waits == ["jobs.wait", "jobs.wait"]
    params = fake.calls[0][1]["input"]["params"]
    assert params["priority"] == 10
    assert "priority" not in fake.calls[0][1]


def test_image_resumes_an_interrupted_job_once(tmp_path):
    fake = Fake([
        {"status": "interrupted", "timed_out": True},
        {"status": "completed", "output_files": ["hero.png"]},
    ])
    found = image(_ctx(tmp_path, fake), "still", prompt="knight", negative="text", resolution="768x1024", seed=7)
    assert found == ["hero.png"]
    resumed = [args for tool, args in fake.calls if tool == "jobs.resume"]
    assert resumed == [{"version": 1, "input": {"intent_id": "game-bosque-heroe-a1-still"}}]


def test_empty_output_raises(tmp_path):
    fake = Fake([{"status": "completed", "output_files": []}])
    with pytest.raises(GameToolError) as caught:
        image(_ctx(tmp_path, fake), "still", prompt="knight", negative="text", resolution="768x1024", seed=7)
    assert caught.value.code == "empty_output"


def test_image_provenance_splits_queue_from_gpu_time(tmp_path):
    fake = Fake([{
        "status": "completed",
        "output_files": ["hero.png"],
        "created_at": 1000.0,
        "started_at": 1040.5,
        "finished_at": 1055.5,
        "processing_time_sec": 15.0,
    }])
    ctx = _ctx(tmp_path, fake)
    image(ctx, "still", prompt="knight", negative="text", resolution="768x1024", seed=7, refs=["plate.png"])
    step = ctx.steps[0]
    assert step["queued_seconds"] == 40.5
    assert step["gpu_seconds"] == 15.0
    assert step["num_inference_steps"] == 40
    assert step["resolution"] == "768x1024"
    assert step["refCount"] == 1
    assert "seconds" in step
    bare = Fake([{"status": "completed", "output_files": ["hero.png"]}])
    quiet = _ctx(tmp_path, bare)
    image(quiet, "still", prompt="knight", negative="text", resolution="768x1024", seed=7)
    omitted = quiet.steps[0]
    assert "queued_seconds" not in omitted
    assert "gpu_seconds" not in omitted
    assert omitted["num_inference_steps"] == 40
    assert omitted["refCount"] == 0


def test_resolution_is_rejected_before_submit(tmp_path):
    fake = Fake([])
    with pytest.raises(GameToolError) as caught:
        image(_ctx(tmp_path, fake), "still", prompt="knight", negative="text", resolution="30x64", seed=7)
    assert caught.value.code == "resolution"
    assert fake.calls == []


def test_intent_id_is_stable(tmp_path):
    fake = Fake([
        {"status": "completed", "output_files": ["hero.png"]},
        {"status": "completed", "output_files": ["hero.png"]},
    ])
    context = _ctx(tmp_path, fake)
    image(context, "still", prompt="knight", negative="text", resolution="768x1024", seed=7)
    image(context, "still", prompt="knight", negative="text", resolution="768x1024", seed=7)
    intents = [args["intent_id"] for tool, args in fake.calls if tool == "generation.image"]
    assert intents == ["game-bosque-heroe-a1-still", "game-bosque-heroe-a1-still"]


def test_file_ref_encodes_the_path_and_the_workspace(tmp_path):
    context = _ctx(tmp_path, Fake([]))
    context.workspace = "a+b & c"
    url = file_ref(context, "game/x y/main#1.png")
    parts = urlsplit(url)
    assert parts.path.startswith("/api/v1/file/")
    assert unquote(parts.path[len("/api/v1/file/"):]) == "game/x y/main#1.png"
    assert parse_qs(parts.query) == {"workspace": ["a+b & c"]}
    assert file_ref(context, "/plain.png").startswith("/api/v1/file/plain.png?workspace=")


class _Model3d:
    def __init__(self, submitted, status):
        self.submitted, self.status, self.calls = submitted, status, []

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        return self.submitted if tool == "model3d.generate" else self.status


def test_model3d_sends_seed_and_texture_and_reports_the_real_error(tmp_path):
    failed = {"status": "failed", "message": "Queued Hunyuan3D generation", "error": "Hunyuan3D is not installed"}
    fake = _Model3d({"job_id": "m1"}, failed)
    with pytest.raises(GameToolError) as caught:
        model3d(_ctx(tmp_path, fake), "mesh", image_path="a.png", texture_resolution=512, seed=7)
    sent = fake.calls[0][1]["input"]
    assert (sent["texture_resolution"], sent["seed"]) == (512, 7)
    assert str(caught.value).endswith("Hunyuan3D is not installed")


def test_a_refused_submission_says_why(tmp_path):
    fake = _Model3d({"status": "failed", "error": "workspace not found"}, {})
    with pytest.raises(GameToolError) as caught:
        model3d(_ctx(tmp_path, fake), "mesh", image_path="a.png")
    assert caught.value.code == "rejected" and "workspace not found" in str(caught.value)


def test_video_seed_and_candidate_seeds(tmp_path):
    from services.game_generators.base import relative, seed_for_step
    from services.game_tools import video_fl2va

    asset = {"spec": {"seed": 0}}
    assert [seed_for_step(asset, step) for step in ("clip", "clip-a1", "clip-a3", "mesh-a2")] == [0, 0, 2, 1]

    class Video:
        def __init__(self):
            self.calls = []

        def __call__(self, tool, args):
            self.calls.append((tool, args))
            if tool == "generation.video":
                return {"job_id": "v1"}
            return {"status": "completed", "output_files": ["clip.mp4"]}

    fake = Video()
    ctx = _ctx(tmp_path, fake)
    video_fl2va(ctx, "clip-a2", prompt="run", start="a.png", frames=49, model="h3", resolution="832x480", seed=5)
    assert fake.calls[0][1]["input"]["params"]["seed"] == 5
    nested = tmp_path / "ws" / "game" / "bosque" / "heroe" / "a1" / "a2" / "sheet.png"
    assert relative(ctx, nested) == "game/bosque/heroe/a1/a2/sheet.png"
