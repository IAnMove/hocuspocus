"""Per-production MCP cost: calls, response bytes, and H3 takes.

The transport journal stores idempotency, not a production id. The runner counts
each loopback reply it actually receives. ``h3_takes`` is the sum of ``clip_takes``.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable


def note_call(state: dict, result: Any) -> None:
    usage = state.setdefault("usage", {})
    usage["mcp_calls"] = _count(usage.get("mcp_calls")) + 1
    usage["response_bytes"] = _count(usage.get("response_bytes")) + _bytes(result)


def usage_summary(state: dict) -> dict[str, int]:
    raw = state.get("usage") if isinstance(state.get("usage"), dict) else {}
    timing = state.get("timing") if isinstance(state.get("timing"), dict) else {}
    return {
        "mcp_calls": _count(raw.get("mcp_calls")),
        "response_bytes": _count(raw.get("response_bytes")),
        "h3_takes": _takes(state.get("clip_takes")),
        "gpu_seconds": _seconds(timing.get("song")) + _seconds(timing.get("frames")) + _seconds(timing.get("clips")),
        "cpu_seconds": _seconds(timing.get("scenes")) + _seconds(timing.get("montage")) + _seconds(timing.get("package")),
        "retry_seconds": _retry_seconds(state),
        "reused_seconds": _reused_seconds(state),
    }


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


def _seconds(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number < 0 or number != number:
        return 0
    return int(round(number))


def _retry_seconds(state: dict) -> int:
    """Share of clip_seconds that belongs to takes after the first. No second clock."""
    seconds = state.get("clip_seconds") if isinstance(state.get("clip_seconds"), dict) else {}
    takes = state.get("clip_takes") if isinstance(state.get("clip_takes"), dict) else {}
    total = 0.0
    for key, value in seconds.items():
        count = _count(takes.get(key))
        if count > 1 and isinstance(value, (int, float)):
            total += float(value) * (count - 1) / count
    return int(round(total))


def _reused_seconds(state: dict) -> int:
    """Clip seconds kept from before this run, except keys named in the latest retake."""
    kept = {item for item in state.get("kept_clips") or [] if isinstance(item, str)}
    runs = state.get("runs") if isinstance(state.get("runs"), list) else []
    latest = runs[-1] if runs and isinstance(runs[-1], dict) else {}
    retake = {item for item in latest.get("retake") or [] if isinstance(item, str)}
    seconds = state.get("clip_seconds") if isinstance(state.get("clip_seconds"), dict) else {}
    total = sum(float(seconds[key]) for key in kept - retake if isinstance(seconds.get(key), (int, float)))
    return int(round(total))


def _takes(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    return sum(_count(item) for item in value.values())
