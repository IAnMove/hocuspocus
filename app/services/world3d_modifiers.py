"""Named modifiers of a Video 3D shot: lights, lenses and camera cards.

The tables are ``app/shared/world3d_modifiers.json``, read here and by ``ui/src/features/scene3d/modifiers.ts``
so the production compiler (Node) and ``world3d.scene.patch`` (Python) resolve the same names to the same numbers.
``world3d_grades.py`` reads the grades from the same file.
"""
from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

_FILE = Path(__file__).resolve().parents[1] / "shared" / "world3d_modifiers.json"
# A scaled framing fov stays inside the editor parser's 8-140 bounds with room to spare.
LENS_FOV_RANGE = (10, 130)


@lru_cache(maxsize=1)
def modifier_tables() -> dict:
    return json.loads(_FILE.read_text(encoding="utf-8"))


LIGHT_NAMES = tuple(modifier_tables()["lights"])
LENS_NAMES = tuple(modifier_tables()["lenses"])
CAMERA_FAMILIES = tuple(modifier_tables()["cameraFamilies"])


def named_light(name) -> dict:
    """The sun of a named light (``kind``, ``direction``, ``intensity``, ``color``) and its ``ambient`` share."""
    preset = modifier_tables()["lights"].get(name) if isinstance(name, str) else None
    if not preset:
        raise ValueError(f"unknown_light:{name}")
    return {"kind": "directional", "direction": list(preset["direction"]), "intensity": preset["intensity"],
            "color": preset["color"], "ambient": preset["ambient"]}


def apply_light(document: dict, name: str) -> None:
    """A named light replaces the document's sun and sets the ambient share; the rest of the lighting stays."""
    preset = named_light(name)
    ambient = preset.pop("ambient")
    document["light"] = preset
    environment = {"source": "room", "rotation": 0, "background": "set", "blur": 0,
                   **((document.get("lighting") or {}).get("environment") or {}), "intensity": ambient}
    document["lighting"] = {**(document.get("lighting") or {}), "environment": environment}


def light_object(raw) -> dict:
    """A directional light given as an object: ``direction`` (three numbers), ``intensity`` 0-10 and ``color`` #rrggbb."""
    if not isinstance(raw, dict) or raw.get("kind", "directional") != "directional" or set(raw) - {"kind", "direction", "intensity", "color"}:
        raise ValueError("light is a name or {kind: directional, direction: [x, y, z], intensity, color}")
    direction = raw.get("direction")
    if not isinstance(direction, list) or len(direction) != 3 or not all(type(value) in (int, float) for value in direction):
        raise ValueError("light.direction is [x, y, z]: the way the light travels")
    intensity = raw.get("intensity")
    if type(intensity) not in (int, float) or not 0 <= intensity <= 10:
        raise ValueError("light.intensity is 0-10")
    if _rgb(raw.get("color")) is None:
        raise ValueError("light.color is #rrggbb")
    return {"kind": "directional", "direction": [float(value) for value in direction], "intensity": float(intensity),
            "color": raw["color"].lower()}


def set_light(document: dict, raw) -> None:
    if isinstance(raw, str):
        apply_light(document, raw)
    else:
        document["light"] = light_object(raw)


def lens_fov(name) -> float:
    lens = modifier_tables()["lenses"].get(name) if isinstance(name, str) else None
    if not lens:
        raise ValueError(f"unknown_lens:{name}")
    return lens["fov"]


def apply_lens(document: dict, name: str) -> None:
    """A lens sets the camera's fov; a framing's fovFrom/fovTo keep their move, scaled by the same ratio."""
    fov = lens_fov(name)
    camera = deepcopy(document["camera"])
    current = camera.get("fov")
    ratio = fov / current if isinstance(current, (int, float)) and current > 0 else 1
    camera["fov"] = fov
    framing = camera.get("framing")
    if isinstance(framing, dict):
        low, high = LENS_FOV_RANGE
        for key in ("fovFrom", "fovTo"):
            if isinstance(framing.get(key), (int, float)):
                framing[key] = min(high, max(low, framing[key] * ratio))
    document["camera"] = camera


def card_kind(card: dict) -> str | None:
    """A card's ``kind`` when the catalog carries one, else ``camera`` for a technique of a camera family."""
    if card.get("kind"):
        return card["kind"]
    return "camera" if card.get("family") in CAMERA_FAMILIES else None


def check_camera_template(template_id) -> dict:
    """The card of a ``kind: camera`` id. An unknown id is ``unknown_template``; another kind is ``invalid_camera_template``."""
    from services.world3d_template_catalog import require_card
    card = require_card(template_id)
    if card_kind(card) != "camera":
        raise ValueError(f"invalid_camera_template:{template_id}")
    return card


def apply_camera_template(document: dict, technique: dict) -> list[str]:
    """The technique's camera and framing on this document, which keeps its duration, cast and place. The framing's
    target is re-read by the caller (``_retarget``). Warns when the two were authored for different frame formats."""
    document["camera"] = deepcopy(technique["camera"])
    portrait = (document.get("height") or 0) > (document.get("width") or 0)
    authored_portrait = (technique.get("height") or 0) > (technique.get("width") or 0)
    if portrait != authored_portrait:
        return [f"camera_template_format: the camera was authored {'portrait' if authored_portrait else 'landscape'} and the scene is "
                f"{'portrait' if portrait else 'landscape'}; apply the frame format again in the editor"]
    return []


def _rgb(color) -> tuple[int, int, int] | None:
    """#rrggbb or #rgb as channels; anything else is None."""
    if not isinstance(color, str) or not color.startswith("#") or len(color) not in (4, 7):
        return None
    digits = color[1:]
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    try:
        return tuple(int(digits[at:at + 2], 16) for at in (0, 2, 4))
    except ValueError:
        return None


def tinted(color, tint) -> str:
    """A gel over the lamp: each channel multiplied. An unreadable colour is kept as it is."""
    base, gel = _rgb(color), _rgb(tint)
    if base is None or gel is None:
        return color
    return "#" + "".join(f"{int(c * t / 255 + 0.5):02x}" for c, t in zip(base, gel))
