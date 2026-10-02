"""Bind a production to a Story or an episode before expensive work starts.

The link file is the relation. Story and series libraries stay authoritative
for the project. Media stays where the producer already wrote it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any

import fcntl


LINK_FILENAME = ".production-project-links-v1.json"
REVIEW_EVENT = "hocuspocus:production-shots-open"
FORMATS = frozenset({"music_video", "trailer", "quick_video", "full_story"})
ORIGINS = frozenset({"mcp", "wizard", "ui"})
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
_WORKSPACE = re.compile(r"^(?:default|[A-Za-z0-9][A-Za-z0-9_-]{0,158})$")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class LinkError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def created_story_id(workspace_id: str, intent_id: str) -> str:
    return "story" + _digest(f"{workspace_id}:{intent_id}")


def production_id_for(workspace_id: str, intent_id: str, execution: int) -> str:
    return "p" + _digest(f"{workspace_id}:{intent_id}:{execution}")


def resolve_production_project(workspace_dir: str, request: MappingRequest, *, create_stub: bool = True) -> dict[str, Any]:
    """Validate or create the project, then persist the production relation."""
    spec = _request(request)
    with _exclusive(workspace_dir):
        return _public(_resolve(workspace_dir, spec, create_stub=create_stub))


def link_existing_production(workspace_dir: str, request: MappingRequest) -> dict[str, Any]:
    """Attach one recognizable production to a project that already exists.

    The production file, its takes and any series record stay as they were.
    A repeated call for the same pair does not add another row.
    """
    spec = _existing_request(request)
    from services.production_work_catalog import find_work

    found = find_work(workspace_dir, spec["workspace_id"], spec["production_id"])
    if found is None:
        raise LinkError("not_found", "Production not found")
    with _exclusive(workspace_dir):
        record, reused = _store_existing_link(workspace_dir, spec, found)
    public = _public(record)
    public["reused"] = reused
    public["applied"] = True
    return public


def bind_producer(workspace_dir: str, request: MappingRequest) -> dict[str, Any]:
    """Attach this producer id to a project before generation starts.

    The caller's production id stays the id. A repeat returns the same project
    and does not create another Story.
    """
    spec = _producer_spec(request)
    with _exclusive(workspace_dir):
        return _bind_producer(workspace_dir, spec)


def note_production_status(workspace_dir: str, production_id: str, status: str) -> dict[str, Any]:
    token = _token(production_id, "invalid_request", "production_id is required")
    if not isinstance(status, str) or not status.strip() or len(status) > 40:
        raise LinkError("invalid_request", "status is required")
    with _exclusive(workspace_dir):
        store = _read(workspace_dir)
        found = _link_for_production(store, token)
        if found is None:
            raise LinkError("invalid_project", "No linked production with this id")
        _intent, record = found
        record["status"] = status.strip()
        record["updated_at"] = _now()
        _write(workspace_dir, store)
        return _public(record)


def refresh_link_status(workspace_dir: str) -> None:
    """Copy the producer file status onto the link. Missing files stay as stored.

    Episode status lives on the link (``note_production_status``). A leftover
    music-shaped ``.production.json`` is not the series render, so it must not
    overwrite running or completed.
    """
    with _exclusive(workspace_dir):
        store = _read(workspace_dir)
        changed = False
        for record in store["links"].values():
            if _episode_project(record.get("project")):
                continue
            status = _file_status(workspace_dir, str(record.get("production_id") or ""))
            if status and status != record.get("status"):
                record["status"] = status
                record["updated_at"] = _now()
                changed = True
        if changed:
            _write(workspace_dir, store)


def read_link_store(workspace_dir: str) -> dict[str, Any]:
    with _exclusive(workspace_dir):
        return _read(workspace_dir)


def _resolve(workspace_dir: str, spec: dict[str, Any], *, create_stub: bool = True) -> dict[str, Any]:
    # Episode media lives in the series library. A music-shaped stub would be
    # pending, and refresh_link_status would copy that over running/completed.
    project = spec.get("project")
    if isinstance(project, dict) and project.get("kind") == "episode":
        create_stub = False
    store = _read(workspace_dir)
    current = store["links"].get(spec["intent_id"])
    if isinstance(current, dict) and not spec["new_execution"]:
        if spec.get("production_id") and spec["production_id"] != current["production_id"]:
            raise LinkError("invalid_production", "intent is already linked to another production")
        _same_project(workspace_dir, spec, current)
        return _finish_existing(workspace_dir, current, create_stub)
    execution = _execution(current, spec["new_execution"])
    production_id = spec.get("production_id") or production_id_for(spec["workspace_id"], spec["intent_id"], execution)
    found = _link_for_production(store, production_id)
    if found is not None:
        if spec["new_execution"]:
            raise LinkError("invalid_production", "Production already belongs to another execution")
        _intent, record = found
        _same_project(workspace_dir, spec, record)
        return _finish_existing(workspace_dir, record, create_stub)
    project, created, seed = _project(workspace_dir, spec, current if isinstance(current, dict) else None)
    previous = current.get("production_ids") if isinstance(current, dict) else []
    identifiers = [item for item in previous if isinstance(item, str)]
    if production_id not in identifiers:
        identifiers.append(production_id)
    record = _record(spec, project, created, seed, production_id, identifiers, execution)
    store["links"][spec["intent_id"]] = record
    _write(workspace_dir, store)
    try:
        _reconcile(workspace_dir, record)
        if create_stub:
            _ensure_stub(workspace_dir, record)
    except OSError as error:
        raise LinkError("partial_write", "The link is stored; retry to finish the production file") from error
    return record


def _finish_existing(workspace_dir: str, record: dict[str, Any], create_stub: bool) -> dict[str, Any]:
    try:
        _reconcile(workspace_dir, record)
        if create_stub:
            _ensure_stub(workspace_dir, record)
    except OSError as error:
        raise LinkError("partial_write", "The link is stored; retry to finish the production file") from error
    return record


def _project(
    workspace_dir: str,
    spec: dict[str, Any],
    current: dict[str, Any] | None,
) -> tuple[dict[str, str], bool, dict[str, Any] | None]:
    explicit = spec.get("project")
    if explicit is not None:
        return _explicit_project(workspace_dir, spec, explicit), False, None
    if isinstance(current, dict) and isinstance(current.get("project"), dict):
        project = {"kind": str(current["project"]["kind"]), "id": str(current["project"]["id"])}
        created = current.get("story_created") is True
        seed = current.get("story_seed") if isinstance(current.get("story_seed"), dict) else None
        return project, created, seed
    return _create_story(workspace_dir, spec)


def _same_project(workspace_dir: str, spec: dict[str, Any], current: dict[str, Any]) -> None:
    explicit = spec.get("project")
    if explicit is None:
        return
    checked = _explicit_project(workspace_dir, spec, explicit)
    stored = current.get("project") if isinstance(current.get("project"), dict) else {}
    if checked != {"kind": stored.get("kind"), "id": stored.get("id")}:
        raise LinkError("invalid_project", "intent is already linked to another project")


def _explicit_project(workspace_dir: str, spec: dict[str, Any], explicit: dict[str, str]) -> dict[str, str]:
    if explicit["kind"] == "episode":
        _require_episode(workspace_dir, spec["workspace_id"], explicit["id"])
        return explicit
    if not _story_exists(workspace_dir, explicit["id"]):
        raise LinkError("invalid_project", "Story project was not found")
    return explicit


def _create_story(workspace_dir: str, spec: dict[str, Any]) -> tuple[dict[str, str], bool, dict[str, Any]]:
    project_id = created_story_id(spec["workspace_id"], spec["intent_id"])
    seed = _story_seed(project_id, spec, [spec.get("production_id") or production_id_for(spec["workspace_id"], spec["intent_id"], 1)])
    if not _story_exists(workspace_dir, project_id):
        _upsert_story(workspace_dir, project_id, seed)
    return {"kind": "story", "id": project_id}, True, seed


def _reconcile(workspace_dir: str, record: dict[str, Any]) -> None:
    project = record.get("project") if isinstance(record.get("project"), dict) else {}
    if project.get("kind") != "story":
        return
    project_id = str(project.get("id") or "")
    seed = record.get("story_seed") if isinstance(record.get("story_seed"), dict) else None
    if record.get("story_created") is True and seed is not None and not _story_exists(workspace_dir, project_id):
        _upsert_story(workspace_dir, project_id, seed)
    if _story_exists(workspace_dir, project_id):
        _attach_productions(workspace_dir, project_id, record)


def _attach_productions(workspace_dir: str, project_id: str, record: dict[str, Any]) -> None:
    from services.story_library import StoryLibraryRevisionConflict, patch_story_project, read_story_library

    for _attempt in range(4):
        library = read_story_library(workspace_dir)
        project = library["projects"].get(project_id)
        if not isinstance(project, dict):
            return
        present = {
            str(item.get("id"))
            for item in project.get("productions") or []
            if isinstance(item, dict) and item.get("id")
        }
        missing = [item for item in record.get("production_ids") or [] if item not in present]
        if not missing:
            return
        entries = list(project.get("productions") or [])
        title = str(record.get("title") or project_id)
        for production_id in missing:
            entries.append(_production_entry(production_id, title, record.get("format"), project_id, record["workspace_id"]))
        updated = dict(project)
        updated["productions"] = entries
        updated["updatedAt"] = _now()
        try:
            patch_story_project(
                workspace_dir,
                project_id,
                updated,
                base_revision=int(library["revision"]),
                make_active=False,
            )
            return
        except StoryLibraryRevisionConflict:
            continue
    raise LinkError("revision_conflict", "Story library changed while linking")


def _ensure_stub(workspace_dir: str, record: dict[str, Any]) -> None:
    if _episode_project(record.get("project")):
        return
    production_id = str(record["production_id"])
    path = os.path.join(workspace_dir, f"{production_id}.production.json")
    current = _read_json(path)
    if current is None and os.path.exists(path):
        raise LinkError("invalid_production", "Production file is not a JSON object")
    if current is None:
        _replace_json(path, _stub_body(record))
        return
    latest = _read_json(path) or current
    if _stamp_identity(latest, record):
        _replace_json(path, latest)


def _stub_body(record: dict[str, Any]) -> dict[str, Any]:
    spec = {"title": record["title"]} if record.get("title") else {}
    state: dict[str, Any] = {
        "status": "pending",
        "project": dict(record["project"]),
        "intent_id": record["intent_id"],
        "origin": record["origin"],
        "spec": spec,
    }
    if record.get("format"):
        state["format"] = record["format"]
    return state


def _stamp_identity(state: dict[str, Any], record: dict[str, Any]) -> bool:
    """Copy missing identity keys onto a live producer file. Do not rewrite when they are already present."""
    changed = False
    if "project" not in state:
        state["project"] = dict(record["project"])
        changed = True
    if "intent_id" not in state:
        state["intent_id"] = record["intent_id"]
        changed = True
    if "origin" not in state:
        state["origin"] = record["origin"]
        changed = True
    if record.get("format") and "format" not in state:
        state["format"] = record["format"]
        changed = True
    spec = state.get("spec") if isinstance(state.get("spec"), dict) else {}
    if record.get("title") and "title" not in spec:
        state["spec"] = {**spec, "title": record["title"]}
        changed = True
    return changed


def _record(
    spec: dict[str, Any],
    project: dict[str, str],
    created: bool,
    seed: dict[str, Any] | None,
    production_id: str,
    identifiers: list[str],
    execution: int,
) -> dict[str, Any]:
    now = _now()
    if isinstance(seed, dict):
        seed = dict(seed)
        seed["productions"] = [
            _production_entry(item, spec["title"], spec.get("format"), project["id"], spec["workspace_id"])
            for item in identifiers
        ]
    return {
        "intent_id": spec["intent_id"],
        "workspace_id": spec["workspace_id"],
        "origin": spec["origin"],
        "format": spec.get("format"),
        "title": spec["title"],
        "project": project,
        "production_id": production_id,
        "production_ids": identifiers,
        "status": "pending",
        "story_created": created,
        "story_seed": seed,
        "execution": execution,
        "created_at": now,
        "updated_at": now,
    }


_PRODUCTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,239}$")


def _existing_request(request: MappingRequest) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise LinkError("invalid_request", "request must be an object")
    production_id = request.get("production_id")
    if not isinstance(production_id, str):
        raise LinkError("invalid_request", "production_id must be a string")
    production_id = production_id.strip()
    if not _PRODUCTION_ID.fullmatch(production_id) or ".." in production_id:
        raise LinkError("invalid_request", "production_id is required")
    project = _project_request(request)
    if project is None:
        raise LinkError("invalid_project", "An existing project is required")
    return {
        "workspace_id": _workspace_id(request),
        "production_id": production_id,
        "project": project,
    }


def _store_existing_link(
    workspace_dir: str,
    spec: dict[str, Any],
    found: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    project = _explicit_project(workspace_dir, spec, spec["project"])
    current_project = found.get("project") if isinstance(found.get("project"), dict) else None
    if current_project and {"kind": current_project.get("kind"), "id": current_project.get("id")} != project:
        raise LinkError("invalid_project", "production is already linked to another project")
    store = _read(workspace_dir)
    current = _link_for_production(store, spec["production_id"])
    if current is not None:
        _intent, record = current
        stored = record.get("project") if isinstance(record.get("project"), dict) else {}
        if {"kind": stored.get("kind"), "id": stored.get("id")} != project:
            raise LinkError("invalid_project", "production is already linked to another project")
        if project["kind"] == "story":
            _attach_productions(workspace_dir, project["id"], record)
        return record, True
    record = _existing_record(spec, found, project)
    store["links"][record["intent_id"]] = record
    _write(workspace_dir, store)
    if project["kind"] == "story":
        _attach_productions(workspace_dir, project["id"], record)
    return record, False


def _existing_record(spec: dict[str, Any], found: dict[str, Any], project: dict[str, str]) -> dict[str, Any]:
    now = _now()
    origin = str(found.get("origin") or "file")
    return {
        "intent_id": f"link-{_digest(spec['workspace_id'] + ':' + spec['production_id'])}",
        "workspace_id": spec["workspace_id"],
        "origin": origin,
        "format": found.get("format") if isinstance(found.get("format"), str) else None,
        "title": str(found.get("title") or spec["production_id"]),
        "project": project,
        "production_id": spec["production_id"],
        "production_ids": [spec["production_id"]],
        "status": str(found.get("status") or "unknown"),
        "story_created": False,
        "story_seed": None,
        "execution": 1,
        "created_at": now,
        "updated_at": now,
    }


def _producer_spec(request: MappingRequest) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise LinkError("invalid_request", "request must be an object")
    production_id = request.get("production_id")
    if not isinstance(production_id, str):
        raise LinkError("invalid_request", "production_id must be a string")
    production_id = production_id.strip()
    if not _PRODUCTION_ID.fullmatch(production_id) or ".." in production_id:
        raise LinkError("invalid_request", "production_id is required")
    workspace_id = _workspace_id(request)
    origin = str(request.get("origin") or "").strip()
    if origin not in ORIGINS:
        raise LinkError("invalid_request", "origin must be mcp, wizard, or ui")
    project = _project_request(request)
    form = _format(request, project)
    write_stub = request.get("write_stub", True)
    if not isinstance(write_stub, bool):
        raise LinkError("invalid_request", "write_stub must be boolean")
    title = str(request.get("title") or "").strip()[:200] or _default_title(form or "quick_video", project)
    return {
        "workspace_id": workspace_id,
        "origin": origin,
        "intent_id": "b" + _digest(f"{workspace_id}:{production_id}"),
        "new_execution": False,
        "project": project,
        "format": form or None,
        "title": title,
        "idea": "",
        "production_id": production_id,
        "write_stub": write_stub,
    }


def _bind_producer(workspace_dir: str, spec: dict[str, Any]) -> dict[str, Any]:
    store = _read(workspace_dir)
    found = _link_for_production(store, spec["production_id"])
    if found is not None:
        return _reuse_producer(workspace_dir, spec, found)
    if spec["project"] is not None:
        project, created, seed = _explicit_project(workspace_dir, spec, spec["project"]), False, None
    else:
        project, created, seed = _create_story_for(workspace_dir, spec, spec["production_id"])
    record = _record(spec, project, created, seed, spec["production_id"], [spec["production_id"]], 1)
    store["links"][spec["intent_id"]] = record
    _write(workspace_dir, store)
    try:
        _reconcile(workspace_dir, record)
        if spec["write_stub"]:
            _ensure_stub(workspace_dir, record)
    except OSError as error:
        raise LinkError("partial_write", "The link is stored; retry to finish the production file") from error
    public = _public(record)
    public["reused"] = False
    public["applied"] = True
    return public


def _reuse_producer(workspace_dir: str, spec: dict[str, Any], found: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    _intent, record = found
    stored = record.get("project") if isinstance(record.get("project"), dict) else {}
    if spec["project"] is not None:
        checked = _explicit_project(workspace_dir, spec, spec["project"])
        if checked != {"kind": stored.get("kind"), "id": stored.get("id")}:
            raise LinkError("invalid_project", "This production is already linked to another project")
    if stored.get("kind") == "episode" and spec.get("format") not in {None, "full_story"}:
        raise LinkError("invalid_project", "This production belongs to a series episode")
    try:
        _reconcile(workspace_dir, record)
        if spec["write_stub"]:
            _ensure_stub(workspace_dir, record)
    except OSError as error:
        raise LinkError("partial_write", "The link is stored; retry to finish the production file") from error
    public = _public(record)
    public["reused"] = True
    public["applied"] = True
    return public


def _create_story_for(
    workspace_dir: str, spec: dict[str, Any], production_id: str,
) -> tuple[dict[str, str], bool, dict[str, Any]]:
    project_id = created_story_id(spec["workspace_id"], spec["intent_id"])
    seed = _story_seed(project_id, spec, [production_id])
    if not _story_exists(workspace_dir, project_id):
        _upsert_story(workspace_dir, project_id, seed)
    return {"kind": "story", "id": project_id}, True, seed


def _request(request: MappingRequest) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise LinkError("invalid_request", "request must be an object")
    project = _project_request(request)
    form = _format(request, project)
    title = str(request.get("title") or "").strip()[:200] or _default_title(form, project)
    return {
        "production_id": _requested_production_id(request),
        "workspace_id": _workspace_id(request),
        "origin": _origin(request),
        "intent_id": _token(request.get("intent_id"), "invalid_request", "intent_id is required"),
        "new_execution": _new_execution(request),
        "project": project,
        "format": form or None,
        "title": title,
        "idea": str(request.get("idea") or "").strip()[:2000],
    }


def _requested_production_id(request: dict[str, Any]) -> str | None:
    value = request.get("production_id")
    if value is None:
        return None
    if not isinstance(value, str) or not _PRODUCTION_ID.fullmatch(value) or ".." in value:
        raise LinkError("invalid_production", "Invalid production_id")
    if request.get("new_execution") is True:
        raise LinkError("invalid_production", "A supplied production_id identifies one execution")
    return value


def _workspace_id(request: dict[str, Any]) -> str:
    workspace_id = _token(request.get("workspace_id") or request.get("workspace"), "invalid_request", "workspace is required")
    if not _WORKSPACE.fullmatch(workspace_id):
        raise LinkError("invalid_request", "workspace is invalid")
    return workspace_id


def _origin(request: dict[str, Any]) -> str:
    origin = str(request.get("origin") or "").strip()
    if origin not in ORIGINS:
        raise LinkError("invalid_request", "origin must be mcp, wizard, or ui")
    return origin


def _new_execution(request: dict[str, Any]) -> bool:
    value = request.get("new_execution", False)
    if not isinstance(value, bool):
        raise LinkError("invalid_request", "new_execution must be boolean")
    return value


def _project_request(request: dict[str, Any]) -> dict[str, str] | None:
    return _with_episode(_explicit(request), str(request.get("episode_id") or "").strip())


def _with_episode(project: dict[str, str] | None, episode_id: str) -> dict[str, str] | None:
    if not episode_id:
        return project
    if project is None:
        return {"kind": "episode", "id": _token(episode_id, "invalid_project", "episode_id is invalid")}
    if project["kind"] != "episode" or project["id"] != episode_id:
        raise LinkError("invalid_project", "episode_id does not match the explicit project")
    return project


def _format(request: dict[str, Any], project: dict[str, str] | None) -> str:
    form = str(request.get("format") or "").strip()
    if form in FORMATS:
        return form
    if project is None:
        raise LinkError("invalid_request", "format is required for a work without a project")
    return ""


def _explicit(request: dict[str, Any]) -> dict[str, str] | None:
    value = request.get("project")
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise LinkError("invalid_project", "project must be an object")
    kind = str(value.get("kind") or "").strip()
    identifier = _token(value.get("id"), "invalid_project", "project.id is required")
    if kind not in {"story", "episode"}:
        raise LinkError("invalid_project", "project.kind must be story or episode")
    return {"kind": kind, "id": identifier}


def _execution(current: dict[str, Any] | None, new_execution: bool) -> int:
    if not isinstance(current, dict):
        return 1
    previous = current.get("execution")
    base = previous if isinstance(previous, int) and not isinstance(previous, bool) and previous > 0 else 1
    return base + 1 if new_execution else base


def _story_seed(project_id: str, spec: dict[str, Any], production_ids: list[str]) -> dict[str, Any]:
    now = _now()
    return {
        "version": 1,
        "id": project_id,
        "revision": 1,
        "title": spec["title"],
        "projectType": spec.get("format") or "quick_video",
        "language": "Español",
        "spokenLanguage": "Español de España",
        "creativeBrief": {"generalIdea": spec.get("idea") or ""},
        "productions": [
            _production_entry(item, spec["title"], spec.get("format"), project_id, spec["workspace_id"])
            for item in production_ids
        ],
        "createdAt": now,
        "updatedAt": now,
    }


def _production_entry(
    production_id: str,
    title: str,
    form: Any,
    project_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    kind = "music_video" if form == "music_video" else "trailer" if form == "trailer" else "film"
    return {
        "id": production_id,
        "kind": kind,
        "title": title or production_id,
        "createdAt": _now(),
        "sourceVersion": 1,
        "status": "draft",
        "provenance": {
            "projectId": project_id,
            "productionId": production_id,
            "workspaceId": workspace_id,
        },
    }


def _upsert_story(workspace_dir: str, project_id: str, project: dict[str, Any]) -> None:
    from services.story_library import StoryLibraryRevisionConflict, patch_story_project, read_story_library

    for _attempt in range(4):
        current = read_story_library(workspace_dir)
        try:
            patch_story_project(
                workspace_dir,
                project_id,
                project,
                base_revision=int(current["revision"]),
                make_active=False,
            )
            return
        except StoryLibraryRevisionConflict:
            continue
    raise LinkError("revision_conflict", "Story library changed while linking")


def _story_exists(workspace_dir: str, project_id: str) -> bool:
    from services.story_library import read_story_library

    return project_id in read_story_library(workspace_dir)["projects"]


def _require_episode(workspace_dir: str, workspace_id: str, episode_id: str) -> None:
    from services.series_library import read_series_library

    library = read_series_library(workspace_dir, workspace_id)
    for series in library.get("seriesById", {}).values():
        episodes = series.get("episodesById") if isinstance(series, dict) else None
        if isinstance(episodes, dict) and isinstance(episodes.get(episode_id), dict):
            return
    raise LinkError("invalid_project", "Episode was not found")


def _link_for_production(store: dict[str, Any], production_id: str) -> tuple[str, dict[str, Any]] | None:
    for intent_id, record in store["links"].items():
        if not isinstance(record, dict):
            continue
        if production_id == record.get("production_id") or production_id in (record.get("production_ids") or []):
            return str(intent_id), record
    return None


def _episode_project(project: Any) -> bool:
    return isinstance(project, dict) and project.get("kind") == "episode"


def _file_status(workspace_dir: str, production_id: str) -> str:
    if not production_id:
        return ""
    body = _read_json(os.path.join(workspace_dir, f"{production_id}.production.json"))
    status = body.get("status") if isinstance(body, dict) else None
    return status.strip() if isinstance(status, str) else ""


def _public(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent_id": record["intent_id"],
        "workspace_id": record["workspace_id"],
        "origin": record["origin"],
        "format": record.get("format"),
        "title": record.get("title") or "",
        "project": dict(record["project"]),
        "production_id": record["production_id"],
        "production_ids": list(record.get("production_ids") or []),
        "status": record.get("status") or "pending",
        "story_created": record.get("story_created") is True,
        "execution": record.get("execution") or 1,
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "review": {
            "event": REVIEW_EVENT,
            "workspace": record["workspace_id"],
            "workspace_id": record["workspace_id"],
            "production_id": record["production_id"],
            "project": dict(record["project"]),
        },
    }


def _read(workspace_dir: str) -> dict[str, Any]:
    path = os.path.join(workspace_dir, LINK_FILENAME)
    body = _read_json(path)
    if body is None:
        return {"version": 1, "revision": 0, "links": {}}
    links = body.get("links") if isinstance(body.get("links"), dict) else {}
    revision = body.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        revision = 0
    return {"version": 1, "revision": revision, "links": links}


def _write(workspace_dir: str, store: dict[str, Any]) -> None:
    store["version"] = 1
    store["revision"] = int(store.get("revision") or 0) + 1
    _replace_json(os.path.join(workspace_dir, LINK_FILENAME), store)


def _read_json(path: str) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    try:
        body = json.loads(open(path, encoding="utf-8").read())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _replace_json(path: str, body: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temporary = f"{path}.{os.getpid()}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(body, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.isfile(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass


def _exclusive(workspace_dir: str):
    os.makedirs(workspace_dir, exist_ok=True)
    key = os.path.realpath(workspace_dir)
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.RLock())
    return _FileLock(os.path.join(workspace_dir, LINK_FILENAME + ".lock"), lock)


class _FileLock:
    def __init__(self, path: str, thread_lock: threading.RLock) -> None:
        self.path = path
        self.thread_lock = thread_lock
        self.handle: Any = None

    def __enter__(self) -> "_FileLock":
        self.thread_lock.acquire()
        self.handle = open(self.path, "a+", encoding="utf-8")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *_args: Any) -> None:
        try:
            if self.handle is not None:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
                self.handle.close()
        finally:
            self.thread_lock.release()


def _token(value: Any, code: str, message: str) -> str:
    token = str(value or "").strip()
    if not token or not _ID.fullmatch(token):
        raise LinkError(code, message)
    return token


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_title(form: str, project: dict[str, str] | None) -> str:
    if project and project["kind"] == "episode":
        return "Episode"
    return {
        "music_video": "Videoclip",
        "trailer": "Tráiler",
        "quick_video": "Vídeo",
        "full_story": "Historia",
    }.get(form, "Vídeo")


MappingRequest = dict[str, Any]


__all__ = [
    "FORMATS", "LINK_FILENAME", "LinkError", "ORIGINS", "REVIEW_EVENT",
    "bind_producer", "created_story_id", "link_existing_production", "note_production_status", "production_id_for",
    "read_link_store", "refresh_link_status", "resolve_production_project",
]
