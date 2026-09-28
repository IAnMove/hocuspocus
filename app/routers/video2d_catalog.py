"""HTTP read of the aggregated Video 2D catalog. No GPU, save or export."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services.video2d_catalogs import CatalogError, query_catalog


def create_video2d_catalog_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/scenes/catalog")
    def catalog(kind: str | None = None, family: str | None = None, q: str | None = None):
        payload = {
            key: value
            for key, value in (("kind", kind), ("family", family), ("q", q))
            if value is not None
        }
        try:
            return query_catalog(payload)
        except CatalogError as error:
            raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": False}) from error

    return router


__all__ = ["create_video2d_catalog_router"]
