"""Media facts for outputs the gallery already lists.

The background worker in ``services.media_dimensions`` fills in video sizes
and average colours after a listing was served. The gallery asks here, for
the names still missing them, so those facts arrive without reloading the
list.
"""

from __future__ import annotations

import os
from typing import Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.media_dimensions import listing_fields, media_kind

MAX_NAMES = 500


class FactsRequest(BaseModel):
    names: list[str] = Field(default_factory=list, max_length=MAX_NAMES)
    workspace: str | None = None


def create_output_facts_router(resolve: Callable[[str, str | None], str | None]) -> APIRouter:
    """``resolve(name, workspace)`` returns the file path, or ``None`` when absent."""
    router = APIRouter()

    @router.post("/api/v1/outputs/facts")
    def output_facts(request: FactsRequest):
        facts: dict[str, dict] = {}
        for name in dict.fromkeys(request.names):
            if not isinstance(name, str) or not name or len(name) > 512:
                raise HTTPException(status_code=400, detail="Invalid output name")
            path = resolve(name, request.workspace)
            kind = media_kind(path) if path else ""
            if not kind:
                continue
            try:
                stat = os.stat(path)
            except OSError:
                continue
            fields = listing_fields(kind, path, stat.st_size, stat.st_mtime)
            if fields:
                facts[name] = fields
        return {"facts": facts}

    return router
