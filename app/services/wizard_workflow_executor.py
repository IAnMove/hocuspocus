"""Server executor for one image → upscale Wizard circuit.

Admission still goes through ``generation.image`` and ``tools.upscale``. This
module never starts a second generation queue. Old checkpoints of other types
are left untouched.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import threading
import uuid
from copy import deepcopy
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import HTTPException
from services.image_generation_commands import command_error
from services.tools_upscale import TOOL_UPSCALE_METHODS
from services.wizard_workflows import (
    WizardWorkflowRevisionConflict,
    read_workflows,
    write_workflows,
)


WORKFLOW_TYPE = "image_then_upscale"
STEP_IMAGE = "generate_image"
STEP_UPSCALE = "upscale_image"
SERVER_OWNER = "server"
IMAGE_OPERATION = "generation.image"
UPSCALE_OPERATION = "tools.upscale"
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "partial"})
ACTIVE_TASK_STATES = frozenset({"created", "queued", "waiting_resource", "running"})
FAILED_TASK_STATES = frozenset({"failed", "cancelled", "interrupted"})


def _now() -> int:
    import time
    return int(time.time() * 1000)


def _step_intent(workflow_id: str, step_id: str) -> str:
    raw = f"{workflow_id}:{step_id}"
    if len(raw) <= 160:
        return raw
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:160]


def _execution_intent(workflow: dict, step_id: str) -> str:
    step = next(item for item in workflow["steps"] if item["stepId"] == step_id)
    return step.get("executionKey") or _step_intent(workflow["workflowId"], step_id)


def _file_url(name: str, workspace: str) -> str:
    text = str(name or "").strip()
    if text.startswith("/api/v1/"):
        return text
    base = os.path.basename(text.replace("\\", "/"))
    return f"/api/v1/file/{quote(base)}?{urlencode({'workspace': workspace})}"


def _output_names(refs: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(refs, list):
        return names
    for item in refs:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
        elif isinstance(item, dict):
            label = str(item.get("name") or item.get("path") or "").strip()
            if label:
                names.append(label)
    return names


def _image_methods() -> list[str]:
    return sorted(
        method
        for method in TOOL_UPSCALE_METHODS
        if method != "h3facerefine" and not method.startswith(("rife", "dlssg"))
    )


def _task_id(receipt: dict) -> str:
    ids = receipt.get("taskIds")
    if isinstance(ids, list) and ids:
        return str(ids[0])
    result = receipt.get("result")
    if isinstance(result, dict) and result.get("task_id"):
        return str(result["task_id"])
    return ""


def _unique(values: list[str]) -> list[str]:
    seen: list[str] = []
    for item in values:
        if item and item not in seen:
            seen.append(item)
    return seen


def _revision_conflict(expected: int, current: int) -> HTTPException:
    return HTTPException(409, {
        "code": "wizard_workflow_revision_conflict",
        "message": f"Wizard workflow revision conflict: expected {expected}, current {current}",
        "expectedRevision": expected,
        "currentRevision": current,
        "retryable": False,
        "recoverable": True,
    })


def _lease_conflict(owner: str) -> HTTPException:
    return HTTPException(409, {
        "code": "wizard_workflow_lease_conflict",
        "message": f"Workflow is leased by {owner}",
        "retryable": False,
        "recoverable": True,
    })


def _new_steps(workflow_id: str, snapshot: dict) -> list[dict[str, Any]]:
    steps = []
    for step_id, kind in ((STEP_IMAGE, IMAGE_OPERATION), (STEP_UPSCALE, UPSCALE_OPERATION)):
        steps.append({
            "stepId": step_id,
            "kind": kind,
            "state": "pending",
            "input": deepcopy(snapshot) if step_id == STEP_IMAGE else {},
            "output": {},
            "taskId": "",
            "pipelineId": "",
            "outputRefs": [],
            "executionKey": _step_intent(workflow_id, step_id),
            "startedAt": 0,
            "completedAt": 0,
            "attempts": 0,
            "error": "",
        })
    return steps


def _new_workflow(body: dict[str, Any], owner: str) -> dict[str, Any]:
    workspace = str(body.get("workspace") or "").strip()
    snapshot = body.get("inputSnapshot") or body.get("input") or {}
    if not isinstance(snapshot, dict):
        raise command_error(422, "invalid_command", "inputSnapshot must be an object")
    if not workspace:
        raise command_error(422, "invalid_workspace", "Use an explicit valid output workspace")
    for field in ("model_type", "prompt", "resolution"):
        if not str(snapshot.get(field) or "").strip():
            raise command_error(422, "invalid_command", f"{field} is required")
    workflow_id = str(body.get("workflowId") or uuid.uuid4())
    now = _now()
    return {
        "workflowId": workflow_id,
        "type": WORKFLOW_TYPE,
        "workspace": workspace,
        "userRequest": str(body.get("userRequest") or ""),
        "state": "prepared",
        "currentStep": 0,
        "steps": _new_steps(workflow_id, snapshot),
        "resolvedEntityIds": {},
        "inputSnapshot": deepcopy(snapshot),
        "taskIds": [],
        "pipelineIds": [],
        "outputRefs": [],
        "confirmationScope": ["generate", "upscale"],
        "processedEventIds": [],
        "attempts": 0,
        "createdAt": now,
        "updatedAt": now,
        "recoverableError": "",
        "cancelRequested": False,
        "resumeRequested": False,
        "pendingInput": None,
        "executorOwner": owner,
        "leaseToken": uuid.uuid4().hex,
        "leaseExpiresAt": 0,
    }


def _replace(collection: dict[str, Any], workflow: dict[str, Any]) -> None:
    workflows = collection["workflows"]
    for index, item in enumerate(workflows):
        if item.get("workflowId") == workflow["workflowId"]:
            workflows[index] = workflow
            return
    workflows.append(workflow)


def _image_command(workflow: dict[str, Any]) -> dict[str, Any]:
    snapshot = workflow["inputSnapshot"]
    payload = {
        "workspace": workflow["workspace"],
        "model_type": snapshot["model_type"],
        "prompt": snapshot["prompt"],
        "resolution": snapshot["resolution"],
        "num_inference_steps": int(snapshot.get("num_inference_steps") or 1),
        "seed": int(snapshot["seed"]) if "seed" in snapshot else -1,
        "guidance_scale": float(snapshot["guidance_scale"]) if "guidance_scale" in snapshot else 1.0,
    }
    if "negative_prompt" in snapshot:
        payload["negative_prompt"] = snapshot["negative_prompt"]
    return {
        "version": 1,
        "operation": IMAGE_OPERATION,
        "intent_id": _execution_intent(workflow, STEP_IMAGE),
        "input": payload,
    }


def _upscale_source(workflow: dict[str, Any]) -> str:
    snapshot = workflow["inputSnapshot"]
    source = str(snapshot.get("source") or "").strip()
    if source:
        return source if source.startswith("/api/v1/") else _file_url(source, workflow["workspace"])
    refs = _output_names(workflow["steps"][0].get("outputRefs") if workflow["steps"] else [])
    if len(refs) == 1:
        return _file_url(refs[0], workflow["workspace"])
    return ""


def _upscale_method(workflow: dict[str, Any]) -> str:
    snapshot = workflow["inputSnapshot"]
    return str(snapshot.get("upscaleMethod") or snapshot.get("method") or "").strip()


def _pause_request(workflow: dict[str, Any]) -> dict[str, Any] | None:
    fields: list[str] = []
    options: list[dict[str, Any]] = []
    if not _upscale_method(workflow):
        fields.append("upscaleMethod")
        for name in _image_methods():
            options.append({"value": name, "label": name, "field": "upscaleMethod"})
    refs = _output_names(workflow["steps"][0].get("outputRefs") if workflow["steps"] else [])
    if not _upscale_source(workflow) and len(refs) != 1:
        fields.append("source")
        for name in refs:
            options.append({
                "value": _file_url(name, workflow["workspace"]),
                "label": name,
                "field": "source",
            })
    if not fields:
        return None
    reason = "Choose the exact upscale method and source before continuing."
    if fields == ["upscaleMethod"]:
        reason = "Choose the exact upscale method before continuing."
    elif fields == ["source"]:
        reason = "The image step published multiple outputs. Choose one exact source."
    return {"reason": reason, "fields": fields, "options": options}


def _upscale_command(workflow: dict[str, Any]) -> dict[str, Any]:
    source = _upscale_source(workflow)
    method = _upscale_method(workflow)
    if not source or not method:
        raise command_error(409, "awaiting_input", "Upscale inputs are not resolved")
    return {
        "version": 2,
        "operation": UPSCALE_OPERATION,
        "intent_id": _execution_intent(workflow, STEP_UPSCALE),
        "input": {
            "workspace": workflow["workspace"],
            "params": {
                "source": source,
                "source_workspace": workflow["workspace"],
                "source_kind": "image",
                "method": method,
                "seed": int(workflow["inputSnapshot"].get("upscaleSeed") or -1),
            },
        },
    }


def _field_options(pending: dict[str, Any], field: str) -> list[dict[str, Any]]:
    matched = []
    for item in pending.get("options") or []:
        if item.get("field") in {None, "", field}:
            matched.append(item)
    return matched


def _answer_value_allowed(pending: dict[str, Any], field: str, value: Any) -> None:
    if value is None:
        raise command_error(422, "invalid_answer", f"Input answer for {field} must not be empty")
    if isinstance(value, str) and not value.strip():
        raise command_error(422, "invalid_answer", f"Input answer for {field} must not be empty")
    options = _field_options(pending, field)
    if not options:
        return
    for item in options:
        if item.get("value") == value:
            return
    raise command_error(422, "invalid_answer", f"Input answer for {field} is not one of the available options")


def _validate_answer(pending: dict[str, Any], answer: dict[str, Any]) -> None:
    declared = list(pending.get("fields") or [])
    extra = [key for key in answer if key not in declared]
    if extra:
        raise command_error(422, "invalid_answer", f"Input answer contains undeclared field(s): {', '.join(extra)}")
    missing = [field for field in declared if field not in answer]
    if missing:
        raise command_error(422, "invalid_answer", f"Input answer is missing field(s): {', '.join(missing)}")
    for field in declared:
        _answer_value_allowed(pending, field, answer[field])


def _apply_answer(workflow: dict[str, Any], answer: dict[str, Any]) -> None:
    snapshot = dict(workflow.get("inputSnapshot") or {})
    snapshot.update(answer)
    workflow["inputSnapshot"] = snapshot
    step = workflow["steps"][workflow["currentStep"]]
    incoming = dict(step.get("input") or {})
    incoming.update(answer)
    step["input"] = incoming


def _failure_state(workflow: dict[str, Any]) -> str:
    if any(step.get("state") == "completed" for step in workflow.get("steps") or []):
        return "partial"
    return "failed"


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": "wizard.image_upscale",
            "version": 1,
            "supportedVersions": [1],
            "domain": "wizard",
            "mutation": True,
            "description": (
                "Start the server-owned image then upscale workflow. Admission uses "
                "generation.image and tools.upscale; the receipt proves each step."
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "version": {"type": "integer", "const": 1},
                    "workflowId": {"type": "string", "minLength": 1, "maxLength": 200},
                    "workspace": {"type": "string", "minLength": 1},
                    "userRequest": {"type": "string"},
                    "input": {"type": "object"},
                    "inputSnapshot": {"type": "object"},
                },
                "required": ["version", "workspace"],
            },
        },
        {
            "name": "wizard.workflow_answer",
            "version": 1,
            "supportedVersions": [1],
            "domain": "wizard",
            "mutation": True,
            "description": (
                "Answer a paused server-owned workflow. expectedRevision is compare-and-swap; "
                "a losing client receives a recoverable conflict and must not invent a new decision."
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "version": {"type": "integer", "const": 1},
                    "workspace": {"type": "string", "minLength": 1},
                    "workflowId": {"type": "string", "minLength": 1},
                    "expectedRevision": {"type": "integer", "minimum": 0},
                    "stepId": {"type": "string"},
                    "answerVersion": {"type": "integer", "minimum": 1},
                    "answer": {"type": "object"},
                },
                "required": ["version", "workspace", "workflowId", "expectedRevision", "answer"],
            },
        },
    ]


class WizardWorkflowExecutor:
    """Advance one durable image → upscale workflow using existing operations."""

    def __init__(self, *, workspace_dir, submit_command, command_receipt, get_task, owner: str = SERVER_OWNER):
        self._workspace_dir = workspace_dir
        self._submit_command = submit_command
        self._command_receipt = command_receipt
        self._get_task = get_task
        self._owner = owner
        self._lock = threading.RLock()
        self._advance_lock = asyncio.Lock()

    def _dir(self, workspace: str) -> str:
        return self._workspace_dir(workspace)

    def _read(self, workspace: str) -> dict[str, Any]:
        return read_workflows(self._dir(workspace))

    def _commit(self, workspace: str, collection: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
        """Persist one workflow without dropping siblings written during await.

        Admission can yield inside ``_submit``. A Wizard UI persist of another
        row increments the shared revision in that window; retrying against the
        latest collection keeps the receipt instead of leaving a running
        checkpoint with no task id.
        """
        workflow["updatedAt"] = _now()
        candidate = collection
        last_error: Exception | None = None
        for _ in range(5):
            try:
                _replace(candidate, workflow)
                saved = write_workflows(
                    self._dir(workspace),
                    candidate,
                    base_revision=int(candidate["revision"]),
                )
                collection["revision"] = saved["revision"]
                if candidate is not collection:
                    collection["workflows"] = candidate["workflows"]
                return {"revision": saved["revision"], "workflow": workflow}
            except WizardWorkflowRevisionConflict as error:
                last_error = error
                candidate = self._read(workspace)
        assert last_error is not None
        raise last_error

    def _load(self, workspace: str, workflow_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        collection = self._read(workspace)
        for item in collection["workflows"]:
            if item.get("workflowId") == workflow_id:
                return collection, item
        raise command_error(404, "workflow_not_found", "No workflow exists for this identifier")

    def _require_lease(self, workflow: dict[str, Any]) -> None:
        owner = str(workflow.get("executorOwner") or "")
        if owner and owner != self._owner:
            raise _lease_conflict(owner)
        workflow["executorOwner"] = self._owner
        if not workflow.get("leaseToken"):
            workflow["leaseToken"] = uuid.uuid4().hex

    def _check_revision(self, collection: dict[str, Any], expected: int | None) -> None:
        if expected is None:
            return
        current = int(collection["revision"])
        if expected != current:
            raise _revision_conflict(expected, current)

    def _lookup_receipt(self, workspace: str, intent_id: str) -> dict[str, Any] | None:
        try:
            payload = self._command_receipt(workspace, intent_id)
        except HTTPException as error:
            if error.status_code == 404:
                return None
            raise
        if not isinstance(payload, dict) or not isinstance(payload.get("receipt"), dict):
            return None
        return payload

    async def _submit(self, command: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
        result = self._submit_command(
            command,
            trusted_tool="wizard",
            submission_context={"workflowId": workflow["workflowId"]},
        )
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict) or not isinstance(result.get("receipt"), dict):
            raise command_error(503, "admission_unavailable", "Command admission did not return a receipt")
        return result

    def _attach(self, workflow: dict[str, Any], step: dict[str, Any], admitted: dict[str, Any]) -> None:
        receipt = deepcopy(admitted["receipt"])
        step["output"] = {**(step.get("output") or {}), "receipt": receipt, "replayed": bool(admitted.get("replayed"))}
        step["taskId"] = _task_id(receipt)
        workflow["taskIds"] = _unique([*(workflow.get("taskIds") or []), step["taskId"]])

    def _fail(self, workspace: str, collection: dict[str, Any], workflow: dict[str, Any], step: dict[str, Any], message: str) -> dict[str, Any]:
        step["state"] = "failed"
        step["error"] = message
        workflow["state"] = _failure_state(workflow)
        workflow["recoverableError"] = message
        return self._commit(workspace, collection, workflow)

    def _ask(self, workspace: str, collection: dict[str, Any], workflow: dict[str, Any], step: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        previous = workflow.get("pendingInput") if isinstance(workflow.get("pendingInput"), dict) else None
        version = 1
        if previous and previous.get("answer") is not None:
            version = max(1, int(previous.get("version") or 1) + 1)
        elif previous:
            version = max(1, int(previous.get("version") or 1))
        workflow["pendingInput"] = {
            "workflowId": workflow["workflowId"],
            "stepId": step["stepId"],
            "reason": request["reason"],
            "fields": request["fields"],
            "options": request.get("options") or [],
            "recommended": (request.get("options") or [{}])[0].get("value") if request.get("options") else None,
            "resolvedEntityIds": dict(workflow.get("resolvedEntityIds") or {}),
            "answer": None,
            "version": version,
            "requestedAt": now,
            "createdAt": now,
            "updatedAt": now,
            "answeredAt": 0,
        }
        step["state"] = "awaiting_input"
        workflow["state"] = "awaiting_input"
        return self._commit(workspace, collection, workflow)

    async def _ensure_admitted(self, workspace: str, collection: dict[str, Any], workflow: dict[str, Any], step: dict[str, Any], command: dict[str, Any]) -> dict[str, Any]:
        intent = command["intent_id"]
        step["executionKey"] = intent
        step["state"] = "running"
        step["startedAt"] = step.get("startedAt") or _now()
        step["attempts"] = int(step.get("attempts") or 0) + 1
        step["error"] = ""
        workflow["state"] = "retrying" if workflow.get("resumeRequested") else "running"
        self._commit(workspace, collection, workflow)
        collection, workflow = self._load(workspace, workflow["workflowId"])
        step = workflow["steps"][workflow["currentStep"]]
        found = self._lookup_receipt(workspace, intent)
        try:
            if found is None:
                found = await self._submit(command, workflow)
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail, dict) else {}
            message = str(detail.get("message") or error.detail)
            return self._fail(workspace, collection, workflow, step, message)
        self._attach(workflow, step, found)
        step["state"] = "waiting"
        workflow["state"] = "queued"
        workflow["resumeRequested"] = False
        return self._commit(workspace, collection, workflow)

    def _complete_current(self, workspace: str, collection: dict[str, Any], workflow: dict[str, Any], step: dict[str, Any], task: dict[str, Any]) -> str:
        refs = _output_names(task.get("result_refs") or (step.get("output") or {}).get("receipt", {}).get("artifacts"))
        step["state"] = "completed"
        step["completedAt"] = _now()
        step["outputRefs"] = _unique([*(step.get("outputRefs") or []), *refs])
        step["output"] = {**(step.get("output") or {}), "taskStatus": "completed"}
        workflow["outputRefs"] = _unique([*(workflow.get("outputRefs") or []), *step["outputRefs"]])
        workflow["currentStep"] = int(workflow["currentStep"]) + 1
        workflow["state"] = "completed" if workflow["currentStep"] >= len(workflow["steps"]) else "running"
        self._commit(workspace, collection, workflow)
        return "continue"

    async def _finish_waiting(self, workspace: str, collection: dict[str, Any], workflow: dict[str, Any], step: dict[str, Any]):
        task = self._get_task(workspace, step.get("taskId") or "")
        if not isinstance(task, dict):
            found = self._lookup_receipt(workspace, step.get("executionKey") or "")
            if found and found.get("task"):
                task = found["task"]
                self._attach(workflow, step, found)
            else:
                return await self._run_step(workspace, collection, workflow, step)
        status = str((task or {}).get("status") or "")
        if status == "completed":
            return self._complete_current(workspace, collection, workflow, step, task)
        if status in FAILED_TASK_STATES:
            return self._fail(workspace, collection, workflow, step, f"Task {step.get('taskId')} {status}")
        if status in ACTIVE_TASK_STATES:
            desired = "running" if status == "running" else "queued"
            if workflow["state"] == desired:
                return {"revision": collection["revision"], "workflow": workflow}
            workflow["state"] = desired
            return self._commit(workspace, collection, workflow)
        return {"revision": collection["revision"], "workflow": workflow}

    async def _run_step(self, workspace: str, collection: dict[str, Any], workflow: dict[str, Any], step: dict[str, Any]):
        if step["stepId"] == STEP_IMAGE:
            return await self._ensure_admitted(workspace, collection, workflow, step, _image_command(workflow))
        if step["stepId"] != STEP_UPSCALE:
            return self._fail(workspace, collection, workflow, step, f"Unknown step {step['stepId']}")
        refs = _output_names(workflow["steps"][0].get("outputRefs") if workflow["steps"] else [])
        if not refs and not str(workflow["inputSnapshot"].get("source") or "").strip():
            return self._fail(workspace, collection, workflow, step, "Image finished without a usable output")
        pause = _pause_request(workflow)
        if pause:
            return self._ask(workspace, collection, workflow, step, pause)
        return await self._ensure_admitted(workspace, collection, workflow, step, _upscale_command(workflow))

    async def _advance_once(self, workspace: str, workflow_id: str):
        collection, workflow = self._load(workspace, workflow_id)
        if workflow["type"] != WORKFLOW_TYPE:
            return {"revision": collection["revision"], "workflow": workflow}
        self._require_lease(workflow)
        if workflow.get("cancelRequested") or workflow["state"] == "cancelled":
            workflow["state"] = "cancelled"
            return self._commit(workspace, collection, workflow)
        if workflow["state"] in TERMINAL_STATES or workflow["state"] == "awaiting_input":
            return {"revision": collection["revision"], "workflow": workflow}
        index = int(workflow.get("currentStep") or 0)
        steps = workflow.get("steps") or []
        if index >= len(steps):
            workflow["state"] = "completed"
            return self._commit(workspace, collection, workflow)
        step = steps[index]
        if step["state"] == "completed":
            workflow["currentStep"] = index + 1
            self._commit(workspace, collection, workflow)
            return "continue"
        if step["state"] == "awaiting_input":
            return {"revision": collection["revision"], "workflow": workflow}
        if step["state"] == "waiting":
            return await self._finish_waiting(workspace, collection, workflow, step)
        return await self._run_step(workspace, collection, workflow, step)

    async def _advance(self, workspace: str, workflow_id: str) -> dict[str, Any]:
        async with self._advance_lock:
            return await self._advance_serial(workspace, workflow_id)

    async def _advance_serial(self, workspace: str, workflow_id: str) -> dict[str, Any]:
        result: dict[str, Any] | str = {"revision": 0, "workflow": {}}
        for _ in range(12):
            result = await self._advance_once(workspace, workflow_id)
            if result != "continue":
                return result
        raise command_error(500, "workflow_stuck", "Workflow advance did not settle")

    async def start(self, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise command_error(422, "invalid_command", "Start body must be a JSON object")
        workflow = _new_workflow(body, self._owner)
        workspace = workflow["workspace"]
        workflow_id = workflow["workflowId"]
        with self._lock:
            collection = self._read(workspace)
            existing = next((item for item in collection["workflows"] if item.get("workflowId") == workflow_id), None)
            if existing is not None:
                if self._return_existing(existing):
                    return {"revision": collection["revision"], "workflow": existing}
            else:
                self._commit(workspace, collection, workflow)
        return await self._advance(workspace, workflow_id)

    def _return_existing(self, existing: dict[str, Any]) -> bool:
        owner = str(existing.get("executorOwner") or "")
        return (
            existing.get("type") != WORKFLOW_TYPE
            or existing.get("state") in TERMINAL_STATES
            or bool(owner and owner != self._owner)
        )

    def _prepare_answer(self, workspace: str, workflow_id: str, body: dict[str, Any], answer: dict[str, Any], expected: int) -> None:
        collection, workflow = self._load(workspace, workflow_id)
        self._check_revision(collection, expected)
        self._require_lease(workflow)
        step = workflow["steps"][workflow["currentStep"]] if workflow["currentStep"] < len(workflow["steps"]) else None
        pending = workflow.get("pendingInput") if isinstance(workflow.get("pendingInput"), dict) else None
        answered = pending.get("answer") if pending else None
        if workflow["state"] != "awaiting_input" or step is None or step["state"] != "awaiting_input" or pending is None:
            if answered == answer:
                return
            raise _revision_conflict(expected, int(collection["revision"]))
        if body.get("stepId") and body["stepId"] != step["stepId"]:
            raise command_error(422, "invalid_answer", "Input answer targets a different workflow step")
        if body.get("answerVersion") not in {None, pending.get("version")}:
            raise command_error(409, "stale_answer", f"Input answer is stale (expected version {pending.get('version')})")
        _validate_answer(pending, answer)
        now = _now()
        _apply_answer(workflow, answer)
        pending["answer"] = deepcopy(answer)
        pending["answeredAt"] = now
        pending["updatedAt"] = now
        step["state"] = "pending"
        step["error"] = ""
        workflow["state"] = "retrying"
        workflow["resumeRequested"] = True
        workflow["recoverableError"] = ""
        workflow["attempts"] = int(workflow.get("attempts") or 0) + 1
        try:
            self._commit(workspace, collection, workflow)
        except WizardWorkflowRevisionConflict as error:
            raise _revision_conflict(error.expected, error.current) from error

    async def answer(self, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise command_error(422, "invalid_command", "Answer body must be a JSON object")
        workspace = str(body.get("workspace") or "").strip()
        workflow_id = str(body.get("workflowId") or "").strip()
        answer = body.get("answer")
        expected = body.get("expectedRevision")
        if not workspace or not workflow_id or not isinstance(answer, dict) or type(expected) is not int:
            raise command_error(422, "invalid_command", "workspace, workflowId, expectedRevision and answer are required")
        with self._lock:
            self._prepare_answer(workspace, workflow_id, body, answer, expected)
        return await self._advance(workspace, workflow_id)

    async def resume(self, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise command_error(422, "invalid_command", "Resume body must be a JSON object")
        workspace = str(body.get("workspace") or "").strip()
        workflow_id = str(body.get("workflowId") or "").strip()
        with self._lock:
            collection, workflow = self._load(workspace, workflow_id)
            self._check_revision(collection, body.get("expectedRevision") if type(body.get("expectedRevision")) is int else None)
            self._require_lease(workflow)
            if workflow["state"] not in {"failed", "partial", "cancelled"}:
                return {"revision": collection["revision"], "workflow": workflow}
            step = workflow["steps"][workflow["currentStep"]] if workflow["currentStep"] < len(workflow["steps"]) else None
            if step and step["state"] != "completed":
                task = self._get_task(workspace, step.get("taskId") or "")
                if task and task.get("status") in FAILED_TASK_STATES:
                    step["executionKey"] = _step_intent(workflow_id, f"{step['stepId']}:retry:{uuid.uuid4().hex}")
                    step["taskId"] = ""
                    step["output"] = {}
                    step["startedAt"] = 0
                step["state"] = "pending"
                step["error"] = ""
            workflow["state"] = "retrying"
            workflow["resumeRequested"] = True
            workflow["cancelRequested"] = False
            workflow["recoverableError"] = ""
            workflow["attempts"] = int(workflow.get("attempts") or 0) + 1
            self._commit(workspace, collection, workflow)
        return await self._advance(workspace, workflow_id)

    async def reconcile(self, workspace: str) -> list[dict[str, Any]]:
        collection = self._read(workspace)
        results = []
        for item in list(collection["workflows"]):
            if item.get("type") != WORKFLOW_TYPE or item.get("state") in TERMINAL_STATES:
                continue
            owner = str(item.get("executorOwner") or "")
            if owner and owner != self._owner:
                continue
            results.append(await self._advance(workspace, item["workflowId"]))
        return results

    async def recover(self, workspaces: list[str]) -> list[dict[str, Any]]:
        results = []
        for workspace in workspaces:
            results.extend(await self.reconcile(workspace))
        return results

    def reconcile_blocking(self, workspace: str) -> list[dict[str, Any]]:
        return asyncio.run(self.reconcile(workspace))

    def recover_blocking(self, workspaces: list[str]) -> list[dict[str, Any]]:
        return asyncio.run(self.recover(workspaces))

    def get(self, workspace: str, workflow_id: str) -> dict[str, Any]:
        collection, workflow = self._load(workspace, workflow_id)
        return {"revision": collection["revision"], "workflow": workflow}

    def list(self, workspace: str) -> dict[str, Any]:
        collection = self._read(workspace)
        workflows = [item for item in collection["workflows"] if item.get("type") == WORKFLOW_TYPE]
        return {"revision": collection["revision"], "workflows": workflows}


def command_handlers(executor: WizardWorkflowExecutor) -> dict[str, Any]:
    async def start(arguments):
        if not isinstance(arguments, dict):
            raise command_error(422, "invalid_command", "Use a JSON object")
        payload = dict(arguments)
        payload.setdefault("inputSnapshot", payload.pop("input", payload.get("inputSnapshot") or {}))
        return await executor.start(payload)

    async def answer(arguments):
        if not isinstance(arguments, dict):
            raise command_error(422, "invalid_command", "Use a JSON object")
        return await executor.answer(arguments)

    return {"wizard.image_upscale": start, "wizard.workflow_answer": answer}
