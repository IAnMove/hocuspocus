"""FFmpeg video-editor jobs for the core/remote profile. No Torch."""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from typing import Any

from services import core_workspace as core
from services.media_refs import parse_media_ref
from services.media_thumbnails import ensure_media_thumbnail
from services.video_editor import extract_frame, probe_audio, probe_media, render_project

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
THUMB_DIR = os.path.join(os.getcwd(), "outputs", "_hocuspocus", "thumbs")


def resolve_media(source: str, workspace: str | None = None) -> str:
    path, chosen = parse_media_ref(source, workspace)
    name = os.path.basename(path)
    folders = []
    if chosen == "__uploads__":
        folders.append(core.uploads_dir())
    else:
        try:
            folders.append(core.workspace_dir(chosen))
        except ValueError:
            pass
        folders.append(core.uploads_dir())
    for folder in folders:
        for candidate in (name, path.lstrip("/")):
            joined = core.safe_join(folder, candidate)
            if joined and os.path.isfile(joined):
                return joined
    raise ValueError(f"Media could not be found: {name or path}")


def probe_video(source: str, workspace: str | None = None) -> dict[str, Any]:
    return probe_media(resolve_media(source, workspace))


def probe_soundtrack(source: str, workspace: str | None = None) -> dict[str, Any]:
    return probe_audio(resolve_media(source, workspace))


def thumbnail_path(source: str, workspace: str | None = None) -> str:
    os.makedirs(THUMB_DIR, exist_ok=True)
    return ensure_media_thumbnail(resolve_media(source, workspace), THUMB_DIR, is_video=True)


def unique_output_name(folder: str, filename: str) -> tuple[str, str]:
    dest = os.path.join(folder, filename)
    if not os.path.exists(dest):
        return filename, dest
    stem, ext = os.path.splitext(filename)
    suffix = 2
    while True:
        candidate = f"{stem}_{suffix}{ext}"
        dest = os.path.join(folder, candidate)
        if not os.path.exists(dest):
            return candidate, dest
        suffix += 1


def screenshot(source: str, time_seconds: float, name: str, workspace: str | None = None) -> dict[str, Any]:
    folder = core.workspace_dir(workspace)
    os.makedirs(folder, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name or "video_frame")).strip("_")
    safe = safe[:60] or "video_frame"
    stamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
    filename, dest = unique_output_name(folder, f"{stamp}_{safe}_frame.png")
    info = extract_frame(resolve_media(source, workspace), dest, time_seconds)
    return {"filename": filename, "url": f"/api/v1/file/{filename}", **info}


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def start_export(body: dict[str, Any]) -> dict[str, Any]:
    clips = body.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValueError("Add at least one video clip")
    workspace = body.get("workspace")
    prepared = []
    for clip in clips:
        if not isinstance(clip, dict):
            raise ValueError("Invalid clip")
        item = dict(clip)
        item["resolved_path"] = resolve_media(str(clip.get("source") or ""), workspace)
        prepared.append(item)
    soundtrack = body.get("soundtrack")
    if isinstance(soundtrack, dict) and soundtrack.get("source"):
        soundtrack = dict(soundtrack)
        soundtrack["resolved_path"] = resolve_media(str(soundtrack.get("source") or ""), workspace)
    else:
        soundtrack = None
    folder = core.workspace_dir(workspace)
    os.makedirs(folder, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(body.get("name") or "edit")).strip("_")
    safe_name = safe_name[:60] or "edit"
    filename, _dest = unique_output_name(folder, f"{stamp}_{safe_name}.mp4")
    destination = core.safe_join(folder, filename)
    if not destination:
        raise ValueError("Invalid export name")
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "workspace": core.active_workspace() if workspace is None else workspace,
        "status": "running",
        "progress": 0,
        "message": "Exporting…",
        "filename": filename,
        "url": None,
        "error": None,
    }
    with _LOCK:
        _JOBS[job_id] = job

    def run() -> None:
        try:
            def progress(percent: int, message: str) -> None:
                with _LOCK:
                    current = _JOBS[job_id]
                    current["progress"] = percent
                    current["message"] = message

            result = render_project(
                prepared,
                destination,
                width=int(body.get("width") or 1280),
                height=int(body.get("height") or 720),
                fps=int(body.get("fps") or 30),
                soundtrack=soundtrack,
                progress=progress,
            )
            with _LOCK:
                current = _JOBS[job_id]
                current["status"] = "completed"
                current["progress"] = 100
                current["message"] = "Export complete"
                current["url"] = f"/api/v1/file/{filename}"
                current["result"] = {"duration": result.get("duration"), "clip_count": len(prepared)}
        except Exception as error:
            with _LOCK:
                current = _JOBS[job_id]
                current["status"] = "failed"
                current["error"] = str(error)
                current["message"] = str(error)

    threading.Thread(target=run, daemon=True).start()
    return dict(job)
