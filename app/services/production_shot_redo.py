"""Regenerate one shot from its frame, its clip, or its scene export.

GPU calls go through ``Production.image`` and ``Production.clip_job``. Those
use ``production.mcp``, which ``Production`` already wraps with
``production_resource_gate.guard_mcp``. Remounting the montage clip is
``production_shot_edit.remount_shot`` (the same ``expected_revision`` path).
Nothing in this module deletes a take or any other media file.
"""
from __future__ import annotations

from typing import Any

from services.production_shot_review import (
    ReviewError, append_history, apply_snapshot, assert_unlocked, find_history, require_key, snapshot,
)

_SOURCES = frozenset({"frame", "clip", "scene"})


def _optional_text(data: dict, name: str) -> str | None:
    value = data.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReviewError("invalid_command", f"{name} must be a string")
    return value


def _optional_int(data: dict, name: str) -> int | None:
    value = data.get(name)
    if value is None:
        return None
    if type(value) is not int:
        raise ReviewError("invalid_command", f"{name} must be an integer")
    return value


def _optional_cast(value: Any) -> list | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ReviewError("invalid_command", "cast must be a list of ids")
    for item in value:
        if not isinstance(item, str) or not item or "/" in item or "\\" in item or ".." in item:
            raise ReviewError("invalid_command", "cast must be a list of ids")
    return list(value)


def parse_redo(data: dict) -> dict:
    source = data.get("from")
    if source not in _SOURCES:
        raise ReviewError("invalid_redo", "from must be frame, clip or scene")
    return {
        "source": source,
        "frame_prompt": _optional_text(data, "frame_prompt"),
        "action": _optional_text(data, "action"),
        "seed": _optional_int(data, "seed"),
        "image_model": _optional_text(data, "image_model"),
        "cast": _optional_cast(data.get("cast")),
        "expected_revision": _optional_int(data, "expected_revision"),
    }


def _assign(spec: dict, key: str, fields: dict) -> None:
    from services.production_shot_review import _spec_shot
    shot = _spec_shot(spec, key)
    if isinstance(fields.get("frame_prompt"), str):
        shot["frame"] = fields["frame_prompt"]
    if isinstance(fields.get("action"), str):
        shot["action"] = fields["action"]
    if type(fields.get("seed")) is int:
        shot["seed"] = fields["seed"]
    if isinstance(fields.get("image_model"), str) and fields["image_model"]:
        shot["image_model"] = fields["image_model"]
    if isinstance(fields.get("cast"), list):
        shot["cast"] = list(fields["cast"])


def _window(production: Any, spec: dict, key: str) -> dict:
    from services.music_production import shot_windows
    for window in shot_windows(spec, production.score()):
        if window.get("key") == key:
            return window
    raise ReviewError("shot_not_found", f"shot {key} has no scene window")


def fresh_attempt(production: Any, key: str) -> int:
    """Reuse ``Production._attempt``, then step past it when this shot already has a frame.

    The image intent id includes the attempt. A redo must not ask the journal for the old job.
    """
    attempt = production._attempt("frame_attempts", key)
    frames = production.state.get("frames") if isinstance(production.state.get("frames"), dict) else {}
    if frames.get(key):
        attempt = production._attempt("frame_attempts", key)
    return attempt


def _land_frame(production: Any, spec: dict, window: dict) -> str:
    from services.music_production import FRAME_RESOLUTIONS
    from services.production_cast_portrait import frame_references
    key = window["key"]
    attempt = fresh_attempt(production, key)
    settings = spec.get("style") or {}
    refs = frame_references(window, production.state.get("cast") or {}, production.state.get("cast_single") or {})
    seed = window.get("seed", 3) + (attempt or 0)
    model = window.get("image_model", settings.get("image_model", "flux2_klein_9b"))
    steps = window.get("image_steps", settings.get("image_steps"))
    job = production.image(
        "frame-" + key, production.frame_prompt(spec, window), refs or None,
        FRAME_RESOLUTIONS[0], seed, model, steps, attempt,
    )
    name = production.wait({key: job}).get(key)
    if not name:
        raise ReviewError("frame_failed", f"shot {key} did not return a start frame")
    production.state.setdefault("frames", {})[key] = name
    return name


def _take_index(production: Any, key: str) -> int:
    tried = production.state.setdefault("clip_takes", {})
    current = tried.get(key)
    if isinstance(current, int):
        return current
    return len((production.state.get("takes") or {}).get(key) or [])


def _clip_seed(window: dict, take: int, explicit: int | None) -> int:
    if type(explicit) is int:
        return explicit
    return 7000 + int(window.get("i") or 0) * 10 + take


def _keep_clip(production: Any, key: str, name: str, take: int) -> None:
    _path, url = production.upload(name)
    production.state.setdefault("takes", {}).setdefault(key, []).append({"file": name, "take": take})
    production.state.setdefault("clips", {})[key] = {"file": name, "qa": {}, "url": url}
    production.state.setdefault("clip_takes", {})[key] = take


def _land_clip(production: Any, spec: dict, window: dict, seed: int | None) -> str:
    key = window["key"]
    take = _take_index(production, key) + 1
    job = production.clip_job(spec, window, _clip_seed(window, take, seed), take - 1)
    name = production.wait({key: job}).get(key)
    if not isinstance(name, str) or not name:
        raise ReviewError("clip_failed", f"shot {key} did not return a clip")
    _keep_clip(production, key, name, take)
    return name


def _abort(production: Any, spec: dict, key: str, checkpoint: dict, before: dict) -> None:
    from services.production_shot_edit import restore_shot
    restore_shot(production, spec, key, checkpoint)
    apply_snapshot(production, spec, key, before)
    production.save()


def redo_shot(production: Any, spec: dict, key: str, *, source: str, frame_prompt: str | None = None,
              action: str | None = None, seed: int | None = None, image_model: str | None = None,
              cast: list | None = None, expected_revision: int | None = None, by: str = "human",
              intent_id: str | None = None) -> dict:
    """Rebuild one shot. ``source`` is ``frame`` (image, then clip, then scene), ``clip``, or ``scene``."""
    from services.production_shot_edit import ShotEditError, shot_checkpoint, remount_shot
    if source not in _SOURCES:
        raise ReviewError("invalid_redo", "from must be frame, clip or scene")
    require_key(key)
    assert_unlocked(production, key)
    before = snapshot(production, spec, key)
    checkpoint = shot_checkpoint(production, spec, key)
    fields = {"frame_prompt": frame_prompt, "action": action, "seed": seed, "image_model": image_model, "cast": cast}
    try:
        _assign(spec, key, fields)
        production.state["spec"] = spec
        if source in {"frame", "clip"}:
            window = _window(production, spec, key)
            if source == "frame":
                _land_frame(production, spec, window)
                window = _window(production, spec, key)
            _land_clip(production, spec, window, seed)
        result = remount_shot(production, spec, key, expected_revision=expected_revision)
    except ReviewError:
        _abort(production, spec, key, checkpoint, before)
        raise
    except ShotEditError:
        _abort(production, spec, key, checkpoint, before)
        raise
    except Exception:
        _abort(production, spec, key, checkpoint, before)
        raise
    after = snapshot(production, spec, key)
    result["history_id"] = append_history(
        production.root, production.id, key, by=by, kind="redo", before=before, after=after, intent_id=intent_id,
    )
    return result


def redo_from_input(production: Any, spec: dict, data: dict) -> dict:
    key = require_key(data.get("shot"))
    fields = parse_redo(data)
    return redo_shot(production, spec, key, **fields)


def undo_shot(production: Any, spec: dict, key: str, history_id: str) -> dict:
    """Restore one history entry's ``before`` snapshot and re-export that scene. Files stay on disk."""
    from services.production_shot_edit import ShotEditError, remount_shot, shot_checkpoint, restore_shot
    require_key(key)
    entry = find_history(production.root, production.id, key, history_id)
    before = entry.get("before") if isinstance(entry.get("before"), dict) else None
    if not before:
        raise ReviewError("history_not_found", "that history entry has no before snapshot")
    current = snapshot(production, spec, key)
    checkpoint = shot_checkpoint(production, spec, key)
    apply_snapshot(production, spec, key, before)
    try:
        result = remount_shot(production, spec, key)
    except (ShotEditError, ReviewError):
        restore_shot(production, spec, key, checkpoint)
        apply_snapshot(production, spec, key, current)
        production.save()
        raise
    except Exception:
        restore_shot(production, spec, key, checkpoint)
        apply_snapshot(production, spec, key, current)
        production.save()
        raise
    restored = snapshot(production, spec, key)
    result["history_id"] = append_history(
        production.root, production.id, key, by="human", kind="undo", before=current, after=restored,
    )
    result["restored"] = before
    return result


def undo_from_input(production: Any, spec: dict, data: dict) -> dict:
    key = require_key(data.get("shot"))
    history_id = data.get("history_id")
    if not isinstance(history_id, str) or not history_id:
        raise ReviewError("invalid_command", "history_id is required")
    return undo_shot(production, spec, key, history_id)
