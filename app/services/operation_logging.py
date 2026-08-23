"""Small structured operation logger with workflow correlation.

Records are single-line JSON for console collectors.  Correlation is inherited
from Director/debug scopes and canonical task scopes, while explicit fields
always win.  The adapter is intentionally independent of FastAPI and model
code so planners and registries can import it safely.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator


_context: ContextVar[dict[str, Any]] = ContextVar(
    "loreframe_operation_context",
    default={},
)
_CORRELATION_FIELDS = (
    "activity_id",
    "pipeline_id",
    "workspace",
    "task_id",
    "root_task_id",
    "request_id",
)


@contextmanager
def operation_scope(**fields: Any) -> Iterator[dict[str, Any]]:
    merged = {
        **_context.get(),
        **{str(key): value for key, value in fields.items() if value not in (None, "")},
    }
    token = _context.set(merged)
    try:
        yield dict(merged)
    finally:
        _context.reset(token)


def operation_context(**fields: Any) -> dict[str, Any]:
    """Merge operation, canonical-task and debug-trace correlation."""

    merged: dict[str, Any] = dict(_context.get())
    try:
        from services.task_manager import current_task_context

        merged.update(current_task_context())
    except (ImportError, AttributeError):
        pass
    try:
        from services.debug_trace import current_context

        merged.update(current_context())
    except (ImportError, AttributeError):
        pass
    merged.update({
        str(key): value for key, value in fields.items() if value not in (None, "")
    })
    if not merged.get("activity_id"):
        merged["activity_id"] = (
            merged.get("root_task_id")
            or merged.get("root_id")
            or merged.get("request_id")
            or ""
        )
    return merged


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _safe(value: Any) -> Any:
    try:
        from services.task_manager import redact_sensitive_data

        return _json_safe(redact_sensitive_data(value))
    except (ImportError, AttributeError):
        return _json_safe(value)


def log_operation(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    *,
    error: BaseException | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Emit one redacted JSON operation record and return its payload."""

    context = operation_context(**fields)
    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": str(event),
        "message": str(message),
    }
    for key in _CORRELATION_FIELDS:
        value = context.pop(key, None)
        if value not in (None, ""):
            payload[key] = value
    if error is not None:
        payload["error"] = {
            "type": type(error).__name__,
            "message": str(error),
        }
    payload.update(context)
    payload = _safe(payload)
    logger.log(level, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    try:
        from services import debug_trace

        debug_trace.trace_event("operation", str(event), **payload)
    except (ImportError, AttributeError):
        pass
    return payload


__all__ = ["log_operation", "operation_context", "operation_scope"]
