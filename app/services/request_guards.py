"""Request guards moved verbatim from the full server.

The full server registers the exception handler and the two HTTP middleware
in their original order. Starlette runs the last middleware it was given
first. These functions call libraries and ``debug_trace`` directly. None of
those is a full-server object, so this module has no bind call.
"""
import json
import re
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from services import debug_trace, execution_mode

async def execution_mode_error_handler(
    _request: Request,
    exc: execution_mode.ExecutionModeError,
):
    """Keep policy refusals explicit across every specialist submission route."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})

async def protect_cross_origin_mutations(request: Request, call_next):
    """Reject browser mutations from a different origin, including on LAN."""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin:
            from urllib.parse import urlsplit

            try:
                origin_host = (urlsplit(origin).netloc or "").casefold()
            except ValueError:
                origin_host = ""
            request_host = str(request.headers.get("host") or "").casefold()
            local_hosts = {"localhost", "127.0.0.1", "[::1]"}
            origin_name = origin_host.rsplit(":", 1)[0]
            request_name = request_host.rsplit(":", 1)[0]
            same_origin_host = bool(origin_host and origin_host == request_host)
            local_proxy = origin_name in local_hosts and request_name in local_hosts
            pinokio_proxy = bool(re.fullmatch(r"\d+\.localhost(?::\d+)?", origin_host))
            if not (same_origin_host or local_proxy or pinokio_proxy):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin API mutations are not allowed"},
                )
    return await call_next(request)

async def trace_user_mutations(request: Request, call_next):
    """Record reconstructible user/API actions while debug tracing is on."""
    should_trace = (
        debug_trace.is_enabled()
        and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path != "/api/v1/debug/user-action"
    )
    event_id = uuid.uuid4().hex if should_trace else ""
    started = time.monotonic()
    if should_trace:
        content_type = request.headers.get("content-type", "")
        request_body = None
        if "application/json" in content_type:
            try:
                raw_body = await request.body()
                request_body = json.loads(raw_body) if raw_body else None
            except Exception as exc:
                request_body = {"parse_error": str(exc)}
        elif content_type:
            request_body = f"<{content_type}; body omitted>"
        from services.task_manager import redact_sensitive_data

        debug_trace.trace_event(
            "user_action", "api_request", event_id=event_id, phase="request",
            method=request.method, path=request.url.path,
            query=redact_sensitive_data(dict(request.query_params)),
            body=redact_sensitive_data(request_body),
        )
    try:
        with debug_trace.context_scope(
            request_id=event_id or None,
            http_method=request.method,
            http_path=request.url.path,
        ):
            response = await call_next(request)
    except Exception as exc:
        if should_trace:
            debug_trace.trace_event(
                "user_action", "api_request", event_id=event_id, phase="error",
                method=request.method, path=request.url.path,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                error={"type": type(exc).__name__, "message": str(exc)},
            )
        raise
    if should_trace:
        debug_trace.trace_event(
            "user_action", "api_request", event_id=event_id, phase="response",
            method=request.method, path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
    return response
