"""MiniMax Image-01 chosen like any image model in the full server: catalog, ``POST /api/v1/generate``, ``generation.image``
(HTTP, MCP and the animation job's tool call), with a fake MiniMax and no GPU.

Run alone like the rest of this package: ``python -m pytest tests/characterization -p no:cacheprovider``.
"""
from __future__ import annotations

import base64
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from services import minimax_image_service
from tests.support.fake_wgp import catalog_attributes
from tests.support.pinned_trellis2 import pin_trellis2_runtime

KEY = "test-key-not-real-0123456789"
MODEL = "minimax:image-01"


def _image_bytes(color=(10, 120, 200), fmt="JPEG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buffer, format=fmt)
    return buffer.getvalue()


class FakeMiniMax:
    """Stands in for ``requests.post`` of the MiniMax client; keeps what was sent (never printed)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.gate = None  # a threading.Event the call waits for

    def __call__(self, url, json=None, headers=None, timeout=None):
        if self.gate is not None:
            assert self.gate.wait(10)
        self.calls.append({"url": url, "body": json, "authorization": (headers or {}).get("Authorization")})

        class Response:
            text = ""

            def raise_for_status(self):
                return None

            def json(self):
                return {"data": {"image_base64": [base64.b64encode(_image_bytes()).decode("ascii")]},
                        "base_resp": {"status_code": 0, "status_msg": "success"}}

        return Response()


@pytest.fixture
def minimax(server, monkeypatch):
    """The server with a MiniMax key set and the HTTP call faked."""
    config = server.wgp.server_config
    monkeypatch.setitem(config, "services", {**config.get("services", {}), "minimax_image_api_key": KEY})
    fake = FakeMiniMax()
    monkeypatch.setattr(minimax_image_service.requests, "post", fake)
    # The picture resolver is built with the engine's LoRA folders, which the fake engine does not have.
    monkeypatch.setattr(server.wgp, "get_lora_search_dirs", lambda _model: [], raising=False)
    return fake


@pytest.fixture
def catalog(server, monkeypatch):
    """A fake WanGP catalog (two models); the 3D, rig and H3 weights are never on disk."""
    from services import minimax_h3_service, model3d_service, rig_service

    for name, value in catalog_attributes().items():
        monkeypatch.setattr(server.wgp, name, value, raising=False)
    monkeypatch.setattr(model3d_service, "is_model_downloaded", lambda _model_id: False)
    monkeypatch.setattr(minimax_h3_service, "is_model_downloaded", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(rig_service, "is_unirig_downloaded", lambda: False)
    pin_trellis2_runtime(monkeypatch)
    return server


def _launch():
    return sys.modules["_launch_runtime"]


def _wait(server, job_id: str, seconds: float = 15) -> dict[str, Any]:
    deadline = time.time() + seconds
    status: dict[str, Any] = {}
    while time.time() < deadline:
        response = server.client.get(f"/api/v1/status/{job_id}")
        assert response.status_code == 200, response.text
        status = response.json()
        if status["status"] in {"completed", "failed", "cancelled"}:
            return status
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {status}")


def _upload(server, name: str, color=(200, 40, 40)) -> str:
    folder = Path("uploads")
    folder.mkdir(exist_ok=True)
    (folder / name).write_bytes(_image_bytes(color, "PNG"))
    return f"/api/v1/uploads/{name}"


def _command(intent: str, *, refs=None, version=2, **params) -> dict[str, Any]:
    fields = {"model_type": MODEL, "prompt": "a lantern in the rain", "resolution": "1920x1080", **params}
    if refs:
        fields["image_refs"] = refs
    if version == 1:
        return {"version": 1, "operation": "generation.image", "intent_id": intent, "input": {"workspace": "default", **fields}}
    return {"version": 2, "operation": "generation.image", "intent_id": intent, "input": {"workspace": "default", "params": fields}}


def _assert_no_key(*values: Any) -> None:
    assert KEY not in json.dumps(values, default=str)


# ----- catalog: it is offered where Qwen Turbo is -----

def test_the_catalog_defaults_and_options_offer_minimax_as_a_remote_image_model(catalog):
    server = catalog
    listed = server.client.get("/api/v1/models").json()
    entry = next(model for model in listed["models"] if model["model_type"] == MODEL)
    assert entry["family"] == "minimax" and entry["resource_requirements"]["tier"] == "remote" and entry["is_downloaded"] is True
    assert entry["api_key_set"] is False and entry["supports_ref_images"] is True
    assert {"id": "minimax", "label": "MiniMax (remote API)", "order": 1170} in listed["families"]
    summary = server.client.get("/api/v1/models", params={"detail": "false"}).json()
    assert MODEL in [model["id"] for model in summary["models"]]
    defaults = server.client.get(f"/api/v1/defaults/{MODEL}")
    assert defaults.status_code == 200 and defaults.json()["num_inference_steps"] == 1
    options = server.client.get(f"/api/v1/model-options/{MODEL}")
    assert options.status_code == 200 and options.json()["lock_inference_steps"] is True
    assert server.client.get("/api/v1/defaults/minimax:no-such-model").status_code == 404


def test_the_catalog_says_when_a_key_is_set(catalog, monkeypatch):
    server = catalog
    config = server.wgp.server_config
    monkeypatch.setitem(config, "services", {**config.get("services", {}), "minimax_api_key": KEY})
    entry = next(model for model in server.client.get("/api/v1/models").json()["models"] if model["model_type"] == MODEL)
    assert entry["api_key_set"] is True
    _assert_no_key(entry)


# ----- POST /api/v1/generate -----

def test_generate_runs_minimax_without_a_model_definition_and_without_waiting_for_the_gpu(server, minimax):
    from services.job_lifecycle import register_generation_job, request_cancel

    launch = _launch()
    local_job = {"id": "local-holds-the-gpu-queue", "status": "queued", "params": {"model_type": "fake_t2v"}}
    register_generation_job(launch._gen_lock, local_job)  # a local job ahead in the FIFO that never runs
    try:
        response = server.client.post("/api/v1/generate", json={
            "model_type": MODEL, "prompt": "a lantern in the rain", "resolution": "1280x720", "generation_mode": "image"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "queued" and body["job_id"] and body["task_id"].startswith("task-generation-")
        status = _wait(server, body["job_id"])
    finally:
        request_cancel(local_job)
    assert status["status"] == "completed" and status["progress"] == 100 and len(status["output_files"]) == 1
    assert (server.outputs / status["output_files"][0]).is_file()
    assert minimax.calls[0]["body"]["aspect_ratio"] == "16:9" and "subject_reference" not in minimax.calls[0]["body"]
    assert minimax.calls[0]["authorization"] == f"Bearer {KEY}"
    task = next(item for item in server.client.get("/api/v1/tasks", params={"workspace": "default", "status": "all"}).json()["tasks"]
                if item["backend_job_id"] == body["job_id"])
    assert task["status"] == "completed" and task["provider"] == "minimax" and task["resource_requirements"] == ["remote:https://api.minimax.io"]
    assert "queue_position" not in status or status["queue_position"] is None
    assert "_generation_queue_token" not in launch._jobs[body["job_id"]], "it never entered the local generation queue"
    _assert_no_key(status, task)


def test_generate_without_a_key_is_a_409_that_says_where_the_key_goes_and_makes_no_job(server, monkeypatch):
    config = server.wgp.server_config
    monkeypatch.setitem(config, "services", {key: value for key, value in config.get("services", {}).items() if "minimax" not in key})
    before = len(server.client.get("/api/v1/jobs").json().get("jobs", []))
    response = server.client.post("/api/v1/generate", json={"model_type": MODEL, "prompt": "a lantern"})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "provider_key_missing" and "Settings → Services" in detail["message"] and "minimax_image_api_key" in detail["message"]
    assert len(server.client.get("/api/v1/jobs").json().get("jobs", [])) == before


def test_generate_sends_the_first_picture_as_the_character_and_a_missing_picture_is_a_422(server, minimax):
    hero = _upload(server, "hero.png")
    response = server.client.post("/api/v1/generate", json={
        "model_type": MODEL, "prompt": "the hero waves", "resolution": "1024x1024", "image_refs": [hero]})
    assert response.status_code == 200, response.text
    assert _wait(server, response.json()["job_id"])["status"] == "completed"
    sent = minimax.calls[0]["body"]["subject_reference"][0]
    assert sent["type"] == "character" and base64.b64decode(sent["image_file"].split(",", 1)[1]) == Path("uploads/hero.png").read_bytes()
    missing = server.client.post("/api/v1/generate", json={
        "model_type": MODEL, "prompt": "the hero waves", "image_refs": ["/api/v1/uploads/never.png"]})
    assert missing.status_code == 422 and missing.json()["detail"]["code"] == "invalid_reference"


def test_a_provider_failure_fails_the_job_and_removes_it_from_the_restart_leftovers(server, minimax, monkeypatch):
    class Bad:
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {}, "base_resp": {"status_code": 1002, "status_msg": "rate limit"}}

    monkeypatch.setattr(minimax_image_service.requests, "post", lambda *args, **kwargs: Bad())
    response = server.client.post("/api/v1/generate", json={"model_type": MODEL, "prompt": "a lantern"})
    status = _wait(server, response.json()["job_id"])
    assert status["status"] == "failed" and "rate limit" in status["error"] and status["output_files"] == []
    assert server.client.get("/api/v1/jobs/recovery").json()["jobs"] == []
    _assert_no_key(status)


# ----- generation.image: the UI command (v2), the older command (v1), MCP and the animation job's tool call -----

def test_the_ui_command_admits_minimax_with_a_note_for_every_reference_it_does_not_send(server, minimax):
    hero, other, third = _upload(server, "hero.png"), _upload(server, "other.png", (0, 0, 200)), _upload(server, "third.png", (0, 200, 0))
    command = _command("ui-minimax-1", refs=[hero, other, third], negative_prompt="blurry")
    first = server.client.post("/api/v1/generation/commands", json=command)
    assert first.status_code == 200, first.text
    receipt = first.json()["receipt"]
    assert receipt["operation"] == "generation.image" and receipt["status"] == "queued" and first.json()["replayed"] is False
    assert len(receipt["notes"]) == 3 and "image_refs[1]" in receipt["notes"][0] and "image_refs[2]" in receipt["notes"][1]
    assert "negative prompt" in receipt["notes"][2]
    status = _wait(server, receipt["result"]["job_id"])
    assert status["status"] == "completed" and "image_refs[1]" in status["message"]
    sent = minimax.calls[0]["body"]["subject_reference"]
    assert len(sent) == 1 and base64.b64decode(sent[0]["image_file"].split(",", 1)[1]) == Path("uploads/hero.png").read_bytes()
    replay = server.client.post("/api/v1/generation/commands", json=command)
    assert replay.status_code == 200 and replay.json()["replayed"] is True and replay.json()["receipt"]["notes"] == receipt["notes"]
    assert len(minimax.calls) == 1, "a replay does not call MiniMax again"
    conflict = server.client.post("/api/v1/generation/commands", json=_command("ui-minimax-1", refs=[hero], prompt="another"))
    assert conflict.status_code == 409
    viewed = server.client.get("/api/v1/generation/commands/receipt", params={"workspace": "default", "intent_id": "ui-minimax-1"}).json()
    assert viewed["receipt"]["notes"] == receipt["notes"] and viewed["task"]["status"] == "completed"
    _assert_no_key(receipt, status, viewed)


def test_the_commands_may_leave_out_steps_guidance_and_seed_and_both_versions_work(server, minimax):
    for version in (1, 2):
        response = server.client.post("/api/v1/generation/commands", json=_command(f"omit-{version}", version=version))
        assert response.status_code == 200, response.text
        assert _wait(server, response.json()["receipt"]["result"]["job_id"])["status"] == "completed"
    assert len(minimax.calls) == 2


def test_a_command_without_a_key_is_refused_before_it_is_admitted(server, monkeypatch):
    config = server.wgp.server_config
    monkeypatch.setitem(config, "services", {key: value for key, value in config.get("services", {}).items() if "minimax" not in key})
    response = server.client.post("/api/v1/generation/commands", json=_command("no-key-1"))
    assert response.status_code == 409 and response.json()["detail"]["code"] == "provider_key_missing"
    receipt = server.client.get("/api/v1/generation/commands/receipt", params={"workspace": "default", "intent_id": "no-key-1"})
    assert receipt.status_code == 404, "nothing was admitted, so the same intention can be sent again once the key is set"


def test_the_mcp_door_and_the_animation_jobs_tool_call_use_the_same_operation(server, minimax):
    from services.local_generation import LocalTools

    launch = _launch()
    # An MCP tool takes the envelope without its operation name: the tool's own name is the operation.
    arguments = {key: value for key, value in _command("mcp-minimax-1").items() if key != "operation"}
    reply = launch._local_mcp.call("generation.image", arguments)
    assert reply["receipt"]["operation"] == "generation.image" and reply["receipt"]["result"]["job_id"]
    assert _wait(server, reply["receipt"]["result"]["job_id"])["status"] == "completed"
    tools = LocalTools(launch._local_mcp.call, "default", str(server.outputs))
    name = tools.image("anim-pose-1", {"model_type": MODEL, "prompt": "a pose", "resolution": "1024x1024",
                                       "num_inference_steps": 4, "guidance_scale": 1, "seed": 1}, "hero-walk-pose1")
    assert name.endswith(".jpg") and (server.outputs / name).is_file()
    assert len(minimax.calls) == 2


def test_cancelling_a_running_minimax_job_ends_it_cancelled_and_leaves_no_picture(server, minimax):
    import threading

    minimax.gate = threading.Event()
    response = server.client.post("/api/v1/generate", json={"model_type": MODEL, "prompt": "a lantern"})
    job_id = response.json()["job_id"]
    deadline = time.time() + 10
    while time.time() < deadline and server.client.get(f"/api/v1/status/{job_id}").json()["status"] != "running":
        time.sleep(0.05)
    cancelled = server.client.post(f"/api/v1/cancel/{job_id}")
    assert cancelled.status_code == 200, cancelled.text
    minimax.gate.set()
    status = _wait(server, job_id)
    assert status["status"] == "cancelled" and status["output_files"] == []
    assert [path.name for path in server.outputs.iterdir() if path.suffix in {".jpg", ".png"}] == []
