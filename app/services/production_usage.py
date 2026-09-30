"""Per-production MCP cost: calls, response bytes, and H3 takes.

The transport journal stores idempotency, not a production id. The runner counts
each loopback reply it actually receives. ``h3_takes`` is the sum of ``clip_takes``.
``response_bytes`` stay bytes. They are not tokens.

``gpu_seconds`` is song + frames + clips. ``cpu_seconds`` is scenes + montage.
Package has no stage. ``retry_seconds`` and ``reused_seconds`` come from ``runs``
and from take or fingerprint fields on the state.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

_GPU = ("song", "frames", "clips")
_CPU = ("scenes", "montage")
_TIMING_KEYS = ("song", "analyze", "cast", "frames", "clips", "scenes", "montage")


def note_call(state: dict, result: Any) -> None:
    usage = state.setdefault("usage", {})
    usage["mcp_calls"] = _count(usage.get("mcp_calls")) + 1
    usage["response_bytes"] = _count(usage.get("response_bytes")) + _bytes(result)


def usage_summary(state: dict) -> dict[str, int]:
    raw = state.get("usage") if isinstance(state.get("usage"), dict) else {}
    gpu, cpu = _gpu_cpu(state)
    timing = state.get("timing") if isinstance(state.get("timing"), dict) else None
    return {
        "mcp_calls": _count(raw.get("mcp_calls")),
        "response_bytes": _count(raw.get("response_bytes")),
        "h3_takes": _takes(state.get("clip_takes")),
        "gpu_seconds": gpu,
        "cpu_seconds": cpu,
        "retry_seconds": _retry_seconds(state, timing),
        "reused_seconds": _reused_seconds(state),
    }


def note_run(state: dict, retake: Any = (), root: Any = None) -> None:
    """Append one ``{started, finished, retake, timing}`` row. Tests call this directly.

    A completed run with ``root`` also records timing medians. The row is enough
    for ``usage_summary`` when ``Production.run`` cannot grow another branch.
    """
    if not isinstance(state, dict):
        return
    runs = state.get("runs")
    if not isinstance(runs, list):
        runs = []
        state["runs"] = runs
    timing = state.get("timing") if isinstance(state.get("timing"), dict) else {}
    kept = {name: timing[name] for name in _TIMING_KEYS if name in timing}
    runs.append({
        "started": state.get("started"),
        "finished": state.get("finished"),
        "retake": _retake_names({"retake": retake}),
        "timing": kept,
    })
    if root and state.get("status") == "completed":
        from services.production_estimate import record_completed
        record_completed(root, state)


SAVE_EVERY_S = 5.0


def attach_usage(mcp: Callable[[str, dict], dict], state: dict, save: Callable[[], None],
                 clock: Callable[[], float] = time.monotonic) -> Callable[[str, dict], dict]:
    """Count each reply. The counters ride along with the next save the run makes anyway; the polling loops
    (a status call every few seconds per job) write the state file at most every SAVE_EVERY_S seconds."""
    last = [float("-inf")]

    def call(tool: str, arguments: dict) -> dict:
        result = mcp(tool, arguments)
        note_call(state, result)
        moment = clock()
        if moment - last[0] >= SAVE_EVERY_S:
            last[0] = moment
            save()
        return result
    return call


def _gpu_cpu(state: dict) -> tuple[int, int]:
    timing = state.get("timing") if isinstance(state.get("timing"), dict) else None
    if timing is not None:
        return _stage_sum(timing, _GPU), _stage_sum(timing, _CPU)
    gpu = cpu = 0
    for run in _runs(state):
        item = run.get("timing") if isinstance(run, dict) else None
        gpu += _stage_sum(item, _GPU)
        cpu += _stage_sum(item, _CPU)
    return gpu, cpu


def _retry_seconds(state: dict, timing: dict | None) -> int:
    runs = _runs(state)
    if any(_retake_names(run) for run in runs):
        return _retake_seconds(runs)
    return _shot_retry(state, timing)


def _retake_seconds(runs: list) -> int:
    total = 0
    for run in runs:
        if not _retake_names(run):
            continue
        item = run.get("timing") if isinstance(run, dict) else None
        total += _stage_sum(item, ("frames", "clips"))
    return total


def _shot_retry(state: dict, timing: dict | None) -> int:
    total = 0.0
    for row in _shot_rows(state, timing):
        takes = _count(row.get("takes"))
        seconds = _seconds(row.get("seconds"))
        if takes > 1 and seconds > 0:
            total += seconds * (takes - 1) / takes
    return int(round(total))


def _shot_rows(state: dict, timing: dict | None) -> list[dict]:
    if isinstance(timing, dict) and isinstance(timing.get("shots"), list):
        return [row for row in timing["shots"] if isinstance(row, dict)]
    raw = state.get("clip_seconds")
    if not isinstance(raw, dict):
        return []
    takes = state.get("clip_takes") if isinstance(state.get("clip_takes"), dict) else {}
    return [{"seconds": seconds, "takes": takes.get(key)} for key, seconds in raw.items()]


def _reused_seconds(state: dict) -> int:
    total = sum(_seconds(run.get("reused_seconds")) for run in _runs(state) if isinstance(run, dict))
    scenes = state.get("scenes")
    if isinstance(scenes, dict):
        for scene in scenes.values():
            if isinstance(scene, dict) and _reused_scene(scene):
                total += _seconds(scene.get("seconds"))
    return int(round(total))


def _reused_scene(scene: dict) -> bool:
    if scene.get("fingerprint_unchanged") is True:
        return True
    current = scene.get("fingerprint")
    prior = scene.get("prior_fingerprint")
    return isinstance(current, str) and isinstance(prior, str) and bool(current) and bool(prior) and current == prior


def _retake_names(run: Any) -> list[str]:
    if not isinstance(run, dict):
        return []
    retake = run.get("retake")
    if not isinstance(retake, (list, tuple)) or isinstance(retake, str):
        return []
    return [item for item in retake if isinstance(item, str) and item]


def _runs(state: dict) -> list:
    runs = state.get("runs")
    return runs if isinstance(runs, list) else []


def _stage_sum(timing: Any, names: tuple[str, ...]) -> int:
    if not isinstance(timing, dict):
        return 0
    total = 0.0
    for name in names:
        total += _seconds(timing.get(name))
    return int(round(total))


def _seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    if value <= 0 or value != value:
        return 0.0
    return float(value)


def _bytes(result: Any) -> int:
    try:
        return len(json.dumps(result, ensure_ascii=False).encode())
    except (TypeError, ValueError):
        return 0


def _count(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _takes(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    return sum(_count(item) for item in value.values())
