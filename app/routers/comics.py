"""Comics HTTP surface: native projects, MiniMax images, and animatic queue.

The launcher injects workspace, media and Activity primitives so this module
never imports WanGP or the launch runtime.
"""

from __future__ import annotations

import base64
import copy
import glob
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, HTTPException

from services import execution_mode, minimax_image_service, resource_scheduler
from services.provider_profile import resolve_minimax_key


_minimax_image_jobs: dict[str, dict] = {}
_minimax_image_jobs_lock = threading.RLock()
_publish_legacy_task: Callable[..., Any] | None = None


def _validate_comic_project(project: dict) -> None:
    if not isinstance(project, dict) or project.get("version") != 2:
        raise HTTPException(status_code=400, detail="A version 2 comic project is required")
    pages = project.get("pages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= 500:
        raise HTTPException(status_code=400, detail="Comic pages must contain between 1 and 500 pages")
    assets = project.get("assets", {})
    if not isinstance(assets, dict) or len(assets) > 10000:
        raise HTTPException(status_code=400, detail="Comic assets must be an object with at most 10000 entries")
    encoded = json.dumps(project, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Comic project is too large")
    # Transient browser object URLs can never survive a reload. Refuse them
    # instead of giving the user a project that appears saved but is broken.
    if '"blob:' in encoded:
        raise HTTPException(status_code=400, detail="Comic contains transient blob assets; upload them before saving")


def _decode_comic_preview(preview: str) -> bytes:
    if not isinstance(preview, str) or not preview.startswith("data:image/png;base64,"):
        raise HTTPException(status_code=400, detail="A PNG comic preview is required")
    try:
        data = base64.b64decode(preview.split(",", 1)[1], validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid PNG comic preview") from exc
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Comic preview is too large")
    return data


def _comic_output_response(name: str) -> dict:
    stem = name[:-len(".comic.json")] if name.endswith(".comic.json") else os.path.splitext(name)[0]
    preview_name = f"{stem}.comic.preview.png"
    return {
        "name": name,
        "type": "comic",
        "url": f"/api/v1/file/{name}",
        "thumbnail_url": f"/api/v1/file/{preview_name}",
    }


def _comic_history_entry(snapshot: dict, snapshot_id: str) -> dict:
    project = snapshot.get("project") if isinstance(snapshot.get("project"), dict) else {}
    return {
        "id": snapshot_id,
        "comicId": str(snapshot.get("comicId") or project.get("id") or ""),
        "title": str(snapshot.get("title") or project.get("title") or "Untitled comic"),
        "createdAt": str(snapshot.get("createdAt") or ""),
        "reason": str(snapshot.get("reason") or "Automatic checkpoint"),
        "persistedName": snapshot.get("persistedName") if isinstance(snapshot.get("persistedName"), str) else None,
        "pageCount": int(snapshot.get("pageCount") or (
            len(project.get("pages", [])) if isinstance(project.get("pages"), list) else 0
        )),
        "assetCount": int(snapshot.get("assetCount") or (
            len(project.get("assets", {})) if isinstance(project.get("assets"), dict) else 0
        )),
    }


def _read_comic_history_snapshot(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            snapshot = json.load(handle)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("project"), dict):
            return None
        return snapshot
    except (OSError, ValueError, TypeError):
        return None


def _read_comic_history_metadata(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            metadata = json.load(handle)
        return metadata if isinstance(metadata, dict) and metadata.get("comicId") else None
    except (OSError, ValueError, TypeError):
        return None


def _comic_reference_image_file(
    source: str,
    workspace: str | None = None,
    *,
    workspace_dir: Callable[..., str] | None = None,
    safe_join: Callable[..., str | None] | None = None,
) -> str:
    """Resolve a local asset to base64, or preserve a validated public URL."""
    if source.startswith("data:image/"):
        if len(source) > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Character reference is too large")
        return source
    if source.startswith(("https://", "http://")):
        parsed = urlparse(source)
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname or hostname == "localhost":
            raise HTTPException(status_code=400, detail="Character reference URL must be public")
        try:
            address = ipaddress.ip_address(hostname)
            if not address.is_global:
                raise HTTPException(status_code=400, detail="Character reference URL must be public")
        except ValueError:
            pass
        if len(source) > 4096:
            raise HTTPException(status_code=400, detail="Character reference URL is too long")
        return source
    path = None
    if workspace_dir is None or safe_join is None:
        raise HTTPException(status_code=400, detail="Character reference must be a HocusPocus Lab output or upload")
    if source.startswith("/api/v1/file/"):
        filename = source.split("/api/v1/file/", 1)[1]
        path = safe_join(workspace_dir(workspace), unquote(filename))
    elif source.startswith("/api/v1/uploads/"):
        filename = source.split("/api/v1/uploads/", 1)[1]
        path = safe_join(os.path.join(os.getcwd(), "uploads"), unquote(filename))
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=400, detail="Character reference must be a HocusPocus Lab output or upload")
    if os.path.getsize(path) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Character reference is too large")
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as handle:
        return f"data:{mime};base64,{base64.b64encode(handle.read()).decode('ascii')}"


def _publish_minimax_image_job(job: dict) -> dict | None:
    publisher = _publish_legacy_task
    if not callable(publisher):
        return None
    try:
        return publisher(copy.deepcopy(job), "minimax-image")
    except Exception as exc:
        print(f"[Task registry] Could not publish MiniMax image {job.get('jobId')}: {exc}")
        return None


def _minimax_image_job_update(job_id: str, **patch) -> dict | None:
    with _minimax_image_jobs_lock:
        job = _minimax_image_jobs.get(job_id)
        if job is None:
            return None
        requested_status = str(patch.get("status") or "")
        if (
            job.get("_cancel_requested")
            and requested_status in {
                "created", "queued", "waiting_resource", "running",
            }
        ):
            return copy.deepcopy(job)
        if (
            str(job.get("status") or "") in {
                "completed", "failed", "cancelled", "interrupted",
            }
            and requested_status
            and requested_status not in {
                "completed", "failed", "cancelled", "interrupted",
            }
        ):
            return copy.deepcopy(job)
        job.update(patch)
        job["updatedAt"] = time.time()
        snapshot = copy.deepcopy(job)
    _publish_minimax_image_job(snapshot)
    return snapshot


def _minimax_image_claim_provider(job_id: str, lane_key: str) -> dict | None:
    """Atomically cross the last cancellable boundary before a paid call."""
    with _minimax_image_jobs_lock:
        job = _minimax_image_jobs.get(job_id)
        if (
            job is None
            or job.get("_cancel_requested")
            or str(job.get("status") or "") in {
                "completed", "failed", "cancelled", "interrupted",
            }
        ):
            return None
        now = time.time()
        job.update(
            status="running",
            phase="requesting",
            message="Generating image with MiniMax Image-01…",
            startedAt=job.get("startedAt") or now,
            acquired_resources=[lane_key],
            updatedAt=now,
        )
        snapshot = copy.deepcopy(job)
    _publish_minimax_image_job(snapshot)
    return snapshot


def _public_minimax_image_job(job: dict) -> dict:
    return {
        key: copy.deepcopy(value)
        for key, value in job.items()
        if key not in {"request", "_cancel_requested"}
    }


def list_minimax_image_jobs() -> list[dict]:
    """Snapshot MiniMax image jobs for Activity's canonical sync."""
    with _minimax_image_jobs_lock:
        return [copy.deepcopy(job) for job in _minimax_image_jobs.values()]


def _cancel_comic_minimax_job(job_id: str) -> dict:
    """Cancel a MiniMax image job. Used by Activity adapters and the HTTP route."""
    with _minimax_image_jobs_lock:
        job = _minimax_image_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="MiniMax image job not found")
        if job.get("status") in {"completed", "failed", "cancelled"}:
            return _public_minimax_image_job(job)
        job["_cancel_requested"] = True
        waiting = job.get("status") in {"created", "queued", "waiting_resource"}
        job["status"] = "cancelled" if waiting else "cancelling"
        job["phase"] = job["status"]
        job["message"] = (
            "Cancelled before the provider call"
            if waiting else "Cancellation requested; waiting for a safe provider boundary…"
        )
        job["updatedAt"] = time.time()
        if waiting:
            job["finishedAt"] = time.time()
        snapshot = copy.deepcopy(job)
    _publish_minimax_image_job(snapshot)
    return _public_minimax_image_job(snapshot)


def cancel_comic_minimax_job(job_id: str) -> dict:
    return _cancel_comic_minimax_job(job_id)


def create_comics_router(
    *,
    workspace_dir: Callable[..., str],
    get_active_workspace: Callable[[], str],
    safe_join: Callable[..., str | None],
    get_services_config: Callable[[], dict[str, Any]],
    publish_legacy_task: Callable[..., Any] | None,
) -> APIRouter:
    """Build the Comics CRUD and MiniMax router with launcher primitives injected."""

    global _publish_legacy_task
    _publish_legacy_task = publish_legacy_task

    router = APIRouter()

    def _comic_history_dir() -> str:
        path = os.path.join(workspace_dir(), ".comic-history")
        os.makedirs(path, exist_ok=True)
        return path

    def _write_comic_output(name: str, project: dict, preview_bytes: bytes | None) -> dict:
        if not name.endswith(".comic.json") or os.path.basename(name) != name:
            raise HTTPException(status_code=400, detail="Invalid comic project name")
        out_dir = workspace_dir()
        os.makedirs(out_dir, exist_ok=True)
        stem = name[:-len(".comic.json")]
        project_path = safe_join(out_dir, name)
        preview_path = safe_join(out_dir, f"{stem}.comic.preview.png")
        if not project_path or not preview_path:
            raise HTTPException(status_code=400, detail="Invalid comic project path")
        project_tmp = project_path + ".tmp"
        preview_tmp = preview_path + ".tmp" if preview_bytes is not None else None
        try:
            with open(project_tmp, "w", encoding="utf-8") as handle:
                json.dump(project, handle, ensure_ascii=False, indent=2)
            if preview_tmp is not None:
                with open(preview_tmp, "wb") as handle:
                    handle.write(preview_bytes)
            os.replace(project_tmp, project_path)
            if preview_tmp is not None:
                os.replace(preview_tmp, preview_path)
        except Exception as exc:
            for stale in (project_tmp, preview_tmp):
                try:
                    if stale and os.path.isfile(stale):
                        os.remove(stale)
                except OSError:
                    pass
            raise HTTPException(status_code=500, detail=f"Failed to save comic: {exc}") from exc
        return _comic_output_response(name)

    def _run_minimax_image_job(job_id: str) -> None:
        with _minimax_image_jobs_lock:
            job = copy.deepcopy(_minimax_image_jobs.get(job_id) or {})
        if not job:
            return

        def cancelled() -> bool:
            with _minimax_image_jobs_lock:
                return bool(
                    (_minimax_image_jobs.get(job_id) or {}).get("_cancel_requested")
                )

        if cancelled():
            _minimax_image_job_update(
                job_id, status="cancelled", phase="cancelled", message="Cancelled",
                finishedAt=time.time(),
            )
            return

        request_body = job.get("request") if isinstance(job.get("request"), dict) else {}
        workspace = str(job.get("workspace") or "default")
        lane = resource_scheduler.remote_lane("minimax", minimax_image_service.API_URL)
        _minimax_image_job_update(
            job_id,
            status="waiting_resource",
            phase="waiting_resource",
            message="Waiting for MiniMax Image-01 API",
            acquired_resources=[],
        )
        try:
            with resource_scheduler.coordinator.acquire(
                lane,
                task_id=str(job.get("taskId") or job_id),
                description="MiniMax Image-01 user request",
                cancelled=cancelled,
            ):
                claimed = _minimax_image_claim_provider(job_id, lane.key)
                if claimed is None:
                    raise resource_scheduler.ResourceAcquireCancelled(
                        f"MiniMax image job {job_id} was cancelled"
                    )
                generated = minimax_image_service.generate_image(
                    api_key=str(resolve_minimax_key(get_services_config(), "image")),
                    prompt=str(request_body.get("prompt") or ""),
                    aspect_ratio=str(request_body.get("aspect_ratio") or "1:1"),
                    output_dir=workspace_dir(workspace),
                    subject_reference=(
                        _comic_reference_image_file(
                            str(request_body.get("subject_reference") or ""),
                            workspace,
                            workspace_dir=workspace_dir,
                            safe_join=safe_join,
                        )
                        if request_body.get("subject_reference") else ""
                    ),
                    filename_prefix="minimax-comic",
                    task_id=str(job.get("taskId") or ""),
                    root_task_id=str(job.get("rootTaskId") or job.get("taskId") or ""),
                )
            name = generated["name"]
            asset = {
                "id": f"asset-{uuid.uuid4().hex[:12]}",
                "name": name,
                "kind": "minimax",
                "source": f"/api/v1/file/{name}",
                "thumbnail": f"/api/v1/file/{name}",
                "prompt": generated["prompt"],
                "provider": "minimax",
                "model": "image-01",
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "metadata": {
                    "jobId": job_id,
                    "taskId": job.get("taskId"),
                    "rootTaskId": job.get("rootTaskId") or job.get("taskId"),
                    "subjectReference": generated["subject_reference"],
                    "aspectRatio": generated["aspect_ratio"],
                },
            }
            if cancelled():
                _minimax_image_job_update(
                    job_id,
                    status="cancelled",
                    phase="cancelled",
                    message="Cancelled after the provider reached a safe boundary",
                    output_files=[name],
                    result={"asset": asset},
                    finishedAt=time.time(), acquired_resources=[],
                )
            else:
                _minimax_image_job_update(
                    job_id,
                    status="completed",
                    phase="completed",
                    message="MiniMax image generated",
                    current=1,
                    total=1,
                    progress=100,
                    output_files=[name],
                    result={"asset": asset},
                    finishedAt=time.time(), acquired_resources=[],
                )
        except resource_scheduler.ResourceAcquireCancelled:
            _minimax_image_job_update(
                job_id, status="cancelled", phase="cancelled", message="Cancelled",
                finishedAt=time.time(), acquired_resources=[],
            )
        except minimax_image_service.MiniMaxImageError as exc:
            _minimax_image_job_update(
                job_id, status="failed", phase="failed", message=str(exc),
                error=str(exc), statusCode=exc.status_code, finishedAt=time.time(),
                acquired_resources=[],
            )
        except Exception as exc:
            traceback.print_exc()
            _minimax_image_job_update(
                job_id, status="failed", phase="failed",
                message=f"MiniMax image generation failed: {exc}", error=str(exc),
                finishedAt=time.time(), acquired_resources=[],
            )

    @router.post("/api/v1/comics")
    def create_comic_output(body: dict):
        """Create a first-class comic project in the active workspace."""
        import re as _re_comic
        project = body.get("project")
        _validate_comic_project(project)
        preview_bytes = _decode_comic_preview(body.get("preview"))
        raw_title = str(project.get("title") or "Untitled comic").strip()
        safe_title = _re_comic.sub(r"[^A-Za-z0-9._-]+", "-", raw_title).strip("-._")[:80] or "comic"
        stamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
        name = f"{stamp}_{safe_title}_{uuid.uuid4().hex[:6]}.comic.json"
        return _write_comic_output(name, project, preview_bytes)

    @router.post("/api/v1/comics/history")
    def create_comic_history(body: dict):
        """Store a durable, de-duplicated recovery checkpoint in the workspace."""
        project = body.get("project")
        _validate_comic_project(project)
        comic_id_value = str(project.get("id") or "").strip()
        if not comic_id_value or len(comic_id_value) > 200:
            raise HTTPException(status_code=400, detail="Comic history requires a valid comic id")
        reason = str(body.get("reason") or "Automatic checkpoint").strip()[:120]
        persisted_name = body.get("persisted_name")
        if persisted_name is not None:
            if (
                not isinstance(persisted_name, str)
                or os.path.basename(persisted_name) != persisted_name
                or not persisted_name.endswith(".comic.json")
            ):
                raise HTTPException(status_code=400, detail="Invalid persisted comic name")
        encoded = json.dumps(project, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        history_dir = _comic_history_dir()
        matching: list[tuple[float, str, dict]] = []
        for path in glob.glob(os.path.join(history_dir, "*.meta.json")):
            metadata = _read_comic_history_metadata(path)
            if metadata and metadata.get("comicId") == comic_id_value:
                matching.append((os.path.getmtime(path), path, metadata))
        matching.sort(reverse=True, key=lambda item: item[0])
        if matching and matching[0][2].get("digest") == digest:
            snapshot_id = os.path.basename(matching[0][1])[:-len(".meta.json")]
            return _comic_history_entry(matching[0][2], snapshot_id)

        snapshot_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:10]}"
        snapshot = {
            "version": 1,
            "comicId": comic_id_value,
            "title": str(project.get("title") or "Untitled comic"),
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reason": reason,
            "persistedName": persisted_name,
            "digest": digest,
            "pageCount": len(project.get("pages", [])),
            "assetCount": len(project.get("assets", {})),
            "project": project,
        }
        metadata = {key: value for key, value in snapshot.items() if key != "project"}
        target = os.path.join(history_dir, f"{snapshot_id}.json")
        metadata_target = os.path.join(history_dir, f"{snapshot_id}.meta.json")
        temporary = target + ".tmp"
        metadata_temporary = metadata_target + ".tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, ensure_ascii=False, indent=2)
            with open(metadata_temporary, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
            os.replace(temporary, target)
            os.replace(metadata_temporary, metadata_target)
        except Exception as exc:
            for stale in (temporary, metadata_temporary, target, metadata_target):
                try:
                    if os.path.isfile(stale):
                        os.remove(stale)
                except OSError:
                    pass
            raise HTTPException(status_code=500, detail=f"Failed to back up comic: {exc}") from exc

        # Keep enough recovery depth without allowing continuous editing to grow
        # the workspace forever. The current checkpoint is included in the limit.
        stale = matching[39:]
        for _, metadata_path, _ in stale:
            stale_id = os.path.basename(metadata_path)[:-len(".meta.json")]
            for path in (metadata_path, os.path.join(history_dir, f"{stale_id}.json")):
                try:
                    os.remove(path)
                except OSError:
                    pass
        return _comic_history_entry(snapshot, snapshot_id)

    @router.get("/api/v1/comics/history")
    def list_comic_history(comic_id: str | None = None):
        history_dir = _comic_history_dir()
        history = []
        for path in glob.glob(os.path.join(history_dir, "*.meta.json")):
            metadata = _read_comic_history_metadata(path)
            if not metadata:
                continue
            if comic_id and metadata.get("comicId") != comic_id:
                continue
            snapshot_id = os.path.basename(path)[:-len(".meta.json")]
            history.append(_comic_history_entry(metadata, snapshot_id))
        history.sort(key=lambda entry: entry.get("createdAt", ""), reverse=True)
        return {"history": history[:500]}

    @router.get("/api/v1/comics/history/{snapshot_id}")
    def get_comic_history(snapshot_id: str):
        if not re.fullmatch(r"[A-Za-z0-9-]{8,80}", snapshot_id):
            raise HTTPException(status_code=400, detail="Invalid comic history id")
        path = os.path.join(_comic_history_dir(), f"{snapshot_id}.json")
        snapshot = _read_comic_history_snapshot(path)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Comic history checkpoint not found")
        project = snapshot["project"]
        _validate_comic_project(project)
        return {
            "project": project,
            "entry": _comic_history_entry(snapshot, snapshot_id),
        }

    @router.put("/api/v1/comics/{name}")
    def update_comic_output(name: str, body: dict):
        """Atomically update a comic, preserving its preview when omitted."""
        project = body.get("project")
        _validate_comic_project(project)
        preview = body.get("preview")
        preview_bytes = _decode_comic_preview(preview) if preview is not None else None
        current = safe_join(workspace_dir(), name)
        if not current or not os.path.isfile(current):
            raise HTTPException(status_code=404, detail="Comic project not found in the active workspace")
        return _write_comic_output(name, project, preview_bytes)

    @router.get("/api/v1/comics/{name}")
    def get_comic_output(name: str):
        path = safe_join(workspace_dir(), name)
        if not path or not name.endswith(".comic.json") or not os.path.isfile(path):
            raise HTTPException(status_code=404, detail="Comic project not found")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                project = json.load(handle)
            _validate_comic_project(project)
            return {"project": project, **_comic_output_response(name)}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid comic project: {exc}") from exc

    @router.post("/api/v1/comics/generate/minimax/jobs")
    def start_comic_minimax_job(body: dict):
        """Start one observable, cancellable MiniMax Image-01 request."""
        workspace = body.get("workspace") if "workspace" in body else get_active_workspace()
        workspace_dir(workspace)
        try:
            execution_mode.validate_remote_provider(workspace, "minimax-image")
        except execution_mode.ExecutionModeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        job_id = f"minimax-image-{uuid.uuid4().hex[:12]}"
        now = time.time()
        job = {
            "jobId": job_id,
            "workspace": workspace,
            "status": "queued",
            "phase": "queued",
            "message": "MiniMax image request queued",
            "current": 0,
            "total": 1,
            "progress": 0,
            "provider": "minimax",
            "model": "image-01",
            "server_origin": "https://api.minimax.io",
            "resource_lane": "remote:https://api.minimax.io",
            "acquired_resources": [],
            "output_files": [],
            "result": None,
            "error": None,
            "createdAt": now,
            "updatedAt": now,
            "_cancel_requested": False,
            "request": {
                "prompt": str(body.get("prompt") or ""),
                "aspect_ratio": str(body.get("aspect_ratio") or "1:1"),
                "subject_reference": body.get("subject_reference"),
            },
        }
        # Validate inexpensive request fields before returning a durable job ID.
        try:
            minimax_image_service.prepare_prompt(job["request"]["prompt"])
            if job["request"]["aspect_ratio"] not in minimax_image_service.SUPPORTED_ASPECT_RATIOS:
                raise minimax_image_service.MiniMaxImageError(
                    "Unsupported MiniMax image aspect ratio", 400,
                )
        except minimax_image_service.MiniMaxImageError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        with _minimax_image_jobs_lock:
            _minimax_image_jobs[job_id] = job
        task = _publish_minimax_image_job(job)
        if isinstance(task, dict):
            with _minimax_image_jobs_lock:
                _minimax_image_jobs[job_id]["taskId"] = task.get("id")
                _minimax_image_jobs[job_id]["rootTaskId"] = task.get("root_id") or task.get("id")
                job = copy.deepcopy(_minimax_image_jobs[job_id])
        threading.Thread(
            target=_run_minimax_image_job,
            args=(job_id,),
            name=f"minimax-image-{job_id[-6:]}",
            daemon=True,
        ).start()
        return _public_minimax_image_job(job)

    @router.get("/api/v1/comics/generate/minimax/jobs/{job_id}")
    def get_comic_minimax_job(job_id: str):
        with _minimax_image_jobs_lock:
            job = copy.deepcopy(_minimax_image_jobs.get(job_id) or {})
        if not job:
            raise HTTPException(status_code=404, detail="MiniMax image job not found")
        return _public_minimax_image_job(job)

    @router.post("/api/v1/comics/generate/minimax/jobs/{job_id}/cancel")
    def cancel_comic_minimax_job(job_id: str):
        return _cancel_comic_minimax_job(job_id)

    @router.post("/api/v1/comics/generate/minimax")
    def generate_comic_minimax(body: dict):
        """Generate one comic panel with MiniMax image-01 and persist it."""
        workspace = body.get("workspace") if "workspace" in body else get_active_workspace()
        execution_mode.validate_remote_provider(workspace, "minimax-image")
        prompt = str(body.get("prompt") or "").strip()
        api_key = resolve_minimax_key(get_services_config(), "image")
        aspect_ratio = str(body.get("aspect_ratio") or "1:1")
        subject = body.get("subject_reference")
        try:
            generated = minimax_image_service.generate_image(
                api_key=api_key,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                output_dir=workspace_dir(workspace),
                subject_reference=(
                    _comic_reference_image_file(
                        str(subject),
                        workspace_dir=workspace_dir,
                        safe_join=safe_join,
                    ) if subject else ""
                ),
                filename_prefix="minimax-comic",
            )
        except minimax_image_service.MiniMaxImageError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        name = generated["name"]
        return {"asset": {
            "id": f"asset-{uuid.uuid4().hex[:12]}",
            "name": name,
            "kind": "minimax",
            "source": f"/api/v1/file/{name}",
            "thumbnail": f"/api/v1/file/{name}",
            "prompt": generated["prompt"],
            "provider": "minimax",
            "model": "image-01",
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "metadata": {
                "subjectReference": generated["subject_reference"],
                "aspectRatio": generated["aspect_ratio"],
            },
        }}

    return router


def create_comics_animatic_router(
    *,
    workspace_dir: Callable[..., str],
    get_active_workspace: Callable[[], str],
    video_editor_task_identity: Callable[[dict, str], tuple[str, str, str | None]],
    register_video_editor_job: Callable[[dict], dict],
    video_editor_job_update: Callable[..., dict],
    public_video_editor_job: Callable[[dict], dict],
    ffmpeg_lane_key: str,
    run_comic_animatic: Callable[[str, dict, str], None],
) -> APIRouter:
    """Queue comic animatics at the original Video Editor ordinal."""

    router = APIRouter()

    @router.post("/api/v1/comics/animatic", status_code=202)
    def start_comic_animatic(body: dict):
        """Create a video storyboard from the comic's final, lettered panels."""
        panels = body.get("panels")
        if not isinstance(panels, list) or not panels:
            raise HTTPException(status_code=400, detail="The comic has no captured panels")
        if len(panels) > 200:
            raise HTTPException(status_code=400, detail="An animatic can contain at most 200 panels")
        try:
            width = int(body.get("width") or 1920)
            height = int(body.get("height") or 1080)
            fps = int(body.get("fps") or 30)
            transition_duration = float(body.get("transition_duration") or .35)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid animatic settings") from exc
        if width < 240 or height < 240 or width > 3840 or height > 3840 or width % 2 or height % 2:
            raise HTTPException(status_code=400, detail="Invalid animatic resolution")
        if fps not in (24, 25, 30, 50, 60):
            raise HTTPException(status_code=400, detail="Unsupported animatic frame rate")
        transition = str(body.get("transition") or "none")
        if transition not in {"none", "crossfade", "fade-black", "wipe-left", "slide-left", "slide-right", "circle-open", "dissolve", "pixelize", "blur", "zoom-in"}:
            raise HTTPException(status_code=400, detail="Unsupported animatic transition")
        workspace = body.get("workspace") if body.get("workspace") is not None else get_active_workspace()
        out_dir = workspace_dir(workspace)
        os.makedirs(out_dir, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(body.get("comic_title") or "comic")).strip("_")[:60] or "comic"
        output_name = f"{time.strftime('%Y-%m-%d-%Hh%Mm%Ss')}_{safe_name}_animatic.mp4"
        output_path = os.path.join(out_dir, output_name)
        suffix = 2
        while os.path.exists(output_path):
            output_name = f"{time.strftime('%Y-%m-%d-%Hh%Mm%Ss')}_{safe_name}_animatic_{suffix}.mp4"
            output_path = os.path.join(out_dir, output_name)
            suffix += 1
        job_id = f"video-edit-{uuid.uuid4().hex[:12]}"
        clean = dict(body, width=width, height=height, fps=fps, transition=transition, transition_duration=transition_duration)
        task_id, root_task_id, parent_task_id = video_editor_task_identity(body, job_id)
        now = time.time()
        job = {
            "job_id": job_id,
            "task_id": task_id,
            "root_task_id": root_task_id,
            "parent_task_id": parent_task_id,
            "workspace": workspace,
            "status": "queued",
            "phase": "queued",
            "progress": 0,
            "current": 0,
            "total": 100,
            "message": "Capturing comic panels…", "filename": None, "url": None,
            "output_files": [],
            "result": None,
            "error": None,
            "provider": "local",
            "model": "FFmpeg",
            "server_origin": "local",
            "resource_lane": ffmpeg_lane_key,
            "resource_requirements": [ffmpeg_lane_key],
            "acquired_resources": [],
            "created_at": now,
            "queued_at": now,
            "updated_at": now,
            "project_id": str(body.get("comic_id") or ""),
            "_cancel_requested": False,
            "_resource_acquired": False,
            "_worker_active": True,
        }
        try:
            snapshot = register_video_editor_job(job)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not queue comic animatic: {exc}") from exc
        worker = threading.Thread(
            target=run_comic_animatic,
            args=(job_id, clean, output_path),
            daemon=True,
            name=f"maestro-{job_id}",
        )
        try:
            worker.start()
        except Exception as exc:
            video_editor_job_update(
                job_id,
                status="failed",
                phase="failed",
                error=str(exc),
                message=f"Could not start comic animatic worker: {exc}",
                acquired_resources=[],
                finished_at=time.time(),
                _worker_active=False,
            )
            raise HTTPException(status_code=500, detail=f"Could not start comic animatic: {exc}") from exc
        return public_video_editor_job(snapshot)

    return router
