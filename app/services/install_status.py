"""What the Installation tab shows: every optional component, its state and its size.

Pure assembly. Hardware support and "installed" come from ``runtime_profiles``; jobs from
``install_jobs``; sizes from a background ``SizeMeter`` so a 10 GB environment never blocks
a request (the size is ``None`` until measured, then cached). Besides the size, each row says how much a
removal would really free: uv hard-links packages from a shared cache, which stays after the folder goes.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, NamedTuple

from services import install_catalog
from services.install_catalog import Component

UNSUPPORTED, NOT_INSTALLED, INSTALLED, NEEDS_UPDATE, RUNNING = (
    "unsupported", "not_installed", "installed", "needs_update", "running")

SIZE_TTL_SECONDS = 300


class Footprint(NamedTuple):
    """What a folder holds on disk, and how much of it a removal would really free."""
    total: int
    unshared: int


def _stat(entry: os.DirEntry) -> os.stat_result:
    # Windows leaves st_nlink at 0 on a DirEntry's stat; only a real stat reports hard links.
    return os.lstat(entry.path) if os.name == "nt" else entry.stat(follow_symlinks=False)


def directory_footprint(path: Path) -> Footprint:
    """Bytes under ``path`` and how many belong to this folder alone.

    uv fills an environment with hard links to Pinokio's shared package cache, so a file with
    another link survives the removal of the folder: only single-link files are freed.
    Never follows symlinks and tolerates files that vanish mid-walk.
    """
    total = unshared = 0
    pending = [str(path)]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(entry.path)
                        continue
                    info = _stat(entry)
                    total += info.st_size
                    if info.st_nlink <= 1:
                        unshared += info.st_size
        except OSError:
            continue
    return Footprint(total, unshared)


class SizeMeter:
    """Measures folders on a daemon thread; ``get`` answers from cache and never waits."""

    def __init__(self, measure: Callable[[Path], Footprint] = directory_footprint, clock: Callable[[], float] = time.monotonic) -> None:
        self._measure, self._clock = measure, clock
        self._sizes: dict[Path, tuple[Footprint, float]] = {}
        self._pending: set[Path] = set()
        self._lock = threading.Lock()

    def get(self, path: Path) -> Footprint | None:
        if not path.exists():
            return Footprint(0, 0)
        with self._lock:
            cached = self._sizes.get(path)
            stale = cached is None or self._clock() - cached[1] > SIZE_TTL_SECONDS
            if stale and path not in self._pending:
                self._pending.add(path)
                threading.Thread(target=self._run, args=(path,), daemon=True).start()
            return cached[0] if cached else None

    def invalidate(self, path: Path) -> None:
        with self._lock:
            self._sizes.pop(path, None)

    def _run(self, path: Path) -> None:
        size = self._measure(path)
        with self._lock:
            self._sizes[path] = (size, self._clock())
            self._pending.discard(path)


def _state(component: Component, engine: dict, env_exists: bool, job: dict | None) -> str:
    if job and job["state"] == "running":
        return RUNNING
    if not engine["supported"]:
        return UNSUPPORTED
    if engine["installed"]:
        return INSTALLED
    return NEEDS_UPDATE if env_exists else NOT_INSTALLED


def _reclaimable(component: Component, root: Path, meter: SizeMeter) -> int | None:
    """What removing the component frees: the single-link bytes of every folder the removal deletes."""
    footprints = [meter.get(root / relative) for relative in component.remove]
    return None if any(footprint is None for footprint in footprints) else sum(f.unshared for f in footprints)


def _component_row(component: Component, engine: dict, root: Path, meter: SizeMeter, job: dict | None) -> dict:
    env = root / component.env
    env_exists = env.exists()
    state = _state(component, engine, env_exists, job)
    footprint = meter.get(env) if env_exists else Footprint(0, 0)
    return {
        **component.as_dict(),
        "state": state,
        "supported": bool(engine["supported"]),
        "reason": None if engine["supported"] else engine.get("reason"),
        "sizeBytes": footprint.total if footprint else None,
        "reclaimableBytes": _reclaimable(component, root, meter),
        "job": job,
    }


def _base_row(profiles: dict, root: Path, meter: SizeMeter) -> dict:
    engines = profiles["engines"]
    engine = engines["wangp"] if engines["wangp"]["supported"] else engines["core"]
    env_exists = (root / engine["env"]).exists()
    footprint = meter.get(root / engine["env"])
    return {
        **install_catalog.base(),
        "engine": "wangp" if engines["wangp"]["supported"] else "core",
        "installed": bool(engine["installed"]),
        # A running app whose receipt is stale needs Update in Pinokio; it is not "missing".
        "state": INSTALLED if engine["installed"] else NEEDS_UPDATE if env_exists else NOT_INSTALLED,
        "sizeBytes": footprint.total if footprint else None,
    }


def build(profiles: dict, jobs, meter: SizeMeter, root: Path, launcher_reason: str | None) -> dict:
    components = install_catalog.components()
    disk = shutil.disk_usage(root)
    rows = [
        _component_row(component, profiles["engines"][component.engine], root, meter, jobs.job(component))
        for component in components
    ]
    busy = jobs.running(components)
    return {
        "launcher": {"available": launcher_reason is None, "reason": launcher_reason},
        "disk": {"freeBytes": disk.free, "totalBytes": disk.total},
        "base": _base_row(profiles, root, meter),
        "components": rows,
        "busy": busy["component"] if busy else None,
    }
