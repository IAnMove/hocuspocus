"""Free-space guard and finished-run cleanup for a music-video production.

``production.run`` refuses to start under 10 GiB free. A completed run deletes
losing takes and ``*-slice-*.wav`` audio slices. The chosen song, the best take
of each shot, scene exports and the final video stay. A failed run deletes nothing.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Callable

MIN_FREE_BYTES = 10 * 1024 ** 3
_VIDEO = frozenset({".mp4", ".webm", ".mov", ".mkv", ".m4v"})


def _free_bytes(usage: Any) -> int:
    free = getattr(usage, "free", None)
    if free is None:
        free = usage[2]
    return int(free)


def require_free_disk(workspace: str | Path, disk_usage: Callable[[str], Any] | None = None) -> None:
    """Raise ProductionError('disk_low') when the workspace volume has under 10 GiB free."""
    measure = disk_usage or shutil.disk_usage
    free = _free_bytes(measure(os.fspath(workspace)))
    if free < MIN_FREE_BYTES:
        from services.music_production import ProductionError
        raise ProductionError("disk_low", "workspace volume has under 10 GiB free")


def kept_names(state: dict) -> set[str]:
    """Basenames a completed run must not delete."""
    names: list[object] = []
    song = state.get("song")
    if isinstance(song, dict):
        names.append(song.get("file"))
    names.append(state.get("final"))
    for key in ("clips", "scenes"):
        group = state.get(key)
        if not isinstance(group, dict):
            continue
        for item in group.values():
            if isinstance(item, dict):
                names.append(item.get("file"))
    return {Path(name).name for name in names if isinstance(name, str) and name}


def _removable(path: Path) -> bool:
    return path.match("*-slice-*.wav") or path.suffix.lower() in _VIDEO


def release_completed(root: str | Path, state: dict) -> None:
    """Delete this run's losing takes and slices. Other statuses keep every file.

    The workspace is shared, so only videos and slices written after the run
    started are candidates. Kept names are never removed.
    """
    if state.get("status") != "completed":
        return
    directory = Path(root)
    if not directory.is_dir():
        return
    keep = kept_names(state)
    started = state.get("started")
    cutoff = float(started) - 1 if isinstance(started, (int, float)) else None
    for path in list(directory.iterdir()):
        if not path.is_file() or path.name in keep or not _removable(path):
            continue
        if cutoff is not None and path.stat().st_mtime < cutoff:
            continue
        path.unlink()
