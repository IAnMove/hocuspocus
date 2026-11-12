"""Presence and hit: what a screen effect lasts and how big it is when a Series script gives neither.

``shared/scene_effect_classes.json`` classifies every effect of ``shared/scene_effects.json``:

* ``presence``: an aura, a shield, light, weather, a screen grade. With no ``duration`` it lasts the whole shot.
* ``hit``: an impact, a burst, a flash, a beam. With no ``duration`` it lasts the seconds the table gives (0.25-1).

``size`` is read the same way. ``cover`` (a presence effect that fills a place) covers the subject the cue names (a cast
member, or ``x``/``y``) by framing, or the whole screen when it names none; ``framing`` (a hit, or an object such as a
portal) is proportioned to the framing; ``own`` leaves the default alone because that effect's ``size`` means something
else (drop size, glyph height) or the effect fills the frame already. A value the script writes always wins: this module
only answers for what it left out (``series_shot_extras.fx_cues``).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DOC = json.loads((Path(__file__).resolve().parents[1] / "shared" / "scene_effect_classes.json").read_text(encoding="utf-8"))
EFFECT_CLASSES: dict[str, dict[str, Any]] = _DOC["effects"]
PRESENCE, HIT = "presence", "hit"
SIZE_MAX = 200.0
_FALLBACK = {"class": HIT, "size": "own", "duration": _DOC["classes"][HIT]["duration"]}


def effect_class(kind: str) -> str:
    """``presence`` or ``hit``. An effect the table does not list is a hit that keeps its own size."""
    return str(EFFECT_CLASSES.get(kind, _FALLBACK)["class"])


def default_duration(kind: str) -> float | str:
    """The length of a cue that gives none: ``"shot"`` for a presence effect, seconds for a hit."""
    entry = EFFECT_CLASSES.get(kind, _FALLBACK)
    return str(_DOC["classes"][PRESENCE]["duration"]) if entry["class"] == PRESENCE else float(entry["duration"])


def _by_framing(table: dict[str, float], framing: str | None) -> float:
    return float(table.get(framing or "", table["default"]))


def default_size(kind: str, framing: str | None, has_subject: bool) -> float | None:
    """The ``size`` (% of the frame's shorter side) of a cue that gives none, or None to leave the effect's own default."""
    entry = EFFECT_CLASSES.get(kind, _FALLBACK)
    sizes = _DOC["sizes"]
    if entry["size"] == "own":
        return None
    if entry["size"] == "cover":
        base = _by_framing(sizes["cover"]["subject"], framing) if has_subject else float(sizes["cover"]["screen"])
    else:
        base = _by_framing(sizes["framing"], framing)
    return round(min(SIZE_MAX, base * float(entry.get("scale", 1))), 3)


def too_short(kind: str, seconds: Any, shot_seconds: float) -> bool:
    """A presence effect that a script gives fewer seconds than the table asks for, in a shot longer than it asks for."""
    warning = _DOC["warning"]
    if effect_class(kind) != PRESENCE or isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return False
    return seconds < warning["belowSeconds"] and shot_seconds > warning["inShotsLongerThanSeconds"]
