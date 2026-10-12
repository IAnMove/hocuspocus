"""One production at a time on this instance's GPU, in the order they were sent.

Two productions at once interleave their jobs in the one GPU queue, so nearly every job loads a different
model: the H3 steps of a piece that shared the GPU went from 14 s to 330-500 s and the piece took 7 h.
A production sent while another runs waits with status ``queued`` (a cancel still stops it), then runs.
So an agent can send every piece of a batch at once and the GPU works through them without gaps.
"""
from __future__ import annotations

import threading
from typing import Any, Callable

from services.production_control import arm, disarm, production_key

_turn = threading.Condition()
_queue: list[str] = []


def queued() -> list[str]:
    with _turn:
        return list(_queue)


def run_in_turn(production: Any, work: Callable[[], None], *, poll: float = 1.0) -> None:
    key = production_key(production.ws, production.id)
    cancel = arm(production.ws, production.id)
    with _turn:
        _queue.append(key)
        noted = False
        while _queue[0] != key:
            if cancel.is_set():
                _queue.remove(key)
                _turn.notify_all()
                disarm(production.ws, production.id)
                production.state.update(status="cancelled", error=None)
                production.log("cancelled while queued")
                return
            if not noted:
                production.state.update(status="queued")
                production.log(f"queued behind {_queue[0].split('/', 1)[-1]}")
                noted = True
            _turn.wait(timeout=poll)
    try:
        work()
    finally:
        with _turn:
            _queue.remove(key)
            _turn.notify_all()
