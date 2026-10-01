"""Per-shot human review, stored beside the production file, never inside it.

``production.status`` keeps rereading ``<id>.production.json``. The review lives in
``<id>.review.json``. Without that file the artistic verdict stays pending.
A human approval is ``approved``. It is never the string ok.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

STATUSES = ("pending", "approved", "changes_requested")


class ReviewError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def review_path(root: Any, production_id: str) -> Path:
    return Path(root) / f"{production_id}.review.json"


def load_review(root: Any, production_id: str) -> dict | None:
    if not root or not production_id:
        return None
    path = review_path(root, production_id)
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def save_review(root: Any, production_id: str, body: dict) -> None:
    path = review_path(root, production_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def ensure_review(root: Any, production_id: str) -> dict:
    body = load_review(root, production_id) or {"version": 1, "production_id": production_id, "shots": {}}
    if not isinstance(body.get("shots"), dict):
        body["shots"] = {}
    body["version"] = 1
    body["production_id"] = production_id
    return body


def shot_row(body: dict, key: str) -> dict:
    shots = body.setdefault("shots", {})
    row = shots.get(key)
    if not isinstance(row, dict):
        row = {"status": "pending", "locked": False, "notes": "", "history": []}
        shots[key] = row
    row.setdefault("history", [])
    return row


def record_decision(root: Any, production_id: str, key: str, *, status: str | None = None, locked: bool | None = None, notes: str | None = None, snapshot: dict | None = None) -> dict:
    if status is not None and status not in STATUSES:
        raise ReviewError("invalid_review", "status must be pending, approved, or changes_requested")
    body = ensure_review(root, production_id)
    row = shot_row(body, key)
    if status is not None:
        row["status"] = status
    if locked is not None:
        row["locked"] = bool(locked)
    if notes is not None:
        row["notes"] = str(notes)[:500]
    if snapshot is not None:
        history = row.setdefault("history", [])
        history.append({"id": uuid.uuid4().hex[:12], "at": time.time(), "snapshot": snapshot})
        row["history"] = history[-8:]
    save_review(root, production_id, body)
    return {"key": key, "status": row.get("status"), "locked": bool(row.get("locked")), "notes": row.get("notes") or ""}


def annotate_rows(rows: list[dict], root: Any, production_id: str) -> list[dict]:
    """Add ``review`` only when a review file exists, so a manifest without one stays unchanged."""
    body = load_review(root, production_id)
    if not body:
        return rows
    shots = body.get("shots") if isinstance(body.get("shots"), dict) else {}
    for row in rows:
        record = shots.get(row.get("key"))
        if isinstance(record, dict):
            row["review"] = {"status": record.get("status") or "pending", "locked": bool(record.get("locked"))}
    return rows


def apply_artistic(summary: dict, root: Any, production_id: str | None) -> dict:
    """Overlay a human verdict. No review file leaves the code-check pending verdict alone."""
    review = summary.get("review") if isinstance(summary.get("review"), dict) else None
    artistic = review.get("artistic") if isinstance(review, dict) else None
    if not isinstance(artistic, dict) or not production_id:
        return summary
    verdict = human_verdict(load_review(root, production_id))
    if verdict is None:
        return summary
    artistic["verdict"] = verdict
    artistic["source"] = "human"
    return summary


def human_verdict(body: dict | None) -> str | None:
    if not isinstance(body, dict):
        return None
    shots = body.get("shots") if isinstance(body.get("shots"), dict) else {}
    rows = [item for item in shots.values() if isinstance(item, dict)]
    if not rows:
        return None
    if any(item.get("status") == "changes_requested" for item in rows):
        return "changes_requested"
    if all(item.get("status") == "approved" for item in rows):
        return "approved"
    return "pending"


def assert_publishable(root: Any, production_id: str, state: dict) -> None:
    """A spec with shot keys publishes only when each one is approved. No shot list is unchanged."""
    spec = state.get("spec") if isinstance(state.get("spec"), dict) else {}
    shots = spec.get("shots")
    if not isinstance(shots, list):
        return
    keys = [shot.get("key") for shot in shots if isinstance(shot, dict) and isinstance(shot.get("key"), str) and shot.get("key")]
    if not keys:
        return
    body = load_review(root, production_id)
    rows = body.get("shots") if isinstance(body, dict) and isinstance(body.get("shots"), dict) else {}
    missing = [key for key in keys if not isinstance(rows.get(key), dict) or rows[key].get("status") != "approved"]
    if missing:
        raise ValueError("review_required: " + ", ".join(missing[:12]))


def is_locked(production: Any, key: str) -> bool:
    body = load_review(getattr(production, "root", None), getattr(production, "id", ""))
    rows = body.get("shots") if isinstance(body, dict) else None
    row = rows.get(key) if isinstance(rows, dict) else None
    return bool(isinstance(row, dict) and row.get("locked"))


def assert_retake_unlocked(production: Any, retake: tuple | list = ()) -> None:
    """Refuse a named retake of a locked shot before the run mutates status."""
    keys = [key for key in retake if isinstance(key, str) and key]
    unlocked_windows(production, [{"key": key} for key in keys], keys)


def assert_obsolete_unlocked(production: Any) -> None:
    """Refuse a run that would keep a locked take shot against a previous song window.

    ``production.song.use`` flags those clips ``obsolete``. The clip pass then
    drops locked keys, so the montage would stitch the old take onto the new
    soundtrack.
    """
    from services.production_takes import obsolete_clip

    clips = (getattr(production, "state", None) or {}).get("clips") or {}
    stale = [key for key, clip in clips.items() if isinstance(key, str) and obsolete_clip(clip)]
    if stale:
        assert_retake_unlocked(production, stale)


def unlocked_windows(production: Any, windows: list[dict], retake: tuple | list = ()) -> list[dict]:
    """Drop locked shots from a frame or clip pass. An explicit retake that names one raises shot_locked.

    ``scenes()`` does not use this: it keeps locked shots in the cut and skips only their export.
    """
    body = load_review(getattr(production, "root", None), getattr(production, "id", ""))
    rows = body.get("shots") if isinstance(body, dict) else None
    if not isinstance(rows, dict):
        return windows
    locked = {key for key, row in rows.items() if isinstance(row, dict) and row.get("locked")}
    blocked = sorted(locked.intersection(retake))
    if blocked:
        from services.music_production import ProductionError
        raise ProductionError("shot_locked", "locked: " + ", ".join(blocked))
    if not locked:
        return windows
    return [window for window in windows if window.get("key") not in locked]


def snapshot(production: Any, key: str) -> dict:
    state = production.state
    spec = state.get("spec") if isinstance(state.get("spec"), dict) else {}
    shot = next((item for item in spec.get("shots") or [] if isinstance(item, dict) and item.get("key") == key), None)
    return {
        "frame": (state.get("frames") or {}).get(key),
        "clip": (state.get("clips") or {}).get(key),
        "scene": (state.get("scenes") or {}).get(key),
        "shot": json.loads(json.dumps(shot)) if isinstance(shot, dict) else None,
    }


def history_entry(root: Any, production_id: str, key: str, history_id: str) -> dict | None:
    body = load_review(root, production_id)
    rows = body.get("shots") if isinstance(body, dict) else None
    row = rows.get(key) if isinstance(rows, dict) else None
    history = row.get("history") if isinstance(row, dict) else None
    if not isinstance(history, list):
        return None
    for item in history:
        if isinstance(item, dict) and item.get("id") == history_id:
            return item
    return None


def restore_snapshot(production: Any, key: str, snap: dict) -> None:
    """Put the snapshot back. Files on disk stay."""
    for field, store in (("frame", "frames"), ("clip", "clips"), ("scene", "scenes")):
        bucket = production.state.setdefault(store, {})
        if snap.get(field) is None:
            bucket.pop(key, None)
        else:
            bucket[key] = snap[field]
    shot = snap.get("shot")
    spec = production.state.get("spec") if isinstance(production.state.get("spec"), dict) else None
    if isinstance(spec, dict) and isinstance(shot, dict):
        shots = spec.get("shots") if isinstance(spec.get("shots"), list) else []
        spec["shots"] = [shot if isinstance(item, dict) and item.get("key") == key else item for item in shots]
        production.state["spec"] = spec
    production.save()
