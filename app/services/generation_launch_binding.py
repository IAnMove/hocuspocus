"""Call-time lookup of names that still live in the launch module.

The generation worker and its tests rebind names on the launch module
(``wgp``, ``update_job``, ``os``, ``time``). A service that copied those
objects at import would keep ``None`` or a stale object: launch imports the
service while later defs are still ahead of it, and ``run_server`` executes
the launch module in a fresh globals dict that is not stored in
``sys.modules``.

Launch calls :func:`bind_server_globals` with its own ``globals()``. A
:class:`_LaunchName` reads that dict when the name is used, so a patch made
after import is visible and a name defined later in launch is not captured
early.
"""
from __future__ import annotations

from typing import Any


_server_globals: dict[str, Any] | None = None


def bind_server_globals(namespace: dict[str, Any]) -> None:
    """Point every :func:`bindable` name at ``namespace``.

    Launch passes the dict its own module is executing in. Calling this again
    with the same dict changes nothing. A later call with a different dict
    replaces it, which is what a second execution of the launch module needs.
    """
    global _server_globals
    _server_globals = namespace


class _LaunchName:
    """One launch-module global, resolved on each use."""

    def __init__(self, name: str) -> None:
        object.__setattr__(self, "_name", name)

    def _value(self) -> Any:
        namespace = _server_globals
        name = object.__getattribute__(self, "_name")
        if namespace is None or name not in namespace:
            raise RuntimeError(f"{name} is used before the launch module binds its globals")
        return namespace[name]

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._value()(*args, **kwargs)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._value(), item)

    def __setattr__(self, item: str, value: Any) -> None:
        setattr(self._value(), item, value)

    def __repr__(self) -> str:
        name = object.__getattribute__(self, "_name")
        return f"<launch global {name}>"


def bindable(name: str) -> _LaunchName:
    """A module global that reads ``name`` from the bound launch dict."""
    return _LaunchName(name)
