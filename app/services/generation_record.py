"""Typed generation-record v1: one attempt to produce an asset.

This module does not import FastAPI, WanGP or launch. It is a portable
read/write **projection** over asset-manifest v1, generation provenance and
the job lifecycle — not a second media store, scheduler or catalog.

Identity graph (one attempt may publish zero or more assets; do not mint a
second Run store):

    command → workflow? → run? → generation attempt → task? → asset*

Identity policy (b): a retry mints a new ``generation_id`` and links the
parent attempt in ``lineage.parents``. ``asset_id`` is reused only when the
bytes are the same artifact. Re-reading a queued/running record does **not**
prove a worker is alive; resume marks ``reconciliation`` and never invents
success.

``workspace_id`` is an optional Workspace **collection**. ``output_folder`` is
the physical folder name. Missing collection stays null; it is never copied
from ``output_folder`` to satisfy the schema.

Public status is ``planned | queued | running | completed | failed |
cancelled``. Asset-manifest ``prepared`` projects to ``planned``. Manifest
``partial`` is not a seventh public status: it becomes ``completed`` with
``result.kind = "partial"`` when a filename exists, otherwise ``failed``.
A running record with ``cancellation.requested`` is the public form of the
in-process ``cancelling`` job state.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence, TypedDict

from .asset_manifest import _iso, _milliseconds, _redact, sidecar_path
from .generation_provenance import provenance_from_manifest, resolve_generation_location


SCHEMA_NAME = "hocuspocus.generation-record"
SCHEMA_VERSION = 1
PROMPT_DISPLAY_MAX = 180
ATTEMPT_IDENTITY_POLICY = "new_generation_id"
PHYSICAL_STORE_BUCKET = "_physical"
AUTHORITY = "projection"

PRODUCTS = frozenset({
    "studio", "story_lab", "series_lab", "director", "comic", "tools",
    "wizard", "video_editor", "video_3d", "character_kit", "system", "unknown",
})
STATUSES = frozenset({
    "planned", "queued", "running", "completed", "failed", "cancelled",
})
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "planned": frozenset({"queued", "cancelled"}),
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"queued", "completed", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}
_PRODUCT_ALIASES = {
    "studio-image": "studio",
    "studio-video": "studio",
    "studio-audio": "studio",
    "story-lab": "story_lab",
    "story-music-video": "story_lab",
    "series-lab": "series_lab",
    "comics": "comic",
    "video-editor": "video_editor",
    "scene-animator-3d": "video_3d",
    "hunyuan3d": "video_3d",
    "3d": "video_3d",
    "character-kit": "character_kit",
    "filesystem-import": "system",
    "legacy": "unknown",
    "upscale": "tools",
    "revoice": "tools",
    "remove_background": "tools",
}
_PRODUCT_FROM_CAPABILITY = {
    "generate_story_song": "story_lab",
    "start_director_production": "director",
    "upscale": "tools",
    "revoice": "tools",
    "remove_background": "tools",
}
_LANGUAGE_KEYS = (
    "conversation_language", "content_language",
    "spoken_language", "technical_prompt_language",
)
_CORRELATION_KEYS = (
    "command_id", "workflow_id", "run_id", "task_id",
    "job_id", "pipeline_id",
)
_CANONICAL_FIELDS = (
    "schema", "schema_version", "generation_id", "asset_id", "product",
    "workspace_id", "output_folder", "project_id", "production_id", "cue_id",
    "candidate_id", "song_version", "prompt_full", "prompt_original",
    "prompt_effective", "prompt_display", "model", "languages", "timestamps",
    "status", "lineage", "error", "retry_count", "cancellation", "location",
    "links", "result", "provenance", "correlations", "revision",
    "reconciliation",
)
_IDENTITY_KEYS = frozenset({
    "schema", "schema_version", "generation_id", "asset_id", "workspace_id",
})
_MERGE_SKIP_EMPTY_LISTS = frozenset({"parents", "derivatives", "transformations"})


class GenerationRecordError(ValueError):
    """The generation record cannot be normalized without losing its contract."""


class GenerationModel(TypedDict, total=False):
    provider: str | None
    id: str | None
    version: str | None
    configuration: dict[str, Any]


class GenerationLanguages(TypedDict, total=False):
    conversation_language: str | None
    content_language: str | None
    spoken_language: str | None
    technical_prompt_language: str | None


class GenerationTimestamps(TypedDict, total=False):
    created_at: str | None
    queued_at: str | None
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
    queue_ms: int | None
    inference_ms: int | None


class GenerationReconciliation(TypedDict, total=False):
    needed: bool
    reason: str | None
    at: str | None


class GenerationLineageRef(TypedDict, total=False):
    generation_id: str | None
    asset_id: str | None
    kind: str | None
    uri: str | None


class GenerationCancellation(TypedDict, total=False):
    requested: bool
    at: str | None
    reason: str | None


class GenerationLocation(TypedDict, total=False):
    filename: str | None
    uri: str | None
    sidecar: str | None


class GenerationLinks(TypedDict, total=False):
    activity_id: str | None
    catalog_id: str | None
    ui_href: str | None


class GenerationRecord(TypedDict, total=False):
    schema: str
    schema_version: int
    generation_id: str
    asset_id: str
    product: str
    workspace_id: str
    output_folder: str
    project_id: str | None
    production_id: str | None
    cue_id: str | None
    candidate_id: str | None
    song_version: str | None
    prompt_full: str
    prompt_original: str
    prompt_effective: str
    prompt_display: str
    model: GenerationModel
    languages: GenerationLanguages
    timestamps: GenerationTimestamps
    status: str
    lineage: dict[str, list[GenerationLineageRef]]
    error: dict[str, Any] | None
    retry_count: int
    cancellation: GenerationCancellation
    location: GenerationLocation
    links: GenerationLinks
    result: dict[str, Any]
    provenance: dict[str, Any]
    correlations: dict[str, Any]
    revision: int
    reconciliation: GenerationReconciliation


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _is_host_path(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if os.path.isabs(text) or text.startswith(("/", "\\")):
        return True
    return len(text) >= 3 and text[1] == ":" and text[2] in "/\\"


def _is_token(value: str | None) -> bool:
    text = str(value or "").strip()
    if not text or text in {".", ".."} or _is_host_path(text):
        return False
    return os.path.basename(text) == text and "/" not in text and "\\" not in text


def _identity_token(value: Any, field: str, *, required: bool) -> str | None:
    text = _clean(value)
    if not text:
        if required:
            raise GenerationRecordError(f"{field} is required")
        return None
    if not _is_token(text) or len(text) > 240:
        raise GenerationRecordError(f"{field} must be a stable ID, never a path")
    return text


def _portable_filename(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None
    name = os.path.basename(text.replace("\\", "/"))
    if not name or name in {".", ".."} or _is_host_path(name):
        raise GenerationRecordError("location values must be relative filenames")
    return name


def _count(value: Any, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return default
    return value


def _optional_ms(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def prompt_display_text(value: Any, limit: int = PROMPT_DISPLAY_MAX) -> str:
    """Truncated, secret-free prompt for lists and inspectors."""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    if limit <= 1:
        return "…"
    return text[: limit - 1].rstrip() + "…"


def map_product(value: Any, *, capability: str | None = None) -> str:
    token = (_clean(value) or "").casefold().replace(" ", "_")
    if token in PRODUCTS:
        return token
    if token in _PRODUCT_ALIASES:
        return _PRODUCT_ALIASES[token]
    mapped = _PRODUCT_FROM_CAPABILITY.get(_clean(capability) or "")
    return mapped if mapped in PRODUCTS else "unknown"


def map_manifest_status(status: Any, *, has_filename: bool = False) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """Project asset-manifest execution.status onto the six public values."""
    raw = (_clean(status) or "").casefold()
    result: dict[str, Any] = {"kind": None}
    if raw == "prepared":
        return "planned", result, None
    if raw == "partial":
        if has_filename:
            return "completed", {"kind": "partial"}, None
        return "failed", result, {
            "code": "partial",
            "message": "Generation finished without a complete artifact",
        }
    if raw in STATUSES:
        result["kind"] = raw if raw in {"completed", "failed", "cancelled"} else None
        return raw, result, None
    if not raw:
        return "planned", result, None
    return "failed", result, {"code": "invalid_status", "message": f"Unsupported status {raw!r}"}


def map_record_status_to_manifest(status: str, *, result_kind: str | None = None) -> str:
    if status == "planned":
        return "prepared"
    if status == "completed" and result_kind == "partial":
        # Public enum stays completed; callers may inspect result.kind.
        return "completed"
    if status in STATUSES:
        return status
    raise GenerationRecordError(f"Unsupported generation status: {status}")


def is_legal_transition(current: str, target: str) -> bool:
    return target in LEGAL_TRANSITIONS.get(current, frozenset())


def belongs_to_workspace(record: Mapping[str, Any], workspace_id: str) -> bool:
    """True only when the record is a member of that Workspace collection.

    A missing/blank ``workspace_id`` is not a collection. Unscoped records
    (physical ``output_folder`` only) never belong to any collection.
    """
    wanted = _clean(workspace_id)
    have = _clean(record.get("workspace_id"))
    return bool(wanted) and have is not None and have == wanted


def is_unscoped_record(record: Mapping[str, Any]) -> bool:
    return _clean(record.get("workspace_id")) is None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _sidecar_for(filename: str | None) -> str | None:
    return sidecar_path(filename).name if filename else None


def _model_block(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    configuration = raw.get("configuration")
    if not isinstance(configuration, Mapping):
        configuration = raw.get("parameters") if isinstance(raw.get("parameters"), Mapping) else {}
    return {
        "provider": _clean(raw.get("provider")),
        "id": _clean(raw.get("id")),
        "version": _clean(raw.get("version") or raw.get("revision")),
        "configuration": dict(configuration),
    }


def _languages_block(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    return {key: _clean(raw.get(key)) for key in _LANGUAGE_KEYS}


def _timestamps_block(value: Any, *, created_fallback: str) -> dict[str, Any]:
    raw = _mapping(value)
    created_at = _iso(raw.get("created_at")) or created_fallback
    queued_at = _iso(raw.get("queued_at"))
    started_at = _iso(raw.get("started_at"))
    completed_at = _iso(raw.get("completed_at"))
    duration = _optional_ms(raw.get("duration_ms"))
    queue_ms = _optional_ms(raw.get("queue_ms"))
    inference_ms = _optional_ms(raw.get("inference_ms"))
    if duration is None:
        duration = _milliseconds(created_at, completed_at)
    if queue_ms is None:
        queue_ms = _milliseconds(queued_at or created_at, started_at)
    if inference_ms is None:
        inference_ms = _milliseconds(started_at, completed_at)
    return {
        "created_at": created_at,
        "queued_at": queued_at,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration,
        "queue_ms": queue_ms,
        "inference_ms": inference_ms,
    }


def _require_lineage_token(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not _is_token(value):
        raise GenerationRecordError(f"lineage {field} must be a stable ID")
    return value


def _lineage_ref(value: Any) -> dict[str, Any] | None:
    raw = _mapping(value)
    generation_id = _require_lineage_token(_clean(raw.get("generation_id")), "generation_id")
    asset_id = _require_lineage_token(_clean(_coalesce(raw.get("asset_id"), raw.get("id"))), "asset_id")
    if generation_id is None and asset_id is None:
        return None
    item: dict[str, Any] = {}
    for key, token in (("generation_id", generation_id), ("asset_id", asset_id),
                       ("kind", _clean(_coalesce(raw.get("kind"), raw.get("role")))),
                       ("uri", _portable_filename(raw.get("uri")))):
        if token:
            item[key] = token
    return item


def _lineage_list(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return []
    result: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for value in values:
        item = _lineage_ref(value)
        if item is None:
            item = _transformation_item(value)
        if item is None:
            continue
        key = (item.get("generation_id"), item.get("asset_id"), item.get("kind"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _transformation_item(value: Any) -> dict[str, Any] | None:
    raw = _mapping(value)
    if not raw:
        return None
    item: dict[str, Any] = {}
    kind = _clean(_coalesce(raw.get("kind"), raw.get("op"), raw.get("role")))
    asset_id = _require_lineage_token(_clean(_coalesce(raw.get("asset_id"), raw.get("id"))), "asset_id")
    generation_id = _require_lineage_token(_clean(raw.get("generation_id")), "generation_id")
    uri = None
    if raw.get("uri"):
        uri = _portable_filename(raw.get("uri"))
    for key, token in (("generation_id", generation_id), ("asset_id", asset_id),
                       ("kind", kind), ("uri", uri)):
        if token:
            item[key] = token
    return item or None


def _reconciliation_block(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    reason = _clean(raw.get("reason"))
    return {
        "needed": bool(raw.get("needed")),
        "reason": reason,
        "at": _iso(raw.get("at")),
    }


def _prompt_pair(prompt_full: Any, prompt_original: Any, prompt_effective: Any) -> tuple[str, str, str]:
    original = str(prompt_original if prompt_original is not None else "")
    effective = str(prompt_effective if prompt_effective is not None else "")
    full = str(prompt_full if prompt_full is not None else "")
    if not original and not effective:
        original = full
        effective = full
    elif not original:
        original = effective or full
    elif not effective:
        effective = original
    display = effective or original or full
    return original, effective, display


def _error_block(value: Any) -> dict[str, Any] | None:
    raw = _mapping(value)
    if not raw:
        return None
    code = _clean(raw.get("code"))
    message = _clean(raw.get("message"))
    details = raw.get("details") if isinstance(raw.get("details"), Mapping) else None
    if not code and not message and not details:
        return None
    error: dict[str, Any] = {}
    if code:
        error["code"] = code[:120]
    if message:
        error["message"] = message[:2000]
    if details:
        error["details"] = dict(details)
    return error


def _cancellation_block(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    return {
        "requested": bool(raw.get("requested")),
        "at": _iso(raw.get("at")),
        "reason": _clean(raw.get("reason")),
    }


def _location_block(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    filename = _portable_filename(raw.get("filename") or raw.get("uri"))
    uri = _portable_filename(raw.get("uri")) or filename
    sidecar = _portable_filename(raw.get("sidecar"))
    if filename and sidecar is None:
        sidecar = sidecar_path(filename).name
    return {"filename": filename, "uri": uri, "sidecar": sidecar}


def _links_block(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    href = _clean(raw.get("ui_href"))
    if href and _is_host_path(href) and not href.startswith(("/", "#")):
        # Host filesystem paths are not portable. App routes such as /activity/x stay.
        if "://" not in href:
            raise GenerationRecordError("links.ui_href must not be a host filesystem path")
    return {
        "activity_id": _clean(raw.get("activity_id")),
        "catalog_id": _clean(raw.get("catalog_id")),
        "ui_href": href,
    }


def _result_block(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    return {"kind": _clean(raw.get("kind"))}


def _provenance_block(value: Any, *, actor: str | None, capability: str | None) -> dict[str, Any]:
    raw = _mapping(value)
    resolved_actor = _clean(raw.get("actor") or actor) or "unknown"
    if resolved_actor not in {"user", "wizard", "system", "unknown"}:
        resolved_actor = "unknown"
    return {
        "actor": resolved_actor,
        "capability": _clean(raw.get("capability") or capability),
    }


def _correlations_block(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    return {key: _clean(raw.get(key)) for key in _CORRELATION_KEYS}


def build_generation_record(
    *,
    generation_id: str | None = None,
    asset_id: str | None = None,
    product: str | None = None,
    workspace_id: str | None = None,
    output_folder: str | None = None,
    project_id: str | None = None,
    production_id: str | None = None,
    cue_id: str | None = None,
    candidate_id: str | None = None,
    song_version: str | None = None,
    prompt_full: str | None = None,
    prompt_original: str | None = None,
    prompt_effective: str | None = None,
    model: Mapping[str, Any] | None = None,
    languages: Mapping[str, Any] | None = None,
    timestamps: Mapping[str, Any] | None = None,
    status: str = "planned",
    parents: Sequence[Mapping[str, Any]] | None = None,
    derivatives: Sequence[Mapping[str, Any]] | None = None,
    transformations: Sequence[Mapping[str, Any]] | None = None,
    error: Mapping[str, Any] | None = None,
    retry_count: int = 0,
    cancellation: Mapping[str, Any] | None = None,
    location: Mapping[str, Any] | None = None,
    links: Mapping[str, Any] | None = None,
    result: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    correlations: Mapping[str, Any] | None = None,
    revision: int = 0,
    reconciliation: Mapping[str, Any] | None = None,
    actor: str | None = None,
    capability: str | None = None,
    mint_ids: bool = True,
) -> dict[str, Any]:
    """Build one JSON-safe generation attempt without host filesystem paths."""
    resolved_status = (_clean(status) or "planned").casefold()
    if resolved_status not in STATUSES:
        raise GenerationRecordError(f"Unsupported generation status: {resolved_status}")
    resolved_generation_id = _identity_token(
        generation_id, "generation_id", required=not mint_ids,
    ) or f"gen_{uuid.uuid4().hex}"
    resolved_asset_id = _identity_token(
        asset_id, "asset_id", required=not mint_ids,
    ) or f"asset_{uuid.uuid4().hex}"
    location_ids = resolve_generation_location(
        workspace_id=workspace_id, output_folder=output_folder,
    )
    collection = _identity_token(
        location_ids.get("workspace_id"), "workspace_id", required=False,
    )
    folder = _portable_filename(location_ids.get("output_folder"))
    if not folder:
        raise GenerationRecordError("output_folder is required")
    original, effective, display = _prompt_pair(prompt_full, prompt_original, prompt_effective)
    record = {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "generation_id": resolved_generation_id,
        "asset_id": resolved_asset_id,
        "product": map_product(product, capability=capability),
        "workspace_id": collection,
        "output_folder": folder,
        "project_id": _clean(project_id),
        "production_id": _clean(production_id),
        "cue_id": _clean(cue_id),
        "candidate_id": _clean(candidate_id),
        "song_version": _clean(song_version),
        "prompt_full": display,
        "prompt_original": original,
        "prompt_effective": effective,
        "prompt_display": prompt_display_text(display),
        "model": _model_block(model),
        "languages": _languages_block(languages),
        "timestamps": _timestamps_block(timestamps, created_fallback=_now_iso()),
        "status": resolved_status,
        "lineage": {
            "parents": _lineage_list(parents),
            "derivatives": _lineage_list(derivatives),
            "transformations": _lineage_list(transformations),
        },
        "error": _error_block(error),
        "retry_count": _count(retry_count),
        "cancellation": _cancellation_block(cancellation),
        "location": _location_block(location),
        "links": _links_block(links),
        "result": _result_block(result),
        "provenance": _provenance_block(provenance, actor=actor, capability=capability),
        "correlations": _correlations_block(correlations),
        "revision": _count(revision),
        "reconciliation": _reconciliation_block(reconciliation),
    }
    if not record["links"].get("catalog_id"):
        record["links"]["catalog_id"] = resolved_asset_id
    return _redact(record)


def _require_record_object(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GenerationRecordError("Generation record must be an object")
    if value.get("schema") != SCHEMA_NAME:
        raise GenerationRecordError("Unsupported generation record schema")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise GenerationRecordError("Unsupported generation record schema")
    return value


def validate_generation_record(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _require_record_object(value)
    lineage = _mapping(payload.get("lineage"))
    normalized = build_generation_record(
        generation_id=payload.get("generation_id"),
        asset_id=payload.get("asset_id"),
        product=payload.get("product"),
        workspace_id=payload.get("workspace_id"),
        output_folder=payload.get("output_folder"),
        project_id=payload.get("project_id"),
        production_id=payload.get("production_id"),
        cue_id=payload.get("cue_id"),
        candidate_id=payload.get("candidate_id"),
        song_version=payload.get("song_version"),
        prompt_full=payload.get("prompt_full"),
        prompt_original=payload.get("prompt_original"),
        prompt_effective=payload.get("prompt_effective"),
        model=_mapping(payload.get("model")),
        languages=_mapping(payload.get("languages")),
        timestamps=_mapping(payload.get("timestamps")),
        status=str(payload.get("status") or "planned"),
        parents=lineage.get("parents"),
        derivatives=lineage.get("derivatives"),
        transformations=lineage.get("transformations"),
        error=_mapping(payload.get("error")) or None,
        retry_count=_count(payload.get("retry_count")),
        cancellation=_mapping(payload.get("cancellation")),
        location=_mapping(payload.get("location")),
        links=_mapping(payload.get("links")),
        result=_mapping(payload.get("result")),
        provenance=_mapping(payload.get("provenance")),
        correlations=_mapping(payload.get("correlations")),
        revision=_count(payload.get("revision")),
        reconciliation=_mapping(payload.get("reconciliation")),
        mint_ids=False,
    )
    if normalized.get("workspace_id") and _is_host_path(normalized["workspace_id"]):
        raise GenerationRecordError("workspace_id and output_folder must never be host paths")
    if _is_host_path(normalized["output_folder"]):
        raise GenerationRecordError("workspace_id and output_folder must never be host paths")
    return {key: normalized[key] for key in _CANONICAL_FIELDS}


def _languages_from_manifest(generation: Mapping[str, Any]) -> dict[str, Any]:
    prompts = _mapping(generation.get("prompts"))
    languages = _mapping(generation.get("languages"))
    intent = _mapping(prompts.get("language_intent"))
    merged = {**intent, **languages}
    content = _clean(_coalesce(merged.get("content_language"), prompts.get("language")))
    if content:
        merged["content_language"] = content
    return merged


def _prompt_from_manifest(generation: Mapping[str, Any]) -> str:
    original, effective = _prompt_pair_from_manifest(generation)
    return effective or original


def _prompt_pair_from_manifest(generation: Mapping[str, Any]) -> tuple[str, str]:
    prompts = _mapping(generation.get("prompts"))
    original = str(prompts.get("original") or "")
    effective = str(prompts.get("effective") or "")
    fallback = ""
    for key in ("audio", "instruction"):
        text = _clean(prompts.get(key))
        if text:
            fallback = text
            break
    if not original and not effective:
        return fallback, fallback
    if not original:
        original = effective or fallback
    if not effective:
        effective = original or fallback
    return original, effective


def _generation_id_from_manifest(
    technical: Mapping[str, Any],
    execution: Mapping[str, Any],
    asset_id: str,
) -> str:
    return _coalesce(
        _clean(technical.get("generation_id")),
        _clean(execution.get("job_id")),
        f"gen_{asset_id}",
    )


def _manifest_parts(manifest: Mapping[str, Any]) -> dict[str, Any]:
    value = _mapping(manifest)
    generation = _mapping(value.get("generation"))
    origin = _mapping(value.get("origin"))
    return {
        "asset": _mapping(value.get("asset")),
        "origin": origin,
        "execution": _mapping(value.get("execution")),
        "generation": generation,
        "timing": _mapping(value.get("timing")),
        "lineage": _mapping(value.get("lineage")),
        "technical": _mapping(value.get("technical")),
        "model": _mapping(generation.get("model")),
        "parameters": _mapping(generation.get("parameters")),
        "project": _mapping(origin.get("project")),
        "production": _mapping(origin.get("production")),
        "provenance": provenance_from_manifest(value),
    }


def _manifest_error(execution: Mapping[str, Any], mapped_error: dict[str, Any] | None) -> dict[str, Any] | None:
    error = execution.get("error")
    if isinstance(error, Mapping):
        return dict(error)
    return mapped_error


def _project_kwargs(parts: Mapping[str, Any]) -> dict[str, Any]:
    origin = parts["origin"]
    execution = parts["execution"]
    provenance = parts["provenance"]
    technical = parts["technical"]
    asset = parts["asset"]
    filename = _portable_filename(_coalesce(asset.get("filename"), asset.get("uri")))
    status, result, mapped_error = map_manifest_status(
        execution.get("status"), has_filename=bool(filename),
    )
    asset_id = _identity_token(asset.get("id"), "asset_id", required=False) or f"asset_{uuid.uuid4().hex}"
    model = dict(parts["model"])
    model["configuration"] = parts["parameters"]
    model["version"] = _coalesce(model.get("revision"), model.get("version"))
    timing = parts["timing"]
    prompt_original, prompt_effective = _prompt_pair_from_manifest(parts["generation"])
    return {
        "generation_id": _generation_id_from_manifest(technical, execution, asset_id),
        "asset_id": asset_id,
        "product": map_product(
            _coalesce(origin.get("tool"), provenance.get("tool")),
            capability=origin.get("capability"),
        ),
        "workspace_id": _coalesce(origin.get("workspace_id"), provenance.get("workspace_id")),
        "output_folder": _coalesce(origin.get("output_folder"), provenance.get("output_folder")),
        "project_id": _coalesce(parts["project"].get("id"), provenance.get("project_id")),
        "production_id": _coalesce(parts["production"].get("id"), provenance.get("production_id")),
        "cue_id": _coalesce(execution.get("cue_id"), provenance.get("cue_id")),
        "candidate_id": _coalesce(execution.get("candidate_id"), provenance.get("candidate_id")),
        "song_version": _coalesce(execution.get("song_version"), provenance.get("song_version")),
        "prompt_full": prompt_effective or prompt_original,
        "prompt_original": prompt_original,
        "prompt_effective": prompt_effective,
        "model": model,
        "languages": _languages_from_manifest(parts["generation"]),
        "timestamps": {
            "created_at": timing.get("created_at"),
            "queued_at": timing.get("queued_at"),
            "started_at": timing.get("started_at"),
            "completed_at": timing.get("completed_at"),
            "duration_ms": _coalesce(timing.get("total_ms"), timing.get("inference_ms")),
            "queue_ms": timing.get("queue_ms"),
            "inference_ms": timing.get("inference_ms"),
        },
        "status": status,
        "parents": _lineage_list(parts["lineage"].get("parents")),
        "transformations": _lineage_list(parts["lineage"].get("transformations")),
        "error": _manifest_error(execution, mapped_error),
        "location": {"filename": filename, "uri": filename, "sidecar": _sidecar_for(filename)},
        "links": {
            "catalog_id": asset_id,
            "activity_id": _coalesce(technical.get("activity_id"), execution.get("task_id")),
        },
        "result": result,
        "provenance": {"actor": provenance.get("actor"), "capability": provenance.get("capability")},
        "correlations": {key: execution.get(key) for key in _CORRELATION_KEYS},
        "actor": provenance.get("actor"),
        "capability": provenance.get("capability"),
        "mint_ids": False,
    }


def project_from_asset_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Project a canonical asset-manifest onto GenerationRecord v1."""
    return build_generation_record(**_project_kwargs(_manifest_parts(manifest)))


def _artifact_parent(item: Mapping[str, Any]) -> dict[str, Any] | None:
    asset_id = item.get("asset_id")
    if not asset_id:
        return None
    parent = {"id": asset_id, "kind": item.get("kind") or "other"}
    if item.get("uri"):
        parent["uri"] = item["uri"]
    return parent


def _entity_patch(kind: str, identifier: str | None) -> dict[str, str] | None:
    if not identifier:
        return None
    return {"kind": kind, "id": identifier}


def to_asset_manifest_patch(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the asset-manifest fields implied by a generation record."""
    value = validate_generation_record(record)
    location = value["location"]
    model = value["model"]
    timestamps = value["timestamps"]
    provenance = value["provenance"]
    filename = location.get("filename")
    parents = [item for item in (_artifact_parent(parent) for parent in value["lineage"]["parents"]) if item]
    result_kind = _mapping(value.get("result")).get("kind")
    patch: dict[str, Any] = {
        "asset": {
            "id": value["asset_id"],
            "filename": filename,
            "uri": _coalesce(location.get("uri"), filename),
        },
        "origin": {
            "tool": value["product"],
            "capability": provenance.get("capability"),
            "actor": _coalesce(provenance.get("actor"), "unknown"),
            "workspace_id": value["workspace_id"],
            "output_folder": value["output_folder"],
            "project": _entity_patch("project", value.get("project_id")),
            "production": _entity_patch("production", value.get("production_id")),
        },
        "execution": {
            "status": map_record_status_to_manifest(value["status"], result_kind=result_kind),
            "error": value.get("error"),
            "cue_id": value.get("cue_id"),
            "candidate_id": value.get("candidate_id"),
            "song_version": value.get("song_version"),
            **value["correlations"],
        },
        "generation": {
            "prompts": {
                "original": value.get("prompt_original") or value["prompt_full"],
                "effective": value.get("prompt_effective") or value["prompt_full"],
                "language": value["languages"].get("content_language"),
            },
            "model": {
                "provider": model.get("provider"),
                "id": model.get("id"),
                "revision": model.get("version"),
            },
            "parameters": _mapping(model.get("configuration")),
            "inputs": parents,
        },
        "timing": {
            "created_at": timestamps.get("created_at"),
            "queued_at": timestamps.get("queued_at"),
            "started_at": timestamps.get("started_at"),
            "completed_at": timestamps.get("completed_at"),
            "queue_ms": timestamps.get("queue_ms"),
            "inference_ms": timestamps.get("inference_ms"),
            "total_ms": timestamps.get("duration_ms"),
        },
        "technical": {
            "generation_id": value["generation_id"],
            "result": value.get("result"),
        },
    }
    lineage_patch: dict[str, Any] = {}
    if parents:
        lineage_patch["parents"] = parents
    transformations = [
        item for item in (
            _artifact_parent(raw) for raw in value["lineage"].get("transformations") or []
        ) if item
    ]
    if transformations:
        lineage_patch["transformations"] = transformations
    if lineage_patch:
        patch["lineage"] = lineage_patch
    if value.get("workspace_id") is None:
        patch["origin"].pop("workspace_id", None)
    return patch


def _stamp_transition(record: dict[str, Any], target: str, at: str) -> None:
    times = dict(record["timestamps"])
    if target == "queued":
        times["queued_at"] = times.get("queued_at") or at
    elif target == "running":
        times["started_at"] = times.get("started_at") or at
    elif target in TERMINAL_STATUSES:
        times["completed_at"] = times.get("completed_at") or at
        times["queue_ms"] = times.get("queue_ms") or _milliseconds(
            times.get("queued_at") or times.get("created_at"),
            times.get("started_at"),
        )
        times["inference_ms"] = times.get("inference_ms") or _milliseconds(
            times.get("started_at"),
            times["completed_at"],
        )
        times["duration_ms"] = times.get("duration_ms") or _milliseconds(
            times.get("created_at"),
            times["completed_at"],
        )
    record["timestamps"] = times


def transition_status(
    record: Mapping[str, Any],
    target: str,
    *,
    at: Any = None,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply one legal lifecycle transition. Cancellation already requested wins."""
    current = validate_generation_record(record)
    resolved = (_clean(target) or "").casefold()
    if current["cancellation"]["requested"] and resolved != "cancelled":
        return apply_cancel(current, reason=current["cancellation"].get("reason"), at=at)
    if not is_legal_transition(current["status"], resolved):
        raise GenerationRecordError(
            f"Illegal generation transition {current['status']!r} -> {resolved!r}",
        )
    current["status"] = resolved
    if resolved == "failed":
        current["error"] = _error_block(error) or current.get("error")
    elif resolved == "completed":
        current["error"] = None
    _stamp_transition(current, resolved, _iso(at) or _now_iso())
    return validate_generation_record(current)


def request_cancel(
    record: Mapping[str, Any],
    *,
    reason: str | None = None,
    at: Any = None,
) -> dict[str, Any]:
    """Mark cancellation. Planned/queued settle immediately; running waits for apply."""
    current = validate_generation_record(record)
    if current["status"] in TERMINAL_STATUSES:
        return current
    stamp = _iso(at) or _now_iso()
    current["cancellation"] = {
        "requested": True,
        "at": stamp,
        "reason": _clean(reason) or current["cancellation"].get("reason"),
    }
    if current["status"] in {"planned", "queued"}:
        return apply_cancel(current, reason=reason, at=stamp)
    return validate_generation_record(current)


def apply_cancel(
    record: Mapping[str, Any],
    *,
    reason: str | None = None,
    at: Any = None,
) -> dict[str, Any]:
    """Settle a cancellation request, matching job-lifecycle acknowledgement."""
    current = validate_generation_record(record)
    if current["status"] == "cancelled":
        return current
    if current["status"] in TERMINAL_STATUSES:
        raise GenerationRecordError("Cannot cancel a finished generation")
    stamp = _iso(at) or current["cancellation"].get("at") or _now_iso()
    current["cancellation"] = {
        "requested": True,
        "at": stamp,
        "reason": _clean(reason) or current["cancellation"].get("reason"),
    }
    current["status"] = "cancelled"
    current["error"] = None
    _stamp_transition(current, "cancelled", stamp)
    return validate_generation_record(current)


def retry_generation(
    record: Mapping[str, Any],
    *,
    same_artifact: bool = False,
) -> dict[str, Any]:
    """Start a new attempt (policy b) linked to the parent generation_id."""
    parent = validate_generation_record(record)
    child = build_generation_record(
        asset_id=parent["asset_id"] if same_artifact else None,
        product=parent["product"],
        workspace_id=parent["workspace_id"],
        output_folder=parent["output_folder"],
        project_id=parent.get("project_id"),
        production_id=parent.get("production_id"),
        cue_id=parent.get("cue_id"),
        candidate_id=parent.get("candidate_id"),
        song_version=parent.get("song_version"),
        prompt_full=parent.get("prompt_full"),
        prompt_original=parent.get("prompt_original"),
        prompt_effective=parent.get("prompt_effective"),
        model=parent.get("model"),
        languages=parent.get("languages"),
        status="planned",
        parents=[{
            "generation_id": parent["generation_id"],
            "asset_id": parent["asset_id"],
            "kind": "attempt",
        }],
        retry_count=parent["retry_count"] + 1,
        location=parent.get("location") if same_artifact else None,
        links={"catalog_id": parent["asset_id"] if same_artifact else None},
        provenance=parent.get("provenance"),
        correlations=parent.get("correlations"),
        actor=(parent.get("provenance") or {}).get("actor"),
        capability=(parent.get("provenance") or {}).get("capability"),
    )
    return child


def attach_derivative(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    """Return the parent with the child linked in derivatives[]. IDs stay put."""
    current = validate_generation_record(parent)
    attempt = validate_generation_record(child)
    current["lineage"] = {
        "parents": current["lineage"]["parents"],
        "derivatives": _lineage_list([
            *current["lineage"]["derivatives"],
            {
                "generation_id": attempt["generation_id"],
                "asset_id": attempt["asset_id"],
                "kind": "attempt",
            },
        ]),
        "transformations": current["lineage"].get("transformations") or [],
    }
    return validate_generation_record(current)


from .generation_record_io import (  # noqa: E402
    GenerationRecordStore,
    load_generation_record,
    merge_generation_record,
    persist_generation_record,
    resume_generation_record,
)


__all__ = [
    "ATTEMPT_IDENTITY_POLICY", "AUTHORITY", "LEGAL_TRANSITIONS", "PHYSICAL_STORE_BUCKET",
    "PRODUCTS", "PROMPT_DISPLAY_MAX", "SCHEMA_NAME", "SCHEMA_VERSION", "STATUSES",
    "TERMINAL_STATUSES",
    "GenerationRecord", "GenerationRecordError", "GenerationRecordStore",
    "apply_cancel", "attach_derivative", "belongs_to_workspace",
    "build_generation_record", "is_legal_transition", "is_unscoped_record",
    "load_generation_record", "map_manifest_status", "map_product",
    "map_record_status_to_manifest", "merge_generation_record",
    "persist_generation_record", "project_from_asset_manifest",
    "prompt_display_text", "request_cancel", "resume_generation_record",
    "retry_generation", "to_asset_manifest_patch", "transition_status",
    "validate_generation_record",
]
