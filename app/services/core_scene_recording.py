"""Publish Scene Animator / Video3D recordings on the core/remote profile.

The UI often sends a silent canvas/WebCodecs capture plus a separate WAV mix
when the browser cannot encode AAC. The NVIDIA runtime muxes that audio into a
unique H.264 MP4. The core profile must do the same or voiced exports are
silently published without a soundtrack and a second take overwrites the first.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any
from urllib.parse import quote

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


def collect_scene_audio_tracks(scene: dict[str, Any], out_dir: str) -> list[dict[str, Any]]:
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
        audio_path = core.safe_join(out_dir, filename)
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
) -> dict[str, Any]:
    audio_tracks = collect_scene_audio_tracks(scene, output_dir)
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
    except Exception:
        try:
            os.remove(output_path)
        except OSError:
            pass
        raise
    suffix = f"?workspace={workspace}" if workspace else ""
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


async def publish_from_form(form: Any) -> dict[str, Any]:
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise ValueError("A recording file is required")
    details = parse_recording_metadata(form.get("metadata") or "{}")
    scene = details["scene"]
    recipe = details.get("recipe") if isinstance(details.get("recipe"), dict) else None
    prompt = str(details.get("prompt") or "")
    workspace = str(details.get("workspace") or "").strip() or None
    folder = core.workspace_dir(workspace)
    os.makedirs(folder, exist_ok=True)
    upload_path = os.path.join(folder, f".{uuid.uuid4().hex}.scene-recording.webm")
    upload_audio_path = os.path.join(folder, f".{uuid.uuid4().hex}.scene-audio.wav")
    audio = form.get("audio")
    started_at = time.time()
    wrote_audio = False
    try:
        await stream_upload_file(upload, upload_path, max_bytes=MAX_RECORDING_BYTES)
        if audio is not None and hasattr(audio, "read"):
            await stream_upload_file(audio, upload_audio_path, max_bytes=MAX_AUDIO_BYTES)
            wrote_audio = True
        return finalize_scene_recording(
            source_path=upload_path,
            output_dir=folder,
            scene=scene,
            recipe=recipe,
            prompt=prompt,
            embedded_audio=details.get("embeddedAudio") is True,
            extra_audio_path=upload_audio_path if wrote_audio else None,
            workspace=workspace,
            started_at=started_at,
        )
    finally:
        for path in (upload_audio_path, upload_path):
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass


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
    if isinstance(error, ValueError):
        return str(error)
    return f"Could not save MP4 recording: {error}"
