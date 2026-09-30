"""Visual check for an H3 clip that is not sung.

Lip-sync scores a sung shot. Any other clip used to be kept on the first file.
This measures motion, flicker, color drift against the first frame, and a
center color-histogram jump. No model. OpenCV is used only to read the file.

The thresholds separate synthetic failures from a shape crossing a stable
background. They are not fitted to the Gremlins v2 clips; that folder was not
on disk, so a later pass should retune them on those 17 clips.
"""
from __future__ import annotations

from typing import Any

import numpy as np

# Motion is the mean absolute frame difference, 0–1. Below this the picture is frozen.
_STILL = 0.012
# Mean absolute second difference of luminance, 0–255. Above this the picture blinks.
_FLICKER = 18.0
# Distance of the mean color from the first frame, 0–1.
_DRIFT = 0.12
# 1 minus the worst center-histogram correlation with the first frame.
_JUMP = 0.35
_MIN_FRAMES = 4


def clip_qa(path: str, sung: bool, vocals: str | None, t0: float, t1: float) -> dict:
    """Lip-sync when the shot is sung and vocals exist; otherwise the visual check."""
    if sung and vocals:
        from services import lipsync_qa
        return lipsync_qa.measure(path, vocals, t0, [t0, t1])
    if sung:
        return {"verdict": "ok"}
    return measure_clip(path)


def measure_clip(path: str) -> dict:
    """Read a clip and judge it. A file that cannot be read is not measured, so it does not spend another take."""
    try:
        frames = _read_frames(path)
    except (OSError, ValueError):
        return _unreadable()
    return assess(frames)


def _unreadable() -> dict:
    return {"verdict": "unreliable", "reasons": ["unreadable"], "best_r": None}


def assess(frames: list) -> dict:
    """Judge frames already in memory. Each frame is HxWx3 uint8."""
    if len(frames) < _MIN_FRAMES:
        return _unreadable()
    grays = [_gray(frame) for frame in frames]
    colors = [_mean_color(frame) for frame in frames]
    motion_mean, motion_max = _motion(grays)
    flicker = _flicker(grays)
    drift = _drift(colors)
    jump = _identity(frames)
    reasons = _reasons(motion_mean, flicker, drift, jump)
    score = _score(motion_mean, flicker, drift, jump)
    return {
        "verdict": "retake" if reasons else "ok",
        "reasons": reasons,
        "best_r": round(score, 3),
        "motion_mean": round(motion_mean, 4),
        "motion_max": round(motion_max, 4),
        "flicker": round(flicker, 2),
        "color_drift": round(drift, 4),
        "identity_jump": round(jump, 4),
    }


def _reasons(motion: float, flicker: float, drift: float, jump: float) -> list[str]:
    found = []
    if motion < _STILL:
        found.append("static")
    if flicker > _FLICKER:
        found.append("flicker")
    if drift > _DRIFT:
        found.append("color_drift")
    if jump > _JUMP:
        found.append("identity")
    return found


def _score(motion: float, flicker: float, drift: float, jump: float) -> float:
    penalties = (
        _shortfall(motion, _STILL),
        _excess(flicker, _FLICKER),
        _excess(drift, _DRIFT),
        _excess(jump, _JUMP),
    )
    return max(0.0, 1.0 - sum(penalties))


def _shortfall(value: float, limit: float) -> float:
    if value >= limit:
        return 0.0
    return (limit - value) / limit


def _excess(value: float, limit: float) -> float:
    if value <= limit:
        return 0.0
    return min(1.0, (value - limit) / limit)


def _gray(frame: np.ndarray) -> np.ndarray:
    image = np.asarray(frame)
    if image.ndim == 2:
        return image.astype(np.float32)
    return image.astype(np.float32).mean(axis=2)


def _mean_color(frame: np.ndarray) -> np.ndarray:
    return np.asarray(frame, dtype=np.float32).reshape(-1, np.asarray(frame).shape[-1]).mean(axis=0)


def _motion(grays: list[np.ndarray]) -> tuple[float, float]:
    diffs = [float(np.abs(grays[i] - grays[i - 1]).mean()) / 255.0 for i in range(1, len(grays))]
    if not diffs:
        return 0.0, 0.0
    return float(np.mean(diffs)), float(np.max(diffs))


def _flicker(grays: list[np.ndarray]) -> float:
    if len(grays) < 3:
        return 0.0
    seconds = []
    for index in range(1, len(grays) - 1):
        second = np.abs(grays[index + 1] - 2.0 * grays[index] + grays[index - 1])
        seconds.append(float(second.mean()))
    return float(np.mean(seconds))


def _drift(colors: list[np.ndarray]) -> float:
    origin = colors[0]
    distances = [float(np.linalg.norm(color - origin)) / (255.0 * np.sqrt(len(origin))) for color in colors[1:]]
    return max(distances) if distances else 0.0


def _identity(frames: list) -> float:
    origin = _center_hist(frames[0])
    jumps = [1.0 - _correl(origin, _center_hist(frame)) for frame in frames[1:]]
    return max(jumps) if jumps else 0.0


def _center_hist(frame: np.ndarray) -> np.ndarray:
    image = np.asarray(frame)
    height, width = image.shape[:2]
    crop = image[height // 4: max(height // 4 + 1, 3 * height // 4), width // 4: max(width // 4 + 1, 3 * width // 4)]
    counts = []
    channels = crop.reshape(-1, crop.shape[-1]).T if crop.ndim == 3 else crop.reshape(1, -1)
    for channel in channels:
        hist, _edges = np.histogram(channel, bins=8, range=(0, 256))
        counts.append(hist.astype(np.float64))
    total = np.concatenate(counts)
    total /= total.sum() or 1.0
    return total


def _correl(left: np.ndarray, right: np.ndarray) -> float:
    a = left - left.mean()
    b = right - right.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 1.0
    return float(np.dot(a, b) / denom)


def _read_frames(path: str) -> list:
    import cv2
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        return []
    try:
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        wanted = set(_indexes(total))
        frames = []
        index = 0
        last = max(wanted) if wanted else 0
        while index <= last:
            ok, frame = capture.read()
            if not ok:
                break
            if index in wanted:
                frames.append(_downscale(frame, cv2))
            index += 1
        return frames
    finally:
        capture.release()


def _indexes(total: int, windows: int = 4, run: int = 8) -> list[int]:
    if total < _MIN_FRAMES:
        return list(range(max(total, 0)))
    if total <= windows * run:
        return list(range(total))
    span = total - run
    chosen: list[int] = []
    for slot in range(windows):
        start = int(round(slot * span / (windows - 1)))
        chosen.extend(range(start, start + run))
    return chosen


def _downscale(frame: Any, cv2: Any) -> np.ndarray:
    height, width = frame.shape[:2]
    if width <= 96:
        return frame
    return cv2.resize(frame, (96, max(1, int(round(height * 96 / width)))), interpolation=cv2.INTER_AREA)
