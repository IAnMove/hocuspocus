"""Minutes for a game batch, from this workspace, the J0 trial, or the defaults.

``REGISTRY[kind].estimate()`` already counts candidates. This module does not
multiply by the candidate count again. History keeps the last 30 samples per
step, the same tail as ``production_estimate.py``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.game_generators import REGISTRY

NAME = ".game-timings.json"
_KEEP = 30
# Seconds. ``image`` is the median of the single Qwen submissions in J0
# (17.0, 17.1, 22.4, 63.9, 76.7), not the multi-pass tile totals.
# H3 turbo: 78.1, 83.4, 142.6, 148.7. H3 quality: 305.7, 306.1.
# SFX: 15.1, 15.2, 16.7. Hunyuan: 80.6, 96.4. Music 49.0. Rig 5.1.
# The median is ordered[len//2], matching production_estimate._median.
TRIAL = {
    "image": 22.4,
    "h3_turbo": 142.6,
    "h3": 306.1,
    "music": 49.0,
    "sfx": 15.2,
    "3d": 96.4,
    "rig": 5.1,
}
DEFAULTS = {
    "image": 85.0,
    "h3_turbo": 110.0,
    "h3": 300.0,
    "music": 40.0,
    "sfx": 15.0,
    "3d": 120.0,
    "rig": 60.0,
}


def read_timings(root: Any) -> dict[str, Any]:
    if not root:
        return {}
    path = Path(root) / NAME
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def record(root: Any, step_type: str, seconds: float) -> None:
    """Keep the last 30 samples for one step type."""
    if not root or isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return
    body = read_timings(root)
    rows = body.get(step_type) if isinstance(body.get(step_type), list) else []
    rows.append(round(float(seconds), 3))
    body[step_type] = [float(item) for item in rows if isinstance(item, (int, float)) and not isinstance(item, bool)][-_KEEP:]
    body["version"] = 1
    _write(Path(root), body)


def seconds_for(root: Any, step_type: str, *, trial: dict[str, float] | None = TRIAL) -> tuple[float, str]:
    """``(seconds, source)`` for one step. ``trial=None`` skips the J0 table."""
    samples = _samples(read_timings(root).get(step_type))
    if samples:
        return _median(samples), f"history({len(samples)})"
    if trial and step_type in trial:
        return float(trial[step_type]), "trial"
    return float(DEFAULTS.get(step_type, DEFAULTS["image"])), "defaults"


def estimate(root: Any, game: dict[str, Any], assets: list[dict[str, Any]], *, trial: dict[str, float] | None = TRIAL) -> dict[str, Any]:
    """``{minutes, source, byKind}``. ``byKind`` is minutes per kind."""
    by_kind: dict[str, float] = {}
    sources: list[str] = []
    for asset in assets:
        kind = str(asset.get("kind") or "image")
        kind_seconds = 0.0
        for step, times in steps_for(game, asset).items():
            seconds, source = seconds_for(root, step, trial=trial)
            kind_seconds += seconds * times
            sources.append(source)
        by_kind[kind] = by_kind.get(kind, 0.0) + kind_seconds
    total = sum(by_kind.values())
    return {
        "minutes": round(total / 60.0, 1),
        "source": _overall(sources, trial),
        "byKind": {kind: round(value / 60.0, 3) for kind, value in by_kind.items()},
    }


def steps_for(game: dict[str, Any], asset: dict[str, Any]) -> dict[str, int]:
    """Step counts. Registered generators already include their candidate count."""
    generator = REGISTRY.get(str(asset.get("kind") or ""))
    if generator is not None:
        counts = generator.estimate(game, asset)
        parsed = _counts(counts)
        if parsed:
            return parsed
    return _fallback(asset)


def _counts(counts: Any) -> dict[str, int]:
    if not isinstance(counts, dict):
        return {}
    parsed = {}
    for key, value in counts.items():
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            parsed[str(key)] = value
    return parsed


def _fallback(asset: dict[str, Any]) -> dict[str, int]:
    """Kinds that register in J6–J8. One failed generator must not stop the estimate."""
    kind = str(asset.get("kind") or "")
    count = _positive(asset.get("candidates"), 1)
    spec = asset.get("spec") if isinstance(asset.get("spec"), dict) else {}
    if kind == "animation":
        return {"image" if spec.get("method") == "strip" else "h3": count}
    if kind == "vfx":
        return {"h3_turbo": count}
    if kind == "sfx":
        return {"sfx": _positive(spec.get("variants"), 1)}
    if kind in {"music", "jingle"}:
        return {"music": count}
    if kind == "voice":
        lines = spec.get("lines") if isinstance(spec.get("lines"), list) else []
        return {"sfx": max(1, len(lines)) * count}
    if kind == "model3d":
        return {"image": count, "3d": count}
    if kind == "character3d":
        return {"3d": count, "rig": count}
    return {"image": count}


def _positive(value: Any, fallback: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return fallback
    return value


def _samples(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    return [float(item) for item in value if isinstance(item, (int, float)) and not isinstance(item, bool)]


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return float(ordered[len(ordered) // 2])


def _overall(sources: list[str], trial: dict[str, float] | None) -> str:
    numbers = []
    for item in sources:
        if item.startswith("history(") and item.endswith(")"):
            numbers.append(int(item[len("history("):-1]))
    if numbers:
        return f"history({min(numbers)})"
    if sources and all(item == "defaults" for item in sources):
        return "defaults"
    if trial is None:
        return "defaults"
    return "trial"


def _write(root: Path, body: dict[str, Any]) -> None:
    path = root / NAME
    temporary = path.with_suffix(".json.tmp")
    try:
        root.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        return
