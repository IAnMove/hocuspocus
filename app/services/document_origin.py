"""Who saved a scene document or a comic, and who created a series record.

Gallery files use the same sidecar shape as an agent's output (``requested_by`` / ``origin``), so
``GET /api/v1/outputs?origin=agent`` and **Made by agents** list them. A person leaves no sidecar.
A later save keeps the first origin.

A series or episode records ``createdBy`` when it is created. A record without that field has an
unknown author; a save never invents one and never replaces the one already stored.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from services.agent_activity import actor_label, current_caller
from services.output_origin import AGENT_TOOL, output_origin

_ACTORS = frozenset({"agent", "wizard", "user"})


def _capability(capability: str) -> str:
    return str(capability or "").strip()[:120]


def _agent_request(capability: str) -> dict[str, str]:
    caller = current_caller() or {}
    request = {"tool": AGENT_TOOL, "capability": capability}
    command_id = caller.get("command_id")
    profile = caller.get("profile")
    if isinstance(command_id, str) and command_id.strip():
        request["command_id"] = command_id.strip()[:160]
    if isinstance(profile, str) and profile.strip():
        request["mcp_profile"] = profile.strip()[:80]
    return request


def maker_fields(capability: str) -> dict[str, Any] | None:
    """Sidecar fields for the current agent or Wizard, or None for a person or the server."""
    actor = actor_label()
    if actor not in ("agent", "wizard"):
        return None
    text = _capability(capability)
    if actor == "wizard":
        origin = {"actor": "wizard", "tool": "wizard"}
        return {"origin": {**origin, **({"capability": text} if text else {})}}
    request = _agent_request(text) if text else {"tool": AGENT_TOOL}
    if text:
        request["capability"] = text
    origin = {"actor": "agent", "tool": AGENT_TOOL, **({"capability": text} if text else {})}
    fields: dict[str, Any] = {"requested_by": request, "origin": origin}
    if request.get("command_id"):
        fields["command_id"] = request["command_id"]
    return fields


def _read_sidecar(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = ""
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def write_document_origin(path: Path, capability: str) -> bool:
    """Write ``<file>.meta.json`` for an agent or Wizard save. Keep an origin that is already there."""
    target = Path(path).with_suffix(".meta.json")
    existing = _read_sidecar(target)
    if output_origin(existing):
        return False
    fields = maker_fields(capability)
    if not fields:
        return False
    _write_json(target, {**existing, **fields})
    return True


def created_by(capability: str) -> dict[str, str]:
    """Who is creating a series record now. The server's own jobs count as ``user``."""
    actor = actor_label()
    if actor not in _ACTORS:
        actor = "user"
    tool = AGENT_TOOL if actor == "agent" else ("wizard" if actor == "wizard" else "series")
    fields = {"actor": actor, "tool": tool}
    text = _capability(capability)
    if text:
        fields["capability"] = text
    return fields


def kept_created_by(value: Any) -> dict[str, str] | None:
    """A stored ``createdBy`` that names agent, wizard or user, or None when it is missing or unusable."""
    if not isinstance(value, dict):
        return None
    actor, tool = value.get("actor"), value.get("tool")
    if actor not in _ACTORS or not isinstance(tool, str):
        return None
    tool = tool.strip()
    if not tool or len(tool) > 80:
        return None
    kept = {"actor": actor, "tool": tool}
    capability = value.get("capability")
    if capability in (None, ""):
        return kept
    if not isinstance(capability, str):
        return None
    capability = capability.strip()
    if not capability or len(capability) > 120:
        return None
    kept["capability"] = capability
    return kept


def series_author(record: Any) -> dict[str, str] | None:
    """The author stored on a series or episode, or None when the record does not say (unknown)."""
    if not isinstance(record, dict):
        return None
    return kept_created_by(record.get("createdBy"))


def keep_record_author(record: dict) -> None:
    """Keep a valid ``createdBy`` through normalize. Leave the field absent when the record has none."""
    if "createdBy" not in record:
        return
    kept = kept_created_by(record.get("createdBy"))
    if kept:
        record["createdBy"] = kept
    else:
        record.pop("createdBy", None)


def _restore_author(previous: dict, record: dict) -> None:
    kept = kept_created_by(previous.get("createdBy")) if isinstance(previous, dict) else None
    if kept:
        record["createdBy"] = kept
    else:
        record.pop("createdBy", None)


def restore_created_by(current: Any, payload: dict) -> None:
    """A later save keeps the author from creation. A new episode sent only in an update stays unknown."""
    previous = current if isinstance(current, dict) else {}
    _restore_author(previous, payload)
    episodes = payload.get("episodesById")
    if not isinstance(episodes, dict):
        return
    stored = previous.get("episodesById") if isinstance(previous.get("episodesById"), dict) else {}
    for episode_id, episode in episodes.items():
        if isinstance(episode, dict):
            prior = stored.get(episode_id)
            _restore_author(prior if isinstance(prior, dict) else {}, episode)


def stamp_created_series(series: dict, capability: str, *, episodes: str | None = None) -> None:
    """Record the current actor on a series that is being created, and on each of its episodes."""
    series["createdBy"] = created_by(capability)
    if not episodes:
        return
    found = series.get("episodesById")
    if not isinstance(found, dict):
        return
    author = created_by(episodes)
    for episode in found.values():
        if isinstance(episode, dict):
            episode["createdBy"] = dict(author)


__all__ = [
    "created_by", "keep_record_author", "kept_created_by", "maker_fields", "restore_created_by",
    "series_author", "stamp_created_series", "write_document_origin",
]
