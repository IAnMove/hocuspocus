"""Cut an approved take to its start and end before the episode join.

A take with no range (the fields absent, or the library default of 0 and 0)
is left as the original file, so the join sees the same bytes it did before.
A named range must be ``0 <= start < end`` and, once the file is known, must
not run past it. The cut keeps the source frame rate and the same in and out
on the sound, so the picture and the sound stay together.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
from typing import Any

# A millisecond past the container is float noise, not a different cut.
_SLACK = 0.001


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"Invalid take range: {label} must be a finite number of seconds")
    return float(value)


def named_range(record: dict[str, Any]) -> tuple[float, float] | None:
    """``(start, end)`` when ``record`` names a cut; None when it does not.

    Raises ``ValueError`` when the named numbers cannot be a cut, before the
    file length is known.
    """
    has_start, has_end = "startTimeSeconds" in record, "endTimeSeconds" in record
    if not has_start and not has_end:
        return None
    start = _number(record.get("startTimeSeconds"), "startTimeSeconds") if has_start else 0.0
    if not has_end:
        raise ValueError("Invalid take range: endTimeSeconds is required when startTimeSeconds is set")
    end = _number(record.get("endTimeSeconds"), "endTimeSeconds")
    if start == 0 and end == 0:
        return None
    if start < 0 or end <= start:
        raise ValueError(
            f"Invalid take range: startTimeSeconds ({start:g}) must be >= 0 "
            f"and less than endTimeSeconds ({end:g})"
        )
    return start, end


def _rate(value: Any) -> float:
    top, _, bottom = str(value or "").partition("/")
    try:
        rate = float(top) / float(bottom or 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
    return rate if rate > 0 else 0.0


def _probe(path: str) -> dict[str, Any]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True, text=True, timeout=60, check=False,
    )
    data = json.loads(result.stdout or "{}") if result.returncode == 0 else {}
    video = next((item for item in data.get("streams") or [] if item.get("codec_type") == "video"), None)
    if not isinstance(video, dict):
        raise ValueError(f"Invalid take range: {os.path.basename(path)} has no video stream")
    audio = next((item for item in data.get("streams") or [] if item.get("codec_type") == "audio"), None)
    duration = float(video.get("duration") or (data.get("format") or {}).get("duration") or 0)
    fps = _rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    if duration <= 0 or fps <= 0:
        raise ValueError(f"Invalid take range: {os.path.basename(path)} has no readable duration or frame rate")
    try:
        frames = int(video.get("nb_frames") or 0)
    except (TypeError, ValueError):
        frames = 0
    return {
        "duration": duration, "fps": fps, "frames": frames or int(round(duration * fps)),
        "audio": isinstance(audio, dict),
    }


def _cut(start: float, end: float, info: dict[str, Any], name: str) -> tuple[float, float] | None:
    """The in and out to encode, or None when the range is already the whole file."""
    duration, fps = float(info["duration"]), float(info["fps"])
    if end > duration + _SLACK:
        raise ValueError(f"Invalid take range: endTimeSeconds ({end:g}) is past {name} ({duration:.3f} s)")
    end = min(end, duration)
    start_frame, end_frame = int(round(start * fps)), int(round(end * fps))
    if start_frame <= 0 and end_frame >= int(info["frames"]):
        return None
    if end_frame <= start_frame:
        raise ValueError(
            f"Invalid take range: {start:g}–{end:g} s is shorter than one frame of {name} ({fps:g} fps)"
        )
    return start_frame / fps, end_frame / fps


def _trim(source: str, dest: str, start: float, end: float, fps: float, audio: bool) -> None:
    """Frame-accurate picture at the source rate, sound cut on the same times."""
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", source,
        "-ss", f"{start:.6f}", "-to", f"{end:.6f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-r", f"{fps:.6f}",
    ]
    command += ["-c:a", "pcm_s16le"] if audio else ["-an"]
    command.append(dest)
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    if completed.returncode != 0 or not os.path.isfile(dest) or os.path.getsize(dest) == 0:
        raise ValueError(f"Could not trim the take {os.path.basename(source)}")


def apply_take_ranges(paths: list[str], clips: list[dict[str, Any]], directory: str) -> list[str]:
    """Paths for the join. A named valid range is a trimmed copy; every other take is unchanged."""
    os.makedirs(directory, exist_ok=True)
    chosen: list[str] = []
    for index, path in enumerate(paths):
        clip = clips[index] if index < len(clips) and isinstance(clips[index], dict) else {}
        span = named_range(clip)
        if span is None:
            chosen.append(path)
            continue
        info = _probe(path)
        window = _cut(span[0], span[1], info, os.path.basename(path))
        if window is None:
            chosen.append(path)
            continue
        dest = os.path.join(directory, f"take-{index:03d}.mov")
        _trim(path, dest, window[0], window[1], float(info["fps"]), bool(info["audio"]))
        chosen.append(dest)
    return chosen
