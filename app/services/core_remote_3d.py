"""Remote Meshy/Hi3D jobs for the core/remote profile. No Hunyuan or Torch."""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from services import core_editor, core_workspace as core
from services.provider_profile import alias_model3d_provider

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if not str(key).startswith("_")}


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return _public(dict(job)) if job else None


def cancel_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        if job.get("status") in {"completed", "failed", "cancelled"}:
            return _public(dict(job))
        job["_cancel_requested"] = True
        if job.get("status") in {"queued", "waiting_resource"}:
            job["status"] = "cancelled"
            job["phase"] = "cancelled"
            job["message"] = "Cancelled"
        else:
            job["status"] = "cancelling"
            job["phase"] = "cancelling"
            job["message"] = "Cancellation requested"
        return _public(dict(job))


def capabilities() -> dict[str, Any]:
    with _LOCK:
        active = sum(1 for job in _JOBS.values() if job.get("status") in {"queued", "running", "cancelling"})
    return {
        "runtime": {"installed": False, "isolated_runtime": False, "releases_vram_after_job": True, "install_hint": None},
        "models": [],
        "presets": [],
        "texture_modes": [],
        "input_views": ["front", "left", "right", "back"],
        "output_formats": ["glb"],
        "active_jobs": active,
        "engines": [],
        "remote": ["meshy", "hi3d"],
    }


def _resolve_image(value: str, workspace: str | None) -> str:
    return core_editor.resolve_media(str(value or ""), workspace)


def _front_image(body: dict[str, Any], workspace: str) -> str | None:
    images = body.get("images") if isinstance(body.get("images"), dict) else {}
    if body.get("image_path") and not images.get("front"):
        images = {**images, "front": body["image_path"]}
    for view in ("front", "left", "right", "back"):
        value = images.get(view)
        if value:
            return _resolve_image(str(value), workspace)
    return None


def _patch(job_id: str, **fields: Any) -> None:
    with _LOCK:
        current = _JOBS.get(job_id)
        if current:
            current.update(fields)


def _remote_provider(body: dict[str, Any], profile: dict[str, Any]) -> str:
    provider = alias_model3d_provider(str(
        body.get("provider") or profile.get("model3d", {}).get("provider") or "local",
    ).strip().lower())
    if provider not in {"meshy", "hi3d"}:
        from routers.system_capabilities import require_capability_http
        require_capability_http("hunyuan3d_local")
        raise RuntimeError("local Hunyuan3D is not available")
    return provider


def start_job(body: dict[str, Any], *, workspace: str, output_dir: str) -> dict[str, Any]:
    from services import execution_mode
    from services.core_production import production_profile_response

    profile = production_profile_response()["profile"]
    provider = _remote_provider(body, profile)
    image_path = _front_image(body, workspace)
    prompt = str((body.get("prompt") or "")).strip()
    if provider == "hi3d" and not image_path:
        raise ValueError("Hi3D needs a reference image")
    if provider == "meshy" and not image_path and not prompt:
        raise ValueError("A prompt or a reference image is required")
    execution_mode.validate_remote_provider(workspace, provider)
    job_id = uuid.uuid4().hex
    model_id = str(body.get("model_id") or profile.get("model3d", {}).get("model") or provider)
    job = {
        "job_id": job_id, "task_id": job_id, "root_task_id": job_id,
        "status": "queued", "progress": 0.0, "phase": "queued",
        "message": f"Queued {provider} generation", "error": None,
        "filename": None, "url": None, "operation": "generate",
        "model_id": model_id, "provider": provider, "workspace": workspace,
        "created_at": time.time(), "updated_at": time.time(),
        "_cancel_requested": False,
        "_request": {"prompt": prompt, "image_path": image_path, "model": model_id, "output_dir": output_dir},
    }
    with _LOCK:
        _JOBS[job_id] = job
        initial = _public(dict(job))
    threading.Thread(target=_run, args=(job_id,), daemon=True, name=f"core-3d-{job_id[:8]}").start()
    return initial


def _call_provider(provider: str, request: dict[str, Any], stem: str, cancelled) -> dict[str, Any]:
    services = core.services_raw()
    output_dir = str(request.get("output_dir") or core.workspace_dir())
    if provider == "meshy":
        from services.meshy_3d_service import generate_model as generate_meshy
        return generate_meshy(
            api_key=str(services.get("meshy_api_key") or ""),
            output_dir=output_dir, prompt=str(request.get("prompt") or ""),
            image_path=request.get("image_path"), model=str(request.get("model") or "latest"),
            cancelled=cancelled, filename_stem=stem,
        )
    from services.hi3d_service import generate_model as generate_hi3d
    image_path = request.get("image_path")
    if not image_path:
        raise RuntimeError("Hi3D needs a reference image")
    return generate_hi3d(
        api_key=str(services.get("hi3d_api_key") or ""), image_path=str(image_path),
        output_dir=output_dir, model=str(request.get("model") or "hitem3dv2.1"),
        cancelled=cancelled, filename_stem=stem,
    )


def _run(job_id: str) -> None:
    def cancelled() -> bool:
        with _LOCK:
            job = _JOBS.get(job_id) or {}
            return bool(job.get("_cancel_requested")) or job.get("status") in {"cancelling", "cancelled"}

    with _LOCK:
        job = dict(_JOBS.get(job_id) or {})
    provider = str(job.get("provider") or "")
    try:
        _patch(job_id, status="running", phase="running", progress=0.1, message=f"Calling {provider}")
        if cancelled():
            _patch(job_id, status="cancelled", phase="cancelled", message="Cancelled")
            return
        result = _call_provider(provider, dict(job.get("_request") or {}), f"{provider}-{job_id[:8]}", cancelled)
        filename = result["filename"]
        _patch(job_id, status="completed", phase="completed", progress=1.0,
               message="3D model ready", filename=filename, url=f"/api/v1/file/{filename}")
    except Exception as exc:
        if cancelled():
            _patch(job_id, status="cancelled", phase="cancelled", message="Cancelled")
            return
        _patch(job_id, status="failed", phase="failed", message=str(exc), error=str(exc))
