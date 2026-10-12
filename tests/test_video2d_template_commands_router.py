"""The Wizard reads the 2D music cards through /api/v1/scenes/templates/commands, the handlers MCP agents call."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from routers.video2d_catalog import TEMPLATE_COMMANDS, create_video2d_template_commands_router
from services.video2d_catalogs import query_handlers


def _post(handlers):
    router = create_video2d_template_commands_router(lambda: handlers)
    return {(route.path, tuple(route.methods)[0]): route.endpoint for route in router.routes}[("/api/v1/scenes/templates/commands", "POST")]


def test_the_route_runs_the_catalog_handler_with_the_mcp_envelope():
    post = _post(query_handlers())
    reply = asyncio.run(post({"operation": "scenes.catalog", "version": 1, "input": {"kind": "templates", "id": "music-pinball"}}))
    assert reply["operation"] == "scenes.catalog" and reply["result"]


def test_suggest_reaches_whatever_handler_the_server_registers_and_other_tools_do_not():
    seen = []

    def suggest(arguments):
        seen.append(arguments)
        return {"version": 1, "status": "completed", "result": {"templates": [{"id": "music-pinball", "reason": "one figure, bounce"}]}}

    post = _post({"scenes.templates.suggest": suggest, "production.run": lambda arguments: pytest.fail("not a 2D card tool")})
    reply = asyncio.run(post({"operation": "scenes.templates.suggest", "version": 1, "input": {"line": "she bounces", "speakers": 1}}))
    assert reply["result"]["templates"][0]["id"] == "music-pinball"
    assert seen == [{"version": 1, "input": {"line": "she bounces", "speakers": 1}}]
    for operation in ("production.run", "scenes.template.compile"):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(post({"operation": operation, "version": 1, "input": {}}))
        assert refused.value.status_code == 422 and refused.value.detail["code"] == "unknown_operation"
    assert "scenes.templates.suggest" in TEMPLATE_COMMANDS


def test_a_catalog_refusal_keeps_its_code():
    post = _post(query_handlers())
    with pytest.raises(HTTPException) as refused:
        asyncio.run(post({"operation": "scenes.catalog", "version": 2, "input": {}}))
    assert refused.value.status_code == 422 and refused.value.detail["code"] == "catalog_bad_envelope"
