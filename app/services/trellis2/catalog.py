"""TRELLIS.2 inside the model catalog: its list entry, download gate, weights helper and delete guard.

``services.model_downloads`` calls these only when the model id is ``trellis2``.
Every import beyond the standard library and FastAPI is lazy, so a machine
without the optional runtime never loads TRELLIS code, probes the GPU or
touches the network until an explicit action asks for it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import HTTPException

MODEL_ID = "trellis2"
SELECTOR_HELP = (
    "Optional official image-to-3D. Install TRELLIS.2 from Advanced, download its weights explicitly, "
    "then select it. Requires Linux x64 / NVIDIA 24GB Ampere, Ada or Hopper."
)
RESOURCE_REQUIREMENTS = {
    "vram_gb": 24, "ram_gb": 32, "storage_gb": 40, "platform": "Linux x64", "backend": "CUDA 12.4",
    "note": "Optional; 32–64GB RAM recommended. Auxiliary model access terms apply.",
}


def catalog_extras(model: dict) -> dict:
    """Extra fields of the TRELLIS.2 row in GET /api/v1/models; nothing for any other 3D model."""
    if model["id"] != MODEL_ID:
        return {}
    from services import model3d_external
    return {
        "official": True, "optional": True, "description": model["description"],
        "selector_help": SELECTOR_HELP, "resource_requirements": dict(RESOURCE_REQUIREMENTS),
        "runtime": model3d_external.installation_status(MODEL_ID),
    }


def require_download_ready() -> None:
    """409 with the actionable hint unless the optional runtime is installed and the machine can run it."""
    from services import model3d_external
    runtime = model3d_external.installation_status(MODEL_ID)
    if not runtime["installed"] or not runtime["compatible"]:
        raise HTTPException(409, runtime["install_hint"])


def refuse_delete_while_downloading(downloads: dict, lock) -> None:
    with lock:
        if (downloads.get(MODEL_ID) or {}).get("status") == "downloading":
            raise HTTPException(409, "Cannot delete model weights while their download is active")


def download_weights() -> None:
    """Run the pinned weights helper with the isolated runtime's Python; it never runs in the API process."""
    from services import model3d_external
    from services.runtime_environment import isolated_environment
    from services.trellis2 import assets
    root, python = model3d_external.runtime_paths(MODEL_ID)
    result = subprocess.run([str(python), str(Path(assets.__file__).resolve())], cwd=root,
                            env=isolated_environment(python), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout)
    if result.returncode:
        raise RuntimeError(result.stdout[-2000:] or "TRELLIS.2 weights download failed")
    if not assets.downloaded():
        raise RuntimeError("TRELLIS.2 download is incomplete")
