"""The five directions of a character and the data contract that the 3D engine reads from the animations of a Character Kit.

A character that moves in a 3D set is drawn from five directions. Qwen makes the ones that face the right; the ones that face the
left are the same sheets **mirrored when they are rendered** (they are never generated):

    side      the profile, looking right        walk-12   idle-side
    front34   three quarters from the front     walk-front34   idle-front34   (looks toward the camera and to the right)
    front     from the front                    walk-front   idle           (looks toward the camera)
    back34    three quarters from behind        walk-back34   idle-back34    (moves away toward the right)
    back      from behind                       walk-back   idle-back      (moves away from the camera)

THE CONTRACT (do not change it without telling the engine): each animation of ``kit["animations"]`` may carry

    ``motion``  ``"walk"`` | ``"idle"``                                         what the sheet does
    ``dir``     ``"side"`` | ``"front"`` | ``"front34"`` | ``"back34"`` | ``"back"``   the way the character faces in it

and a reader that finds neither on an entry gets them with ``contract_of``: ``dir`` from the entry's ``view`` (``side`` is ``side``,
``front`` is ``front``, ``front34``, ``back34`` and ``back`` are themselves, a ``bust`` has none) and ``motion`` from ``group: cycle``
plus an id that starts with ``walk`` or ``idle`` (a gesture, an expression, ``run``, ``jump``, ``step`` and an author's own animation
have none). What is stored wins over what is deduced. The sheet is a grid of equal cells (``sheet.columns`` x ``sheet.rows``,
``sheet.count`` of them in the order of the poses) with the boots on the line ``feet`` of the cell, as always; ``fps`` and ``loop``
say how it plays. ``facing`` is ``right`` for ``side``, ``front34`` and ``back34`` (flip the cell to face left) and ``front`` for the
two views that look neither way. When one direction has several sheets (the four-pose ``walk`` and the twelve-pose ``walk-12``, both
``side``), ``sheets_for`` lists the approved ones best first: more cells first, then the order of the kit. The ids above are the
catalog's, but the engine should look sheets up by ``motion`` and ``dir``.

``walk_sheet`` is the sheet a Series entrance (``enterGait: "walk"``) plays: the approved ``walk-12``, else the approved ``walk``.
The same rules are in ``ui/src/lib/characterAnimationDirections.ts`` for the code that runs in the browser and in node.
"""
from __future__ import annotations

from typing import Any

from services.character_animations import DIRS, MOTIONS, animation as catalog_animation

# The view of a sheet is the direction it shows; a bust is a portrait and has none.
_VIEW_DIR = {direction: direction for direction in DIRS}
WALK_SHEETS = ("walk-12", "walk")
_APPROVED = "approved"


def _catalog_entry(animation_id: str) -> dict[str, Any]:
    try:
        return catalog_animation(animation_id)
    except KeyError:
        return {}


def _listed(value: Any, allowed: tuple[str, ...]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def contract_of(animation_id: str, entry: dict[str, Any] | None = None) -> dict[str, str]:
    """``{"motion"?, "dir"?}`` of an animation: what its entry stores, else what its view, group and id say, else what the catalog says
    about that id. A key that cannot be told is left out."""
    listed = _catalog_entry(animation_id)
    stored = entry or {}
    found = {"dir": _listed(stored.get("dir"), DIRS), "motion": _listed(stored.get("motion"), MOTIONS)}
    if found["dir"] is None:
        found["dir"] = _VIEW_DIR.get(str(stored.get("view") or listed.get("view") or ""))
    if found["motion"] is None:
        group = stored.get("group") or listed.get("group")
        found["motion"] = next((motion for motion in MOTIONS if group == "cycle" and animation_id.startswith(motion)), None)
        found["motion"] = found["motion"] or _listed(listed.get("motion"), MOTIONS)
    return {key: value for key, value in found.items() if value}


def sheets_for(animations: dict[str, Any], motion: str, direction: str, *, approved: bool = True) -> list[tuple[str, dict[str, Any]]]:
    """The sheets of a kit that do ``motion`` facing ``direction``, best first: more cells, then the kit's own order. Only approved
    ones unless ``approved`` is false."""
    def does(name: str, made: dict[str, Any]) -> bool:
        said = contract_of(name, made)
        return said.get("motion") == motion and said.get("dir") == direction

    found = [(name, made) for name, made in animations.items()
             if isinstance(made, dict) and (not approved or made.get("reviewState") == _APPROVED) and does(name, made)]
    return sorted(found, key=lambda item: -int(((item[1].get("sheet") or {}).get("count")) or 0))


def walk_sheet(animations: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The approved sheet an entrance walks with: ``walk-12`` first, then ``walk``; None when neither is approved."""
    for name in WALK_SHEETS:
        made = animations.get(name)
        if isinstance(made, dict) and made.get("reviewState") == _APPROVED:
            return name, made
    return None


def has_walk_sheet(animations: dict[str, Any]) -> bool:
    """Whether the kit has any sheet of ``WALK_SHEETS`` at all, whatever its review state."""
    return any(isinstance(animations.get(name), dict) for name in WALK_SHEETS)
