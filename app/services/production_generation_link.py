"""Attach the producer's own identity before its first worker can start."""
from __future__ import annotations

from typing import Any

from services.production_project_link import LinkError, bind_producer, note_production_status


def register_generation(root: str, workspace: str, production_id: str, data: dict, *, form: str,
                        title: str, create_stub: bool = False) -> dict[str, Any]:
    project = data.get("project")
    provenance = data.get("provenance") if isinstance(data.get("provenance"), dict) else {}
    if project is None and isinstance(provenance, dict) and provenance.get("project_id"):
        project = {"kind": "story", "id": provenance["project_id"]}
    origin = data.get("origin") or provenance.get("actor") or "ui"
    if origin not in {"mcp", "wizard", "ui"}:
        origin = "ui"
    return bind_producer(root, {
        "workspace": workspace, "production_id": production_id,
        "origin": origin, "project": project, "episode_id": data.get("episode_id"),
        "format": form, "title": title,
        "idea": data.get("idea") or data.get("scene_description") or "",
        "write_stub": create_stub,
    })


def attach_music(production: Any, data: dict, spec: dict) -> dict[str, Any]:
    from fastapi import HTTPException
    try:
        registered = register_generation(str(production.root), production.ws, production.id,
                                         {"origin": "mcp", **data},
                                         form="trailer" if spec.get("structure") == "trailer" else "music_video",
                                         title=spec.get("title") or production.id)
    except LinkError as error:
        raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": False}) from error
    production.state.update(
        project=registered["project"],
        intent_id=registered["intent_id"],
        origin=registered["origin"],
    )
    if registered.get("format"):
        production.state["format"] = registered["format"]
    production.save()
    return registered


def attach_director(pipeline: dict, params: dict) -> dict[str, Any]:
    from services.production_run import adapt_pipeline_record
    form = {"music_video": "music_video", "trailer": "trailer"}.get(params.get("pipeline_type"), "quick_video")
    identifier = (params.get("provenance") or {}).get("production_id") or adapt_pipeline_record(pipeline)["production"]["id"]
    registered = register_generation(pipeline["out_dir"], pipeline.get("workspace") or "default",
                                     identifier, params, form=form,
                                     title=params.get("title") or params.get("scene_description") or identifier)
    pipeline.update(production_id=identifier, project=registered["project"])
    params["provenance"] = {**(params.get("provenance") or {}), "production_id": identifier}
    if registered["project"]["kind"] == "story":
        params["provenance"]["project_id"] = registered["project"]["id"]
    return registered


def attach_episode(root: str, workspace: str, episode: dict, data: dict) -> dict[str, Any]:
    registered = register_generation(root, workspace, f"series-{episode['id']}",
                                     {**data, "project": {"kind": "episode", "id": episode["id"]}},
                                     form="full_story", title=episode.get("title") or episode["id"])
    ids = episode.setdefault("productionIds", [])
    if registered["production_id"] not in ids:
        ids.append(registered["production_id"])
    note_production_status(root, registered["production_id"], "running")
    return registered
