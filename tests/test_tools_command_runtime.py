"""Native Tools route admission and recovery; no model or processor execution."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from routers.image_generation_commands import create_image_generation_commands_router, image_command_handlers
from routers.tools_upscale_commands import tools_upscale_command_catalog
from services.native_generation_operation import NativeGenerationOperation
from services.tools_upscale import TOOL_UPSCALE_METHODS
from services.tools_upscale_spec import freeze_tools_upscale_spec
from tests.test_image_generation_commands import FakeNative, _command as image_command, _run


def command(intent="upscale-intent"):
    return {"version": 2, "operation": "tools.upscale", "intent_id": intent,
            "input": {"workspace": "tool-destination", "params": {
                "source": "/api/v1/file/source.png?workspace=tool-source",
                "source_kind": "image", "method": "lanczos2", "seed": 42}}}


def native_endpoint(tmp_path, legacy_calls):
    source = Path(__file__).resolve().parents[1] / "app" / "_launch_runtime.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    definition = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "tools_upscale")
    definition.decorator_list = []
    namespace = {
        "Request": object, "HTTPException": HTTPException, "uuid": uuid, "time": time,
        "threading": threading, "_TOOL_UPSCALE_METHODS": TOOL_UPSCALE_METHODS,
        "_resolve_tool_source": lambda body, **_kwargs: (
            str(tmp_path / "source.png"), "source.png", "tool-source", body["source_kind"],
            "asset_source", body["workspace"], str(tmp_path / "destination")),
        "_register_manual_generation_job": lambda job: legacy_calls.append(job),
        "execution_mode": SimpleNamespace(policy=lambda: SimpleNamespace(simulated=False)),
    }
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["tools_upscale"]


def configured_service(native, tmp_path):
    service = native.service()
    legacy_calls, worker_calls = [], []

    def freeze(body):
        frozen = freeze_tools_upscale_spec(body)
        original_input = frozen["effective"]["input"]
        return frozen, {**deepcopy(original_input["params"]), "workspace": original_input["workspace"]}

    service.runtime_defaults = lambda: {"prompt": "unrelated image form", "model_type": "must-not-leak"}
    service.operations["tools.upscale"] = NativeGenerationOperation(
        freeze=freeze, prepare=lambda params: (params, []), catalog=tools_upscale_command_catalog(),
        prepare_request=native_endpoint(tmp_path, legacy_calls),
        worker=lambda job_id: worker_calls.append(job_id) or True, use_generation_defaults=False,
    )
    return service, legacy_calls, worker_calls


def test_tools_http_and_mcp_share_the_native_route_and_exact_receipt(tmp_path):
    native = FakeNative(tmp_path)
    service, legacy, workers = configured_service(native, tmp_path)
    app = FastAPI()
    app.include_router(create_image_generation_commands_router(service))
    with TestClient(app) as client:
        response = client.post("/api/v1/generation/commands", json=command(),
                               headers={"X-Hocus-UI-Surface": "wizard"})
        assert response.status_code == 200
    first = response.json()
    second = _run(image_command_handlers(service)["tools.upscale"](
        {key: value for key, value in command().items() if key != "operation"}))
    assert first["receipt"] == second["receipt"]
    assert second["replayed"] is True
    assert len(native.dispatch_calls) == 1
    job = native.dispatch_calls[0]
    assert job["params"]["model_type"] == "post_processing"
    assert "prompt" not in job["params"]
    assert "_non_durable_tool" not in job["params"]
    assert job["params"]["source_workspace"] == "tool-source"
    assert job["provenance"]["capability"] == "tools.upscale"
    assert job["provenance"]["actor"] == "wizard"
    assert service.native_worker(job)(job["id"]) is True
    assert workers == [job["id"]]
    assert legacy == []
    assert native.prepare_calls == 0
    another = _run(service.submit(command("another-deliberate-upscale")))
    assert another["receipt"]["taskIds"] != first["receipt"]["taskIds"]


def test_tool_recovery_retains_native_snapshot_and_requires_exact_admission(tmp_path):
    native = FakeNative(tmp_path)
    service, _, _ = configured_service(native, tmp_path)
    accepted = _run(service.submit(command()))
    restarted = FakeNative(tmp_path, interrupt_stale=True)
    recovery, legacy, workers = configured_service(restarted, tmp_path)
    recovery.restore_recovery(["tool-destination"])
    assert len(restarted.persist_calls) == 1
    record = restarted.persist_calls[0]
    assert recovery.filter_recovery([record]) == [record]
    assert record["params"] == native.dispatch_calls[0]["params"]
    assert recovery.native_worker(record)(record["id"]) is True
    assert workers == [record["id"]]
    forged = deepcopy(record)
    forged["provenance"]["command"]["command_id"] = "not-admitted"
    with pytest.raises(HTTPException) as caught:
        recovery.native_worker(forged)
    assert caught.value.status_code == 503
    assert workers == [record["id"]]
    drifted = deepcopy(record)
    drifted["id"] = "different-native-job"
    with pytest.raises(HTTPException) as mismatch:
        recovery.native_worker(drifted)
    assert mismatch.value.status_code == 503
    assert mismatch.value.detail["code"] == "recovery_mismatch"
    assert workers == [record["id"]]
    assert legacy == []
    assert _run(recovery.submit(command()))["receipt"] == accepted["receipt"]
    assert restarted.dispatch_calls == []


def test_tool_keeps_collection_attribution_separate_from_physical_output_workspace(tmp_path):
    native = FakeNative(tmp_path)
    service, _, _ = configured_service(native, tmp_path)
    request = command()
    request["input"]["workspace_collection_id"] = "collection-curated"
    accepted = _run(service.submit(request))
    job = native.dispatch_calls[0]
    assert job["workspace"] == "tool-destination"
    assert accepted["receipt"]["result"]["workspace"] == "tool-destination"
    assert job["provenance"]["workspace_id"] == "collection-curated"


def test_image_admission_cannot_be_relabelled_as_a_tool_worker(tmp_path):
    native = FakeNative(tmp_path)
    service, _, workers = configured_service(native, tmp_path)
    _run(service.submit(image_command()))
    record = deepcopy(native.dispatch_calls[0])
    record["provenance"]["capability"] = "tools.upscale"
    with pytest.raises(HTTPException):
        service.native_worker(record)
    assert workers == []


@pytest.mark.parametrize("capability", ["upscale", "tools.upscale"])
def test_native_task_projection_identifies_upscale_for_activity(tmp_path, capability):
    source = Path(__file__).resolve().parents[1] / "app" / "_launch_runtime.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    definition = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_generation_task_fields")
    namespace = {
        "time": time,
        "os": __import__("os"),
        "_workspace_dir": lambda workspace: str(Path("/tmp/activity-test") / workspace),
        "_public_generation_details": lambda params: params,
        "_task_status": lambda status: status,
        "_task_timestamp": lambda job, key: job.get(key),
        "_canonical_legacy_progress": lambda *_args: 0,
        "_is_durable_generation_job": lambda _job: True,
        "_local_gpu_lane": SimpleNamespace(key="local_gpu:0"),
    }
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), "exec"), namespace)
    task = namespace["_generation_task_fields"]({
        "id": "upscale-job", "status": "queued", "workspace": "tool-destination",
        "params": {"generation_mode": "image", "model_type": "post_processing"},
        "provenance": {"capability": capability, "command": {"command_id": "tool-intent"}},
    })
    assert task["title"] == "Tools · Upscale"
    assert task["metadata"]["capability"] == capability
    assert task["metadata"]["command_id"] == "tool-intent"
    assert task["workspace"] == "tool-destination"
    assert task["backend_job_id"] == "upscale-job"
