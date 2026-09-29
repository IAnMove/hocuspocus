"""Model3D MCP preserves REST admission and safely replays transport retries."""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from routers.model3d_commands import command_catalog, command_handlers
from routers.wangp_mcp import create_wangp_mcp_router


def arguments(**patch):
    return {"version": 1, "intent_id": "mesh-1", "input": {"workspace": "test", **patch}}


def adapters(tmp_path, generate, status=lambda _: {}):
    return command_handlers(generate=generate, status=status, journal_path=tmp_path / "journal.db")


@pytest.mark.parametrize("input", [{"prompt": "Literal low-poly tree"},
                                    {"images": {"front": "/api/v1/file/ref.png?workspace=test"}}])
def test_forwards_native_body_and_replays_after_adapter_restart(tmp_path, input):
    calls = []

    async def generate(request):
        calls.append(await request.json())
        assert request.trusted_tool == "external_agent"
        return {"job_id": "native-1", "status": "queued", "workspace": "test"}

    command = arguments(**input, preset="eco", texture_mode="none", target_face_num=900)
    first = asyncio.run(adapters(tmp_path, generate)["model3d.generate"](command))
    retry = asyncio.run(adapters(tmp_path, generate)["model3d.generate"](command))
    assert first == retry
    assert first["result"]["job_id"] == "native-1"
    assert len(calls) == 1
    assert all(calls[0][key] == value for key, value in command["input"].items())
    assert calls[0]["provenance"]["command"]["command_id"] == "mesh-1"


def test_changed_payload_conflicts_without_second_admission(tmp_path):
    async def generate(_):
        return {"job_id": "1", "workspace": "test"}

    handler = adapters(tmp_path, generate)["model3d.generate"]
    asyncio.run(handler(arguments(prompt="tree")))
    with pytest.raises(ValueError, match="different parameters"):
        asyncio.run(handler(arguments(prompt="coin")))


def test_uncertain_admission_never_submits_twice(tmp_path):
    calls = []

    async def generate(_):
        calls.append(1)
        raise HTTPException(500, "Publication failed after admission")

    handler = adapters(tmp_path, generate)["model3d.generate"]
    with pytest.raises(HTTPException) as first:
        asyncio.run(handler(arguments(prompt="tree")))
    assert first.value.status_code == 500
    with pytest.raises(HTTPException) as retry:
        asyncio.run(handler(arguments(prompt="tree")))
    assert retry.value.detail["code"] == "submission_uncertain"
    assert len(calls) == 1


def test_native_validation_error_is_replayed(tmp_path):
    calls = []

    async def generate(_):
        calls.append(1)
        raise HTTPException(400, "3D front image not found")

    handler = adapters(tmp_path, generate)["model3d.generate"]
    first = asyncio.run(handler(arguments(image_path="missing.png")))
    assert first["status"] == "failed"
    assert asyncio.run(handler(arguments(image_path="missing.png"))) == first
    assert len(calls) == 1


def test_status_keeps_native_job_and_qualifies_workspace_url(tmp_path):
    job = {"job_id": "1", "workspace": "test", "status": "completed", "url": "/api/v1/file/tree.glb"}
    handler = adapters(tmp_path, None, lambda _: job)["model3d.status"]
    reply = asyncio.run(handler({"version": 1, "input": {"workspace": "test", "job_id": "1"}}))
    assert reply["result"]["url"] == "/api/v1/file/tree.glb?workspace=test"
    assert job["url"] == "/api/v1/file/tree.glb"
    with pytest.raises(HTTPException) as error:
        asyncio.run(handler({"version": 1, "input": {"workspace": "other", "job_id": "1"}}))
    assert error.value.status_code == 404


@pytest.mark.parametrize("command", [
    {"version": True, "input": {"workspace": "test"}},
    {"version": 1, "input": {"workspace": ""}},
    {"version": 1, "input": {"workspace": "test"}, "intent_id": "../bad"},
])
def test_invalid_envelope_does_not_admit(tmp_path, command):
    handler = adapters(tmp_path, None)["model3d.generate"]
    with pytest.raises(ValueError):
        asyncio.run(handler(command))


def test_registered_mcp_transport_invokes_model3d_without_discovery(tmp_path):
    async def generate(_):
        return {"job_id": "real-lane", "status": "queued", "workspace": "test"}

    app = FastAPI()
    app.include_router(create_wangp_mcp_router(
        handlers=adapters(tmp_path, generate), command_operations=command_catalog(),
        journal_path=tmp_path / "transport.db", token_getter=lambda: "test-token",
    ))

    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/v1/mcp", headers={"Authorization": "Bearer test-token"}, json={
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "model3d.generate", "arguments": arguments(prompt="tree")},
            })

    reply = asyncio.run(call()).json()["result"]
    assert not reply["isError"]
    assert reply["structuredContent"]["result"]["job_id"] == "real-lane"
    json.dumps(command_catalog())
