"""Isolated server-side image → upscale workflow executor.

These checks never import ``_launch_runtime`` and never start a model worker.
They reuse FakeNative admission so the existing generation queue remains the
only dispatch path.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.wizard_workflow_executor import create_wizard_workflow_executor_router
from routers.wangp_mcp import create_wangp_mcp_router
from services.native_generation_operation import NativeGenerationOperation
from services.tools_upscale_spec import freeze_tools_upscale_spec
from services.wizard_workflow_executor import (
    SERVER_OWNER,
    STEP_IMAGE,
    STEP_UPSCALE,
    WORKFLOW_TYPE,
    WizardWorkflowExecutor,
    catalog,
    command_handlers,
)
from services.wizard_workflows import read_workflows, write_workflows
from tests.test_image_generation_commands import FakeNative, _mcp_call
from routers.tools_upscale_commands import tools_upscale_command_catalog


WORKSPACE = "workspace-a"


def _snapshot(**overrides):
    payload = {
        "model_type": "pi_flux2",
        "prompt": '  literal "mañana"\nsecond line  ',
        "resolution": "512x512",
        "num_inference_steps": 1,
        "seed": -1,
        "guidance_scale": 1.0,
        "upscaleMethod": "lanczos2",
    }
    payload.update(overrides)
    return payload


def _start_body(workflow_id="wf-image-upscale", **overrides):
    snapshot = _snapshot(**overrides.pop("snapshot", {})) if "snapshot" in overrides else _snapshot()
    if "upscaleMethod" in overrides:
        snapshot["upscaleMethod"] = overrides.pop("upscaleMethod")
    body = {
        "workspace": WORKSPACE,
        "workflowId": workflow_id,
        "userRequest": "Generate a poster and upscale it",
        "inputSnapshot": snapshot,
    }
    body.update(overrides)
    return body


def _tools_service(native: FakeNative):
    service = native.service()

    def freeze(command):
        frozen = freeze_tools_upscale_spec(command)
        payload = frozen["effective"]["input"]
        return frozen, {**deepcopy(payload["params"]), "workspace": payload["workspace"]}

    service.operations["tools.upscale"] = NativeGenerationOperation(
        freeze=freeze,
        prepare=lambda params: (params, []),
        catalog=tools_upscale_command_catalog(),
        prepare_request=native.prepare,
        use_generation_defaults=False,
    )
    return service


def _executor(tmp_path: Path, native: FakeNative | None = None):
    native = native or FakeNative(tmp_path)
    service = _tools_service(native)

    def workspace_dir(name: str) -> str:
        path = Path(tmp_path) / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def get_task(workspace: str, task_id: str):
        if not task_id:
            return None
        return native.registry(workspace).get(task_id)

    executor = WizardWorkflowExecutor(
        workspace_dir=workspace_dir,
        submit_command=service.submit,
        command_receipt=service.receipt,
        get_task=get_task,
    )
    return executor, native, service, workspace_dir


def _app(executor, tmp_path):
    app = FastAPI()
    app.include_router(create_wizard_workflow_executor_router(executor))
    app.include_router(create_wangp_mcp_router(
        handlers=command_handlers(executor),
        command_operations=catalog(),
        journal_path=Path(tmp_path) / "mcp-journal.sqlite",
        token_getter=lambda: "test-token",
    ))
    return TestClient(app)


def _complete(native: FakeNative, workspace: str, task_id: str, refs: list[str]):
    registry = native.registry(workspace)
    registry.update(task_id, status="running", force=True)
    registry.update(task_id, status="completed", result_refs=refs, force=True)


def test_closing_tabs_after_image_admit_admits_upscale_once(tmp_path):
    executor, native, _service, _workspace_dir = _executor(tmp_path)
    client = _app(executor, tmp_path)

    started = client.post("/api/v1/wizard/workflows/executor", json=_start_body())
    assert started.status_code == 200, started.text
    body = started.json()
    workflow = body["workflow"]
    assert workflow["state"] == "queued"
    assert workflow["executorOwner"] == SERVER_OWNER
    assert workflow["steps"][0]["state"] == "waiting"
    assert workflow["steps"][0]["taskId"]
    assert len(native.dispatch_calls) == 1
    assert native.dispatch_calls[0]["provenance"]["capability"] == "generation.image"

    image_task = workflow["steps"][0]["taskId"]
    _complete(native, WORKSPACE, image_task, ["poster.png"])
    ticked = client.post("/api/v1/wizard/workflows/executor/reconcile", json={"workspace": WORKSPACE})
    assert ticked.status_code == 200, ticked.text
    again = client.post("/api/v1/wizard/workflows/executor/reconcile", json={"workspace": WORKSPACE})
    assert again.status_code == 200

    current = client.get(
        f"/api/v1/wizard/workflows/executor/{workflow['workflowId']}",
        params={"workspace": WORKSPACE},
    ).json()["workflow"]
    assert current["steps"][0]["state"] == "completed"
    assert current["steps"][1]["state"] == "waiting"
    assert current["steps"][1]["kind"] == "tools.upscale"
    assert len(native.dispatch_calls) == 2
    assert native.dispatch_calls[1]["provenance"]["capability"] == "tools.upscale"
    assert native.dispatch_calls[1]["params"]["source"] == "/api/v1/file/poster.png?workspace=workspace-a"
    assert native.dispatch_calls[1]["params"]["method"] == "lanczos2"
    _complete(native, WORKSPACE, current["steps"][1]["taskId"], ["poster-up.png"])
    client.post("/api/v1/wizard/workflows/executor/reconcile", json={"workspace": WORKSPACE})
    finished = client.get(
        f"/api/v1/wizard/workflows/executor/{workflow['workflowId']}",
        params={"workspace": WORKSPACE},
    ).json()["workflow"]
    assert finished["state"] == "completed"
    assert finished["outputRefs"] == ["poster.png", "poster-up.png"]
    assert len(native.dispatch_calls) == 2


def test_restart_between_admit_and_save_reconciles_receipt_without_duplicate(tmp_path):
    executor, native, _service, workspace_dir = _executor(tmp_path)
    from asyncio import run
    started = run(executor.start(_start_body("wf-restart")))
    workflow = started["workflow"]
    assert len(native.dispatch_calls) == 1
    directory = workspace_dir(WORKSPACE)
    collection = read_workflows(directory)
    lost = deepcopy(collection)
    step = lost["workflows"][0]["steps"][0]
    step["state"] = "running"
    step["taskId"] = ""
    step["output"] = {}
    lost["workflows"][0]["state"] = "running"
    write_workflows(directory, lost, base_revision=int(collection["revision"]))

    restarted, _native, _ignored, _dir = _executor(tmp_path, native)
    recovered = run(restarted.recover([WORKSPACE]))
    assert recovered
    restored = recovered[0]["workflow"]
    assert restored["steps"][0]["taskId"] == workflow["steps"][0]["taskId"]
    assert restored["steps"][0]["output"]["receipt"]["commandId"]
    assert restored["steps"][0]["state"] == "waiting"
    assert len(native.dispatch_calls) == 1
    run(restarted.reconcile(WORKSPACE))
    assert len(native.dispatch_calls) == 1


def test_two_clients_answering_yield_one_winner_and_recoverable_conflict(tmp_path):
    executor, native, _service, _workspace_dir = _executor(tmp_path)
    client = _app(executor, tmp_path)
    started = client.post(
        "/api/v1/wizard/workflows/executor",
        json=_start_body("wf-question", snapshot=_snapshot(upscaleMethod="")),
    )
    assert started.status_code == 200, started.text
    workflow = started.json()["workflow"]
    _complete(native, WORKSPACE, workflow["steps"][0]["taskId"], ["choice.png"])
    paused = client.post("/api/v1/wizard/workflows/executor/reconcile", json={"workspace": WORKSPACE})
    assert paused.status_code == 200
    current = paused.json()["results"][0]
    workflow = current["workflow"]
    assert workflow["state"] == "awaiting_input"
    assert workflow["pendingInput"]["fields"] == ["upscaleMethod"]
    revision = current["revision"]
    first = client.post("/api/v1/wizard/workflows/executor/answer", json={
        "workspace": WORKSPACE,
        "workflowId": workflow["workflowId"],
        "expectedRevision": revision,
        "stepId": STEP_UPSCALE,
        "answerVersion": 1,
        "answer": {"upscaleMethod": "lanczos2"},
    })
    second = client.post("/api/v1/wizard/workflows/executor/answer", json={
        "workspace": WORKSPACE,
        "workflowId": workflow["workflowId"],
        "expectedRevision": revision,
        "stepId": STEP_UPSCALE,
        "answerVersion": 1,
        "answer": {"upscaleMethod": "lanczos1.5"},
    })
    assert first.status_code == 200, first.text
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "wizard_workflow_revision_conflict"
    assert detail["recoverable"] is True
    winner = first.json()["workflow"]
    assert winner["pendingInput"]["answer"] == {"upscaleMethod": "lanczos2"}
    assert winner["steps"][1]["state"] == "waiting"
    assert len(native.dispatch_calls) == 2
    assert native.dispatch_calls[1]["params"]["method"] == "lanczos2"


def test_mcp_can_start_and_answer_the_same_circuit(tmp_path):
    executor, native, _service, _workspace_dir = _executor(tmp_path)
    client = _app(executor, tmp_path)
    start = _mcp_call(client, "wizard.image_upscale", {
        "version": 1,
        "workspace": WORKSPACE,
        "workflowId": "wf-mcp",
        "userRequest": "poster then upscale",
        "input": _snapshot(upscaleMethod=""),
    })
    assert start.status_code == 200, start.text
    result = start.json()["result"]
    assert result["isError"] is False
    workflow = result["structuredContent"]["workflow"]
    _complete(native, WORKSPACE, workflow["steps"][0]["taskId"], ["mcp.png"])
    paused = client.post("/api/v1/wizard/workflows/executor/reconcile", json={"workspace": WORKSPACE}).json()
    revision = paused["results"][0]["revision"]
    answer = _mcp_call(client, "wizard.workflow_answer", {
        "version": 1,
        "workspace": WORKSPACE,
        "workflowId": "wf-mcp",
        "expectedRevision": revision,
        "answer": {"upscaleMethod": "lanczos2"},
    }, request_id=2)
    assert answer.status_code == 200, answer.text
    payload = answer.json()["result"]["structuredContent"]["workflow"]
    assert payload["steps"][1]["state"] == "waiting"
    assert payload["pendingInput"]["answer"]["upscaleMethod"] == "lanczos2"


def test_old_checkpoints_are_not_migrated_or_rewritten(tmp_path):
    executor, native, _service, workspace_dir = _executor(tmp_path)
    directory = workspace_dir(WORKSPACE)
    write_workflows(directory, {
        "revision": 0,
        "workflows": [{
            "workflowId": "legacy-rhythm",
            "type": "create_rhythmic_3d_video",
            "workspace": WORKSPACE,
            "state": "waiting",
            "currentStep": 0,
            "steps": [{"stepId": "song", "kind": "generate_song", "state": "waiting", "input": {}}],
        }],
    }, base_revision=0)
    from asyncio import run
    recovered = run(executor.recover([WORKSPACE]))
    assert recovered == []
    loaded = read_workflows(directory)
    assert loaded["revision"] == 1
    assert loaded["workflows"][0]["type"] == "create_rhythmic_3d_video"
    assert loaded["workflows"][0]["state"] == "waiting"
    assert len(native.dispatch_calls) == 0


def test_ui_lease_blocks_server_advance(tmp_path):
    executor, native, _service, workspace_dir = _executor(tmp_path)
    directory = workspace_dir(WORKSPACE)
    write_workflows(directory, {
        "revision": 0,
        "workflows": [{
            "workflowId": "wf-ui",
            "type": WORKFLOW_TYPE,
            "workspace": WORKSPACE,
            "state": "prepared",
            "currentStep": 0,
            "executorOwner": "ui",
            "steps": [
                {"stepId": STEP_IMAGE, "kind": "generation.image", "state": "pending", "input": _snapshot()},
                {"stepId": STEP_UPSCALE, "kind": "tools.upscale", "state": "pending", "input": {}},
            ],
            "inputSnapshot": _snapshot(),
        }],
    }, base_revision=0)
    from asyncio import run
    recovered = run(executor.recover([WORKSPACE]))
    assert recovered == []
    assert len(native.dispatch_calls) == 0
    loaded = read_workflows(directory)
    assert loaded["workflows"][0]["executorOwner"] == "ui"


def test_sibling_persist_during_submit_keeps_receipt(tmp_path):
    executor, native, service, workspace_dir = _executor(tmp_path)
    original_submit = service.submit

    async def racing_submit(command, **kwargs):
        directory = workspace_dir(WORKSPACE)
        collection = read_workflows(directory)
        collection["workflows"].append({
            "workflowId": "wf-ui-sibling",
            "type": "create_rhythmic_3d_video",
            "workspace": WORKSPACE,
            "state": "waiting",
            "currentStep": 0,
            "steps": [{"stepId": "song", "kind": "generate_song", "state": "waiting", "input": {}}],
        })
        write_workflows(directory, collection, base_revision=int(collection["revision"]))
        return await original_submit(command, **kwargs)

    executor._submit_command = racing_submit
    from asyncio import run
    started = run(executor.start(_start_body("wf-race")))
    workflow = started["workflow"]
    assert workflow["steps"][0]["state"] == "waiting"
    assert workflow["steps"][0]["taskId"]
    assert workflow["steps"][0]["output"]["receipt"]["commandId"]
    assert len(native.dispatch_calls) == 1
    loaded = read_workflows(workspace_dir(WORKSPACE))
    assert {item["workflowId"] for item in loaded["workflows"]} == {"wf-race", "wf-ui-sibling"}
    saved = next(item for item in loaded["workflows"] if item["workflowId"] == "wf-race")
    assert saved["steps"][0]["state"] == "waiting"
    assert saved["steps"][0]["taskId"] == workflow["steps"][0]["taskId"]


def test_start_retry_reattaches_receipt_to_running_checkpoint(tmp_path):
    executor, native, _service, workspace_dir = _executor(tmp_path)
    from asyncio import run
    first = run(executor.start(_start_body("wf-running")))
    directory = workspace_dir(WORKSPACE)
    collection = read_workflows(directory)
    lost = deepcopy(collection)
    step = lost["workflows"][0]["steps"][0]
    step["state"] = "running"
    step["taskId"] = ""
    step["output"] = {}
    lost["workflows"][0]["state"] = "running"
    write_workflows(directory, lost, base_revision=int(collection["revision"]))

    recovered = run(executor.start(_start_body("wf-running")))
    workflow = recovered["workflow"]
    assert workflow["steps"][0]["taskId"] == first["workflow"]["steps"][0]["taskId"]
    assert workflow["steps"][0]["output"]["receipt"]["commandId"]
    assert workflow["steps"][0]["state"] == "waiting"
    assert len(native.dispatch_calls) == 1


def test_start_retry_advances_prepared_server_checkpoint(tmp_path):
    executor, native, _service, workspace_dir = _executor(tmp_path)
    write_workflows(workspace_dir(WORKSPACE), {
        "revision": 0,
        "workflows": [{
            "workflowId": "wf-prepared",
            "type": WORKFLOW_TYPE,
            "workspace": WORKSPACE,
            "state": "prepared",
            "currentStep": 0,
            "executorOwner": SERVER_OWNER,
            "steps": [
                {"stepId": STEP_IMAGE, "kind": "generation.image", "state": "pending", "input": _snapshot()},
                {"stepId": STEP_UPSCALE, "kind": "tools.upscale", "state": "pending", "input": {}},
            ],
            "inputSnapshot": _snapshot(),
        }],
    }, base_revision=0)
    from asyncio import run
    started = run(executor.start(_start_body("wf-prepared")))
    workflow = started["workflow"]
    assert workflow["state"] == "queued"
    assert workflow["steps"][0]["state"] == "waiting"
    assert workflow["steps"][0]["taskId"]
    assert len(native.dispatch_calls) == 1


def test_catalog_describes_start_and_answer_operations():
    names = [item["name"] for item in catalog()]
    assert names == ["wizard.image_upscale", "wizard.workflow_answer"]
