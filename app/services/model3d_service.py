"""Native Hunyuan3D job manager.

The Hunyuan runtime lives inside Maestro but uses an isolated Python
environment.  Each job runs in a short-lived worker process, so CUDA state and
VRAM are fully released when generation finishes.  This is deliberately
separate from Maestro's audio/video environment: the official Hunyuan3D 2.0
and 2.1 stacks require older diffusers/transformers builds.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import execution_mode, resource_scheduler
from .asset_manifest import publish_generation_sidecar
from .hunyuan3d.weight_integrity import dit_cache_root, purge_truncated_safetensors, truncated_safetensors
from .minimax_image_service import MiniMaxImageError, generate_image as generate_minimax_image


SERVICE_DIR = Path(__file__).resolve().parent / "hunyuan3d"
ENV_DIR = SERVICE_DIR / "env"
INSTALL_MARKER = ENV_DIR / ".maestro_hunyuan3d_v1.installed"
WORKER_PATH = SERVICE_DIR / "worker.py"
VENDOR_DIR = SERVICE_DIR / "vendor"
JOBS_DIR = Path(__file__).resolve().parents[1] / "ckpts" / "model3d" / "jobs"
HF_CACHE_DIR = Path(__file__).resolve().parents[1] / "ckpts" / "model3d" / "huggingface"
DIT_CONDITION_SUFFIX = (
    ", white background, centered 3D object, studio product shot, no people, no text, no extra objects"
)

MODEL3D_EXTENSIONS = {"glb", "obj", "ply", "stl"}


MODELS: list[dict[str, Any]] = [
    {
        "id": "hunyuan3d-2mini-turbo",
        "label": "Hunyuan3D 2 Mini Turbo",
        "engine": "v2",
        "repo": "tencent/Hunyuan3D-2mini",
        "subfolder": "hunyuan3d-dit-v2-mini-turbo",
        "parameters": "0.6B",
        "multiview": False,
        "turbo": True,
        "supports_text": True,
        "recommended_vram_gb": 6,
        "description": "Fastest geometry model; best when sharing the GPU with other HocusPocus Lab workloads.",
    },
    {
        "id": "hunyuan3d-2mini-fast",
        "label": "Hunyuan3D 2 Mini Fast",
        "engine": "v2",
        "repo": "tencent/Hunyuan3D-2mini",
        "subfolder": "hunyuan3d-dit-v2-mini-fast",
        "parameters": "0.6B",
        "multiview": False,
        "turbo": False,
        "supports_text": True,
        "recommended_vram_gb": 6,
        "description": "Small guidance-distilled model with a quality/speed balance.",
    },
    {
        "id": "hunyuan3d-2mini",
        "label": "Hunyuan3D 2 Mini",
        "engine": "v2",
        "repo": "tencent/Hunyuan3D-2mini",
        "subfolder": "hunyuan3d-dit-v2-mini",
        "parameters": "0.6B",
        "multiview": False,
        "turbo": False,
        "supports_text": True,
        "recommended_vram_gb": 6,
        "description": "Full-step compact model.",
    },
    {
        "id": "hunyuan3d-2-turbo",
        "label": "Hunyuan3D 2 Turbo",
        "engine": "v2",
        "repo": "tencent/Hunyuan3D-2",
        "subfolder": "hunyuan3d-dit-v2-0-turbo",
        "parameters": "1.1B",
        "multiview": False,
        "turbo": True,
        "supports_text": True,
        "recommended_vram_gb": 8,
        "description": "Fast full-size Hunyuan3D 2.0 geometry model.",
    },
    {
        "id": "hunyuan3d-2-fast",
        "label": "Hunyuan3D 2 Fast",
        "engine": "v2",
        "repo": "tencent/Hunyuan3D-2",
        "subfolder": "hunyuan3d-dit-v2-0-fast",
        "parameters": "1.1B",
        "multiview": False,
        "turbo": False,
        "supports_text": True,
        "recommended_vram_gb": 8,
        "description": "Guidance-distilled full-size model.",
    },
    {
        "id": "hunyuan3d-2",
        "label": "Hunyuan3D 2",
        "engine": "v2",
        "repo": "tencent/Hunyuan3D-2",
        "subfolder": "hunyuan3d-dit-v2-0",
        "parameters": "1.1B",
        "multiview": False,
        "turbo": False,
        "supports_text": True,
        "recommended_vram_gb": 8,
        "description": "Original full-step Hunyuan3D 2.0 model.",
    },
    {
        "id": "hunyuan3d-2mv-turbo",
        "label": "Hunyuan3D 2 Multi-view Turbo",
        "engine": "v2",
        "repo": "tencent/Hunyuan3D-2mv",
        "subfolder": "hunyuan3d-dit-v2-mv-turbo",
        "parameters": "1.1B",
        "multiview": True,
        "turbo": True,
        "supports_text": False,
        "recommended_vram_gb": 8,
        "description": "Fast front/left/right/back image-to-3D model.",
    },
    {
        "id": "hunyuan3d-2mv-fast",
        "label": "Hunyuan3D 2 Multi-view Fast",
        "engine": "v2",
        "repo": "tencent/Hunyuan3D-2mv",
        "subfolder": "hunyuan3d-dit-v2-mv-fast",
        "parameters": "1.1B",
        "multiview": True,
        "turbo": False,
        "supports_text": False,
        "recommended_vram_gb": 8,
        "description": "Guidance-distilled multi-view geometry model.",
    },
    {
        "id": "hunyuan3d-2mv",
        "label": "Hunyuan3D 2 Multi-view",
        "engine": "v2",
        "repo": "tencent/Hunyuan3D-2mv",
        "subfolder": "hunyuan3d-dit-v2-mv",
        "parameters": "1.1B",
        "multiview": True,
        "turbo": False,
        "supports_text": False,
        "recommended_vram_gb": 8,
        "description": "Highest-quality full-step multi-view model.",
    },
    {
        "id": "hunyuan3d-2.1",
        "label": "Hunyuan3D 2.1 + PBR",
        "engine": "v21",
        "repo": "tencent/Hunyuan3D-2.1",
        "subfolder": "hunyuan3d-dit-v2-1",
        "parameters": "3.3B",
        "multiview": False,
        "turbo": False,
        "supports_text": True,
        "recommended_vram_gb": 10,
        "description": "Highest-fidelity geometry with optional production-ready PBR materials.",
    },
]

MODEL_BY_ID = {model["id"]: model for model in MODELS}

PRESETS: dict[str, dict[str, Any]] = {
    "eco": {
        "label": "Low VRAM",
        "description": "Mini Turbo, CPU offload, 128 octree, no texture.",
        "model_id": "hunyuan3d-2mini-turbo",
        "num_inference_steps": 5,
        "guidance_scale": 5.0,
        "octree_resolution": 128,
        "num_chunks": 8000,
        "texture_mode": "none",
        "cpu_offload": True,
        "flashvdm": True,
    },
    "balanced": {
        "label": "Balanced",
        "description": "Full-size Turbo geometry with standard texture support.",
        "model_id": "hunyuan3d-2-turbo",
        "num_inference_steps": 5,
        "guidance_scale": 5.0,
        "octree_resolution": 256,
        "num_chunks": 12000,
        "texture_mode": "v2-turbo",
        "cpu_offload": True,
        "flashvdm": True,
    },
    "quality": {
        "label": "Quality / PBR",
        "description": "Hunyuan3D 2.1, 384 octree and PBR materials.",
        "model_id": "hunyuan3d-2.1",
        "num_inference_steps": 30,
        "guidance_scale": 5.0,
        "octree_resolution": 384,
        "num_chunks": 20000,
        "texture_mode": "pbr",
        "cpu_offload": True,
        "flashvdm": False,
    },
    "multiview": {
        "label": "Multi-view Fast",
        "description": "Multi-view Turbo using up to four reference views.",
        "model_id": "hunyuan3d-2mv-turbo",
        "num_inference_steps": 5,
        "guidance_scale": 5.0,
        "octree_resolution": 256,
        "num_chunks": 12000,
        "texture_mode": "v2-turbo",
        "cpu_offload": True,
        "flashvdm": True,
    },
}

_jobs: dict[str, dict[str, Any]] = {}
_processes: dict[str, subprocess.Popen] = {}
_lock = threading.RLock()
# Backward-compatible alias for callers that still need the physical
# primitive. New work must use ResourceCoordinator.acquire so waiting and
# cancellation are observable.
GPU_SLOT = resource_scheduler.coordinator.shared_lock(
    resource_scheduler.local_gpu_lane(0)
)

_TERMINAL_STATES = {"completed", "failed", "cancelled"}
_ACTIVE_JOB_STATES = frozenset({
    "queued",
    "waiting",
    "waiting_resource",
    "running",
    "cancelling",
})
# Job-registry hygiene: keep a short history of finished jobs for status
# polling, but never let the in-memory dict grow with server uptime.
_MAX_FINISHED_JOBS = 20
_FINISHED_JOB_TTL_SECONDS = 3600
# Backpressure: the semaphore serializes GPU work, so anything beyond a
# handful of waiting jobs means something is stuck — reject early instead of
# accumulating blocked threads.
_MAX_ACTIVE_JOBS = 4
# Watchdog limits for a single worker: silence usually means a stalled
# download or a wedged CUDA context; the absolute cap covers slow-but-alive
# pathological runs.
_WORKER_INACTIVITY_LIMIT_SECONDS = 15 * 60
_WORKER_TIME_LIMIT_SECONDS = 2 * 3600
# Hunyuan decodes the occupancy volume in `num_chunks` points at once.
# The UI used to allow 500000, which allocates a giant CUDA buffer and
# can freeze the host via GPU OOM / swap. Official demos stay ≤ 20000.
_MAX_DECODE_CHUNKS = 40000
_MAX_CHUNKS_AT_OCTREE_384 = 24000
_MAX_CHUNKS_AT_OCTREE_512 = 16000


def _python_path() -> Path | None:
    candidates = [ENV_DIR / "python.exe", ENV_DIR / "bin" / "python"]
    return next((path for path in candidates if path.is_file()), None)


def installation_status() -> dict[str, Any]:
    python_path = _python_path()
    v2_source = VENDOR_DIR / "Hunyuan3D-2" / "hy3dgen"
    v21_source = VENDOR_DIR / "Hunyuan3D-2.1" / "hy3dshape"
    installed = bool(python_path and INSTALL_MARKER.is_file() and WORKER_PATH.is_file() and v2_source.is_dir() and v21_source.is_dir())
    return {
        "installed": installed,
        "python": str(python_path) if python_path else None,
        "v2_source": v2_source.is_dir(),
        "v21_source": v21_source.is_dir(),
        "isolated_runtime": True,
        "releases_vram_after_job": True,
        "install_hint": None if installed else "Run HocusPocus Lab's standard Install or Update action.",
    }


def is_model_downloaded(model_id: str) -> bool:
    """Return whether the selected Hugging Face snapshot is cached locally."""
    model = MODEL_BY_ID.get(model_id)
    if model is None:
        return False
    repo_cache = HF_CACHE_DIR / "hub" / f"models--{model['repo'].replace('/', '--')}" / "snapshots"
    if not repo_cache.is_dir():
        return False
    snapshots = [path for path in repo_cache.iterdir() if path.is_dir()]
    if model["engine"] == "v21":
        return bool(snapshots)
    return any((snapshot / model["subfolder"]).is_dir() for snapshot in snapshots)


def models_sharing_repo(model_id: str) -> list[dict[str, Any]]:
    """Return sibling catalog entries whose weights live in the same HF repo.

    Several variants (mini/fast/turbo families) are subfolders of one shared
    Hugging Face repository, and the cache can only be removed per-repo:
    snapshot files are deduplicated blobs, so deleting a single subfolder
    could silently corrupt the remaining variants.
    """
    model = MODEL_BY_ID.get(model_id)
    if model is None:
        return []
    return [item for item in MODELS if item["repo"] == model["repo"] and item["id"] != model_id]


def has_active_jobs(model_id: str | None = None) -> bool:
    """Return whether a job can still be using the selected model cache.

    Hunyuan3D variants in the same Hugging Face repository share one cache,
    so filtering by ``model_id`` intentionally includes active sibling
    variants from that repository.  A registered worker process also counts
    as active even if cancellation has already changed the public job status;
    this closes the short race while that process is still shutting down.
    Passing no model returns whether any Hunyuan3D job is active.
    """
    cache_model_ids: set[str] | None = None
    if model_id is not None:
        requested_id = str(model_id)
        model = MODEL_BY_ID.get(requested_id)
        if model is None:
            cache_model_ids = {requested_id}
        else:
            cache_model_ids = {
                item["id"] for item in MODELS if item["repo"] == model["repo"]
            }

    with _lock:
        for job_id, job in _jobs.items():
            job_model_id = str(job.get("model_id") or "")
            if not job_model_id:
                request_model = (job.get("request") or {}).get("model") or {}
                if isinstance(request_model, dict):
                    job_model_id = str(request_model.get("id") or "")
            if cache_model_ids is not None and job_model_id not in cache_model_ids:
                continue
            if str(job.get("status") or "").lower() in _ACTIVE_JOB_STATES:
                return True
            # A registered process remains authoritative while cancellation
            # unwinds. The cache must stay untouched until the worker removes
            # this handle in _run_job_serialized's finally block.
            if job_id in _processes:
                return True
    return False


def delete_model_cache(model_id: str) -> list[str]:
    """Remove the upstream repository cache used by a Hunyuan3D variant.

    Deletion is repo-granular (see models_sharing_repo), so callers must
    surface the affected sibling variants to the user before invoking this.
    """
    model = MODEL_BY_ID.get(model_id)
    if model is None:
        raise ValueError(f"Unknown Hunyuan3D model: {model_id}")
    repo_cache = HF_CACHE_DIR / "hub" / f"models--{model['repo'].replace('/', '--')}"
    if not repo_cache.exists():
        return []
    shutil.rmtree(repo_cache)
    return [model["repo"]]


def capabilities() -> dict[str, Any]:
    with _lock:
        active = sum(1 for job in _jobs.values() if job["status"] in _ACTIVE_JOB_STATES)
    return {
        "runtime": installation_status(),
        "models": MODELS,
        "presets": [{"id": key, **value} for key, value in PRESETS.items()],
        "texture_modes": [
            {"id": "none", "label": "Geometry only", "recommended_vram_gb": 6},
            {"id": "v2", "label": "Hunyuan3D Paint 2.0", "recommended_vram_gb": 16},
            {"id": "v2-turbo", "label": "Hunyuan3D Paint 2.0 Turbo", "recommended_vram_gb": 16},
            {"id": "pbr", "label": "Hunyuan3D Paint 2.1 PBR", "recommended_vram_gb": 21},
        ],
        "input_views": ["front", "left", "right", "back"],
        "output_formats": sorted(MODEL3D_EXTENSIONS),
        "active_jobs": active,
    }


def _safe_decode_chunks(num_chunks: int, octree_resolution: int) -> int:
    """Keep volume decode buffers from growing with octree cubed."""
    cap = _MAX_DECODE_CHUNKS
    if octree_resolution >= 512:
        cap = min(cap, _MAX_CHUNKS_AT_OCTREE_512)
    elif octree_resolution >= 384:
        cap = min(cap, _MAX_CHUNKS_AT_OCTREE_384)
    return max(1000, min(cap, int(num_chunks)))


def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _bounded_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def _prepare_request(
    body: dict[str, Any],
    image_paths: dict[str, str],
    source_mesh_path: str | None = None,
) -> dict[str, Any]:
    operation = str(body.get("operation") or "generate").strip().lower()
    if operation not in {"generate", "retexture"}:
        raise ValueError(f"Unsupported Hunyuan3D operation: {operation}")
    preset_id = str(body.get("preset") or "balanced")
    preset = dict(PRESETS.get(preset_id, PRESETS["balanced"]))
    model_id = str(body.get("model_id") or preset["model_id"])
    if model_id not in MODEL_BY_ID:
        raise ValueError(f"Unknown Hunyuan3D model: {model_id}")
    model = dict(MODEL_BY_ID[model_id])

    prompt = str(body.get("prompt") or "").strip()
    clean_images = {key: value for key, value in image_paths.items() if key in {"front", "left", "right", "back"} and value}
    if operation == "retexture":
        if not source_mesh_path:
            raise ValueError("Choose a GLB to retexture")
        if Path(source_mesh_path).suffix.lower() != ".glb":
            raise ValueError("Retexturing currently supports GLB source files only")
        if not clean_images and not prompt:
            raise ValueError("Provide a texture reference image or describe the new material")
    elif model["multiview"]:
        if "front" not in clean_images:
            raise ValueError("Multi-view models require at least a front image")
    elif not clean_images and not prompt:
        raise ValueError("Provide an image or a text prompt")

    output_format = str(body.get("output_format") or "glb").lower().lstrip(".")
    if output_format not in MODEL3D_EXTENSIONS:
        raise ValueError(f"Unsupported 3D output format: {output_format}")
    if operation == "retexture" and output_format != "glb":
        raise ValueError("Retextured assets are exported as GLB copies")

    texture_mode = str(body.get("texture_mode", preset["texture_mode"]))
    if texture_mode not in {"none", "v2", "v2-turbo", "pbr"}:
        raise ValueError(f"Unsupported texture mode: {texture_mode}")
    if operation == "retexture" and texture_mode == "none":
        raise ValueError("Choose a Hunyuan Paint texture mode for retexturing")
    if texture_mode == "pbr" and model["engine"] != "v21":
        raise ValueError("PBR materials require the Hunyuan3D 2.1 model")
    if texture_mode == "pbr" and output_format != "glb":
        raise ValueError("PBR materials must be exported as GLB so all maps remain embedded")

    settings = {
        "prompt": prompt,
        "seed": _bounded_int(body.get("seed"), 1234, 0, 2**32 - 1),
        "num_inference_steps": _bounded_int(body.get("num_inference_steps", preset["num_inference_steps"]), preset["num_inference_steps"], 1, 100),
        "guidance_scale": _bounded_float(body.get("guidance_scale", preset["guidance_scale"]), preset["guidance_scale"], 0.0, 30.0),
        "octree_resolution": _bounded_int(body.get("octree_resolution", preset["octree_resolution"]), preset["octree_resolution"], 64, 512),
        "num_chunks": _bounded_int(body.get("num_chunks", preset["num_chunks"]), preset["num_chunks"], 1000, _MAX_DECODE_CHUNKS),
        "texture_mode": texture_mode,
        "texture_resolution": _bounded_int(body.get("texture_resolution"), 512, 256, 1024),
        "remove_background": bool(body.get("remove_background", True)),
        "cpu_offload": bool(body.get("cpu_offload", preset["cpu_offload"])),
        "flashvdm": bool(body.get("flashvdm", preset["flashvdm"])),
        "compile": bool(body.get("compile", False)),
        "mc_algo": str(body.get("mc_algo") or "dmc"),
        "reduce_face": bool(body.get("reduce_face", False)),
        "target_face_num": _bounded_int(body.get("target_face_num"), 40000, 100, 1_000_000),
        "output_format": output_format,
    }
    if settings["mc_algo"] not in {"mc", "dmc"}:
        settings["mc_algo"] = "dmc"
    settings["num_chunks"] = _safe_decode_chunks(
        settings["num_chunks"], settings["octree_resolution"]
    )

    return {
        "operation": operation,
        "preset": preset_id,
        "model": model,
        "images": clean_images,
        "source_mesh": source_mesh_path,
        "settings": settings,
    }


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in job.items()
        if key not in {"request", "process", "cancel_requested"}
    }


def _canonical_task_id(job_id: str) -> str:
    """Return the durable task identity used by the canonical task adapter."""
    return f"task-model3d-{job_id}"


def _prune_finished_jobs_locked() -> None:
    """Drop old terminal jobs; callers must hold _lock."""
    now = time.time()
    finished = sorted(
        (item for item in _jobs.items() if item[1]["status"] in _TERMINAL_STATES),
        key=lambda item: item[1].get("updated_at", 0.0),
        reverse=True,
    )
    for index, (job_id, job) in enumerate(finished):
        if index >= _MAX_FINISHED_JOBS or now - job.get("updated_at", 0.0) > _FINISHED_JOB_TTL_SECONDS:
            _jobs.pop(job_id, None)


def _minimax_api_key() -> str:
    try:
        from services.generation import RuntimeConfig
        from .provider_profile import resolve_minimax_key
        return resolve_minimax_key(RuntimeConfig.services(), "image")
    except Exception:
        return ""


def _services() -> dict:
    try:
        from services.generation import RuntimeConfig
        return RuntimeConfig.services()
    except Exception:
        return {}


def _active_profile() -> dict:
    try:
        from services.generation import RuntimeConfig
        from .provider_profile import alias_model3d_provider
        raw = RuntimeConfig.get("maestro_production_profile") or {}
        image = raw.get("image") if isinstance(raw.get("image"), dict) else {}
        model3d = raw.get("model3d") if isinstance(raw.get("model3d"), dict) else {}
        return {
            "image_provider": str(image.get("provider") or "local").lower(),
            "model3d_provider": alias_model3d_provider(str(model3d.get("provider") or "local")),
            "model3d_model": str(model3d.get("model") or "").strip(),
        }
    except Exception:
        return {"image_provider": "local", "model3d_provider": "local", "model3d_model": ""}


def _condition_text_job_with_minimax(request_data: dict[str, Any], output_dir: str, job_id: str) -> str | None:
    if request_data.get("images"):
        return None
    prompt = str((request_data.get("settings") or {}).get("prompt") or "").strip()
    if not prompt:
        return None
    if _active_profile().get("image_provider") != "minimax":
        return None
    api_key = _minimax_api_key()
    if not api_key:
        return None
    condition_prompt = prompt if "white background" in prompt.lower() else f"{prompt}{DIT_CONDITION_SUFFIX}"
    result = generate_minimax_image(
        api_key=api_key,
        prompt=condition_prompt,
        aspect_ratio="1:1",
        output_dir=output_dir,
        filename_prefix="hy3d-ref",
        task_id=job_id,
        root_task_id=job_id,
    )
    return str(result["path"])


def _purge_truncated_dit_cache() -> list[Path]:
    truncated = truncated_safetensors(dit_cache_root(HF_CACHE_DIR))
    if truncated:
        purge_truncated_safetensors(dit_cache_root(HF_CACHE_DIR))
    return truncated


def _start_remote_job(
    *,
    provider: str,
    body: dict[str, Any],
    image_paths: dict[str, str],
    output_dir: str,
    workspace: str,
) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    task_id = _canonical_task_id(job_id)
    prompt = str((body.get("prompt") or body.get("settings", {}).get("prompt") if isinstance(body.get("settings"), dict) else "") or "").strip()
    model_id = str(body.get("model_id") or _active_profile().get("model3d_model") or provider)
    image_path = image_paths.get("front") or next(iter(image_paths.values()), None)
    job = {
        "job_id": job_id,
        "task_id": task_id,
        "root_task_id": task_id,
        "status": "queued",
        "progress": 0.0,
        "phase": "queued",
        "message": f"Queued {provider} generation",
        "error": None,
        "filename": None,
        "url": None,
        "operation": "generate",
        "model_id": model_id,
        "provider": provider,
        "workspace": str(workspace or "default"),
        "created_at": time.time(),
        "updated_at": time.time(),
        "request": {
            "provider": provider,
            "prompt": prompt,
            "image_path": image_path,
            "model": model_id,
        },
    }
    with _lock:
        _jobs[job_id] = job
        initial = _public_job(dict(job))
    thread = threading.Thread(
        target=_run_remote_job,
        args=(job_id, os.path.abspath(output_dir)),
        daemon=True,
    )
    thread.start()
    return initial


def _run_remote_job(job_id: str, output_dir: str) -> None:
    def cancelled() -> bool:
        with _lock:
            job = _jobs.get(job_id, {})
            return bool(job.get("cancel_requested")) or job.get("status") in {
                "cancelling", "cancelled",
            }

    with _lock:
        job = _jobs.get(job_id) or {}
        request_data = dict(job.get("request") or {})
        provider = str(job.get("provider") or request_data.get("provider") or "")
    services = _services()
    stem = f"{provider}-{job_id[:8]}"
    try:
        _update_job(job_id, status="running", phase="running", progress=0.1, message=f"Calling {provider}")
        if cancelled():
            _settle_cancelled_job(job_id)
            return
        if provider == "meshy":
            from .meshy_3d_service import generate_model as generate_meshy
            result = generate_meshy(
                api_key=str(services.get("meshy_api_key") or ""),
                output_dir=output_dir,
                prompt=str(request_data.get("prompt") or ""),
                image_path=request_data.get("image_path"),
                model=str(request_data.get("model") or "latest"),
                cancelled=cancelled,
                filename_stem=stem,
            )
        elif provider == "hi3d":
            from .hi3d_service import generate_model as generate_hi3d
            image_path = request_data.get("image_path")
            if not image_path:
                if _active_profile().get("image_provider") != "minimax":
                    raise RuntimeError(
                        "Hi3D needs a photo. Add a reference image, or set MiniMax Image as the default image generator."
                    )
                still = _condition_text_job_with_minimax(
                    {"images": {}, "settings": {"prompt": request_data.get("prompt") or "3D object, white background"}},
                    output_dir,
                    job_id,
                )
                if not still:
                    raise RuntimeError("Hi3D needs a photo. Add a reference image or configure MiniMax Image.")
                image_path = still
            result = generate_hi3d(
                api_key=str(services.get("hi3d_api_key") or ""),
                image_path=str(image_path),
                output_dir=output_dir,
                model=str(request_data.get("model") or "hitem3dv2.1"),
                cancelled=cancelled,
                filename_stem=stem,
            )
        else:
            raise RuntimeError(f"Unknown 3D provider: {provider}")
        filename = result["filename"]
        _update_job(
            job_id,
            status="completed",
            phase="completed",
            progress=1.0,
            message="3D model ready",
            filename=filename,
            url=f"/api/v1/file/{filename}",
        )
    except Exception as exc:
        if cancelled():
            _settle_cancelled_job(job_id)
            return
        _update_job(
            job_id,
            status="failed",
            phase="failed",
            message=str(exc),
            error=str(exc),
        )


def start_job(
    *,
    body: dict[str, Any],
    image_paths: dict[str, str],
    output_dir: str,
    source_mesh_path: str | None = None,
    workspace: str = "default",
) -> dict[str, Any]:
    execution_mode.validate_generation(workspace)
    profile = _active_profile()
    provider = str(body.get("provider") or profile.get("model3d_provider") or "local").strip().lower()
    if provider in {"meshy", "hi3d"}:
        execution_mode.validate_remote_provider(workspace, provider)
        return _start_remote_job(
            provider=provider,
            body=body,
            image_paths=image_paths,
            output_dir=output_dir,
            workspace=workspace,
        )
    request_data = _prepare_request(body, image_paths, source_mesh_path)
    if not execution_mode.policy().simulated:
        runtime = installation_status()
        if not runtime["installed"]:
            raise RuntimeError(runtime["install_hint"])

    with _lock:
        _prune_finished_jobs_locked()
        active = sum(1 for job in _jobs.values() if job["status"] in _ACTIVE_JOB_STATES)
    if active >= _MAX_ACTIVE_JOBS:
        raise ValueError("Too many queued 3D jobs; wait for the current ones to finish or cancel them")

    job_id = uuid.uuid4().hex
    task_id = _canonical_task_id(job_id)
    job = {
        "job_id": job_id,
        "task_id": task_id,
        "root_task_id": task_id,
        "status": "queued",
        "progress": 0.0,
        "phase": "queued",
        "message": "Queued Hunyuan3D retexture" if request_data["operation"] == "retexture" else "Queued Hunyuan3D generation",
        "error": None,
        "filename": None,
        "url": None,
        "operation": request_data["operation"],
        "model_id": request_data["model"]["id"],
        "workspace": str(workspace or "default"),
        "created_at": time.time(),
        "updated_at": time.time(),
        "request": request_data,
    }
    with _lock:
        _jobs[job_id] = job
        initial_response = _public_job(dict(job))
    thread = threading.Thread(target=_run_job, args=(job_id, os.path.abspath(output_dir)), daemon=True)
    thread.start()
    return initial_response


def _update_job(job_id: str, **updates: Any) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return False
        # Terminal cancellation is absorbing, and a running worker that is
        # already unwinding must not be resurrected by a late progress or
        # completion update.
        if (
            job.get("status") in _TERMINAL_STATES
            or job.get("status") == "cancelling"
            or job.get("cancel_requested")
        ):
            return False
        job.update(updates)
        job["updated_at"] = time.time()
        # The request payload (settings + image paths) is only needed while
        # the job runs; keeping it on finished jobs just bloats the registry.
        if job["status"] in _TERMINAL_STATES:
            job.pop("request", None)
        return True


def _settle_cancelled_job(job_id: str) -> bool:
    """Publish terminal cancellation after the worker has released its lane."""
    with _lock:
        job = _jobs.get(job_id)
        if (
            not job
            or job.get("status") in _TERMINAL_STATES
            or not (
                job.get("cancel_requested")
                or job.get("status") == "cancelling"
            )
        ):
            return False
        job.update({
            "status": "cancelled",
            "phase": "cancelled",
            "message": (
                "3D retexture cancelled"
                if job.get("operation") == "retexture"
                else "3D generation cancelled"
            ),
            "updated_at": time.time(),
        })
        job.pop("request", None)
        return True


def _run_job(job_id: str, output_dir: str) -> None:
    def cancelled() -> bool:
        with _lock:
            job = _jobs.get(job_id, {})
            return bool(job.get("cancel_requested")) or job.get("status") in {
                "cancelling",
                "cancelled",
            }

    _update_job(
        job_id,
        status="waiting_resource",
        phase="waiting_resource",
        message="Waiting for local GPU 0",
    )
    try:
        with resource_scheduler.coordinator.acquire(
            resource_scheduler.local_gpu_lane(0),
            task_id=_canonical_task_id(job_id),
            description="Hunyuan3D generation",
            cancelled=cancelled,
        ):
            if cancelled():
                return
            _run_job_serialized(job_id, output_dir)
    except resource_scheduler.ResourceAcquireCancelled:
        return
    finally:
        # The coordinator context has exited here, so a running cancellation
        # becomes terminal only after the GPU lane is actually available.
        _settle_cancelled_job(job_id)


def _cleanup_partial_output(output_path: Path) -> None:
    """Remove a failed/cancelled job's half-written export and its preview."""
    for stale in (
        output_path,
        output_path.with_suffix(".preview.png"),
        output_path.with_suffix(".meta.json"),
    ):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass


def _spawn_worker_if_active(
    job_id: str,
    command: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    message: str,
) -> subprocess.Popen | None:
    """Atomically transition an active job and register its subprocess.

    Holding ``_lock`` across the short ``Popen`` call gives cancellation one
    linearization point: it either wins before this block (no process starts),
    or it runs afterward with a registered, terminable process handle.
    """
    with _lock:
        job = _jobs.get(job_id)
        if (
            not job
            or job.get("status") not in {"queued", "waiting", "waiting_resource"}
            or job.get("cancel_requested")
            or not job.get("request")
            or job_id in _processes
        ):
            return None
        job.update({
            "status": "running",
            "phase": "starting",
            "message": message,
            "progress": 0.02,
            "updated_at": time.time(),
        })
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        _processes[job_id] = process
        return process


def _run_job_serialized(job_id: str, output_dir: str) -> None:
    if execution_mode.policy().simulated:
        with _lock:
            job = _jobs.get(job_id) or {}
            request_data = dict(job.get("request") or {})
        if not request_data:
            return
        _update_job(
            job_id, status="running", phase="simulated_inference",
            progress=0.08, message="Simulating Hunyuan3D inference…",
        )
        try:
            output = execution_mode.create_artifact(
                {"generation_mode": "3d"}, output_dir, job_id,
                progress=lambda message, value, _step, _total: _update_job(
                    job_id, message=message, progress=value / 100.0,
                    phase="simulated_inference",
                ),
                cancelled=lambda: bool((_jobs.get(job_id) or {}).get("cancel_requested")),
            )
            filename = os.path.basename(output)
            _update_job(
                job_id, status="completed", phase="completed", progress=1.0,
                message="3D model ready · simulated artifact", filename=filename,
                url=f"/api/v1/file/{filename}", simulated=True,
            )
        except InterruptedError:
            _settle_cancelled_job(job_id)
        except Exception as exc:
            _update_job(
                job_id, status="failed", phase="failed", message=str(exc), error=str(exc),
            )
        return
    python_path = _python_path()
    if not python_path:
        _update_job(job_id, status="failed", phase="failed", error="Hunyuan3D runtime is not installed")
        return

    with _lock:
        job = _jobs.get(job_id)
        request_data = job.get("request") if job else None
    if not request_data:
        # Cancelled (and possibly pruned) before the slot was acquired.
        return
    model_id = request_data["model"]["id"]
    output_format = request_data["settings"]["output_format"]
    operation = request_data.get("operation") or "generate"
    safe_model = re.sub(r"[^a-zA-Z0-9._-]+", "-", model_id)
    stamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
    if operation == "retexture":
        source_stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", Path(request_data["source_mesh"]).stem)[:48]
        filename = f"{stamp}_retextured_{source_stem}_{job_id[:8]}.{output_format}"
    else:
        filename = f"{stamp}_{safe_model}_{job_id[:8]}.{output_format}"
    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not request_data.get("images") and str((request_data.get("settings") or {}).get("prompt") or "").strip():
        _update_job(
            job_id,
            phase="text_to_image",
            progress=0.06,
            message="Generating a MiniMax reference still so HunyuanDiT is not loaded on the GPU",
        )
        minimax_error = None
        reference_path = None
        try:
            reference_path = _condition_text_job_with_minimax(request_data, output_dir, job_id)
        except MiniMaxImageError as exc:
            minimax_error = str(exc)
        except Exception as exc:
            minimax_error = str(exc)
        _purge_truncated_dit_cache()
        if reference_path:
            request_data.setdefault("images", {})["front"] = reference_path
            with _lock:
                job = _jobs.get(job_id)
                if job and isinstance(job.get("request"), dict):
                    job["request"] = request_data
            _update_job(job_id, message="Reference still ready; starting Hunyuan3D mesh")
        else:
            extra = f" MiniMax image failed ({minimax_error})." if minimax_error else (
                " Set MiniMax Image as the default image generator in Settings, or add a photo."
            )
            raise RuntimeError(
                "Hunyuan3D text-to-3D needs a reference still."
                f"{extra}"
            )
    request_path = JOBS_DIR / f"{job_id}.json"
    request_path.write_text(json.dumps(request_data, indent=2), encoding="utf-8")
    pid_path = JOBS_DIR / f"{job_id}.pid"

    command = [str(python_path), str(WORKER_PATH), "--request", str(request_path), "--output", str(output_path)]
    env = os.environ.copy()
    # Built-in Hunyuan3D models are public. Do not inherit Pinokio's global HF
    # credentials: some Hub/proxy combinations omit X-Repo-Commit from
    # authenticated HEAD responses, which makes huggingface_hub incorrectly
    # report that model_index.json is missing.
    isolated_network_vars = (
        "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_TOKEN_PATH",
        "HF_ENDPOINT", "HF_INFERENCE_ENDPOINT", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
        "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE",
    )
    for env_var in isolated_network_vars:
        env.pop(env_var, None)
    minimax_key = _minimax_api_key()
    if minimax_key:
        env["MINIMAX_API_KEY"] = minimax_key
    env.update({
        "PYTHONUNBUFFERED": "1",
        "HF_HOME": str(HF_CACHE_DIR),
        "HUGGINGFACE_HUB_CACHE": str(HF_CACHE_DIR / "hub"),
        "HF_ENDPOINT": "https://huggingface.co",
        "HF_HUB_ETAG_TIMEOUT": "30",
        "HF_HUB_DOWNLOAD_TIMEOUT": "60",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "PYTORCH_CUDA_ALLOC_CONF": env.get("PYTORCH_CUDA_ALLOC_CONF") or "expandable_segments:True",
    })
    lines: list[str] = []
    generation_committed = False
    try:
        process = _spawn_worker_if_active(
            job_id,
            command,
            cwd=str(SERVICE_DIR),
            env=env,
            message=(
                "Starting isolated Hunyuan3D retexture worker"
                if operation == "retexture"
                else "Starting isolated Hunyuan3D worker"
            ),
        )
        if process is None:
            _cleanup_partial_output(output_path)
            return
        # Record the worker PID on disk so a hard-killed Maestro (SIGKILL,
        # OOM, reload) can reap the orphan on the next startup instead of
        # leaving it holding VRAM forever.
        try:
            pid_path.write_text(str(process.pid), encoding="utf-8")
        except OSError:
            pass

        activity = {"at": time.monotonic()}
        deadline = time.monotonic() + _WORKER_TIME_LIMIT_SECONDS
        timeout_reason: dict[str, str] = {}

        def _watchdog() -> None:
            while process.poll() is None:
                time.sleep(15)
                now = time.monotonic()
                if now - activity["at"] > _WORKER_INACTIVITY_LIMIT_SECONDS:
                    timeout_reason["error"] = (
                        f"3D worker produced no output for {_WORKER_INACTIVITY_LIMIT_SECONDS // 60} minutes"
                    )
                elif now > deadline:
                    timeout_reason["error"] = (
                        f"3D generation exceeded the {_WORKER_TIME_LIMIT_SECONDS // 3600}h limit"
                    )
                else:
                    continue
                process.kill()
                return

        threading.Thread(target=_watchdog, daemon=True).start()

        assert process.stdout is not None
        for raw_line in process.stdout:
            activity["at"] = time.monotonic()
            line = raw_line.rstrip()
            if not line:
                continue
            print(f"[Hunyuan3D] {line}")
            lines.append(line)
            lines = lines[-60:]
            if line.startswith("MAESTRO_EVENT "):
                try:
                    event = json.loads(line[len("MAESTRO_EVENT "):])
                    _update_job(
                        job_id,
                        phase=str(event.get("phase") or "running"),
                        message=str(event.get("message") or "Generating 3D asset"),
                        progress=max(0.0, min(0.99, float(event.get("progress", 0.0)))),
                    )
                except Exception:
                    pass

        exit_code = process.wait()
        with _lock:
            current_job = _jobs.get(job_id, {})
            status = current_job.get("status")
            cancellation_pending = bool(current_job.get("cancel_requested"))
        if cancellation_pending or status in {"cancelling", "cancelled"}:
            _cleanup_partial_output(output_path)
            return
        if timeout_reason:
            raise RuntimeError(timeout_reason["error"])
        if exit_code != 0 or not output_path.is_file():
            detail = "\n".join(lines[-25:]) or f"Worker exited with code {exit_code}"
            raise RuntimeError(detail[-4000:])

        # The mesh is on disk. Sidecar/status failures must not delete it.
        generation_committed = True
        try:
            publish_generation_sidecar(
                output_path,
                {
                    "generation_mode": "model3d",
                    "mode": "model3d",
                    "job_id": job_id,
                    "task_id": _canonical_task_id(job_id),
                    "root_task_id": _canonical_task_id(job_id),
                    "created_at": time.time(),
                    "params": {
                        **request_data["settings"],
                        "model_id": model_id,
                        "operation": operation,
                        "source_model": os.path.basename(request_data["source_mesh"]) if request_data.get("source_mesh") else None,
                        "preset": request_data["preset"],
                        "images": request_data["images"],
                    },
                },
                workspace_id=current_job.get("workspace"),
                tool="model3d",
            )
        except Exception as sidecar_error:
            print(f"[Hunyuan3D] Failed to publish sidecar for {filename}: {sidecar_error}")
        _update_job(
            job_id,
            status="completed",
            phase="completed",
            message=("GLB retextured as a new copy; worker exited and VRAM was released" if operation == "retexture" else "3D asset generated; worker exited and VRAM was released"),
            progress=1.0,
            filename=filename,
            url=f"/api/v1/file/{filename}",
            size=output_path.stat().st_size,
        )
    except Exception as exc:
        with _lock:
            cancelled = _jobs.get(job_id, {}).get("status") == "cancelled"
        if not cancelled:
            _update_job(
                job_id,
                status="failed",
                phase="failed",
                message=("Hunyuan3D retexture failed" if operation == "retexture" else "Hunyuan3D generation failed"),
                error=str(exc),
            )
        if not generation_committed:
            _cleanup_partial_output(output_path)
    finally:
        with _lock:
            _processes.pop(job_id, None)
            current_job = _jobs.get(job_id, {})
            cancellation_pending = (
                bool(current_job.get("cancel_requested"))
                or current_job.get("status") in {"cancelling", "cancelled"}
            )
        if cancellation_pending:
            _cleanup_partial_output(output_path)
        for stale_path in (request_path, pid_path):
            try:
                stale_path.unlink(missing_ok=True)
            except Exception:
                pass


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return _public_job(dict(job)) if job else None


def cancel_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        process = _processes.get(job_id)
        if not job:
            return None
        if job["status"] in {"completed", "failed", "cancelled"}:
            return _public_job(dict(job))
        spawned = process is not None
        if spawned:
            job.update({
                "cancel_requested": True,
                "phase": "cancelling",
                "message": "Stopping the 3D worker at a safe boundary",
                "updated_at": time.time(),
            })
        else:
            job.update({
                "status": "cancelled",
                "cancel_requested": True,
                "phase": "cancelled",
                "message": (
                    "3D retexture cancelled"
                    if job.get("operation") == "retexture"
                    else "3D generation cancelled"
                ),
                "updated_at": time.time(),
            })
            job.pop("request", None)
    if process and process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
    return get_job(job_id)


def cancel_all_jobs() -> int:
    with _lock:
        active_ids = [job_id for job_id, job in _jobs.items() if job["status"] in _ACTIVE_JOB_STATES]
    for job_id in active_ids:
        cancel_job(job_id)
    return len(active_ids)


def _is_hunyuan_worker(pid: int) -> bool:
    """Best-effort check that a PID belongs to one of our worker processes."""
    proc_cmdline = Path("/proc") / str(pid) / "cmdline"
    try:
        if proc_cmdline.is_file():
            cmdline = proc_cmdline.read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
            return WORKER_PATH.name in cmdline and "hunyuan3d" in cmdline
    except OSError:
        return False
    try:
        # Non-Linux platforms: only act when psutil can positively identify
        # the process; PIDs get recycled, so never kill blindly.
        import psutil

        cmdline = " ".join(psutil.Process(pid).cmdline())
        return WORKER_PATH.name in cmdline and "hunyuan3d" in cmdline
    except Exception:
        return False


def _reap_stale_jobs() -> None:
    """Clean up after a previous Maestro process that died mid-generation.

    Job state is in-memory and the atexit hook does not run on SIGKILL/OOM,
    so an interrupted run can leave an orphan worker holding VRAM plus stale
    request/pid files in JOBS_DIR. Everything found here predates this
    process and is stale by definition.
    """
    if not JOBS_DIR.is_dir():
        return
    for pid_path in JOBS_DIR.glob("*.pid"):
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if pid > 0 and _is_hunyuan_worker(pid):
            print(f"[Hunyuan3D] Terminating orphaned worker from a previous run (pid {pid})")
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        try:
            pid_path.unlink(missing_ok=True)
        except OSError:
            pass
    for request_path in JOBS_DIR.glob("*.json"):
        try:
            request_path.unlink(missing_ok=True)
        except OSError:
            pass


atexit.register(cancel_all_jobs)

try:
    _reap_stale_jobs()
except Exception as exc:  # Never block Maestro startup on cleanup.
    print(f"[Hunyuan3D] Stale job cleanup skipped: {exc}")
