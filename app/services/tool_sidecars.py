"""Provenance sidecars for files the CPU tools write: ``studio.key``, ``audio.shorten`` and the flat rig.

A generation already has a ``.meta.json``. These tools wrote their files bare,
so the gallery could not say where a keyed sprite, a shortened song or a rig
mouth came from, nor how to make it again. Each file now gets a v1 sidecar
(``services/asset_manifest.publish_generation_sidecar``) with:

* ``params``: the tool's own parameters (``tool`` names it), enough to run the
  step again with the same input;
* ``parents``: the source file(s), with their asset id when they have one;
* ``transformations``: what the tool did to them;
* the actor (``agent`` for an MCP client, ``wizard``, ``user``) and, for an
  agent, ``requested_by``.

Writing a sidecar never fails the tool: the file is already on disk.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from services.agent_activity import AGENT_TOOL, actor_label, agent_attribution, requested_by
from services.asset_catalog import _stable_unmanaged_id
from services.asset_manifest import _existing_canonical_asset_id, infer_asset_kind, publish_generation_sidecar_best_effort

UPLOADS = "__uploads__"


def _named_file(source: str, workspace: str) -> tuple[str, str] | None:
    """``(owner, name)`` of a ``/api/v1/file/…`` or ``/api/v1/uploads/…`` URL, or of a workspace-relative name."""
    parsed = urlparse(source.strip())
    if parsed.path.startswith("/api/v1/file/"):
        owner = (parse_qs(parsed.query).get("workspace") or [workspace])[0]
        return owner, unquote(parsed.path[len("/api/v1/file/"):])
    if parsed.path.startswith("/api/v1/uploads/"):
        return UPLOADS, unquote(parsed.path[len("/api/v1/uploads/"):])
    if parsed.scheme or parsed.netloc or source.startswith("/"):
        return None
    return workspace, source.strip()


def source_ref(source: Any, workspace: str, folder: str | os.PathLike[str], role: str = "source") -> dict[str, str] | None:
    """The lineage parent a tool read: asset id (its sidecar's, or the stable id of an unmanaged file), kind and uri."""
    if not isinstance(source, str) or not source.strip() or len(source) > 2000:
        return None
    named = _named_file(source, workspace)
    if named is None or not named[1] or ".." in Path(named[1]).parts:
        return None
    owner, name = named
    uri = f"uploads/{name}" if owner == UPLOADS else name if owner == workspace else f"{owner}/{name}"
    asset_id = _existing_canonical_asset_id(Path(folder) / name) if owner == workspace else None
    return {"id": asset_id or _stable_unmanaged_id(owner, name), "kind": infer_asset_kind(name), "uri": uri, "role": role}


def publish_tool_sidecar(output: str | os.PathLike[str], *, workspace: str, tool: str, capability: str,
                         params: dict[str, Any], parents: list[dict[str, str] | None],
                         transformation: dict[str, Any]) -> None:
    """Write the sidecar of one tool output (best effort, see the module docstring)."""
    path = Path(output)
    actor = actor_label()
    # An MCP tool that runs through the app's routes (a loopback) reaches here as the agent's, not in its scope.
    attribution = agent_attribution(capability) or ({"tool": AGENT_TOOL, "capability": capability} if actor == "agent" else {})
    sidecar = {
        "params": {"tool": capability, **params},
        "generation_mode": infer_asset_kind(path.name),
        "output_filename": path.name,
        "parents": [parent for parent in parents if parent],
        "transformations": [transformation],
        **requested_by(attribution),
    }
    publish_generation_sidecar_best_effort(path, sidecar, workspace_id=workspace, tool=tool, actor=actor,
                                           capability=capability)


def key_sidecar(result: dict[str, Any], payload: dict[str, Any], folder: str) -> dict[str, Any]:
    """``studio.key``: the keyed file names its source, screen mode and options. Returns ``result`` unchanged."""
    name = result.get("file") if isinstance(result, dict) else None
    if isinstance(name, str) and name and os.path.isfile(os.path.join(folder, name)):
        workspace = str(payload.get("workspace") or "")
        options = {key: payload[key] for key in ("adaptive", "despill") if isinstance(payload.get(key), bool)}
        params = {"source": payload.get("source"), "mode": payload.get("mode", "green"), **options}
        if isinstance(result.get("report"), dict):
            params["report"] = result["report"]
        publish_tool_sidecar(os.path.join(folder, name), workspace=workspace, tool="studio-key", capability="studio.key",
                             params=params, parents=[source_ref(payload.get("source"), workspace, folder)],
                             transformation={"type": "key", "mode": params["mode"], **options})
    return result


def shorten_sidecar(destination: str, payload: dict[str, Any], folder: str, *, keep: list, time_map: Any,
                    duration: float) -> None:
    """``audio.shorten``: the short WAV names its source and the kept ranges, so the same cut can be made again."""
    workspace = str(payload.get("workspace") or "")
    params = {"source": payload.get("source"), "keep": keep, "time_map": time_map, "duration_seconds": duration}
    if payload.get("duration_max") is not None:
        params["duration_max"] = payload.get("duration_max")
    publish_tool_sidecar(destination, workspace=workspace, tool="audio-shorten", capability="audio.shorten", params=params,
                         parents=[source_ref(payload.get("source"), workspace, folder)],
                         transformation={"type": "shorten", "keep": keep})


def _rig_files(character: dict[str, Any], kit_id: str) -> dict[str, str]:
    """``{file: role}`` of every image the rig wrote for the kit: pose rigs, blinks, mouths (shared and per pose)."""
    found: dict[str, str] = {}
    prefix = f"kit-{kit_id}-"

    def visit(value: Any, role: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, f"{role}.{key}" if role else str(key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{role}.{index}")
        elif isinstance(value, str) and "/api/v1/file/" in value:
            name = unquote(urlparse(value).path.rsplit("/", 1)[-1])
            if name.startswith(prefix) and name.endswith(".png"):
                found.setdefault(name, role)
    visit({key: character.get(key) for key in ("base", "poses", "mouth", "eyes", "anchors")}, "")
    return found


def rig_sidecars(result: dict[str, Any], *, workspace: str, kit_id: str, folder: str, request: dict[str, Any]) -> dict[str, Any]:
    """``characters.rig.flat``: each image it wrote names the kit, its role, the rig style and hints, and the pose
    images it was rigged from (the kit provenance's ``sources``). Returns ``result`` unchanged."""
    character = result.get("character") if isinstance(result, dict) else None
    if not isinstance(character, dict):
        return result
    provenance = next((entry for entry in reversed(character.get("provenance") or [])
                       if isinstance(entry, dict) and entry.get("method") == "flat-rig"), {})
    sources = provenance.get("sources") if isinstance(provenance.get("sources"), dict) else {}
    parents = [source_ref(source, workspace, folder, role=f"pose:{pose}") for pose, source in sorted(sources.items())]
    files = _rig_files(character, kit_id)
    review = result.get("review")
    if isinstance(review, str):
        files.setdefault(unquote(urlparse(review).path.rsplit("/", 1)[-1]), "review")
    base = {"kit_id": kit_id, "kit_name": character.get("name"), "style": provenance.get("style"),
            "hints": provenance.get("hints"), "poses": request.get("poses")}
    for name, role in files.items():
        path = os.path.join(folder, name)
        if not os.path.isfile(path) or os.path.isfile(os.path.splitext(path)[0] + ".meta.json"):
            continue  # an image with the same pixels (content-named) already has its sidecar
        publish_tool_sidecar(path, workspace=workspace, tool="flat-rig", capability="characters.rig.flat",
                             params={**base, "role": role}, parents=parents,
                             transformation={"type": "flat-rig", "role": role})
    return result


__all__ = ["key_sidecar", "publish_tool_sidecar", "rig_sidecars", "shorten_sidecar", "source_ref"]
