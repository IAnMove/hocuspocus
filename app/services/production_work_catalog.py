"""One catalog row per production, read from the stores that already exist.

Titles are not identities. A link, a production file, a story row and a
Director snapshot that share a production id are the same work.
"""

from __future__ import annotations

import json
import os
from typing import Any

from services.production_project_link import read_link_store, refresh_link_status
from services.production_run import adapt_pipeline_record


def list_works(
    workspace_dir: str,
    workspace_id: str,
    *,
    pipelines: list[dict[str, Any]] | None = None,
    form: str = "",
    status: str = "",
    limit: int = 0,
    offset: int = 0,
) -> dict[str, Any]:
    refresh_link_status(workspace_dir)
    rows: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, str]] = []
    _from_files(workspace_dir, workspace_id, rows, warnings)
    _from_links(workspace_dir, workspace_id, rows)
    _from_stories(workspace_dir, workspace_id, rows, warnings)
    _from_pipelines(workspace_id, pipelines or [], rows, warnings)
    _from_director_files(workspace_dir, workspace_id, rows, warnings)
    values = list(rows.values())
    if form:
        values = [item for item in values if item.get("format") == form]
    if status:
        values = [item for item in values if item.get("status") == status]
    values.sort(key=lambda item: (str(item.get("updated_at") or ""), item["production_id"]), reverse=True)
    total = len(values)
    start = max(0, int(offset or 0))
    end = start + int(limit) if limit and int(limit) > 0 else None
    return {"works": values[start:end], "total": total, "warnings": warnings}


def find_work(workspace_dir: str, workspace_id: str, production_id: str) -> dict[str, Any] | None:
    listed = list_works(workspace_dir, workspace_id)
    return next((item for item in listed["works"] if item["production_id"] == production_id), None)


def _from_files(workspace_dir: str, workspace_id: str, rows: dict[str, dict], warnings: list[dict[str, str]]) -> None:
    try:
        names = os.listdir(workspace_dir)
    except OSError as error:
        warnings.append({"source": "workspace", "error": type(error).__name__})
        return
    for name in names:
        if not name.endswith(".production.json"):
            continue
        production_id = name[: -len(".production.json")]
        if not production_id:
            continue
        body = _json_file(os.path.join(workspace_dir, name))
        if body is None:
            warnings.append({"source": name, "error": "unreadable"})
            continue
        # Episode media lives in the series library. A leftover
        # ``.production.json`` is not the render, so its pending status must
        # not enter the catalog even when its timestamp is newer than the link.
        project = _project(body.get("project"))
        if project and project.get("kind") == "episode":
            continue
        _merge(rows, _file_row(workspace_id, production_id, body))


def _from_links(workspace_dir: str, workspace_id: str, rows: dict[str, dict]) -> None:
    store = read_link_store(workspace_dir)
    for record in store["links"].values():
        if not isinstance(record, dict) or record.get("workspace_id") not in (None, "", workspace_id):
            continue
        for production_id in record.get("production_ids") or []:
            if not isinstance(production_id, str) or not production_id:
                continue
            _merge(rows, _link_row(workspace_id, production_id, record))


def _from_stories(workspace_dir: str, workspace_id: str, rows: dict[str, dict], warnings: list[dict[str, str]]) -> None:
    from services.story_library import read_story_library

    try:
        library = read_story_library(workspace_dir)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        warnings.append({"source": ".story-library-v1.json", "error": type(error).__name__})
        return
    for project in library["projects"].values():
        project_id = str(project.get("id") or "")
        for item in project.get("productions") or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            _merge(rows, _story_row(workspace_id, project, item, project_id))


def _from_pipelines(workspace_id: str, pipelines: list[dict[str, Any]], rows: dict[str, dict], warnings: list[dict[str, str]]) -> None:
    for pipeline in pipelines:
        if not isinstance(pipeline, dict):
            continue
        if str(pipeline.get("workspace") or workspace_id) not in ("", workspace_id):
            continue
        try:
            adapted = adapt_pipeline_record(pipeline, workspace_id)
        except ValueError as error:
            warnings.append({"source": "pipeline", "error": type(error).__name__})
            continue
        _merge(rows, _pipeline_row(workspace_id, adapted["production"]))


def _from_director_files(workspace_dir: str, workspace_id: str, rows: dict[str, dict], warnings: list[dict[str, str]]) -> None:
    try:
        names = os.listdir(workspace_dir)
    except OSError:
        return
    for name in names:
        if not name.startswith("_director_pipeline_") or not name.endswith(".json"):
            continue
        body = _json_file(os.path.join(workspace_dir, name))
        if body is None:
            warnings.append({"source": name, "error": "unreadable"})
            continue
        body.setdefault("workspace", workspace_id)
        _from_pipelines(workspace_id, [body], rows, warnings)


def _file_row(workspace_id: str, production_id: str, body: dict[str, Any]) -> dict[str, Any]:
    spec = body.get("spec") if isinstance(body.get("spec"), dict) else {}
    project = _project(body.get("project"))
    return _row(
        workspace_id=workspace_id,
        production_id=production_id,
        title=str(spec.get("title") or body.get("title") or production_id),
        status=str(body.get("status") or "unknown"),
        origin=str(body.get("origin") or "file"),
        form=body.get("format") if isinstance(body.get("format"), str) else None,
        project=project,
        linked=project is not None,
        updated_at=body.get("updated_at") if isinstance(body.get("updated_at"), str) else None,
        preview=_preview(body.get("contact_sheet")),
    )


def _link_row(workspace_id: str, production_id: str, record: dict[str, Any]) -> dict[str, Any]:
    project = _project(record.get("project"))
    return _row(
        workspace_id=workspace_id,
        production_id=production_id,
        title=str(record.get("title") or production_id),
        status=str(record.get("status") or "pending"),
        origin=str(record.get("origin") or "link"),
        form=record.get("format") if isinstance(record.get("format"), str) else None,
        project=project,
        linked=project is not None,
        updated_at=record.get("updated_at") if isinstance(record.get("updated_at"), str) else None,
        preview=None,
    )


def _story_row(workspace_id: str, project: dict[str, Any], item: dict[str, Any], project_id: str) -> dict[str, Any]:
    kind = item.get("kind") if item.get("kind") in {"music_video", "trailer", "film"} else None
    form = project.get("projectType") if isinstance(project.get("projectType"), str) else kind
    return _row(
        workspace_id=workspace_id,
        production_id=str(item["id"]),
        title=str(item.get("title") or project.get("title") or item["id"]),
        status=str(item.get("status") or "unknown"),
        origin="story",
        form=form,
        project={"kind": "story", "id": project_id},
        linked=True,
        updated_at=project.get("updatedAt") if isinstance(project.get("updatedAt"), str) else None,
        preview=None,
    )


def _pipeline_row(workspace_id: str, production: dict[str, Any]) -> dict[str, Any]:
    project = _project(production.get("project"))
    return _row(
        workspace_id=workspace_id,
        production_id=str(production["id"]),
        title=str(production.get("title") or production["id"]),
        status="unknown",
        origin="director",
        form=str(production.get("kind") or "") or None,
        project=project,
        linked=project is not None,
        updated_at=production.get("updated_at") if isinstance(production.get("updated_at"), str) else None,
        preview=None,
    )


def _row(**fields: Any) -> dict[str, Any]:
    return {
        "workspace_id": fields["workspace_id"],
        "production_id": fields["production_id"],
        "title": fields["title"],
        "status": fields["status"],
        "origin": fields["origin"],
        "format": fields["form"],
        "project": fields["project"],
        "linked": fields["linked"],
        "updated_at": fields["updated_at"],
        "preview": fields["preview"],
    }


def _merge(rows: dict[str, dict], candidate: dict[str, Any]) -> None:
    current = rows.get(candidate["production_id"])
    if current is None:
        rows[candidate["production_id"]] = candidate
        return
    previous_at = current.get("updated_at")
    for key in ("title", "status", "origin", "format", "project", "updated_at", "preview"):
        if _empty(current.get(key)) and not _empty(candidate.get(key)):
            current[key] = candidate[key]
    current["linked"] = current.get("project") is not None or candidate["linked"]
    # Compare against the timestamp that arrived with this row. Filling an empty
    # updated_at above would otherwise make a later completed link look "the same
    # age" as a pending file and leave the catalog unfinished.
    if candidate.get("updated_at") and str(candidate.get("updated_at")) > str(previous_at or ""):
        current["updated_at"] = candidate["updated_at"]
        if candidate.get("status") not in (None, "", "unknown", "draft", "pending"):
            current["status"] = candidate["status"]
    # Episode status lives on the link. A leftover pending file with a newer
    # timestamp must not hide running or completed.
    if _episode_kind(current.get("project")) or _episode_kind(candidate.get("project")):
        if _weak_status(current.get("status")) and not _weak_status(candidate.get("status")):
            current["status"] = candidate["status"]


def _project(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    kind = str(value.get("kind") or "").strip()
    identifier = str(value.get("id") or "").strip()
    if not kind or not identifier:
        return None
    return {"kind": kind, "id": identifier}


def _preview(value: Any) -> str | None:
    if not isinstance(value, str) or not value or "/" in value or ".." in value:
        return None
    return value


def _json_file(path: str) -> dict[str, Any] | None:
    try:
        body = json.loads(open(path, encoding="utf-8").read())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _empty(value: Any) -> bool:
    return value in (None, "", [], {})


def _episode_kind(project: Any) -> bool:
    return isinstance(project, dict) and project.get("kind") == "episode"


def _weak_status(status: Any) -> bool:
    return status in (None, "", "unknown", "draft", "pending")


__all__ = ["find_work", "list_works"]
