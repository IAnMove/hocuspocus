"""Canonical project read model over the existing durable domain stores.

The catalog is deliberately an index. Story Lab, Series Lab, Comics and
Video3D scenes remain authoritative in their current stores while callers get
one portable identity contract that never exposes host paths.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .character_kit_library import normalize_character_kit_library
from .series_library import normalize_series_library
from .story_library import normalize_story_library


SCHEMA_NAME = "hocuspocus.project-record"
SCHEMA_VERSION = 1
PROJECT_KINDS = frozenset({
    "story", "series", "episode", "comic", "scene3d", "character_kit",
    "video_editor",
})


class ProjectCatalogError(ValueError):
    """A source cannot be represented without violating project identity."""


def _text(value: Any, fallback: str = "") -> str:
    result = str(value or "").strip()
    return result or fallback


def _iso(value: Any, fallback_timestamp: float | None = None) -> str | None:
    if value not in (None, ""):
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                parsed = None
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            fallback_timestamp = float(value)
    if fallback_timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(
            fallback_timestamp, timezone.utc,
        ).isoformat().replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError):
        return None


def _legacy_id(kind: str, workspace_id: str, source_key: str) -> str:
    value = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"hocuspocus:project:{kind}:{workspace_id}:{source_key}",
    )
    return f"project_legacy_{value.hex}"


def build_project_record(
    *,
    project_id: str,
    kind: str,
    title: str,
    workspace_id: str,
    adapter: str,
    source_key: str,
    subtype: str | None = None,
    revision: int | None = None,
    created_at: Any = None,
    updated_at: Any = None,
    fallback_timestamp: float | None = None,
    parent: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    identifier = _text(project_id)
    resolved_kind = _text(kind).casefold()
    scope = _text(workspace_id)
    if not identifier or len(identifier) > 240:
        raise ProjectCatalogError("Project record requires a bounded immutable ID")
    if resolved_kind not in PROJECT_KINDS:
        raise ProjectCatalogError(f"Unsupported project kind: {resolved_kind}")
    if not scope:
        raise ProjectCatalogError("Project record requires an explicit workspace source")
    clean_revision = revision if isinstance(revision, int) and not isinstance(revision, bool) and revision >= 0 else None
    parent_value = None
    if isinstance(parent, Mapping):
        parent_id = _text(parent.get("id"))
        parent_kind = _text(parent.get("kind")).casefold()
        if parent_id and parent_kind in PROJECT_KINDS:
            parent_value = {"id": parent_id, "kind": parent_kind}
    created = _iso(created_at, fallback_timestamp)
    updated = _iso(updated_at, fallback_timestamp) or created
    return {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "id": identifier,
        "kind": resolved_kind,
        "subtype": _text(subtype) or None,
        "title": _text(title, "Untitled project"),
        "revision": clean_revision,
        "created_at": created,
        "updated_at": updated,
        "parent": parent_value,
        "workspace_ids": [scope],
        "sources": [{
            "workspace_id": scope,
            "adapter": _text(adapter, "unknown"),
            "key": _text(source_key, identifier),
        }],
        "metadata": dict(metadata or {}),
    }


def validate_project_record(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectCatalogError("Project record must be an object")
    if value.get("schema") != SCHEMA_NAME or value.get("schema_version") != SCHEMA_VERSION:
        raise ProjectCatalogError("Unsupported project record schema")
    if not _text(value.get("id")) or value.get("kind") not in PROJECT_KINDS:
        raise ProjectCatalogError("Project record has invalid identity")
    workspaces = value.get("workspace_ids")
    sources = value.get("sources")
    if not isinstance(workspaces, list) or not workspaces or not all(_text(item) for item in workspaces):
        raise ProjectCatalogError("Project record has no workspace sources")
    if not isinstance(sources, list) or not sources:
        raise ProjectCatalogError("Project record has no source locator")
    return dict(value)


def adapt_story_library(value: Any, workspace_id: str) -> list[dict[str, Any]]:
    library = normalize_story_library(value)
    records = []
    for project in library["projects"].values():
        identifier = _text(project.get("id"))
        records.append(build_project_record(
            project_id=identifier,
            kind="story",
            subtype=_text(project.get("projectType")) or None,
            title=_text(project.get("title"), "Untitled story"),
            revision=project.get("revision"),
            created_at=project.get("createdAt"),
            updated_at=project.get("updatedAt"),
            workspace_id=workspace_id,
            adapter="story-library-v2",
            source_key=f"story:{identifier}",
            metadata={
                "active": identifier == library.get("activeId"),
                "library_revision": library.get("revision"),
            },
        ))
    return records


def adapt_series_library(value: Any, workspace_id: str) -> list[dict[str, Any]]:
    library = normalize_series_library(value, workspace_id)
    records = []
    for series in library["seriesById"].values():
        identifier = _text(series.get("id"))
        episodes = series.get("episodesById") if isinstance(series.get("episodesById"), Mapping) else {}
        records.append(build_project_record(
            project_id=identifier,
            kind="series",
            title=_text(series.get("title"), "Untitled series"),
            revision=series.get("revision"),
            created_at=series.get("createdAt"),
            updated_at=series.get("updatedAt"),
            workspace_id=workspace_id,
            adapter="series-library-v1",
            source_key=f"series:{identifier}",
            metadata={"episode_count": len(episodes)},
        ))
        for episode in episodes.values():
            episode_id = _text(episode.get("id"))
            if not episode_id:
                continue
            records.append(build_project_record(
                project_id=episode_id,
                kind="episode",
                subtype="series_episode",
                title=_text(episode.get("title"), "Untitled episode"),
                revision=episode.get("revision"),
                created_at=episode.get("createdAt"),
                updated_at=episode.get("updatedAt"),
                workspace_id=workspace_id,
                adapter="series-library-v1",
                source_key=f"series:{identifier}:episode:{episode_id}",
                parent={"kind": "series", "id": identifier},
                metadata={
                    "season_id": _text(episode.get("seasonId")) or None,
                    "status": _text(episode.get("status")) or None,
                },
            ))
    return records


def adapt_character_kit_library(value: Any, workspace_id: str) -> list[dict[str, Any]]:
    library = normalize_character_kit_library(value)
    records = []
    for kit in library["kits"].values():
        identifier = _text(kit.get("id"))
        records.append(build_project_record(
            project_id=identifier,
            kind="character_kit",
            subtype=_text(kit.get("style")) or None,
            title=_text(kit.get("name"), "Untitled character kit"),
            created_at=kit.get("createdAt"),
            updated_at=kit.get("updatedAt"),
            workspace_id=workspace_id,
            adapter="character-kit-library-v1",
            source_key=f"character-kit:{identifier}",
            metadata={
                "active": identifier == library.get("activeId"),
                "library_revision": library.get("revision"),
                "pose_count": len(kit.get("poses") or {}),
            },
        ))
    return records


def adapt_project_file(
    filename: str,
    value: Any,
    workspace_id: str,
    *,
    modified_at: float | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectCatalogError("Project file must contain an object")
    lowered = filename.casefold()
    if lowered.endswith(".comic.json"):
        kind, adapter = "comic", "comic-file-v2"
        title = _text(value.get("title"), "Untitled comic")
        metadata = {"page_count": len(value.get("pages") or [])}
    elif lowered.endswith(".scene.json"):
        kind, adapter = "scene3d", "scene-file-v1"
        title = _text(value.get("name"), "Untitled scene")
        metadata = {"layer_count": len(value.get("layers") or [])}
    else:
        raise ProjectCatalogError("Unsupported project file")
    identifier = _text(value.get("id")) or _legacy_id(kind, workspace_id, filename)
    return build_project_record(
        project_id=identifier,
        kind=kind,
        title=title,
        revision=value.get("revision"),
        created_at=value.get("createdAt"),
        updated_at=value.get("updatedAt"),
        fallback_timestamp=modified_at,
        workspace_id=workspace_id,
        adapter=adapter,
        source_key=filename,
        metadata=metadata,
    )


def _merge_record(current: dict[str, Any], candidate: dict[str, Any]) -> None:
    for workspace in candidate["workspace_ids"]:
        if workspace not in current["workspace_ids"]:
            current["workspace_ids"].append(workspace)
    for source in candidate["sources"]:
        if source not in current["sources"]:
            current["sources"].append(source)
    if _text(candidate.get("updated_at")) > _text(current.get("updated_at")):
        for key in ("title", "subtype", "revision", "created_at", "updated_at", "parent", "metadata"):
            current[key] = candidate.get(key)


def scan_project_catalog(
    roots: Iterable[Mapping[str, Any]],
    *,
    search: str = "",
    kind: str = "",
    workspace_id: str = "",
    limit: int = 0,
    offset: int = 0,
) -> dict[str, Any]:
    """Read all supported stores below explicit workspace roots."""
    records: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, str]] = []

    def register(record: dict[str, Any], scope: str) -> None:
        identifier = record["id"]
        current = records.get(identifier)
        if current is None:
            records[identifier] = record
        elif current["kind"] != record["kind"]:
            warnings.append({
                "workspace_id": scope,
                "source": record["sources"][0]["key"],
                "error": "project_id_collision",
            })
        else:
            _merge_record(current, record)

    seen_roots: set[str] = set()
    for root in roots:
        if not isinstance(root, Mapping):
            continue
        scope = _text(root.get("workspace_id"))
        directory = _text(root.get("path"))
        if not scope or not directory or (workspace_id and scope != workspace_id):
            continue
        resolved = os.path.realpath(os.path.abspath(directory))
        if resolved in seen_roots or not os.path.isdir(resolved):
            continue
        seen_roots.add(resolved)
        sources = (
            (".story-library-v1.json", adapt_story_library),
            (".series-library-v1.json", adapt_series_library),
            (".character-kit-library-v1.json", adapt_character_kit_library),
        )
        for filename, adapter in sources:
            path = Path(resolved, filename)
            if not path.is_file():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                for record in adapter(raw, scope):
                    register(record, scope)
            except (OSError, ValueError, TypeError) as exc:
                warnings.append({
                    "workspace_id": scope,
                    "source": filename,
                    "error": type(exc).__name__,
                })
        try:
            entries = list(os.scandir(resolved))
        except OSError:
            continue
        for entry in entries:
            lowered = entry.name.casefold()
            if not lowered.endswith((".comic.json", ".scene.json")) or not entry.is_file(follow_symlinks=False):
                continue
            try:
                stat = entry.stat(follow_symlinks=False)
                raw = json.loads(Path(entry.path).read_text(encoding="utf-8"))
                register(adapt_project_file(
                    entry.name, raw, scope, modified_at=stat.st_mtime,
                ), scope)
            except (OSError, ValueError, TypeError) as exc:
                warnings.append({
                    "workspace_id": scope,
                    "source": entry.name,
                    "error": type(exc).__name__,
                })

    values = list(records.values())
    wanted_kind = _text(kind).casefold()
    if wanted_kind:
        if wanted_kind not in PROJECT_KINDS:
            raise ProjectCatalogError(f"Unsupported project kind: {wanted_kind}")
        values = [item for item in values if item["kind"] == wanted_kind]
    needle = _text(search).casefold()
    if needle:
        values = [item for item in values if needle in " ".join((
            item["title"], item["id"], _text(item.get("subtype")),
        )).casefold()]
    values.sort(key=lambda item: (_text(item.get("updated_at")), item["id"]), reverse=True)
    total = len(values)
    start = max(0, int(offset or 0))
    end = start + int(limit) if limit and int(limit) > 0 else None
    return {"projects": values[start:end], "total": total, "warnings": warnings}


def find_project(
    roots: Iterable[Mapping[str, Any]],
    project_id: str,
) -> dict[str, Any] | None:
    result = scan_project_catalog(roots)
    return next((item for item in result["projects"] if item["id"] == project_id), None)


__all__ = [
    "PROJECT_KINDS", "SCHEMA_NAME", "SCHEMA_VERSION", "ProjectCatalogError",
    "adapt_character_kit_library", "adapt_project_file", "adapt_series_library",
    "adapt_story_library",
    "build_project_record", "find_project", "scan_project_catalog",
    "validate_project_record",
]
