"""Minute estimate from this workspace's finished runs, otherwise the documented defaults.

Enhance minutes are a provisional default (``EXTRA_MINUTES_PER_CLIP``), not a measurement.
The history file is ``<workspace>/.production-timings.json``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NAME = ".production-timings.json"
SEED_MINUTES = 2
H3_MINUTES = 5
TAIL_MINUTES = 1
EXTRA_MINUTES_PER_CLIP = 1
_KEEP = 30


def read_timings(root: Any) -> dict:
    if not root:
        return {}
    path = Path(root) / NAME
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def record_observation(root: Any, state: dict) -> None:
    """Append one median per finished run. Missing numbers are left out."""
    if not root:
        return
    timing = state.get("timing") if isinstance(state.get("timing"), dict) else {}
    body = read_timings(root)
    _append(body, "clip_s", _median_or_none(_clip_seconds(timing)))
    _append(body, "scene_s", _scene_each(state, timing))
    song = timing.get("song") if isinstance(timing.get("song"), (int, float)) else None
    if song is not None:
        _append(body, "seed_min", round(float(song) / 60.0, 3))
    _write(Path(root), body)


def estimate_minutes(spec: dict, h3_count: int, root: Any = None) -> tuple[float, str]:
    """``(minutes, estimate_source)``. ``history(n)`` or ``defaults``."""
    seeds = _seeds(spec)
    history = read_timings(root)
    clips = _numbers(history.get("clip_s"))
    seed_rates = _numbers(history.get("seed_min"))
    if clips:
        per_h3 = _median(clips) / 60.0
        per_seed = _median(seed_rates) if seed_rates else SEED_MINUTES
        source = f"history({len(clips)})"
    else:
        per_h3, per_seed, source = H3_MINUTES, SEED_MINUTES, "defaults"
    minutes = per_seed * seeds + per_h3 * h3_count + TAIL_MINUTES
    enhance = spec.get("enhance") if isinstance(spec.get("enhance"), dict) else None
    if enhance and enhance.get("method") in ("flashvsr", "rife"):
        minutes += EXTRA_MINUTES_PER_CLIP * h3_count
        if source != "defaults":
            source = source + "+default_enhance"
    return float(round(minutes, 1)), source


def _seeds(spec: dict) -> int:
    song = spec.get("song") if isinstance(spec.get("song"), dict) else {}
    if song.get("file"):
        return 0
    raw = song.get("seeds")
    if isinstance(raw, list) and raw:
        return len(raw)
    return 3


def _numbers(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    return [float(item) for item in value if isinstance(item, (int, float))]


def _clip_seconds(timing: dict) -> list[float]:
    shots = timing.get("shots") if isinstance(timing.get("shots"), list) else []
    return [float(item["seconds"]) for item in shots if _has_seconds(item)]


def _has_seconds(item: Any) -> bool:
    return isinstance(item, dict) and isinstance(item.get("seconds"), (int, float))


def _scene_each(state: dict, timing: dict) -> float | None:
    scenes = state.get("scenes") if isinstance(state.get("scenes"), dict) else {}
    done = sum(1 for item in scenes.values() if isinstance(item, dict) and item.get("file"))
    if not done or not isinstance(timing.get("scenes"), (int, float)):
        return None
    return float(timing["scenes"]) / done


def _median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return _median(values)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return float(ordered[len(ordered) // 2])


def _append(body: dict, key: str, value: float | None) -> None:
    if value is None:
        return
    rows = body.get(key) if isinstance(body.get(key), list) else []
    rows.append(round(float(value), 3))
    body[key] = rows[-_KEEP:]
    body["version"] = 1


def _write(root: Path, body: dict) -> None:
    path = root / NAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
