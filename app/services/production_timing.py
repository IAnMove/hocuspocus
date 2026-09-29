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


def timing_summary(state: dict) -> dict[str, Any]:
    """Seven stage seconds plus {key, seconds, takes}. Missing stages are 0."""
    raw = state.get("timing") if isinstance(state.get("timing"), dict) else {}
    timing: dict[str, Any] = {name: _seconds(raw.get(name)) for name in STAGES}
    rows = raw.get("shots") if isinstance(raw.get("shots"), list) else []
    shots = []
    for item in rows:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not item["key"]:
            continue
        shots.append({"key": item["key"][:80], "seconds": _seconds(item.get("seconds")), "takes": _takes(item.get("takes"))})
        if len(shots) >= 60:
            break
    timing["shots"] = shots
    return timing


class StageWatch:
    """Start and stop around Production.run. Clips also time each shot."""

    def __init__(self, production: Any, clock: Callable[[], float] | None = None) -> None:
        self.production = production
        self._clock = clock or time.perf_counter
        self._name: str | None = None
        self._t0 = 0.0
        self._wrapped: list[tuple[str, Any]] = []
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
        if name == "clips":
            self._arm_shots()

    def stop(self) -> None:
        name = self._name
        self._name = None
        if not name:
            return
        elapsed = self._clock() - self._t0
        timing = self.production.state.setdefault("timing", {})
        timing[name] = _seconds(_seconds(timing.get(name)) + elapsed)
        if name != "clips":
            return
        try:
            self._publish_takes()
        finally:
            self._disarm()

    def _arm_shots(self) -> None:
        if self._wrapped:
            return
        production = self.production
        original_job = production.clip_job
        original_wait = production.wait

        def wrapped_job(spec, window, seed, take=0):
            t0 = self._clock()
            try:
                return original_job(spec, window, seed, take)
            finally:
                self._add_shot(window.get("key") if isinstance(window, dict) else None, self._clock() - t0)

        def wrapped_wait(jobs, poll=6):
            t0 = self._clock()
            try:
                return original_wait(jobs, poll)
            finally:
                self._share(jobs, self._clock() - t0)

        production.clip_job = wrapped_job
        self._wrapped.append(("clip_job", original_job))
        production.wait = wrapped_wait
        self._wrapped.append(("wait", original_wait))

    def _disarm(self) -> None:
        for name, original in self._wrapped:
            setattr(self.production, name, original)
        self._wrapped = []

    def _add_shot(self, key: Any, seconds: float) -> None:
        if not isinstance(key, str) or not key:
            return
        row = self._row(key)
        row["seconds"] = _seconds(_seconds(row.get("seconds")) + seconds)

    def _share(self, jobs: Any, seconds: float) -> None:
        if not isinstance(jobs, dict) or not jobs:
            return
        part = seconds / len(jobs)
        for key in jobs:
            self._add_shot(key, part)

    def _row(self, key: str) -> dict[str, Any]:
        shots = self.production.state.setdefault("timing", {}).setdefault("shots", [])
        for item in shots:
            if isinstance(item, dict) and item.get("key") == key:
                return item
        item = {"key": key, "seconds": 0, "takes": 0}
        shots.append(item)
        return item

    def _publish_takes(self) -> None:
        takes = self.production.state.get("clip_takes") or {}
        if not isinstance(takes, dict):
            return
        shots = (self.production.state.get("timing") or {}).get("shots") or []
        for item in shots:
            if isinstance(item, dict) and isinstance(item.get("key"), str) and item["key"] in takes:
                item["takes"] = _takes(takes[item["key"]])
