"""Block on a production JSON file until status, stage, or a terminal state.

``production.status`` calls :func:`wait_for_status`. The loop sleeps about one
second between reads (injectable) and never busy-polls. ``wait_s`` 0 reads once.
``until`` defaults to ``change`` so existing callers keep today's behaviour.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

MAX_WAIT_S = 1200
POLL_S = 1.0
_UNTIL = frozenset({"change", "stage", "done"})
_DONE = frozenset({"completed", "failed", "cancelled"})


def normalize_wait_s(value: Any) -> int:
    """Integer seconds in ``0..1200``. ``None`` is the default, zero."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_WAIT_S:
        raise _invalid(f"wait_s must be an integer from 0 to {MAX_WAIT_S}.")
    return value


def _normalize_until(value: Any) -> str:
    if value is None:
        return "change"
    if value in _UNTIL:
        return str(value)
    raise _invalid("until must be change, stage or done.")


def calls_to_cover(duration_s: int, wait_s: int, changes: tuple[int, ...]) -> int:
    """How many status calls follow ``duration_s`` if each waits at most ``wait_s``.

    ``changes`` are timestamps where the status value flips. A call returns at
    the next flip inside its window, otherwise when the window ends. No sleeping.
    """
    if wait_s <= 0:
        raise ValueError("wait_s must be positive")
    now = 0
    calls = 0
    ordered = tuple(sorted(changes))
    while now < duration_s:
        calls += 1
        horizon = min(duration_s, now + wait_s)
        for moment in ordered:
            if now < moment <= horizon:
                horizon = moment
                break
        now = horizon
    return calls


def _ready(state: dict, status: Any, stage: Any, mode: str) -> bool:
    if mode == "done":
        return state.get("status") in _DONE
    if state.get("status") != status:
        return True
    return mode == "stage" and state.get("stage") != stage


async def wait_for_status(
    path: Path,
    wait_s: Any = 0,
    *,
    until: Any = "change",
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Any] | None = None,
    poll_s: float = POLL_S,
) -> dict:
    """Return the production object.

    ``until`` ``change`` (default) returns when ``status`` changes. ``stage``
    also returns when ``stage`` changes. ``done`` waits until status is
    ``completed``, ``failed`` or ``cancelled``. A wait that ends before that
    condition includes ``waited_s``. The loop sleeps; it does not busy-poll.
    """
    now = clock or time.monotonic
    pause = sleep or asyncio.sleep
    limit = normalize_wait_s(wait_s)
    mode = _normalize_until(until)
    started = now()
    state = _read_state(path)
    baseline = state.get("status")
    stage = state.get("stage")
    if limit <= 0 or _ready(state, baseline, stage, mode):
        return state
    while now() - started < limit:
        remaining = limit - (now() - started)
        await pause(min(poll_s, remaining))
        try:
            state = _read_state(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if _ready(state, baseline, stage, mode):
            return state
    viewed = dict(state)
    viewed["waited_s"] = max(0, int(round(now() - started)))
    return viewed


def _read_state(path: Path) -> dict:
    state = json.loads(Path(path).read_text())
    if isinstance(state, dict):
        return state
    raise ValueError("production state must be an object")


def _invalid(message: str) -> HTTPException:
    return HTTPException(422, {"code": "invalid_command", "message": message, "retryable": False})
