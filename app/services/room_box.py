"""A metric interior: an open box in metres, y up, for a cast that stands on the floor.

The origin is the middle of the floor. x runs to the right, z away from the camera. The open side (no wall) is
z = -depth/2, toward the camera; the back wall is z = +depth/2. Left is x = -width/2, right is x = +width/2.
Greater z is farther away. Walls are wound so their normals point into the room, and every material is double
sided, so a sign error is still visible from inside. ``fitGltf`` scales a model by 1.7 / bbox height about the
origin and does not recenter it: the floor is a plane at y = 0 (no thickness) and the walls reach the ceiling,
so a slot scale of ceiling/1.7 with ``grounded: false`` leaves the room in metres.

``kind: "room"`` with a ``mold`` is the other room (``production_rooms``). This module accepts ``kind: "room"``
only when there is no mold and the size is an object (or the entry already names a floor, walls, a door, windows
or a ceiling). The camera numbers live in ``app/shared/room_box_camera.json``; the TypeScript stage reads that
same file.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image


# pygltflib is an optional dependency that only the GLB writer needs; the boot path imports this module, so the
# diorama helpers (which import it at the top) are loaded when a room is built, not at import time.
def _quad(*args):
    from services.diorama_set import _quad as quad
    return quad(*args)


def _arrays(quads):
    from services.diorama_set import _arrays as arrays
    return arrays(quads)


_FRAME = json.loads((Path(__file__).resolve().parents[1] / "shared" / "room_box_camera.json").read_text(encoding="utf-8"))
TILE = float(_FRAME["floorTile"])
WALLS = ("back", "left", "right")
_NAME = __import__("re").compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_FIELDS = {"kind", "prompt", "size", "floor", "walls", "ceiling", "door", "windows", "props", "seed", "tile"}
_SIZE = {"w", "d", "h"}
_DOOR = {"wall", "x", "w", "h"}
_WINDOW = {"wall", "x", "y", "w", "h"}
_PROP = {"prompt", "on", "wall", "floor", "x", "z", "height_m"}
_TONES = {"floor": (186, 154, 104), "walls": (214, 208, 196), "ceiling": (232, 232, 228), "door": (128, 74, 38), "prop": (86, 138, 156)}


def is_box_room(entry) -> bool:
    """A box room wears ``kind: "room"`` and a size object (or a floor, walls, door, windows or ceiling) and no mold."""
    if not isinstance(entry, dict) or entry.get("kind") != "room" or "mold" in entry:
        return False
    return isinstance(entry.get("size"), dict) or any(key in entry for key in ("floor", "walls", "door", "windows", "ceiling"))


def camera_pose(depth: float, *, wide: bool = True) -> dict:
    """Eye at adult eye height just outside the open side, looking into the room. One formula, shared with TypeScript."""
    back = _FRAME["wideBack"] if wide else _FRAME["mediumBack"]
    return {
        "eye": [0.0, float(_FRAME["eyeHeight"]), round(-depth / 2 - back, 4)],
        "look": [0.0, float(_FRAME["lookY"]), round(depth * _FRAME["lookZShare"], 4)],
        "fov": float(_FRAME["fovWide"] if wide else _FRAME["fovMedium"]),
    }


def check_box(name: str, entry: dict) -> str | None:
    """Why ``entry`` is not a box room, or None. The message names the field."""
    try:
        normalize(entry)
    except (TypeError, ValueError) as error:
        return f"sets.{name}: {error}"
    return None


def normalize(entry: dict) -> dict:
    """The canonical box: defaults filled in (door 0.9×2.0, ceiling 2.6) and every measure checked."""
    if not isinstance(entry, dict):
        raise ValueError("a box room is an object")
    if entry.get("kind") != "room":
        raise ValueError('kind is "room"')
    if "mold" in entry:
        raise ValueError("a box room has no mold; a mold room keeps kind room with mold")
    unknown = set(entry) - _FIELDS
    if unknown:
        raise ValueError(f"unknown room fields: {', '.join(sorted(unknown))}")
    size = _size(entry.get("size"))
    _text(entry.get("prompt"), "prompt")
    _text(entry.get("floor"), "floor")
    _text(entry.get("walls"), "walls")
    ceiling = _ceiling(entry.get("ceiling"), size["h"])
    _own_tile(entry.get("tile"))
    if "door" in entry and entry["door"] is None:
        raise ValueError("door: null is not a door; omit it for a 0.9×2.0 door on the back wall")
    door = _door(entry["door"] if "door" in entry else None, size)
    windows = _windows(entry.get("windows", []), size, door)
    props = _props(entry.get("props", []), size)
    seed = _seed(entry.get("seed"))
    spec = {"kind": "room", "prompt": entry["prompt"].strip(), "size": size, "floor": entry["floor"].strip(),
            "walls": entry["walls"].strip(), "door": door, "windows": windows, "props": props, "tile": TILE}
    if ceiling:
        spec["ceiling"] = ceiling
    if seed is not None:
        spec["seed"] = seed
    return spec


def prop_point(size: dict, prop: dict) -> tuple[float, float, float]:
    """Where a prop's feet are. A wall prop's ``x`` runs along the wall from its centre and ``z`` is the inset."""
    width, depth = size["w"], size["d"]
    if prop["on"] == "floor":
        return (prop["x"], 0.0, prop["z"])
    inset = prop["z"]
    if prop["wall"] == "back":
        return (prop["x"], 0.0, depth / 2 - inset)
    if prop["wall"] == "left":
        return (-width / 2 + inset, 0.0, prop["x"])
    return (width / 2 - inset, 0.0, prop["x"])


def door_point(size: dict, door: dict) -> tuple[float, float, float]:
    """The door's foot, on the wall."""
    return prop_point(size, {"on": "wall", "wall": door["wall"], "x": door["x"], "z": 0.0})


def build_room(target: str | Path, spec: dict, textures: dict | None = None) -> dict:
    """Write the room GLB. ``textures`` maps floor/walls/ceiling/door and ``props`` (a list of images) to pictures."""
    spec = spec if _is_canonical(spec) else normalize(spec)
    _write(target, _parts(spec, textures or {}))
    size = spec["size"]
    return {"width": size["w"], "depth": size["d"], "height": size["h"]}


def placeholder_room(target: str | Path, spec: dict) -> dict:
    """The same geometry with flat colours, so a room can be placed before any texture exists."""
    return build_room(target, spec, {})


def _is_canonical(spec: dict) -> bool:
    size = spec.get("size") if isinstance(spec, dict) else None
    door = spec.get("door") if isinstance(spec, dict) else None
    return isinstance(size, dict) and "h" in size and isinstance(door, dict) and "w" in door and "tile" in spec


def _size(value) -> dict:
    if not isinstance(value, dict) or set(value) - _SIZE or "w" not in value or "d" not in value:
        raise ValueError("size is {w, d, h} in metres (h defaults to 2.6)")
    width, depth = _measure(value.get("w"), 2, 20, "size.w"), _measure(value.get("d"), 2, 20, "size.d")
    height = _FRAME["ceiling"] if "h" not in value else _measure(value.get("h"), 2.2, 6, "size.h")
    return {"w": width, "d": depth, "h": height}


def _ceiling(value, height: float) -> str | None:
    if value is None:
        return None
    _text(value, "ceiling")
    if height < 2.2:
        raise ValueError("ceiling is taller than the room")
    return value.strip()


def _door(value, size: dict) -> dict:
    if value is None:
        value = {"wall": "back", "x": 0, "w": _FRAME["doorWidth"], "h": _FRAME["doorHeight"]}
    if not isinstance(value, dict) or set(value) - _DOOR:
        raise ValueError("door is {wall, x, w, h} in metres, or omit it for a 0.9×2.0 door on the back wall")
    wall = _wall(value.get("wall", "back"), "door.wall")
    opening = {"wall": wall, "x": _measure(value.get("x", 0), -20, 20, "door.x"),
               "w": _measure(value.get("w", _FRAME["doorWidth"]), 0.4, 2.5, "door.w"),
               "h": _measure(value.get("h", _FRAME["doorHeight"]), 1.6, min(2.4, size["h"]), "door.h")}
    _fits(opening, size, "door")
    return opening


def _windows(value, size: dict, door: dict) -> list:
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("windows lists at most 8 {wall, x, y, w, h}")
    openings = []
    for index, window in enumerate(value):
        if not isinstance(window, dict) or set(window) - _WINDOW:
            raise ValueError(f"windows[{index}] is {{wall, x, y, w, h}} in metres")
        opening = {"wall": _wall(window.get("wall"), f"windows[{index}].wall"),
                   "x": _measure(window.get("x"), -20, 20, f"windows[{index}].x"),
                   "y": _measure(window.get("y"), 0, size["h"], f"windows[{index}].y"),
                   "w": _measure(window.get("w"), 0.3, 4, f"windows[{index}].w"),
                   "h": _measure(window.get("h"), 0.3, size["h"], f"windows[{index}].h")}
        if opening["y"] + opening["h"] > size["h"] - 0.02:
            raise ValueError(f"windows[{index}] does not fit under the ceiling")
        _fits(opening, size, f"windows[{index}]")
        openings.append(opening)
    _separate(door, openings, size)
    return openings


def _props(value, size: dict) -> list:
    if not isinstance(value, list) or len(value) > 12:
        raise ValueError("at most 12 props")
    return [_prop(prop, size, index) for index, prop in enumerate(value)]


def _prop(prop, size: dict, index: int) -> dict:
    if not isinstance(prop, dict) or set(prop) - _PROP:
        raise ValueError(f"props[{index}] is {{prompt, on: floor|wall, wall?, x, z, height_m}}")
    _text(prop.get("prompt"), f"props[{index}].prompt")
    on = _prop_on(prop, index)
    height = _measure(prop.get("height_m"), 0.05, min(4, size["h"]), f"props[{index}].height_m")
    x = _measure(prop.get("x"), -20, 20, f"props[{index}].x")
    if on == "floor":
        z = _measure(prop.get("z"), -20, 20, f"props[{index}].z")
        _inside_floor(size, x, z, f"props[{index}]")
        return {"prompt": prop["prompt"].strip(), "on": "floor", "x": x, "z": z, "height_m": height}
    wall = _wall(prop.get("wall"), f"props[{index}].wall")
    inset = _inset(prop.get("z", 0.02), size, wall, index)
    along = _measure(x, -_length(size, wall) / 2 + 0.05, _length(size, wall) / 2 - 0.05, f"props[{index}].x")
    return {"prompt": prop["prompt"].strip(), "on": "wall", "wall": wall, "x": along, "z": inset, "height_m": height}


def _prop_on(prop: dict, index: int) -> str:
    shorthand = "wall" if isinstance(prop.get("wall"), str) else "floor" if prop.get("floor") is True else None
    named = prop.get("on")
    if named is not None and shorthand is not None:
        raise ValueError(f"props[{index}] gives both on and a wall/floor shorthand")
    on = named or shorthand
    if on not in ("floor", "wall"):
        raise ValueError(f"props[{index}].on is floor or wall (or set wall to back, left or right, or floor: true)")
    if on == "wall" and prop.get("wall") is None:
        raise ValueError(f"props[{index}].wall is back, left or right")
    return on


def _inset(value, size: dict, wall: str, index: int) -> float:
    """``z`` is a small inset (0–0.5). A room coordinate that already sits against the wall is accepted too."""
    number = _measure(value, -20, 20, f"props[{index}].z")
    if 0 <= number <= 0.5:
        return number
    depth = {"back": size["d"] / 2 - number, "left": number - (-size["w"] / 2), "right": size["w"] / 2 - number}[wall]
    if not 0 <= depth <= 0.5:
        raise ValueError(f"props[{index}] wall prop must stand against a wall")
    return round(depth, 4)


def _inside_floor(size, x, z, what) -> None:
    if abs(x) > size["w"] / 2 - 0.02 or abs(z) > size["d"] / 2 - 0.02:
        raise ValueError(f"{what} is outside the floor")


def _separate(door: dict, windows: list, size: dict) -> None:
    rects = [(*_span(door, size), 0.0, door["h"], door["wall"])]
    for index, window in enumerate(windows):
        rects.append((*_span(window, size), window["y"], window["y"] + window["h"], window["wall"]))
    for index, rect in enumerate(rects):
        for other in rects[index + 1:]:
            if rect[4] == other[4] and rect[0] < other[1] and other[0] < rect[1] and rect[2] < other[3] and other[2] < rect[3]:
                raise ValueError("door and windows overlap")


def _span(opening: dict, size: dict) -> tuple[float, float]:
    centre = _length(size, opening["wall"]) / 2 + opening["x"]
    return centre - opening["w"] / 2, centre + opening["w"] / 2


def _fits(opening: dict, size: dict, what: str) -> None:
    start, end = _span(opening, size)
    if start < 0.02 or end > _length(size, opening["wall"]) - 0.02:
        raise ValueError(f"{what} does not fit on the {opening['wall']} wall")


def _length(size: dict, wall: str) -> float:
    return size["w"] if wall == "back" else size["d"]


def _wall(value, what: str) -> str:
    if value in ("front", "open"):
        raise ValueError(f"{what}: the open side has no wall")
    if value not in WALLS:
        raise ValueError(f"{what} is back, left or right")
    return value


def _own_tile(value) -> None:
    """A stored room repeats ``tile`` from the shared camera file. A missing tile means that same default."""
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != TILE:
        raise ValueError(f"tile is {TILE:g}")


def _seed(value):
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 2**31 - 1:
        raise ValueError("seed is an integer from 0")
    return value


def _text(value, what: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 2000:
        raise ValueError(f"{what} is required text")


def _measure(value, low, high, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= float(value) <= high:
        raise ValueError(f"{what} is metres ({low:g}-{high:g})")
    return round(float(value), 4)


def _parts(spec: dict, textures: dict) -> list[dict]:
    size = spec["size"]
    parts = [_part("floor", _floor(size), _picture(textures.get("floor"), _TONES["floor"]), repeat=True),
             _part("walls", _walls(spec), _picture(textures.get("walls"), _TONES["walls"]), repeat=True),
             _part("door", _door_slab(spec), _picture(textures.get("door"), _TONES["door"]), repeat=False)]
    if spec.get("ceiling"):
        parts.append(_part("ceiling", _ceiling_quad(size), _picture(textures.get("ceiling"), _TONES["ceiling"]), repeat=True))
    pictures = list(textures.get("props") or [])
    for index, prop in enumerate(spec["props"]):
        parts.append(_part(f"prop-{index + 1}", _prop_quad(spec, prop),
                           _picture(pictures[index] if index < len(pictures) else None, _TONES["prop"], alpha=255), repeat=False, alpha=True))
    return parts


def _part(name, quads, png, *, repeat: bool, alpha: bool = False) -> dict:
    return {"name": name, "arrays": _arrays(quads), "png": png, "repeat": repeat, "alpha": alpha}


def _picture(source, tone, alpha=None) -> bytes:
    if source:
        with Image.open(source) as picture:
            image = picture.convert("RGBA" if alpha is not None else "RGB")
    else:
        image = Image.new("RGBA" if alpha is not None else "RGB", (64, 64), (*tone, 255 if alpha is None else alpha))
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def _floor(size: dict) -> list:
    width, depth, tile = size["w"], size["d"], TILE
    x, z = width / 2, depth / 2
    u, v = width / tile, depth / tile
    return [_quad([(-x, 0, z), (x, 0, z), (x, 0, -z), (-x, 0, -z)], [(0, v), (u, v), (u, 0), (0, 0)])]


def _ceiling_quad(size: dict) -> list:
    """Inward normal is -y: counter-clockwise as seen from inside the room looking up."""
    width, depth, height, tile = size["w"], size["d"], size["h"], TILE
    x, z = width / 2, depth / 2
    u, v = width / tile, depth / tile
    return [_quad([(-x, height, -z), (x, height, -z), (x, height, z), (-x, height, z)], [(0, 0), (u, 0), (u, v), (0, v)])]


def _walls(spec: dict) -> list:
    quads = []
    for wall in WALLS:
        quads.extend(_wall_quads(spec, wall))
    return quads


def _wall_quads(spec: dict, wall: str) -> list:
    size = spec["size"]
    length = _length(size, wall)
    quads = []
    for along0, along1, up0, up1 in _cells(length, size["h"], _holes(spec, wall)):
        quads.append(_quad(_corners(wall, size, along0, along1, up0, up1), _uv(along0, along1, up0, up1)))
    return quads


def _holes(spec: dict, wall: str) -> list:
    holes = []
    if spec["door"]["wall"] == wall:
        holes.append(_span_rect(spec["door"], spec["size"], 0.0))
    for window in spec["windows"]:
        if window["wall"] == wall:
            holes.append(_span_rect(window, spec["size"], window["y"]))
    return holes


def _span_rect(opening: dict, size: dict, bottom: float) -> tuple:
    start, end = _span(opening, size)
    return (start, end, bottom, bottom + opening["h"])


def _cells(length: float, height: float, holes: list) -> list:
    cuts_x, cuts_y = {0.0, length}, {0.0, height}
    for start, end, bottom, top in holes:
        cuts_x.update((start, end))
        cuts_y.update((bottom, top))
    xs = sorted(value for value in cuts_x if 0 <= value <= length + 1e-6)
    ys = sorted(value for value in cuts_y if 0 <= value <= height + 1e-6)
    cells = []
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            if x1 - x0 < 1e-4 or y1 - y0 < 1e-4:
                continue
            if any(a0 - 1e-6 <= (x0 + x1) / 2 <= a1 + 1e-6 and b0 - 1e-6 <= (y0 + y1) / 2 <= b1 + 1e-6 for a0, a1, b0, b1 in holes):
                continue
            cells.append((x0, x1, y0, y1))
    return cells


def _corners(wall: str, size: dict, a0: float, a1: float, y0: float, y1: float):
    """Counter-clockwise from inside the room. Back looks toward -z, left toward +x, right toward -x."""
    if wall == "back":
        z, x0, x1 = size["d"] / 2, -size["w"] / 2 + a0, -size["w"] / 2 + a1
        return [(x1, y0, z), (x0, y0, z), (x0, y1, z), (x1, y1, z)]
    z0, z1 = -size["d"] / 2 + a0, -size["d"] / 2 + a1
    x = -size["w"] / 2 if wall == "left" else size["w"] / 2
    if wall == "left":
        return [(x, y0, z1), (x, y0, z0), (x, y1, z0), (x, y1, z1)]
    return [(x, y0, z0), (x, y0, z1), (x, y1, z1), (x, y1, z0)]


def _uv(a0, a1, y0, y1):
    tile = TILE
    return [(a1 / tile, y0 / tile), (a0 / tile, y0 / tile), (a0 / tile, y1 / tile), (a1 / tile, y1 / tile)]


def _door_slab(spec: dict) -> list:
    """A visible slab of the door's real height, 2 cm inside the hole, so the frame has a door to measure."""
    door, size = spec["door"], spec["size"]
    corners = _corners(door["wall"], _inset_size(size, door["wall"]), *_door_cell(door, size))
    return [_quad(corners, [(0, 0), (1, 0), (1, 1), (0, 1)])]


def _door_cell(door: dict, size: dict) -> tuple:
    start, end = _span(door, size)
    return start, end, 0.0, door["h"]


def _inset_size(size: dict, wall: str) -> dict:
    """Shrink the wall plane 2 cm into the room so the slab does not fight the wall."""
    shrunk = dict(size)
    if wall == "back":
        shrunk["d"] = size["d"] - 0.04
    else:
        shrunk["w"] = size["w"] - 0.04
    return shrunk


def _prop_quad(spec: dict, prop: dict) -> list:
    width = max(0.15, prop["height_m"] * 0.62)
    x, _y, z = prop_point(spec["size"], prop)
    half = width / 2
    if prop["on"] == "floor" or prop.get("wall") == "back":
        corners = [(x + half, 0, z), (x - half, 0, z), (x - half, prop["height_m"], z), (x + half, prop["height_m"], z)]
    elif prop["wall"] == "left":
        corners = [(x, 0, z - half), (x, 0, z + half), (x, prop["height_m"], z + half), (x, prop["height_m"], z - half)]
    else:
        corners = [(x, 0, z + half), (x, 0, z - half), (x, prop["height_m"], z - half), (x, prop["height_m"], z + half)]
    return [_quad(corners, [(0, 0), (1, 0), (1, 1), (0, 1)])]


def _write(target: str | Path, parts: list[dict]) -> None:
    import pygltflib

    blob = bytearray()
    gltf = pygltflib.GLTF2(asset=pygltflib.Asset(version="2.0", generator="hocuspocus room_box"),
                           scenes=[pygltflib.Scene(nodes=[0])], scene=0)

    def view(data: bytes, kind: int | None = None) -> int:
        while len(blob) % 4:
            blob.append(0)
        gltf.bufferViews.append(pygltflib.BufferView(buffer=0, byteOffset=len(blob), byteLength=len(data), target=kind))
        blob.extend(data)
        return len(gltf.bufferViews) - 1

    def accessor(array: np.ndarray, shape: str, component: int, kind: int) -> int:
        bounds = {"max": array.max(axis=0).tolist(), "min": array.min(axis=0).tolist()} if shape == "VEC3" else {}
        gltf.accessors.append(pygltflib.Accessor(bufferView=view(array.tobytes(), kind), componentType=component,
                                                 count=len(array), type=shape, **bounds))
        return len(gltf.accessors) - 1

    repeat = pygltflib.Sampler(magFilter=pygltflib.LINEAR, minFilter=pygltflib.LINEAR_MIPMAP_LINEAR,
                                wrapS=pygltflib.REPEAT, wrapT=pygltflib.REPEAT)
    clamp = pygltflib.Sampler(magFilter=pygltflib.LINEAR, minFilter=pygltflib.LINEAR_MIPMAP_LINEAR,
                               wrapS=pygltflib.CLAMP_TO_EDGE, wrapT=pygltflib.CLAMP_TO_EDGE)
    gltf.samplers.extend((repeat, clamp))
    primitives = []
    for part in parts:
        positions, normals, uvs, indices = part["arrays"]
        image = len(gltf.images)
        gltf.images.append(pygltflib.Image(bufferView=view(part["png"]), mimeType="image/png", name=part["name"]))
        gltf.textures.append(pygltflib.Texture(source=image, sampler=0 if part["repeat"] else 1))
        material = pygltflib.Material(
            name=part["name"], doubleSided=True,
            alphaMode=pygltflib.BLEND if part["alpha"] else pygltflib.OPAQUE,
            pbrMetallicRoughness=pygltflib.PbrMetallicRoughness(
                baseColorTexture=pygltflib.TextureInfo(index=len(gltf.textures) - 1),
                baseColorFactor=[1, 1, 1, 1], metallicFactor=0.0, roughnessFactor=0.9))
        gltf.materials.append(material)
        attributes = pygltflib.Attributes(
            POSITION=accessor(positions, "VEC3", pygltflib.FLOAT, pygltflib.ARRAY_BUFFER),
            NORMAL=accessor(normals, "VEC3", pygltflib.FLOAT, pygltflib.ARRAY_BUFFER),
            TEXCOORD_0=accessor(uvs, "VEC2", pygltflib.FLOAT, pygltflib.ARRAY_BUFFER))
        primitives.append(pygltflib.Primitive(attributes=attributes, indices=accessor(indices, "SCALAR", pygltflib.UNSIGNED_SHORT, pygltflib.ELEMENT_ARRAY_BUFFER),
                                              material=len(gltf.materials) - 1))
    gltf.meshes.append(pygltflib.Mesh(name="room", primitives=primitives))
    gltf.nodes.append(pygltflib.Node(name="room", mesh=0))
    gltf.buffers.append(pygltflib.Buffer(byteLength=len(blob)))
    gltf.set_binary_blob(bytes(blob))
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    gltf.save_binary(str(target))


def image_count(entry) -> int:
    """Pictures a box room draws: floor, walls, an optional ceiling and each prop. Door and windows are holes."""
    try:
        spec = normalize(entry)
    except (TypeError, ValueError):
        return 0
    return 2 + int(bool(spec.get("ceiling"))) + len(spec["props"])


def valid_name(name) -> bool:
    return isinstance(name, str) and bool(_NAME.match(name))
