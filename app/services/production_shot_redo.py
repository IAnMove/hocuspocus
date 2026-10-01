"""Redo one shot from its frame, its clip, or its scene export.

Unit tests pass ``shoot_frame`` and ``shoot_clip``. This module does not call ffmpeg
or a GPU. Scene redo calls the injected exporter, which is ``reexport_shot``.
"""
from __future__ import annotations

from typing import Any, Callable

_ORIGINS = frozenset({"frame", "clip", "scene"})


def redo(
    production: Any,
    spec: dict,
    key: str,
    origin: str,
    *,
    frame_prompt: str | None = None,
    action: str | None = None,
    shoot_frame: Callable[..., Any],
    shoot_clip: Callable[..., Any],
    export_scene: Callable[..., Any],
) -> dict:
    if origin not in _ORIGINS:
        from services.music_production import ProductionError
        raise ProductionError("invalid_redo", "from must be frame, clip, or scene")
    from services.production_shot_review import is_locked, record_decision, restore_snapshot, snapshot
    if is_locked(production, key):
        from services.music_production import ProductionError
        raise ProductionError("shot_locked", "locked: " + key)
    snap = snapshot(production, key)
    record_decision(production.root, production.id, key, snapshot=snap)
    try:
        _apply(production, spec, key, origin, frame_prompt, action, shoot_frame, shoot_clip, export_scene)
    except Exception:
        restore_snapshot(production, key, snap)
        raise
    return {"key": key, "from": origin}


def undo(production: Any, spec: dict, key: str, history_id: str, *, export_scene: Callable[..., Any]) -> dict:
    from services.production_shot_review import history_entry, is_locked, restore_snapshot
    if is_locked(production, key):
        from services.music_production import ProductionError
        raise ProductionError("shot_locked", "locked: " + key)
    entry = history_entry(production.root, production.id, key, history_id)
    if not isinstance(entry, dict) or not isinstance(entry.get("snapshot"), dict):
        from services.music_production import ProductionError
        raise ProductionError("history_not_found", f"no history {history_id} for {key}")
    restore_snapshot(production, key, entry["snapshot"])
    export_scene(production, spec, key)
    return {"key": key, "history_id": history_id}


def _apply(
    production: Any,
    spec: dict,
    key: str,
    origin: str,
    frame_prompt: str | None,
    action: str | None,
    shoot_frame: Callable[..., Any],
    shoot_clip: Callable[..., Any],
    export_scene: Callable[..., Any],
) -> None:
    if origin == "frame":
        _pop(production, "frames", key)
        _pop(production, "frame_failures", key)
        production._attempt("frame_attempts", key)
        shoot_frame(production, spec, key, frame_prompt)
        _require_media(production, "frames", key)
        return
    if origin == "clip":
        _pop(production, "clips", key)
        shoot_clip(production, spec, key, action)
        _require_media(production, "clips", key)
        return
    export_scene(production, spec, key)


def _require_media(production: Any, field: str, key: str) -> None:
    """A shooter that returns without media is not success: the previous take must come back."""
    bucket = production.state.get(field)
    row = bucket.get(key) if isinstance(bucket, dict) else None
    if field == "frames" and isinstance(row, str) and row:
        return
    if field == "clips" and isinstance(row, dict) and row.get("file"):
        return
    from services.music_production import ProductionError
    raise ProductionError("redo_failed", f"{field} missing after redo: {key}")


def _pop(production: Any, field: str, key: str) -> None:
    bucket = production.state.get(field)
    if isinstance(bucket, dict):
        bucket.pop(key, None)
