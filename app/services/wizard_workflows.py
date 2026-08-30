"""Durable per-workspace workflows for the embedded HocusPocus Wizard.

The file stores orchestration checkpoints, never executable code.  Creative
steps are resolved by the UI's registered workflow definition after reload;
mechanical state and canonical task correlation survive process restarts.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Any


WORKFLOW_FILENAME = ".wizard-workflows-v1.json"
MAX_WORKFLOWS = 100
MAX_STEPS = 100
MAX_BYTES = 4 * 1024 * 1024
_LOCK = threading.RLock()

WORKFLOW_STATES = frozenset({
    "prepared", "queued", "waiting", "running", "completed",
    "partial", "failed", "retrying", "cancelled",
})
STEP_STATES = frozenset({"pending", "running", "waiting", "completed", "failed", "cancelled"})
_SENSITIVE_PARTS = (
    "api_key", "apikey", "token", "authorization", "password", "passwd",
    "secret", "cookie", "session",
)


class WizardWorkflowRevisionConflict(ValueError):
    def __init__(self, expected: int, current: int):
        super().__init__(
            f"Wizard workflow revision conflict: expected {expected}, current {current}"
        )
        self.expected = expected
        self.current = current


def empty_workflows() -> dict[str, Any]:
    return {"version": 1, "revision": 0, "workflows": []}


def _text(value: Any, limit: int) -> str:
    return str(value or "").replace("\x00", "")[:limit]


def _integer(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return default


def _number(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return value if value == value else 0


def _safe_value(value: Any, depth: int = 0) -> Any:
    if depth > 8:
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, str):
        return _text(value, 8_000)
    if isinstance(value, list):
        return [_safe_value(item, depth + 1) for item in value[:200]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:200]:
            clean_key = _text(key, 160)
            lowered = clean_key.casefold().replace("-", "_")
            result[clean_key] = (
                "[REDACTED]"
                if any(part in lowered for part in _SENSITIVE_PARTS)
                else _safe_value(item, depth + 1)
            )
        return result
    return _text(value, 2_000)


def _string_list(value: Any, limit: int = 100, item_limit: int = 300) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item, item_limit) for item in value[:limit] if str(item or "").strip()]


def _clean_step(value: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    step_id = _text(value.get("stepId") or value.get("id"), 160)
    if not step_id:
        step_id = f"step-{index + 1}"
    state = _text(value.get("state"), 30)
    if state not in STEP_STATES:
        state = "pending"
    return {
        "stepId": step_id,
        "kind": _text(value.get("kind"), 160),
        "state": state,
        "input": _safe_value(value.get("input") if isinstance(value.get("input"), dict) else {}),
        "output": _safe_value(value.get("output") if isinstance(value.get("output"), dict) else {}),
        "taskId": _text(value.get("taskId"), 200),
        "pipelineId": _text(value.get("pipelineId"), 200),
        "outputRefs": _string_list(value.get("outputRefs"), 100, 500),
        "executionKey": _text(value.get("executionKey"), 500),
        "startedAt": _integer(value.get("startedAt")),
        "completedAt": _integer(value.get("completedAt")),
        "attempts": _integer(value.get("attempts")),
        "error": _text(value.get("error"), 4_000),
    }


def _clean_workflow(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    workflow_id = _text(value.get("workflowId"), 200)
    workflow_type = _text(value.get("type"), 160)
    workspace = _text(value.get("workspace"), 160)
    if not workflow_id or not workflow_type or not workspace:
        return None
    state = _text(value.get("state"), 30)
    if state not in WORKFLOW_STATES:
        state = "prepared"
    steps = []
    for index, raw in enumerate((value.get("steps") or [])[:MAX_STEPS]):
        step = _clean_step(raw, index)
        if step:
            steps.append(step)
    current_step = min(_integer(value.get("currentStep")), len(steps))
    return {
        "workflowId": workflow_id,
        "type": workflow_type,
        "workspace": workspace,
        "userRequest": _text(value.get("userRequest"), 8_000),
        "state": state,
        "currentStep": current_step,
        "steps": steps,
        "resolvedEntityIds": _safe_value(
            value.get("resolvedEntityIds")
            if isinstance(value.get("resolvedEntityIds"), dict) else {}
        ),
        "inputSnapshot": _safe_value(
            value.get("inputSnapshot")
            if isinstance(value.get("inputSnapshot"), dict) else {}
        ),
        "taskIds": _string_list(value.get("taskIds"), 100, 200),
        "pipelineIds": _string_list(value.get("pipelineIds"), 100, 200),
        "outputRefs": _string_list(value.get("outputRefs"), 200, 500),
        "confirmationScope": _string_list(value.get("confirmationScope"), 100, 200),
        "processedEventIds": [_integer(item) for item in (value.get("processedEventIds") or [])[-500:]],
        "attempts": _integer(value.get("attempts")),
        "createdAt": _integer(value.get("createdAt")),
        "updatedAt": _integer(value.get("updatedAt")),
        "recoverableError": _text(value.get("recoverableError"), 4_000),
        "cancelRequested": value.get("cancelRequested") is True,
        "resumeRequested": value.get("resumeRequested") is True,
    }


def normalize_workflows(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Wizard workflows must be a JSON object")
    revision = value.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("Wizard workflow revision must be a non-negative integer")
    workflows = []
    seen: set[str] = set()
    for raw in (value.get("workflows") or [])[:MAX_WORKFLOWS]:
        workflow = _clean_workflow(raw)
        if not workflow or workflow["workflowId"] in seen:
            continue
        seen.add(workflow["workflowId"])
        workflows.append(workflow)
    return {"version": 1, "revision": revision, "workflows": workflows}


def workflow_path(workspace_dir: str) -> str:
    return os.path.join(workspace_dir, WORKFLOW_FILENAME)


def read_workflows(workspace_dir: str) -> dict[str, Any]:
    path = workflow_path(workspace_dir)
    with _LOCK:
        if not os.path.isfile(path):
            return empty_workflows()
        with open(path, "r", encoding="utf-8") as handle:
            return normalize_workflows(json.load(handle))


def write_workflows(
    workspace_dir: str,
    value: Any,
    *,
    base_revision: int,
) -> dict[str, Any]:
    if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision < 0:
        raise ValueError("baseRevision must be a non-negative integer")
    collection = normalize_workflows(value)
    with _LOCK:
        current = read_workflows(workspace_dir)
        current_revision = int(current["revision"])
        if base_revision != current_revision:
            raise WizardWorkflowRevisionConflict(base_revision, current_revision)
        collection["revision"] = current_revision + 1
        encoded = json.dumps(collection, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_BYTES:
            raise ValueError("Wizard workflows are too large to save")
        os.makedirs(workspace_dir, exist_ok=True)
        path = workflow_path(workspace_dir)
        temporary = f"{path}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                if os.path.isfile(temporary):
                    os.remove(temporary)
            except OSError:
                pass
        return collection
