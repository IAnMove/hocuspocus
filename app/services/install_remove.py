"""Uninstall an optional component: delete only what its catalog entry lists.

The entry lists generated folders inside ``app/services`` (``install_catalog.Component``
rejects anything else), plus the engine's ``app/.runtime/<engine>.managed`` marker.
Downloaded model files are never listed: they belong to the Storage Manager. A path that is
a link is refused rather than followed, because another checkout may share that environment.
"""
from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from services.install_catalog import REMOVABLE_ROOT, Component

IN_USE = "in_use"
SHARED_ENVIRONMENT = "shared_environment"
OUTSIDE_APP = "outside_app"


class RemovalRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RemovalPlan:
    component: Component
    paths: tuple[Path, ...]
    marker: Path


def _inside_removable_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to((root / REMOVABLE_ROOT).resolve())
    except ValueError:
        return False
    return True


def plan(component: Component, root: Path, in_use: Callable[[str], bool]) -> RemovalPlan:
    """Check that removal is safe and list what exists. Raises ``RemovalRefused`` otherwise."""
    if in_use(component.engine):
        raise RemovalRefused(IN_USE, f"{component.title} is running. Stop what uses it first.")
    paths = []
    for relative in component.remove:
        path = root / relative
        if path.is_symlink():
            raise RemovalRefused(
                SHARED_ENVIRONMENT, f"{relative} is a link to another install. Remove it from that install.")
        if not _inside_removable_root(root, path):
            raise RemovalRefused(OUTSIDE_APP, f"{relative} is outside the folders an uninstall may touch.")
        if path.exists():
            paths.append(path)
    return RemovalPlan(component, tuple(paths), root / "app" / ".runtime" / f"{component.engine}.managed")


def _make_writable_and_retry(function, path, _excinfo) -> None:
    """Conda environments contain read-only files, which Windows will not delete."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def execute(removal: RemovalPlan) -> None:
    for path in removal.paths:
        if path.is_dir():
            shutil.rmtree(path, onerror=_make_writable_and_retry)
        else:
            path.unlink(missing_ok=True)
    removal.marker.unlink(missing_ok=True)
