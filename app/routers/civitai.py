"""Routes mounted where the launch module registered them."""
from __future__ import annotations

from fastapi import APIRouter, Request

from services import civitai, civitai_downloads


def create_civitai_filters_router():
    """Base-model filters, then the checkpoint architecture picker."""
    router = APIRouter()

    @router.get("/api/v1/civitai/base-models")
    def civitai_base_models():
        """Return supported model filters for the browser."""
        return civitai.civitai_base_models()

    @router.get("/api/v1/civitai/checkpoint-architectures")
    def civitai_checkpoint_architectures(base_model: str = ""):
        """List architectures a checkpoint can be imported as (video/image models
    we already support), plus a best-guess default for the given CivitAI
    baseModel so the UI picker can pre-select it."""
        return civitai.civitai_checkpoint_architectures(base_model)

    return router


def create_civitai_browser_router():
    """Search, model detail, download, and the download list."""
    router = APIRouter()

    @router.get("/api/v1/civitai/search")
    def civitai_search(
        query: str = "", sort: str = "Highest Rated", period: str = "AllTime",
        nsfw: bool = False, types: str = "LORA", baseModels: str = "",
        limit: int = 20, cursor: str = "",
    ):
        """Proxy CivitAI model search (TTL-cached)."""
        return civitai.civitai_search(query, sort, period, nsfw, types, baseModels, limit, cursor)

    @router.get("/api/v1/civitai/model/{model_id}")
    def civitai_model_detail(model_id: int):
        """Fetch CivitAI model details with local architecture mapping (TTL-cached)."""
        return civitai.civitai_model_detail(model_id)

    @router.post("/api/v1/civitai/download")
    async def civitai_download(request: Request):
        """Start downloading a file from CivitAI."""
        return await civitai_downloads.civitai_download(request)

    @router.get("/api/v1/civitai/downloads")
    def civitai_downloads_status():
        """List active and recent downloads."""
        return civitai_downloads.civitai_downloads_status()

    return router
