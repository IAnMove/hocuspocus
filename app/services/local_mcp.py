"""Call the server's own MCP tool handlers from a worker thread, without HTTP or a token.

Long server jobs (the Series episode render) chain the same tools an agent
would use: generation, waiting, analysis, scene save and export, take import.
Calling the handlers in process keeps one path for every caller and does not
require the user to enable MCP access. Coroutines run on the server's event
loop when it is known (as they would for a real MCP request); otherwise on a
private loop, which is what tests use.
"""
from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Callable
from typing import Any

from services.agent_activity import SERVER_CALLER, caller_scope


async def _as_server(awaitable: Any) -> Any:
    """Run a handler coroutine inside the server caller scope on whichever loop executes it."""
    with caller_scope(SERVER_CALLER):
        return await awaitable


class LocalMcp:
    def __init__(self, handlers: Callable[[], dict[str, Callable[[Any], Any]]], timeout: float = 1800) -> None:
        self._handlers = handlers
        self._timeout = timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._loop = loop

    def _run(self, value: Any) -> Any:
        if not inspect.isawaitable(value):
            return value
        value = _as_server(value)
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not loop:
                return asyncio.run_coroutine_threadsafe(value, loop).result(self._timeout)
        return asyncio.run(value)

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """The tool's result, or ``{"_is_error": True, "error": {...}}`` like an MCP tool error."""
        from fastapi import HTTPException

        handler = self._handlers().get(tool)
        if not callable(handler):
            return {"_is_error": True, "error": {"code": "unknown_tool", "message": f"{tool} is not available", "retryable": False}}
        try:
            with caller_scope(SERVER_CALLER):  # the server's own job: never reported as agent work
                value = handler(arguments)
            result = self._run(value)
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail, dict) else {"code": "failed", "message": str(error.detail)}
            return {"_is_error": True, "error": {**detail, "status": error.status_code}}
        return result if isinstance(result, dict) else {"result": result}
