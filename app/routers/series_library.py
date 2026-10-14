"""Series Lab library and project HTTP surface shared by full launch and core runtime.

Plan and render jobs stay on their existing owners. Attempt approval and the
shot duration preview are separate factories so each server can mount them
where that server already answers those paths. This module does not import
WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import copy
import json
import os
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException


_resolve_workspace: Callable[..., str]
_library_lock: Any
_read_library: Callable[[str], dict]
_write_library: Callable[[str, dict], dict]
_project_or_404: Callable[[dict, str], dict]
# Launch names for the moved bodies. _bind assigns these to the same objects.
_series_library_workspace: Callable[..., str]
_series_library_lock: Any
_read_series_workspace: Callable[[str], dict]
_write_series_workspace: Callable[[str, dict], dict]
_series_project_or_404: Callable[[dict, str], dict]
_workspace_dir: Callable[..., str]
_safe_join: Callable[..., str | None]


def _bind_series_library_runtime(
    *,
    resolve_workspace: Callable[..., str],
    library_lock: Any,
    read_library: Callable[[str], dict],
    write_library: Callable[[str, dict], dict],
    project_or_404: Callable[[dict, str], dict],
    workspace_dir: Callable[..., str] | None = None,
    safe_join: Callable[..., str | None] | None = None,
) -> None:
    global _resolve_workspace, _library_lock, _read_library, _write_library, _project_or_404
    global _series_library_workspace, _series_library_lock
    global _read_series_workspace, _write_series_workspace, _series_project_or_404
    global _workspace_dir, _safe_join
    _resolve_workspace = resolve_workspace
    _library_lock = library_lock
    _read_library = read_library
    _write_library = write_library
    _project_or_404 = project_or_404
    _series_library_workspace = resolve_workspace
    _series_library_lock = library_lock
    _read_series_workspace = read_library
    _write_series_workspace = write_library
    _series_project_or_404 = project_or_404
    if workspace_dir is not None:
        _workspace_dir = workspace_dir
    if safe_join is not None:
        _safe_join = safe_join


def create_series_library_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/series/library")
    def get_series_library(workspace: str | None = None):
        """Load the authoritative Series Lab library for one workspace."""
        target_workspace = _resolve_workspace(workspace)
        try:
            with _library_lock:
                return _read_library(target_workspace)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"Could not read the Series Lab library: {exc}") from exc

    @router.put("/api/v1/series/library")
    def put_series_library(body: dict):
        """Atomically replace a Series library; resource endpoints are preferred."""
        target_workspace = _resolve_workspace(body.get("workspace"))
        try:
            with _library_lock:
                return _write_library(target_workspace, body.get("library"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Could not save the Series Lab library: {exc}") from exc

    @router.get("/api/v1/series")
    def list_series_projects(workspace: str | None = None):
        target_workspace = _resolve_workspace(workspace)
        with _library_lock:
            library = _read_library(target_workspace)
        return {
            "workspaceId": target_workspace,
            "seriesOrder": library["seriesOrder"],
            "series": [library["seriesById"][item] for item in library["seriesOrder"]],
        }

    @router.post("/api/v1/series")
    def create_series_project_endpoint(body: dict):
        from services.document_origin import stamp_created_series
        from services.series_library import create_series_project, normalize_series_project

        workspace = _resolve_workspace(body.get("workspace"))
        try:
            with _library_lock:
                library = _read_library(workspace)
                raw_series = body.get("series")
                if isinstance(raw_series, dict):
                    series = normalize_series_project(raw_series, str(raw_series.get("id") or ""), workspace)
                    stamp_created_series(series, "series.create", episodes="series.episode.create")
                else:
                    series = create_series_project(
                        workspace,
                        title=str(body.get("title") or "Untitled series"),
                        language=body.get("language") if isinstance(body.get("language"), str) else None,
                    )
                if series["id"] in library["seriesById"]:
                    raise HTTPException(status_code=409, detail="A Series Lab project with this id already exists")
                library["seriesById"][series["id"]] = series
                library["seriesOrder"].append(series["id"])
                stored = _write_library(workspace, library)
                return stored["seriesById"][series["id"]]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/v1/series/templates")
    def list_series_templates(language: str | None = None):
        """Templates to start a series from: cast, locations, canon and a 2D pilot."""
        from services.series_templates import list_templates
        return {"templates": list_templates(language)}

    @router.post("/api/v1/series/templates/{template_id}")
    def create_series_from_template(template_id: str, body: dict):
        """Create a series and its pilot from a template, in language es or en."""
        from services.series_templates import SeriesTemplateError, build_series

        workspace = _resolve_workspace(body.get("workspace"))
        try:
            series = build_series(template_id, workspace, title=str(body.get("title") or ""), language=body.get("language"))
        except SeriesTemplateError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
        with _library_lock:
            library = _read_library(workspace)
            library["seriesById"][series["id"]] = series
            library["seriesOrder"].append(series["id"])
            stored = _write_library(workspace, library)
        return stored["seriesById"][series["id"]]

    @router.get("/api/v1/series/{series_id}")
    def get_series_project_endpoint(series_id: str, workspace: str | None = None):
        target_workspace = _resolve_workspace(workspace)
        with _library_lock:
            return _project_or_404(_read_library(target_workspace), series_id)

    router.add_api_route("/api/v1/series/{series_id}", put_series_project_endpoint, methods=["PUT"])
    router.add_api_route("/api/v1/series/{series_id}", delete_series_project_endpoint, methods=["DELETE"])
    router.add_api_route("/api/v1/series/{series_id}/duplicate", duplicate_series_project_endpoint, methods=["POST"])
    router.add_api_route("/api/v1/series/import-story", import_story_as_series_endpoint, methods=["POST"])
    router.add_api_route("/api/v1/series/{series_id}/episodes", create_series_episode_endpoint, methods=["POST"])
    router.add_api_route("/api/v1/series/{series_id}/episodes", list_series_episodes_endpoint, methods=["GET"])
    router.add_api_route("/api/v1/series/{series_id}/episodes/{episode_id}", get_series_episode_endpoint, methods=["GET"])
    router.add_api_route("/api/v1/series/{series_id}/episodes/{episode_id}", delete_series_episode_endpoint, methods=["DELETE"])
    router.add_api_route("/api/v1/series/{series_id}/assets/import", import_series_asset_endpoint, methods=["POST"])
    router.add_api_route("/api/v1/series/{series_id}/episodes/{episode_id}", put_series_episode_endpoint, methods=["PUT"])
    router.add_api_route("/api/v1/series/{series_id}/episodes/{episode_id}/canon/commit", commit_series_canon_endpoint, methods=["POST"])
    router.add_api_route("/api/v1/series/{series_id}/episodes/{episode_id}/references/refresh", refresh_series_episode_references, methods=["POST"])
    router.add_api_route("/api/v1/series/{series_id}/canon/approve", approve_series_canon_endpoint, methods=["POST"])
    router.add_api_route("/api/v1/series/{series_id}/episodes/{episode_id}/references/route", route_series_episode_references_endpoint, methods=["POST"])

    return router


def _require_series_deletion_ready(
    workspace: str,
    series_id: str,
    episode_id: str | None = None,
) -> None:
    from services.series_lifecycle import ActiveSeriesJobsError, require_no_active_series_jobs

    try:
        require_no_active_series_jobs(
            _workspace_dir(workspace),
            workspace,
            series_id,
            episode_id=episode_id,
        )
    except ActiveSeriesJobsError as exc:
        raise HTTPException(status_code=409, detail=exc.detail()) from exc

def _series_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _story_import_upload_path(value: str) -> str:
    """Allow multimodal analysis only for files uploaded into Maestro."""
    upload_dir = os.path.realpath(os.path.join(os.getcwd(), "uploads"))
    candidate = os.path.realpath(str(value or ""))
    if candidate != upload_dir and not candidate.startswith(upload_dir + os.sep):
        raise HTTPException(status_code=400, detail="Smart asset analysis only accepts HocusPocus Lab uploads")
    if not os.path.isfile(candidate):
        raise HTTPException(status_code=400, detail="One imported asset is no longer available")
    return candidate

def _approve_series_version_take(workspace: str, library: dict, series: dict, episode: dict, shot_index: int, language: str,
                                 attempt_id: str, approved_by: str = "user") -> dict:
    """Approve a take for a language version (its own approval and length); the original's stays as it was."""
    from services.series_language_versions import set_version_take
    shot = episode["shots"][shot_index]
    try:
        set_version_take(episode, language, shot["id"], attempt_id, approved_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    now = _series_iso_now()
    episode["updatedAt"] = now
    series["episodesById"][episode["id"]] = episode
    series["revision"] = int(series.get("revision") or 1) + 1
    series["updatedAt"] = now
    library["seriesById"][series["id"]] = series
    stored = _write_series_workspace(workspace, library)
    version = stored["seriesById"][series["id"]]["episodesById"][episode["id"]]["languageVersions"][language]
    return {**stored["seriesById"][series["id"]]["episodesById"][episode["id"]]["shots"][shot_index],
            "language": language, "approvedAttemptId": version["approvedAttemptIds"].get(shot["id"]),
            "durationSeconds": (version.get("durations") or {}).get(shot["id"])}

def put_series_project_endpoint(series_id: str, body: dict):
    from services.series_library import normalize_series_project, series_canon_inputs_changed, series_put_payload

    workspace = _series_library_workspace(body.get("workspace"))
    raw_series = body.get("series")
    if not isinstance(raw_series, dict):
        raise HTTPException(status_code=400, detail="Series project is required")
    if raw_series.get("id") not in {None, "", series_id}:
        raise HTTPException(status_code=400, detail="Series project id does not match the route")
    try:
        with _series_library_lock:
            library = _read_series_workspace(workspace)
            current = _series_project_or_404(library, series_id)
            base_revision = body.get("baseRevision")
            if base_revision is not None and int(base_revision) != int(current.get("revision") or 1):
                raise HTTPException(
                    status_code=409,
                    detail=f"Series revision changed to {current.get('revision')}; reload before saving",
                )
            updated = normalize_series_project({**series_put_payload(current, raw_series), "id": series_id}, series_id, workspace)
            if series_canon_inputs_changed(current, updated):
                updated["canon"]["approval"] = "draft"
                updated["canon"]["approvedAt"] = ""
            updated["revision"] = int(current.get("revision") or 1) + 1
            updated["createdAt"] = current.get("createdAt") or updated["createdAt"]
            updated["updatedAt"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            library["seriesById"][series_id] = updated
            stored = _write_series_workspace(workspace, library)
            return stored["seriesById"][series_id]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

def delete_series_project_endpoint(series_id: str, workspace: str | None = None):
    target_workspace = _series_library_workspace(workspace)
    with _series_library_lock:
        library = _read_series_workspace(target_workspace)
        _series_project_or_404(library, series_id)
        _require_series_deletion_ready(target_workspace, series_id)
        del library["seriesById"][series_id]
        library["seriesOrder"] = [item for item in library["seriesOrder"] if item != series_id]
        _write_series_workspace(target_workspace, library)
    return {"deleted": True, "seriesId": series_id, "outputsPreserved": True}

def duplicate_series_project_endpoint(series_id: str, body: dict | None = None):
    from services.series_library import duplicate_series_project, normalize_series_project

    body = body if isinstance(body, dict) else {}
    workspace = _series_library_workspace(body.get("workspace"))
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        source = _series_project_or_404(library, series_id)
        duplicate = duplicate_series_project(source)
        duplicate = normalize_series_project(duplicate, duplicate["id"], workspace)
        library["seriesById"][duplicate["id"]] = duplicate
        source_index = library["seriesOrder"].index(series_id)
        library["seriesOrder"].insert(source_index + 1, duplicate["id"])
        stored = _write_series_workspace(workspace, library)
    return stored["seriesById"][duplicate["id"]]

def import_story_as_series_endpoint(body: dict):
    from services.series_library import import_story_project
    from services.story_library import read_story_library
    import shutil

    workspace = _series_library_workspace(body.get("workspace"))
    story = body.get("story") if isinstance(body.get("story"), dict) else None
    if story is None:
        story_id = str(body.get("storyId") or "").strip()
        if not story_id:
            raise HTTPException(status_code=400, detail="Choose a Story Lab project to import")
        story_library = read_story_library(_workspace_dir(workspace))
        story = story_library.get("projects", {}).get(story_id)
        if not isinstance(story, dict):
            raise HTTPException(status_code=404, detail="Story Lab source project not found")
    try:
        story_for_import = copy.deepcopy(story)
        upload_sources: dict[str, str] = {}
        for asset_key, asset in (
            story_for_import.get("assets", {}).items()
            if isinstance(story_for_import.get("assets"), dict) else []
        ):
            if not isinstance(asset, dict):
                continue
            source = str(asset.get("source") or "")
            if source.startswith("/api/v1/uploads/"):
                from urllib.parse import unquote
                upload_name = unquote(source.split("/api/v1/uploads/", 1)[1])
                local_candidate = _safe_join(os.path.join(os.getcwd(), "uploads"), upload_name)
                local_source = _story_import_upload_path(local_candidate or "")
                asset_id = str(asset.get("id") or asset_key)
                upload_sources[asset_id] = local_source
                # A valid workspace placeholder lets the pure importer retain
                # entity links. It is replaced with the copied destination
                # before the authoritative library is written.
                asset["source"] = f"assets/story-import/{uuid.uuid4().hex}.bin"
            elif os.path.isabs(source):
                try:
                    local_source = _story_import_upload_path(source)
                except HTTPException:
                    continue
                asset_id = str(asset.get("id") or asset_key)
                upload_sources[asset_id] = local_source
                # A valid workspace placeholder lets the pure importer retain
                # entity links. It is replaced with the copied destination
                # before the authoritative library is written.
                asset["source"] = f"assets/story-import/{uuid.uuid4().hex}.bin"
        imported = import_story_project(story_for_import, workspace)
        for asset_id, local_source in upload_sources.items():
            imported_asset = imported.get("assets", {}).get(asset_id)
            if not isinstance(imported_asset, dict):
                continue
            extension = os.path.splitext(local_source)[1].lower()[:12]
            relative = f"assets/{imported['id']}/{uuid.uuid4().hex[:16]}{extension}"
            destination = _safe_join(_workspace_dir(workspace), relative)
            if not destination:
                raise ValueError("Invalid imported Story asset destination")
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(local_source, destination)
            imported_asset["uri"] = relative
        with _series_library_lock:
            library = _read_series_workspace(workspace)
            library["seriesById"][imported["id"]] = imported
            library["seriesOrder"].append(imported["id"])
            stored = _write_series_workspace(workspace, library)
        return stored["seriesById"][imported["id"]]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

def create_series_episode_endpoint(series_id: str, body: dict):
    from services.series_episode import create_checked_episode

    workspace = _series_library_workspace(body.get("workspace"))
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = copy.deepcopy(_series_project_or_404(library, series_id))
        if series.get("canon", {}).get("approval") != "approved":
            raise HTTPException(status_code=400, detail="Approve the reviewed Series canon before creating an episode")
        episode = create_checked_episode(series, body)
        series["episodesById"][episode["id"]] = episode
        season = next(item for item in series["seasons"] if item["id"] == episode["seasonId"])
        season["episodeOrder"].append(episode["id"])
        series["revision"] = int(series.get("revision") or 1) + 1
        series["updatedAt"] = episode["updatedAt"]
        library["seriesById"][series_id] = series
        stored = _write_series_workspace(workspace, library)
    return stored["seriesById"][series_id]["episodesById"][episode["id"]]

def list_series_episodes_endpoint(series_id: str, workspace: str | None = None):
    target_workspace = _series_library_workspace(workspace)
    with _series_library_lock:
        series = _series_project_or_404(_read_series_workspace(target_workspace), series_id)
        ordered = []
        seen: set[str] = set()
        for season in series.get("seasons", []):
            if not isinstance(season, dict):
                continue
            for episode_id in season.get("episodeOrder", []):
                episode = series.get("episodesById", {}).get(episode_id)
                if isinstance(episode, dict) and episode_id not in seen:
                    ordered.append(copy.deepcopy(episode)); seen.add(episode_id)
        ordered.extend(
            copy.deepcopy(episode) for episode_id, episode in series.get("episodesById", {}).items()
            if isinstance(episode, dict) and episode_id not in seen
        )
    return {"episodes": ordered}

def get_series_episode_endpoint(series_id: str, episode_id: str, workspace: str | None = None):
    target_workspace = _series_library_workspace(workspace)
    with _series_library_lock:
        series = _series_project_or_404(_read_series_workspace(target_workspace), series_id)
        episode = series.get("episodesById", {}).get(episode_id)
        if not isinstance(episode, dict):
            raise HTTPException(status_code=404, detail="Series episode not found")
        return copy.deepcopy(episode)

def delete_series_episode_endpoint(series_id: str, episode_id: str, workspace: str | None = None):
    target_workspace = _series_library_workspace(workspace)
    with _series_library_lock:
        library = _read_series_workspace(target_workspace)
        series = copy.deepcopy(_series_project_or_404(library, series_id))
        if episode_id not in series.get("episodesById", {}):
            raise HTTPException(status_code=404, detail="Series episode not found")
        _require_series_deletion_ready(target_workspace, series_id, episode_id)
        del series["episodesById"][episode_id]
        for season in series.get("seasons", []):
            if isinstance(season, dict):
                season["episodeOrder"] = [item for item in season.get("episodeOrder", []) if item != episode_id]
        now = _series_iso_now()
        series["revision"] = int(series.get("revision") or 1) + 1
        series["updatedAt"] = now
        library["seriesById"][series_id] = series
        _write_series_workspace(target_workspace, library)
    return {"deleted": True, "episodeId": episode_id, "outputsPreserved": True}

def import_series_asset_endpoint(series_id: str, body: dict):
    """Copy a Maestro upload into the authoritative workspace asset tree."""
    import shutil
    from services.series_plate_checks import with_plate_warning
    from services.series_production import attach_series_import, existing_generated_reference

    workspace = _series_library_workspace(body.get("workspace"))
    source = _story_import_upload_path(str(body.get("uploadPath") or ""))
    owner_type = str(body.get("ownerType") or "series")
    owner_id = str(body.get("ownerId") or series_id).strip()
    if owner_type not in {"series", "character", "location", "prop", "episode", "shot"}:
        raise HTTPException(status_code=400, detail="Unsupported Series asset owner")
    kind = str(body.get("kind") or "image")
    if kind not in {"image", "audio", "video", "character", "location", "prop", "other"}:
        kind = "other"
    extension = os.path.splitext(source)[1].lower()[:12]
    extra_metadata = copy.deepcopy(body.get("metadata")) if isinstance(body.get("metadata"), dict) else {}
    if len(json.dumps(extra_metadata, ensure_ascii=False, default=str).encode("utf-8")) > 32 * 1024:
        raise HTTPException(status_code=413, detail="Series asset metadata is too large")
    asset_id = f"asset_{uuid.uuid4().hex[:12]}"
    relative = os.path.join("assets", series_id, f"{asset_id}{extension}").replace(os.sep, "/")
    destination = _safe_join(_workspace_dir(workspace), relative)
    if not destination:
        raise HTTPException(status_code=400, detail="Invalid Series asset destination")
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = copy.deepcopy(_series_project_or_404(library, series_id))
        entity = None
        existing = existing_generated_reference(series, owner_type, owner_id, extra_metadata)
        if existing and body.get("asTake") is not True:
            return {"asset": existing, "series": series}
        collection_name = {
            "character": "characters", "location": "locations", "prop": "props",
        }.get(owner_type)
        if collection_name:
            entity = next((
                item for item in series.get(collection_name, []) if item.get("id") == owner_id
            ), None)
            if not isinstance(entity, dict):
                raise HTTPException(status_code=404, detail=f"Series {owner_type} not found")
        elif owner_type == "episode" and owner_id not in series.get("episodesById", {}):
            raise HTTPException(status_code=404, detail="Series episode not found")
        elif owner_type == "shot" and not any(
            shot.get("id") == owner_id
            for episode in series.get("episodesById", {}).values() if isinstance(episode, dict)
            for shot in episode.get("shots", []) if isinstance(shot, dict)
        ):
            raise HTTPException(status_code=404, detail="Series shot not found")
        asset = {
            "id": asset_id, "workspaceId": workspace, "kind": kind,
            "uri": relative, "ownerType": owner_type, "ownerId": owner_id,
            "isDerivedThumbnail": False,
            "metadata": {
                "name": str(body.get("name") or os.path.basename(source))[:300],
                "referenceRole": str(body.get("referenceRole") or "reference")[:100],
                "importedAt": _series_iso_now(),
                **({
                    str(key)[:100]: copy.deepcopy(value)
                    for key, value in extra_metadata.items()
                    if isinstance(key, str) and key not in {"referenceRole", "importedAt"}
                }),
            },
        }
        try:
            attach_series_import(series, asset, as_take=body.get("asTake") is True, source_path=source)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(source, destination)
        now = _series_iso_now()
        series["revision"] = int(series.get("revision") or 1) + 1
        series["updatedAt"] = now
        library["seriesById"][series_id] = series
        stored = _write_series_workspace(workspace, library)
    stored_series = stored["seriesById"][series_id]
    return with_plate_warning(
        {"asset": stored_series["assets"][asset_id], "series": stored_series}, source, body, stored_series)

def put_series_episode_endpoint(series_id: str, episode_id: str, body: dict):
    from services.series_episode import apply_series_episode_update

    workspace = _series_library_workspace(body.get("workspace"))
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = _series_project_or_404(library, series_id)
        updated_series = apply_series_episode_update(
            series_id, episode_id, body, series, updated_at=_series_iso_now(),
        )
        library["seriesById"][series_id] = updated_series
        try:
            stored = _write_series_workspace(workspace, library)
        except ValueError as exc:
            # Validation of the whole project (for example an id used twice in the series) is the caller's error.
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return stored["seriesById"][series_id]["episodesById"][episode_id]

def commit_series_canon_endpoint(series_id: str, episode_id: str, body: dict):
    from services.series_library import SeriesConflictError, commit_canon_delta

    workspace = _series_library_workspace(body.get("workspace"))
    decisions = body.get("decisions") if isinstance(body.get("decisions"), dict) else {}
    try:
        base_revision = int(body.get("baseRevision"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="baseRevision is required") from exc
    try:
        with _series_library_lock:
            library = _read_series_workspace(workspace)
            series = _series_project_or_404(library, series_id)
            updated = commit_canon_delta(series, episode_id, decisions, base_revision)
            library["seriesById"][series_id] = updated
            stored = _write_series_workspace(workspace, library)
        return stored["seriesById"][series_id]
    except SeriesConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

def refresh_series_episode_references(series_id: str, episode_id: str, body: dict):
    from services.series_library import SeriesConflictError
    from services.series_production import refresh_episode_references
    workspace = _series_library_workspace(body.get("workspace"))
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        try:
            series = refresh_episode_references(_series_project_or_404(library, series_id), episode_id, int(body.get("baseRevision", -1)))
        except SeriesConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        series["updatedAt"] = _series_iso_now()
        series["episodesById"][episode_id]["updatedAt"] = series["updatedAt"]
        library["seriesById"][series_id] = series
        stored = _write_series_workspace(workspace, library)
    return stored["seriesById"][series_id]

def approve_series_canon_endpoint(series_id: str, body: dict):
    workspace = _series_library_workspace(body.get("workspace"))
    try:
        base_revision = int(body.get("baseRevision"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="baseRevision is required") from exc
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = copy.deepcopy(_series_project_or_404(library, series_id))
        canon = series.get("canon") if isinstance(series.get("canon"), dict) else {}
        if int(canon.get("revision") or 1) != base_revision:
            raise HTTPException(
                status_code=409,
                detail=f"Canon revision changed to {canon.get('revision')}; reload before approval",
            )
        if not str(canon.get("worldSummary") or "").strip():
            raise HTTPException(status_code=400, detail="Complete the World summary before approving canon")
        if not series.get("characters"):
            raise HTTPException(status_code=400, detail="Add at least one principal character before approving canon")
        if not series.get("locations"):
            raise HTTPException(status_code=400, detail="Add at least one canonical location before approving canon")
        now = _series_iso_now()
        if canon.get("approval") != "approved":
            canon["revision"] = base_revision + 1
        canon["approval"] = "approved"
        canon["approvedAt"] = now
        series["canon"] = canon
        for collection in ("characters", "locations", "props"):
            for item in series.get(collection, []):
                if isinstance(item, dict):
                    item["approval"] = "approved"
        series["revision"] = int(series.get("revision") or 1) + 1
        series["updatedAt"] = now
        library["seriesById"][series_id] = series
        stored = _write_series_workspace(workspace, library)
    return stored["seriesById"][series_id]

def route_series_episode_references_endpoint(series_id: str, episode_id: str, body: dict):
    from services.series_library import series_for_episode_snapshot
    from services.series_reference_router import route_episode_references, route_shot_references

    workspace = _series_library_workspace(body.get("workspace"))
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = _series_project_or_404(library, series_id)
        episode = series.get("episodesById", {}).get(episode_id)
        if not isinstance(episode, dict):
            raise HTTPException(status_code=404, detail="Series episode not found")
        routing_series = series_for_episode_snapshot(series, episode)
        shot_id = str(body.get("shotId") or "").strip()
        capabilities = body.get("capabilities") if isinstance(body.get("capabilities"), dict) else None
        if shot_id:
            shot = next((item for item in episode.get("shots", []) if item.get("id") == shot_id), None)
            if not isinstance(shot, dict):
                raise HTTPException(status_code=404, detail="Series shot not found")
            return {"shotId": shot_id, "manifest": route_shot_references(routing_series, episode, shot, capabilities)}
        return {"manifests": route_episode_references(routing_series, episode, capabilities)}

def preview_series_shot_duration(series_id: str, body: dict):
    """Preview the same authoritative duration contract used by save/render."""
    from services.series_render import plan_series_shot_duration

    workspace = _series_library_workspace(body.get("workspace"))
    shot = body.get("shot")
    if not isinstance(shot, dict):
        raise HTTPException(status_code=400, detail="Series shot is required")
    with _series_library_lock:
        series = copy.deepcopy(_series_project_or_404(
            _read_series_workspace(workspace), series_id,
        ))
    try:
        return plan_series_shot_duration(series, shot)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

def approve_series_shot_attempt_endpoint(
    series_id: str, episode_id: str, shot_id: str, attempt_id: str, body: dict | None = None,
):
    from services.agent_activity import current_actor
    from services.series_library import approve_shot_render_attempt

    body = body if isinstance(body, dict) else {}
    # Who approves: a person, an agent or the Wizard, or the server render (X-Hocus-Actor, see ActorHeaderMiddleware).
    approved_by = current_actor()
    workspace = _series_library_workspace(body.get("workspace"))
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = copy.deepcopy(_series_project_or_404(library, series_id))
        episode = series.get("episodesById", {}).get(episode_id)
        if not isinstance(episode, dict):
            raise HTTPException(status_code=404, detail="Series episode not found")
        shot_index = next((
            index for index, shot in enumerate(episode.get("shots", []))
            if isinstance(shot, dict) and shot.get("id") == shot_id
        ), None)
        if shot_index is None:
            raise HTTPException(status_code=404, detail="Series shot not found")
        language = body.get("language")
        if isinstance(language, str) and language:
            from services.series_shot_plan import language_key
            if language != language_key(series):
                return _approve_series_version_take(workspace, library, series, episode, shot_index, language, attempt_id,
                                                    approved_by)
        try:
            episode["shots"][shot_index] = approve_shot_render_attempt(
                episode["shots"][shot_index], attempt_id, approved_by,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        now = _series_iso_now()
        if episode.get("shots") and all(
            isinstance(shot, dict) and bool(shot.get("approvedAttemptId"))
            for shot in episode.get("shots", [])
        ):
            episode["status"] = "completed"
        episode["updatedAt"] = now
        series["episodesById"][episode_id] = episode
        series["revision"] = int(series.get("revision") or 1) + 1
        series["updatedAt"] = now
        library["seriesById"][series_id] = series
        stored = _write_series_workspace(workspace, library)
    return stored["seriesById"][series_id]["episodesById"][episode_id]["shots"][shot_index]

def approve_series_episode_attempts_endpoint(
    series_id: str, episode_id: str, body: dict,
):
    from services.agent_activity import current_actor
    from services.series_library import approve_episode_render_attempts

    workspace = _series_library_workspace(body.get("workspace"))
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = copy.deepcopy(_series_project_or_404(library, series_id))
        episode = series.get("episodesById", {}).get(episode_id)
        if not isinstance(episode, dict):
            raise HTTPException(status_code=404, detail="Series episode not found")
        try:
            episode = approve_episode_render_attempts(episode, body.get("selections"), current_actor())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        now = _series_iso_now()
        if episode.get("shots") and all(
            isinstance(shot, dict) and bool(shot.get("approvedAttemptId"))
            for shot in episode.get("shots", [])
        ):
            episode["status"] = "completed"
        episode["updatedAt"] = now
        series["episodesById"][episode_id] = episode
        series["revision"] = int(series.get("revision") or 1) + 1
        series["updatedAt"] = now
        library["seriesById"][series_id] = series
        stored = _write_series_workspace(workspace, library)
    stored_series = stored["seriesById"][series_id]
    return {
        "seriesId": series_id,
        "episodeId": episode_id,
        "revision": stored_series["revision"],
        "episode": stored_series["episodesById"][episode_id],
    }

def reject_series_shot_attempt_endpoint(
    series_id: str, episode_id: str, shot_id: str, attempt_id: str, body: dict | None = None,
):
    from services.agent_activity import current_actor
    from services.series_library import reject_shot_render_attempt

    body = body if isinstance(body, dict) else {}
    workspace = _series_library_workspace(body.get("workspace"))
    with _series_library_lock:
        library = _read_series_workspace(workspace)
        series = copy.deepcopy(_series_project_or_404(library, series_id))
        episode = series.get("episodesById", {}).get(episode_id)
        if not isinstance(episode, dict):
            raise HTTPException(status_code=404, detail="Series episode not found")
        shot_index = next((
            index for index, shot in enumerate(episode.get("shots", []))
            if isinstance(shot, dict) and shot.get("id") == shot_id
        ), None)
        if shot_index is None:
            raise HTTPException(status_code=404, detail="Series shot not found")
        try:
            episode["shots"][shot_index] = reject_shot_render_attempt(
                episode["shots"][shot_index], attempt_id, current_actor(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        now = _series_iso_now()
        episode["status"] = "rendering"
        episode["updatedAt"] = now
        series["episodesById"][episode_id] = episode
        series["revision"] = int(series.get("revision") or 1) + 1
        series["updatedAt"] = now
        library["seriesById"][series_id] = series
        stored = _write_series_workspace(workspace, library)
    return stored["seriesById"][series_id]["episodesById"][episode_id]["shots"][shot_index]


def create_series_shot_duration_router() -> APIRouter:
    router = APIRouter()
    router.add_api_route("/api/v1/series/{series_id}/shots/duration/preview", preview_series_shot_duration, methods=["POST"])
    return router


def create_series_attempt_approval_router() -> APIRouter:
    router = APIRouter()
    router.add_api_route("/api/v1/series/{series_id}/episodes/{episode_id}/shots/{shot_id}/attempts/{attempt_id}/approve", approve_series_shot_attempt_endpoint, methods=["POST"])
    router.add_api_route("/api/v1/series/{series_id}/episodes/{episode_id}/attempts/approve-bulk", approve_series_episode_attempts_endpoint, methods=["POST"])
    return router


def create_series_attempt_reject_router() -> APIRouter:
    router = APIRouter()
    router.add_api_route("/api/v1/series/{series_id}/episodes/{episode_id}/shots/{shot_id}/attempts/{attempt_id}/reject", reject_series_shot_attempt_endpoint, methods=["POST"])
    return router
