"""Skip a production save when only the log or the usage counters changed.

Clip, frame, final, status and spec writes still land immediately. A quiet poll
can lose at most five seconds of log lines and usage counts.
"""
from __future__ import annotations

import json
import time
from typing import Any

SAVE_EVERY_S = 5.0
VOLATILE = frozenset({"log", "usage"})
_clock = time.monotonic
_seen: dict[str, tuple[str, float]] = {}


def allow_save(path: Any, state: dict) -> bool:
    """True when this path should be written. The first write of a path always writes."""
    digest = _digest(state)
    if digest is None:
        return True
    key = str(path)
    moment = _clock()
    previous = _seen.get(key)
    if previous is None or previous[0] != digest or moment - previous[1] >= SAVE_EVERY_S:
        _seen[key] = (digest, moment)
        return True
    return False


def _digest(state: dict) -> str | None:
    stable = {key: value for key, value in state.items() if key not in VOLATILE}
    try:
        return json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None
