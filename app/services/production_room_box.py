"""Box rooms for a production: a metric interior from flat textures, beside the mold rooms.

``spec.sets`` maps a name to ``{kind: "room", prompt, size: {w, d, h}, floor, walls, ceiling?, door?, windows?, props?, seed}``
with no ``mold``. ``prompt`` is the place. It is stored and it is not painted into the floor, the walls or the ceiling:
those are flat repeating textures, and a place (or the production's look) makes the image model draw a scene in
perspective. A prop is its own cutout, also without the place or the look. Door and windows are holes, not pictures.

The built record's kind is ``room_box`` (see ``production_models``), so the mold builder is never asked to build one.
"""
from __future__ import annotations

import copy
from typing import Any

from services.production_diorama import GROUND_STAGING
from services.production_seeds import default_seed
from services.room_box import build_room, check_box, image_count, normalize

WALL_STAGING = ("Flat orthographic view straight at a wall, the pattern fills the whole picture edge to edge and repeats "
                "evenly, everything in sharp focus, flat even lighting, no perspective, no floor, no ceiling, no corners, "
                "no furniture, no people, no shadows")
CEILING_STAGING = ("Flat orthographic view straight at a ceiling, the pattern fills the whole picture edge to edge and "
                   "repeats evenly, everything in sharp focus, flat even lighting, no perspective, no walls, no lights, no people")
PROP_STAGING = ("One object alone, full height, centered, on a plain flat background, no room, no floor, no walls, no people, no text")
SURFACE_SIZE = "1024x1024"
PROP_SIZE = "768x1024"
RECIPE = 1


def check_room_box(name: str, entry: dict, _text=None) -> str | None:
    return check_box(name, entry)


def recipe(entry: dict) -> dict:
    return {**entry, "recipe": RECIPE}


def is_built(record: dict) -> bool:
    return bool(record.get("file"))


def picture_jobs(production: Any, name: str, entry: dict, look: str, choice: tuple) -> dict[str, str | None]:
    """Image jobs keyed ``set:<name>:<part>``. ``look`` is ignored on purpose: flat textures take no production look."""
    del look
    spec = normalize(entry)
    seed = spec.get("seed", default_seed(production, 11))
    attempt = production._attempt("set_attempts", name)
    production.state["sets"][name]["entry"] = copy.deepcopy(entry)
    parts = {
        "floor": (f"A seamless tileable texture seen from straight above: {spec['floor']}. {GROUND_STAGING}", SURFACE_SIZE),
        "walls": (f"A seamless tileable wall texture: {spec['walls']}. {WALL_STAGING}", SURFACE_SIZE),
    }
    if spec.get("ceiling"):
        parts["ceiling"] = (f"A seamless tileable ceiling texture: {spec['ceiling']}. {CEILING_STAGING}", SURFACE_SIZE)
    for index, prop in enumerate(spec["props"]):
        parts[f"prop-{index + 1}"] = (f"{prop['prompt']}. {PROP_STAGING}", PROP_SIZE)
    return {f"set:{name}:{part}": production.image(f"set-{name}-{part}", prompt, None, size, seed + index, *choice, attempt)
            for index, (part, (prompt, size)) in enumerate(parts.items())}


def build(production: Any, name: str, record: dict) -> None:
    """One GLB for the set, from the pictures already in the workspace."""
    pictures = record.pop("pictures", {})
    spec = normalize(record.get("entry") or {})
    stem = f"set-{production.id}-{name}.glb"
    textures = {key: production.root / pictures[key] for key in ("floor", "walls", "ceiling") if key in pictures}
    textures["props"] = [production.root / pictures[f"prop-{index + 1}"] for index in range(len(spec["props"])) if f"prop-{index + 1}" in pictures]
    try:
        build_room(production.root / stem, spec, textures)
    except (OSError, ValueError, KeyError) as error:
        record["error"] = f"room build failed: {error}"
        return
    record.update(file=stem, url=_url(production, stem), roomBox=spec)
    production.log(f"set {name}: box room {spec['size']['w']}×{spec['size']['d']}×{spec['size']['h']} m")


def image_counts(entry: dict) -> int:
    """How many pictures a box room asks for. An entry that does not normalise counts as none."""
    return image_count(entry)


def _url(production: Any, file: str) -> str:
    return f"/api/v1/file/{file}?workspace={production.ws}"
