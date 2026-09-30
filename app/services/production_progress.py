"""Stage, landed clips and an ETA from this run or from saved timings.

``eta_s`` is null when there is no measured sample. It is never a guessed number.
"""
from __future__ import annotations

from typing import Any


def progress_summary(state: dict, root: str | None = None) -> dict[str, Any]:
    spec = state.get("spec") if isinstance(state.get("spec"), dict) else {}
    shots = spec.get("shots") if isinstance(spec.get("shots"), list) else []
    total_clips = sum(1 for shot in shots if isinstance(shot, dict) and shot.get("kind") == "h3")
    clips = state.get("clips") if isinstance(state.get("clips"), dict) else {}
    segments = state.get("segments") if isinstance(state.get("segments"), list) else []
    scenes = state.get("scenes") if isinstance(state.get("scenes"), dict) else {}
    done = sum(1 for item in scenes.values() if isinstance(item, dict) and item.get("file"))
    stage = state.get("stage") if isinstance(state.get("stage"), str) else None
    return {
        "stage": stage,
        "clips": _row(len(clips), total_clips, _clip_samples(state), root, "clip_s"),
        "scenes": _row(done, len(segments), [], root, "scene_s"),
    }


def _row(done: int, total: int, samples: list[float], root: str | None, kind: str) -> dict[str, Any]:
    remaining = max(0, total - done)
    return {"landed" if kind == "clip_s" else "done": done, "total": total, "eta_s": _eta(remaining, samples, root, kind)}


def _clip_samples(state: dict) -> list[float]:
    timing = state.get("timing") if isinstance(state.get("timing"), dict) else {}
    rows = timing.get("shots") if isinstance(timing.get("shots"), list) else []
    seconds = state.get("clip_seconds") if isinstance(state.get("clip_seconds"), dict) else {}
    found = [float(item["seconds"]) for item in rows if isinstance(item, dict) and isinstance(item.get("seconds"), (int, float))]
    if found:
        return found
    return [float(value) for value in seconds.values() if isinstance(value, (int, float)) and value >= 0]


def _eta(remaining: int, samples: list[float], root: str | None, kind: str) -> int | None:
    if remaining <= 0:
        return 0
    median = _median(samples)
    if median is None and root:
        median = _history(root, kind)
    if median is None:
        return None
    return int(round(remaining * median))


def _history(root: str, kind: str) -> float | None:
    from services.production_estimate import read_timings
    body = read_timings(root)
    rows = body.get(kind) if isinstance(body.get(kind), list) else []
    return _median([float(item) for item in rows if isinstance(item, (int, float))])


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return float(ordered[len(ordered) // 2])
