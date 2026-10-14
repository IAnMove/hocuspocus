"""Model list, files, reload, options and the active-download snapshot.

Each factory is mounted at the first route it replaces, so the registration
order of the full server stays the same. The handlers live in
``services.model_downloads`` and ``services.model_options``.
"""
from __future__ import annotations

from fastapi import APIRouter

from services import model_downloads, model_options


def create_model_list_router():
    """GET /api/v1/models at the full server's original position."""
    router = APIRouter()

    @router.get("/api/v1/models")
    def list_models(detail: bool = True):
        """List available model families and model types.

        HTTP defaults to the full catalog so the Studio UI keeps working.
        Pass detail=false for the short MCP summary.
        """
        return model_downloads.list_models(detail)

    return router


def create_model_files_router():
    """Debug, delete, download, status, resolutions and defaults, in that order."""
    router = APIRouter()

    @router.get("/api/v1/models/{model_type}/debug")
    def debug_model(model_type: str):
        """Debug: show raw model definition and download check."""
        return model_downloads.debug_model(model_type)

    @router.delete("/api/v1/models/{model_type}")
    def delete_model(model_type: str):
        """Delete a model's checkpoint files from disk."""
        return model_downloads.delete_model(model_type)

    @router.post("/api/v1/models/{model_type}/download")
    def download_model(model_type: str):
        """Start downloading a model's files in the background."""
        return model_downloads.download_model(model_type)

    @router.get("/api/v1/models/downloads/status")
    def model_downloads_status():
        """Status of model pre-downloads started via POST .../download."""
        return model_downloads.model_downloads_status()

    @router.get("/api/v1/resolutions")
    def list_resolutions():
        """List available resolution choices."""
        return model_downloads.list_resolutions()

    @router.get("/api/v1/defaults/{model_type}")
    def get_defaults(model_type: str):
        """Get default settings for a model type."""
        return model_downloads.get_defaults(model_type)

    return router


def create_model_reload_router():
    """POST /api/v1/models/reload between the CivitAI filters and installed checkpoints."""
    router = APIRouter()

    @router.post("/api/v1/models/reload")
    def reload_model_definitions():
        """Re-scan defaults/ + finetunes/ so a newly-imported checkpoint (or any
        hand-added finetune) appears in the model list without restarting the
        server. Returns the new model count and any model_types that appeared."""
        return model_downloads.reload_model_definitions()

    return router


def create_model_options_router():
    """GET /api/v1/model-options/{model_type} at the full server's original position."""
    router = APIRouter()

    @router.get("/api/v1/model-options/{model_type}")
    def get_model_options(model_type: str):
        """Return UI-relevant model options for dynamic rendering."""
        return model_options.get_model_options(model_type)

    return router


def create_active_downloads_router():
    """GET /api/v1/downloads/active at the full server's original position."""
    router = APIRouter()

    @router.get("/api/v1/downloads/active")
    def get_active_downloads():
        """Return a snapshot of in-progress model file downloads.

        UI polls this during long generation prep phases to surface
        download progress and stall warnings. Each entry includes
        `seconds_since_progress` so the UI can render "stalled — waiting
        for retry" badges without doing time math itself.

        Empty list when nothing is downloading. Best-effort tracking —
        if a download path bypasses `huggingface_hub`'s tqdm progress
        bar (some upstream Wan2GP code does this for misc files), it
        won't appear here even though the safe_download timeout
        protections still apply.
        """
        return model_downloads.get_active_downloads()

    return router
