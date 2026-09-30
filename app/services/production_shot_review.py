"""Per-shot review state for one production.

The file is ``<id>.review.json``, written with a temp file and ``os.replace``.
It is not part of ``production.json`` (that file is rewritten while a run waits).
``shots.json`` only gains a ``review`` field.
"""
from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path
from typing import Any

_STATUSES = frozenset({"pending", "approved", "changes_requested"})


class ReviewError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def review_path(root: Path, production_id: str) -> Path:
    return Path(root) / f"{production_id}.review.json"


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _atomic_json(path: Path, body: dict) -> None:
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, path)


def empty_document(production_id: str) -> dict:
    return {"version": 1, "production_id": production_id, "shots": {}}


def load_review(root: Path, production_id: str) -> dict:
    path = review_path(root, production_id)
    if not path.is_file():
        return empty_document(production_id)
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return empty_document(production_id)
    if not isinstance(body, dict) or body.get("version") != 1:
        return empty_document(production_id)
    body["production_id"] = production_id
    body.setdefault("shots", {})
    return body


def save_review(root: Path, production_id: str, body: dict) -> None:
    body["version"] = 1
    body["production_id"] = production_id
    _atomic_json(review_path(root, production_id), body)


def _row(body: dict, key: str) -> dict:
    shots = body.setdefault("shots", {})
    row = shots.get(key)
    if not isinstance(row, dict):
        row = {"status": "pending", "locked": False, "notes": [], "history": []}
        shots[key] = row
    row.setdefault("status", "pending")
    row.setdefault("locked", False)
    row.setdefault("notes", [])
    row.setdefault("history", [])
    return row


def require_key(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 80 or Path(value).name != value or value in {".", ".."}:
        raise ReviewError("invalid_command", "shot is required")
    return value


def _spec_shot(spec: dict, key: str) -> dict:
    for shot in spec.get("shots") or []:
        if isinstance(shot, dict) and shot.get("key") == key:
            return shot
    raise ReviewError("shot_not_found", f"no shot {key}")


def load_spec(root: Path, production_id: str) -> dict:
    path = Path(root) / f"{production_id}.production.json"
    if not path.is_file():
        raise ReviewError("production_not_found", "No production with this id")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReviewError("production_not_found", "No production with this id") from error
    spec = state.get("spec") if isinstance(state, dict) else None
    if not isinstance(spec, dict):
        raise ReviewError("invalid_spec", "This production has no spec")
    return spec


def snapshot(production: Any, spec: dict, key: str) -> dict:
    """The fields undo puts back. Media files are names, not something to delete."""
    shot = _spec_shot(spec, key)
    frames = _dict(production.state.get("frames"))
    clip = _dict(_dict(production.state.get("clips")).get(key))
    overrides = shot.get("overrides") if isinstance(shot.get("overrides"), dict) else {}
    return {
        "frame": frames.get(key),
        "clip": clip.get("file"),
        "frame_prompt": shot.get("frame"),
        "action": shot.get("action"),
        "overrides": copy.deepcopy(overrides),
    }


def _put_name(bucket: dict, key: str, name: Any) -> None:
    if isinstance(name, str) and name:
        bucket[key] = name
        return
    bucket.pop(key, None)


def apply_snapshot(production: Any, spec: dict, key: str, snap: dict) -> None:
    """Point the shot at the saved names and prompts. Does not delete files."""
    shot = _spec_shot(spec, key)
    shot["frame"] = snap.get("frame_prompt")
    shot["action"] = snap.get("action")
    overrides = snap.get("overrides") if isinstance(snap.get("overrides"), dict) else {}
    if overrides:
        shot["overrides"] = copy.deepcopy(overrides)
    else:
        shot.pop("overrides", None)
    _put_name(production.state.setdefault("frames", {}), key, snap.get("frame"))
    clips = production.state.setdefault("clips", {})
    clip_name = snap.get("clip")
    if isinstance(clip_name, str) and clip_name:
        current = dict(_dict(clips.get(key)))
        current["file"] = clip_name
        clips[key] = current
    else:
        clips.pop(key, None)
    production.state["spec"] = spec


def review_public(row: dict) -> dict:
    history = row.get("history") if isinstance(row.get("history"), list) else []
    last = history[-1] if history and isinstance(history[-1], dict) else {}
    public = {
        "status": row.get("status") if row.get("status") in _STATUSES else "pending",
        "locked": row.get("locked") is True,
    }
    if isinstance(last.get("id"), str):
        public["history_id"] = last["id"]
    return public


def _manifest_path(root: Path, production_id: str) -> Path:
    return Path(root) / f"{production_id}.shots.json"


def stamp_manifest(root: Path, production_id: str, key: str, row: dict) -> None:
    """Add ``review`` on the matching manifest row. Other fields stay as they are."""
    path = _manifest_path(root, production_id)
    if not path.is_file():
        return
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    shots = body.get("shots") if isinstance(body, dict) else None
    if not isinstance(shots, list):
        return
    matched = False
    for shot in shots:
        if isinstance(shot, dict) and shot.get("key") == key:
            shot["review"] = review_public(row)
            matched = True
            break
    if not matched:
        return
    _atomic_json(path, body)


def with_review_fields(root: Path, production_id: str, rows: list) -> list:
    """Keep ``review`` when ``write_manifest`` rebuilds the rows. No review file means no new field."""
    if not isinstance(rows, list):
        return rows
    path = review_path(root, production_id)
    if not path.is_file():
        return rows
    shots = _dict(load_review(root, production_id).get("shots"))
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = shots.get(row.get("key"))
        if isinstance(item, dict):
            row["review"] = review_public(item)
    return rows


def _note(text: Any, by: str) -> dict | None:
    if not isinstance(text, str) or not text.strip():
        return None
    return {"at": int(time.time()), "by": by, "text": text.strip()[:500]}


def set_review(root: Path, production_id: str, spec: dict, key: str, status: str, note: Any = None, by: str = "human") -> dict:
    if status not in _STATUSES:
        raise ReviewError("invalid_status", "status must be pending, approved or changes_requested")
    _spec_shot(spec, key)
    body = load_review(root, production_id)
    row = _row(body, key)
    row["status"] = status
    item = _note(note, by)
    if item:
        row["notes"].append(item)
    save_review(root, production_id, body)
    stamp_manifest(root, production_id, key, row)
    return {"shot": key, "status": status, "locked": row.get("locked") is True, "note": item}


def set_lock(root: Path, production_id: str, spec: dict, key: str, locked: bool) -> dict:
    if locked is not True and locked is not False:
        raise ReviewError("invalid_command", "locked must be boolean")
    _spec_shot(spec, key)
    body = load_review(root, production_id)
    row = _row(body, key)
    row["locked"] = locked
    save_review(root, production_id, body)
    stamp_manifest(root, production_id, key, row)
    return {"shot": key, "locked": locked, "status": row.get("status") or "pending"}


def _next_history_id(history: list) -> str:
    highest = 0
    for entry in history:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        suffix = entry["id"][1:]
        if entry["id"].startswith("h") and suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"h{highest + 1}"


def append_history(root: Path, production_id: str, key: str, *, by: str, kind: str, before: dict, after: dict, intent_id: str | None = None) -> str:
    body = load_review(root, production_id)
    row = _row(body, key)
    history = row.setdefault("history", [])
    ident = _next_history_id(history)
    entry = {"id": ident, "at": int(time.time()), "by": by, "kind": kind, "before": before, "after": after}
    if intent_id:
        entry["intent_id"] = intent_id
    history.append(entry)
    save_review(root, production_id, body)
    stamp_manifest(root, production_id, key, row)
    return ident


def find_history(root: Path, production_id: str, key: str, history_id: str) -> dict:
    body = load_review(root, production_id)
    row = _dict(_dict(body.get("shots")).get(key))
    for entry in row.get("history") or []:
        if isinstance(entry, dict) and entry.get("id") == history_id:
            return entry
    raise ReviewError("history_not_found", f"no history {history_id}")


def _is_locked(row: Any) -> bool:
    return isinstance(row, dict) and row.get("locked") is True


def locked_keys(production: Any) -> set[str]:
    shots = _dict(load_review(production.root, production.id).get("shots"))
    return {key for key, row in shots.items() if _is_locked(row)}


def without_locked(production: Any, windows: list) -> list:
    """Drop locked shots from a frame, clip or scene pass. The lock check stays here so the caller adds one call."""
    locked = locked_keys(production)
    if not locked:
        return windows
    return [item for item in windows if not (isinstance(item, dict) and item.get("key") in locked)]


def assert_unlocked(production: Any, key: str) -> None:
    if key in locked_keys(production):
        raise ReviewError("shot_locked", f"shot {key} is locked")


def manifest_shots(root: Path, production_id: str) -> list | None:
    """None when there is no shot manifest. An empty list is a manifest with no shots."""
    path = _manifest_path(root, production_id)
    if not path.is_file():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    shots = body.get("shots") if isinstance(body, dict) else None
    if not isinstance(shots, list):
        return None
    return [shot for shot in shots if isinstance(shot, dict) and shot.get("key")]


def _status_of(body: dict, key: str) -> str:
    status = _dict(_dict(body.get("shots")).get(key)).get("status")
    if status in _STATUSES:
        return status
    return "pending"


def require_reviews_approved(root: Path, production_id: str, accept_unreviewed: bool) -> None:
    """Block publish only when ``shots.json`` lists shots that are not approved.

    A production with no shot manifest is an older publish and is not blocked.
    A missing review file counts as pending for every listed shot.
    """
    if accept_unreviewed:
        return
    shots = manifest_shots(root, production_id)
    if not shots:
        return
    body = load_review(root, production_id)
    pending = [shot["key"] for shot in shots if _status_of(body, shot["key"]) != "approved"]
    if pending:
        raise ReviewError("review_incomplete", "approve every shot or pass accept_unreviewed: " + ", ".join(pending[:8]))


def review_from_input(root: Path, data: dict) -> dict:
    spec = load_spec(root, data["production_id"])
    key = require_key(data.get("shot"))
    status = data.get("status")
    if not isinstance(status, str):
        raise ReviewError("invalid_command", "status is required")
    note = data.get("note")
    if note is not None and not isinstance(note, str):
        raise ReviewError("invalid_command", "note must be a string")
    return set_review(root, data["production_id"], spec, key, status, note=note, by="human")


def lock_from_input(root: Path, data: dict) -> dict:
    spec = load_spec(root, data["production_id"])
    key = require_key(data.get("shot"))
    return set_lock(root, data["production_id"], spec, key, data.get("locked"))
