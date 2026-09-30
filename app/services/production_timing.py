"""Wall-clock seconds for each production stage, small enough for production.status.

Numbers only: no image paths and no prompts. A stage that did not run stays 0.
Parallel clip waits are split across the shots in that round; the 60 s backoff
stays in the clips total.
"""
from __future__ import annotations

import time
from typing import Any, Callable

STAGES = ("song", "analyze", "cast", "frames", "clips", "scenes", "montage")


def _seconds(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number < 0 or number != number:
        return 0
    return int(round(number))


def _takes(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


PERF_FIELDS = ("s_per_step", "degraded", "model")


def note_clip_performance(state: dict, key: str, status_payload: Any) -> None:
    """Copy performance fields the job status actually returned. Missing keys stay null."""
    perf = status_payload.get("performance") if isinstance(status_payload, dict) else None
    source = perf if isinstance(perf, dict) else {}
    if not isinstance(state, dict) or not isinstance(key, str) or not key:
        return
    bucket = state.get("clip_perf")
    if not isinstance(bucket, dict):
        bucket = {}
        state["clip_perf"] = bucket
    bucket[key] = {name: source[name] if name in source else None for name in PERF_FIELDS}


def _phase(state: dict, key: str) -> dict[str, Any] | None:
    perf = state.get("clip_perf") if isinstance(state, dict) else None
    record = perf.get(key) if isinstance(perf, dict) else None
    if not isinstance(record, dict):
        return None
    return {name: record[name] if name in record else None for name in PERF_FIELDS}


def _with_phase(state: dict, key: str, row: dict) -> dict:
    phase = _phase(state, key)
    if not phase:
        return row
    return {**row, **phase}


def timing_summary(state: dict) -> dict[str, Any]:
    """Seven stage seconds plus {key, seconds, takes}. Missing stages are 0."""
    raw = state.get("timing") if isinstance(state.get("timing"), dict) else {}
    timing: dict[str, Any] = {name: _seconds(raw.get(name)) for name in STAGES}
    rows = raw.get("shots") if isinstance(raw.get("shots"), list) else []
    shots = []
    for item in rows:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not item["key"]:
            continue
        shots.append(_with_phase(state, item["key"], {"key": item["key"][:80], "seconds": _seconds(item.get("seconds")), "takes": _takes(item.get("takes"))}))
        if len(shots) >= 60:
            break
    timing["shots"] = shots
    return timing


class StageWatch:
    """Times each stage of Production.run. The per-shot rows come from ``clip_seconds`` and ``clip_takes``
    (the same numbers the take loop keeps), so nothing here wraps or patches the production."""

    def __init__(self, production: Any, clock: Callable[[], float] | None = None) -> None:
        self.production = production
        self._clock = clock or time.perf_counter
        self._name: str | None = None
        self._t0 = 0.0
        timing = production.state.get("timing")
        if not isinstance(timing, dict):
            timing = {}
            production.state["timing"] = timing
        for name in STAGES:
            timing.setdefault(name, 0)
        if not isinstance(timing.get("shots"), list):
            timing["shots"] = []

    def call(self, name: str, fn: Callable[..., Any], *args: Any) -> Any:
        self.start(name)
        try:
            return fn(*args)
        finally:
            self.stop()

    def start(self, name: str) -> None:
        self._name = name
        self._t0 = self._clock()

    def stop(self) -> None:
        name = self._name
        self._name = None
        if not name:
            return
        timing = self.production.state.setdefault("timing", {})
        previous = timing.get(name)
        timing[name] = round((float(previous) if isinstance(previous, (int, float)) and previous > 0 else 0.0) + self._clock() - self._t0, 3)
        if name == "clips":
            self._publish_shots()

    def _publish_shots(self) -> None:
        state = self.production.state
        seconds = state.get("clip_seconds") if isinstance(state.get("clip_seconds"), dict) else {}
        takes = state.get("clip_takes") if isinstance(state.get("clip_takes"), dict) else {}
        state.setdefault("timing", {})["shots"] = [
            _with_phase(state, key, {"key": key, "seconds": round(float(value), 3), "takes": _takes(takes.get(key))})
            for key, value in seconds.items() if isinstance(key, str) and key and isinstance(value, (int, float))
        ][:60]
