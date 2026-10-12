"""Look room in a 2D Series shot: a character stands with the open frame in front of their gaze.

Film grammar ("look room", "nose room"): a figure facing screen-left stands right of centre, one facing right stands
left of it, and two people in a shot face each other. Which way a pose looks comes from its kit (``facing``) or is
detected on its image (``pose_facing``).

``series.episode.from_script`` keeps it (``apply``): one person facing left left of the centre band (x < 45), or
facing right right of it (x > 55), is mirrored to ``100 - x``; two people who look away from each other swap their x
when that makes fewer of them look away; three or more are never moved, only reported. A cast entry with
``lookRoom: false`` (or a shot with it), an entrance (``enterFrom``...) or a ``transform`` keeps its x, as does a
pose cut by its image border on one side only, which edge snap holds on that side (unless ``edgeSnap: false``).
``series.shot.update`` moves nobody: the user's edit wins, and ``warnings`` says who looks out of the frame.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from services import pose_facing, series_cutouts
from services.series_shot_plan import cast_x

LOW, HIGH = 45.0, 55.0
REASONS = {"crowd": "three or more in the shot: nobody is moved", "same": "both look the same way: swapping does not help"}


class Poses:
    """Which way each (character, pose) of a series looks and the side an edge-cut pose is held on, read once."""

    def __init__(self, series: dict[str, Any], kits: dict[str, Any], root: str | None) -> None:
        self.kits = {item.get("id"): kits.get(((item.get("voiceProfile") or {}).get("characterKitRef") or {}).get("id") or "")
                     for item in series.get("characters") or [] if isinstance(item, dict)}
        self.root, self.found = root, {}

    def __call__(self, character: str, pose: str) -> dict[str, Any]:
        if (character, pose) not in self.found:
            kit = self.kits.get(character)
            facing = pose_facing.kit_pose_facing(kit, pose, self.root) or {}
            path = pose_facing.workspace_path((pose_facing.pose_asset(kit, pose) or {}).get("source"), self.root)
            measured = series_cutouts.measure(Path(path)) if path else None
            sides = [side for side in ("left", "right") if side in ((measured or [None, {}])[1] or {})]
            self.found[(character, pose)] = {"facing": facing.get("facing"), "held": sides[0] if len(sides) == 1 else None}
        return self.found[(character, pose)]


def _pinned(entry: dict[str, Any]) -> bool:
    return entry.get("lookRoom") is False or isinstance(entry.get("transform"), dict) or any(key.startswith("enter") for key in entry)


def _members(series: dict[str, Any], shot: dict[str, Any], poses: Poses) -> list[dict[str, Any]]:
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    if layout.get("lookRoom") is False or shot.get("productionMethod", "animation_2d") != "animation_2d":
        return []
    entries = [entry for entry in layout.get("cast") or [] if isinstance(entry, dict) and entry.get("characterId")]
    members = []
    for entry, x in zip(entries, cast_x(series, shot)):
        pose = str(entry.get("poseId") or "base")
        facts = poses(entry["characterId"], pose)
        members.append({"entry": entry, "character": entry["characterId"], "pose": pose, "x": x, "facing": facts["facing"],
                        "held": None if entry.get("edgeSnap") is False else facts["held"], "pinned": _pinned(entry)})
    return members


def _out(member: dict[str, Any]) -> bool:
    return (member["facing"] == "left" and member["x"] < LOW) or (member["facing"] == "right" and member["x"] > HIGH)


def _fits(member: dict[str, Any], x: float) -> bool:
    """An edge-cut pose stays on its cut side (edge snap would bring it back)."""
    return not member["held"] or ("left" if x < 50 else "right") == member["held"]


def _away(member: dict[str, Any], x: float, other: float) -> bool:
    return (member["facing"] == "left" and x < other) or (member["facing"] == "right" and x > other)


def _one(member: dict[str, Any]) -> tuple[list, list]:
    if member["pinned"] or not _out(member):
        return [], []
    target = 100 - member["x"]
    return ([(member, target)], []) if _fits(member, target) else ([], [(member, "cut")])


def _two(first: dict[str, Any], second: dict[str, Any]) -> tuple[list, list]:
    a, b = first["x"], second["x"]
    before = _away(first, a, b) + _away(second, b, a)
    if a == b or not before or first["pinned"] or second["pinned"]:
        return [], []
    if _away(first, b, a) + _away(second, a, b) >= before:
        reason = "same"
    elif not (_fits(first, b) and _fits(second, a)):
        reason = "cut"
    else:
        return [(first, b), (second, a)], []
    return [], [(member, reason) for member, x, other in ((first, a, b), (second, b, a)) if _away(member, x, other)]


def plan(series: dict[str, Any], shot: dict[str, Any], poses: Poses) -> tuple[list, list]:
    """``(moves, kept)`` for one shot: ``[(member, new x)]`` and ``[(member, reason)]`` for who still looks out."""
    members = _members(series, shot, poses)
    if len(members) == 1:
        return _one(members[0])
    if len(members) == 2:
        return _two(*members)
    return [], [(member, "crowd") for member in members if not member["pinned"] and _out(member)]


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(float(value), 2)


def _reason(member: dict[str, Any], code: str) -> str:
    if code == "cut":
        return f"cut on its {member['held']} side: edge snap holds it there (edgeSnap false frees it)"
    return REASONS[code]


def _who(shot: dict[str, Any], member: dict[str, Any]) -> dict[str, Any]:
    return {"shot": shot.get("id"), "character": member["character"], "pose": member["pose"], "facing": member["facing"]}


def apply(series: dict[str, Any], kits: dict[str, Any], shots: list[dict[str, Any]], root: str | None) -> dict[str, list]:
    """Move the cast of each 2D shot so nobody looks out of the frame (the shots' ``layout2d.cast`` x is changed in
    place). Returns ``lookRoom`` (every move: shot, character, pose, facing, from, to) and ``lookRoomKept`` (who still
    looks out, with the reason), each only when not empty."""
    poses, moved, kept = Poses(series, kits, root), [], []
    for shot in shots:
        moves, still = plan(series, shot, poses)
        for member, target in moves:
            member["entry"]["x"] = _number(target)
            moved.append({**_who(shot, member), "from": _number(member["x"]), "to": _number(target)})
        kept += [{**_who(shot, member), "x": _number(member["x"]), "reason": _reason(member, code)} for member, code in still]
    return {key: value for key, value in (("lookRoom", moved), ("lookRoomKept", kept)) if value}


def warnings(series: dict[str, Any], kits: dict[str, Any], shot: dict[str, Any], root: str | None) -> list[str]:
    """Who looks out of the frame in this shot as it stands; nothing is moved."""
    moves, still = plan(series, copy.deepcopy(shot), Poses(series, kits, root))
    found = [f"{member['character']} ({member['pose']}) faces {member['facing']} at x {_number(member['x'])} and looks out "
             f"of the frame: x {_number(target)} gives look room (lookRoom false on the cast entry silences this)"
             for member, target in moves]
    return found + [f"{member['character']} ({member['pose']}) faces {member['facing']} at x {_number(member['x'])} and looks "
                    f"out of the frame ({_reason(member, code)})" for member, code in still]
