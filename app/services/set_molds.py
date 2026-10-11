"""Interior molds in metres. Authored coordinates use the medium size and scale per axis."""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1] / "shared"
MOLDS = SHARED / "set_molds"
WALLS = {"back", "front", "left", "right"}
CAMERAS = ("two_shot", "ots_a", "ots_b", "wide", "close_1", "close_2", "entrance")


def defaults() -> dict:
    """Read on every request so measured defaults do not require code changes."""
    return json.loads((SHARED / "set_defaults.json").read_text(encoding="utf-8"))


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _vector(value, count=3) -> bool:
    return isinstance(value, list) and len(value) == count and all(_number(n) for n in value)


def _inside(point, dimensions) -> bool:
    w, d, h = dimensions
    return _vector(point) and -w / 2 <= point[0] <= w / 2 and 0 <= point[1] <= h and -d / 2 <= point[2] <= d / 2


def _entries(mold, key) -> list:
    entries = mold.get(key, [])
    if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
        raise ValueError(f"{key}: expected objects")
    ids = [row.get("id") for row in entries]
    if any(not isinstance(id_, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", id_) for id_ in ids) or len(set(ids)) != len(ids):
        raise ValueError(f"{key}: unique identifiers required")
    return entries


def _openings(mold, dims):
    for opening in mold.get("openings", []):
        wall = opening.get("wall")
        span = dims[0] if wall in {"front", "back"} else dims[1]
        x, width, height, sill = (opening.get(k, 0) for k in ("x", "width", "height", "sill"))
        if wall not in mold["walls"] or opening.get("kind") not in {"door", "window"}:
            raise ValueError("opening: unknown wall or kind")
        if not all(_number(v) for v in (x, width, height, sill)) or not (0 < width <= span and 0 < height and 0 <= sill and sill + height <= dims[2]):
            raise ValueError("opening outside wall")
        if not width / 2 <= x * span <= span - width / 2:
            raise ValueError("opening outside wall")
        if opening.get("surface", "window_view" if opening["kind"] == "window" else "door") not in mold["surfaces"]:
            raise ValueError("opening: unknown surface")


def _blocks(mold, dims):
    for block in _entries(mold, "blocks"):
        box = block.get("box")
        if not _vector(box, 6) or not all(n > 0 for n in box[3:]):
            raise ValueError("block: invalid box")
        x, y, z, w, h, d = box
        if not all(_inside(point, dims) for point in ([x-w/2, y, z-d/2], [x+w/2, y+h, z+d/2])):
            raise ValueError("block outside room")
        if not set(block.get("surfaces", [])) <= set(mold["surfaces"]):
            raise ValueError("block: unknown surface")


def validate_mold(mold: dict) -> dict:
    """Reject impossible geometry before compilation or generation."""
    if not isinstance(mold, dict) or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", str(mold.get("id", ""))):
        raise ValueError("invalid mold id")
    if mold.get("kind") != "interior" or set(mold.get("sizes", {})) != {"small", "medium", "large"}:
        raise ValueError("interior requires small, medium and large sizes")
    for dims in mold["sizes"].values():
        if not _vector(dims) or not all(0.5 <= n <= 30 for n in dims):
            raise ValueError("room dimensions must be between 0.5 and 30 metres")
    surfaces = mold.get("surfaces", [])
    if not surfaces or len(set(surfaces)) != len(surfaces) or not all(isinstance(s, str) for s in surfaces):
        raise ValueError("unique surfaces required")
    if not set(mold.get("walls", [])) <= WALLS or not {f"wall_{w}" for w in mold["walls"]} <= set(surfaces):
        raise ValueError("unknown wall surface")
    if not set(mold.get("defaultSkin", {})) <= set(surfaces):
        raise ValueError("defaultSkin: unknown surface")
    dims = mold["sizes"]["medium"]
    for key in ("marks", "propAnchors", "cameras"):
        for entry in _entries(mold, key):
            if not _inside(entry.get("position"), dims):
                raise ValueError(f"{key}: {entry['id']} outside room")
            if key == "propAnchors" and (entry.get("on") not in surfaces or not _number(entry.get("maxHeight")) or entry["maxHeight"] <= 0):
                raise ValueError("anchor: unknown surface or invalid height")
            if key == "cameras" and (not _inside(entry.get("lookAt"), dims) or not _number(entry.get("fov")) or not 1 <= entry["fov"] <= 120):
                raise ValueError("camera: invalid target or fov")
    _openings(mold, dims)
    _blocks(mold, dims)
    return mold


def load_mold(id_: str) -> dict:
    if not isinstance(id_, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", id_):
        raise ValueError("invalid mold id")
    try:
        return validate_mold(json.loads((MOLDS / f"{id_}.json").read_text(encoding="utf-8")))
    except FileNotFoundError as error:
        raise ValueError(f"unknown mold: {id_}") from error


def resolve_mold(id_: str, size: str = "medium") -> dict:
    mold = copy.deepcopy(load_mold(id_))
    if size not in mold["sizes"]:
        raise ValueError(f"unknown size: {size}")
    w, d, h = mold["sizes"][size]
    bw, bd, bh = mold["sizes"]["medium"]
    scale = (w/bw, h/bh, d/bd)
    def point(values):
        return [round(v * factor, 6) for v, factor in zip(values, scale)]
    for key in ("marks", "propAnchors", "cameras"):
        for entry in mold.get(key, []):
            entry["position"] = point(entry["position"])
            if "lookAt" in entry:
                entry["lookAt"] = point(entry["lookAt"])
            if "maxHeight" in entry:
                entry["maxHeight"] *= scale[1]
    for block in mold.get("blocks", []):
        block["box"] = point(block["box"][:3]) + point(block["box"][3:])
    for opening in mold.get("openings", []):
        opening["width"] *= scale[0] if opening["wall"] in {"back", "front"} else scale[2]
        for field in ("height", "sill"):
            if field in opening:
                opening[field] *= scale[1]
    return {**mold, "size": size, "dimensions": [w, d, h]}


def catalog() -> list[dict]:
    return [load_mold(path.stem) for path in sorted(MOLDS.glob("*.json"))]


def surface_sizes(mold: dict) -> dict[str, list[float]]:
    w, d, h = mold["dimensions"]
    result = {"floor": [w, d], "ceiling": [w, d], "wall_back": [w, h], "wall_front": [w, h], "wall_left": [d, h], "wall_right": [d, h]}
    for opening in mold["openings"]:
        result[opening.get("surface", "window_view" if opening["kind"] == "window" else "door")] = [opening["width"], opening["height"]]
    for block in mold["blocks"]:
        for name in block["surfaces"]:
            result[name] = [block["box"][3], block["box"][5] if name.endswith("_top") else block["box"][4]]
    return {name: result[name] for name in mold["surfaces"]}
