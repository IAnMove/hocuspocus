"""Shared full/core writing coach; proposals use the existing scoped LLM routing."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from services.writing_guide import parse_result, prepare_request, prompts, response_schema


def create_writing_guide_router(*, ensure_llm_loaded: Callable, writing_override: Callable) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/writing-guide/propose")
    async def propose(request: Request, body: dict):
        try:
            prepared = prepare_request(body)
            override = writing_override(body)
        except ValueError as error:
            raise HTTPException(400, {"code": "invalidRequest", "message": str(error)}) from error
        from services import llm_service
        from services.task_manager import CancellationToken
        token = CancellationToken()
        activity_id = f"writing-guide-{uuid.uuid4().hex}"
        started = time.monotonic()

        def generate():
            llm_service.begin_activity_tracking(activity_id, detail="Writing guide")
            def run():
                prompt, system = prompts(prepared)
                args = dict(prompt=prompt, system_prompt=system, json_schema=response_schema(prepared),
                            max_new_tokens=2400, temperature=0.6, cancellation_token=token)
                if override:
                    raw = llm_service.generate_openai_compatible(**args, model_id=override["model"],
                                                               base_url=override["base_url"], api_key=override["api_key"])
                else:
                    ensure_llm_loaded()
                    raw = llm_service.generate(**args, enable_thinking=False)
                return parse_result(raw, prepared)
            try:
                result = llm_service.run_with_activity_tracking(activity_id, run)
                usage = llm_service.get_activity_tracking(activity_id).get("usage", {})
                return {**result, "usage": usage if usage.get("calls") else None,
                        "elapsedSeconds": round(time.monotonic() - started, 3),
                        "provider": str(body.get("writingProvider") or "maestro"),
                        "model": override["model"] if override else llm_service.get_status().get("model_id", "")}
            finally:
                llm_service.update_activity_tracking(activity_id, status="terminal")

        job = asyncio.create_task(asyncio.to_thread(generate))
        try:
            while not job.done():
                await asyncio.wait({job}, timeout=0.25)
                if await request.is_disconnected():
                    token.cancel("Writing guide client disconnected")
            return await job
        except (ValueError, json.JSONDecodeError) as error:
            raise HTTPException(502, {"code": "invalidProposal", "message": str(error)}) from error
        except asyncio.CancelledError:
            token.cancel("Writing guide request cancelled")
            raise
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(502, {"code": "providerFailed", "message": "Writing provider failed"}) from error

    return router
