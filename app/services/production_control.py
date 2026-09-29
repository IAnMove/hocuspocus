"""Cooperative stop for one music-video production.

``production.run`` arms a ``threading.Event``. ``Production.wait`` and the
pauses between rounds notice it within a fifth of a second and leave the
status ``cancelled``. The files stay, so a later ``production.run`` continues.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

_events: dict[str, threading.Event] = {}
_guard = threading.Lock()


class Cancelled(Exception):
    """The caller asked this production to stop. The run can be resumed."""


def production_key(workspace: str, production_id: str) -> str:
    return f"{workspace}/{production_id}"


def arm(workspace: str, production_id: str) -> threading.Event:
    """The event for this run. A cancel that arrived as the thread started is kept."""
    key = production_key(workspace, production_id)
    with _guard:
        event = _events.get(key)
        if event is None:
            event = threading.Event()
            _events[key] = event
        return event


def disarm(workspace: str, production_id: str) -> None:
    with _guard:
        _events.pop(production_key(workspace, production_id), None)


def request_cancel(workspace: str, production_id: str, threads: dict[str, threading.Thread], lock: threading.Lock) -> bool:
    """Set the flag when that production's thread is alive."""
    key = production_key(workspace, production_id)
    with lock:
        thread = threads.get(key)
        if not (thread and thread.is_alive()):
            return False
        with _guard:
            event = _events.get(key)
            if event is None:
                event = threading.Event()
                _events[key] = event
            event.set()
    return True


def checkpoint(event: threading.Event | None) -> None:
    if event is not None and event.is_set():
        raise Cancelled()


def sleep_until(event: threading.Event | None, seconds: float, sleep: Callable[[float], None], step: float = 0.2) -> None:
    """Sleep up to ``seconds``. One sleep when nothing can cancel, so callers that patch ``sleep`` stay stable."""
    if event is None:
        sleep(seconds)
        return
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        checkpoint(event)
        left = deadline - time.monotonic()
        if left <= 0:
            return
        sleep(min(step, left))
