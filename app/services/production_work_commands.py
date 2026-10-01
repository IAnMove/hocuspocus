"""List, open, and resolve a work without starting a generator.

The catalog rows stay the records that already exist. This module only adds
the review event the UI already listens for.
"""

from __future__ import annotations

import json
from typing import Any

from services.production_project_link import (
    REVIEW_EVENT,
    link_existing_production,
    read_link_store,
    resolve_production_project,
)
from services.production_work_catalog import find_work, list_works


class WorkCommandError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_OPERATIONS = frozenset({
    "production.works.list",
    "production.works.open",
    "production.works.resolve",
    "production.works.link",
})


def command_catalog() -> list[dict[str, str]]:
    return [{"name": name} for name in sorted(_OPERATIONS)]


def run_command(workspace_dir: str, body: dict[str, Any]) -> dict[str, Any]:
    operation, data = _envelope(body)
    workspace_id = _workspace(data)
    if operation == "production.works.list":
        return _list(workspace_dir, workspace_id, data)
    if operation == "production.works.open":
        return _open(workspace_dir, workspace_id, data)
    if operation == "production.works.link":
        return _link(workspace_dir, workspace_id, data)
    return _resolve(workspace_dir, workspace_id, data)


def _envelope(body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(body, dict) or body.get("version") != 1:
        raise WorkCommandError("invalid_request", "version must be 1")
    operation = body.get("operation")
    if operation not in _OPERATIONS:
        raise WorkCommandError("unknown_operation", "Unknown production works operation")
    data = body.get("input")
    if not isinstance(data, dict):
        raise WorkCommandError("invalid_request", "input must be an object")
    return str(operation), data


def _workspace(data: dict[str, Any]) -> str:
    workspace_id = str(data.get("workspace") or "").strip()
    if not workspace_id or len(workspace_id) > 160:
        raise WorkCommandError("invalid_request", "workspace is required")
    return workspace_id


def _list(workspace_dir: str, workspace_id: str, data: dict[str, Any]) -> dict[str, Any]:
    listed = list_works(
        workspace_dir,
        workspace_id,
        form=_filter(data, "format"),
        status=_filter(data, "status"),
    )
    series_ids = _series_map(workspace_dir, workspace_id)
    works = [_annotate(item, series_ids) for item in listed["works"]]
    return {"applied": False, "works": works, "total": listed["total"], "warnings": listed["warnings"]}


def _open(workspace_dir: str, workspace_id: str, data: dict[str, Any]) -> dict[str, Any]:
    production_id = str(data.get("production_id") or "").strip()
    if not production_id or len(production_id) > 240:
        raise WorkCommandError("invalid_request", "production_id is required")
    found = find_work(workspace_dir, workspace_id, production_id)
    if found is None:
        raise WorkCommandError("not_found", "Production not found")
    return {"applied": False, "work": _annotate(found, _series_map(workspace_dir, workspace_id))}


def _resolve(workspace_dir: str, workspace_id: str, data: dict[str, Any]) -> dict[str, Any]:
    intent = data.get("intent_id")
    existed = _intent_exists(workspace_dir, intent)
    record = resolve_production_project(workspace_dir, {**data, "workspace": workspace_id})
    found = find_work(workspace_dir, workspace_id, str(record["production_id"]))
    work = _annotate(found, _series_map(workspace_dir, workspace_id)) if found else None
    return {
        "applied": True,
        "reused": existed and data.get("new_execution") is not True,
        "production_id": record["production_id"],
        "project": record["project"],
        "origin": record["origin"],
        "review": record["review"],
        "work": work,
    }


def _link(workspace_dir: str, workspace_id: str, data: dict[str, Any]) -> dict[str, Any]:
    record = link_existing_production(workspace_dir, {**data, "workspace": workspace_id})
    found = find_work(workspace_dir, workspace_id, str(record["production_id"]))
    work = _annotate(found, _series_map(workspace_dir, workspace_id)) if found else None
    return {
        "applied": True,
        "reused": record.get("reused") is True,
        "production_id": record["production_id"],
        "project": record["project"],
        "origin": record["origin"],
        "review": record["review"],
        "work": work,
    }


def _intent_exists(workspace_dir: str, intent: Any) -> bool:
    if not isinstance(intent, str) or not intent:
        return False
    try:
        store = read_link_store(workspace_dir)
    except (OSError, ValueError):
        return False
    return isinstance(store.get("links", {}).get(intent), dict)


def _filter(data: dict[str, Any], key: str) -> str:
    value = data.get(key) or ""
    if not isinstance(value, str) or len(value) > 40:
        raise WorkCommandError("invalid_request", f"{key} is invalid")
    return value


def _annotate(item: dict[str, Any], series_ids: dict[str, str]) -> dict[str, Any]:
    project = item.get("project") if isinstance(item.get("project"), dict) else None
    series_id = series_ids.get(str(project.get("id"))) if project and project.get("kind") == "episode" else None
    review = {
        "event": REVIEW_EVENT,
        "workspace": item["workspace_id"],
        "production_id": item["production_id"],
        "project": project,
    }
    if series_id:
        review["series_id"] = series_id
    return {**item, "series_id": series_id, "review": review}


def _series_map(workspace_dir: str, workspace_id: str) -> dict[str, str]:
    from services.series_library import read_series_library

    try:
        library = read_series_library(workspace_dir, workspace_id)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    series_by_id = library.get("seriesById") if isinstance(library, dict) else None
    if not isinstance(series_by_id, dict):
        return {}
    found: dict[str, str] = {}
    for series_id, series in series_by_id.items():
        episodes = series.get("episodesById") if isinstance(series, dict) else None
        if not isinstance(episodes, dict):
            continue
        for episode_id in episodes:
            if isinstance(episode_id, str) and episode_id not in found:
                found[episode_id] = str(series_id)
    return found


__all__ = ["WorkCommandError", "run_command"]
