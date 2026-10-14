"""Favorites and the character-kit helpers the scene routes still call.

The functions are the launch helpers, unchanged. ``_workspace_dir`` and
``_get_active_workspace`` are the launch kernel aliases, assigned before a
request. ``_read_kit_library`` is assigned when launch imports the kit library.
"""
from __future__ import annotations

import json
import os
import re

from fastapi import HTTPException


_workspace_dir = None
_get_active_workspace = None
_read_kit_library = None


def _favorites_path() -> str:
    """Path to favorites JSON file for the active workspace."""
    return os.path.join(_workspace_dir(), ".favorites.json")

def _load_favorites() -> set:
    """Load favorites set for the active workspace."""
    from services.win_safe_files import favorites_lock
    fp = _favorites_path()
    if os.path.isfile(fp):
        try:
            with favorites_lock:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
            return set(data) if isinstance(data, list) else set()
        except Exception:
            pass
    return set()

def _save_favorites(favs: set):
    """Save favorites set for the active workspace.

    favorites_lock (shared with director_pipeline's delete sweep, which
    rewrites the same file) serializes read-modify-write cycles so a
    concurrent pipeline delete can't be clobbered by a stale write."""
    from services.win_safe_files import favorites_lock
    fp = _favorites_path()
    with favorites_lock:
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(sorted(favs), f)

def _character_kit_workspace(value) -> str:
    workspace = str(value or _get_active_workspace()).strip()
    if workspace != "default" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", workspace):
        raise HTTPException(status_code=400, detail="Invalid Character Kit workspace")
    return workspace

def _character_kit_conflict(exc) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "character_kit_revision_conflict",
            "message": str(exc),
            "expectedRevision": exc.expected,
            "currentRevision": exc.current,
        },
    )

def _character_kit_for_scene(workspace: str, kit_id: str) -> dict | None:
    from services.series_shot_bridge import with_pose_sizes
    kit = (_read_kit_library(_workspace_dir(workspace)).get("kits") or {}).get(kit_id)
    return with_pose_sizes(kit, _workspace_dir(workspace)) if kit else None
