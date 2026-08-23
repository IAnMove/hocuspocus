"""HTTP surface for the persistent style library."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from services.style_library import (
    StyleImportPreflightError,
    StyleLibrary,
    StyleManifestDegradedError,
)


def create_style_library_router(library: StyleLibrary) -> APIRouter:
    router = APIRouter(prefix="/api/v1/style-library", tags=["style-library"])

    @router.get("/sources")
    def list_sources():
        return {"sources": library.source_status()}

    @router.get("/styles")
    def list_styles(
        model_family: str = "minimax",
        source_id: str = "",
        collection: str = "",
        group: str = "",
        q: str = "",
        sort: str = "source_order",
        offset: int = 0,
        limit: int = 60,
    ):
        try:
            return library.list_styles(
                model_family=model_family,
                source_id=source_id,
                collection=collection,
                group=group,
                query=q,
                sort=sort,
                offset=offset,
                limit=limit,
            )
        except StyleManifestDegradedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/imports/minimax-h3-1k")
    def import_minimax_h3_1k():
        try:
            return library.start_minimax_import()
        except StyleImportPreflightError as exc:
            raise HTTPException(status_code=507, detail=exc.detail()) from exc
        except StyleManifestDegradedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/imports/minimax-h3-1k/preflight")
    def import_minimax_h3_1k_preflight():
        return library.import_preflight()

    @router.post("/manifest/recover")
    def recover_manifest():
        try:
            return library.recover_manifest()
        except StyleManifestDegradedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/imports/{job_id}")
    def import_status(job_id: str):
        job = library.import_status(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Style import job not found")
        return job

    @router.post("/imports/{job_id}/cancel")
    def cancel_import(job_id: str):
        job = library.cancel_import(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Style import job not found")
        return job

    @router.get("/styles/{style_id}/preview")
    def style_preview(style_id: str):
        try:
            path = library.preview_path(style_id)
        except (KeyError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Style preview not found")
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @router.get("/styles/{style_id}/video")
    def style_video(style_id: str):
        try:
            path = library.video_path(style_id)
        except (KeyError, FileNotFoundError):
            raise HTTPException(status_code=404, detail="Style video not found")
        return FileResponse(path, media_type="video/mp4")

    @router.delete("/styles/{style_id}")
    def delete_style(style_id: str, confirm: bool = Query(False)):
        if not confirm:
            raise HTTPException(status_code=400, detail="Deletion requires confirm=true")
        try:
            return library.delete_style(style_id)
        except StyleManifestDegradedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError:
            raise HTTPException(status_code=404, detail="Style not found")

    return router
