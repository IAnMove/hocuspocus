"""Shared video admission, HTTP/MCP replay and receipt recovery without a provider."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from routers.image_generation_commands import (
    create_image_generation_commands_router,
    image_command_catalog,
    image_command_handlers,
)
from routers.wangp_mcp import create_wangp_mcp_router
from services.video_generation_commands import create_video_operation
from services.video_generation_spec import freeze_video_generation_spec
from tests.test_image_generation_commands import FakeNative, _command as image_command, _db_counts, _mcp_call, _run


T2V_DEFINITION = {
    "architecture": "t2v_1.3B",
    "image_outputs": False,
    "audio_only": False,
    "frames_minimum": 5,
    "frames_steps": 4,
    "guidance_max_phases": 3,
    "inference_steps_min": 1,
    "inference_steps_max": 100,
    "sample_solvers": [("unipc", "unipc"), ("euler", "euler")],
}


def video_command(intent="video-test-intent", **params):
    native = {
        "model_type": "t2v_1.3B",
        "prompt": '  A lantern over wet cobblestones.\n"Mañana"  ',
        "resolution": "832x480",
        "video_length": 81,
        "num_inference_steps": 30,
        "guidance_scale": 5.0,
        "seed": 42,
        "negative_prompt": " blur ",
        "generation_mode": "video",
        "image_mode": 0,
    }
    native.update(params)
    return {
        "version": 2,
        "operation": "generation.video",
        "intent_id": intent,
        "input": {"workspace": "video-test", "params": native},
    }


class RecordingResources:
    def __init__(self, *, media=None, error=None):
        self.media = media
        self.error = error
        self.media_calls = []

    def prepare_media(self, params):
        self.media_calls.append(deepcopy(params))
        if self.error is not None:
            raise self.error
        if self.media is not None:
            prepared, identities = self.media
            return deepcopy(prepared), deepcopy(identities)
        return deepcopy(params), []

    def prepare_loras(self, params, definition):
        del params, definition
        return []


def configured_service(native, tmp_path, resources=None, downloaded=True):
    service = native.service()
    native_prepare = service.prepare
    resources = resources or RecordingResources()

    async def prepare_request(request):
        assert request.prepared_studio_video is True
        return await native_prepare(request)

    runtime = {
        "wgp": SimpleNamespace(get_model_def=lambda model: deepcopy(T2V_DEFINITION) if model in {"t2v", "t2v_1.3B"} else None),
        "_check_model_downloaded": lambda _model: downloaded,
    }
    service.prepare = prepare_request
    service.runtime_defaults = lambda: {"model_type": "wrong-image-model", "prompt": "global residue"}
    service.operations["generation.video"] = create_video_operation(
        runtime, resources=lambda: resources, execution_policy=lambda _workspace: None,
    )
    return service, resources


def _video_app(service, tmp_path):
    app = FastAPI()
    app.include_router(create_image_generation_commands_router(service))
    app.include_router(create_wangp_mcp_router(
        handlers=image_command_handlers(service),
        command_operations=image_command_catalog(
            [service.operations["generation.video"].catalog],
        ),
        journal_path=tmp_path / "mcp-journal.sqlite",
        token_getter=lambda: "test-token",
    ))
    return TestClient(app)


def test_http_and_mcp_share_literal_video_admission(tmp_path):
    native = FakeNative(tmp_path)
    service, _ = configured_service(native, tmp_path)
    command = video_command()
    with _video_app(service, tmp_path) as client:
        first = client.post(
            "/api/v1/generation/commands",
            json=command,
            headers={"X-Hocus-UI-Surface": "wizard"},
        )
        assert first.status_code == 200, first.text
        catalog = client.get("/api/v1/generation/commands").json()
        listed = client.post(
            "/api/v1/wangp/mcp",
            headers={"Authorization": "Bearer test-token"},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ).json()["result"]["tools"]
    names = {operation["name"] for operation in catalog["operations"]}
    assert {"generation.image", "generation.video", "generation.receipt"} <= names
    video_tool = next(tool for tool in listed if tool["name"] == "generation.video")
    assert "operation" not in video_tool["inputSchema"]["properties"]
    generate_tool = next(tool for tool in listed if tool["name"] == "generate")
    assert "video" in generate_tool["inputSchema"]["properties"]["params"]["properties"]["generation_mode"]["enum"]

    mcp_arguments = {key: value for key, value in command.items() if key != "operation"}
    replay = _run(image_command_handlers(service)["generation.video"](mcp_arguments))
    receipt = first.json()["receipt"]
    assert replay == {"receipt": receipt, "replayed": True}
    assert receipt["operation"] == "generation.video"
    assert len(native.dispatch_calls) == 1
    job = native.dispatch_calls[0]
    assert job["params"]["prompt"] == command["input"]["params"]["prompt"]
    assert job["params"]["model_type"] == "t2v_1.3B"
    assert job["params"]["generation_mode"] == "video"
    assert job["params"]["image_mode"] == 0
    assert job["params"]["multi_prompts_gen_type"] == 2
    assert job["params"]["sliding_window_size"] == command["input"]["params"]["video_length"]
    assert "wrong-image-model" not in job["params"].values()
    entry = native.registry("video-test").command_admission(command["intent_id"])
    assert entry["original"] == command
    assert entry["effective"]["runtime"]["params"]["prompt"] == command["input"]["params"]["prompt"]
    assert entry["effective"]["runtime"]["provenance"]["capability"] == "generation.video"
    assert entry["effective"]["runtime"]["provenance"]["actor"] == "wizard"


def test_wizard_and_mcp_effective_requests_match(tmp_path):
    native = FakeNative(tmp_path)
    service, _ = configured_service(native, tmp_path)
    command = video_command()
    wizard = _run(service.submit(command, trusted_tool="wizard"))
    mcp_arguments = {key: value for key, value in command.items() if key != "operation"}
    mcp = _run(image_command_handlers(service)["generation.video"](mcp_arguments))
    assert mcp["receipt"] == wizard["receipt"]
    frozen = freeze_video_generation_spec(command)
    entry = native.registry("video-test").command_admission(command["intent_id"])
    assert entry["effective"]["input"] == frozen["effective"]["input"]
    assert entry["digest"] == frozen["fingerprint"]
    assert len(native.dispatch_calls) == 1


def test_same_intent_replays_and_new_intent_creates_another_generation(tmp_path):
    native = FakeNative(tmp_path)
    service, _ = configured_service(native, tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda _: _run(service.submit(video_command())), range(6)))
    assert all(reply["receipt"] == replies[0]["receipt"] for reply in replies)
    assert len(native.dispatch_calls) == 1
    second = _run(service.submit(video_command("another-deliberate-video")))
    assert second["receipt"]["taskIds"] != replies[0]["receipt"]["taskIds"]
    assert _db_counts(native.registry("video-test"))["tasks"] == 2
    changed = video_command()
    changed["input"]["params"]["prompt"] += " extra"
    with pytest.raises(HTTPException) as conflict:
        _run(service.submit(changed))
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException) as domain:
        _run(service.submit(image_command("video-test-intent", workspace="video-test")))
    assert domain.value.status_code == 409


def test_parameter_rejection_and_missing_model_add_no_tasks(tmp_path):
    native = FakeNative(tmp_path)
    service, _ = configured_service(native, tmp_path)
    invalid = video_command("bad-params")
    invalid["input"]["params"]["model_type"] = "t2v_2_2"
    with pytest.raises(HTTPException) as rejected:
        _run(service.submit(invalid))
    assert rejected.value.status_code == 422
    assert native.registry("video-test").command_admission("bad-params") is None
    assert _db_counts(native.registry("video-test"))["tasks"] == 0

    missing_native = FakeNative(tmp_path)
    missing, _ = configured_service(missing_native, tmp_path, downloaded=False)
    with pytest.raises(HTTPException) as unavailable:
        _run(missing.submit(video_command("missing-model")))
    assert unavailable.value.status_code == 409
    assert missing_native.registry("video-test").command_admission("missing-model") is None
    assert missing_native.dispatch_calls == []


def test_cross_workspace_reference_adds_no_tasks(tmp_path):
    native = FakeNative(tmp_path)
    resources = RecordingResources(error=ValueError("The reference must name its actual source workspace"))
    service, _ = configured_service(native, tmp_path, resources=resources)
    request = video_command("foreign-ref", image_start="/api/v1/file/frame.png?workspace=source")
    with pytest.raises(HTTPException) as rejected:
        _run(service.submit(request))
    assert rejected.value.status_code == 422
    assert native.registry("video-test").command_admission("foreign-ref") is None
    assert native.dispatch_calls == []
    assert resources.media_calls


def test_prepare_pins_literal_prompt_and_single_window(tmp_path):
    from services.studio_video_preparation import prepare_studio_video

    resources = RecordingResources()
    params = {
        "workspace": "video-test",
        "model_type": "t2v",
        "prompt": 'A lantern over wet cobblestones.\n"Mañana"',
        "resolution": "832x480",
        "video_length": 161,
        "num_inference_steps": 30,
        "guidance_scale": 5.0,
        "generation_mode": "video",
        "image_mode": 0,
    }
    prepared, media = prepare_studio_video(
        params,
        model_definition=lambda _model: deepcopy(T2V_DEFINITION),
        model_downloaded=lambda _model: True,
        resources=resources,
        execution_policy=lambda _workspace: None,
    )
    assert prepared["prompt"] == params["prompt"]
    assert prepared["multi_prompts_gen_type"] == 2
    assert prepared["sliding_window_size"] == 161
    assert media == []


def test_lost_http_response_still_recovers_the_receipt(tmp_path):
    native = FakeNative(tmp_path)
    service, _ = configured_service(native, tmp_path)
    command = video_command("lost-response")
    first = _run(service.submit(command, trusted_tool="wizard"))
    recovered = service.receipt("video-test", "lost-response")
    assert recovered["receipt"] == first["receipt"]
    assert recovered["task"]["id"] == first["receipt"]["result"]["task_id"]
    replay = _run(service.submit(command, trusted_tool="external_agent"))
    assert replay == {"receipt": first["receipt"], "replayed": True}
    assert len(native.dispatch_calls) == 1
