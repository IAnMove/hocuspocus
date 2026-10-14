"""Call-time lookup of names that still live in the launch module.

Recast helpers moved out of launch, but a few collaborators stay there and
are defined later in that file, or are patched on the launch module by tests.
Copying them at import would keep None or a stale object. Launch calls
:func:`bind_recast_helpers` once with its own ``globals()``. A
:class:`_LaunchName` reads that dict when the name is used.
"""

from typing import Any


_server_globals: dict[str, Any] | None = None


def bind_recast_helpers(namespace: dict[str, Any]) -> None:
    """Point every :func:`bindable` name at ``namespace``.

    One call owns the slots. Launch passes the dict its module is executing
    in, which is the same dict later assignments fill.
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
            raise RuntimeError(
                f"{name} is used before the launch module binds its globals"
            )
        return namespace[name]

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._value()(*args, **kwargs)

    def __fspath__(self) -> str:
        import os
        return os.fspath(self._value())


def bindable(name: str) -> _LaunchName:
    """A module global that reads ``name`` from the bound launch dict."""
    return _LaunchName(name)
