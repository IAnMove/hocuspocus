"""Rig MCP uses native jobs, durable retry identity and exact workspace reads."""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from routers.model3d_commands import command_handlers as model_handlers
from routers.model3d_rig_commands import command_catalog, command_handlers
from routers.wangp_mcp import create_wangp_mcp_router


def request(**patch):
    return {"version": 1, "intent_id": "rig-pilot", "input": {
        "workspace": "movie", "source": "hero.glb", "engine": "unirig", "animations": ["idle", "walk"], **patch}}


def test_native_rig_body_and_retries_keep_one_job(tmp_path):
    calls = []

    async def generate(req):
        calls.append(await req.json())
        return {"workspace": "movie", "job_id": "native-rig", "status": "queued"}

    def handlers(): return command_handlers(generate=generate, status=None, journal_path=tmp_path / "requests.db")
    first = asyncio.run(handlers()["model3d.rig"](request(rig_profile="humanoid", seed=64)))
    assert asyncio.run(handlers()["model3d.rig"](request(rig_profile="humanoid", seed=64))) == first
    assert first["operation"] == "model3d.rig"
    assert len(calls) == 1 and calls[0]["engine"] == "unirig"
    assert calls[0]["animations"] == ["idle", "walk"]
    assert calls[0]["source"] == "hero.glb"
    assert calls[0]["provenance"]["capability"] == "model3d.rig"
    with pytest.raises(ValueError, match="different parameters"):
        asyncio.run(handlers()["model3d.rig"](request(source="other.glb")))


def test_model_generation_and_rig_intents_cannot_collide(tmp_path):
    calls = []

    async def generate(req):
        calls.append(await req.json())
        return {"workspace": "movie", "job_id": str(len(calls)), "status": "queued"}

    model = model_handlers(generate=generate, status=None, journal_path=tmp_path / "shared.db")
    rig = command_handlers(generate=generate, status=None, journal_path=tmp_path / "shared.db")
    a = asyncio.run(model["model3d.generate"](request()))
    b = asyncio.run(rig["model3d.rig"](request()))
    assert a["result"]["job_id"] != b["result"]["job_id"]
    assert len(calls) == 2


def test_completed_rig_preserves_clips_and_cannot_be_read_from_another_workspace(tmp_path):
    job = {"workspace": "movie", "status": "completed", "url": "/api/v1/file/hero-rig.glb",
           "animations": ["Idle Sway", "Walk Cycle"], "joint_count": 22}
    handlers = command_handlers(generate=None, status=lambda _: job, journal_path=tmp_path / "requests.db")
    args = {"version": 1, "input": {"workspace": "movie", "job_id": "native-rig"}}
    result = asyncio.run(handlers["model3d.rig.status"](args))
    assert result["result"]["url"] == "/api/v1/file/hero-rig.glb?workspace=movie"
    assert result["result"]["animations"] == job["animations"]
    assert job["url"] == "/api/v1/file/hero-rig.glb"
    args["input"]["workspace"] = "another"
    with pytest.raises(HTTPException) as error: asyncio.run(handlers["model3d.rig.status"](args))
    assert error.value.status_code == 404


def test_rig_is_callable_through_authenticated_mcp_without_discovery(tmp_path):
    async def generate(_): return {"workspace": "movie", "job_id": "real-rig-job", "status": "queued"}
    app = FastAPI()
    app.include_router(create_wangp_mcp_router(token_getter=lambda: "test-token",
        handlers=command_handlers(generate=generate, status=None, journal_path=tmp_path / "requests.db"),
        command_operations=command_catalog(), journal_path=tmp_path / "mcp.db"))

    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/v1/mcp", headers={"Authorization": "Bearer test-token"}, json={
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "model3d.rig", "arguments": request()}})

    result = asyncio.run(call()).json()["result"]
    assert not result["isError"]
    assert result["structuredContent"]["result"]["job_id"] == "real-rig-job"
    json.dumps(command_catalog())


def test_humanoid_engine_is_a_rig_option_with_pose():
    submit = command_catalog()[0]
    payload = submit["inputSchema"]["properties"]["input"]["properties"]
    assert payload["engine"]["enum"] == ["unirig", "procedural", "humanoid"]
    assert payload["pose"]["enum"] == ["t", "a"]
    assert "not_humanoid" in submit["description"]
