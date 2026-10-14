"""LoRA guide routes, mounted at the three places the launch module registered them."""
from __future__ import annotations

from fastapi import APIRouter, Request

from services import lora_guides


def create_lora_guide_status_router():
    """The scan-status route, registered before the LoRA library."""
    router = APIRouter()

    @router.get("/api/v1/loras/scan-status/{scan_id}")
    def scan_status(scan_id: str):
        """Get the status of a LoRA scan operation."""
        return lora_guides.scan_status(scan_id)

    return router

def create_lora_guide_router():
    """Generate one guide, then read one guide."""
    router = APIRouter()

    @router.post("/api/v1/loras/generate-guide")
    async def generate_lora_guide(request: Request):
        """Generate a .guide.md for a LoRA by feeding its CivitAI metadata to the LLM."""
        return await lora_guides.generate_lora_guide(request)

    @router.get("/api/v1/loras/{model_type}/{filename}/guide")
    def get_lora_guide(model_type: str, filename: str):
        """Get the generated guide for a LoRA, if it exists."""
        return lora_guides.get_lora_guide(model_type, filename)

    return router

def create_lora_guide_scan_router():
    """The scan-all route, registered after checkpoint guide generation."""
    router = APIRouter()

    @router.post("/api/v1/loras/scan-and-generate-guides")
    async def scan_and_generate_guides(request: Request):
        """Scan all local LoRAs, fetch CivitAI metadata by hash, and generate guides.

        For each LoRA without a .guide.md:
        1. If no .civitai.json, compute SHA256 hash and look up on CivitAI
        2. If metadata exists (or was just fetched), generate a guide via LLM
        Returns progress via streaming-style response (but uses a background thread + polling).
        """
        return await lora_guides.scan_and_generate_guides(request)

    return router
