"""Talking-character operations for ``scenes.video2d.edit``: mount_character, add_line, animate_talk.

An agent building a cutout scene had to run the editor's TypeScript to mount
a Character Kit and compile its mouths. These operations do it on the
server through the same compiler as the Series render
(``ui/scripts/seriesShot.ts``):

- ``mount_character {workspace, kit_id, x, framing, pose_id?, z?, motion?}``
  places a kit (pose, nine mouths, blink) for a framing, eyes on the line;
- ``add_line {kit_id, id, text, start, end, filename, cues?, driver?}``
  adds the speech track, the dialogue beat and its mouth keyframes
  (``cues`` from ``audio.mouth_cues``; without them the text drives the mouths);
- ``animate_talk {motion?}`` rebuilds the bob while talking and the breath
  otherwise for every mounted character.

Kits are read from the workspace by a reader the runtime binds.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

FRAMINGS = ("wide", "two", "medium", "close")
MOTIONS = ("idle", "still", "shake")
_reader: Callable[[str, str], dict[str, Any] | None] | None = None


def bind_kit_reader(reader: Callable[[str, str], dict[str, Any] | None]) -> None:
    global _reader
    _reader = reader


def _edit():
    from services import video2d_edit
    return video2d_edit


def _kit(workspace: Any, kit_id: Any) -> dict[str, Any]:
    edit = _edit()
    if not isinstance(workspace, str) or not workspace:
        edit._fail("invalid_input", "mount_character needs the workspace that holds the Character Kit")
    if _reader is None:
        edit._fail("characters_unavailable", "Character Kits are not available in this runtime")
    kit = _reader(workspace, edit._id(kit_id))
    if not kit:
        edit._fail("character_not_found", f"No Character Kit {kit_id} in {workspace}")
    return kit


def _run(payload: dict[str, Any]) -> dict[str, Any]:
    from services.series_shot_bridge import SeriesShotError, run_series_shot
    try:
        return run_series_shot(payload)
    except SeriesShotError as error:
        _edit()._fail("character_op_failed", str(error))
    raise AssertionError("unreachable")


def _replace(document: dict, updated: dict) -> None:
    document.clear()
    document.update(updated)


def mount_character(document: dict, operation: dict, warnings: list) -> None:
    edit = _edit()
    edit._only(operation, {"op", "workspace", "kit_id", "x", "framing", "pose_id", "z", "motion"})
    if operation.get("framing") not in FRAMINGS:
        edit._fail("invalid_input", "framing must be wide, two, medium or close")
    x = edit._number(operation.get("x"), -50, 150, "invalid_input", "x is a percentage of the frame width")
    kit = _kit(operation.get("workspace"), operation.get("kit_id"))
    request = {"x": x, "framing": operation["framing"], "workspace": operation["workspace"],
               **({"poseId": operation["pose_id"]} if isinstance(operation.get("pose_id"), str) else {}),
               **({"z": float(operation["z"])} if isinstance(operation.get("z"), (int, float)) else {}),
               **({"motion": operation["motion"]} if operation.get("motion") in MOTIONS else {})}
    _replace(document, _run({"mode": "mount_character", "document": document, "kit": kit, "request": request}))


def add_line(document: dict, operation: dict, warnings: list) -> None:
    edit = _edit()
    edit._only(operation, {"op", "kit_id", "id", "text", "start", "end", "filename", "cues", "driver"})
    start = edit._number(operation.get("start"), 0, 600, "invalid_input", "start is seconds from the scene start")
    end = edit._number(operation.get("end"), start, 600, "invalid_input", "end comes after start")
    if not isinstance(operation.get("text"), str) or not operation["text"].strip():
        edit._fail("invalid_input", "A line needs its text")
    if not isinstance(operation.get("filename"), str) or not operation["filename"]:
        edit._fail("invalid_input", "A line needs the workspace audio file")
    line = {"id": edit._id(operation.get("id")), "kitId": edit._id(operation.get("kit_id")), "text": operation["text"].strip(),
            "start": start, "end": end, "filename": operation["filename"],
            **({"cues": operation["cues"]} if operation.get("cues") else {}),
            **({"driver": operation["driver"]} if isinstance(operation.get("driver"), str) else {})}
    if not operation.get("cues"):
        warnings.append({"code": "line_without_cues", "message": f"{line['id']}: mouths follow the text; pass cues from audio.mouth_cues"})
    _replace(document, _run({"mode": "add_line", "document": document, "line": line}))


def animate_talk(document: dict, operation: dict, warnings: list) -> None:
    edit = _edit()
    edit._only(operation, {"op", "motion"})
    motion = operation.get("motion", "idle")
    if motion not in MOTIONS:
        edit._fail("invalid_input", "motion must be idle, still or shake")
    _replace(document, _run({"mode": "animate_talk", "document": document, "motion": motion}))


HANDLERS = {"mount_character": mount_character, "add_line": add_line, "animate_talk": animate_talk}


def schemas(op_schema: Callable[[str, list[str], dict], dict], identity: dict) -> list[dict]:
    text = {"type": "string", "minLength": 1, "maxLength": 2000}
    return [
        op_schema("mount_character", ["workspace", "kit_id", "x", "framing"], {
            "workspace": {"type": "string", "minLength": 1, "maxLength": 120}, "kit_id": identity, "x": {"type": "number"},
            "framing": {"enum": list(FRAMINGS)}, "pose_id": identity, "z": {"type": "number"}, "motion": {"enum": list(MOTIONS)}}),
        op_schema("add_line", ["kit_id", "id", "text", "start", "end", "filename"], {
            "kit_id": identity, "id": identity, "text": text, "start": {"type": "number", "minimum": 0}, "end": {"type": "number", "minimum": 0},
            "filename": {"type": "string", "minLength": 1, "maxLength": 300}, "cues": {"type": ["array", "object"]}, "driver": {"type": "string"}}),
        op_schema("animate_talk", [], {"motion": {"enum": list(MOTIONS)}}),
    ]


DESCRIPTION = (
    " mount_character places a Character Kit (pose, nine mouths, blink) for a framing (wide feet on the floor; two, medium, close "
    "eyes on one line) at x %. add_line adds a recorded line of a mounted kit: its speech track, beat and mouth keyframes; pass "
    "cues from audio.mouth_cues for phonetic mouths. animate_talk rebuilds the bob while talking and the breath otherwise."
)
