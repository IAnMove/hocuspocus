"""MCP tools that calibrate a location plate's perspective (``series.location.stage.set`` and ``.check``).

Thin projections of the routes in ``routers/series_stage.py``, the same ones Series Lab's location panel and the Wizard call: one operation
behind the three doors. Merged into ``services/series_commands.py`` through ``OPERATIONS`` and ``RUNNERS``.
"""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

_ID = {"type": "string", "minLength": 1, "maxLength": 160}
_WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 120}
_FRACTION = {"type": "number", "minimum": 0, "maximum": 1}
_REF = {"type": "object", "additionalProperties": False, "required": ["baseY", "heightPct"], "properties": {
    "baseY": {"type": "number", "minimum": 0.05, "maximum": 1, "description": "y of the floor under the reference object (fraction of the plate height, from the top)"},
    "heightPct": {"type": "number", "minimum": 0.01, "maximum": 1.5, "description": "its height as a fraction of the plate height"},
    "heightM": {"type": "number", "minimum": 0.05, "maximum": 30, "description": "its real height in metres (default 2: a door)"}}}
_STAGE = {"horizon": {"type": "number", "minimum": 0, "maximum": 0.95, "description": "y of the horizon / eye line (fraction of the plate height)"},
          "ref": _REF, "floorTop": {**_FRACTION, "description": "the farthest floor a person can stand on (default: the reference's baseY)"}}

OPERATIONS: dict[str, tuple[dict[str, Any], list[str], bool, str]] = {
    "series.location.stage.set": (
        {"workspace": _WORKSPACE, "series_id": _ID, "location_id": _ID, **_STAGE, "clear": {"type": "boolean"}},
        ["workspace", "series_id", "location_id"], True,
        "Calibrate a location plate's perspective once, so a person's size comes from where they stand and how tall they are, not from the "
        "framing alone. horizon = the y of the eye line, ref = one object of known height standing on the floor {baseY: y of its foot, "
        "heightPct: how tall it is, heightM: its metres, default 2 for a door}, all fractions of the plate's height from the top; "
        "floorTop = the farthest floor (default baseY). Measure them by LOOKING at series.location.stage.check's grid, never by guessing. "
        "2D wide and two-shots with people in the location are then sized by it (cast depth 0 far to 1 near, heightM metres; medium and "
        "close keep their framing) and render again on the next production; the reply lists them. clear: true takes the stage away. "
        "Editable in Series Lab's location panel.",
    ),
    "series.location.stage.check": (
        {"workspace": _WORKSPACE, "series_id": _ID, "location_id": _ID, "asset_id": _ID, "file": {"type": "string", "maxLength": 300},
         "step": {"type": "number", "minimum": 0.05, "maximum": 0.25}, **_STAGE},
        ["workspace", "series_id", "location_id"], False,
        "Calibration aid, changes nothing in the series: draws a grid (a line every 10 %, labelled with the fraction of the plate; step "
        "changes it) over the location's still plate, or file / asset_id, and saves it as a workspace file (grid.url, grid.file). LOOK at "
        "that image and read baseY / heightPct / horizon off it. Also returns the plate's size, the saved stage and a cheap horizon guess "
        "with its confidence (a guess: a room has no visible horizon; a horizontal edge in a room is the wall-floor junction). With horizon "
        "and ref it draws that proposal too (horizon, reference, three 1.75 m bars at depth 0, 0.5 and 1) so you can check it before "
        "series.location.stage.set. Warnings figure_scale_off and stage_missing in the script check point here.",
    ),
}


def _path(data: dict[str, Any], tail: str) -> str:
    return f"/api/v1/series/{quote(str(data['series_id']), safe='')}/locations/{quote(str(data['location_id']), safe='')}/stage{tail}"


def _set(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    body = {key: data[key] for key in ("workspace", "horizon", "ref", "floorTop", "clear") if key in data}
    return request("POST", _path(data, ""), body=body)


def _check(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    body = {key: data[key] for key in ("workspace", "asset_id", "file", "step", "horizon", "ref", "floorTop") if key in data}
    return request("POST", _path(data, "/check"), body=body)


RUNNERS: dict[str, Callable[..., Any]] = {"series.location.stage.set": _set, "series.location.stage.check": _check}
