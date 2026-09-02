"""Canonical Production and Run read models for legacy Director pipelines."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any


PRODUCTION_SCHEMA = "hocuspocus.production-record"
RUN_SCHEMA = "hocuspocus.run-record"
SCHEMA_VERSION = 1


def _text(value: Any, fallback: str = "") -> str:
    result = str(value or "").strip()
    return result or fallback


def _stable_id(kind: str, pipeline_id: str) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, f"hocuspocus:{kind}:director:{pipeline_id}")
    return f"{kind}_legacy_{value.hex}"


def _integer(value: Any, fallback: int = 0) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            parsed = datetime.fromtimestamp(float(value), timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    else:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _project_ref(value: Mapping[str, Any]) -> dict[str, str] | None:
    candidates = (
        ("project", value.get("project_id")),
        ("story", value.get("story_id")),
        ("comic", value.get("comic_id")),
        ("episode", value.get("episode_id")),
        ("series", value.get("series_id")),
    )
    for kind, identifier in candidates:
        token = _text(identifier)
        if token:
            return {"kind": kind, "id": token}
    return None


def adapt_pipeline_record(value: Mapping[str, Any], workspace_id: str = "default") -> dict[str, Any]:
    """Split one legacy pipeline snapshot into a production and one run."""
    if not isinstance(value, Mapping):
        raise ValueError("Pipeline snapshot must be an object")
    pipeline_id = _text(value.get("pipeline_id") or value.get("id"))
    if not pipeline_id:
        raise ValueError("Pipeline snapshot has no identity")
    workspace = _text(value.get("workspace"), _text(workspace_id, "default"))
    production_id = _text(value.get("production_id")) or _stable_id("production", pipeline_id)
    run_id = _text(value.get("run_id")) or _stable_id("run", pipeline_id)
    pipeline_type = _text(value.get("pipeline_type"), "director")
    created_at = _iso(value.get("created_at"))
    updated_at = _iso(value.get("updated_at")) or _iso(value.get("completed_at")) or created_at
    completed_at = _iso(value.get("completed_at"))
    status = _text(value.get("status"), "unknown").casefold()
    title = _text(value.get("title") or value.get("scene_description"))
    if not title:
        title = pipeline_type.replace("_", " ").title()
    production = {
        "schema": PRODUCTION_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "id": production_id,
        "kind": pipeline_type,
        "title": title,
        "project": _project_ref(value),
        "workspace_ids": [workspace],
        "created_at": created_at,
        "updated_at": updated_at,
        "plan": {
            "clip_count": max(0, _integer(value.get("clip_count"))),
            "generation_mode": _text(value.get("generation_mode")) or None,
        },
        "run_ids": [run_id],
    }
    run = {
        "schema": RUN_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "id": run_id,
        "production_id": production_id,
        "attempt": max(1, _integer(value.get("attempt"), 1)),
        "status": status,
        "phase": _text(value.get("phase"), status),
        "workspace_id": workspace,
        "created_at": created_at,
        "started_at": _iso(value.get("started_at")) or created_at,
        "updated_at": updated_at,
        "completed_at": completed_at,
        "correlations": {
            "pipeline_id": pipeline_id,
            "task_id": _text(value.get("task_id")) or None,
            "job_id": _text(value.get("job_id")) or None,
        },
        "output_count": max(0, _integer(value.get("output_count"), len(value.get("output_files") or []))),
        "error": _text(value.get("error")) or None,
    }
    return {"production": production, "run": run}


def build_production_run_catalog(
    pipelines: Iterable[Mapping[str, Any]],
    workspace_id: str = "default",
) -> dict[str, Any]:
    productions: dict[str, dict[str, Any]] = {}
    runs: dict[str, dict[str, Any]] = {}
    for pipeline in pipelines:
        adapted = adapt_pipeline_record(pipeline, workspace_id)
        production = adapted["production"]
        run = adapted["run"]
        current = productions.get(production["id"])
        if current is None:
            productions[production["id"]] = production
        else:
            if run["id"] not in current["run_ids"]:
                current["run_ids"].append(run["id"])
            if _text(production.get("updated_at")) > _text(current.get("updated_at")):
                for key in ("title", "project", "updated_at", "plan"):
                    current[key] = production[key]
            for workspace in production["workspace_ids"]:
                if workspace not in current["workspace_ids"]:
                    current["workspace_ids"].append(workspace)
        runs[run["id"]] = run
    production_values = sorted(
        productions.values(), key=lambda item: (_text(item.get("updated_at")), item["id"]), reverse=True,
    )
    run_values = sorted(
        runs.values(), key=lambda item: (_text(item.get("updated_at")), item["id"]), reverse=True,
    )
    return {"productions": production_values, "runs": run_values}


__all__ = [
    "PRODUCTION_SCHEMA", "RUN_SCHEMA", "SCHEMA_VERSION",
    "adapt_pipeline_record", "build_production_run_catalog",
]
