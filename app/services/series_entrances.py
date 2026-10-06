"""A character walking into a 2D Series shot: when, how long, with what gait, and where its feet land.

A ``layout2d.cast`` entry with ``enterFrom`` (``left``/``right``) slides in from beyond that edge of the frame:

    {"characterId": "monk", "x": 60, "enterFrom": "left", "enterAt": 0.5, "enterDuration": 3.0,
     "enterGait": "walk", "enterStep": 0.6}

* ``enterAt``: when the entrance starts (s, default 0.2); ``enterDuration``: how long it lasts (s, default 1.2, so
  the default entrance ends at 1.4 s). Both are kept inside the shot.
* ``enterGait``: ``hop`` (the default: the paper puppet's little hop every 0.22 s) or ``walk``: a small bob on every
  step, highest mid-step and down on each footfall, with a slight sway (``enterSway`` degrees, default 1.5; 0 for
  none). ``enterStep`` is the walk's step in seconds (default 0.5); the walk takes a whole number of steps, so the
  step is stretched a little to fit the entrance, and its feet land on its start, every step after it and its end.

``entrance`` plans one entry for the compiler (``ui/scripts/seriesShot.ts`` draws the gait) and ``footfalls`` says
when its feet land, so sound can follow: an sfx or fx cue with ``"anchor": "enter"`` and ``"cast"`` (an index into the
shot's cast, or a character id) plays at the start of that entrance plus its ``offset``, and an sfx with
``"repeat": "steps"`` plays once on every footfall (``series_shot_extras``).
"""
from __future__ import annotations

import math
from typing import Any

GAITS = ("hop", "walk")
SIDES = {"left": -15.0, "right": 115.0}
DEFAULT_START = 0.2
DEFAULT_END = 1.4
# The compiler's hop: one every this many seconds, up on the odd ones (``bodyKeyframes`` in seriesShot.ts).
HOP_SECONDS = 0.22
WALK_STEP = 0.5
WALK_SWAY = 1.5
_LIMITS = (("enterAt", 0, 600), ("enterDuration", 0.1, 60), ("enterStep", 0.2, 2), ("enterSway", 0, 8))


def _number(value: Any, low: float, high: float) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high else None


def entry_fields(value: dict[str, Any]) -> dict[str, Any]:
    """The entrance fields of a cast entry that are valid (the others are dropped, like the rest of ``layout2d``)."""
    found: dict[str, Any] = {key: float(value[key]) for key, low, high in _LIMITS if _number(value.get(key), low, high) is not None}
    if value.get("enterGait") in GAITS:
        found["enterGait"] = value["enterGait"]
    return found


def entrance(entry: dict[str, Any], duration: float) -> dict[str, Any] | None:
    """How a cast entry enters a shot of ``duration`` seconds: ``{fromX, start, end}`` plus, for a walk, ``gait``,
    ``step`` (s) and ``sway`` (degrees). None when it is there from the start."""
    if entry.get("enterFrom") not in SIDES:
        return None
    at, length = _number(entry.get("enterAt"), 0, 600), _number(entry.get("enterDuration"), 0.1, 60)
    start = round(min(DEFAULT_START if at is None else at, max(0.0, duration - 0.1)), 3)
    end = round(min(duration, max(start + 0.1, start + (DEFAULT_END - DEFAULT_START if length is None else length))), 3)
    planned: dict[str, Any] = {"fromX": SIDES[entry["enterFrom"]], "start": start, "end": end}
    if entry.get("enterGait") == "walk":
        wanted = _number(entry.get("enterStep"), 0.2, 2) or WALK_STEP
        steps = max(1, round((end - start) / wanted))
        sway = _number(entry.get("enterSway"), 0, 8)
        planned.update(gait="walk", step=round((end - start) / steps, 4), sway=WALK_SWAY if sway is None else sway)
    return planned


def footfalls(planned: dict[str, Any]) -> list[float]:
    """When the feet of an entrance land: a walk on its start and every step to its end; a hop on its start, every
    other hop (the compiler lifts the odd ones) and its end."""
    start, end = planned["start"], planned["end"]
    if planned.get("gait") == "walk":
        count = max(1, round((end - start) / planned["step"]))
        return [round(start + (end - start) * index / count, 3) for index in range(count + 1)]
    hops = max(1, math.floor((end - start) / HOP_SECONDS + 0.5))  # Math.round, as the compiler counts them
    landed = [round(start + (end - start) * index / hops, 3) for index in range(0, hops, 2)]
    return [*landed, round(end, 3)]


def shot_entrances(shot: dict[str, Any], duration: float, framing: str = "") -> list[dict[str, Any] | None]:
    """The entrance of every cast entry of a 2D shot (``layout2d.cast``, else ``visibleCharacterIds``), in order, each
    with its ``characterId``; None for one that is there from the start. A ``title`` framing has no cast."""
    if framing == "title":
        return []
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    explicit = [item for item in layout.get("cast") or [] if isinstance(item, dict) and item.get("characterId")]
    entries = explicit or [{"characterId": cid} for cid in shot.get("visibleCharacterIds") or []]
    planned = ((entry, entrance(entry, duration)) for entry in entries)
    return [{**found, "characterId": entry["characterId"]} if found else None for entry, found in planned]


def find(entrances: list[dict[str, Any] | None] | None, cast: Any) -> dict[str, Any] | None:
    """The entrance a cue names: ``cast`` is an index into the shot's cast or a character id."""
    if not entrances:
        return None
    if isinstance(cast, int) and not isinstance(cast, bool):
        return entrances[cast] if 0 <= cast < len(entrances) else None
    return next((item for item in entrances if item and item.get("characterId") == cast), None)
