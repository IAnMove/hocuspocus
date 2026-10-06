"""Simulated MCP waits for the game image tool."""
from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from services.game_generators.base import GenContext
from services.game_tools import GameToolError, file_ref, image


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
    workspace.mkdir()
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
