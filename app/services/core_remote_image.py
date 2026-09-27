"""MiniMax Image-01 jobs for Studio generate on the core/remote profile."""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from services import core_workspace as core
from services.minimax_image_service import (
    MiniMaxImageError,
    SUPPORTED_ASPECT_RATIOS,
    aspect_ratio_for_resolution,
    generate_image,
    local_image_data_uri,
    prepare_prompt,
)
from services.provider_profile import resolve_minimax_key
from services.wangp_submission import resolve_wangp_media

MODEL_ID = "minimax:image-01"
_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_ACTIVE = {"queued", "waiting_resource", "running", "cancelling"}


def catalog_entry() -> dict[str, Any]:
    return {
        "model_type": MODEL_ID,
        "name": "MiniMax Image-01",
        "description": "Remote MiniMax Image-01. Requires an API key in Settings → Services.",
        "family": "minimax",
        "architecture": "minimax_image",
        "resource_requirements": {"tier": "remote", "backend": "minimax", "note": "Remote API"},
        "is_i2v": False,
        "is_t2v": False,
        "guidance_max_phases": 1,
        "fps": 0,
        "supports_end_frame": False,
        "supports_audio": False,
        "supports_ref_images": True,
        "is_downloaded": True,
        "nsfw_only": False,
        "director": {
            "image": {"compatible": True, "reason": ""},
            "video": {},
            "supports_audio_input": False,
            "generates_audio": False,
            "supports_voice_reference": False,
            "max_image_refs": 1,
        },
    }


def model_options() -> dict[str, Any]:
    return {
        "model_type": MODEL_ID,
        "architecture": "minimax_image",
        "guidance_max_phases": 1,
        "lock_guidance_phases": True,
        "sliding_window": False,
        "motion_amplitude": False,
        "flow_shift": False,
        "tea_cache": False,
        "returns_audio": False,
        "any_audio_prompt": False,
        "audio_scale_name": "",
        "lock_inference_steps": True,
        "lock_guidance_scale": True,
        "no_negative_prompt": True,
        "i2v_class": False,
        "t2v_class": False,
        "image_outputs": True,
        "supports_end_frame": False,
        "fps": 0,
    }


def defaults() -> dict[str, Any]:
    return {"prompt": "", "resolution": "1024x1024", "image_mode": 1, "generation_mode": "image"}


def is_minimax_image_request(body: dict[str, Any]) -> bool:
    model = str(body.get("model_type") or "")
    if model.startswith("minimax:"):
        return True
    if str(body.get("generation_mode") or "") != "image":
        return False
    from services.core_production import production_profile_response
    return production_profile_response()["profile"].get("image", {}).get("provider") == "minimax"


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["id"],
        "task_id": job.get("task_id"),
        "root_task_id": job.get("root_task_id") or job.get("task_id"),
        "status": job["status"],
        "progress": job["progress"],
        "step": job.get("step", 0),
        "total_steps": job.get("total_steps", 1),
        "phase": job.get("phase", ""),
        "message": job["message"],
        "output_files": list(job.get("output_files") or []),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "generation_details": {"model_type": MODEL_ID, "generation_mode": "image"},
    }


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return _public(job) if job else None


def list_active() -> list[dict[str, Any]]:
    with _LOCK:
        return [_public(job) for job in _JOBS.values() if job.get("status") in _ACTIVE]


def cancel_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None
        if job["status"] not in _ACTIVE:
            return _public(job)
        job["_cancel_requested"] = True
        if job["status"] == "queued":
            job.update(status="cancelled", phase="cancelled", message="Cancelled", finished_at=time.time())
        else:
            job.update(status="cancelling", phase="cancelling", message="Cancellation requested")
        result = _public(job)
        notify = job.get("_on_update")
    if notify:
        notify()
    return result


def _patch(job_id: str, **fields: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            job.update(fields)
        notify = job.get("_on_update") if job else None
    if notify:
        notify()


def restore_job(task: dict[str, Any]) -> None:
    """Restore polling from a durable task without invoking a provider."""
    job_id = task["backend_job_id"]
    with _LOCK:
        _JOBS.setdefault(job_id, {
            "id": job_id, "task_id": task["id"], "root_task_id": task.get("root_id"),
            "status": task["status"], "phase": task["status"],
            "progress": 100 if task["status"] == "completed" else 0,
            "message": task.get("message") or "", "error": task.get("error"),
            "output_files": list(task.get("result_refs") or []),
            "created_at": task.get("created_at"), "workspace": task.get("workspace"),
        })


def encode_subject_reference(source: str, workspace: str) -> str:
    """Encode a Studio upload/file URL the same way Comic/Director feed Image-01."""
    value = str(source or "").strip()
    if not value:
        return ""
    if value.startswith("data:image/"):
        if len(value) > 25 * 1024 * 1024:
            raise MiniMaxImageError("MiniMax identity reference is too large", 413)
        return value
    try:
        path = resolve_wangp_media(
            value,
            workspace,
            uploads_dir=core.uploads_dir(),
            workspace_dir=core.workspace_dir(workspace),
        )
    except ValueError as error:
        raise MiniMaxImageError("MiniMax identity reference is unavailable", 400) from error
    return local_image_data_uri(path)


def start_job(body: dict[str, Any], *, workspace: str, job_id: str | None = None, on_update=None) -> dict[str, Any]:
    from services import execution_mode

    prompt = prepare_prompt(str(body.get("prompt") or ""))
    ratio = str(body.get("aspect_ratio") or "")
    if ratio not in SUPPORTED_ASPECT_RATIOS:
        ratio = aspect_ratio_for_resolution(str(body.get("resolution") or "1024x1024"))
    execution_mode.validate_remote_provider(workspace, "minimax-image")
    subject = encode_subject_reference(str(body.get("subject_reference") or ""), workspace)
    job_id = str(job_id or "").strip() or uuid.uuid4().hex
    now = time.time()
    with _LOCK:
        existing = _JOBS.get(job_id)
        if existing is not None:
            return _public(existing)
        job = {
            "id": job_id, "task_id": job_id, "root_task_id": job_id,
            "status": "queued", "progress": 0, "step": 0, "total_steps": 1,
            "phase": "queued", "message": "MiniMax image request queued",
            "output_files": [], "error": None, "workspace": workspace,
            "created_at": now, "started_at": None, "finished_at": None,
            "_cancel_requested": False,
            "_on_update": on_update,
            "request": {"prompt": prompt, "aspect_ratio": ratio, "subject_reference": subject},
        }
        _JOBS[job_id] = job
        initial = _public(job)
    threading.Thread(target=_run, args=(job_id,), daemon=True, name=f"minimax-image-{job_id[:8]}").start()
    return initial


def _run(job_id: str) -> None:
    with _LOCK:
        job = dict(_JOBS.get(job_id) or {})
    request = job.get("request") or {}
    workspace = str(job.get("workspace") or "default")
    try:
        _patch(job_id, status="running", phase="running", progress=10, started_at=time.time(),
               message="Calling MiniMax Image-01")
        with _LOCK:
            cancelled = (_JOBS.get(job_id) or {}).get("_cancel_requested")
        if cancelled:
            _patch(job_id, status="cancelled", phase="cancelled", message="Cancelled", finished_at=time.time())
            return
        result = generate_image(
            api_key=resolve_minimax_key(core.services_raw(), "image"),
            prompt=str(request.get("prompt") or ""),
            aspect_ratio=str(request.get("aspect_ratio") or "1:1"),
            output_dir=core.workspace_dir(workspace),
            subject_reference=str(request.get("subject_reference") or ""),
            filename_prefix="minimax-image-01",
            task_id=job_id,
            root_task_id=job_id,
        )
        _patch(
            job_id, status="completed", phase="completed", progress=100, step=1,
            message="Image ready", output_files=[result["name"]], finished_at=time.time(),
        )
    except MiniMaxImageError as exc:
        _patch(job_id, status="failed", phase="failed", message=str(exc), error=str(exc), finished_at=time.time())
    except Exception as exc:
        _patch(job_id, status="failed", phase="failed", message=str(exc), error=str(exc), finished_at=time.time())
