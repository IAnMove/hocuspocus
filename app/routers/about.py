"""About page data: repository, author and the exact deployed commit."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from app_identity import about_payload


def create_about_router(ui_dist: str | Path) -> APIRouter:
    router = APIRouter(tags=["about"])

    @router.get("/api/v1/about")
    def get_about():
        return about_payload(Path(ui_dist))

    return router
