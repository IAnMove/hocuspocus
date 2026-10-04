"""Block on an existing generation job until it finishes.

``jobs.wait`` returns the same payload as status. It does not poll the GPU or
start a model. A lifecycle update, or an event or future already stored on
the job, wakes the waiter.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import HTTPException

# ``discarded`` is terminal. ``interrupted`` and every other non-terminal
# status stay open so a resumable job is not reported as finished.
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "discarded"})
DEFAULT_TIMEOUT_S = 30
MAX_TIMEOUT_S = 120
_SIGNAL_KEYS = ("completion", "done", "_done", "finished", "event", "_event")

_condition = threading.Condition()
_version = 0


def note_job_state(snapshot: Mapping[str, Any] | None = None) -> None:
    """Wake waiters after a lifecycle update. The snapshot is not stored."""
    if snapshot is not None and not isinstance(snapshot, Mapping):
        return
    global _version
    with _condition:
        _version += 1
        _condition.notify_all()


def is_terminal(status: Any) -> bool:
    return str(status or "") in TERMINAL_STATUSES


def normalize_timeout(value: Any) -> float:
    if value is None:
        return float(DEFAULT_TIMEOUT_S)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid("timeout_s must be a number of seconds.")
    if value <= 0:
        raise _invalid("timeout_s must be greater than zero.")
    if value > MAX_TIMEOUT_S:
        return float(MAX_TIMEOUT_S)
    return float(value)


def completion_signal(job: Any) -> Any:
    """Return an event or future already stored on ``job``, if any."""
    if not isinstance(job, Mapping):
        return None
    for key in _SIGNAL_KEYS:
        candidate = job.get(key)
        if _is_signal(candidate):
            return candidate
    return None


def command_catalog() -> list[dict]:
    payload = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "job_id": {"type": "string", "minLength": 1},
            "timeout_s": {
                "type": "number",
                "exclusiveMinimum": 0,
                "maximum": MAX_TIMEOUT_S,
                "description": "Seconds to block. Default 30. Values above 120 are capped.",
            },
        },
        "required": ["job_id"],
    }
    return [{
        "name": "jobs.wait",
        "version": 1,
        "domain": "jobs",
        "mutation": False,
        "description": (
            "Block until a generation job reaches completed, failed, cancelled, "
            "or discarded, or until timeout_s. Returns the same payload as status, "
            "including progress when the queue already has it. When timeout_s elapses "
            "first it returns the live status with timed_out: true (not an error); call "
            "again to keep waiting. Does not poll the GPU or start a model. An "
            "interrupted job stays open because it can be resumed."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "const": 1},
                "input": payload,
            },
            "required": ["version", "input"],
        },
    }]


def command_handlers(read_status: Callable[[str], dict], lookup_job: Callable[[str], Any]):
    async def jobs_wait(arguments: dict) -> dict:
        payload = _require_input(arguments)
        job_id = _require_job_id(payload)
        timeout_s = payload["timeout_s"] if "timeout_s" in payload else None
        return await asyncio.to_thread(
            wait_for_job,
            job_id,
            timeout_s,
            read_status=read_status,
            lookup_job=lookup_job,
        )

    return {"jobs.wait": jobs_wait}


def wait_for_job(
    job_id: str,
    timeout_s: Any = None,
    *,
    read_status: Callable[[str], dict],
    lookup_job: Callable[[str], Any],
) -> dict:
    """Block until status is terminal or ``timeout_s`` elapses."""
    deadline = time.monotonic() + normalize_timeout(timeout_s)
    signal_seen = False
    while True:
        seen = _version_now()
        payload = _public_status(read_status(job_id))
        if is_terminal(payload.get("status")):
            return payload
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _timed_out(payload)
        signal = completion_signal(_record(lookup_job, job_id))
        if signal is not None and not _signaled(signal):
            signal_seen = False
            _wait_signal(signal, remaining)
            continue
        if signal is not None and _signaled(signal) and not signal_seen:
            signal_seen = True
            continue
        signal_seen = False
        _wait_change(seen, remaining)


def _version_now() -> int:
    with _condition:
        return _version


def _wait_change(seen: int, timeout: float) -> None:
    if timeout <= 0:
        return
    with _condition:
        if _version != seen:
            return
        _condition.wait(timeout)


def _record(lookup_job: Callable[[str], Any] | None, job_id: str) -> Any:
    if lookup_job is None:
        return None
    return lookup_job(job_id)


def _public_status(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail={
            "code": "invalid_status",
            "message": "Status payload must be an object.",
            "retryable": False,
        })
    return dict(payload)


def _timed_out(payload: dict) -> dict:
    """The job is still open: return its live status, not an error.

    An MCP error envelope reads ``status: failed`` at the top level, which made
    clients treat a long but healthy job as a failure. ``code`` stays for
    callers that matched it.
    """
    return {**payload, "timed_out": True, "code": "timeout", "retryable": True}


def _invalid(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={
        "code": "invalid_command",
        "message": message,
        "retryable": False,
    })


def _require_input(arguments: Any) -> dict:
    version_ok = isinstance(arguments, dict) and arguments.get("version") == 1
    if not version_ok or not isinstance(arguments.get("input"), dict):
        raise _invalid("Use version 1 and an input object.")
    return arguments["input"]


def _require_job_id(payload: Mapping[str, Any]) -> str:
    job_id = payload.get("job_id")
    if isinstance(job_id, str) and job_id.strip():
        return job_id.strip()
    raise _invalid("job_id is required.")


def _is_signal(value: Any) -> bool:
    if value is None or isinstance(value, (str, bytes, int, float, bool, dict, list, tuple)):
        return False
    if callable(getattr(value, "result", None)) and callable(getattr(value, "done", None)):
        return True
    return callable(getattr(value, "wait", None))


def _signaled(signal: Any) -> bool:
    is_set = getattr(signal, "is_set", None)
    if callable(is_set):
        return bool(is_set())
    done = getattr(signal, "done", None)
    if callable(done):
        return bool(done())
    return False


def _wait_signal(signal: Any, timeout: float) -> None:
    if timeout <= 0:
        return
    if callable(getattr(signal, "result", None)) and callable(getattr(signal, "done", None)):
        try:
            signal.result(timeout=timeout)
        except Exception:
            return
        return
    wait = getattr(signal, "wait", None)
    if callable(wait):
        wait(timeout)
