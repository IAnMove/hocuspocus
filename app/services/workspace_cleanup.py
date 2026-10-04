"""Intermediate files are released when the work that made them is done.

A workspace holds three kinds of files. Results (published videos, approved
takes, kits, series, saved scenes) are never touched here. Intermediates are
what a job needs only while it runs: the frames and audio mix of an export, the
copies a production puts in uploads, the raw takes of a voice line. Caches can
be rebuilt. Until now nothing released intermediates: one installation held
28 GB of frames from exports published weeks ago, another 122 GB.

Exports release their staging when they publish (``World3DExportService``),
productions release their uploads when they complete (``production_disk``),
the native series render drops each raw take once trimmed. ``startup_cleanup``
releases what a restart or an older version left behind. Set
``HOCUS_KEEP_EXPORT_STAGING=1`` to keep export staging for debugging.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

EXPORT_FOLDERS = (".world3d-export", ".scene2d-export")
# Text files of a staging folder are small and say what was rendered; everything else is regenerable.
KEEP_IN_STAGING = (".json", ".txt")
# Staging of these tasks may still be in use, or is about to be when the user resumes.
LIVE_STATUSES = frozenset({"queued", "waiting_resource", "running", "interrupted"})
# A staging folder touched this recently may belong to a worker that has not registered yet.
SETTLE_SECONDS = 300
VOICE_RAW = re.compile(r"^(ln-.+)-raw\d+\.wav$")
TEMP_PREFIXES = ("hocuspocus-speech-",)


def keep_export_staging() -> bool:
    return os.environ.get("HOCUS_KEEP_EXPORT_STAGING", "").strip().lower() in {"1", "true", "yes"}


def _remove(path: Path) -> int:
    """Delete a file or a tree; returns the bytes it held (0 when it was already gone)."""
    try:
        if path.is_dir() and not path.is_symlink():
            size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
            shutil.rmtree(path, ignore_errors=True)
            return size
        size = path.stat().st_size
        path.unlink()
        return size
    except OSError:
        return 0


def release_export_staging(staging: Path) -> int:
    """Drop the frames and media of one export's staging folder; keep its JSON and text. Returns bytes freed."""
    freed = 0
    if not staging.is_dir():
        return 0
    for child in list(staging.iterdir()):
        if child.is_file() and child.suffix.lower() in KEEP_IN_STAGING:
            continue
        freed += _remove(child)
    return freed


def prune_export_staging(workspace_dir: str, registry: Any, operations: Iterable[str], token_for: Callable[[str], str],
                         now: float | None = None) -> dict[str, int]:
    """Release the staging of every export that is not live: completed, failed, cancelled or unknown to the registry."""
    live: set[str] = set()
    wanted = set(operations)
    for status in LIVE_STATUSES:
        for task in registry.list(statuses={status}, limit=1000):
            if task.get("workflow") not in wanted:
                continue
            admission = registry.command_admission_for_task(task["id"])
            if admission and isinstance(admission.get("intent_id"), str):
                live.add(token_for(admission["intent_id"]))
    moment = time.time() if now is None else now
    released, freed = 0, 0
    for folder in EXPORT_FOLDERS:
        root = Path(workspace_dir) / folder
        if not root.is_dir():
            continue
        for child in list(root.iterdir()):
            if not child.is_dir() or child.name in live:
                continue
            try:
                if moment - child.stat().st_mtime < SETTLE_SECONDS:
                    continue
            except OSError:
                continue
            size = release_export_staging(child)
            if size:
                released += 1
                freed += size
    return {"released": released, "bytes": freed}


def release_voice_raws(workspace_dir: str) -> dict[str, int]:
    """Drop the raw takes of series voice lines whose trimmed recording exists (``ln-…-raw0.wav`` + ``.meta.json``)."""
    root = Path(workspace_dir)
    released, freed = 0, 0
    if not root.is_dir():
        return {"released": 0, "bytes": 0}
    for path in list(root.iterdir()):
        match = VOICE_RAW.match(path.name) if path.is_file() else None
        if not match or not (root / f"{match.group(1)}.wav").is_file():
            continue
        for item in (path, path.with_name(f"{path.stem}.meta.json")):
            size = _remove(item) if item.is_file() else 0
            freed += size
        released += 1
    return {"released": released, "bytes": freed}


def sweep_temp_dirs(prefixes: Iterable[str] = TEMP_PREFIXES, max_age_seconds: float = 86400, root: str | None = None,
                    now: float | None = None) -> dict[str, int]:
    """Remove the temporary folders older versions left in the system temp directory."""
    base = Path(root or tempfile.gettempdir())
    moment = time.time() if now is None else now
    released, freed = 0, 0
    names = tuple(prefixes)
    try:
        children = list(base.iterdir())
    except OSError:
        return {"released": 0, "bytes": 0}
    for child in children:
        if not child.name.startswith(names) or not child.is_dir():
            continue
        try:
            if moment - child.stat().st_mtime < max_age_seconds:
                continue
        except OSError:
            continue
        size = _remove(child)
        released += 1
        freed += size
    return {"released": released, "bytes": freed}


def startup_cleanup(workspaces: Iterable[str], workspace_dir: Callable[[str], str], registry_for: Callable[[str], Any],
                    operations: Iterable[str], token_for: Callable[[str], str], log: Callable[[str], None] = print,
                    temp_root: str | None = None) -> dict[str, int]:
    """Release what the last run and older versions left behind, in every workspace; one line of log."""
    total = {"released": 0, "bytes": 0}
    if keep_export_staging():
        log("[Storage] HOCUS_KEEP_EXPORT_STAGING is set: export staging is kept")
    for workspace in workspaces:
        try:
            root = workspace_dir(workspace)
            parts = [release_voice_raws(root)]
            if not keep_export_staging():
                parts.append(prune_export_staging(root, registry_for(workspace), operations, token_for))
        except Exception as error:  # one workspace must not stop the others
            log(f"[Storage] cleanup skipped for {workspace}: {type(error).__name__}: {error}")
            continue
        for part in parts:
            total["released"] += part["released"]
            total["bytes"] += part["bytes"]
    swept = sweep_temp_dirs(root=temp_root)
    total["released"] += swept["released"]
    total["bytes"] += swept["bytes"]
    if total["bytes"]:
        log(f"[Storage] Released {total['bytes'] / 1024 ** 3:.1f} GB of intermediate files ({total['released']} items)")
    return total


__all__ = ["EXPORT_FOLDERS", "KEEP_IN_STAGING", "LIVE_STATUSES", "keep_export_staging", "prune_export_staging",
           "release_export_staging", "release_voice_raws", "startup_cleanup", "sweep_temp_dirs"]
