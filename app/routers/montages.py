"""HTTP projection of editable montages (``<name>.montage.json``).

The Video Editor lists, opens, saves and exports montages here; external agents
use the same service through the MCP ``montages.*`` operations.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from services.montage_commands import MontageCommands, command_catalog
from services.montage_documents import MontageError


def _raise(error: MontageError) -> None:
    raise HTTPException(error.status, {"code": error.code, "message": str(error)}) from error


def create_montages_router(commands: MontageCommands) -> APIRouter:
    router = APIRouter()

    async def run(name: str, payload: dict) -> dict:
        try:
            return (await commands.execute_async(name, {"version": 1, "input": payload}))["result"]
        except MontageError as error:
            _raise(error)
            raise  # pragma: no cover - _raise always raises

    async def body(request: Request) -> dict:
        data = await request.body()
        if len(data) > 3 * 1024 * 1024:
            raise HTTPException(413, "Montage request exceeds 3 MB")
        try:
            value = await request.json()
        except ValueError as error:
            raise HTTPException(422, "Request must be valid JSON") from error
        if not isinstance(value, dict):
            raise HTTPException(422, "Request must be a JSON object")
        return value

    @router.get("/api/v1/montages/commands")
    def catalog():
        return {"version": 1, "operations": command_catalog()}

    @router.get("/api/v1/montages")
    async def list_montages(workspace: str):
        return await run("montages.list", {"workspace": workspace})

    @router.get("/api/v1/montages/{file}")
    async def get_montage(file: str, workspace: str):
        return await run("montages.get", {"workspace": workspace, "file": file})

    @router.post("/api/v1/montages")
    async def save_montage(request: Request):
        payload = await body(request)
        allowed = {"workspace", "montage", "file", "expected_revision"}
        return await run("montages.save", {key: value for key, value in payload.items() if key in allowed})

    @router.get("/api/v1/montages/{file}/shots")
    async def montage_shots(file: str, workspace: str):
        return await run("montages.shots.get", {"workspace": workspace, "file": file})

    @router.post("/api/v1/montages/{file}/shots/{clip_id}/regenerate", status_code=202)
    async def regenerate_shot(file: str, clip_id: str, request: Request):
        payload = await body(request)
        allowed = {"workspace", "intent_id", "expected_revision", "prompt", "seed"}
        return await run("montages.shot.regenerate",
                         {"file": file, "clip_id": clip_id, **{key: value for key, value in payload.items() if key in allowed}})

    @router.post("/api/v1/montages/{file}/shots/{clip_id}/select")
    async def select_take(file: str, clip_id: str, request: Request):
        payload = await body(request)
        allowed = {"workspace", "take_id", "expected_revision", "retime"}
        return await run("montages.shot.select",
                         {"file": file, "clip_id": clip_id, **{key: value for key, value in payload.items() if key in allowed}})

    @router.post("/api/v1/montages/{file}/export", status_code=202)
    async def export_montage(file: str, workspace: str):
        return await run("montages.export", {"workspace": workspace, "file": file})

    return router


__all__ = ["create_montages_router"]
