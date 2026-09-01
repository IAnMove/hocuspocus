"""Versioned, portable provenance manifests for generated and imported assets."""

from __future__ import annotations

import json
import math
import mimetypes
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_NAME = "hocuspocus.asset-manifest"
SCHEMA_VERSION = 1
ASSET_KINDS = frozenset({
    "image", "audio", "video", "scene", "model3d", "document", "other",
})
EXECUTION_STATUSES = frozenset({
    "prepared", "queued", "running", "completed", "partial", "failed", "cancelled",
})
EXECUTION_MODES = frozenset({"real", "plan", "simulate", "import"})
_CANONICAL_FIELDS = (
    "schema", "schema_version", "asset", "origin", "execution", "generation",
    "timing", "lineage", "technical",
)
_SENSITIVE_KEYS = frozenset({
    "api_key", "apikey", "authorization", "credential", "credentials",
    "password", "secret", "token", "access_token", "refresh_token",
    "bearer_token", "auth_token", "private_key",
})
_KIND_BY_EXTENSION = {
    ".aac": "audio", ".flac": "audio", ".m4a": "audio", ".mp3": "audio",
    ".ogg": "audio", ".wav": "audio", ".gif": "image", ".jpeg": "image",
    ".jpg": "image", ".png": "image", ".webp": "image", ".avi": "video",
    ".mkv": "video", ".mov": "video", ".mp4": "video", ".webm": "video",
    ".glb": "model3d", ".gltf": "model3d", ".obj": "model3d", ".fbx": "model3d",
    ".json": "document", ".md": "document", ".pdf": "document", ".txt": "document",
}


class AssetManifestError(ValueError):
    """The asset manifest cannot be normalized without losing its contract."""


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _redact(value: Any, key: str = "") -> Any:
    lowered = key.casefold().replace("-", "_")
    if (
        lowered in _SENSITIVE_KEYS
        or lowered.endswith("_api_key")
        or lowered.endswith("_password")
        or lowered.endswith("_secret")
        or lowered.endswith("_token")
    ):
        return "[REDACTED]"
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(child): _redact(item, str(child)) for child, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_redact(item) for item in value]
    return str(value)


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
    else:
        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            return None
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            parsed = datetime.fromtimestamp(timestamp, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _milliseconds(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        left = datetime.fromisoformat(start.replace("Z", "+00:00"))
        right = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, round((right - left).total_seconds() * 1000))


def infer_asset_kind(filename: str, generation_mode: Any = None) -> str:
    mode = str(generation_mode or "").strip().casefold()
    aliases = {"3d": "model3d", "model": "model3d", "text": "document"}
    mode = aliases.get(mode, mode)
    if mode in ASSET_KINDS:
        return mode
    if str(filename or "").casefold().endswith(".scene.json"):
        return "scene"
    return _KIND_BY_EXTENSION.get(Path(filename).suffix.casefold(), "other")


def _entity_ref(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    kind = _clean_text(value.get("kind"))
    identifier = _clean_text(value.get("id"))
    if not kind or not identifier:
        return None
    result: dict[str, Any] = {"kind": kind, "id": identifier}
    version = value.get("version")
    if isinstance(version, int) and version >= 0:
        result["version"] = version
    return result


def _artifact_refs(values: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    result = []
    for value in values or ():
        if not isinstance(value, Mapping):
            continue
        identifier = _clean_text(value.get("id"))
        kind = _clean_text(value.get("kind"))
        if not identifier or not kind:
            continue
        item = {"id": identifier, "kind": kind}
        for key in ("uri", "role"):
            text = _clean_text(value.get(key))
            if text:
                item[key] = text
        result.append(item)
    return result


def sidecar_path(output_path: str | os.PathLike[str]) -> Path:
    return Path(output_path).with_suffix(".meta.json")


def build_asset_manifest(
    output_path: str | os.PathLike[str],
    *,
    asset_id: str | None = None,
    kind: str | None = None,
    workspace_id: str | None = None,
    project: Mapping[str, Any] | None = None,
    production: Mapping[str, Any] | None = None,
    tool: str = "unknown",
    capability: str | None = None,
    actor: str = "unknown",
    status: str = "completed",
    execution_mode: str = "real",
    correlations: Mapping[str, Any] | None = None,
    prompts: Mapping[str, Any] | None = None,
    model: Mapping[str, Any] | None = None,
    parameters: Mapping[str, Any] | None = None,
    inputs: Sequence[Mapping[str, Any]] | None = None,
    parents: Sequence[Mapping[str, Any]] | None = None,
    transformations: Sequence[Mapping[str, Any]] | None = None,
    timing: Mapping[str, Any] | None = None,
    media: Mapping[str, Any] | None = None,
    technical: Mapping[str, Any] | None = None,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one JSON-safe manifest without exposing absolute local paths."""
    output = Path(output_path)
    filename = output.name
    resolved_kind = str(kind or infer_asset_kind(filename)).casefold()
    if resolved_kind not in ASSET_KINDS:
        raise AssetManifestError(f"Unsupported asset kind: {resolved_kind}")
    if status not in EXECUTION_STATUSES:
        raise AssetManifestError(f"Unsupported execution status: {status}")
    if execution_mode not in EXECUTION_MODES:
        raise AssetManifestError(f"Unsupported execution mode: {execution_mode}")
    if actor not in {"user", "wizard", "system", "unknown"}:
        actor = "unknown"

    raw_timing = dict(timing or {})
    created_at = _iso(raw_timing.get("created_at"))
    queued_at = _iso(raw_timing.get("queued_at"))
    started_at = _iso(raw_timing.get("started_at"))
    completed_at = _iso(raw_timing.get("completed_at"))
    if created_at is None:
        created_at = started_at or completed_at or _iso(datetime.now(timezone.utc).isoformat())
    queue_ms = raw_timing.get("queue_ms")
    inference_ms = raw_timing.get("inference_ms")
    total_ms = raw_timing.get("total_ms")
    if not isinstance(queue_ms, int) or queue_ms < 0:
        queue_ms = _milliseconds(queued_at or created_at, started_at)
    if not isinstance(inference_ms, int) or inference_ms < 0:
        inference_ms = _milliseconds(started_at, completed_at)
    if not isinstance(total_ms, int) or total_ms < 0:
        total_ms = _milliseconds(created_at, completed_at)

    media_value = dict(media or {})
    if output.is_file():
        try:
            media_value.setdefault("size_bytes", output.stat().st_size)
        except OSError:
            pass
    mime_type, _encoding = mimetypes.guess_type(filename)
    if mime_type:
        media_value.setdefault("mime_type", mime_type)
    if output.suffix:
        media_value.setdefault("extension", output.suffix.casefold())

    correlation = dict(correlations or {})
    execution = {
        "status": status,
        "mode": execution_mode,
        **{key: _clean_text(correlation.get(key)) for key in (
            "command_id", "workflow_id", "run_id", "task_id", "root_task_id",
            "job_id", "pipeline_id",
        )},
        "error": _redact(dict(error)) if isinstance(error, Mapping) else None,
    }
    manifest = {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "asset": {
            "id": _clean_text(asset_id) or f"asset_{uuid.uuid4().hex}",
            "kind": resolved_kind,
            "filename": filename,
            "uri": filename,
            "media": _redact(media_value),
        },
        "origin": {
            "tool": _clean_text(tool) or "unknown",
            "capability": _clean_text(capability),
            "actor": actor,
            "workspace_id": _clean_text(workspace_id),
            "project": _entity_ref(project),
            "production": _entity_ref(production),
        },
        "execution": execution,
        "generation": {
            "prompts": _redact(dict(prompts or {})),
            "model": _redact(dict(model or {})),
            "parameters": _redact(dict(parameters or {})),
            "inputs": _artifact_refs(inputs),
        },
        "timing": {
            "created_at": created_at,
            "queued_at": queued_at,
            "started_at": started_at,
            "completed_at": completed_at,
            "queue_ms": queue_ms,
            "inference_ms": inference_ms,
            "total_ms": total_ms,
        },
        "lineage": {
            "parents": _artifact_refs(parents),
            "transformations": _redact(list(transformations or [])),
        },
        "technical": _redact(dict(technical or {})),
    }
    return manifest


def validate_asset_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AssetManifestError("Asset manifest must be an object")
    if value.get("schema") != SCHEMA_NAME or value.get("schema_version") != SCHEMA_VERSION:
        raise AssetManifestError("Unsupported asset manifest schema")
    asset = value.get("asset")
    origin = value.get("origin")
    execution = value.get("execution")
    if not isinstance(asset, Mapping) or not _clean_text(asset.get("id")):
        raise AssetManifestError("Asset manifest has no asset.id")
    filename = _clean_text(asset.get("filename"))
    if not filename or filename != os.path.basename(filename):
        raise AssetManifestError("Asset manifest has an invalid asset filename")
    if asset.get("kind") not in ASSET_KINDS:
        raise AssetManifestError("Asset manifest has an invalid asset kind")
    if not isinstance(origin, Mapping) or not _clean_text(origin.get("tool")):
        raise AssetManifestError("Asset manifest has no origin.tool")
    if not isinstance(execution, Mapping) or execution.get("status") not in EXECUTION_STATUSES:
        raise AssetManifestError("Asset manifest has an invalid execution status")
    if execution.get("mode") not in EXECUTION_MODES:
        raise AssetManifestError("Asset manifest has an invalid execution mode")
    generation = value.get("generation")
    timing = value.get("timing")
    lineage = value.get("lineage")
    if not isinstance(generation, Mapping) or any(
        key not in generation for key in ("prompts", "model", "parameters", "inputs")
    ):
        raise AssetManifestError("Asset manifest has an invalid generation block")
    if not isinstance(timing, Mapping):
        raise AssetManifestError("Asset manifest has no timing block")
    if not isinstance(lineage, Mapping) or any(
        key not in lineage for key in ("parents", "transformations")
    ):
        raise AssetManifestError("Asset manifest has an invalid lineage block")
    # A sidecar may retain top-level legacy fields for old consumers. The
    # canonical read model deliberately excludes those compatibility fields:
    # they can contain host paths and are not part of the portable contract.
    return _redact({key: value.get(key) for key in _CANONICAL_FIELDS if key in value})


def adapt_legacy_sidecar(
    output_path: str | os.PathLike[str],
    legacy: Mapping[str, Any],
    *,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Return a canonical read model for a legacy sidecar without rewriting it."""
    params = legacy.get("params") if isinstance(legacy.get("params"), Mapping) else {}
    generation_mode = legacy.get("generation_mode") or params.get("generation_mode")
    prompts = {
        "original": params.get("original_prompt"),
        "effective": params.get("prompt") or params.get("video_prompt"),
        "negative": params.get("negative_prompt"),
        "audio": params.get("audio_prompt"),
        "language": params.get("language") or params.get("prompt_language"),
    }
    model = {
        "id": params.get("model_type") or legacy.get("model_type"),
        "provider": params.get("provider") or legacy.get("provider"),
        "revision": params.get("model_revision") or legacy.get("model_revision"),
    }
    started_at = legacy.get("started_at") or params.get("started_at")
    completed_at = legacy.get("completed_at") or legacy.get("created_at")
    generation_seconds = legacy.get("generation_time")
    inference_ms = (
        max(0, round(float(generation_seconds) * 1000))
        if isinstance(generation_seconds, (int, float)) else None
    )
    correlations = {
        key: legacy.get(key) or params.get(key)
        for key in ("command_id", "workflow_id", "run_id", "task_id", "root_task_id", "job_id", "pipeline_id")
    }
    if not _clean_text(correlations.get("pipeline_id")):
        correlations["pipeline_id"] = (
            legacy.get("director_pipeline_id")
            or params.get("director_pipeline_id")
            or params.get("_director_pipeline_id")
        )
    stable_workspace = workspace_id or legacy.get("workspace") or params.get("workspace")
    legacy_asset_id = _clean_text(legacy.get("asset_id")) or (
        "asset_legacy_"
        + uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"hocuspocus:{stable_workspace or 'unscoped'}:{Path(output_path).name}",
        ).hex
    )
    return build_asset_manifest(
        output_path,
        asset_id=legacy_asset_id,
        kind=infer_asset_kind(str(output_path), generation_mode),
        workspace_id=stable_workspace,
        tool=legacy.get("tool") or params.get("source") or "legacy",
        capability=legacy.get("capability"),
        actor=legacy.get("actor") or "unknown",
        status=legacy.get("status") if legacy.get("status") in EXECUTION_STATUSES else "completed",
        execution_mode="simulate" if legacy.get("simulated") else "real",
        correlations=correlations,
        prompts=prompts,
        model=model,
        parameters=params,
        timing={
            "created_at": legacy.get("created_at"),
            "started_at": started_at,
            "completed_at": completed_at,
            "inference_ms": inference_ms,
        },
        technical={"legacy_sidecar": True},
        error=legacy.get("error") if isinstance(legacy.get("error"), Mapping) else None,
    )


def read_asset_manifest(
    output_path: str | os.PathLike[str],
    *,
    workspace_id: str | None = None,
) -> dict[str, Any] | None:
    path = sidecar_path(output_path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, Mapping):
        return None
    if value.get("schema") == SCHEMA_NAME:
        try:
            return validate_asset_manifest(value)
        except AssetManifestError:
            return None
    return adapt_legacy_sidecar(output_path, value, workspace_id=workspace_id)


def write_asset_manifest(
    output_path: str | os.PathLike[str],
    manifest: Mapping[str, Any],
    *,
    legacy_fields: Mapping[str, Any] | None = None,
) -> Path:
    """Atomically persist a canonical sidecar, retaining required legacy keys."""
    normalized = validate_asset_manifest(manifest)
    document = {**_redact(dict(legacy_fields or {})), **normalized}
    target = sidecar_path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = None
        if isinstance(existing, Mapping) and existing.get("schema") == SCHEMA_NAME:
            existing_asset = existing.get("asset")
            existing_id = (
                _clean_text(existing_asset.get("id"))
                if isinstance(existing_asset, Mapping) else None
            )
            incoming_id = _clean_text(normalized["asset"].get("id"))
            if existing_id and incoming_id != existing_id:
                raise AssetManifestError(
                    f"Refusing to replace asset identity {existing_id!r} with {incoming_id!r}"
                )
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


__all__ = [
    "ASSET_KINDS", "AssetManifestError", "SCHEMA_NAME", "SCHEMA_VERSION",
    "adapt_legacy_sidecar", "build_asset_manifest", "infer_asset_kind",
    "read_asset_manifest", "sidecar_path", "validate_asset_manifest",
    "write_asset_manifest",
]
