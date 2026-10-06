"""The Wizard reaches the media tools through /api/v1/media/commands, the same handlers MCP agents call."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from routers.production_media import create_production_media_router


def test_the_media_commands_route_dispatches_to_the_tool_handlers():
    seen = []

    async def frame(arguments):
        seen.append(arguments)
        return {"version": 1, "status": "completed", "operation": "media.frame", "result": {"file": "clip-frame-last.png"}}

    router = create_production_media_router({"media.frame": frame})
    routes = {(route.path, tuple(route.methods)[0]): route.endpoint for route in router.routes}
    assert routes[("/api/v1/media/commands", "GET")]() == {"version": 1, "operations": ["media.frame"]}
    post = routes[("/api/v1/media/commands", "POST")]
    reply = asyncio.run(post({"operation": "media.frame", "version": 1, "input": {"workspace": "ws", "source": "a.mp4", "at": "last"}}))
    assert reply["result"]["file"] == "clip-frame-last.png"
    assert seen == [{"version": 1, "input": {"workspace": "ws", "source": "a.mp4", "at": "last"}}]
    with pytest.raises(HTTPException) as unknown:
        asyncio.run(post({"operation": "shell.run", "version": 1, "input": {}}))
    assert unknown.value.status_code == 422 and unknown.value.detail["code"] == "unknown_operation"
