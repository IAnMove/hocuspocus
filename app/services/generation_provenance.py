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
_TASK_REFERENCE_FIELDS = (
    "production_id", "cue_id", "candidate_id", "song_version",
)
_TRUSTED_TOOL_BY_CAPABILITY = {
    "generate_story_song": "story_lab",
    "start_director_production": "director",
}
_TASK_ENTITY_FIELDS = (
    ("production", "production_id"),
    ("song_candidate", "candidate_id"),
    ("cue", "cue_id"),
    ("project", "project_id"),
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
        # Browser-supplied tool labels are untrusted. The public capability is
        # already allow-listed, so derive the initiating UI surface from it.
        "tool": _TRUSTED_TOOL_BY_CAPABILITY.get(capability or "", "studio"),
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


def task_fields_from_provenance(
    provenance: Mapping[str, Any] | None,
    *,
    pipeline_id: str | None = None,
) -> dict[str, Any]:
    """Project one generation provenance into canonical task fields.

    Task records deliberately keep the project as a first-class relation and
    use the most specific durable object as their entity.  The current
    priority is Director production, song candidate, cue, then Story project;
    this lets a generated song point at its candidate while a Director task
    points at its production.  ``project_id`` remains a first-class field and
    the remaining Story/Cue references stay in ``metadata`` so task consumers
    can follow the complete song-to-video chain without parsing labels or
    prompts.

    ``pipeline_id`` is runtime-owned.  When it is not present on the
    provenance command (for example while publishing a Director snapshot),
    the caller may supply the canonical ID it already owns.  Empty values and
    the physical ``output_folder`` are intentionally ignored: an output
    folder is not a project or Workspace collection.
    """
    raw = provenance if isinstance(provenance, Mapping) else {}
    command = raw.get("command") if isinstance(raw.get("command"), Mapping) else {}

    project_id = _clean(raw.get("project_id"))
    entity_type, entity_id = _task_entity(raw)

    resolved_pipeline_id = (
        _clean(raw.get("pipeline_id"))
        or _clean(command.get("pipeline_id"))
        or _clean(pipeline_id)
    )
    metadata = {
        key: value
        for key in _TASK_REFERENCE_FIELDS
        if (value := _clean(raw.get(key))) is not None
    }
    fields: dict[str, Any] = {}
    if project_id:
        fields["project_id"] = project_id
    if entity_type and entity_id:
        fields["entity_type"] = entity_type
        fields["entity_id"] = entity_id
    if resolved_pipeline_id:
        fields["pipeline_id"] = resolved_pipeline_id
    if metadata:
        fields["metadata"] = metadata
    return fields


def _task_entity(provenance: Mapping[str, Any]) -> tuple[str | None, str | None]:
    for entity_type, field in _TASK_ENTITY_FIELDS:
        entity_id = _clean(provenance.get(field))
        if entity_id:
            return entity_type, entity_id
    return None, None


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
    "resolve_generation_location", "task_fields_from_provenance",
]
