"""Capabilities and strict request contract for isolated image-to-3D engines.

No model imports, installation, network requests or GPU probes in the API process.
Runtime paths are administrator configuration, never accepted from a request.
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path
from typing import Any

EXTERNAL_MODELS = [
    {
        "id": "trellis2", "label": "TRELLIS.2 · Official Microsoft 4B", "engine": "trellis2", "provider": "trellis2",
        "official": True, "optional": True, "minimum_vram_gb": 24, "supported_platforms": ["linux"],
        "repo": "microsoft/TRELLIS.2-4B", "subfolder": "", "parameters": "4B",
        "multiview": False, "supports_text": False, "turbo": False,
        "recommended_vram_gb": 24,
        "description": "Single-image geometry and native PBR materials; isolated Linux/CUDA runtime.",
        "resolutions": [512, 1024, 1536], "supports_low_vram": False,
        "supports_camera_fov": False, "multiview_reason": "single_image",
    },
    {
        "id": "pixal3d", "label": "Pixal3D", "engine": "pixal3d", "provider": "pixal3d",
        "repo": "TencentARC/Pixal3D", "subfolder": "", "parameters": "—",
        "multiview": False, "supports_text": False, "turbo": False,
        "recommended_vram_gb": None,
        "description": "Pixel-aligned image-to-3D with PBR. Multi-view camera contracts are not integrated yet.",
        "resolutions": [1024, 1536], "supports_low_vram": True,
        "supports_camera_fov": True, "multiview_reason": "camera_contract",
    },
]
EXTERNAL_IDS = frozenset(model["id"] for model in EXTERNAL_MODELS)
WORKER = Path(__file__).resolve().parent / "hunyuan3d" / "external_worker.py"


def runtime_paths(engine: str) -> tuple[Path, Path]:
    if engine not in EXTERNAL_IDS:
        raise ValueError("Unknown isolated 3D engine")
    prefix = f"HOCUSPOCUS_{engine.upper()}"
    root = Path(os.environ.get(f"{prefix}_ROOT") or Path(__file__).parent / "model3d_runtimes" / engine).resolve()
    python = Path(os.environ.get(f"{prefix}_PYTHON") or root / "env" / "bin" / "python").resolve()
    if engine == "trellis2" and not os.environ.get(f"{prefix}_ROOT"):
        root = root / "vendor/TRELLIS.2"
    return root, python


def installation_status(engine: str) -> dict[str, Any]:
    root, python = runtime_paths(engine)
    entry = root / ("trellis2/pipelines/__init__.py" if engine == "trellis2" else "inference.py")
    configured = sys.platform == "linux" and entry.is_file() and python.is_file() and os.access(python, os.X_OK)
    compatible, reason, weights = True, None, None
    if engine == "trellis2":
        from .runtime_profiles import detect_profiles, managed_ready
        from .trellis2.assets import downloaded
        support = detect_profiles(inspect_engines=set())["engines"][engine]
        compatible, reason = support["supported"], support["reason"]
        configured = configured and managed_ready(engine)
        weights = downloaded()
    return {
        "installed": configured,
        "compatible": compatible, "compatibility_reason": reason, "weights_downloaded": weights,
        "validation": "configured_not_gpu_validated" if configured else "not_configured",
        "isolated_runtime": True, "releases_vram_after_job": True,
        "install_hint": reason if not compatible else (None if configured and weights is not False else (
            "Optional TRELLIS.2: run Advanced > Install TRELLIS.2, restart HocusPocus, then download its weights in Settings > Model Visibility > 3D. Requires Hugging Face access to DINOv3 and RMBG-2.0."
            if engine == "trellis2" else
            f"Configure HOCUSPOCUS_{engine.upper()}_ROOT and HOCUSPOCUS_{engine.upper()}_PYTHON "
            "for an isolated Linux/CUDA installation. See docs/development/MODEL3D_ENGINES.md."
        )),
    }


def _integer(body: dict, key: str, default: int, low: int, high: int) -> int:
    value = body.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{key} must be an integer between {low} and {high}")
    return value


def prepare_request(body: dict, images: dict, model: dict) -> dict:
    if body.get("operation", "generate") != "generate":
        raise ValueError(f"{model['label']} does not support retexturing in this integration")
    if not images.get("front") or any(value for key, value in images.items() if key != "front"):
        raise ValueError(f"{model['label']} requires exactly one front image; multi-view is not available in this integration")
    if str(body.get("prompt") or "").strip():
        raise ValueError(f"{model['label']} is image-only; a text prompt is not supported")
    if body.get("output_format", "glb") != "glb" or body.get("texture_mode", "native-pbr") != "native-pbr":
        raise ValueError("This engine exports GLB with native PBR, not Hunyuan Paint")
    unsupported = {
        "num_inference_steps", "guidance_scale", "octree_resolution", "num_chunks",
        "texture_resolution", "cpu_offload", "flashvdm", "remove_background",
        "compile", "reduce_face", "target_face_num", "mc_algo", "preset", "source_model",
    }
    supplied = unsupported.intersection(body)
    if supplied:
        raise ValueError(f"Unsupported engine parameters: {', '.join(sorted(supplied))}")
    settings = _settings(body, model)
    return {"operation": "generate", "preset": "native", "model": dict(model),
            "images": {"front": images["front"]}, "source_mesh": None, "settings": settings}


def _settings(body: dict, model: dict) -> dict:
    resolution = _integer(body, "resolution", 1024, 512, 1536)
    if resolution not in model["resolutions"]:
        raise ValueError("Unsupported engine resolution")
    low_vram = body.get("low_vram", model["supports_low_vram"])
    if not isinstance(low_vram, bool) or (low_vram and not model["supports_low_vram"]):
        raise ValueError("Unsupported low_vram setting")
    return {"seed": _integer(body, "seed", 1234, 0, 2**32 - 1),
            "resolution": resolution, "low_vram": low_vram,
            "camera_fov": _camera_fov(body.get("camera_fov", 0), model),
            "output_format": "glb", "texture_mode": "native-pbr", "prompt": ""}


def _camera_fov(fov: Any, model: dict) -> float:
    if isinstance(fov, bool) or not isinstance(fov, (int, float)) or not math.isfinite(fov):
        raise ValueError("camera_fov must be finite")
    if fov != 0 and (not model["supports_camera_fov"] or not 0.01 <= fov <= 3.13):
        raise ValueError("camera_fov must be 0 (automatic) or 0.01–3.13 radians for Pixal3D")
    return float(fov)
