"""Platform encode presets, pre-export warnings, and optional loudness normalisation.

The pass stays on FFmpeg. It does not enter the generation queue.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from typing import Any

PRESETS = {
    "x": {"max_seconds": 140, "premium_max_seconds": 180, "aspect": (16, 9), "audio_bitrate": "128k", "lufs": -14.0, "true_peak": -1.0},
    "youtube": {"max_seconds": None, "premium_max_seconds": None, "aspect": (16, 9), "audio_bitrate": "192k", "lufs": -14.0, "true_peak": -1.0},
    "shorts": {"max_seconds": 60, "premium_max_seconds": 90, "aspect": (9, 16), "audio_bitrate": "128k", "lufs": -14.0, "true_peak": -1.0},
    "apple": {"max_seconds": None, "premium_max_seconds": None, "aspect": None, "audio_bitrate": "192k", "lufs": -16.0, "true_peak": -1.0},
    "broadcast": {"max_seconds": None, "premium_max_seconds": None, "aspect": None, "audio_bitrate": "192k", "lufs": -23.0, "true_peak": -1.0},
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
        video += ["-preset", "slow", "-crf", "14"]
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


def loudness_target(preset: str) -> tuple[float, float] | None:
    spec = PRESETS.get(preset)
    if spec is None:
        raise PublishPresetError("Unknown publish preset")
    lufs = spec.get("lufs")
    if lufs is None:
        return None
    return float(lufs), float(spec["true_peak"])


def measure_loudnorm(source: str, preset: str = "x") -> dict[str, str]:
    target = loudness_target(preset)
    if target is None:
        raise PublishPresetError("This preset is not loudness-normalized")
    lufs, peak = target
    result = _run([
        "ffmpeg", "-hide_banner", "-i", source,
        "-af", f"loudnorm=I={lufs:g}:TP={peak:g}:LRA=11:print_format=json",
        "-f", "null", "-",
    ])
    start = result.stderr.rfind("{")
    end = result.stderr.rfind("}")
    if start < 0 or end < start:
        raise PublishPresetError("loudnorm did not report a measurement", status=500)
    measured = json.loads(result.stderr[start:end + 1])
    return {key: str(measured[key]) for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}


def loudnorm_usable(measured: dict[str, str] | None) -> bool:
    """Two-pass loudnorm rejects non-finite measured_* (digital silence is -inf)."""
    if not measured:
        return False
    try:
        values = {
            key: float(measured[key])
            for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
        }
    except (KeyError, TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in values.values()):
        return False
    return -99.0 <= values["input_i"] <= 0.0 and -99.0 <= values["target_offset"] <= 99.0


def _json_loudness(value: float) -> float | None:
    if not math.isfinite(value):
        return None
    return round(value, 1)


def loudnorm_filter(measured: dict[str, str], preset: str = "x") -> str:
    target = loudness_target(preset)
    if target is None:
        raise PublishPresetError("This preset is not loudness-normalized")
    lufs, peak = target
    return (
        f"loudnorm=I={lufs:g}:TP={peak:g}:LRA=11:"
        f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
        f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
        f"offset={measured['target_offset']}:linear=true"
    )


def _program(path: str) -> dict[str, float]:
    result = _run(["ffmpeg", "-hide_banner", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"])
    lufs = None
    peak = None
    for line in result.stderr.splitlines():
        stripped = line.strip()
        if stripped.startswith("I:"):
            lufs = float(stripped.split()[1])
        elif stripped.startswith("Peak:"):
            peak = float(stripped.split()[1])
    if lufs is None or peak is None:
        raise PublishPresetError("ebur128 did not report integrated loudness", status=500)
    return {"lufs": lufs, "true_peak": peak}


def integrated_lufs(path: str) -> float:
    return _program(path)["lufs"]


def loudness_warning(reading: dict[str, float], target: tuple[float, float]) -> dict[str, Any] | None:
    lufs, peak = target
    measured_lufs = reading["lufs"]
    measured_peak = reading["true_peak"]
    lufs_ok = math.isfinite(measured_lufs) and abs(measured_lufs - lufs) <= 1.0
    peak_ok = not math.isfinite(measured_peak) or measured_peak <= peak + 0.05
    if lufs_ok and peak_ok:
        return None
    return {
        "code": "loudness",
        "lufs": _json_loudness(measured_lufs),
        "true_peak": _json_loudness(measured_peak),
        "target_lufs": lufs,
        "target_true_peak": peak,
    }


def loudness_report(path: str, preset: str) -> dict[str, Any] | None:
    """Measured output loudness. A miss is a warning and does not raise."""
    target = loudness_target(preset)
    if target is None:
        return None
    try:
        reading = _program(path)
    except (PublishPresetError, ValueError, subprocess.TimeoutExpired):
        return {
            "lufs": None,
            "true_peak": None,
            "target_lufs": target[0],
            "target_true_peak": target[1],
            "warning": {
                "code": "loudness",
                "lufs": None,
                "true_peak": None,
                "target_lufs": target[0],
                "target_true_peak": target[1],
            },
        }
    lufs, peak = target
    return {
        "lufs": _json_loudness(reading["lufs"]),
        "true_peak": _json_loudness(reading["true_peak"]),
        "target_lufs": lufs,
        "target_true_peak": peak,
        "warning": loudness_warning(reading, target),
    }


def render_publish(source: str, destination: str, preset: str, *, premium: bool = False, loudnorm: dict[str, str] | None = None) -> list[str]:
    command = publish_command(source, destination, preset, premium=premium, loudnorm=loudnorm)
    _run(command, timeout=1800)
    return command


def publish_command(source: str, destination: str, preset: str, *, premium: bool = False, loudnorm: dict[str, str] | None = None) -> list[str]:
    command = ["ffmpeg", "-y", "-i", source]
    if loudnorm_usable(loudnorm) and loudness_target(preset) is not None:
        command += ["-af", loudnorm_filter(loudnorm, preset)]
    command += encode_args(preset, premium=premium)
    command += ["-movflags", "+faststart", destination]
    return command
