"""Provenance sidecars for files ``audio.shorten`` and the flat rig (``characters.rig.flat``) write.

A generation already has a ``.meta.json``; ``studio.key`` and the media tools
write theirs with ``services/production_media_common.publish_sidecar``. The
song shortener and the flat rig wrote their files bare, so the gallery could
not say where a short song or a rig mouth came from, nor how to make it again.
They now use the same sidecar: the tool's parameters (enough to run the step
again), the source files as lineage parents, and the agent that asked.

Writing a sidecar never fails the tool: the file is already on disk.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from services.agent_activity import loopback_agent_scope
from services.production_media_common import publish_sidecar, source_ref


def shorten_sidecar(destination: str, source: str, payload: dict[str, Any], *, keep: list, time_map: Any, duration: float) -> None:
    """``audio.shorten``: the short WAV names its source and the kept ranges, so the same cut can be made again."""
    params = {"keep": keep, "time_map": time_map, "duration_seconds": duration}
    if payload.get("duration_max") is not None:
        params["duration_max"] = payload.get("duration_max")
    workspace = str(payload.get("workspace") or "")
    publish_sidecar(destination, workspace, "audio.shorten", "audio", params, [source_ref(source, workspace)])


def _workspace_file(url: Any, workspace: str, folder: str) -> str | None:
    """The path of a ``/api/v1/file/<name>?workspace=<this one>`` URL inside ``folder``, or None."""
    if not isinstance(url, str) or "/api/v1/file/" not in url:
        return None
    parsed = urlparse(url)
    owner = (parse_qs(parsed.query).get("workspace") or [workspace])[0]
    name = unquote(parsed.path.split("/api/v1/file/", 1)[-1])
    if owner != workspace or not name or ".." in name.replace("\\", "/").split("/"):
        return None
    path = os.path.join(folder, name)
    return path if os.path.isfile(path) else None


def _rig_files(character: dict[str, Any], kit_id: str) -> dict[str, str]:
    """``{url: role}`` of every image the rig wrote for the kit: pose rigs, blinks, mouths (shared and per pose)."""
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
                found.setdefault(value, role)
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
    parents = [source_ref(path, workspace, role=f"pose:{pose}") for pose, url in sorted(sources.items())
               if (path := _workspace_file(url, workspace, folder))]
    files = _rig_files(character, kit_id)
    if isinstance(result.get("review"), str):
        files.setdefault(result["review"], "review")
    base = {"kit_id": kit_id, "kit_name": character.get("name"), "style": provenance.get("style"),
            "hints": provenance.get("hints"), "poses": request.get("poses")}
    with loopback_agent_scope():
        for url, role in files.items():
            path = _workspace_file(url, workspace, folder)
            if path is None or os.path.isfile(os.path.splitext(path)[0] + ".meta.json"):
                continue  # gone, or an image with the same pixels (content-named) that already has its sidecar
            publish_sidecar(path, workspace, "characters.rig.flat", "image", {**base, "role": role}, parents)
    return result


__all__ = ["rig_sidecars", "shorten_sidecar"]
