"""Story, Character Kit and Series filesystem persistence for core/remote."""
from __future__ import annotations

import copy
import json
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException

from services import core_workspace as core
from services.character_kit_library import (
    CharacterKitRevisionConflict,
    delete_character_kit,
    patch_character_kit,
    read_character_kit_library,
)
from services.series_library import (
    create_series_episode,
    create_series_project,
    duplicate_series_project,
    import_story_project,
    normalize_series_project,
    read_series_library,
    series_canon_inputs_changed,
    validate_workspace_id,
    write_series_library,
)
from services.story_library import (
    StoryLibraryRevisionConflict,
    delete_story_project,
    patch_story_project,
    read_story_library,
    write_story_library,
)
_LOCK = threading.RLock()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _workspace(value: Any) -> str:
    name = str(value or core.active_workspace() or "default").strip()
    try:
        core.workspace_dir(name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return name


def _dir(value: Any) -> str:
    return core.workspace_dir(_workspace(value))


def _conflict(code: str, exc: Any) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": code,
            "message": str(exc),
            "expectedRevision": getattr(exc, "expected", None),
            "currentRevision": getattr(exc, "current", None),
        },
    )


def _series_workspace(value: Any) -> str:
    try:
        name = validate_workspace_id(value or core.active_workspace())
        core.workspace_dir(name)
        return name
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _read_series(workspace: str) -> dict:
    return read_series_library(_dir(workspace), workspace)


def _write_series(workspace: str, library: dict) -> dict:
    return write_series_library(_dir(workspace), library, workspace)


def _series_or_404(library: dict, series_id: str) -> dict:
    series = library.get("seriesById", {}).get(series_id)
    if not isinstance(series, dict):
        raise HTTPException(status_code=404, detail="Series Lab project not found")
    return series


def _story_import_upload_path(value: str) -> str:
    upload_dir = os.path.realpath(core.uploads_dir())
    candidate = os.path.realpath(str(value or ""))
    if candidate != upload_dir and not candidate.startswith(upload_dir + os.sep):
        raise HTTPException(status_code=400, detail="Imported Story assets must come from HocusPocus Lab uploads")
    if not os.path.isfile(candidate):
        raise HTTPException(status_code=400, detail="One imported asset is no longer available")
    return candidate


def _prepare_story_uploads_for_series_import(story: dict, workspace: str) -> dict:
    """Copy Story Lab upload files into the workspace so import_story_project keeps them."""
    prepared = copy.deepcopy(story)
    upload_sources: dict[str, str] = {}
    assets = prepared.get("assets") if isinstance(prepared.get("assets"), dict) else {}
    for asset_key, asset in assets.items():
        if not isinstance(asset, dict):
            continue
        source = str(asset.get("source") or "")
        local_source = None
        if source.startswith("/api/v1/uploads/"):
            upload_name = unquote(source.split("/api/v1/uploads/", 1)[1])
            local_candidate = core.safe_join(core.uploads_dir(), upload_name)
            local_source = _story_import_upload_path(local_candidate or "")
        elif os.path.isabs(source):
            try:
                local_source = _story_import_upload_path(source)
            except HTTPException:
                continue
        if not local_source:
            continue
        asset_id = str(asset.get("id") or asset_key)
        upload_sources[asset_id] = local_source
        # A valid workspace placeholder lets the pure importer retain entity links.
        asset["source"] = f"assets/story-import/{uuid.uuid4().hex}.bin"
    imported = import_story_project(prepared, workspace)
    for asset_id, local_source in upload_sources.items():
        imported_asset = imported.get("assets", {}).get(asset_id)
        if not isinstance(imported_asset, dict):
            continue
        extension = os.path.splitext(local_source)[1].lower()[:12]
        relative = f"assets/{imported['id']}/{uuid.uuid4().hex[:16]}{extension}"
        destination = core.safe_join(_dir(workspace), relative)
        if not destination:
            raise ValueError("Invalid imported Story asset destination")
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(local_source, destination)
        imported_asset["uri"] = relative
    return imported


def create_core_labs_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/stories/library")
    def get_story_library(workspace: str | None = None):
        try:
            with _LOCK:
                return read_story_library(_dir(workspace))
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=500, detail=f"Could not read the Story Lab library: {error}") from error

    @router.put("/api/v1/stories/library")
    def put_story_library(body: dict):
        try:
            with _LOCK:
                return write_story_library(
                    _dir(body.get("workspace")),
                    body.get("library"),
                    base_revision=body.get("baseRevision"),
                )
        except StoryLibraryRevisionConflict as error:
            raise _conflict("story_library_revision_conflict", error) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.patch("/api/v1/stories/library/projects/{project_id}")
    def patch_story(project_id: str, body: dict):
        try:
            with _LOCK:
                return patch_story_project(
                    _dir(body.get("workspace")),
                    project_id,
                    body.get("project"),
                    base_revision=body.get("baseRevision"),
                    make_active=body.get("makeActive") is True,
                )
        except StoryLibraryRevisionConflict as error:
            raise _conflict("story_library_revision_conflict", error) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.delete("/api/v1/stories/library/projects/{project_id}")
    def delete_story(project_id: str, body: dict):
        try:
            with _LOCK:
                return delete_story_project(
                    _dir(body.get("workspace")),
                    project_id,
                    base_revision=body.get("baseRevision"),
                )
        except StoryLibraryRevisionConflict as error:
            raise _conflict("story_library_revision_conflict", error) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Story project not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/api/v1/character-kits/library")
    def get_kits(workspace: str | None = None):
        try:
            return read_character_kit_library(_dir(workspace))
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=500, detail=f"Could not read Character Kits: {error}") from error

    @router.patch("/api/v1/character-kits/library/kits/{kit_id}")
    def patch_kit(kit_id: str, body: dict):
        try:
            return patch_character_kit(
                _dir(body.get("workspace")),
                kit_id,
                body.get("kit"),
                base_revision=body.get("baseRevision"),
                make_active=body.get("makeActive") is not False,
            )
        except CharacterKitRevisionConflict as error:
            raise _conflict("character_kit_revision_conflict", error) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.delete("/api/v1/character-kits/library/kits/{kit_id}")
    def delete_kit(kit_id: str, body: dict):
        try:
            return delete_character_kit(
                _dir(body.get("workspace")),
                kit_id,
                base_revision=body.get("baseRevision"),
            )
        except CharacterKitRevisionConflict as error:
            raise _conflict("character_kit_revision_conflict", error) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Character Kit not found") from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/api/v1/series/library")
    def get_series_library(workspace: str | None = None):
        target = _series_workspace(workspace)
        with _LOCK:
            return _read_series(target)

    @router.put("/api/v1/series/library")
    def put_series_library(body: dict):
        target = _series_workspace(body.get("workspace"))
        try:
            with _LOCK:
                return _write_series(target, body.get("library"))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/api/v1/series")
    def list_series(workspace: str | None = None):
        target = _series_workspace(workspace)
        with _LOCK:
            library = _read_series(target)
        return {
            "workspaceId": target,
            "seriesOrder": library["seriesOrder"],
            "series": [library["seriesById"][item] for item in library["seriesOrder"]],
        }

    @router.post("/api/v1/series")
    def create_series(body: dict):
        workspace = _series_workspace(body.get("workspace"))
        try:
            with _LOCK:
                library = _read_series(workspace)
                raw = body.get("series")
                series = (
                    normalize_series_project(raw, str(raw.get("id") or ""), workspace)
                    if isinstance(raw, dict)
                    else create_series_project(workspace, title=str(body.get("title") or "Untitled series"))
                )
                if series["id"] in library["seriesById"]:
                    raise HTTPException(status_code=409, detail="A Series Lab project with this id already exists")
                library["seriesById"][series["id"]] = series
                library["seriesOrder"].append(series["id"])
                stored = _write_series(workspace, library)
                return stored["seriesById"][series["id"]]
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post("/api/v1/series/import-story")
    def import_story(body: dict):
        workspace = _series_workspace(body.get("workspace"))
        story = body.get("story") if isinstance(body.get("story"), dict) else None
        if story is None:
            story_id = str(body.get("storyId") or "").strip()
            if not story_id:
                raise HTTPException(status_code=400, detail="Choose a Story Lab project to import")
            story = read_story_library(_dir(workspace)).get("projects", {}).get(story_id)
            if not isinstance(story, dict):
                raise HTTPException(status_code=404, detail="Story Lab source project not found")
        try:
            imported = _prepare_story_uploads_for_series_import(story, workspace)
            with _LOCK:
                library = _read_series(workspace)
                library["seriesById"][imported["id"]] = imported
                library["seriesOrder"].append(imported["id"])
                stored = _write_series(workspace, library)
            return stored["seriesById"][imported["id"]]
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/api/v1/series/{series_id}")
    def get_series(series_id: str, workspace: str | None = None):
        with _LOCK:
            return _series_or_404(_read_series(_series_workspace(workspace)), series_id)

    @router.put("/api/v1/series/{series_id}")
    def put_series(series_id: str, body: dict):
        workspace = _series_workspace(body.get("workspace"))
        raw = body.get("series")
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail="Series project is required")
        if raw.get("id") not in {None, "", series_id}:
            raise HTTPException(status_code=400, detail="Series project id does not match the route")
        try:
            with _LOCK:
                library = _read_series(workspace)
                current = _series_or_404(library, series_id)
                base_revision = body.get("baseRevision")
                if base_revision is not None and int(base_revision) != int(current.get("revision") or 1):
                    raise HTTPException(
                        status_code=409,
                        detail=f"Series revision changed to {current.get('revision')}; reload before saving",
                    )
                updated = normalize_series_project({**raw, "id": series_id}, series_id, workspace)
                if series_canon_inputs_changed(current, updated):
                    updated["canon"]["approval"] = "draft"
                    updated["canon"]["approvedAt"] = ""
                updated["revision"] = int(current.get("revision") or 1) + 1
                updated["createdAt"] = current.get("createdAt") or updated["createdAt"]
                updated["updatedAt"] = _iso_now()
                library["seriesById"][series_id] = updated
                return _write_series(workspace, library)["seriesById"][series_id]
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.delete("/api/v1/series/{series_id}")
    def delete_series(series_id: str, workspace: str | None = None):
        target = _series_workspace(workspace)
        with _LOCK:
            library = _read_series(target)
            _series_or_404(library, series_id)
            del library["seriesById"][series_id]
            library["seriesOrder"] = [item for item in library["seriesOrder"] if item != series_id]
            _write_series(target, library)
        return {"deleted": True, "seriesId": series_id, "outputsPreserved": True}

    @router.post("/api/v1/series/{series_id}/duplicate")
    def duplicate_series(series_id: str, body: dict | None = None):
        body = body if isinstance(body, dict) else {}
        workspace = _series_workspace(body.get("workspace"))
        with _LOCK:
            library = _read_series(workspace)
            source = _series_or_404(library, series_id)
            duplicate = duplicate_series_project(source)
            duplicate = normalize_series_project(duplicate, duplicate["id"], workspace)
            library["seriesById"][duplicate["id"]] = duplicate
            source_index = library["seriesOrder"].index(series_id)
            library["seriesOrder"].insert(source_index + 1, duplicate["id"])
            stored = _write_series(workspace, library)
        return stored["seriesById"][duplicate["id"]]

    @router.post("/api/v1/series/{series_id}/episodes")
    def create_episode(series_id: str, body: dict):
        workspace = _series_workspace(body.get("workspace"))
        with _LOCK:
            library = _read_series(workspace)
            series = copy.deepcopy(_series_or_404(library, series_id))
            if series.get("canon", {}).get("approval") != "approved":
                raise HTTPException(status_code=400, detail="Approve the reviewed Series canon before creating an episode")
            episode = create_series_episode(
                series, str(body.get("seasonId") or "") or None,
                **(body.get("episode") if isinstance(body.get("episode"), dict) else {}),
            )
            series["episodesById"][episode["id"]] = episode
            season = next(item for item in series["seasons"] if item["id"] == episode["seasonId"])
            season["episodeOrder"].append(episode["id"])
            series["revision"] = int(series.get("revision") or 1) + 1
            series["updatedAt"] = episode["updatedAt"]
            library["seriesById"][series_id] = series
            stored = _write_series(workspace, library)
        return stored["seriesById"][series_id]["episodesById"][episode["id"]]

    @router.get("/api/v1/series/{series_id}/episodes")
    def list_episodes(series_id: str, workspace: str | None = None):
        with _LOCK:
            series = _series_or_404(_read_series(_series_workspace(workspace)), series_id)
        ordered, seen = [], set()
        for season in series.get("seasons", []):
            if not isinstance(season, dict):
                continue
            for episode_id in season.get("episodeOrder", []):
                episode = series.get("episodesById", {}).get(episode_id)
                if isinstance(episode, dict) and episode_id not in seen:
                    ordered.append(copy.deepcopy(episode))
                    seen.add(episode_id)
        return {"episodes": ordered}

    @router.get("/api/v1/series/{series_id}/episodes/{episode_id}")
    def get_episode(series_id: str, episode_id: str, workspace: str | None = None):
        with _LOCK:
            series = _series_or_404(_read_series(_series_workspace(workspace)), series_id)
            episode = series.get("episodesById", {}).get(episode_id)
        if not isinstance(episode, dict):
            raise HTTPException(status_code=404, detail="Series episode not found")
        return copy.deepcopy(episode)

    @router.put("/api/v1/series/{series_id}/episodes/{episode_id}")
    def put_episode(series_id: str, episode_id: str, body: dict):
        from routers.series_episode import apply_series_episode_update

        workspace = _series_workspace(body.get("workspace"))
        with _LOCK:
            library = _read_series(workspace)
            series = _series_or_404(library, series_id)
            updated = apply_series_episode_update(series_id, episode_id, body, series, updated_at=_iso_now())
            library["seriesById"][series_id] = updated
            stored = _write_series(workspace, library)
        return stored["seriesById"][series_id]["episodesById"][episode_id]

    @router.delete("/api/v1/series/{series_id}/episodes/{episode_id}")
    def delete_episode(series_id: str, episode_id: str, workspace: str | None = None):
        target = _series_workspace(workspace)
        with _LOCK:
            library = _read_series(target)
            series = copy.deepcopy(_series_or_404(library, series_id))
            if episode_id not in series.get("episodesById", {}):
                raise HTTPException(status_code=404, detail="Series episode not found")
            del series["episodesById"][episode_id]
            for season in series.get("seasons", []):
                if isinstance(season, dict):
                    season["episodeOrder"] = [item for item in season.get("episodeOrder", []) if item != episode_id]
            series["revision"] = int(series.get("revision") or 1) + 1
            series["updatedAt"] = _iso_now()
            library["seriesById"][series_id] = series
            _write_series(target, library)
        return {"deleted": True, "episodeId": episode_id, "outputsPreserved": True}

    @router.post("/api/v1/series/{series_id}/canon/approve")
    def approve_canon(series_id: str, body: dict):
        workspace = _series_workspace(body.get("workspace"))
        try:
            base_revision = int(body.get("baseRevision"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="baseRevision is required") from exc
        with _LOCK:
            library = _read_series(workspace)
            series = copy.deepcopy(_series_or_404(library, series_id))
            canon = series["canon"]
            if int(canon.get("revision") or 1) != base_revision:
                raise HTTPException(status_code=409, detail="Canon revision changed; reload before approval")
            if not canon.get("worldSummary", "").strip() or not series.get("characters") or not series.get("locations"):
                raise HTTPException(status_code=400, detail="Complete the world, characters and locations before approving canon")
            if canon.get("approval") != "approved":
                canon["revision"] = base_revision + 1
            canon.update(approval="approved", approvedAt=_iso_now())
            for collection in ("characters", "locations", "props"):
                for entity in series.get(collection, []):
                    entity["approval"] = "approved"
            series["revision"] += 1
            series["updatedAt"] = _iso_now()
            library["seriesById"][series_id] = series
            stored = _write_series(workspace, library)
        return stored["seriesById"][series_id]

    @router.post("/api/v1/series/{series_id}/episodes/{episode_id}/references/refresh")
    def refresh_references(series_id: str, episode_id: str, body: dict):
        from services.series_production import refresh_episode_references
        from services.series_library import SeriesConflictError
        workspace = _series_workspace(body.get("workspace"))
        with _LOCK:
            library = _read_series(workspace)
            try:
                series = refresh_episode_references(_series_or_404(library, series_id), episode_id, int(body.get("baseRevision", -1)))
            except SeriesConflictError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            series["updatedAt"] = _iso_now()
            series["episodesById"][episode_id]["updatedAt"] = series["updatedAt"]
            library["seriesById"][series_id] = series
            stored = _write_series(workspace, library)
        return stored["seriesById"][series_id]

    @router.post("/api/v1/series/{series_id}/assets/import")
    def import_asset(series_id: str, body: dict):
        import shutil
        from services.series_production import attach_series_import, existing_generated_reference

        workspace = _series_workspace(body.get("workspace"))
        source_name = str(body.get("uploadPath") or "")
        source = core.safe_join(core.uploads_dir(), os.path.basename(source_name))
        if not source or not os.path.isfile(source):
            raise HTTPException(status_code=400, detail="Upload a file into HocusPocus before importing it")
        owner_type = str(body.get("ownerType") or "series")
        owner_id = str(body.get("ownerId") or series_id).strip()
        kind = str(body.get("kind") or "image")
        asset_id = f"asset_{os.urandom(6).hex()}"
        extension = os.path.splitext(source)[1].lower()[:12]
        relative = f"assets/{series_id}/{asset_id}{extension}"
        destination = core.safe_join(_dir(workspace), relative)
        if not destination:
            raise HTTPException(status_code=400, detail="Invalid Series asset destination")
        with _LOCK:
            library = _read_series(workspace)
            series = copy.deepcopy(_series_or_404(library, series_id))
            metadata = copy.deepcopy(body.get("metadata")) if isinstance(body.get("metadata"), dict) else {}
            if len(json.dumps(metadata, ensure_ascii=False).encode()) > 32 * 1024:
                raise HTTPException(status_code=413, detail="Series asset metadata is too large")
            existing = existing_generated_reference(series, owner_type, owner_id, metadata)
            if existing and body.get("asTake") is not True:
                return {"asset": existing, "series": series}
            asset = {
                "id": asset_id, "workspaceId": workspace, "kind": kind,
                "uri": relative, "ownerType": owner_type, "ownerId": owner_id,
                "isDerivedThumbnail": False,
                "metadata": {**metadata, "name": str(body.get("name") or os.path.basename(source))[:300],
                    "referenceRole": str(body.get("referenceRole") or "reference")[:100], "importedAt": _iso_now()},
            }
            try:
                attach_series_import(series, asset, as_take=body.get("asTake") is True, source_path=source)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(source, destination)
            series["revision"] = int(series.get("revision") or 1) + 1
            series["updatedAt"] = _iso_now()
            library["seriesById"][series_id] = series
            stored = _write_series(workspace, library)
        return {"asset": stored["seriesById"][series_id]["assets"][asset_id], "series": stored["seriesById"][series_id]}

    return router
