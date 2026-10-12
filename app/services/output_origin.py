"""Who asked for a gallery file, read once from its sidecar for the listing (``GET /api/v1/outputs``).

The details panel reads the whole sidecar (``ui/src/lib/outputProvenance.ts``); the listing carries only this, so
the gallery can badge and filter agent work without opening each file::

    {"actor": "agent" | "wizard", "capability": "generation.image"}

``agent`` is an MCP client, ``wizard`` is Ask to the Wizard. Files a person made have no origin (None).
"""
from __future__ import annotations

from typing import Any

AGENT_TOOL = "external_agent"
WIZARD = "wizard"
# ``GET /api/v1/outputs?origin=``: ``agent`` keeps MCP and Wizard work (as the Activity "Agents" view), the others one.
FILTERS = ("agent", "mcp", "wizard")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value != "None" else ""


def output_origin(meta: Any) -> dict[str, str] | None:
    """The maker recorded in a sidecar (``origin`` of a generation record, ``requested_by`` of an agent's file)."""
    if not isinstance(meta, dict):
        return None
    origin = meta.get("origin") if isinstance(meta.get("origin"), dict) else {}
    requested = meta.get("requested_by") if isinstance(meta.get("requested_by"), dict) else {}
    capability = (_text(requested.get("capability")) or _text(origin.get("capability")))[:120]
    if WIZARD in (origin.get("actor"), origin.get("tool"), requested.get("tool")):
        actor = WIZARD
    elif AGENT_TOOL in (requested.get("tool"), origin.get("tool")) or origin.get("actor") == "agent":
        actor = "agent"
    else:
        return None
    return {"actor": actor, **({"capability": capability} if capability else {})}


def origin_matches(origin: Any, wanted: str) -> bool:
    actor = origin.get("actor") if isinstance(origin, dict) else None
    if wanted == "agent":
        return actor in ("agent", WIZARD)
    if wanted == "mcp":
        return actor == "agent"
    return actor == wanted


def filter_by_origin(files: list[dict], wanted: str) -> list[dict]:
    """The listing rows whose ``origin`` matches ``wanted`` (see :data:`FILTERS`); every row when it is empty."""
    wanted = str(wanted or "").strip().lower()
    if not wanted:
        return files
    if wanted not in FILTERS:
        return []
    return [item for item in files if origin_matches(item.get("origin"), wanted)]


__all__ = ["FILTERS", "filter_by_origin", "origin_matches", "output_origin"]
