"""Attach extra songs to an assembled videoclip and remount without GPU.

The original mix stays put. Each alternative song is a sidecar record that can
be mounted later with FFmpeg: reuse the source-clip order, then randomly
append shots from that pool if the new track is longer. A shorter track keeps
the original order and is cut with ``-shortest``.

The full server's list, attach, delete and mount handlers live here too.
``configure_workspace`` binds the caller's workspace when the routes are
mounted. ``configure_editor`` binds the video editor job registry after launch
imports that registry, which is later in startup than these routes.
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import traceback
import uuid
from typing import Any, Callable

from fastapi import HTTPException

from services import resource_scheduler
from services.asset_manifest import SCHEMA_NAME, publish_generation_sidecar, read_asset_manifest
from services.mix_concat import concatenate_multi_clip_videos, probe_duration_seconds
from services.output_result_kind import classify_output_result_kind
from services.video_editor import probe_audio


MAX_SOURCE_CLIPS = 120
MAX_PLANNED_CLIPS = 240


def sidecar_path(video_path: str) -> str:
    return os.path.splitext(video_path)[0] + ".meta.json"


def load_sidecar(video_path: str) -> dict[str, Any]:
    path = sidecar_path(video_path)
    if not os.path.isfile(path):
        return {"params": {}, "created_at": time.time()}
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"params": {}, "created_at": time.time()}
    if not isinstance(payload, dict):
        return {"params": {}, "created_at": time.time()}
    params = payload.get("params")
    if not isinstance(params, dict):
        payload["params"] = {}
    return payload


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _physical_output_folder(value: Any) -> str | None:
    """Physical output-folder name; never an absolute host path or a Workspace id."""
    text = _clean_text(value)
    if not text:
        return None
    name = os.path.basename(text.replace("\\", "/"))
    return name or None


def _workspace_collection_id(value: Any) -> str | None:
    """Keep a real Workspace collection ID; folder names are not collections."""
    text = _clean_text(value)
    if not text or os.path.basename(text.replace("\\", "/")) != text:
        return None
    if text.startswith("workspace_"):
        return text
    return None


def _sidecar_location(
    payload: dict[str, Any],
    payload_origin: dict[str, Any] | None,
    disk_origin: dict[str, Any] | None,
) -> tuple[str | None, str | None]:
    payload_origin = payload_origin or {}
    disk_origin = disk_origin or {}
    folder = (
        _physical_output_folder(payload.get("output_folder"))
        or _physical_output_folder(payload_origin.get("output_folder"))
        or _physical_output_folder(disk_origin.get("output_folder"))
        or _physical_output_folder(payload.get("workspace"))
    )
    collection = (
        _workspace_collection_id(payload.get("workspace_id"))
        or _workspace_collection_id(payload_origin.get("workspace_id"))
        or _workspace_collection_id(disk_origin.get("workspace_id"))
    )
    if not folder:
        legacy = (
            _physical_output_folder(payload.get("workspace_id"))
            or _physical_output_folder(payload_origin.get("workspace_id"))
            or _physical_output_folder(disk_origin.get("workspace_id"))
        )
        if legacy and legacy != collection:
            folder = legacy
    return collection, folder


def _v1_origin(document: Any) -> dict[str, Any] | None:
    if not isinstance(document, dict) or document.get("schema") != SCHEMA_NAME:
        return None
    origin = document.get("origin")
    return origin if isinstance(origin, dict) else None


def _has_director_pipeline(payload: dict[str, Any]) -> bool:
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    return any(
        _clean_text(value)
        for value in (
            payload.get("pipeline_id"),
            payload.get("director_pipeline_id"),
            params.get("director_pipeline_id"),
            params.get("_director_pipeline_id"),
        )
    )


def save_sidecar(video_path: str, sidecar: dict[str, Any], *, tool: str | None = None) -> None:
    """Publish gallery sidecar fields through the v1 asset-manifest writer.

    An explicit ``tool`` wins. Otherwise a canonical ``origin.tool`` on the
    payload or existing v1 file is preserved so series-assembly/director/studio
    are not rewritten. If only a director pipeline id is present, tool is
    omitted so publish can attribute director. Actor is never invented as
    ``user``. A payload ``workspace`` string is the physical output folder,
    not a Workspace collection.
    """
    payload = sidecar if isinstance(sidecar, dict) else {}
    payload_origin = _v1_origin(payload)
    disk_origin = None
    existing = load_sidecar(video_path)
    if _v1_origin(existing) is not None:
        manifest = read_asset_manifest(video_path)
        origin = None if manifest is None else manifest.get("origin")
        disk_origin = origin if isinstance(origin, dict) else None
    resolved_tool = (
        _clean_text(tool)
        or _clean_text((payload_origin or {}).get("tool"))
        or _clean_text((disk_origin or {}).get("tool"))
    )
    if resolved_tool is None and _has_director_pipeline(payload):
        resolved_tool = None
    collection, folder = _sidecar_location(payload, payload_origin, disk_origin)
    publish_generation_sidecar(
        video_path,
        payload,
        workspace_id=collection,
        output_folder=folder,
        tool=resolved_tool,
    )


def _song_list(sidecar: dict[str, Any]) -> list[dict[str, Any]]:
    params = sidecar.setdefault("params", {})
    songs = params.get("alternative_songs")
    if not isinstance(songs, list):
        songs = []
        params["alternative_songs"] = songs
    return songs


def source_clip_names(sidecar: dict[str, Any], assembled_name: str) -> list[str]:
    """Prefer authored shot lists; fall back to the assembled video itself."""
    params = sidecar.get("params") if isinstance(sidecar.get("params"), dict) else {}
    names: list[str] = []
    raw = params.get("source_clips")
    if isinstance(raw, list):
        names.extend(str(item).strip() for item in raw if str(item).strip())
    editor = params.get("video_editor")
    if isinstance(editor, dict) and isinstance(editor.get("clips"), list):
        for clip in editor["clips"]:
            if not isinstance(clip, dict):
                continue
            source = str(clip.get("source") or clip.get("name") or "").strip()
            if source:
                names.append(os.path.basename(source.split("?", 1)[0]))
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
        if len(unique) >= MAX_SOURCE_CLIPS:
            break
    assembled = os.path.basename(assembled_name).strip()
    if unique:
        return unique
    return [assembled] if assembled else []


def resolve_existing_files(names: list[str], out_dir: str) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for name in names:
        path = os.path.join(out_dir, name)
        if not os.path.isfile(path) or os.path.getsize(path) <= 0:
            continue
        duration = probe_duration_seconds(path) or 0.0
        if duration <= 0.05:
            continue
        resolved.append({"name": name, "path": path, "duration": float(duration)})
    return resolved


def resolve_remount_sources(
    sidecar: dict[str, Any],
    assembled_name: str,
    out_dir: str,
) -> list[dict[str, Any]]:
    """Resolve authored shots, falling back to the assembled videoclip."""
    sources = resolve_existing_files(source_clip_names(sidecar, assembled_name), out_dir)
    if not sources:
        sources = resolve_existing_files([os.path.basename(assembled_name)], out_dir)
    return sources


def recover_stale_mounts(
    sidecar: dict[str, Any],
    is_job_active: Callable[[str], bool],
) -> bool:
    """Release persisted ``mounting`` records whose in-process worker is gone."""
    changed = False
    for record in _song_list(sidecar):
        if not isinstance(record, dict) or str(record.get("status") or "") != "mounting":
            continue
        job_id = str(record.get("job_id") or "").strip()
        if job_id and is_job_active(job_id):
            continue
        record["status"] = "attached"
        record["job_id"] = None
        changed = True
    return changed


def plan_timeline(
    sources: list[dict[str, Any]],
    target_seconds: float,
    *,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """Keep original order, then randomly append pool shots until the song fits."""
    if not sources:
        raise ValueError("This videoclip has no reusable source shots to remount.")
    target = float(target_seconds)
    if not target or target <= 0.2:
        raise ValueError("The alternative song has no usable duration.")
    planned: list[dict[str, Any]] = []
    elapsed = 0.0
    for source in sources:
        if elapsed >= target - 0.02:
            break
        take = min(float(source["duration"]), target - elapsed)
        planned.append({
            "name": source["name"],
            "path": source["path"],
            "duration": float(source["duration"]),
            "used": take,
            "extra": False,
        })
        elapsed += take
        if len(planned) >= MAX_PLANNED_CLIPS:
            break
    picker = rng or random.Random()
    while elapsed < target - 0.02 and len(planned) < MAX_PLANNED_CLIPS:
        pool = sources
        if len(sources) > 1:
            last = planned[-1]["path"]
            distinct = [item for item in sources if item["path"] != last]
            if distinct:
                pool = distinct
        source = picker.choice(pool)
        take = min(float(source["duration"]), target - elapsed)
        planned.append({
            "name": source["name"],
            "path": source["path"],
            "duration": float(source["duration"]),
            "used": take,
            "extra": True,
        })
        elapsed += take
    return planned


def slug_audio_name(audio_name: str) -> str:
    stem = os.path.splitext(os.path.basename(audio_name))[0]
    slug = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").lower()
    return (slug[:40] or "song")


def unique_mounted_name(out_dir: str, parent_name: str, audio_name: str) -> str:
    parent_stem = os.path.splitext(os.path.basename(parent_name))[0]
    parent_stem = re.sub(r"_mv$", "", parent_stem)
    slug = slug_audio_name(audio_name)
    base = f"{parent_stem}_{slug}_mv.mp4"
    candidate = base
    suffix = 2
    while os.path.exists(os.path.join(out_dir, candidate)):
        candidate = f"{parent_stem}_{slug}_{suffix}_mv.mp4"
        suffix += 1
    return candidate


def public_song(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(record.get("id") or ""),
        "audio_name": str(record.get("audio_name") or ""),
        "duration_seconds": float(record.get("duration_seconds") or 0),
        "created_at": float(record.get("created_at") or 0),
        "status": str(record.get("status") or "attached"),
        "mounted_output": record.get("mounted_output") or None,
        "job_id": record.get("job_id") or None,
        "extra_clip_count": int(record.get("extra_clip_count") or 0),
        "planned_clip_count": int(record.get("planned_clip_count") or 0),
    }


def find_song(sidecar: dict[str, Any], song_id: str | None = None, audio_name: str | None = None) -> dict[str, Any] | None:
    wanted_id = str(song_id or "").strip()
    wanted_audio = os.path.basename(str(audio_name or "").strip())
    for record in _song_list(sidecar):
        if not isinstance(record, dict):
            continue
        if wanted_id and str(record.get("id") or "") == wanted_id:
            return record
        if wanted_audio and os.path.basename(str(record.get("audio_name") or "")) == wanted_audio:
            return record
    return None


def attach_song(
    sidecar: dict[str, Any],
    *,
    audio_name: str,
    duration_seconds: float,
) -> dict[str, Any]:
    name = os.path.basename(str(audio_name or "").strip())
    if not name:
        raise ValueError("Choose an existing audio output.")
    existing = find_song(sidecar, audio_name=name)
    if existing:
        existing["duration_seconds"] = float(duration_seconds)
        if existing.get("status") not in {"mounting", "mounted"}:
            existing["status"] = "attached"
        return existing
    record = {
        "id": f"song-{uuid.uuid4().hex[:10]}",
        "audio_name": name,
        "duration_seconds": float(duration_seconds),
        "created_at": time.time(),
        "status": "attached",
        "mounted_output": None,
        "job_id": None,
        "extra_clip_count": 0,
        "planned_clip_count": 0,
    }
    _song_list(sidecar).append(record)
    return record


def remove_song(sidecar: dict[str, Any], song_id: str) -> dict[str, Any]:
    songs = _song_list(sidecar)
    for index, record in enumerate(songs):
        if isinstance(record, dict) and str(record.get("id") or "") == song_id:
            if str(record.get("status") or "") == "mounting":
                raise ValueError("Wait for the current remount to finish before removing this song.")
            return songs.pop(index)
    raise ValueError("That alternative song is not attached to this videoclip.")


def describe_parent(
    *,
    video_name: str,
    video_path: str,
    sidecar: dict[str, Any],
    source_files: list[dict[str, Any]],
) -> dict[str, Any]:
    duration = probe_duration_seconds(video_path) or 0.0
    adaptation = "random_extras" if len(source_files) > 1 else "loop_assembled"
    return {
        "parent": video_name,
        "duration_seconds": duration,
        "source_clip_count": len(source_files),
        "adaptation": adaptation,
        "songs": [public_song(item) for item in _song_list(sidecar) if isinstance(item, dict)],
    }


def write_mounted_sidecar(
    *,
    output_path: str,
    parent_name: str,
    parent_sidecar: dict[str, Any],
    song: dict[str, Any],
    planned: list[dict[str, Any]],
    job_id: str,
    workspace: str,
) -> None:
    parent_params = parent_sidecar.get("params") if isinstance(parent_sidecar.get("params"), dict) else {}
    extra_count = sum(1 for item in planned if item.get("extra"))
    payload = {
        "params": {
            "result_kind": "music_video",
            "production_kind": "music_video",
            "pipeline_type": parent_params.get("pipeline_type") or "music_video",
            "source_clips": [item["name"] for item in planned],
            "parent_output": parent_name,
            "alternative_song_id": song.get("id"),
            "alternative_audio_name": song.get("audio_name"),
            "model_type": parent_params.get("model_type") or "ffmpeg_remount",
            "provider": parent_params.get("provider") or "ffmpeg",
            "resolution": parent_params.get("resolution") or "",
        },
        "result_kind": "music_video",
        "generation_mode": "video",
        "job_id": job_id,
        "workspace": workspace,
        "created_at": time.time(),
        "parent_output": parent_name,
    }
    pipeline_id = (
        _clean_text(parent_sidecar.get("pipeline_id"))
        or _clean_text(parent_sidecar.get("director_pipeline_id"))
        or _clean_text(parent_params.get("pipeline_id"))
        or _clean_text(parent_params.get("director_pipeline_id"))
        or _clean_text(parent_params.get("_director_pipeline_id"))
    )
    if pipeline_id:
        payload["pipeline_id"] = pipeline_id
        payload["director_pipeline_id"] = pipeline_id
        payload["params"]["director_pipeline_id"] = pipeline_id
    for key in ("task_id", "root_task_id"):
        value = _clean_text(parent_sidecar.get(key)) or _clean_text(parent_params.get(key))
        if value:
            payload[key] = value
    save_sidecar(output_path, payload, tool="alternative-songs")
    song["status"] = "mounted"
    song["mounted_output"] = os.path.basename(output_path)
    song["extra_clip_count"] = extra_count
    song["planned_clip_count"] = len(planned)
    classify = classify_output_result_kind(
        os.path.basename(output_path),
        payload["params"],
        payload,
    )
    if classify != "music_video":
        payload["params"]["result_kind"] = "music_video"
        save_sidecar(output_path, payload, tool="alternative-songs")


def remount_clips(
    planned: list[dict[str, Any]],
    audio_path: str,
    output_path: str,
    *,
    abort_callback: Callable[[], bool] | None = None,
) -> None:
    if not planned:
        raise ValueError("No clips were planned for this remount.")
    paths = [str(item["path"]) for item in planned]
    ok = concatenate_multi_clip_videos(
        paths,
        output_path,
        audio_path,
        abort_callback=abort_callback,
    )
    if not ok:
        raise RuntimeError("FFmpeg could not remount this videoclip with the alternative song.")
    if not os.path.isfile(output_path) or os.path.getsize(output_path) <= 0:
        raise RuntimeError("The remount finished without writing a video file.")


def probe_song_duration(audio_path: str) -> float:
    return float(probe_audio(audio_path)["duration"])


_alternative_song_sidecar_lock = threading.RLock()

_workspace_dir = None
_safe_join = None
_get_active_workspace = None
_video_editor_job_snapshot = None
_video_editor_job_update = None
_video_editor_cancel_requested = None
_finish_video_editor_cancelled = None
_remove_video_editor_output_bundle = None
_resolve_video_editor_audio_source = None
_register_video_editor_job = None
_video_editor_task_identity = None
_VIDEO_EDITOR_FFMPEG_LANE = None
_VIDEO_EDITOR_TERMINAL = None


def configure_workspace(*, workspace_dir, safe_join, get_active_workspace) -> None:
    """Bind the caller's workspace before a request."""
    global _workspace_dir, _safe_join, _get_active_workspace
    _workspace_dir = workspace_dir
    _safe_join = safe_join
    _get_active_workspace = get_active_workspace


def configure_editor(
    *,
    video_editor_job_snapshot,
    video_editor_job_update,
    video_editor_cancel_requested,
    finish_video_editor_cancelled,
    remove_video_editor_output_bundle,
    resolve_video_editor_audio_source,
    register_video_editor_job,
    video_editor_task_identity,
    ffmpeg_lane,
    terminal,
) -> None:
    """Bind the one video-editor job registry. Launch calls this after importing it."""
    global _video_editor_job_snapshot, _video_editor_job_update, _video_editor_cancel_requested
    global _finish_video_editor_cancelled, _remove_video_editor_output_bundle
    global _resolve_video_editor_audio_source, _register_video_editor_job
    global _video_editor_task_identity, _VIDEO_EDITOR_FFMPEG_LANE, _VIDEO_EDITOR_TERMINAL
    _video_editor_job_snapshot = video_editor_job_snapshot
    _video_editor_job_update = video_editor_job_update
    _video_editor_cancel_requested = video_editor_cancel_requested
    _finish_video_editor_cancelled = finish_video_editor_cancelled
    _remove_video_editor_output_bundle = remove_video_editor_output_bundle
    _resolve_video_editor_audio_source = resolve_video_editor_audio_source
    _register_video_editor_job = register_video_editor_job
    _video_editor_task_identity = video_editor_task_identity
    _VIDEO_EDITOR_FFMPEG_LANE = ffmpeg_lane
    _VIDEO_EDITOR_TERMINAL = terminal


def _alternative_song_parent(name: str, workspace: str | None = None) -> tuple[str, str, str, dict]:
    """Return workspace dir, video path, basename and sidecar for one mix."""
    from services.alternative_songs import load_sidecar

    out_dir = _workspace_dir(workspace)
    filepath = _safe_join(out_dir, name)
    if filepath is None or not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail="Videoclip not found")
    if os.path.splitext(filepath)[1].lower() not in {".mp4", ".mkv", ".webm", ".mov"}:
        raise HTTPException(status_code=400, detail="Alternative songs are for video mixes")
    return out_dir, filepath, os.path.basename(filepath), load_sidecar(filepath)

def _alternative_song_sources(out_dir: str, video_name: str, sidecar: dict) -> list[dict]:
    from services.alternative_songs import resolve_remount_sources

    sources = resolve_remount_sources(sidecar, video_name, out_dir)
    if not sources:
        raise HTTPException(
            status_code=400,
            detail="This videoclip has no reusable shots on disk to remount",
        )
    return sources

def _alternative_song_job_is_active(job_id: str) -> bool:
    """Only an in-process editor worker can finish a persisted remount."""
    snapshot = _video_editor_job_snapshot(job_id)
    return bool(
        snapshot
        and str(snapshot.get("status") or "") not in {"completed", "failed", "cancelled"}
        and snapshot.get("_worker_active")
    )

def _recover_stale_alternative_song_mounts(video_path: str, sidecar: dict) -> bool:
    from services.alternative_songs import recover_stale_mounts, save_sidecar

    changed = recover_stale_mounts(sidecar, _alternative_song_job_is_active)
    if changed:
        save_sidecar(video_path, sidecar)
    return changed

def _run_alternative_song_mount(
    job_id: str,
    *,
    out_dir: str,
    video_path: str,
    video_name: str,
    audio_path: str,
    output_path: str,
    song_id: str,
    workspace: str,
    seed: int,
) -> None:
    from services.alternative_songs import (
        find_song,
        load_sidecar,
        plan_timeline,
        remount_clips,
        resolve_remount_sources,
        save_sidecar,
        write_mounted_sidecar,
    )

    def fail(message: str) -> None:
        with _alternative_song_sidecar_lock:
            sidecar = load_sidecar(video_path)
            song = find_song(sidecar, song_id=song_id)
            if song is not None:
                song["status"] = "failed"
                song["job_id"] = job_id
                save_sidecar(video_path, sidecar)
        _video_editor_job_update(
            job_id,
            status="failed",
            phase="failed",
            error=message,
            message=message,
            output_files=[],
            acquired_resources=[],
            finished_at=time.time(),
            _resource_acquired=False,
            _worker_active=False,
        )

    try:
        _video_editor_job_update(
            job_id,
            status="waiting_resource",
            phase="waiting_resource",
            message="Waiting for the local FFmpeg lane…",
            acquired_resources=[],
        )
        with _alternative_song_sidecar_lock:
            sidecar = load_sidecar(video_path)
            sources = resolve_remount_sources(sidecar, video_name, out_dir)
            song = find_song(sidecar, song_id=song_id)
            if song is None:
                raise ValueError("The alternative song disappeared before remount")
            target = float(song.get("duration_seconds") or 0)
        planned = plan_timeline(sources, target, rng=random.Random(seed))
        try:
            with resource_scheduler.coordinator.acquire(
                _VIDEO_EDITOR_FFMPEG_LANE,
                task_id=str((_video_editor_job_snapshot(job_id) or {}).get("task_id") or job_id),
                description="Alternative song remount",
                cancelled=lambda: _video_editor_cancel_requested(job_id),
            ):
                started = _video_editor_job_update(
                    job_id,
                    status="running",
                    phase="rendering",
                    message="Remounting videoclip with the alternative song…",
                    started_at=time.time(),
                    acquired_resources=[_VIDEO_EDITOR_FFMPEG_LANE.key],
                    _resource_acquired=True,
                )
                if (
                    _video_editor_cancel_requested(job_id)
                    or str(started.get("status") or "") in _VIDEO_EDITOR_TERMINAL
                ):
                    raise resource_scheduler.ResourceAcquireCancelled(
                        f"Alternative song remount {job_id} was cancelled before FFmpeg started"
                    )
                remount_clips(
                    planned,
                    audio_path,
                    output_path,
                    abort_callback=lambda: _video_editor_cancel_requested(job_id),
                )
        except resource_scheduler.ResourceAcquireCancelled:
            current = _video_editor_job_snapshot(job_id) or {}
            deferred = bool(current.get("started_at"))
            with _alternative_song_sidecar_lock:
                sidecar = load_sidecar(video_path)
                song = find_song(sidecar, song_id=song_id)
                if song is not None and str(song.get("status") or "") == "mounting":
                    song["status"] = "attached"
                    song["job_id"] = None
                    save_sidecar(video_path, sidecar)
            _finish_video_editor_cancelled(
                job_id,
                output_path,
                message=(
                    "Cancelled after FFmpeg reached a safe boundary"
                    if deferred else "Cancelled before FFmpeg started"
                ),
                cancel_mode="deferred" if deferred else "immediate",
                safe_boundary=(
                    "after_current_ffmpeg_render" if deferred else "before_ffmpeg"
                ),
            )
            return

        if _video_editor_cancel_requested(job_id):
            with _alternative_song_sidecar_lock:
                sidecar = load_sidecar(video_path)
                song = find_song(sidecar, song_id=song_id)
                if song is not None:
                    song["status"] = "attached"
                    song["job_id"] = None
                    save_sidecar(video_path, sidecar)
            _finish_video_editor_cancelled(
                job_id,
                output_path,
                message="Cancelled after FFmpeg reached a safe boundary",
                cancel_mode="deferred",
                safe_boundary="after_current_ffmpeg_render",
            )
            return

        with _alternative_song_sidecar_lock:
            sidecar = load_sidecar(video_path)
            song = find_song(sidecar, song_id=song_id)
            if song is None:
                raise ValueError("The alternative song disappeared after remount")
            write_mounted_sidecar(
                output_path=output_path,
                parent_name=video_name,
                parent_sidecar=sidecar,
                song=song,
                planned=planned,
                job_id=job_id,
                workspace=workspace,
            )
            save_sidecar(video_path, sidecar)
        output_name = os.path.basename(output_path)
        _video_editor_job_update(
            job_id,
            status="completed",
            phase="completed",
            progress=100,
            current=100,
            message="Alternative song remount complete",
            filename=output_name,
            url=f"/api/v1/file/{output_name}",
            output_files=[output_name],
            acquired_resources=[],
            finished_at=time.time(),
            _resource_acquired=False,
            _worker_active=False,
        )
    except Exception as exc:
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        _remove_video_editor_output_bundle(output_path)
        fail(str(exc))

def list_alternative_songs(name: str, workspace: str | None = None):
    """List songs attached to an assembled videoclip without remounting."""
    from services.alternative_songs import describe_parent

    with _alternative_song_sidecar_lock:
        out_dir, filepath, video_name, sidecar = _alternative_song_parent(name, workspace)
        _recover_stale_alternative_song_mounts(filepath, sidecar)
        sources = _alternative_song_sources(out_dir, video_name, sidecar)
        return describe_parent(
            video_name=video_name,
            video_path=filepath,
            sidecar=sidecar,
            source_files=sources,
        )

def attach_alternative_song(name: str, body: dict, workspace: str | None = None):
    """Attach an existing audio output as an alternative song. No GPU work."""
    with _alternative_song_sidecar_lock:
        return _attach_alternative_song_locked(name, body, workspace)

def _attach_alternative_song_locked(name: str, body: dict, workspace: str | None = None):
    from services.alternative_songs import attach_song, describe_parent, public_song, save_sidecar

    audio_name = str((body or {}).get("audio_name") or "").strip()
    if not audio_name:
        raise HTTPException(status_code=400, detail="audio_name is required")
    ws = workspace if workspace is not None else (body or {}).get("workspace")
    out_dir, filepath, video_name, sidecar = _alternative_song_parent(name, ws)
    sources = _alternative_song_sources(out_dir, video_name, sidecar)
    try:
        audio_path = _resolve_video_editor_audio_source(audio_name, ws)
        from services.alternative_songs import probe_song_duration
        duration = probe_song_duration(audio_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record = attach_song(sidecar, audio_name=os.path.basename(audio_path), duration_seconds=duration)
    save_sidecar(filepath, sidecar)
    parent = describe_parent(
        video_name=video_name, video_path=filepath, sidecar=sidecar, source_files=sources,
    )
    return {"song": public_song(record), **parent}

def delete_alternative_song(name: str, song_id: str, workspace: str | None = None):
    with _alternative_song_sidecar_lock:
        return _delete_alternative_song_locked(name, song_id, workspace)

def _delete_alternative_song_locked(name: str, song_id: str, workspace: str | None = None):
    from services.alternative_songs import public_song, remove_song, save_sidecar

    _out_dir, filepath, _video_name, sidecar = _alternative_song_parent(name, workspace)
    _recover_stale_alternative_song_mounts(filepath, sidecar)
    try:
        removed = remove_song(sidecar, song_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_sidecar(filepath, sidecar)
    return {"removed": public_song(removed)}

def mount_alternative_song(name: str, song_id: str, body: dict | None = None, workspace: str | None = None):
    """Remount the videoclip with an attached alternative song using FFmpeg only."""
    with _alternative_song_sidecar_lock:
        return _mount_alternative_song_locked(name, song_id, body, workspace)

def _mount_alternative_song_locked(
    name: str,
    song_id: str,
    body: dict | None = None,
    workspace: str | None = None,
):
    from services.alternative_songs import (
        attach_song,
        find_song,
        public_song,
        save_sidecar,
        unique_mounted_name,
        probe_song_duration,
    )

    payload = body if isinstance(body, dict) else {}
    ws = workspace if workspace is not None else payload.get("workspace")
    out_dir, filepath, video_name, sidecar = _alternative_song_parent(name, ws)
    _recover_stale_alternative_song_mounts(filepath, sidecar)
    _alternative_song_sources(out_dir, video_name, sidecar)
    record = find_song(sidecar, song_id=song_id)
    if record is None:
        audio_name = str(payload.get("audio_name") or "").strip()
        if not audio_name:
            raise HTTPException(status_code=404, detail="Alternative song not found")
        try:
            audio_path = _resolve_video_editor_audio_source(audio_name, ws)
            record = attach_song(
                sidecar,
                audio_name=os.path.basename(audio_path),
                duration_seconds=probe_song_duration(audio_path),
            )
            song_id = str(record["id"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if str(record.get("status") or "") == "mounting":
        raise HTTPException(status_code=409, detail="That song is already remounting")
    try:
        audio_path = _resolve_video_editor_audio_source(str(record.get("audio_name") or ""), ws)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        seed = int(payload.get("seed") if payload.get("seed") is not None else 1)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="seed must be an integer") from exc
    output_name = unique_mounted_name(out_dir, video_name, str(record.get("audio_name") or "song"))
    output_path = os.path.join(out_dir, output_name)
    job_id = f"alt-song-{uuid.uuid4().hex[:12]}"
    task_id, root_task_id, parent_task_id = _video_editor_task_identity(payload, job_id)
    now = time.time()
    job = {
        "job_id": job_id,
        "task_id": task_id,
        "root_task_id": root_task_id,
        "parent_task_id": parent_task_id,
        "workspace": ws or _get_active_workspace(),
        "status": "queued",
        "phase": "queued",
        "progress": 0,
        "current": 0,
        "total": 100,
        "message": "Waiting to remount the alternative song…",
        "filename": None,
        "url": None,
        "output_files": [],
        "result": None,
        "error": None,
        "provider": "local",
        "model": "FFmpeg",
        "server_origin": "local",
        "resource_lane": _VIDEO_EDITOR_FFMPEG_LANE.key,
        "resource_requirements": [_VIDEO_EDITOR_FFMPEG_LANE.key],
        "acquired_resources": [],
        "created_at": now,
        "queued_at": now,
        "updated_at": now,
        "_cancel_requested": False,
        "_resource_acquired": False,
        "_worker_active": True,
    }
    record["status"] = "mounting"
    record["job_id"] = job_id
    save_sidecar(filepath, sidecar)
    try:
        snapshot = _register_video_editor_job(job)
    except Exception as exc:
        record["status"] = "attached"
        record["job_id"] = None
        save_sidecar(filepath, sidecar)
        raise HTTPException(status_code=500, detail=f"Could not queue remount: {exc}") from exc
    worker = threading.Thread(
        target=_run_alternative_song_mount,
        kwargs={
            "job_id": job_id,
            "out_dir": out_dir,
            "video_path": filepath,
            "video_name": video_name,
            "audio_path": audio_path,
            "output_path": output_path,
            "song_id": song_id,
            "workspace": str(job["workspace"]),
            "seed": seed,
        },
        daemon=True,
        name=f"maestro-{job_id}",
    )
    try:
        worker.start()
    except Exception as exc:
        record["status"] = "attached"
        record["job_id"] = None
        save_sidecar(filepath, sidecar)
        _video_editor_job_update(
            job_id,
            status="failed",
            phase="failed",
            error=str(exc),
            message=f"Could not start remount: {exc}",
            finished_at=time.time(),
            _worker_active=False,
        )
        raise HTTPException(status_code=500, detail=f"Could not start remount: {exc}") from exc
    return {
        "job_id": job_id,
        "task_id": snapshot.get("task_id"),
        "status": snapshot.get("status"),
        "song": public_song(record),
        "output_name": output_name,
    }
