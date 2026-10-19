"""HTTP for an agent's review of a character's animation (``services/character_animation_review.py``).

``POST /api/v1/character-kits/animations/review`` is the door of the ``characters.animation.review`` MCP tool and the Wizard's
``review_character_animation``: the actor is always ``agent``, so in review mode (``agent_autonomy``, the default) it answers 403 with
the way to approve by hand, and in «Modo un solo disparo» it approves or rejects and stamps ``reviewedBy: agent`` with the note. A person
reviews in Characters › Animaciones, which edits the kit directly and stamps ``reviewedBy: person``.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from services.character_animation_review import AnimationReviewError, review_kit_animation


class ReviewAnimation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=120)
    kitId: str = Field(min_length=1, max_length=160)
    animation: str = Field(min_length=1, max_length=64)
    decision: str = Field(pattern="^(approve|reject)$")
    note: str = Field(default="", max_length=500)


def create_character_animation_review_router(*, workspace_dir: Callable[[str], str], services: Callable[[], Mapping[str, Any]]) -> APIRouter:
    router = APIRouter(prefix="/animations", tags=["Character kits"])  # mounted under /api/v1/character-kits

    @router.post("/review")
    async def review_animation(body: ReviewAnimation):
        """Approve or reject an animation of a saved character as an agent. Only in «Modo un solo disparo» (agent_autonomy = one_shot)."""
        try:
            folder = workspace_dir(body.workspace)
            return {"review": await run_in_threadpool(review_kit_animation, folder, body.kitId, body.animation, body.decision, body.note, "agent",
                                                      services=services())}
        except AnimationReviewError as error:
            raise HTTPException(status_code=error.status, detail={"code": error.code, "message": str(error)}) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail={"code": "invalid_request", "message": str(error)}) from error

    return router
