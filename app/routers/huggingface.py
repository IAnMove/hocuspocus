"""Routes mounted where the launch module registered them."""
from __future__ import annotations

from fastapi import APIRouter, Request

from services import hf_import


def create_huggingface_import_router():
    """Hugging Face and CivitAI LoRA import."""
    router = APIRouter()

    @router.post("/api/v1/huggingface/import-lora")
    async def hf_import_lora(request: Request):
        """Import a LoRA from a HuggingFace OR CivitAI URL.

    Endpoint name is historical (HF-only originally). Now dispatches by
    URL type:
      - huggingface.co/<user>/<repo> → parses repo metadata, downloads
        .safetensors, saves sidecar, etc.
      - civitai.com/models/<id>[?modelVersionId=<vid>] → fetches model
        details from CivitAI API, downloads the chosen version's file,
        saves the same sidecar shape (so the LoRA browser shows it
        identically regardless of source).
      - civitai.com/api/download/models/<vid> → direct version-id download.

    Both paths produce the same download-record shape so the active
    downloads UI shows them identically.
    """
        return await hf_import.hf_import_lora(request)

    return router
