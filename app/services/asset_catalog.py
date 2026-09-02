"""Global read model over output folders and versioned asset sidecars."""

from __future__ import annotations

import json
import os
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
        for entry in entries:
            if not _is_asset_file(entry.name) or not entry.is_file(follow_symlinks=False):
                continue
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            media_path = Path(entry.path)
            manifest, metadata_status = _manifest_for(media_path, scope, stat.st_mtime)
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

    values = list(records.values())
    wanted_kind = str(kind or "").strip().casefold()
    if wanted_kind:
        values = [item for item in values if item["kind"] == wanted_kind]
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
    values.sort(key=lambda item: (item["completed_at"], item["id"]), reverse=True)
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
