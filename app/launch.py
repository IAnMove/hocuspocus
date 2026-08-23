"""Lightweight application entry point.

The legacy WanGP/FastAPI runtime is deferred to :mod:`_launch_runtime`, so
tooling can import :func:`create_app` without importing Torch, probing GPUs or
changing process-global launch state.
"""

from __future__ import annotations

import importlib
import os
import runpy
import sys
from types import ModuleType
from typing import Any


_runtime: ModuleType | None = None


def _app_directory() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def create_app() -> Any:
    """Load and return the existing FastAPI application on first use."""

    global _runtime
    if _runtime is None:
        previous_cwd = os.getcwd()
        previous_argv = sys.argv[:]
        previous_path = sys.path[:]
        try:
            app_dir = _app_directory()
            if app_dir not in sys.path:
                sys.path.insert(0, app_dir)
            _runtime = importlib.import_module("_launch_runtime")
        finally:
            os.chdir(previous_cwd)
            sys.argv[:] = previous_argv
            sys.path[:] = previous_path

        # Preserve helpers historically imported from ``launch`` once the
        # runtime has intentionally been constructed.
        for name, value in vars(_runtime).items():
            if not name.startswith("__") and name not in {"create_app", "_runtime"}:
                globals()[name] = value

    return _runtime.api


def __getattr__(name: str) -> Any:
    if name == "api":
        return create_app()
    raise AttributeError(name)


def run_server() -> None:
    """Execute the unchanged runtime entry point exactly once."""

    previous_path = sys.path[:]
    try:
        app_dir = _app_directory()
        if app_dir not in sys.path:
            sys.path.insert(0, app_dir)
        runpy.run_module("_launch_runtime", run_name="__main__")
    finally:
        sys.path[:] = previous_path


if __name__ == "__main__":
    run_server()
