"""Free-space guard and finished-run cleanup for a music-video production.

``production.run`` refuses to start under 10 GiB free. A completed run deletes
losing takes recorded in ``state["discarded"]`` and this production's
``{id}-slice-*.wav`` audio slices. The workspace is shared, so other videos stay.
The chosen song, every take of each shot (they are what a person swaps in when
editing a shot), scene exports and the final video stay. A failed run deletes nothing.
"""
from __future__ import annotations

import json

import os
import shutil
from pathlib import Path
from typing import Any, Callable

MIN_FREE_BYTES = 10 * 1024 ** 3


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
    for rows in (state.get("takes") or {}).values():     # every take stays: a person may swap one in when editing the shot
        names.extend(take.get("file") for take in rows if isinstance(take, dict))
    for key in ("clips", "scenes"):
        group = state.get(key)
        if not isinstance(group, dict):
            continue
        for item in group.values():
            if isinstance(item, dict):
                names.append(item.get("file"))
    return {Path(name).name for name in names if isinstance(name, str) and name}


def discard(state: dict, name: object) -> None:
    """Remember a losing take or audio slice this run may delete when it completes."""
    if not isinstance(name, str) or not name:
        return
    base = Path(name).name
    if not base or base in {".", ".."}:
        return
    names = state.setdefault("discarded", [])
    if base not in names:
        names.append(base)


def _owned_slice(path: Path, production_id: str) -> bool:
    return bool(production_id) and path.name.startswith(f"{production_id}-slice-") and path.suffix.lower() == ".wav"


def release_uploads(uploads_dir: str | Path, state: dict) -> int:
    """Delete the copies a completed run put in uploads/ unless its state still refers to them (a clip URL the package uses)."""
    names = [name for name in (state.get("uploads") or []) if isinstance(name, str) and name and os.sep not in name]
    if state.get("status") != "completed" or not names:
        return 0
    referenced_in = json.dumps({key: value for key, value in state.items() if key != "uploads"}, ensure_ascii=False)
    kept, removed = [], 0
    for name in names:
        if name in referenced_in:
            kept.append(name)
            continue
        try:
            Path(uploads_dir, name).unlink()
            removed += 1
        except FileNotFoundError:
            pass
        except OSError:
            kept.append(name)
    state["uploads"] = kept
    return removed


def release_completed(root: str | Path, state: dict, production_id: str = "") -> None:
    """Delete this run's losing takes and slices. Other statuses keep every file.

    Only basenames listed in ``state["discarded"]`` and ``{id}-slice-*.wav`` for
    this production are candidates. Kept names and every other workspace file
    stay, including videos from another production in the same root.
    """
    if state.get("status") != "completed":
        return
    directory = Path(root)
    if not directory.is_dir():
        return
    keep = kept_names(state)
    doomed = {Path(name).name for name in (state.get("discarded") or []) if isinstance(name, str) and name}
    for path in list(directory.iterdir()):
        if not path.is_file() or path.name in keep:
            continue
        if path.name in doomed or _owned_slice(path, production_id):
            path.unlink()
