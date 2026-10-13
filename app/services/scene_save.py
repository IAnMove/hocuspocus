"""Save a scene document and publish a scene recording for both servers.

Launch and core keep their own scene-file answers. The workspace query on a
recording URL is an injected option: core adds it, launch does not. Recording
transcode runs off the event loop, two jobs at a time, and a declared upload
size over the cap is refused before the body is read.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote

from fastapi import HTTPException

from services import core_workspace as core
from services.asset_manifest import publish_generation_sidecar
from services.scene_recording import (
    SceneRecordingTranscodeError,
    canonical_scene_fps,
    transcode_scene_recording,
)
from services.upload_stream import UploadTooLargeError, stream_upload_file

MAX_RECORDING_BYTES = 500 * 1024 * 1024
MAX_AUDIO_BYTES = 32 * 1024 * 1024
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_PREVIEW_BYTES = 20 * 1024 * 1024
output_scan_cache: dict[str, Any] = {}
_SCAN_LOCK = threading.Lock()
_SLOTS_BY_LOOP: dict[int, asyncio.Semaphore] = {}

WorkspaceDir = Callable[[str | None], str]
StreamUpload = Callable[..., Awaitable[int]]


class SceneRecordingSidecarError(Exception):
    """The MP4 was written and then its sidecar failed. The detail is already worded."""


def parse_recording_metadata(raw: object) -> dict[str, Any]:
    text = raw if isinstance(raw, str) else "{}"
    if len(text.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValueError("Scene recording metadata is too large")
    try:
        details = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("Invalid scene recording metadata") from error
    if not isinstance(details, dict):
        raise ValueError("Scene recording metadata must be an object")
    scene = details.get("scene")
    recipe = details.get("recipe")
    prompt = details.get("prompt", "")
    if not isinstance(scene, dict) or scene.get("version") != 1:
        raise ValueError("A version 1 scene is required")
    if recipe is not None and not isinstance(recipe, dict):
        raise ValueError("Scene recipe must be an object")
    if not isinstance(prompt, str) or len(prompt) > 200_000:
        raise ValueError("Scene prompt must be text under 200,000 characters")
    layers = scene.get("layers")
    if not isinstance(layers, list) or len(layers) > 500:
        raise ValueError("Scene layers must be a list of at most 500 items")
    return details


def collect_scene_audio_tracks(
    scene: dict[str, Any],
    out_dir: str,
    *,
    safe_join: Callable[..., str | None] | None = None,
) -> list[dict[str, Any]]:
    join = safe_join or core.safe_join
    raw_audio_tracks = scene.get("audioTracks") or []
    if not isinstance(raw_audio_tracks, list) or len(raw_audio_tracks) > 8:
        raise ValueError("Scene audio tracks must be a list of at most 8 items")
    audio_tracks: list[dict[str, Any]] = []
    for index, raw_track in enumerate(raw_audio_tracks):
        if not isinstance(raw_track, dict):
            raise ValueError(f"Scene audio track {index + 1} is invalid")
        filename = str(raw_track.get("filename") or "").strip()
        if not filename or os.path.basename(filename) != filename:
            raise ValueError(f"Scene audio track {index + 1} has an invalid filename")
        audio_path = join(out_dir, filename)
        if not audio_path or not os.path.isfile(audio_path):
            raise ValueError(f"Scene audio track {index + 1} was not found in this workspace")
        try:
            start_time = max(0.0, min(3600.0, float(raw_track.get("startTime", 0))))
            volume = max(0.0, min(2.0, float(raw_track.get("volume", 1))))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Scene audio track {index + 1} has invalid timing") from error
        audio_tracks.append({"path": audio_path, "start_time": start_time, "volume": volume})
    return audio_tracks


def recording_output_name(scene: dict[str, Any]) -> str:
    raw_name = str(scene.get("name") or "3D scene").strip()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_name).strip("-._")[:80] or "3d-scene"
    stamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
    return f"{stamp}_{safe_name}_3d_{uuid.uuid4().hex[:6]}.mp4"


def finalize_scene_recording(
    *,
    source_path: str,
    output_dir: str,
    scene: dict[str, Any],
    recipe: dict[str, Any] | None,
    prompt: str,
    embedded_audio: bool,
    extra_audio_path: str | None,
    workspace: str | None,
    started_at: float | None = None,
    include_workspace_query: bool = True,
    sidecar_error_prefix: str = "Could not save MP4 recording",
    safe_join: Callable[..., str | None] | None = None,
) -> dict[str, Any]:
    audio_tracks = collect_scene_audio_tracks(scene, output_dir, safe_join=safe_join)
    if extra_audio_path:
        audio_tracks.append({"path": extra_audio_path, "start_time": 0, "volume": 1})
    output_name = recording_output_name(scene)
    output_path = os.path.join(output_dir, output_name)
    fps = canonical_scene_fps(scene.get("fps"))
    begun = started_at if started_at is not None else time.time()
    transcode_scene_recording(
        source_path,
        output_path,
        fps=fps,
        audio_tracks=audio_tracks,
        duration=float(scene.get("duration") or 0),
        embedded_audio=embedded_audio,
    )
    completed_at = time.time()
    width = int(scene.get("width") or 0)
    height = int(scene.get("height") or 0)
    duration = float(scene.get("duration") or 0)
    source_assets = []
    if isinstance(recipe, dict):
        source_assets = recipe.get("assets") if isinstance(recipe.get("assets"), list) else []
    if not source_assets:
        layers = scene.get("layers") if isinstance(scene.get("layers"), list) else []
        source_assets = [
            {
                "id": layer.get("id"),
                "name": layer.get("name"),
                "kind": layer.get("type"),
                "source": layer.get("source"),
            }
            for layer in layers
            if isinstance(layer, dict) and layer.get("source")
        ]
    sidecar = {
        "params": {
            "model_type": "scene-animator-3d",
            "generation_mode": "3d-scene-compositor",
            "prompt": prompt,
            "original_prompt": prompt,
            "scene_recipe": recipe,
            "scene": scene,
            "source_assets": source_assets,
            "audio_tracks": scene.get("audioTracks") or [],
            "resolution": f"{width}x{height}" if width and height else None,
            "width": width,
            "height": height,
            "fps": fps,
            "duration_seconds": duration,
            "video_length": round(duration * fps) if duration > 0 else None,
        },
        "generation_mode": "video",
        "tool": "scene-animator-3d",
        "generation_time": round(completed_at - begun, 3),
        "created_at": completed_at,
        "completed_at": completed_at,
        "output_filename": output_name,
    }
    try:
        publish_generation_sidecar(
            output_path,
            sidecar,
            workspace_id=workspace,
            tool="scene-animator-3d",
        )
    except Exception as error:
        try:
            os.remove(output_path)
        except OSError:
            pass
        raise SceneRecordingSidecarError(f"{sidecar_error_prefix}: {error}") from error
    suffix = f"?workspace={workspace}" if include_workspace_query and workspace else ""
    return {
        "name": output_name,
        "type": "video",
        "mode": "video",
        "size": os.path.getsize(output_path),
        "created_at": completed_at,
        "completed_at": completed_at,
        "url": f"/api/v1/file/{output_name}{suffix}",
        "thumbnail_url": f"/api/v1/outputs/thumbnail/{quote(output_name, safe='')}{suffix}",
    }


def drop_output_scan(folder: str, cache: dict | None = None, lock: threading.Lock | None = None) -> None:
    target = output_scan_cache if cache is None else cache
    guard = _SCAN_LOCK if lock is None else lock
    with guard:
        target.pop(folder, None)


async def _close_upload(upload: Any) -> None:
    close = getattr(upload, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


async def _reject_declared_size(upload: Any, limit: int) -> None:
    size = getattr(upload, "size", None)
    if size is None:
        return
    try:
        too_big = int(size) > limit
    except (TypeError, ValueError):
        return
    if not too_big:
        return
    await _close_upload(upload)
    raise UploadTooLargeError("recording exceeds the size cap")


def _default_slots() -> asyncio.Semaphore:
    """Two ffmpeg jobs per event loop. A semaphore cannot move to another loop."""
    loop = asyncio.get_running_loop()
    slots = _SLOTS_BY_LOOP.get(id(loop))
    if slots is None:
        slots = asyncio.Semaphore(2)
        _SLOTS_BY_LOOP[id(loop)] = slots
    return slots


async def _finalize_in_slot(slots: asyncio.Semaphore, **kwargs: Any) -> dict[str, Any]:
    async with slots:
        return await asyncio.to_thread(finalize_scene_recording, **kwargs)


def _remove_temp(path: str) -> None:
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


async def publish_from_form(
    form: Any,
    *,
    workspace_dir: WorkspaceDir | None = None,
    include_workspace_query: bool = True,
    scan_cache: dict | None = None,
    scan_cache_lock: threading.Lock | None = None,
    stream_upload: StreamUpload | None = None,
    transcode_slots: asyncio.Semaphore | None = None,
    sidecar_error_prefix: str = "Could not save MP4 recording",
    safe_join: Callable[..., str | None] | None = None,
) -> dict[str, Any]:
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise ValueError("A recording file is required")
    await _reject_declared_size(upload, MAX_RECORDING_BYTES)
    try:
        details = parse_recording_metadata(form.get("metadata") or "{}")
    except ValueError:
        await _close_upload(upload)
        raise
    scene = details["scene"]
    recipe = details.get("recipe") if isinstance(details.get("recipe"), dict) else None
    prompt = str(details.get("prompt") or "")
    workspace = str(details.get("workspace") or "").strip() or None
    resolve = workspace_dir or core.workspace_dir
    folder = resolve(workspace)
    os.makedirs(folder, exist_ok=True)
    upload_path = os.path.join(folder, f".{uuid.uuid4().hex}.scene-recording.webm")
    upload_audio_path = os.path.join(folder, f".{uuid.uuid4().hex}.scene-audio.wav")
    audio = form.get("audio")
    started_at = time.time()
    wrote_audio = False
    ingest = stream_upload or stream_upload_file
    slots = transcode_slots or _default_slots()
    try:
        await ingest(upload, upload_path, max_bytes=MAX_RECORDING_BYTES)
        if audio is not None and hasattr(audio, "read"):
            await ingest(audio, upload_audio_path, max_bytes=MAX_AUDIO_BYTES)
            wrote_audio = True
        saved = await _finalize_in_slot(
            slots,
            source_path=upload_path,
            output_dir=folder,
            scene=scene,
            recipe=recipe,
            prompt=prompt,
            embedded_audio=details.get("embeddedAudio") is True,
            extra_audio_path=upload_audio_path if wrote_audio else None,
            workspace=workspace,
            started_at=started_at,
            include_workspace_query=include_workspace_query,
            sidecar_error_prefix=sidecar_error_prefix,
            safe_join=safe_join,
        )
    finally:
        _remove_temp(upload_audio_path)
        _remove_temp(upload_path)
    drop_output_scan(folder, scan_cache, scan_cache_lock)
    return saved


def http_error_status(error: Exception) -> int:
    if isinstance(error, UploadTooLargeError):
        return 413
    if isinstance(error, SceneRecordingTranscodeError):
        return 400
    if isinstance(error, ValueError):
        return 400
    return 500


def http_error_detail(error: Exception) -> str:
    if isinstance(error, UploadTooLargeError):
        return "Recording is too large (max 500 MB)"
    if isinstance(error, SceneRecordingTranscodeError):
        return f"Could not convert recording to MP4: {error}"
    if isinstance(error, SceneRecordingSidecarError):
        return str(error)
    if isinstance(error, ValueError):
        return str(error)
    return f"Could not save MP4 recording: {error}"


def save_launch_scene(body: dict, *, workspace_dir: WorkspaceDir) -> dict[str, Any]:
    """Persist a Scene Animator project. The returned URLs have no workspace query."""
    import base64

    from services.document_origin import write_document_origin

    scene = body.get("scene")
    preview = body.get("preview")
    if not isinstance(scene, dict) or scene.get("version") != 1:
        raise HTTPException(status_code=400, detail="A version 1 scene is required")
    layers = scene.get("layers")
    if not isinstance(layers, list) or len(layers) > 500:
        raise HTTPException(status_code=400, detail="Scene layers must be a list of at most 500 items")
    if not isinstance(preview, str) or not preview.startswith("data:image/png;base64,"):
        raise HTTPException(status_code=400, detail="A PNG scene preview is required")
    try:
        preview_bytes = base64.b64decode(preview.split(",", 1)[1], validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid PNG preview") from exc
    if len(preview_bytes) > MAX_PREVIEW_BYTES:
        raise HTTPException(status_code=413, detail="Scene preview is too large")

    raw_name = str(scene.get("name") or "Untitled scene").strip()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_name).strip("-._")[:80] or "scene"
    stamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
    stem = f"{stamp}_{safe_name}_{uuid.uuid4().hex[:6]}.scene"
    out_dir = workspace_dir(body.get("workspace") or None)
    os.makedirs(out_dir, exist_ok=True)
    scene_name = f"{stem}.json"
    preview_name = f"{stem}.preview.png"
    scene_path = os.path.join(out_dir, scene_name)
    preview_path = os.path.join(out_dir, preview_name)
    scene_tmp = scene_path + ".tmp"
    preview_tmp = preview_path + ".tmp"
    try:
        with open(scene_tmp, "w", encoding="utf-8") as handle:
            json.dump(scene, handle, ensure_ascii=False, indent=2)
        with open(preview_tmp, "wb") as handle:
            handle.write(preview_bytes)
        os.replace(scene_tmp, scene_path)
        os.replace(preview_tmp, preview_path)
    except Exception as exc:
        for path in (scene_tmp, preview_tmp):
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to save scene: {exc}") from exc
    write_document_origin(Path(scene_path), "scenes.save")
    return {
        "name": scene_name,
        "type": "scene",
        "url": f"/api/v1/file/{scene_name}",
        "thumbnail_url": f"/api/v1/file/{preview_name}",
    }


def save_core_scene(body: Any, *, workspace_dir: WorkspaceDir, active_workspace: Callable[[], str]) -> dict[str, Any]:
    """Core's scene save: no preview, and the file URL keeps ?workspace=."""
    scene = body.get("scene") if isinstance(body, dict) else None
    if not isinstance(scene, dict):
        raise HTTPException(status_code=400, detail="A version 1 scene is required")
    workspace = body.get("workspace")
    if workspace is None:
        workspace = active_workspace()
    folder = workspace_dir(workspace)
    os.makedirs(folder, exist_ok=True)
    name = f"{time.strftime('%Y-%m-%d-%Hh%Mm%Ss')}_scene_{uuid.uuid4().hex[:6]}.scene.json"
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(scene, handle)
    return {"name": name, "type": "scene", "url": f"/api/v1/file/{name}?workspace={workspace}"}


def publish_layer_scene(
    *,
    folder: Path,
    stem: str,
    encoded: str,
    png: bytes | None,
    workspace: str,
    document: dict,
    capability: str,
) -> dict[str, Any]:
    """Write one Video 2D scene revision the way scene_documents.save_document does."""
    from services.document_origin import write_document_origin
    from services.scene_links import remember_saved

    target = folder / (stem + ".scene.json")
    temporary = folder / (stem + ".scene.json.tmp")
    if png:
        (folder / (stem + ".scene.preview.png")).write_bytes(png)
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(encoded)
    temporary.replace(target)
    remember_saved(folder, document, target.name)
    write_document_origin(target, capability)

    def file_url(name: str) -> str:
        return "/api/v1/file/" + quote(name) + "?workspace=" + quote(workspace, safe="")

    saved = {
        "name": target.name,
        "type": "scene",
        "workspace_id": workspace,
        "url": file_url(target.name),
        "editor": "video2d",
    }
    if png:
        saved["thumbnail_url"] = file_url(stem + ".scene.preview.png")
    return saved
