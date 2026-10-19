"""What every surface of a box room wears: a procedural material by default, a picture from the image model once painted.

A stored room keeps, for each of floor, walls, ceiling (when it has one), door and trim, an entry:

- ``{"source": "procedural", "material", "color", "tile_m", "seed"}``: drawn by ``room_materials``, chosen from the words of
  the room's floor and walls, deterministic and free;
- ``{"source": "ai", "file", "tile_m", "prompt", "seed", "sha"}``: a picture the image model made for that surface (and
  healed so it repeats), kept as a PNG in the workspace so it can be opened again.

``build_room`` takes the pictures; ``complete_textures`` fills every surface it was not given with the procedural one.
``look_fingerprint`` identifies what the room looks like, so a Series shot that stands in it can tell when it changed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from services import room_materials

SURFACES = ("floor", "walls", "ceiling", "door", "trim")
_SEED = {"floor": 1, "walls": 2, "ceiling": 3, "door": 4, "trim": 5}
# Bumped when the room's geometry or lighting recipe changes, so a stored look no longer matches an older build.
GEOMETRY_VERSION = 1


def present(spec: dict) -> tuple[str, ...]:
    """The surfaces this room has: no ceiling picture unless the room has a ceiling."""
    return tuple(surface for surface in SURFACES if surface != "ceiling" or spec.get("ceiling"))


def default_entries(spec: dict, style: str = "") -> dict[str, dict]:
    """The procedural entry of each surface, from the words of the spec. ``style`` (or the place) decides only when a
    surface's own words name no material."""
    picks = room_materials.defaults_for(spec, style or spec.get("prompt") or "")
    base = int(spec.get("seed") or 0)
    return {surface: {"source": "procedural", **picks[surface], "seed": base + _SEED[surface]} for surface in present(spec)}


def procedural_picture(spec: dict, surface: str, entry: dict) -> Image.Image:
    color = room_materials.rgb_of(entry["color"])
    if surface == "door":
        return room_materials.door_leaf(entry["material"], entry["seed"], color, spec["door"]["w"], spec["door"]["h"])
    return room_materials.make(entry["material"], entry["seed"], color)


def complete_textures(spec: dict, textures: dict) -> dict:
    """``textures`` plus a procedural picture (and its metres per repeat) for every surface it does not name."""
    done = dict(textures)
    tiles = dict(done.get("tile_m") or {})
    door_given = bool(done.get("door"))
    for surface, entry in default_entries(spec).items():
        if done.get(surface):
            continue
        done[surface] = procedural_picture(spec, surface, entry)
        tiles[surface] = entry["tile_m"]
    done["tile_m"] = tiles
    done.setdefault("door_panels", not door_given)
    return done


def textures_of(root: Path, spec: dict, entries: dict) -> dict:
    """The ``build_room`` textures a stored room's entries describe: picture files for ``ai`` surfaces, a procedural
    picture for the others."""
    textures: dict = {"tile_m": {}}
    for surface, entry in entries.items():
        if surface not in present(spec):
            continue
        textures["tile_m"][surface] = float(entry["tile_m"])
        textures[surface] = (root / entry["file"]) if entry.get("source") == "ai" else procedural_picture(spec, surface, entry)
    textures["door_panels"] = (entries.get("door") or {}).get("source") != "ai"
    return textures


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def look_fingerprint(spec: dict, entries: dict) -> str:
    """Identity of what the room looks like: the spec, each surface's entry (an ``ai`` one carries its picture's hash)
    and the versions of the drawings and of the geometry."""
    payload = {"spec": spec, "surfaces": {key: entries[key] for key in sorted(entries)},
               "materials": room_materials.VERSION, "geometry": GEOMETRY_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()[:16]
