"""Attach extra songs to an assembled videoclip and remount without GPU.

The original mix stays put. Each alternative song is a sidecar record that can
be mounted later with FFmpeg: reuse the source-clip order, then randomly
append shots from that pool if the new track is longer. A shorter track keeps
the original order and is cut with ``-shortest``.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import uuid
from typing import Any, Callable

from services.mix_concat import probe_duration_seconds
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


def save_sidecar(video_path: str, sidecar: dict[str, Any]) -> None:
    path = sidecar_path(video_path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(sidecar, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


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
            "resolution": parent_params.get("resolution") or "",
        },
        "result_kind": "music_video",
        "generation_mode": "video",
        "job_id": job_id,
        "workspace": workspace,
        "created_at": time.time(),
        "parent_output": parent_name,
    }
    save_sidecar(output_path, payload)
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
        save_sidecar(output_path, payload)


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
    try:
        from wgp import concatenate_multi_clip_videos
    except ImportError:
        from app.wgp import concatenate_multi_clip_videos  # type: ignore
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
