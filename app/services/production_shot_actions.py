"""Review actions for one shot, using the records the shot view already reads.

Selecting a take marks the previous export stale. Re-export updates that one
montage clip or Director filename. Nothing here calls a model, ffmpeg, or
``production.run``. ``applied`` is false until the posted plan is the plan
that runs.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from services.production_shot_review import history_entry, is_runner_snapshot, load_review, record_decision
from services.production_work_catalog import find_work


class ActionError(ValueError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$")
_WRITABLE = frozenset({"music", "director", "montage"})
_REVIEW = frozenset({"pending", "approved", "changes_requested"})
_ACTIONS = frozenset({"select", "review", "lock", "undo", "reexport", "open_scene", "request", "regenerate"})


def annotate_actions(shots: list[dict[str, Any]]) -> None:
    for shot in shots:
        shot["actions"] = describe_actions(shot)


def describe_actions(shot: dict[str, Any]) -> list[dict[str, Any]]:
    source = _source(shot)
    locked = _review_flag(shot, "locked")
    writable = source in _WRITABLE
    regenerable = source in {"music", "director", "series"} and shot.get("regenerable", True)
    return [
        _choice("select", writable and not locked and bool(shot.get("takes")), _write_reason(writable, locked, bool(shot.get("takes")))),
        _choice("review", True, None),
        _choice("lock", True, None),
        _choice("undo", writable and not locked and bool(_history(shot)), _undo_reason(writable, locked, shot)),
        _choice("reexport", writable and not locked, _write_reason(writable, locked, True)),
        _choice("open_scene", bool(_scene_id(shot)), None if _scene_id(shot) else "no_scene"),
        _choice("regenerate", regenerable and not locked,
                "shot_locked" if locked else (None if regenerable else "origin_unsupported")),
    ]


def stored_revision(workspace_dir: str, production_id: str) -> int:
    kind, document, _path = _locate(workspace_dir, production_id)
    if kind is None or not isinstance(document, dict):
        return 0
    return _revision(document)


def perform(workspace_dir: str, workspace_id: str, production_id: str, shot_id: str, body: dict[str, Any]) -> dict[str, Any]:
    if find_work(workspace_dir, workspace_id, production_id) is None:
        raise ActionError("not_found", "Production not found")
    action = body.get("action") if isinstance(body, dict) else None
    if action not in _ACTIONS:
        raise ActionError("invalid_action", "Unsupported shot action")
    if action == "request":
        return _request(workspace_dir, workspace_id, production_id, shot_id, body)
    if action == "regenerate":
        from services.production_shot_regeneration import regeneration_target
        return regeneration_target(workspace_dir, workspace_id, production_id, shot_id, body)
    if action == "open_scene":
        return _open_scene(workspace_dir, workspace_id, production_id, shot_id)
    if action == "review":
        return _review(workspace_dir, production_id, shot_id, body)
    if action == "lock":
        return _lock(workspace_dir, production_id, shot_id, body)
    return _mutate(workspace_dir, workspace_id, production_id, shot_id, action, body)


def _request(workspace_dir: str, workspace_id: str, production_id: str, shot_id: str, body: dict[str, Any]) -> dict[str, Any]:
    plan = body.get("plan") if isinstance(body.get("plan"), dict) else None
    if body.get("apply") is not True:
        return {"plan": plan, "applied": False}
    if plan is None or plan.get("action") not in {"select", "review", "lock", "undo", "reexport", "open_scene"}:
        raise ActionError("invalid_plan", "apply runs only the plan object that was shown")
    posted = dict(plan)
    if "expected_revision" not in posted and "expected_revision" in body:
        posted["expected_revision"] = body.get("expected_revision")
    result = perform(workspace_dir, workspace_id, production_id, shot_id, posted)
    return {"plan": plan, "applied": True, "result": result}


def _mutate(workspace_dir: str, workspace_id: str, production_id: str, shot_id: str, action: str, body: dict[str, Any]) -> dict[str, Any]:
    with _hold_edit(workspace_id, production_id):
        kind, document, path = _require_document(workspace_dir, production_id)
        if kind not in _WRITABLE or not isinstance(document, dict) or path is None:
            raise ActionError("origin_unsupported", "This origin has no shared edit")
        _expect(document, body.get("expected_revision"))
        if _locked(workspace_dir, production_id, shot_id):
            raise ActionError("shot_locked", "locked: " + shot_id)
        if action == "select":
            return _select(workspace_dir, production_id, shot_id, kind, document, path, body)
        if action == "undo":
            return _undo(workspace_dir, production_id, shot_id, kind, document, path, body)
        return _reexport(workspace_dir, production_id, shot_id, kind, document, path)


@contextmanager
def _hold_edit(workspace_id: str, production_id: str) -> Iterator[None]:
    """Occupy the same slot production.run and music shot edits use.

    Catalog select/undo/reexport rewrite ``<id>.shots.json`` or
    ``_director_pipeline_*.json``. A live music runner or Director save
    replaces that file from memory, so a concurrent write would drop the
    catalog take.
    """
    from fastapi import HTTPException

    from services import music_production
    from services.director.pipeline_locks import director_holds_production
    from services.production_commands import holding_edit

    if director_holds_production(production_id):
        raise ActionError("already_running", "This production is running")
    try:
        with holding_edit(music_production, workspace_id, production_id):
            yield
    except HTTPException as error:
        detail = error.detail if isinstance(error.detail, dict) else {}
        raise ActionError(
            str(detail.get("code") or "already_running"),
            str(detail.get("message") or "This production is running"),
        ) from error


def _select(workspace_dir: str, production_id: str, shot_id: str, kind: str, document: dict, path: str, body: dict[str, Any]) -> dict[str, Any]:
    take = _safe(body.get("take") or body.get("take_file"))
    if take is None:
        raise ActionError("take_not_found", "take is required")
    if kind == "music":
        _select_music(workspace_dir, production_id, shot_id, document, take)
    elif kind == "director":
        _select_director(workspace_dir, production_id, shot_id, document, take)
    else:
        _select_montage(workspace_dir, production_id, shot_id, document, take)
    revision = _bump(document)
    _save(path, document)
    return {"action": "select", "shot": shot_id, "take": take, "revision": revision, "applied": True}


def _select_music(workspace_dir: str, production_id: str, shot_id: str, document: dict, take: str) -> None:
    shot = _row(document.get("shots"), "key", shot_id)
    if take not in _files(shot.get("takes"), "file"):
        raise ActionError("take_not_found", take)
    _remember(workspace_dir, production_id, shot_id, {"clip": shot.get("clip"), "video_stale": _bool(shot.get("video_stale"))})
    shot["clip"] = take
    shot["video_stale"] = True
    _mark_montage(workspace_dir, document.get("montage"), shot_id, stale=True)


def _select_director(workspace_dir: str, production_id: str, shot_id: str, document: dict, take: str) -> None:
    clip = _row(document.get("clips"), "shot_id", shot_id)
    if take not in _files(clip.get("video_attempts"), "filename", "id"):
        raise ActionError("take_not_found", take)
    _remember(workspace_dir, production_id, shot_id, {
        "selected_video_filename": clip.get("selected_video_filename"),
        "video_filename": clip.get("video_filename"),
        "video_stale": _bool(clip.get("video_stale")),
    })
    clip["selected_video_filename"] = take
    clip["video_stale"] = True


def _select_montage(workspace_dir: str, production_id: str, shot_id: str, document: dict, take: str) -> None:
    clip = _montage_clip(document, shot_id)
    chosen = next((item for item in _list(clip.get("takes")) if item.get("id") == take), None)
    if chosen is None or _safe(chosen.get("source")) is None:
        raise ActionError("take_not_found", take)
    _remember(workspace_dir, production_id, shot_id, {
        "selectedTakeId": clip.get("selectedTakeId"),
        "source": clip.get("source"),
        "video_stale": _bool(clip.get("video_stale")),
    })
    clip["selectedTakeId"] = take
    clip["video_stale"] = True


def _reexport(workspace_dir: str, production_id: str, shot_id: str, kind: str, document: dict, path: str) -> dict[str, Any]:
    if kind == "music":
        _reexport_music(workspace_dir, production_id, shot_id, document)
    elif kind == "director":
        _reexport_director(workspace_dir, production_id, shot_id, document)
    else:
        _reexport_montage(workspace_dir, production_id, shot_id, document)
    revision = _bump(document)
    _save(path, document)
    return {"action": "reexport", "shot": shot_id, "revision": revision, "applied": True}


def _reexport_music(workspace_dir: str, production_id: str, shot_id: str, document: dict) -> None:
    shot = _row(document.get("shots"), "key", shot_id)
    take = _safe(shot.get("clip"))
    if take is None:
        raise ActionError("take_not_found", "the shot has no selected take")
    name = _safe(document.get("montage"))
    if name is None or not name.endswith(".montage.json"):
        raise ActionError("montage_missing", "this production has no montage yet")
    montage_path = os.path.join(workspace_dir, name)
    montage, problem = _read(montage_path)
    if problem or not isinstance(montage, dict):
        raise ActionError("montage_missing", name)
    clip = _montage_clip(montage, shot_id)
    _remember(workspace_dir, production_id, shot_id, {"clip": shot.get("clip"), "video_stale": _bool(shot.get("video_stale")), "montage_source": clip.get("source")})
    clip["source"] = take
    clip["video_stale"] = False
    shot["video_stale"] = False
    _bump(montage)
    _save(montage_path, montage)


def _reexport_director(workspace_dir: str, production_id: str, shot_id: str, document: dict) -> None:
    clip = _row(document.get("clips"), "shot_id", shot_id)
    take = _safe(clip.get("selected_video_filename") or clip.get("video_filename"))
    if take is None:
        raise ActionError("take_not_found", "the shot has no selected take")
    _remember(workspace_dir, production_id, shot_id, {
        "selected_video_filename": clip.get("selected_video_filename"),
        "video_filename": clip.get("video_filename"),
        "video_stale": _bool(clip.get("video_stale")),
    })
    clip["video_filename"] = take
    clip["video_stale"] = False


def _reexport_montage(workspace_dir: str, production_id: str, shot_id: str, document: dict) -> None:
    clip = _montage_clip(document, shot_id)
    chosen = _chosen_take(clip)
    source = _safe(chosen.get("source")) if chosen else _safe(clip.get("source"))
    if source is None:
        raise ActionError("take_not_found", "the shot has no selected take")
    _remember(workspace_dir, production_id, shot_id, {
        "selectedTakeId": clip.get("selectedTakeId"),
        "source": clip.get("source"),
        "video_stale": _bool(clip.get("video_stale")),
    })
    clip["source"] = source
    clip["video_stale"] = False
    clip.pop("selectedTakeId", None)


def _undo(workspace_dir: str, production_id: str, shot_id: str, kind: str, document: dict, path: str, body: dict[str, Any]) -> dict[str, Any]:
    history_id = body.get("history_id")
    if not isinstance(history_id, str) or not history_id:
        raise ActionError("history_not_found", "history_id is required")
    entry = history_entry(workspace_dir, production_id, shot_id, history_id)
    snap = entry.get("snapshot") if isinstance(entry, dict) else None
    if not isinstance(snap, dict):
        raise ActionError("history_not_found", history_id)
    if is_runner_snapshot(snap):
        raise ActionError("history_incompatible", "this history belongs to the production runner")
    if kind == "music":
        _restore_music(workspace_dir, document, shot_id, snap)
    elif kind == "director":
        _restore_fields(_row(document.get("clips"), "shot_id", shot_id), snap, ("selected_video_filename", "video_filename", "video_stale"))
    else:
        _restore_fields(_montage_clip(document, shot_id), snap, ("selectedTakeId", "source", "video_stale"))
    revision = _bump(document)
    _save(path, document)
    return {"action": "undo", "shot": shot_id, "history_id": history_id, "revision": revision, "applied": True}


def _restore_music(workspace_dir: str, document: dict, shot_id: str, snap: dict) -> None:
    shot = _row(document.get("shots"), "key", shot_id)
    if "clip" in snap:
        clip = snap.get("clip")
        if clip is not None and not isinstance(clip, str):
            raise ActionError("history_incompatible", "this history belongs to the production runner")
        shot["clip"] = clip
    _put_bool(shot, "video_stale", snap.get("video_stale"))
    if "montage_source" in snap:
        _restore_montage(workspace_dir, document.get("montage"), shot_id, snap)
        return
    if "video_stale" in snap:
        _mark_montage(workspace_dir, document.get("montage"), shot_id, stale=snap.get("video_stale") is True)


def _review(workspace_dir: str, production_id: str, shot_id: str, body: dict[str, Any]) -> dict[str, Any]:
    status = body.get("status")
    if status not in _REVIEW:
        raise ActionError("invalid_review", "status must be pending, approved, or changes_requested")
    notes = body.get("notes") if isinstance(body.get("notes"), str) else None
    result = record_decision(workspace_dir, production_id, shot_id, status=status, notes=notes)
    return {"action": "review", "applied": True, **result}


def _lock(workspace_dir: str, production_id: str, shot_id: str, body: dict[str, Any]) -> dict[str, Any]:
    locked = body.get("locked")
    if not isinstance(locked, bool):
        raise ActionError("invalid_review", "locked must be true or false")
    result = record_decision(workspace_dir, production_id, shot_id, locked=locked)
    return {"action": "lock", "applied": True, **result}


def _open_scene(workspace_dir: str, workspace_id: str, production_id: str, shot_id: str) -> dict[str, Any]:
    from services.production_shot_view import shot_view
    view = shot_view(workspace_dir, workspace_id, production_id)
    shot = next((item for item in (view or {}).get("shots") or [] if item.get("id") == shot_id), None)
    scene = shot.get("scene") if isinstance(shot, dict) else None
    if not isinstance(scene, dict) or not scene.get("id"):
        raise ActionError("no_scene", "this shot has no scene")
    return {"action": "open_scene", "applied": False, "scene": {"kind": scene.get("kind"), "id": scene.get("id")}}


def _choice(action: str, enabled: bool, reason: str | None) -> dict[str, Any]:
    row: dict[str, Any] = {"action": action, "enabled": enabled}
    if not enabled:
        row["reason"] = reason or "unavailable"
    return row


def _write_reason(writable: bool, locked: bool, has_takes: bool) -> str | None:
    if locked:
        return "shot_locked"
    if not writable:
        return "origin_unsupported"
    if not has_takes:
        return "no_take"
    return None


def _undo_reason(writable: bool, locked: bool, shot: dict[str, Any]) -> str | None:
    if locked:
        return "shot_locked"
    if not writable:
        return "origin_unsupported"
    if not _history(shot):
        return "no_history"
    return None


def _source(shot: dict[str, Any]) -> str:
    provenance = shot.get("provenance")
    if isinstance(provenance, dict) and isinstance(provenance.get("source"), str):
        return provenance["source"]
    return ""


def _review_flag(shot: dict[str, Any], key: str) -> bool:
    review = shot.get("review")
    return bool(isinstance(review, dict) and review.get(key))


def _history(shot: dict[str, Any]) -> str | None:
    review = shot.get("review")
    value = review.get("history_id") if isinstance(review, dict) else None
    return value if isinstance(value, str) and value else None


def _scene_id(shot: dict[str, Any]) -> str | None:
    scene = shot.get("scene")
    value = scene.get("id") if isinstance(scene, dict) else None
    return value if isinstance(value, str) and value else None


def _require_document(workspace_dir: str, production_id: str):
    kind, document, path = _locate(workspace_dir, production_id)
    if kind is None:
        raise ActionError("origin_unsupported", "This origin has no shared edit")
    if document is None:
        raise ActionError("shots_unreadable", "The shot record could not be read")
    return kind, document, path


def _locate(workspace_dir: str, production_id: str):
    manifest = os.path.join(workspace_dir, f"{production_id}.shots.json")
    if os.path.isfile(manifest):
        body, problem = _read(manifest)
        return "music", None if problem else body, manifest
    director = _director_path(workspace_dir, production_id)
    if director:
        body, problem = _read(director)
        return "director", None if problem else body, director
    montage = _montage_path(workspace_dir, production_id)
    if montage:
        body, problem = _read(montage)
        return "montage", None if problem else body, montage
    return None, None, None


def snapshot_recency(path: str, body: dict[str, Any] | None = None) -> tuple[float, float]:
    """Rank a Director snapshot so review, select and regenerate share one file.

    A second Start from a lingering Story Lab handoff writes another
    ``_director_pipeline_*.json`` with the same ``production_id``. Lexicographic
    name order then pointed writes at the older cut.
    """
    stamp = _timestamp(body.get("updated_at") if isinstance(body, dict) else None)
    if stamp is None and isinstance(body, dict):
        stamp = _timestamp(body.get("completed_at"))
    if stamp is None and isinstance(body, dict):
        stamp = _timestamp(body.get("created_at"))
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    return (stamp or 0.0, mtime)


def _timestamp(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _director_path(workspace_dir: str, production_id: str) -> str | None:
    try:
        names = sorted(os.listdir(workspace_dir))
    except OSError:
        return None
    chosen: str | None = None
    chosen_rank: tuple[float, float] | None = None
    for name in names:
        if not name.startswith("_director_pipeline_") or not name.endswith(".json") or ".." in name:
            continue
        path = os.path.join(workspace_dir, name)
        body, problem = _read(path)
        if problem or not isinstance(body, dict) or not _director_matches(body, production_id):
            continue
        rank = snapshot_recency(path, body)
        if chosen_rank is None or rank > chosen_rank:
            chosen, chosen_rank = path, rank
    return chosen


def _director_matches(body: dict, production_id: str) -> bool:
    from services.production_run import pipeline_matches_production

    return pipeline_matches_production(body, production_id)


def _montage_path(workspace_dir: str, production_id: str) -> str | None:
    production, problem = _read(os.path.join(workspace_dir, f"{production_id}.production.json"))
    if problem or not isinstance(production, dict):
        return None
    name = _safe(production.get("montage_file"))
    if name and name.endswith(".montage.json") and os.path.isfile(os.path.join(workspace_dir, name)):
        return os.path.join(workspace_dir, name)
    return None


def _mark_montage(workspace_dir: str, name: Any, shot_id: str, *, stale: bool) -> None:
    def apply(clip: dict) -> None:
        clip["video_stale"] = stale

    _rewrite_montage(workspace_dir, name, shot_id, apply)


def _restore_montage(workspace_dir: str, name: Any, shot_id: str, snap: dict) -> None:
    def apply(clip: dict) -> None:
        source = snap.get("montage_source")
        if source is None:
            clip.pop("source", None)
        else:
            clip["source"] = source
        if "video_stale" in snap:
            _put_bool(clip, "video_stale", snap.get("video_stale"))

    _rewrite_montage(workspace_dir, name, shot_id, apply)


def _rewrite_montage(workspace_dir: str, name: Any, shot_id: str, apply: Callable[[dict], None]) -> None:
    safe = _safe(name)
    if safe is None or not safe.endswith(".montage.json"):
        return
    path = os.path.join(workspace_dir, safe)
    if not os.path.isfile(path):
        return
    document, problem = _read(path)
    if problem or not isinstance(document, dict):
        return
    try:
        clip = _montage_clip(document, shot_id)
    except ActionError:
        return
    apply(clip)
    _bump(document)
    _save(path, document)


def _montage_clip(document: dict, shot_id: str) -> dict:
    for clip in _list(document.get("clips")):
        origin = clip.get("origin") if isinstance(clip.get("origin"), dict) else {}
        if clip.get("id") == shot_id or origin.get("shotId") == shot_id:
            return clip
    raise ActionError("shot_not_found", shot_id)


def _row(raw: Any, key: str, shot_id: str) -> dict:
    for item in _list(raw):
        if item.get(key) == shot_id:
            return item
    raise ActionError("shot_not_found", shot_id)


def _chosen_take(clip: dict) -> dict | None:
    selected = clip.get("selectedTakeId")
    for item in _list(clip.get("takes")):
        if item.get("id") == selected:
            return item
    return None


def _files(raw: Any, *keys: str) -> list[str]:
    found = []
    for item in _list(raw):
        for key in keys:
            name = _safe(item.get(key))
            if name:
                found.append(name)
                break
    return found


def _restore_fields(target: dict, snap: dict, keys: tuple[str, ...]) -> None:
    for key in keys:
        if key not in snap:
            continue
        if key == "video_stale":
            _put_bool(target, key, snap.get(key))
        elif snap.get(key) is None:
            target.pop(key, None)
        else:
            target[key] = snap.get(key)


def _put_bool(target: dict, key: str, value: Any) -> None:
    if isinstance(value, bool):
        target[key] = value
    else:
        target.pop(key, None)


def _remember(workspace_dir: str, production_id: str, shot_id: str, snap: dict) -> None:
    record_decision(workspace_dir, production_id, shot_id, snapshot=snap)


def _locked(workspace_dir: str, production_id: str, shot_id: str) -> bool:
    body = load_review(workspace_dir, production_id)
    rows = body.get("shots") if isinstance(body, dict) else None
    row = rows.get(shot_id) if isinstance(rows, dict) else None
    return bool(isinstance(row, dict) and row.get("locked"))


def _expect(document: dict, expected: Any) -> None:
    current = _revision(document)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected != current:
        raise ActionError("stale_revision", str(current))


def _revision(document: dict) -> int:
    value = document.get("revision")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _bump(document: dict) -> int:
    document["revision"] = _revision(document) + 1
    return document["revision"]


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _list(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _safe(value: Any) -> str | None:
    if not isinstance(value, str) or ".." in value:
        return None
    name = value.replace("\\", "/").split("/")[-1]
    if not _NAME.fullmatch(name):
        return None
    return name


def _read(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
    except FileNotFoundError:
        return None, None
    except (OSError, json.JSONDecodeError):
        return None, "unreadable"
    return body if isinstance(body, dict) else None, None if isinstance(body, dict) else "unreadable"


def _save(path: str, body: dict) -> None:
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(body, handle)
    os.replace(temporary, path)
