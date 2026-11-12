"""The one H3 frame lattice: 17n+5 frames at 24 fps, 124 to 345 per native pass.

The sidecar accepted 362 frames with nearest rounding while the handler,
Series and the Director used 345 and rounded up, so a shot fitted in one path
and was refused in another. Every path reads these numbers from here.
345 is the last lattice point at or below the model's 15-second limit
(14.375 s); 362 (15.08 s) would break that contract.
"""
from __future__ import annotations

import math

FPS = 24
STEP = 17
OFFSET = 5
MIN_FRAMES = 124
MAX_FRAMES = 345
MODEL_DEF_FIELDS = {
    "fps": FPS,
    "frames_minimum": MIN_FRAMES,
    "frames_steps": STEP,
    "frames_maximum": MAX_FRAMES,
    "frame_alignment_modulus": STEP,
    "frame_alignment_remainder": OFFSET,
    "frame_alignment_mode": "ceil",
}


def align_up(frames: float) -> int:
    """The first lattice point at or above ``frames``."""
    frames = max(1, int(math.ceil(frames)))
    if frames <= OFFSET:
        return OFFSET
    return OFFSET + math.ceil((frames - OFFSET) / STEP) * STEP


def align_nearest(frames: float) -> int:
    """The lattice point closest to ``frames`` (ties go up)."""
    return OFFSET + max(0, int(math.floor((float(frames) - OFFSET) / STEP + 0.5))) * STEP


def clamp(frames: int) -> int:
    """Inside one native pass: never below 124, never above 345."""
    return max(MIN_FRAMES, min(MAX_FRAMES, int(frames)))


def frames_for_seconds(seconds: float, *, fps: int = FPS) -> int:
    """The frame count a duration needs: rounded up to the lattice, inside one pass (a 10 s request → 243)."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        value = 10.0
    if not math.isfinite(value):
        value = 10.0
    return clamp(align_up(max(0.0, value) * fps))


def seconds_for_frames(frames: int, *, fps: int = FPS) -> float:
    return round(int(frames) / fps, 3)


__all__ = ["FPS", "MAX_FRAMES", "MIN_FRAMES", "MODEL_DEF_FIELDS", "OFFSET", "STEP", "align_nearest", "align_up", "clamp",
           "frames_for_seconds", "seconds_for_frames"]
