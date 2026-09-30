"""Block on a production JSON file until its status value changes.

``production.status`` calls :func:`wait_for_status`. The loop sleeps about one
second between reads (injectable) and never busy-polls. ``wait_s`` 0 reads once.
The server accepts up to 1200 s. ``until`` is ``change`` (the status value),
``stage`` (the status value or ``state["stage"]``), or ``done`` (completed,
failed, or cancelled). A client may still poll at 300 s.
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
_UNTIL = ("change", "stage", "done")
_DONE = ("completed", "failed", "cancelled")


def normalize_wait_s(value: Any) -> int:
    """Integer seconds in ``0..1200``. ``None`` is the default, zero."""
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_WAIT_S:
        raise _invalid(f"wait_s must be an integer from 0 to {MAX_WAIT_S}.")
    return value


def normalize_until(value: Any) -> str:
    """``change`` (default), ``stage``, or ``done``. Anything else is invalid_command."""
    if value is None or value == "":
        return "change"
    if value in _UNTIL:
        return value
    raise _invalid("until must be change, stage, or done.")


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
    until: Any = "change",
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], Any] | None = None,
    poll_s: float = POLL_S,
) -> dict:
    """Return a copy of the production object, with ``waited_s`` for the caller to lift off."""
    now = clock or time.monotonic
    pause = sleep or asyncio.sleep
    limit = normalize_wait_s(wait_s)
    mode = normalize_until(until)
    started = now()
    state = _read_state(path)
    baseline, baseline_stage = state.get("status"), state.get("stage")
    if limit <= 0 or _ready(state, baseline, baseline_stage, mode, initial=True):
        return _stamp(state, started, now())
    while now() - started < limit:
        remaining = limit - (now() - started)
        await pause(min(poll_s, remaining))
        try:
            state = _read_state(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if _ready(state, baseline, baseline_stage, mode, initial=False):
            return _stamp(state, started, now())
    return _stamp(state, started, now())


def _ready(state: dict, baseline: Any, baseline_stage: Any, mode: str, *, initial: bool) -> bool:
    status = state.get("status")
    if mode == "done":
        return status in _DONE
    if initial:
        return False
    if status != baseline:
        return True
    return mode == "stage" and state.get("stage") != baseline_stage


def _stamp(state: dict, started: float, moment: float) -> dict:
    stamped = dict(state)
    stamped["waited_s"] = int(round(max(0.0, moment - started)))
    return stamped


def _read_state(path: Path) -> dict:
    state = json.loads(Path(path).read_text())
    if isinstance(state, dict):
        return state
    raise ValueError("production state must be an object")


def _invalid(message: str) -> HTTPException:
    return HTTPException(422, {"code": "invalid_command", "message": message, "retryable": False})
