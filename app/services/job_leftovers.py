"""MCP view of the existing durable generation queue.

This is not a second queue. Leftovers are the records already persisted for
the recovery dialog. Resume and discard call the same recovery hooks the UI
uses; they never start a second worker for a job that is already live.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import uuid
from typing import Any, Callable

from fastapi import HTTPException

from services.durable_generation_queue import DurableGenerationQueue

ACTIVE_STATUSES = frozenset({"queued", "waiting_resource", "running", "cancelling"})
_MAX_INTENT = 160
# Written after the first durable persist (H3 window planning). A crash during
# GPU work must still match the original submit body.
_RUNTIME_PARAM_KEYS = frozenset({
    "h3_window_prompts",
    "h3_window_plan",
    "h3_window_plan_signature",
    "minimax_h3_window_storyboard",
})


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message, "retryable": status >= 500})


def _workspace(value: Any) -> str:
    text = str(value or "default").strip()
    return text or "default"


def recovery_status(previous: Any) -> str:
    """Queued work is a leftover; a dead running worker is interrupted."""
    if str(previous or "queued") in {"running", "cancelling"}:
        return "interrupted"
    return "leftover"


def content_fingerprint(params: Any, workspace: Any) -> str:
    """Hash submission content. Identity, provenance and runtime keys are excluded."""
    clean: dict[str, Any] = {}
    if isinstance(params, dict):
        for key in sorted(params):
            if (
                isinstance(key, str)
                and not key.startswith("_")
                and key not in _RUNTIME_PARAM_KEYS
            ):
                clean[key] = params[key]
    payload = {"workspace": _workspace(workspace), "params": clean}
    try:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(encoded).hexdigest()


def intent_of(record: Any) -> str:
    provenance = record.get("provenance") if isinstance(record, dict) else None
    command = provenance.get("command") if isinstance(provenance, dict) else None
    command_id = command.get("command_id") if isinstance(command, dict) else None
    if isinstance(command_id, str) and command_id.strip():
        return command_id.strip()
    if isinstance(record, dict):
        return str(record.get("id") or "")
    return ""


def _preview(params: dict) -> str:
    text = params.get("prompt")
    if not isinstance(text, str) or not text.strip():
        text = params.get("lyrics")
    if not isinstance(text, str):
        return ""
    return text.strip()[:240]


def public_job(record: dict) -> dict:
    params = record.get("params") if isinstance(record.get("params"), dict) else {}
    status = recovery_status(record.get("status"))
    return {
        "job_id": str(record.get("id") or ""),
        "intent_id": intent_of(record),
        "status": status,
        "previous_status": str(record.get("status") or "queued"),
        "workspace": _workspace(record.get("workspace")),
        "model_type": str(params.get("model_type") or ""),
        "prompt_preview": _preview(params),
        "fingerprint": content_fingerprint(params, record.get("workspace")),
        "created_at": float(record.get("created_at") or 0),
    }


def status_document(record: dict) -> dict:
    summary = public_job(record)
    if summary["status"] == "interrupted":
        message = "Generation was interrupted and is waiting for resume or discard."
    else:
        message = "Leftover generation is waiting for resume or discard."
    summary.update({
        "task_id": f"task-generation-{summary['job_id']}",
        "progress": 0,
        "message": message,
        "output_files": [],
        "error": None,
        "recoverable": True,
    })
    return summary


def duplicate_payload(record: dict) -> dict:
    summary = public_job(record)
    return {
        "code": "duplicate_leftover",
        "job_id": summary["job_id"],
        "intent_id": summary["intent_id"],
        "status": summary["status"],
        "workspace": summary["workspace"],
        "message": "A leftover with this content is already waiting. Resume that id instead of submitting again.",
    }


def receipt_document(record: dict) -> dict:
    summary = public_job(record)
    task_id = f"task-generation-{summary['job_id']}"
    return {
        "version": 1,
        "status": summary["status"],
        "receipt": {
            "commandId": summary["intent_id"],
            "result": {
                "job_id": summary["job_id"],
                "task_id": task_id,
                "status": summary["status"],
                "workspace": summary["workspace"],
            },
        },
        "task": {
            "id": task_id,
            "status": summary["status"],
            "backend_job_id": summary["job_id"],
            "workspace": summary["workspace"],
            "recoverable": True,
            "message": status_document(record)["message"],
        },
    }


def _same_intent(record: dict, intent_id: str) -> bool:
    wanted = intent_id.strip()
    if not wanted:
        return False
    if str(record.get("id") or "") == wanted:
        return True
    return intent_of(record) == wanted


def find_leftover(records: list[dict], intent_id: str, workspace: str | None = None) -> dict | None:
    for record in records:
        if workspace is not None and _workspace(record.get("workspace")) != _workspace(workspace):
            continue
        if _same_intent(record, intent_id):
            return record
    return None


def find_live(jobs: dict, intent_id: str) -> dict | None:
    for job in jobs.values():
        if isinstance(job, dict) and _same_intent(job, intent_id):
            return job
    return None


def match_fingerprint(records: list[dict], params: Any, workspace: Any) -> dict | None:
    if not isinstance(params, dict):
        return None
    fingerprint = content_fingerprint(params, workspace)
    if not fingerprint:
        return None
    for record in records:
        stored = record.get("params") if isinstance(record.get("params"), dict) else {}
        if content_fingerprint(stored, record.get("workspace")) == fingerprint:
            return record
    return None


def _require_intent(intent_id: str, operation: str) -> str:
    if not isinstance(intent_id, str) or not intent_id.strip() or len(intent_id) > _MAX_INTENT:
        raise _error(422, "invalid_command", f"{operation} requires intent_id")
    return intent_id.strip()


def _operation(name: str, mutation: bool, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "version": 1,
        "domain": "jobs",
        "mutation": mutation,
        "description": description,
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        },
    }


def _input(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": properties, "required": required or []}


def command_catalog() -> list[dict]:
    version = {"type": "integer", "const": 1}
    intent = {"type": "string", "minLength": 1, "maxLength": _MAX_INTENT}
    return [
        _operation(
            "jobs.leftovers", False,
            "List generation requests left in the durable queue after a restart. "
            "They are not running. Resume or discard one by intent_id; do not submit a second copy.",
            {"version": version, "input": _input({})}, ["version"],
        ),
        _operation(
            "jobs.resume", True,
            "Resume one leftover by input.intent_id on the existing recovery queue. "
            "Does not start a second job when that leftover is already running.",
            {"version": version, "input": _input({"intent_id": intent}, ["intent_id"]), "intent_id": intent}, ["version"],
        ),
        _operation(
            "jobs.discard", True,
            "Discard one leftover by input.intent_id. Does not cancel a job that is already running.",
            {"version": version, "input": _input({"intent_id": intent}, ["intent_id"]), "intent_id": intent}, ["version"],
        ),
    ]


def _require_version(arguments: Any, operation: str) -> dict:
    if not isinstance(arguments, dict) or type(arguments.get("version")) is not int or arguments.get("version") != 1:
        raise _error(422, "invalid_command", f"{operation} requires version 1")
    return arguments


def _intent_argument(arguments: Any, operation: str) -> str:
    """``{version, input: {intent_id}}`` like every other command; the first top-level form still works."""
    payload = _require_version(arguments, operation)
    if set(payload) - {"version", "intent_id", "input"}:
        raise _error(422, "invalid_command", f"{operation} does not accept extra fields")
    nested = payload.get("input")
    if nested is not None:
        if not isinstance(nested, dict) or set(nested) - {"intent_id"} or "intent_id" in payload:
            raise _error(422, "invalid_command", f"{operation} takes intent_id once, inside input")
        return _require_intent(nested.get("intent_id"), operation)
    return _require_intent(payload.get("intent_id"), operation)


def command_handlers(service: "JobLeftovers") -> dict[str, Callable[[Any], dict]]:
    def leftovers(arguments: Any) -> dict:
        payload = _require_version(arguments, "jobs.leftovers")
        if set(payload) - {"version", "input"} or payload.get("input") not in (None, {}):
            raise _error(422, "invalid_command", "jobs.leftovers accepts only version and an empty input")
        return service.list_response()

    def resume(arguments: Any) -> dict:
        return service.resume_response(_intent_argument(arguments, "jobs.resume"))

    def discard(arguments: Any) -> dict:
        return service.discard_response(_intent_argument(arguments, "jobs.discard"))

    return {"jobs.leftovers": leftovers, "jobs.resume": resume, "jobs.discard": discard}


class JobLeftovers:
    """Read and mutate the process-wide durable generation queue."""

    def __init__(
        self,
        *,
        queue: DurableGenerationQueue,
        jobs: dict,
        lock: threading.Lock | None = None,
        prepare: Callable[[list[dict]], list[dict]] | None = None,
        rehydrate: Callable[[dict], tuple[dict | None, bool]] | None = None,
        start: Callable[[dict], None] | None = None,
        discard_record: Callable[[dict], None] | None = None,
    ):
        self.queue = queue
        self.jobs = jobs
        self.lock = lock or threading.Lock()
        self.prepare = prepare
        self.rehydrate = rehydrate
        self.start = start
        self.discard_record = discard_record

    def reloaded(self) -> "JobLeftovers":
        """New in-memory view of the same queue file, as after a process restart."""
        return JobLeftovers(
            queue=DurableGenerationQueue(self.queue.path),
            jobs={},
            prepare=self.prepare,
            rehydrate=self.rehydrate,
            start=self.start,
            discard_record=self.discard_record,
        )

    def _queue_records_unlocked(self) -> list[dict]:
        """Durable leftovers that are not live. Never projects command recovery."""
        return self.queue.list(exclude_ids=list(self.jobs.keys()))

    def _records_unlocked(self) -> list[dict]:
        records = self._queue_records_unlocked()
        if self.prepare is None:
            return records
        prepared = self.prepare(records)
        return list(prepared or [])

    def _duplicate_unlocked(self, params: Any, workspace: Any) -> dict | None:
        # Submit/status must not run restore/filter: a sqlite failure in one
        # workspace must not 503 every generation.
        record = match_fingerprint(self._queue_records_unlocked(), params, workspace)
        if record is None:
            return None
        return duplicate_payload(record)

    def duplicate_for_submit(self, params: Any, workspace: Any) -> dict | None:
        with self.lock:
            return self._duplicate_unlocked(params, workspace)

    def enqueue(
        self,
        params: dict,
        *,
        workspace: str = "default",
        intent_id: str,
        provenance: dict | None = None,
        previous_status: str = "queued",
    ) -> dict:
        intent_id = _require_intent(intent_id, "submit")
        with self.lock:
            duplicate = self._duplicate_unlocked(params, workspace)
            if duplicate is not None:
                return duplicate
            return self._enqueue_unlocked(
                params, workspace=workspace, intent_id=intent_id,
                provenance=provenance, previous_status=previous_status,
            )

    def _enqueue_unlocked(
        self, params: dict, *, workspace: str, intent_id: str,
        provenance: dict | None, previous_status: str,
    ) -> dict:
        job_id = uuid.uuid4().hex[:8]
        command = {"command_id": intent_id}
        if isinstance(provenance, dict) and isinstance(provenance.get("command"), dict):
            command = {**provenance["command"], "command_id": intent_id}
        stored_provenance = dict(provenance or {})
        stored_provenance["command"] = command
        record = {
            "id": job_id,
            "status": previous_status or "queued",
            "created_at": time.time(),
            "params": copy.deepcopy(params),
            "workspace": _workspace(workspace),
            "provenance": stored_provenance,
        }
        self.queue.upsert(record)
        created = public_job(record)
        return {"job_id": created["job_id"], "intent_id": created["intent_id"], "status": "queued"}

    def list_response(self) -> dict:
        with self.lock:
            jobs = [public_job(record) for record in self._records_unlocked()]
        return {"version": 1, "status": "completed", "operation": "jobs.leftovers", "result": {"jobs": jobs}}

    def status_for(self, job_id: str) -> dict | None:
        if not isinstance(job_id, str) or not job_id.strip():
            return None
        with self.lock:
            record = find_leftover(self._queue_records_unlocked(), job_id.strip())
        if record is None:
            return None
        return status_document(record)

    def receipt_for(self, workspace: str, intent_id: str) -> dict | None:
        if not isinstance(intent_id, str) or not intent_id.strip():
            return None
        with self.lock:
            record = find_leftover(self._queue_records_unlocked(), intent_id.strip(), workspace=workspace)
        if record is None:
            return None
        return receipt_document(record)

    def resume_response(self, intent_id: str) -> dict:
        intent_id = _require_intent(intent_id, "jobs.resume")
        with self.lock:
            return self._resume_unlocked(intent_id)

    def _resume_unlocked(self, intent_id: str) -> dict:
        live = find_live(self.jobs, intent_id)
        if live is not None and str(live.get("status") or "") in ACTIVE_STATUSES:
            return self._resume_body(live, intent_id, started=False)
        record = find_leftover(self._records_unlocked(), intent_id)
        if record is None:
            if live is not None:
                return self._resume_body(live, intent_id, started=False)
            raise _error(404, "leftover_not_found", "No leftover matches this intent_id")
        job, created = self._rehydrate(record)
        if job is None or not created:
            if job is not None:
                return self._resume_body(job, intent_id, started=False)
            raise _error(422, "leftover_not_resumable", "This leftover has no recoverable generation request")
        self._invoke_start(job)
        return self._resume_body(job, intent_id, started=True)

    def _rehydrate(self, record: dict) -> tuple[dict | None, bool]:
        if self.rehydrate is not None:
            return self.rehydrate(record)
        return self._rehydrate_local(record)

    def _rehydrate_local(self, record: dict) -> tuple[dict | None, bool]:
        job_id = str(record.get("id") or "").strip()
        params = record.get("params") if isinstance(record.get("params"), dict) else None
        if not job_id or not isinstance(params, dict) or not params.get("model_type"):
            if job_id:
                self.queue.remove(job_id)
            return None, False
        existing = self.jobs.get(job_id)
        if isinstance(existing, dict):
            return existing, False
        job = {
            "id": job_id,
            "status": "queued",
            "progress": 0,
            "message": "Recovered · queued",
            "params": copy.deepcopy(params),
            "workspace": _workspace(record.get("workspace")),
            "provenance": copy.deepcopy(record.get("provenance") or {}),
            "output_files": [],
            "error": None,
            "recovered": True,
        }
        self.jobs[job_id] = job
        return job, True

    def _invoke_start(self, job: dict) -> None:
        if self.start is not None:
            self.start(job)
            return
        job["status"] = "completed"
        job["message"] = "Done"
        self.queue.remove(str(job.get("id") or ""))

    def _resume_body(self, job: dict, intent_id: str, *, started: bool) -> dict:
        return {
            "version": 1,
            "status": "completed",
            "operation": "jobs.resume",
            "result": {
                "job_id": str(job.get("id") or ""),
                "intent_id": intent_of(job) or intent_id,
                "status": str(job.get("status") or "queued"),
                "started": started,
            },
        }

    def discard_response(self, intent_id: str) -> dict:
        intent_id = _require_intent(intent_id, "jobs.discard")
        with self.lock:
            return self._discard_unlocked(intent_id)

    def _discard_unlocked(self, intent_id: str) -> dict:
        live = find_live(self.jobs, intent_id)
        if live is not None and str(live.get("status") or "") in ACTIVE_STATUSES:
            return self._discard_body(live, intent_id, discarded=False)
        record = find_leftover(self._records_unlocked(), intent_id)
        if record is None:
            raise _error(404, "leftover_not_found", "No leftover matches this intent_id")
        self._invoke_discard(record)
        return self._discard_body(record, intent_id, discarded=True)

    def _invoke_discard(self, record: dict) -> None:
        if self.discard_record is not None:
            self.discard_record(record)
            return
        self.queue.remove(str(record.get("id") or ""))

    def _discard_body(self, record: dict, intent_id: str, *, discarded: bool) -> dict:
        status = str(record.get("status") or "queued")
        if discarded:
            status = "discarded"
        return {
            "version": 1,
            "status": "completed",
            "operation": "jobs.discard",
            "result": {
                "job_id": str(record.get("id") or ""),
                "intent_id": intent_of(record) or intent_id,
                "discarded": discarded,
                "status": status,
            },
        }
