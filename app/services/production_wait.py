"""Block on a production JSON file until its status value changes.

``production.status`` calls :func:`wait_for_status`. The loop sleeps about one
second between reads (injectable) and never busy-polls. ``wait_s`` 0 reads once.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

MAX_WAIT_S = 300
POLL_S = 1.0


def normalize_wait_s(value: Any) -> int:
    """Integer seconds in ``0..300``. ``None`` is the default, zero."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_WAIT_S:
        raise _invalid("wait_s must be an integer from 0 to 300.")
    return value


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


async def wait_for_status(
    path: Path,
    wait_s: Any = 0,
    *,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Any] | None = None,
    poll_s: float = POLL_S,
) -> dict:
    """Return the production object. Wait until ``status`` changes, or ``wait_s`` elapses."""
    now = clock or time.monotonic
    pause = sleep or asyncio.sleep
    limit = normalize_wait_s(wait_s)
    started = now()
    state = _read_state(path)
    baseline = state.get("status")
    if limit <= 0:
        return state
    while now() - started < limit:
        remaining = limit - (now() - started)
        await pause(min(poll_s, remaining))
        try:
            state = _read_state(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if state.get("status") != baseline:
            return state
    return state


def _read_state(path: Path) -> dict:
    state = json.loads(Path(path).read_text())
    if isinstance(state, dict):
        return state
    raise ValueError("production state must be an object")


def _invalid(message: str) -> HTTPException:
    return HTTPException(422, {"code": "invalid_command", "message": message, "retryable": False})
