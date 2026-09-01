"""Explicit bootstrap for the documented standalone WanGP Python API.

Normal HocusPocus consumers must use :func:`get_wgp` and never load WanGP.
This module is the one alternate entrypoint for processes that start through
``shared.api.init()`` instead of ``_launch_runtime.py``.
"""
from __future__ import annotations

import importlib
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from .runtime import bind_wgp, get_wgp


_BOOTSTRAP_LOCK = threading.RLock()


def _import_wgp() -> Any:
    """Keep the exceptional dynamic import named and visible to the gate."""
    return importlib.import_module("wgp")


def _module_root(module: Any) -> Path:
    module_file = getattr(module, "__file__", None)
    if not module_file:
        raise RuntimeError("The loaded WanGP module has no __file__; its root cannot be verified")
    return Path(module_file).resolve().parent


def _require_root(module: Any, expected_root: Path) -> None:
    actual_root = _module_root(module)
    if actual_root != expected_root:
        raise RuntimeError(f"WanGP module already loaded from {actual_root}, expected {expected_root}")


def get_or_bootstrap_wgp(
    *,
    expected_root: str | Path,
    importer: Callable[[str], Any] | None = None,
) -> Any:
    """Return the singleton, importing it once for a standalone API process.

    The caller owns cwd and argv setup.  ``importer`` exists for tests; the
    production path uses the single, architecture-gated import above.
    """
    expected = Path(expected_root).resolve()
    with _BOOTSTRAP_LOCK:
        try:
            bound = get_wgp()
        except RuntimeError:
            bound = None

        registered = sys.modules.get("wgp")
        if bound is not None:
            if registered is not bound:
                raise RuntimeError(
                    "The bound WanGP instance does not match sys.modules['wgp']; "
                    "refusing to create a second runtime"
                )
            _require_root(bound, expected)
            return bound

        module = registered
        if module is None:
            module = importer("wgp") if importer is not None else _import_wgp()
            if sys.modules.get("wgp") is not module:
                raise RuntimeError(
                    "The WanGP importer did not register the returned module in sys.modules"
                )

        _require_root(module, expected)
        bind_wgp(module)
        return module
