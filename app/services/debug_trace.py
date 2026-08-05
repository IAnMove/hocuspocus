"""Opt-in structured debug tracing for reproducible Maestro sessions.

The trace is deliberately disabled until :func:`configure` supplies an
enabled callback. Records are newline-delimited JSON so a partial/crashed run
remains readable. Secrets and binary payloads are redacted before disk I/O.
"""

from __future__ import annotations

import functools
import inspect
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable


_write_lock = threading.Lock()
_enabled: Callable[[], bool] = lambda: False
_log_dir: Callable[[], str] = lambda: os.path.join("logs", "debug")
_session_id = uuid.uuid4().hex
_sequence = 0
_context: ContextVar[dict[str, Any]] = ContextVar("maestro_debug_context", default={})
_SENSITIVE_KEYS = {
    "api_key", "apikey", "authorization", "password", "secret", "token",
    "access_token", "refresh_token", "cookie", "credential", "credentials",
}


def configure(*, enabled: Callable[[], bool], log_dir: Callable[[], str]) -> None:
    global _enabled, _log_dir
    _enabled = enabled
    _log_dir = log_dir


def is_enabled() -> bool:
    try:
        return bool(_enabled())
    except Exception:
        return False


def current_log_path() -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return os.path.abspath(os.path.join(_log_dir(), f"maestro-debug-{day}.jsonl"))


@contextmanager
def context_scope(**fields: Any):
    """Correlate nested records without coupling services to one workflow."""
    merged = {**_context.get(), **{k: v for k, v in fields.items() if v not in (None, "")}}
    token = _context.set(merged)
    try:
        yield
    finally:
        _context.reset(token)


def current_context() -> dict[str, Any]:
    return dict(_context.get())


def _sanitize(value: Any, key: str = "", depth: int = 0) -> Any:
    """Return JSON-safe data while retaining prompts and textual responses."""
    lower_key = key.lower()
    if (
        lower_key in _SENSITIVE_KEYS
        or lower_key.endswith("_api_key")
        or lower_key.endswith("_password")
        or lower_key.endswith("_secret")
        or lower_key.endswith("_credential")
    ):
        return "<redacted>"
    if depth > 12:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, bytes):
        return f"<binary:{len(value)} bytes>"
    if isinstance(value, str):
        if value.startswith("data:") and ";base64," in value[:160]:
            return f"<base64-data:{len(value)} chars>"
        # Retain complete normal prompts/results, but never allow a single
        # pathological value to grow the trace without bound.
        if len(value) > 2_000_000:
            return value[:2_000_000] + f"<truncated:{len(value) - 2_000_000} chars>"
        return value
    if isinstance(value, dict):
        return {str(k): _sanitize(v, str(k), depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(v, key, depth + 1) for v in value]
    return str(value)


def trace_event(category: str, action: str, **fields: Any) -> str | None:
    """Append one atomic JSONL record. Tracing must never break the app."""
    if not is_enabled():
        return None
    event_id = str(fields.pop("event_id", "") or uuid.uuid4().hex)
    global _sequence
    with _write_lock:
        _sequence += 1
        sequence = _sequence
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": _session_id,
        "sequence": sequence,
        "process_id": os.getpid(),
        "thread": threading.current_thread().name,
        "event_id": event_id,
        "category": category,
        "action": action,
        "context": _sanitize(_context.get()),
        **_sanitize(fields),
    }
    try:
        path = current_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str)
        with _write_lock, open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return event_id
    except Exception as exc:
        print(f"[DebugTrace] Failed to write trace: {exc}")
        return None


def start_session(**metadata: Any) -> str | None:
    """Write a reconstruction anchor after launch configuration is available."""
    return trace_event("session", "start", metadata=metadata, log_path=current_log_path())


def trace_llm_usage(usage: dict[str, Any]) -> None:
    """Attach provider-reported token usage to the active decorated call."""
    if not usage or not is_enabled():
        return
    call_id = str(_context.get().get("llm_call_id") or "")
    trace_event(
        "llm_call", "usage", event_id=call_id or None, phase="usage", usage=usage,
    )


def trace_llm_call(action: str, context: Callable[[], dict[str, Any]] | None = None):
    """Decorator recording full sanitized LLM arguments, result, and errors."""
    def decorate(fn):
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            if not is_enabled():
                return fn(*args, **kwargs)
            call_id = uuid.uuid4().hex
            started = time.monotonic()
            try:
                bound = signature.bind_partial(*args, **kwargs)
                bound.apply_defaults()
                request_data = dict(bound.arguments)
            except Exception:
                request_data = {"args": args, "kwargs": kwargs}
            try:
                call_context = context() if context else {}
            except Exception:
                call_context = {}
            with context_scope(llm_call_id=call_id, **call_context):
                trace_event(
                    "llm_call", action, event_id=call_id, phase="request",
                    request=request_data,
                )
                try:
                    result = fn(*args, **kwargs)
                except Exception as exc:
                    trace_event(
                        "llm_call", action, event_id=call_id, phase="error",
                        duration_ms=round((time.monotonic() - started) * 1000, 2),
                        error={"type": type(exc).__name__, "message": str(exc)},
                    )
                    raise
                trace_event(
                    "llm_call", action, event_id=call_id, phase="response",
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                    response=result,
                )
            return result

        return wrapped
    return decorate


def sanitize_for_trace(value: Any) -> Any:
    """Public sanitizer for HTTP middleware and tests."""
    return _sanitize(value)
