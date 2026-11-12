"""Is every shot's sound where its pictures are, in a joined episode?

Each approved take carries its own sound (lines, effects, foley), already in sync with its mouths. After the join
and the finishing passes, that sound must play from the moment the take's pictures do. This reads both, at a speech
envelope resolution of 5 ms, and finds by cross-correlation where each take's sound really is on the episode's
timeline: the lag against where the join placed its pictures. Ambience and score laid on top lower the correlation
but do not move its peak. A take whose sound cannot be told apart (silence, a still with a drone) is reported as
unsure, not as late.

It is how a drifting join is caught (#903: ~10 ms a join, 2.7 s over 268 shots), whatever the cause. A take that
cannot be placed says nothing about the ones after it, so the sound's length is also held against the pictures': a
pass that adds or drops sound moves every later take, placed or not.
"""
from __future__ import annotations

import subprocess
from collections.abc import Sequence
from typing import Any

import numpy as np

from services.mix_concat import ffprobe_for

RATE = 8000
# Envelope step, seconds: 5 ms, well under a 24 fps frame.
HOP = 0.005
# How far either way of its planned start a take's sound is looked for, seconds.
SEARCH = 0.75
# Lips read late beyond about a frame: past this the take is reported out of sync.
TOLERANCE = 0.045
# A peak correlation below this is not trusted to place the take.
MIN_SCORE = 0.45
# Takes shorter than this hold too little sound to place.
MIN_SECONDS = 0.4
# The sound and the pictures may end a video frame and an AAC frame apart; more is sound added or lost on the way.
LENGTH_TOLERANCE = 0.1


def decode(path: str, ffmpeg: str, *, timeout: float = 600) -> np.ndarray | None:
    """The file's sound as mono samples at ``RATE``, or None when it has none."""
    try:
        completed = subprocess.run(
            [ffmpeg, "-v", "error", "-nostdin", "-i", path, "-map", "0:a:0", "-ac", "1", "-ar", str(RATE),
             "-f", "f32le", "-"], capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout:
        return None
    return np.frombuffer(completed.stdout, dtype=np.float32)


def picture_seconds(path: str, ffmpeg: str) -> float | None:
    """How long the file's pictures run, or None when it cannot be read."""
    try:
        completed = subprocess.run(
            [ffprobe_for(ffmpeg), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
             "-of", "csv=p=0", path], capture_output=True, text=True, timeout=30)
        return float((completed.stdout or "").strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def envelope(samples: np.ndarray) -> np.ndarray:
    """Loudness every ``HOP`` with its slow level taken away: onsets and syllables stand out, a steady bed does not."""
    step = int(RATE * HOP)
    count = len(samples) // step
    if count == 0:
        return np.zeros(0)
    frames = samples[:count * step].reshape(count, step).astype(np.float64)
    level = np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-4)
    width = max(1, int(0.2 / HOP))
    slow = np.convolve(level, np.ones(width) / width, mode="same")
    return np.clip(level - slow, 0.0, None)


def _correlations(window: np.ndarray, probe: np.ndarray) -> np.ndarray:
    """Pearson correlation of ``probe`` with every same-length stretch of ``window``."""
    n = len(probe)
    centred = probe - probe.mean()
    norm = np.sqrt((centred ** 2).sum())
    if norm == 0:
        return np.zeros(max(0, len(window) - n + 1))
    dots = np.correlate(window, centred, mode="valid")
    sums = np.concatenate(([0.0], np.cumsum(window)))
    squares = np.concatenate(([0.0], np.cumsum(window ** 2)))
    totals, square_totals = sums[n:] - sums[:-n], squares[n:] - squares[:-n]
    spread = np.sqrt(np.maximum(square_totals - totals ** 2 / n, 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(spread > 0, dots / (spread * norm), 0.0)


def take_lag(take: np.ndarray, episode: np.ndarray, start: float, around: float = 0.0) -> tuple[float, float] | None:
    """Where ``take``'s envelope sits in ``episode``'s against ``start`` (seconds; positive: the sound is late) and
    the peak correlation, looked for within ``SEARCH`` of ``around`` (the lag found so far), or None when the take is
    too short or silent to place."""
    if len(take) * HOP < MIN_SECONDS or not take.any():
        return None
    search = int(SEARCH / HOP)
    first = int(round((start + around) / HOP)) - search
    low = max(0, first)
    window = episode[low:low + len(take) + 2 * search + (low - first)]
    if len(window) < len(take):
        return None
    scores = _correlations(window, take)
    if not len(scores):
        return None
    best = int(np.argmax(scores))
    return (low + best - int(round(start / HOP))) * HOP, float(scores[best])


def check_sync(output_path: str, clip_paths: Sequence[str], offsets: Sequence[float], *, ffmpeg: str,
               tolerance: float = TOLERANCE) -> dict[str, Any]:
    """Each take's sound against where its pictures start in ``output_path`` (``offsets``, the join's clip starts).

    ``late``: takes whose sound is off by more than ``tolerance``, in episode order, with ``index`` (0-based clip),
    ``lagMs`` (positive: the sound comes after the pictures) and ``score``. ``unsure``: takes that could not be placed.
    ``lengthGapMs``: how much longer the sound runs than the pictures; past ``LENGTH_TOLERANCE`` it is out of sync too.
    """
    joined = decode(output_path, ffmpeg)
    if joined is None:
        return {"checked": False, "reason": "The joined episode has no readable sound"}
    episode = envelope(joined)
    placed: list[dict[str, Any]] = []
    unsure: list[int] = []
    # A drifting join moves every later take further: each is looked for around the lag of the last one placed.
    drift = 0.0
    for index, (path, start) in enumerate(zip(clip_paths, offsets)):
        samples = decode(path, ffmpeg)
        found = take_lag(envelope(samples), episode, float(start), drift) if samples is not None else None
        if found is None or found[1] < MIN_SCORE:
            unsure.append(index)
            continue
        drift = found[0]
        placed.append({"index": index, "lagMs": round(found[0] * 1000), "score": round(found[1], 2)})
    late = [item for item in placed if abs(item["lagMs"]) > tolerance * 1000]
    worst = max((abs(item["lagMs"]) for item in placed), default=0)
    pictures = picture_seconds(output_path, ffmpeg)
    gap = {} if pictures is None else {"lengthGapMs": round((len(joined) / RATE - pictures) * 1000)}
    return {"checked": True, "inSync": not late and not _lengths_differ(gap), "placed": len(placed), "unsure": unsure,
            "toleranceMs": round(tolerance * 1000), "maxLagMs": worst, "late": late,
            "lags": [[item["index"], item["lagMs"]] for item in placed], **gap}


def _lengths_differ(report: dict[str, Any]) -> bool:
    return abs(report.get("lengthGapMs") or 0) > LENGTH_TOLERANCE * 1000


def sync_note(report: dict[str, Any]) -> str:
    """One sentence for the assembly message."""
    if not report.get("checked"):
        return f"Sound sync not checked: {report.get('reason', 'unknown')}."
    if report["inSync"]:
        return f"Sound in sync on {report['placed']} clips (worst {report['maxLagMs']} ms)."
    late, notes = report["late"], []
    if late:
        notes.append(f"Sound out of sync on {len(late)} of {report['placed']} clips, from clip {late[0]['index'] + 1} "
                     f"(worst {report['maxLagMs']} ms).")
    if _lengths_differ(report):
        gap = report["lengthGapMs"]
        notes.append(f"The sound runs {abs(gap)} ms {'longer' if gap > 0 else 'shorter'} than the pictures.")
    return " ".join(notes)
