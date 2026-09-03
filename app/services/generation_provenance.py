"""Typed generation provenance: initiator, model, location and command context.

This module does not import FastAPI, WanGP or model runtimes. It is the
portable read/write vocabulary for asset-manifest v1.

Initiator (who started the work) is never the same field as provider/model
(what computed the bytes). Workspace is a collection ID. Output folder is a
physical directory name, never an absolute host path.
"""

from __future__ import annotations

from typing import Any, Mapping, TypedDict


INITIATORS = frozenset({"user", "wizard", "system", "unknown"})
_SUBMISSION_COMMAND_FIELDS = ("command_id", "workflow_id", "run_id")
_SUBMISSION_REFERENCE_FIELDS = (
    "project_id", "production_id", "cue_id", "candidate_id", "song_version",
)


class CommandContext(TypedDict, total=False):
    command_id: str | None
    workflow_id: str | None
    run_id: str | None
    task_id: str | None
    root_task_id: str | None
    job_id: str | None
    pipeline_id: str | None
    cue_id: str | None
    candidate_id: str | None
    song_version: str | None


class GenerationLocation(TypedDict, total=False):
    workspace_id: str | None
    output_folder: str | None


class GenerationProvenance(TypedDict, total=False):
    actor: str
    tool: str
    capability: str | None
    provider: str | None
    model_id: str | None
    workspace_id: str | None
    output_folder: str | None
    project_id: str | None
    production_id: str | None
    cue_id: str | None
    candidate_id: str | None
    song_version: str | None
    command: CommandContext


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def resolve_generation_location(
    *,
    workspace_id: str | None = None,
    output_folder: str | None = None,
) -> GenerationLocation:
    """Split a Workspace collection ID from a physical output-folder name.

    Legacy writers pass the folder name as ``workspace_id``. Until those
    call sites send both kwargs, that string is stored on both fields so
    existing readers keep working. An explicit ``output_folder`` without a
    collection ID does not invent a Workspace.
    """
    collection = _clean(workspace_id)
    folder = _clean(output_folder)
    if folder and collection and folder != collection:
        return {"workspace_id": collection, "output_folder": folder}
    if folder and not collection:
        return {"workspace_id": None, "output_folder": folder}
    if collection:
        return {"workspace_id": collection, "output_folder": collection}
    return {"workspace_id": None, "output_folder": None}


def normalize_submission_provenance(value: Any) -> GenerationProvenance:
    """Validate the optional provenance attached to a generation request.

    This is attribution data, not an authorization boundary. Runtime-owned
    identifiers (job/task/pipeline) and the physical output folder are added
    by the backend and therefore cannot be supplied by the browser.
    """
    raw = value if isinstance(value, Mapping) else {}
    actor = _clean(raw.get("actor")) or "unknown"
    if actor not in INITIATORS:
        actor = "unknown"
    capability = _clean(raw.get("capability"))
    workspace_id = _clean(raw.get("workspace_id"))
    command_raw = raw.get("command") if isinstance(raw.get("command"), Mapping) else {}
    command: CommandContext = {}
    for key in _SUBMISSION_COMMAND_FIELDS:
        cleaned = _clean(command_raw.get(key))
        if cleaned:
            command[key] = cleaned[:200]
    result: GenerationProvenance = {
        "actor": actor,
        "tool": "studio",
        "command": command,
    }
    if capability:
        result["capability"] = capability[:200]
    if workspace_id:
        result["workspace_id"] = workspace_id[:200]
    for key in _SUBMISSION_REFERENCE_FIELDS:
        value = _clean(raw.get(key))
        if value:
            result[key] = value[:200]
    return result


def provenance_from_manifest(manifest: Mapping[str, Any] | None) -> GenerationProvenance:
    """Project a canonical manifest onto initiator vs provider/model vs location."""
    value = manifest if isinstance(manifest, Mapping) else {}
    origin = value.get("origin") if isinstance(value.get("origin"), Mapping) else {}
    execution = value.get("execution") if isinstance(value.get("execution"), Mapping) else {}
    generation = value.get("generation") if isinstance(value.get("generation"), Mapping) else {}
    model = generation.get("model") if isinstance(generation.get("model"), Mapping) else {}
    actor = _clean(origin.get("actor")) or "unknown"
    if actor not in INITIATORS:
        actor = "unknown"
    command: CommandContext = {
        key: _clean(execution.get(key))
        for key in (
            "command_id", "workflow_id", "run_id", "task_id",
            "root_task_id", "job_id", "pipeline_id", "cue_id",
            "candidate_id", "song_version",
        )
    }
    return {
        "actor": actor,
        "tool": _clean(origin.get("tool")) or "unknown",
        "capability": _clean(origin.get("capability")),
        "provider": _clean(model.get("provider")),
        "model_id": _clean(model.get("id")),
        "workspace_id": _clean(origin.get("workspace_id")),
        "output_folder": _clean(origin.get("output_folder")),
        "project_id": _clean((origin.get("project") or {}).get("id"))
            if isinstance(origin.get("project"), Mapping) else None,
        "production_id": _clean((origin.get("production") or {}).get("id"))
            if isinstance(origin.get("production"), Mapping) else None,
        "cue_id": command.get("cue_id"),
        "candidate_id": command.get("candidate_id"),
        "song_version": command.get("song_version"),
        "command": command,
    }


__all__ = [
    "CommandContext", "GenerationLocation", "GenerationProvenance", "INITIATORS",
    "normalize_submission_provenance", "provenance_from_manifest",
    "resolve_generation_location",
]
