"""The look of a flat rig (``characters.rig.flat`` ``style``) and the look a kit keeps between rigs.

``rig_style`` checks a look: the paper mouths' ``smile``, ``smirk``, ``width`` and ``mouth_scale``, ``screen`` for a
face that is a screen and ``mouthStyle``. ``kit_look`` is the look a rig of a kit uses: the keys the call gives over
the kit's own look, its last rig's, else the rig defaults of the character style preset it was made in
(``character_styles``), so a re-rig (a pose added, a mouth line placed, an agent's call with no style) keeps a warp
kit warp unless ``style.mouthStyle`` says otherwise.
"""
from __future__ import annotations

from typing import Any

from services.character_styles import preset_rig
from services.flat_rig_base import FlatRigError

STYLE_LIMITS = {"smile": (-1.0, 1.0, 0.15), "smirk": (0.0, 1.0, 0.0), "width": (0.3, 0.9, 0.62),
                "mouth_scale": (0.4, 1.2, 0.78)}
# paper: the painted mouth is wiped and nine paper mouths are drawn. ink: it is kept as the rest shape and the open
# shapes are dark openings in its own ink. warp: the pose's own lower face moves (flat_rig_warp), per pose.
MOUTH_STYLES = ("paper", "ink", "warp")


def rig_style(value: Any) -> dict[str, Any]:
    """Mouth look: ``smile`` -1..1, ``smirk`` 0..1, ``width`` and ``mouth_scale`` (paper mouths); ``screen`` for a
    screen face; ``mouthStyle`` ``paper`` (default), ``ink`` or ``warp``."""
    raw = value if isinstance(value, dict) else {}
    style: dict[str, Any] = {"screen": raw.get("screen") is True}
    for key, (low, high, default) in STYLE_LIMITS.items():
        number = raw.get(key, default)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not low <= float(number) <= high:
            raise FlatRigError("invalid_style", f"style.{key} must be a number from {low} to {high}")
        style[key] = float(number)
    mouth_style = raw.get("mouthStyle", "paper")
    if mouth_style not in MOUTH_STYLES:
        raise FlatRigError("invalid_style", "style.mouthStyle must be paper, ink or warp")
    style["mouthStyle"] = mouth_style
    return style


LOOK_KEYS = ("screen", *STYLE_LIMITS, "mouthStyle")


def _saved_look(kit: dict[str, Any]) -> dict[str, Any]:
    """The kit's own look: the last rig's, else the rig defaults of the style preset the kit was made in (its
    ``character-style-create`` provenance). A look edited by hand into something invalid is ignored, as saved hints
    are."""
    for entry in reversed(kit.get("provenance") or []):
        if entry.get("method") == "flat-rig":
            saved = entry.get("style") if isinstance(entry.get("style"), dict) else {}
        elif entry.get("method") == "character-style-create":
            saved = preset_rig(entry.get("style"))
        else:
            continue
        try:
            rig_style(saved)
        except FlatRigError:
            return {}
        return {key: saved[key] for key in LOOK_KEYS if key in saved}
    return {}


def kit_look(kit: dict[str, Any], style: Any = None) -> dict[str, Any]:
    """The look a rig of this kit uses: the keys ``style`` gives over the kit's own look (``_saved_look``), then the
    defaults. A re-rig (a pose added, a mouth line placed) keeps a warp kit warp unless ``style.mouthStyle`` says
    otherwise."""
    return rig_style({**_saved_look(kit), **(style if isinstance(style, dict) else {})})
