"""Global read model over output folders and versioned asset sidecars."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from .asset_manifest import (
    SCHEMA_NAME,
    AssetManifestError,
    adapt_legacy_sidecar,
    build_asset_manifest,
    infer_asset_kind,
    validate_asset_manifest,
)


# Sidecar JSON is the slow part of Desde HocusPocus. Keep one parsed
# manifest per file, keyed by the media file and its sidecar, and reread
# only the files that changed. Directory listing still happens every time
# so a new or deleted file shows up immediately.
_catalog_cache_lock = threading.Lock()
_catalog_cache: dict[str, dict[str, dict[str, Any]]] = {}
_catalog_cache_seen: dict[str, float] = {}
# One entry per workspace folder. The catalog scans every workspace on each
# request, so a cap below the workspace count would evict each folder just
# before it is needed again and the cache would never hit.
_CATALOG_CACHE_ROOTS = 256

MEDIA_EXTENSIONS = frozenset({
    ".aac", ".avi", ".flac", ".gif", ".glb", ".gltf", ".jpeg", ".jpg",
    ".m4a", ".mkv", ".mov", ".mp3", ".mp4", ".obj", ".ogg", ".pdf",
    ".ply", ".png", ".stl", ".txt", ".usdz", ".wav", ".webm", ".webp",
    ".zip",
})


def _stable_unmanaged_id(workspace_id: str, filename: str) -> str:
    value = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"hocuspocus:unmanaged:{workspace_id}:{filename}",
    )
    return f"asset_unmanaged_{value.hex}"


def _timestamp(value: Any, fallback: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return fallback


def _is_asset_file(name: str) -> bool:
    lowered = name.casefold()
    if (
        name.startswith((".", "_"))
        or lowered.endswith(".meta.json")
        or lowered.endswith(".preview.png")
    ):
        return False
    return (
        Path(name).suffix.casefold() in MEDIA_EXTENSIONS
        or lowered.endswith(".scene.json")
        or lowered.endswith(".comic.json")
    )


def _manifest_for(
    media_path: Path,
    workspace_id: str,
    modified_at: float,
) -> tuple[dict[str, Any], str]:
    sidecar = media_path.with_suffix(".meta.json")
    if sidecar.is_file():
        try:
            raw = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
            status = "unreadable"
        else:
            if isinstance(raw, Mapping) and raw.get("schema") == SCHEMA_NAME:
                try:
                    return validate_asset_manifest(raw), "canonical"
                except AssetManifestError:
                    status = "invalid"
            elif isinstance(raw, Mapping):
                return adapt_legacy_sidecar(
                    media_path, raw, workspace_id=workspace_id,
                ), "legacy"
            else:
                status = "invalid"
    else:
        status = "missing"
    manifest = build_asset_manifest(
        media_path,
        asset_id=_stable_unmanaged_id(workspace_id, media_path.name),
        kind=infer_asset_kind(media_path.name),
        workspace_id=workspace_id,
        tool="filesystem-import",
        actor="unknown",
        execution_mode="import",
        timing={"created_at": modified_at, "completed_at": modified_at},
        technical={"sidecar_status": status},
    )
    return manifest, status


def _prompt_preview(manifest: Mapping[str, Any]) -> str:
    generation = manifest.get("generation")
    prompts = generation.get("prompts") if isinstance(generation, Mapping) else None
    if not isinstance(prompts, Mapping):
        return ""
    for key in ("effective", "original", "audio"):
        value = str(prompts.get(key) or "").strip()
        if value:
            return value[:240]
    return ""


def _summary(
    manifest: Mapping[str, Any],
    *,
    workspace_id: str,
    filename: str,
    modified_at: float,
    size_bytes: int,
    metadata_status: str,
    include_manifest: bool,
) -> dict[str, Any]:
    asset = manifest.get("asset") if isinstance(manifest.get("asset"), Mapping) else {}
    origin = manifest.get("origin") if isinstance(manifest.get("origin"), Mapping) else {}
    execution = manifest.get("execution") if isinstance(manifest.get("execution"), Mapping) else {}
    generation = manifest.get("generation") if isinstance(manifest.get("generation"), Mapping) else {}
    model = generation.get("model") if isinstance(generation.get("model"), Mapping) else {}
    timing = manifest.get("timing") if isinstance(manifest.get("timing"), Mapping) else {}
    record = {
        "id": str(asset.get("id") or ""),
        "kind": str(asset.get("kind") or "other"),
        "filename": filename,
        "size_bytes": size_bytes,
        "created_at": _timestamp(timing.get("created_at"), modified_at),
        "completed_at": _timestamp(timing.get("completed_at"), modified_at),
        "metadata_status": metadata_status,
        "workspace_ids": [workspace_id],
        "locations": [{
            "workspace_id": workspace_id,
            "output_folder": origin.get("output_folder") or workspace_id,
            "filename": filename,
        }],
        "origin": {
            "tool": origin.get("tool") or "unknown",
            "capability": origin.get("capability"),
            "actor": origin.get("actor") or "unknown",
            "workspace_id": origin.get("workspace_id"),
            "output_folder": origin.get("output_folder") or workspace_id,
            "project": origin.get("project"),
            "production": origin.get("production"),
        },
        "execution": {
            "status": execution.get("status"),
            "mode": execution.get("mode"),
            "command_id": execution.get("command_id"),
            "workflow_id": execution.get("workflow_id"),
            "run_id": execution.get("run_id"),
            "task_id": execution.get("task_id"),
            "job_id": execution.get("job_id"),
            "pipeline_id": execution.get("pipeline_id"),
        },
        "model": {"provider": model.get("provider"), "id": model.get("id")},
        "prompt_preview": _prompt_preview(manifest),
    }
    if include_manifest:
        record["manifest"] = dict(manifest)
    return record


def _created_sort_parts(item: Mapping[str, Any]) -> tuple[bool, float, str]:
    created = item.get("created_at")
    missing = not isinstance(created, (int, float)) or float(created) <= 0
    stamp = 0.0 if missing else float(created)
    return missing, stamp, str(item.get("id") or "")


def _file_identity(path: str) -> tuple[int, int] | None:
    try:
        stat = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _remember_catalog_root(root: str, files: dict[str, dict[str, Any]]) -> None:
    now = time.monotonic()
    with _catalog_cache_lock:
        _catalog_cache[root] = files
        _catalog_cache_seen[root] = now
        while len(_catalog_cache) > _CATALOG_CACHE_ROOTS:
            oldest = min(_catalog_cache_seen, key=lambda key: _catalog_cache_seen[key])
            if oldest == root:
                others = [key for key in _catalog_cache_seen if key != root]
                if not others:
                    break
                oldest = min(others, key=lambda key: _catalog_cache_seen[key])
            _catalog_cache.pop(oldest, None)
            _catalog_cache_seen.pop(oldest, None)


def _manifest_cached(
    root: str,
    filename: str,
    media_path: Path,
    workspace_id: str,
    stat: os.stat_result,
    previous: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    sidecar = str(media_path.with_suffix(".meta.json"))
    # The manifest embeds the workspace id (unmanaged ids are scoped by it).
    identity = (stat.st_mtime_ns, stat.st_size, _file_identity(sidecar), workspace_id)
    cached = previous.get(filename)
    if cached and cached.get("identity") == identity:
        return cached["manifest"], cached["status"], cached
    manifest, status = _manifest_for(media_path, workspace_id, stat.st_mtime)
    record = {"identity": identity, "manifest": manifest, "status": status}
    return manifest, status, record


def _sort_catalog(values: list[dict[str, Any]], sort: str) -> None:
    mode = str(sort or "").strip().casefold()
    if mode in {"", "completed_desc"}:
        values.sort(key=lambda item: (item["completed_at"], str(item.get("id") or "")), reverse=True)
        return
    if mode == "created_desc":
        values.sort(key=lambda item: (
            _created_sort_parts(item)[0],
            -_created_sort_parts(item)[1],
            _created_sort_parts(item)[2],
        ))
        return
    if mode == "created_asc":
        values.sort(key=_created_sort_parts)
        return
    filename = lambda item: str(item.get("filename") or "").casefold()
    identifier = lambda item: str(item.get("id") or "")
    if mode == "name_asc":
        values.sort(key=lambda item: (filename(item), identifier(item)))
        return
    if mode == "name_desc":
        values.sort(key=identifier)
        values.sort(key=filename, reverse=True)
        return
    raise ValueError(f"Unknown catalog sort: {sort}")


def scan_asset_catalog(
    roots: Iterable[Mapping[str, Any]],
    *,
    search: str = "",
    kind: str = "",
    workspace_id: str = "",
    metadata_statuses: Iterable[str] = (),
    limit: int = 0,
    offset: int = 0,
    include_manifest: bool = False,
    sort: str = "",
) -> dict[str, Any]:
    """Scan explicit roots and aggregate copies sharing one canonical asset ID."""
    records: dict[str, dict[str, Any]] = {}
    seen_roots: set[str] = set()
    for root in roots:
        if not isinstance(root, Mapping):
            continue
        scope = str(root.get("workspace_id") or "").strip()
        directory = str(root.get("path") or "").strip()
        if not scope or not directory or (workspace_id and scope != workspace_id):
            continue
        resolved_root = os.path.realpath(os.path.abspath(directory))
        if resolved_root in seen_roots or not os.path.isdir(resolved_root):
            continue
        seen_roots.add(resolved_root)
        try:
            entries = list(os.scandir(resolved_root))
        except OSError:
            continue
        with _catalog_cache_lock:
            previous = dict(_catalog_cache.get(resolved_root) or {})
        fresh: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if not _is_asset_file(entry.name) or not entry.is_file(follow_symlinks=False):
                continue
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            media_path = Path(entry.path)
            manifest, metadata_status, record = _manifest_cached(
                resolved_root, entry.name, media_path, scope, stat, previous,
            )
            fresh[entry.name] = record
            item = _summary(
                manifest,
                workspace_id=scope,
                filename=entry.name,
                modified_at=stat.st_mtime,
                size_bytes=stat.st_size,
                metadata_status=metadata_status,
                include_manifest=include_manifest,
            )
            identifier = item["id"]
            current = records.get(identifier)
            if current is None:
                records[identifier] = item
                continue
            location = item["locations"][0]
            if location not in current["locations"]:
                current["locations"].append(location)
                if scope not in current["workspace_ids"]:
                    current["workspace_ids"].append(scope)
            if item["completed_at"] > current["completed_at"]:
                current.update({
                    key: value for key, value in item.items()
                    if key not in {"locations", "workspace_ids"}
                })
        _remember_catalog_root(resolved_root, fresh)

    values = list(records.values())
    wanted_kinds = {
        part.strip().casefold()
        for part in str(kind or "").split(",")
        if part.strip()
    }
    if wanted_kinds:
        values = [item for item in values if item["kind"] in wanted_kinds]
    wanted_statuses = {str(item).strip().casefold() for item in metadata_statuses if str(item).strip()}
    if wanted_statuses:
        values = [item for item in values if item["metadata_status"] in wanted_statuses]
    needle = str(search or "").strip().casefold()
    if needle:
        values = [item for item in values if needle in " ".join((
            item["filename"],
            str(item["origin"].get("tool") or ""),
            str(item["origin"].get("capability") or ""),
            str(item["model"].get("id") or ""),
            item["prompt_preview"],
        )).casefold()]
    _sort_catalog(values, sort)
    total = len(values)
    start = max(0, int(offset or 0))
    if limit and int(limit) > 0:
        values = values[start:start + int(limit)]
    elif start:
        values = values[start:]
    return {"assets": values, "total": total}


def find_asset(
    roots: Iterable[Mapping[str, Any]],
    asset_id: str,
) -> dict[str, Any] | None:
    result = scan_asset_catalog(roots, include_manifest=True)
    return next((item for item in result["assets"] if item["id"] == asset_id), None)


__all__ = ["MEDIA_EXTENSIONS", "find_asset", "scan_asset_catalog"]
