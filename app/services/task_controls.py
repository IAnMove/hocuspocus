"""What the Activity buttons (cancel, resume, discard) do for each kind of task.

The full server keeps its own switch (``canonical_task_sync._control_canonical_task``) because
it owns every worker. The core server does not: it mounts a subset of the routers, and each
mounted router knows how to stop its own jobs. So the router that owns an adapter registers
its handlers here when its factory runs, and ``core_canonical_tasks.control_task`` looks them
up. Only adapters core really mounts end up with an entry; a task of any other adapter keeps
the old behaviour.

A handler takes the whole task row (``task["backend_job_id"]``, ``task["workspace"]``,
``task["root_id"]``... whatever the adapter needs) and returns what the route sends back as
``result``. It may raise ``HTTPException``. Standard library only: routers import this module,
never the other way round.
"""
from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator
from typing import Any

Handler = Callable[[dict], Any]

# The Activity route calls "retry" for both its retry and its resume buttons.
_ALIASES = {"retry": "resume"}

_lock = threading.RLock()
_handlers: dict[tuple[str, str], Handler] = {}


def _action(action: str) -> str:
    return _ALIASES.get(str(action or "").strip().lower(), str(action or "").strip().lower())


def register(adapter: str, action: str, handler: Handler) -> None:
    """Set the handler for ``action`` on tasks of ``adapter``. The last registration wins (a router factory may be built again)."""
    name, verb = str(adapter or "").strip(), _action(action)
    if not name or not verb or not callable(handler):
        raise ValueError("A task control needs an adapter, an action and a callable")
    with _lock:
        _handlers[(name, verb)] = handler


@contextlib.contextmanager
def restored() -> Iterator[None]:
    """Keep the table as it is and put it back afterwards, dropping what the block registered. Tests only."""
    with _lock:
        saved = dict(_handlers)
    try:
        yield
    finally:
        with _lock:
            _handlers.clear()
            _handlers.update(saved)


def handler_for(adapter: str, action: str) -> Handler | None:
    with _lock:
        return _handlers.get((str(adapter or "").strip(), _action(action)))


def registered() -> tuple[tuple[str, str], ...]:
    """Every (adapter, action) with a handler, sorted."""
    with _lock:
        return tuple(sorted(_handlers))


def job_id(task: dict) -> str:
    """The id of the backend job a task row stands for."""
    return str(task.get("backend_job_id") or "")
