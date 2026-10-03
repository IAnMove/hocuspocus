"""Platform encode presets, pre-export warnings, and optional loudness normalisation.

The pass stays on FFmpeg. It does not enter the generation queue.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

PRESETS = {
    "x": {"max_seconds": 140, "premium_max_seconds": 180, "aspect": (16, 9), "audio_bitrate": "128k"},
    "youtube": {"max_seconds": None, "premium_max_seconds": None, "aspect": (16, 9), "audio_bitrate": "192k"},
    "shorts": {"max_seconds": 60, "premium_max_seconds": 90, "aspect": (9, 16), "audio_bitrate": "128k"},
    "archive": {"max_seconds": None, "premium_max_seconds": None, "aspect": None, "audio_bitrate": "320k"},
}


class PublishPresetError(ValueError):
    def __init__(self, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def encode_args(preset: str, *, premium: bool = False) -> list[str]:
    spec = PRESETS.get(preset)
    if spec is None:
        raise PublishPresetError("Unknown publish preset")
    video = ["-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p"]
    if preset == "archive":
        video += ["-preset", "slow", "-crf", "12"]
    else:
        video += ["-preset", "medium", "-crf", "18"]
    return [*video, "-c:a", "aac", "-b:a", spec["audio_bitrate"]]


def _aspect_differs(width: int, height: int, target: tuple[int, int]) -> bool:
    if width <= 0 or height <= 0:
        return True
    return abs((width / height) - (target[0] / target[1])) > 0.02


def collect_warnings(
    *,
    preset: str,
    width: int,
    height: int,
    duration: float,
    overlays: list[dict[str, Any]] | None = None,
    premium: bool = False,
) -> list[dict[str, Any]]:
    spec = PRESETS.get(preset)
    if spec is None:
        raise PublishPresetError("Unknown publish preset")
    found: list[dict[str, Any]] = []
    limit = spec["premium_max_seconds"] if premium else spec["max_seconds"]
    if limit is not None and float(duration) > float(limit):
        found.append({"code": "duration", "limit": limit, "duration": round(float(duration), 3)})
    aspect = spec["aspect"]
    if aspect is not None and _aspect_differs(int(width), int(height), aspect):
        found.append({"code": "aspect", "expected": f"{aspect[0]}:{aspect[1]}"})
    if preset == "shorts":
        outside = []
        for item in overlays or []:
            if not isinstance(item, dict):
                continue
            y = float(item.get("y") if item.get("y") is not None else 50)
            item_width = float(item.get("width") if item.get("width") is not None else 100)
            if y < 12 or y > 80 or item_width > 90:
                outside.append(str(item.get("id") or "overlay"))
        if outside:
            found.append({"code": "safe_area", "ids": outside})
    return found


def _run(command: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffmpeg failed").strip()[-800:]
        raise PublishPresetError(detail, status=500)
    return result


def measure_loudnorm(source: str) -> dict[str, str]:
    result = _run([
        "ffmpeg", "-hide_banner", "-i", source,
        "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
        "-f", "null", "-",
    ])
    start = result.stderr.rfind("{")
    end = result.stderr.rfind("}")
    if start < 0 or end < start:
        raise PublishPresetError("loudnorm did not report a measurement", status=500)
    measured = json.loads(result.stderr[start:end + 1])
    return {key: str(measured[key]) for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}


def loudnorm_filter(measured: dict[str, str]) -> str:
    return (
        "loudnorm=I=-14:TP=-1:LRA=11:"
        f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
        f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
        f"offset={measured['target_offset']}:linear=true"
    )


def integrated_lufs(path: str) -> float:
    result = _run(["ffmpeg", "-hide_banner", "-i", path, "-af", "ebur128", "-f", "null", "-"])
    matches = []
    for line in result.stderr.splitlines():
        stripped = line.strip()
        if stripped.startswith("I:"):
            matches.append(float(stripped.split()[1]))
    if not matches:
        raise PublishPresetError("ebur128 did not report integrated loudness", status=500)
    return matches[-1]


def render_publish(source: str, destination: str, preset: str, *, premium: bool = False, loudnorm: dict[str, str] | None = None) -> list[str]:
    command = publish_command(source, destination, preset, premium=premium, loudnorm=loudnorm)
    _run(command, timeout=1800)
    return command


def publish_command(source: str, destination: str, preset: str, *, premium: bool = False, loudnorm: dict[str, str] | None = None) -> list[str]:
    command = ["ffmpeg", "-y", "-i", source]
    if loudnorm:
        command += ["-af", loudnorm_filter(loudnorm)]
    command += encode_args(preset, premium=premium)
    command += ["-movflags", "+faststart", destination]
    return command
