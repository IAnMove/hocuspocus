"""Idempotent music generation submission (reservation before inference).

This module does not import FastAPI, WanGP or launch. It reserves command,
generation, task and candidate IDs, verifies Story destinations by ID, and
deduplicates by idempotency key. Starting a GPU/provider worker is the
caller's optional ``after_persist`` hook.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .minimax_music_service import ALLOWED_MODELS, COVER_MODELS
from .story_library import read_story_library
from .task_manager import TaskRegistry


SCHEMA_NAME = "hocuspocus.music-submission"
SCHEMA_VERSION = 1
STORE_DIRNAME = "music-submissions"
LOCAL_MODELS = frozenset({"ace_step_v1_5_xl_sft_lm_4b", "minimax_music3"})
REMOTE_MODELS = frozenset(ALLOWED_MODELS)
INTENTS = frozenset({"retransmit", "retry", "new_version"})
_STORE_LOCK = threading.RLock()


class MusicSubmissionError(ValueError):
    def __init__(self, message: str, status_code: int = 400, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = dict(details or {})


class MusicSubmissionConflict(MusicSubmissionError):
    def __init__(self, message: str = "Idempotency key reused with a different spec"):
        super().__init__(message, status_code=409)


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _portable_folder(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None
    name = os.path.basename(text.replace("\\", "/"))
    if not name or name in {".", ".."} or os.path.isabs(name) or "/" in name or "\\" in name:
        raise MusicSubmissionError("output_folder must be a relative folder name, never a path")
    return name


def classify_music_route(model: str | None) -> str:
    token = _clean(model) or "music-3.0"
    if token in LOCAL_MODELS or token.startswith("ace_step"):
        return "local"
    if token in REMOTE_MODELS:
        return "remote_minimax"
    raise MusicSubmissionError(f"Unsupported music model: {token}")


def _stable_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def spec_snapshot(request: Mapping[str, Any]) -> dict[str, Any]:
    from .music_model_contract import MusicModelError, freeze_music_spec

    try:
        frozen = freeze_music_spec(request)
    except MusicModelError as exc:
        raise MusicSubmissionError(str(exc), exc.status_code, exc.details) from exc
    frozen["output_folder"] = _portable_folder(
        request.get("output_folder") or request.get("workspace"),
    )
    frozen["workspace_id"] = _clean(request.get("workspace_id"))
    frozen["intent"] = _intent(request)
    return frozen


def spec_hash(spec: Mapping[str, Any]) -> str:
    return hashlib.sha256(_stable_dump(dict(spec)).encode("utf-8")).hexdigest()


def _token_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _story_row_by_id(items: Any, token: str) -> dict[str, Any] | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and _clean(item.get("id")) == token:
            return item
    return None


def verify_story_destination(
    workspace_dir: str,
    spec: Mapping[str, Any],
) -> None:
    """Require Story rows by ID. Never resolve a project or cue by title."""
    project_id = spec.get("project_id")
    if not project_id:
        return
    library = read_story_library(workspace_dir)
    expected = spec.get("library_revision")
    if expected not in (None, ""):
        try:
            wanted = int(expected)
        except (TypeError, ValueError) as exc:
            raise MusicSubmissionError("library_revision must be an integer") from exc
        if wanted != int(library.get("revision") or 0):
            raise MusicSubmissionConflict(
                f"Story library revision conflict: expected {wanted}, current {library.get('revision')}",
            )
    project = library.get("projects", {}).get(project_id)
    if not isinstance(project, dict):
        raise MusicSubmissionError(f"Story project {project_id!r} was not found", 404)
    cue_id = spec.get("cue_id")
    if not cue_id:
        return
    cue = _story_row_by_id((project.get("music") or {}).get("cues"), cue_id)
    if cue is None:
        raise MusicSubmissionError(f"Story cue {cue_id!r} was not found", 404)
    candidate_id = spec.get("candidate_id")
    if candidate_id and _story_row_by_id(cue.get("candidates"), candidate_id) is None:
        raise MusicSubmissionError(f"Story song candidate {candidate_id!r} was not found", 404)


def _validate_spec(spec: dict[str, Any]) -> str:
    if not spec.get("output_folder"):
        raise MusicSubmissionError("output_folder is required")
    route = classify_music_route(spec.get("model"))
    if not spec.get("prompt"):
        raise MusicSubmissionError("A music style prompt is required")
    model = spec["model"]
    if model not in COVER_MODELS and not spec["instrumental"] and not spec["lyrics"]:
        raise MusicSubmissionError("Lyrics are required for a vocal song")
    if model in COVER_MODELS and not spec.get("reference_audio_filename"):
        raise MusicSubmissionError("Upload a valid reference song before generating a cover")
    return route


class MusicSubmissionStore:
    """One JSON document per idempotency key with atomic replace."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root) / STORE_DIRNAME
        self._lock = threading.RLock()

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]
        return self.root / f"{digest}.json"

    def load(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return dict(value) if isinstance(value, dict) else None

    def persist(self, record: Mapping[str, Any]) -> dict[str, Any]:
        key = str(record["idempotency_key"])
        path = self._path(key)
        payload = json.loads(json.dumps(record, ensure_ascii=False))
        with _STORE_LOCK:
            existing = self.load(key)
            if existing:
                if existing.get("spec_hash") != payload.get("spec_hash"):
                    raise MusicSubmissionConflict()
                return existing
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                with open(temporary, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            except Exception:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
            return payload

    def get_by_generation_id(self, generation_id: str) -> dict[str, Any] | None:
        token = str(generation_id or "").strip()
        if not token or not self.root.is_dir():
            return None
        for path in sorted(self.root.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and str(value.get("generation_id") or "") == token:
                return dict(value)
        return None

    def replace(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Overwrite an existing reservation with the same spec hash."""
        key = str(record["idempotency_key"])
        path = self._path(key)
        payload = json.loads(json.dumps(record, ensure_ascii=False))
        with _STORE_LOCK:
            existing = self.load(key)
            if existing is None:
                raise MusicSubmissionError(f"Unknown music reservation {key}", 404)
            if existing.get("spec_hash") != payload.get("spec_hash"):
                raise MusicSubmissionConflict()
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            try:
                with open(temporary, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            except Exception:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
            return payload


def _intent(request: Mapping[str, Any]) -> str:
    raw = (_clean(request.get("intent")) or "retransmit").casefold()
    if request.get("retry") is True:
        raw = "retry"
    if request.get("new_version") is True:
        raw = "new_version"
    if raw not in INTENTS:
        raise MusicSubmissionError(f"Unsupported music submission intent: {raw}")
    return raw


def submit_music_generation(
    *,
    workspace_dir: str,
    request: Mapping[str, Any],
    task_registry: TaskRegistry | None = None,
    after_persist: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Reserve durable IDs and return 202-shaped state without running inference."""
    from .music_model_contract import MusicModelError, assert_enqueue_guard

    spec = spec_snapshot(request)
    try:
        assert_enqueue_guard(spec)
    except MusicModelError as exc:
        raise MusicSubmissionError(str(exc), exc.status_code, exc.details) from exc
    route = _validate_spec(spec)
    intent = spec["intent"]
    digest = spec_hash(spec)
    key = _clean(request.get("idempotency_key") or request.get("idempotencyKey"))
    if not key:
        # No key: a new attempt. Replay only happens when the caller repeats a key.
        key = _token_id("idem")
    store = MusicSubmissionStore(workspace_dir)
    existing = store.load(key)
    if existing:
        if existing.get("spec_hash") != digest:
            raise MusicSubmissionConflict()
        existing = dict(existing)
        existing["replay"] = True
        return existing
    verify_story_destination(workspace_dir, spec)
    job_id = _token_id("minimax-music") if route == "remote_minimax" else _token_id("local-music")
    task_id = _clean(request.get("task_id")) or f"task-{job_id}"
    generation_id = _clean(request.get("generation_id")) or _token_id("gen")
    candidate_id = spec.get("candidate_id") or _token_id("song")
    command_id = _clean(request.get("command_id") or request.get("commandId")) or _token_id("cmd")
    parent_generation_id = _clean(request.get("parent_generation_id")) if intent == "retry" else None
    record = {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "idempotency_key": key,
        "spec_hash": digest,
        "spec": spec,
        "intent": intent,
        "route": route,
        "command_id": command_id,
        "generation_id": generation_id,
        "task_id": task_id,
        "job_id": job_id,
        "candidate_id": candidate_id,
        "parent_generation_id": parent_generation_id,
        "status": "queued",
        "replay": False,
        "created_at": _now_iso(),
        "start_error": None,
    }
    stored = store.persist(record)
    if stored.get("job_id") != record["job_id"]:
        stored = dict(stored)
        stored["replay"] = True
        return stored
    registry = task_registry or TaskRegistry(workspace_dir, interrupt_stale=False)
    registry.create(
        id=task_id,
        kind="music",
        workflow="generate_story_song",
        status="queued",
        title="Story song",
        workspace=spec["output_folder"],
        project_id=spec.get("project_id") or "",
        backend_job_id=job_id,
        metadata={
            "generation_id": generation_id,
            "candidate_id": candidate_id,
            "command_id": command_id,
            "idempotency_key": key,
        },
    )
    if after_persist is not None:
        try:
            after_persist(stored)
        except Exception as exc:
            stored = dict(stored)
            stored["start_error"] = str(exc)[:500]
            stored["status"] = "queued"
    stored["replay"] = False
    return stored


def public_music_job(record: Mapping[str, Any]) -> dict[str, Any]:
    spec = record.get("spec") if isinstance(record.get("spec"), Mapping) else {}
    return {
        "jobId": record.get("job_id"),
        "taskId": record.get("task_id"),
        "rootTaskId": record.get("task_id"),
        "workspace": spec.get("output_folder"),
        "status": record.get("status") or "queued",
        "phase": record.get("status") or "queued",
        "message": "Music generation accepted",
        "current": 0,
        "total": spec.get("count") or 1,
        "progress": 0,
        "provider": "local" if record.get("route") == "local" else "minimax",
        "model": spec.get("model"),
        "candidates": [],
        "error": record.get("start_error"),
        "generationId": record.get("generation_id"),
        "commandId": record.get("command_id"),
        "candidateId": record.get("candidate_id"),
        "idempotencyKey": record.get("idempotency_key"),
        "replay": bool(record.get("replay")),
    }
