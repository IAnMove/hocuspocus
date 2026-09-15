"""Studio video factory, resources and catalog without loading a model."""

from copy import deepcopy
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from routers.image_generation_commands import create_image_generation_commands_router, image_command_handlers
from routers.studio_video_commands import video_command_catalog
from services.image_generation_runtime import create_image_generation_commands
from services.native_generation_operation import NativeGenerationOperation
from services.studio_video_resources import StudioVideoResources
from services.video_generation_spec import freeze_video_generation_spec, video_generation_schema
from tests.test_image_generation_commands import FakeNative, _run
from tests.test_video_generation_commands import T2V_DEFINITION, configured_service, video_command


def write_png(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), "red").save(path)


def test_catalog_describes_the_closed_wan_t2v_tool():
    catalog = video_command_catalog()
    assert catalog["name"] == "generation.video"
    assert catalog["version"] == 2
    assert catalog["videoModelTypes"] == ["t2v", "t2v_1.3B"]
    assert catalog["inputSchema"]["properties"]["operation"]["const"] == "generation.video"
    assert catalog["inputSchema"]["additionalProperties"] is False
    assert video_generation_schema()["video_model_family"] == catalog["videoModelFamily"]


def test_runtime_factory_publishes_generation_video(tmp_path):
    native = FakeNative(tmp_path)
    runtime = {
        "_durable_generation_queue": SimpleNamespace(upsert=lambda _job: None),
        "_run_generation_with_preparation": lambda _job_id: None,
        "_jobs": {},
        "register_generation_job": lambda *_args: None,
        "_gen_lock": object(),
        "_cancel_h3_idle_release": lambda: None,
        "_active_gen_states": {},
        "_task_registry": native.registry,
        "generate": native.prepare,
        "_new_generation_job": native.make_job,
        "_generation_task_fields": native.task_fields,
        "execution_mode": SimpleNamespace(validate_generation=lambda _workspace: None),
        "wgp": SimpleNamespace(
            primary_settings={},
            get_model_def=lambda model: deepcopy(T2V_DEFINITION) if model == "t2v_1.3B" else None,
            get_lora_search_dirs=lambda _model: [],
        ),
        "_check_model_downloaded": lambda _model: True,
        "_workspace_dir": lambda workspace: str(tmp_path / workspace),
        "_list_workspaces": lambda: [{"name": "video-test"}],
        "_lora_is_compatible_with_model": lambda *_args: False,
    }
    service = create_image_generation_commands(runtime)
    adapter = service.operations["generation.video"]
    assert isinstance(adapter, NativeGenerationOperation)
    assert adapter.catalog["name"] == "generation.video"
    assert service.operations["generation.sfx"].catalog["name"] != "generation.video" if "generation.sfx" in service.operations else True

    app = FastAPI()
    app.include_router(create_image_generation_commands_router(service))
    with TestClient(app) as client:
        names = {item["name"] for item in client.get("/api/v1/generation/commands").json()["operations"]}
    assert "generation.video" in names
    assert "generation.image" in names


def test_real_resources_reject_a_foreign_or_missing_workspace_before_admission(tmp_path):
    native = FakeNative(tmp_path)
    for name in ("video-test", "source"):
        (tmp_path / name).mkdir()
    write_png(tmp_path / "source" / "frame.png")
    resources = StudioVideoResources(
        workspace_dir=lambda name: str(tmp_path / name),
        uploads_dir=lambda: str(tmp_path / "uploads"),
        list_workspaces=lambda: [{"name": "source"}, {"name": "video-test"}],
        lora_search_dirs=lambda _model: [],
        lora_compatible=lambda *_args: False,
    )
    service, _ = configured_service(native, tmp_path, resources=resources)
    lying = video_command("lying-frame", image_start="/api/v1/file/frame.png?workspace=video-test")
    with pytest.raises(HTTPException) as missing_in_declared:
        _run(service.submit(lying))
    assert missing_in_declared.value.status_code == 422
    assert native.registry("video-test").command_admission("lying-frame") is None

    missing = video_command("missing-source", image_start="/api/v1/file/absent.png?workspace=source")
    with pytest.raises(HTTPException) as missing_error:
        _run(service.submit(missing))
    assert missing_error.value.status_code == 422
    assert native.dispatch_calls == []


def test_unsupported_start_frame_is_resolved_then_rejected_without_a_task(tmp_path):
    native = FakeNative(tmp_path)
    (tmp_path / "source").mkdir()
    write_png(tmp_path / "source" / "frame.png")
    resources = StudioVideoResources(
        workspace_dir=lambda name: str(tmp_path / name),
        uploads_dir=lambda: str(tmp_path / "uploads"),
        list_workspaces=lambda: [{"name": "source"}, {"name": "video-test"}],
        lora_search_dirs=lambda _model: [],
        lora_compatible=lambda *_args: False,
    )
    service, _ = configured_service(native, tmp_path, resources=resources)
    request = video_command("start-frame", image_start="/api/v1/file/frame.png?workspace=source")
    with pytest.raises(HTTPException) as rejected:
        _run(service.submit(request))
    assert rejected.value.status_code == 422
    assert "does not accept image or video references" in str(rejected.value.detail)
    assert native.registry("video-test").command_admission("start-frame") is None


def test_mcp_handler_omits_transport_operation_and_legacy_generate_remains(tmp_path):
    native = FakeNative(tmp_path)
    service, _ = configured_service(native, tmp_path)
    handler = image_command_handlers(service)["generation.video"]
    command = video_command()
    arguments = {key: value for key, value in command.items() if key != "operation"}
    result = _run(handler(arguments))
    assert result["receipt"]["operation"] == "generation.video"
    with pytest.raises(HTTPException):
        _run(handler({**arguments, "operation": "generation.video"}))
    frozen = freeze_video_generation_spec(command)
    assert frozen["original"]["operation"] == "generation.video"
