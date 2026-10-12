"""Staged review of a Series Lab episode: a production mode and, per shot, a plan and a preview decision with notes.

An episode is produced in one of three modes:

* ``direct``: everything renders and assembles as it always did (the default, and what an episode without
  ``review`` is).
* ``plan``: each shot's plan (what it shows and says) is approved before it renders.
* ``preview``: the plan is approved, then a cheap preview is rendered and approved (or sent back with notes), then
  the final takes are made and the episode is assembled.

The state lives on the episode, owned by the server (``POST .../review``, ``series.episode.review.set``)::

    episode["review"] = {
        "mode": "direct" | "plan" | "preview", "updatedAt": iso,
        "shots": {shot_id: {
            "plan": "pending" | "approved" | "changes", "planAt": iso, "planDigest": hex, "planBy": author,
            "preview": "pending" | "approved" | "changes", "previewAt": iso, "previewDigest": hex, "previewBy": author,
            "previewAttemptId": attempt_id,
            "notes": [{"id": "note_<hex>", "at": iso, "stage": "plan" | "preview" | "final", "text": str,
                       "by": author}]}}}

An author is who decided or wrote: ``user``, ``agent`` (an MCP client), ``wizard`` (Ask to the Wizard) or ``server``
(a production approving on its own), as on a take's ``approvedBy`` (``services/agent_activity.current_actor``).

A shot without an entry is pending at both stages and has no notes. A decision keeps the digest of the shot's
content (``SHOT_CONTENT_FIELDS``: lines, cast, layout2d, scene3d, location, framing...) it was made on, so when that
content changes, by any write path, the decision goes back to pending; the notes stay. The one exception is a
``series.shot.update`` that changed only an sfx volume: it moves the decision to the new digest (``carry_decisions``). A preview decision is also
about one take: a newer take that was not made as that preview's final (``attempt.reviewStage`` ``final``) puts it
back to pending, since nobody has looked at it yet.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from typing import Any

MODES = ("direct", "plan", "preview")
STATUSES = ("pending", "approved", "changes")
STAGES = ("plan", "preview", "final")
AUTHORS = ("user", "agent", "wizard", "server")
MAX_NOTES = 100
MAX_NOTE_CHARS = 2000
MAX_CHANGES = 500
CHANGE_KEYS = frozenset({"shotId", "plan", "preview", "attemptId", "note", "removeNoteId"})
NOTE_KEYS = frozenset({"id", "text", "stage", "by"})
_NOTE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
# What the user is asked next, in production order; "changes" are the agent's to fix.
STEP_ORDER = ("changes", "approve_plan", "render", "render_previews", "approve_previews", "render_final")
USER_STEPS = ("approve_plan", "render", "render_previews", "approve_previews", "render_final")


class ReviewError(ValueError):
    def __init__(self, message: str, *, status: int = 400, code: str = "invalid_review") -> None:
        super().__init__(message)
        self.status, self.code = status, code


def _plain(value: Any) -> Any:
    """``56.0`` and ``56`` are one position: a browser round trip turns one into the other."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _without_sfx_volume(layout: Any) -> Any:
    if not isinstance(layout, dict) or not isinstance(layout.get("sfx"), list):
        return layout
    cues = [{key: value for key, value in cue.items() if key != "volume"} if isinstance(cue, dict) else cue
            for cue in layout["sfx"]]
    return {**layout, "sfx": cues}


def content_digest(shot: dict, *, sfx_volume: bool = True) -> str:
    """Fingerprint of what a shot shows and says, as ``same_shot_content`` compares it.

    Stored decisions always hold the full digest. ``sfx_volume=False`` leaves the sfx cues' volume out, only to tell
    an edit that changed nothing but a mix level (``carry_decisions``)."""
    from .series_library import SHOT_CONTENT_FIELDS, _beat_content, _take_layout
    payload = {}
    for key in sorted(SHOT_CONTENT_FIELDS):
        # A generated or imported take keeps its look when only the sound laid at the cut changes.
        value = _beat_content(shot.get(key)) if key == "dialogueBeats" else _take_layout(shot) if key == "layout2d" else shot.get(key)
        if key == "layout2d" and not sfx_volume:
            value = _without_sfx_volume(value)
        if value:
            payload[key] = _plain(value)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:16]


def carry_decisions(episode: dict, shot_id: str, before: str, after: str) -> None:
    """Move the shot's plan and preview decisions made on digest ``before`` to ``after``: for an edit the caller
    knows changed only a mix level (an sfx volume). Any other change leaves them to go back to pending."""
    review = episode.get("review") if isinstance(episode.get("review"), dict) else {}
    shots = review.get("shots") if isinstance(review.get("shots"), dict) else {}
    entry = shots.get(shot_id)
    if not isinstance(entry, dict):
        return
    for stage in ("plan", "preview"):
        if entry.get(f"{stage}Digest") == before:
            entry[f"{stage}Digest"] = after


def _attempts(shot: dict) -> list[dict]:
    return [item for item in shot.get("attempts") or [] if isinstance(item, dict)]


def _usable(attempt: dict) -> bool:
    return attempt.get("status") == "completed" and attempt.get("reviewDecision") != "rejected" \
        and bool(attempt.get("outputAssetIds"))


def latest_take(shot: dict) -> dict | None:
    """The newest completed take that was not rejected: what a reviewer looks at."""
    return next((item for item in reversed(_attempts(shot)) if _usable(item)), None)


def approved_take(shot: dict) -> dict | None:
    approved = shot.get("approvedAttemptId")
    return next((item for item in _attempts(shot) if approved and item.get("id") == approved
                 and item.get("status") == "completed"), None)


def final_equivalent(shot: dict) -> bool:
    """True when the preview render is the final render: every method but a 3D shot exported above draft quality."""
    if shot.get("productionMethod") != "animation_3d":
        return True
    scene3d = shot.get("scene3d") if isinstance(shot.get("scene3d"), dict) else {}
    return (scene3d.get("quality") or "draft") == "draft"


def full_quality(shot: dict, attempt: dict | None) -> bool:
    return bool(attempt) and (attempt.get("reviewStage") != "preview" or final_equivalent(shot))


def _index(shot: dict, attempt_id: Any) -> int | None:
    return next((index for index, item in enumerate(_attempts(shot)) if attempt_id and item.get("id") == attempt_id), None)


def _preview_current(shot: dict, attempt_id: Any) -> bool:
    """The reviewed take still exists, is usable, and no newer take that nobody reviewed came after it."""
    index = _index(shot, attempt_id)
    attempts = _attempts(shot)
    if index is None or not _usable(attempts[index]):
        return False
    return not any(_usable(item) and item.get("reviewStage") != "final" for item in attempts[index + 1:])


# Normalization ------------------------------------------------------------------------------------------------------

def _decision(value: dict, stage: str, digest: str, shot: dict) -> dict:
    status = value.get(stage) if value.get(stage) in STATUSES else "pending"
    if status != "pending" and value.get(f"{stage}Digest") != digest:
        status = "pending"
    if status != "pending" and stage == "preview" and not _preview_current(shot, value.get("previewAttemptId")):
        status = "pending"
    if status == "pending":
        return {stage: "pending"}
    decided = {stage: status, f"{stage}Digest": digest}
    if isinstance(value.get(f"{stage}At"), str):
        decided[f"{stage}At"] = value[f"{stage}At"]
    if value.get(f"{stage}By") in AUTHORS:
        decided[f"{stage}By"] = value[f"{stage}By"]
    if stage == "preview":
        decided["previewAttemptId"] = value["previewAttemptId"]
    return decided


def _note(value: Any) -> dict | None:
    if not isinstance(value, dict) or not isinstance(value.get("text"), str) or not value["text"].strip():
        return None
    note_id = value.get("id") if isinstance(value.get("id"), str) and _NOTE_ID.match(value["id"]) else f"note_{uuid.uuid4().hex[:16]}"
    return {"id": note_id, "at": value["at"] if isinstance(value.get("at"), str) else "",
            "stage": value["stage"] if value.get("stage") in STAGES else "final", "text": value["text"][:MAX_NOTE_CHARS],
            "by": value["by"] if value.get("by") in AUTHORS else "user"}


def _notes(value: Any) -> list[dict]:
    notes = [note for note in (_note(item) for item in value) if note] if isinstance(value, list) else []
    return notes[-MAX_NOTES:]


def _entry(value: dict, shot: dict) -> dict | None:
    digest = content_digest(shot)
    entry = {**_decision(value, "plan", digest, shot), **_decision(value, "preview", digest, shot),
             "notes": _notes(value.get("notes"))}
    if entry["plan"] == "pending" and entry["preview"] == "pending" and not entry["notes"]:
        return None
    return entry


def _entries(raw: dict, episode: dict) -> dict:
    shots = {shot.get("id"): shot for shot in episode.get("shots") or [] if isinstance(shot, dict)}
    stored = raw.get("shots") if isinstance(raw.get("shots"), dict) else {}
    entries = {}
    for shot_id, value in stored.items():
        entry = _entry(value, shots[shot_id]) if shot_id in shots and isinstance(value, dict) else None
        if entry:
            entries[shot_id] = entry
    return entries


def normalize_episode_review(episode: dict) -> None:
    """Repair ``episode.review`` in place: known mode, entries of existing shots only, stale decisions back to pending.
    The default (direct, nothing decided, no notes) is stored as no ``review`` at all."""
    raw = episode.get("review")
    if not isinstance(raw, dict):
        episode.pop("review", None)
        return
    mode = raw.get("mode") if raw.get("mode") in MODES else "direct"
    entries = _entries(raw, episode)
    if mode == "direct" and not entries:
        episode.pop("review", None)
        return
    episode["review"] = {"mode": mode, **({"updatedAt": raw["updatedAt"]} if isinstance(raw.get("updatedAt"), str) else {}),
                         "shots": entries}


def keep_stored_review(current: dict, payload: dict) -> None:
    """A whole-project save (``PUT /api/v1/series/{id}``) carries each episode's stored review: it is the server's,
    written only by the review endpoint, so a client copy that is older cannot undo a decision or a note."""
    stored = current.get("episodesById") if isinstance(current.get("episodesById"), dict) else {}
    sent = payload.get("episodesById") if isinstance(payload.get("episodesById"), dict) else {}
    for episode_id, episode in sent.items():
        if not isinstance(episode, dict):
            continue
        previous = stored.get(episode_id) if isinstance(stored.get(episode_id), dict) else {}
        if isinstance(previous.get("review"), dict):
            episode["review"] = copy.deepcopy(previous["review"])
        else:
            episode.pop("review", None)


# Reading ------------------------------------------------------------------------------------------------------------

def episode_mode(episode: dict) -> str:
    review = episode.get("review") if isinstance(episode.get("review"), dict) else {}
    return review.get("mode") if review.get("mode") in MODES else "direct"


def shot_entry(episode: dict, shot_id: str) -> dict:
    """A shot's review with its defaults (pending, pending, no notes)."""
    review = episode.get("review") if isinstance(episode.get("review"), dict) else {}
    entry = (review.get("shots") or {}).get(shot_id) if isinstance(review.get("shots"), dict) else None
    return {"plan": "pending", "preview": "pending", "notes": [], **copy.deepcopy(entry or {})}


def preview_ready(shot: dict, entry: dict) -> bool:
    """Preview mode: the approved take is the reviewed preview at full quality, or a final made after it."""
    take = approved_take(shot)
    if take is None or entry.get("preview") != "approved":
        return False
    reviewed = entry.get("previewAttemptId")
    if take.get("id") == reviewed:
        return full_quality(shot, take)
    reviewed_at, take_at = _index(shot, reviewed), _index(shot, take.get("id"))
    return take.get("reviewStage") == "final" and reviewed_at is not None and take_at is not None and take_at > reviewed_at


def classify(episode: dict, shot: dict) -> str:
    """The shot's place in the episode's mode: ready, or the step it waits for (see ``STEP_ORDER``)."""
    mode = episode_mode(episode)
    if mode == "direct":
        return "ready" if approved_take(shot) else "render"
    entry = shot_entry(episode, str(shot.get("id")))
    if entry["plan"] != "approved":
        return "changes" if entry["plan"] == "changes" else "approve_plan"
    if mode == "plan":
        return "ready" if approved_take(shot) else "render"
    if entry["preview"] == "approved":
        return "ready" if preview_ready(shot, entry) else "render_final"
    if entry["preview"] == "changes":
        return "changes"
    return "approve_previews" if latest_take(shot) else "render_previews"


def _ordered(episode: dict) -> list[dict]:
    shots = [shot for shot in episode.get("shots") or [] if isinstance(shot, dict)]
    return sorted(shots, key=lambda shot: (int(shot.get("order") or 0), str(shot.get("id") or "")))


def _counts(entries: list[dict], kinds: list[str]) -> dict:
    return {"total": len(entries), "ready": kinds.count("ready"),
            **{stage: {status: sum(1 for entry in entries if entry[stage] == status) for status in STATUSES}
               for stage in ("plan", "preview")}}


def _next_step(steps: list[dict], total: int) -> dict:
    """The user's next action; else the agent's changes; else the cut."""
    for wanted in (USER_STEPS, ("changes",)):
        found = next((step for step in steps if step["kind"] in wanted), None)
        if found:
            return found
    return {"kind": "assemble", "count": total}


def summary(episode: dict) -> dict:
    """Counts per stage, the steps left in production order and the user's next one."""
    shots = _ordered(episode)
    kinds = [classify(episode, shot) for shot in shots]
    entries = [shot_entry(episode, str(shot.get("id"))) for shot in shots]
    steps = [{"kind": kind, "count": kinds.count(kind)} for kind in STEP_ORDER if kinds.count(kind)]
    return {"mode": episode_mode(episode), "counts": _counts(entries, kinds), "steps": steps,
            "nextStep": _next_step(steps, len(shots))}


def shot_report(episode: dict, shot: dict) -> dict:
    entry = shot_entry(episode, str(shot.get("id")))
    latest = latest_take(shot)
    kind = classify(episode, shot)
    return {"shotId": shot.get("id"), "order": shot.get("order"), "sceneId": shot.get("sceneId"),
            "productionMethod": shot.get("productionMethod"), "plan": entry["plan"], "preview": entry["preview"],
            "previewAttemptId": entry.get("previewAttemptId"), "latestAttemptId": (latest or {}).get("id"),
            "latestStage": (latest or {}).get("reviewStage"), "approvedAttemptId": shot.get("approvedAttemptId"),
            "step": kind, "notes": entry["notes"]}


def report(series: dict, episode: dict) -> dict:
    """Everything an agent needs to act on the user's review: state, steps and every note."""
    return {"seriesId": series.get("id"), "episodeId": episode.get("id"), "revision": series.get("revision"),
            **summary(episode), "shots": [shot_report(episode, shot) for shot in _ordered(episode)]}


# Writing ------------------------------------------------------------------------------------------------------------

def _status(change: dict, key: str) -> str | None:
    if key not in change:
        return None
    if change[key] not in STATUSES:
        raise ReviewError(f"{key} must be one of {', '.join(STATUSES)}")
    return change[key]


def _decide(entry: dict, stage: str, status: str, shot: dict, now: str, by: str = "user") -> None:
    for key in (f"{stage}At", f"{stage}Digest", f"{stage}By", *(("previewAttemptId",) if stage == "preview" else ())):
        entry.pop(key, None)
    entry[stage] = status
    if status != "pending":
        entry.update({f"{stage}At": now, f"{stage}Digest": content_digest(shot), f"{stage}By": by})


def _set_preview(entry: dict, status: str, shot: dict, attempt_id: Any, now: str, by: str = "user") -> None:
    if status != "pending":
        take = next((item for item in _attempts(shot) if item.get("id") == attempt_id), None) if attempt_id else latest_take(shot)
        if take is None or not _usable(take):
            raise ReviewError(f"Shot {shot.get('order')} has no completed take to review yet; render its preview first")
        if not _preview_current(shot, take.get("id")):
            raise ReviewError(f"Shot {shot.get('order')} has a newer take than {take.get('id')}; review the newest one")
    _decide(entry, "preview", status, shot, now, by)
    if status != "pending":
        entry["previewAttemptId"] = take["id"]
    if status == "approved" and entry["plan"] != "approved":
        # A good preview of a shot is a good plan of it.
        _decide(entry, "plan", "approved", shot, now, by)


def default_stage(episode: dict, entry: dict) -> str:
    mode = episode_mode(episode)
    if mode == "direct":
        return "final"
    return "preview" if mode == "preview" and entry["plan"] == "approved" else "plan"


def _check_note(raw: Any) -> str | None:
    """Validate a note change; returns its id (None for a new note)."""
    if not isinstance(raw, dict) or set(raw) - NOTE_KEYS or not isinstance(raw.get("text"), str):
        raise ReviewError("note must be {text, id?, stage?, by?}")
    if len(raw["text"]) > MAX_NOTE_CHARS:
        raise ReviewError(f"A note is limited to {MAX_NOTE_CHARS} characters")
    if raw.get("stage") not in (None, *STAGES):
        raise ReviewError(f"note.stage must be one of {', '.join(STAGES)}")
    if raw.get("by") not in (None, *AUTHORS):
        raise ReviewError(f"note.by must be one of {', '.join(AUTHORS)}")
    note_id = raw.get("id")
    if note_id is not None and (not isinstance(note_id, str) or not _NOTE_ID.match(note_id)):
        raise ReviewError("note.id must be a short id of letters, digits, _ and -")
    return note_id


def _write_note(episode: dict, entry: dict, raw: Any, now: str, by: str = "user") -> str | None:
    """Add or update (same id) a note; empty text removes it. Returns the id written."""
    note_id = _check_note(raw)
    existing = next((note for note in entry["notes"] if note_id and note["id"] == note_id), None)
    if not raw["text"].strip():
        entry["notes"] = [note for note in entry["notes"] if note is not existing]
        return None
    if existing is None:
        if len(entry["notes"]) >= MAX_NOTES:
            raise ReviewError(f"A shot keeps at most {MAX_NOTES} notes; remove old ones first")
        existing = {"id": note_id or f"note_{uuid.uuid4().hex[:16]}"}
        entry["notes"].append(existing)
    existing.update(at=now, text=raw["text"], stage=raw.get("stage") or existing.get("stage") or default_stage(episode, entry),
                    by=raw.get("by") or existing.get("by") or by)
    return existing["id"]


def _apply_shot(episode: dict, shots: dict[str, dict], change: Any, now: str, by: str) -> tuple[str, str | None]:
    if not isinstance(change, dict) or set(change) - CHANGE_KEYS:
        raise ReviewError(f"Each shot change takes {', '.join(sorted(CHANGE_KEYS))}")
    shot = shots.get(change.get("shotId")) if isinstance(change.get("shotId"), str) else None
    if shot is None:
        raise ReviewError(f"Series shot {change.get('shotId')} not found", status=404, code="not_found")
    entry = shot_entry(episode, shot["id"])
    plan, preview = _status(change, "plan"), _status(change, "preview")
    if plan is not None:
        _decide(entry, "plan", plan, shot, now, by)
    if preview is not None:
        _set_preview(entry, preview, shot, change.get("attemptId"), now, by)
    if change.get("removeNoteId"):
        entry["notes"] = [note for note in entry["notes"] if note["id"] != change["removeNoteId"]]
    note_id = _write_note(episode, entry, change["note"], now, by) if "note" in change else None
    review = episode.setdefault("review", {"mode": episode_mode(episode), "shots": {}})
    review.setdefault("shots", {})[shot["id"]] = entry
    return shot["id"], note_id


def _check_change(body: Any) -> tuple[str | None, list]:
    if not isinstance(body, dict):
        raise ReviewError("The review change must be an object")
    mode = body.get("mode")
    changes = body.get("shots") if body.get("shots") is not None else []
    if mode is not None and mode not in MODES:
        raise ReviewError(f"mode must be one of {', '.join(MODES)}")
    if not isinstance(changes, list) or len(changes) > MAX_CHANGES:
        raise ReviewError(f"shots must be a list of at most {MAX_CHANGES} changes")
    if mode is None and not changes:
        raise ReviewError("Send a mode or at least one shot change")
    return mode, changes


def apply_review_change(episode: dict, body: dict, *, now: str, by: str = "user") -> dict[str, str]:
    """Apply ``{mode?, shots?: [{shotId, plan?, preview?, attemptId?, note?, removeNoteId?}]}`` to ``episode`` in place
    (validated; nothing is applied when a change is refused). ``by`` is who decides (``AUTHORS``): each decision records
    it as ``planBy`` / ``previewBy``, and it is a note's author unless the note says otherwise. Returns the id of each
    note written, by shot id."""
    by = by if by in AUTHORS else "user"
    mode, changes = _check_change(body)
    working = copy.deepcopy(episode)
    shots = {str(shot.get("id")): shot for shot in working.get("shots") or [] if isinstance(shot, dict)}
    review = working.setdefault("review", {"mode": episode_mode(episode), "shots": {}})
    review["mode"] = mode or review.get("mode") or "direct"
    note_ids = {}
    for change in changes:
        shot_id, note_id = _apply_shot(working, shots, change, now, by)
        if note_id:
            note_ids[shot_id] = note_id
    working["review"]["updatedAt"] = now
    normalize_episode_review(working)
    episode.clear()
    episode.update(working)
    return note_ids


def stored_review(episode: dict) -> dict:
    review = episode.get("review") if isinstance(episode.get("review"), dict) else None
    return copy.deepcopy(review) if review else {"mode": "direct", "shots": {}}
