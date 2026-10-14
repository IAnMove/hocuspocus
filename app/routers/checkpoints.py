"""Routes mounted where the launch module registered them."""
from __future__ import annotations

from fastapi import APIRouter, Request

from services import checkpoints


def create_checkpoints_library_router():
    """Installed checkpoints, then the update check."""
    router = APIRouter()

    @router.get("/api/v1/checkpoints/installed")
    def checkpoints_installed():
        """List CivitAI-imported checkpoints with their cached update status."""
        return checkpoints.checkpoints_installed()

    @router.post("/api/v1/checkpoints/check-updates")
    def checkpoints_check_updates(force: bool = False):
        """Query CivitAI for newer versions of every imported checkpoint and update
    the manifest. Skips the network round-trip if checked within 24h unless
    force=true."""
        return checkpoints.checkpoints_check_updates(force)

    return router


def create_checkpoint_guide_router():
    """Generate one checkpoint guide."""
    router = APIRouter()

    @router.post("/api/v1/checkpoints/{model_type}/generate-guide")
    async def generate_checkpoint_guide(model_type: str, request: Request):
        """(Re)generate the inline prompt-enhancer guide for an imported CivitAI
    checkpoint, reading full metadata from its co-located .civitai.json sidecar.

    Useful when the enhance LLM was not loaded at download time (the auto path
    skips guide generation in that case, just like the LoRA path). Writes
    model.enhance_guide_text back into the finetune JSON and returns the text.

    Optional JSON body {"source_url": "..."} (or {"source_urls": [...]}) supplies
    the semi-auto follow-the-pointer hint: a CivitAI model URL (the source LoRA
    this checkpoint merges) or a HuggingFace model URL, used to enrich the guide
    when the checkpoint's own description doesn't link its source.
    """
        return await checkpoints.generate_checkpoint_guide(model_type, request)

    return router
