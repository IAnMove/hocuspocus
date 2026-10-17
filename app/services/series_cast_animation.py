"""A kit animation in a 2D Series shot: a character waves, gets angry or walks in with the drawings of its own sheet.

A ``layout2d.cast`` entry (a script shot's cast entry) takes ``animation``: the id of one of the animations of the
character's Character Kit (``app/shared/character_animations.json``: ``walk``, ``wave``, ``angry``, ``happy``... or one the
author made) or a window of it:

    {"characterId": "ana", "x": 40, "animation": "wave"}
    {"characterId": "ana", "x": 40, "animation": {"id": "angry", "at": 2.5, "duration": 1.2, "loop": "once"}}

* ``at``: when it starts, in seconds inside the shot (default 0). ``duration``: how long it plays (default one pass of the
  sheet: its cells over its fps, back and forth for a ``pingpong``). ``loop``: ``loop``, ``pingpong`` or ``once`` (the sheet's own
  by default; ``true`` is ``loop`` and ``false`` is ``once``).
* Only an ``approved`` animation can be played: a sheet that is still pending, or was rejected, is refused by the script check
  with the way out (approve it in Characters > Animaciones).
* While the sheet plays it takes the pose's place: the pose picture and its mouth and eyes are hidden and come back when it
  ends. The compiler (``ui/scripts/seriesShot.ts`` and ``seriesSheet.ts``) draws it; this module only says what is asked.

``enterGait: "walk"`` uses the kit's approved ``walk`` sheet for the whole entrance (``walk_window`` is its interval): the
entrance, its steps and its footfalls are planned as ever (``series_entrances``) and the compiler decides, from the kit, whether
a sheet or the body bob walks. A cast member whose ``walk`` sheet is not approved keeps the bob, and the check warns.
"""
from __future__ import annotations

import re
from typing import Any

from services import series_entrances as entrances

LOOPS = ("loop", "pingpong", "once")
WALK = "walk"
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_LIMITS = (("at", 0, 600), ("duration", 0.1, 600))
_MIN_LEFT = 0.1
_FORMS = "animation must be an animation id or {id, at, duration, loop}"


def _number(value: Any, low: float, high: float) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high else None


def _loop(value: Any) -> str | None:
    if isinstance(value, bool):
        return "loop" if value else "once"
    return value if value in LOOPS else None


def request(value: Any) -> dict[str, Any] | None:
    """The animation a cast entry asks for as ``{id, at?, duration?, loop?}``; bad numbers and loops are dropped (like the
    rest of ``layout2d``), a value that names no animation is None."""
    if isinstance(value, str):
        return {"id": value} if _ID.fullmatch(value) else None
    if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not _ID.fullmatch(value["id"]):
        return None
    found: dict[str, Any] = {"id": value["id"]}
    for key, low, high in _LIMITS:
        number = _number(value.get(key), low, high)
        if number is not None:
            found[key] = number
    loop = _loop(value.get("loop"))
    if loop is not None:
        found["loop"] = loop
    return found


def entry_fields(value: dict[str, Any]) -> dict[str, Any]:
    """The ``animation`` of a cast entry when it is valid (stored as the window, even when the entry gave only the id)."""
    found = request(value.get("animation"))
    return {"animation": found} if found else {}


def planned(entry: dict[str, Any], duration: float) -> dict[str, Any] | None:
    """The animation of a cast entry inside a shot of ``duration`` seconds: ``{id, at, duration?, loop?}``. It starts inside the
    shot (an animation after the end still happens in it, like an entrance) and never ends after it. A missing ``duration`` is
    left to the compiler: one pass of the sheet."""
    found = request(entry.get("animation"))
    if found is None:
        return None
    at = round(min(found.get("at", 0.0), max(0.0, duration - _MIN_LEFT)), 3)
    plan: dict[str, Any] = {"id": found["id"], "at": at}
    if "duration" in found:
        plan["duration"] = round(max(_MIN_LEFT, min(found["duration"], duration - at)), 3)
    if "loop" in found:
        plan["loop"] = found["loop"]
    return plan


def walk_window(enter: dict[str, Any] | None) -> tuple[float, float] | None:
    """When a planned entrance walks (the interval a ``walk`` sheet would play), None for a hop or no entrance."""
    if not enter or enter.get("gait") != "walk":
        return None
    return float(enter["start"]), float(enter["end"])


# The script check ---------------------------------------------------------------------

def _kit_animations(checker: Any, character_id: str) -> dict[str, Any]:
    character = checker.characters.get(character_id) or {}
    kit = checker.kits.get(((character.get("voiceProfile") or {}).get("characterKitRef") or {}).get("id") or "") or {}
    return kit.get("animations") if isinstance(kit.get("animations"), dict) else {}


def _length(animation: dict[str, Any], loop: str) -> float:
    """Seconds of one pass of a sheet: its cells at its fps; a ``pingpong`` goes there and back."""
    sheet, fps = animation.get("sheet") or {}, float(animation.get("fps") or 4)
    count = int(sheet.get("count") or 1)
    cells = count * 2 - 2 if loop == "pingpong" and count > 1 else count
    return cells / fps


def _window_problems(raw: Any, where: str) -> list[str]:
    if request(raw) is None:
        return [f"{where}: {_FORMS}"]
    if not isinstance(raw, dict):
        return []
    found = []
    if raw.get("at") is not None and _number(raw["at"], 0, 600) is None:
        found.append(f"{where}: animation at must be a number from 0 to 600 seconds")
    if raw.get("duration") is not None and _number(raw["duration"], 0.1, 600) is None:
        found.append(f"{where}: animation duration must be a number from 0.1 to 600 seconds")
    if raw.get("loop") is not None and _loop(raw["loop"]) is None:
        found.append(f"{where}: animation loop must be one of {', '.join(LOOPS)}")
    return found


def _state_problem(animations: dict[str, Any], who: str, name: str, where: str) -> str | None:
    """Why the kit cannot play ``name``, None when it can."""
    made = animations.get(name)
    if not isinstance(made, dict):
        approved = sorted(key for key, item in animations.items() if isinstance(item, dict) and item.get("reviewState") == "approved")
        have = f"approved animations: {', '.join(approved)}" if approved else "it has no approved animations: make them in Characters › Animaciones"
        return f"{where}: animation '{name}' of '{who}' is not in its Character Kit ({have})"
    state = made.get("reviewState")
    if state == "approved":
        return None
    if state == "rejected":
        return f"{where}: animation '{name}' of '{who}' was rejected: make it again in Characters › Animaciones"
    return f"{where}: animation '{name}' of '{who}' is pending approval: approve it in Characters › Animaciones"


def playable_problem(animations: dict[str, Any], who: str, name: str, where: str) -> str | None:
    """Why the kit cannot play ``name`` (it has none, it is pending or it was rejected), in the script check's words; None when
    it can. A card applied to a shot (``series.shot.card.apply``) refuses the same sheets the script does."""
    return _state_problem(animations, who, name, where)


def _walk_in(entry: dict[str, Any], animations: dict[str, Any]) -> tuple[float, float] | None:
    """The interval a cast entry's approved ``walk`` sheet plays on its entrance, None when the entrance walks with the bob."""
    if (animations.get(WALK) or {}).get("reviewState") != "approved":
        return None
    return walk_window(entrances.entrance(entry, 600.0))


def _overlap_problem(entry: dict[str, Any], found: dict[str, Any], animations: dict[str, Any], who: str, where: str) -> str | None:
    walk = _walk_in(entry, animations)
    made = animations.get(found["id"])
    if walk is None or not isinstance(made, dict):
        return None
    start = found.get("at", 0.0)
    end = start + found.get("duration", _length(made, found.get("loop") or made.get("loop") or "loop"))
    if start < walk[1] and end > walk[0]:
        return (f"{where}: animation '{found['id']}' of '{who}' overlaps its walk-in ({walk[0]:g}-{walk[1]:g} s): "
                f"start it at {walk[1]:g} s or later")
    return None


def _check_entry(entry: dict[str, Any], animations: dict[str, Any], shot: dict[str, Any], where: str) -> list[str]:
    who = str(entry.get("characterId"))
    raw = entry["animation"]
    problems = _window_problems(raw, where)
    found = request(raw)
    if found is None:
        return problems
    state = _state_problem(animations, who, found["id"], where)
    if state:
        return [*problems, state]
    length = shot.get("duration") if not shot.get("lines") else None
    if isinstance(length, (int, float)) and not isinstance(length, bool) and found.get("at", 0.0) >= length:
        problems.append(f"{where}: animation '{found['id']}' of '{who}' starts at {found['at']:g} s, but the shot lasts {length:g} s")
    overlap = _overlap_problem(entry, found, animations, who, where)
    return [*problems, overlap] if overlap else problems


def check_cast(checker: Any, entries: list[dict[str, Any]], shot: dict[str, Any], where: str, shot_id: str,
               warnings: list[dict[str, Any]]) -> None:
    """Problems of the shot's cast animations (they stop the script) and a warning for a walk-in whose ``walk`` sheet is not
    approved (it walks with the body bob, as before)."""
    from services.series_script_warnings import group_warning
    for entry in entries:
        who = str(entry.get("characterId"))
        animations = _kit_animations(checker, who)
        if entry.get("animation") is not None:
            checker.problems.extend(_check_entry(entry, animations, shot, where))
        walking = entry.get("enterFrom") in entrances.SIDES and entry.get("enterGait") == "walk"
        walk = animations.get(WALK)
        if walking and isinstance(walk, dict) and walk.get("reviewState") != "approved":
            group_warning(warnings, "walk_sheet_not_approved", who, shot_id,
                          f"has a {WALK} sheet that is not approved, so its walk-in keeps the body bob: approve it in Characters › Animaciones")
