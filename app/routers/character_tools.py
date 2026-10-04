"""Browser routes for the one-click character tools; MCP keeps its own envelope.

The Character Creator keys a generated pose (``studio.key``) and checks a
designed voice (``qa.speech``). Both routes take the command input as the
body and call the same handler as the MCP tool, so results, errors and the
``intent_id`` replay are identical.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _envelope(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail={"code": "invalid_command", "message": "Send a JSON object", "retryable": False})
    envelope: dict[str, Any] = {"version": 1, "input": {key: value for key, value in body.items() if key != "intent_id"}}
    if "intent_id" in body:
        envelope["intent_id"] = body["intent_id"]
    return envelope


def create_character_tools_router(*, studio_key: Handler, speech_qa: Handler) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/studio/key")
    async def key_image(request: Request):
        """Key a workspace image on a green, blue or magenta screen (the studio.key command)."""
        return await studio_key(_envelope(await request.json()))

    @router.post("/api/v1/qa/speech")
    async def check_speech(request: Request):
        """Transcript, error rate, pitch and pace of a workspace take (the qa.speech command)."""
        return await speech_qa(_envelope(await request.json()))

    return router
