"""Rest-pose boxes of the parts of a GLB: one world-space box per mesh node, read from its JSON chunk alone.

``glb_bounds`` merges every mesh of a model into one box, which is the right answer for "how big is it" and a useless one
for "does something pass through it": a village is one 42 x 17 x 60 m box with streets inside. A *part* is a mesh node of
the default scene (a house, a tower, the ground slab); its box is the union of its primitives' POSITION accessor boxes
under the node's world transform, in the glTF's own units, y up. Same rules and limits as ``glb_bounds`` (header and JSON
chunk only, rest pose, ``min``/``max`` required), and the same promise: ``glb_parts`` never raises.

A model with more than ``MAX_PARTS`` mesh nodes keeps the largest ``MAX_PARTS`` by volume and says how many it left out.
A part's ``index`` is its position among the mesh nodes in traversal order (parents before children, the order of the
default scene), so it stays the same whatever was left out and names the part in a collision warning.
"""
from __future__ import annotations

import math
from itertools import product
from pathlib import Path

from services.procedural_3d.glb_bounds import MAX_JSON_BYTES, _apply, _mesh_nodes, _primitive_boxes, _read_document, _Refused

MAX_PARTS = 200
_DIGITS = 5


def glb_parts(path, *, max_parts: int = MAX_PARTS, max_json_bytes: int = MAX_JSON_BYTES) -> dict:
    """``{ok, parts: [{index, node, name, min, max}], omitted, reason}``; ``ok: False`` and a ``reason`` (as ``glb_bounds``) otherwise."""
    try:
        parts = _parts(_read_document(Path(path), max_json_bytes))
    except _Refused as refusal:
        return _refused(str(refusal))
    except FileNotFoundError:
        return _refused("missing_file")
    except Exception:  # noqa: BLE001 - the contract is that a bad file never raises
        return _refused("unreadable")
    if not parts:
        return _refused("no_meshes")
    kept = sorted(sorted(parts, key=lambda part: -_volume(part))[:max_parts], key=lambda part: part["index"])
    return {"ok": True, "parts": kept, "omitted": len(parts) - len(kept), "reason": None}


def _refused(reason: str) -> dict:
    return {"ok": False, "parts": [], "omitted": 0, "reason": reason}


def _volume(part: dict) -> float:
    return math.prod(part["max"][axis] - part["min"][axis] for axis in range(3))


def _parts(document: dict) -> list[dict]:
    parts = []
    for index, (node_index, node, world, mesh) in enumerate(_mesh_nodes(document)):
        box = _node_box(document, world, mesh)
        if box is not None:
            name = node.get("name") if isinstance(node.get("name"), str) else None
            parts.append({"index": index, "node": node_index, "name": name[:80] if name else None, "min": box[0], "max": box[1]})
    return parts


def _node_box(document: dict, world, mesh) -> tuple[list[float], list[float]] | None:
    low, high = [math.inf] * 3, [-math.inf] * 3
    for box_low, box_high in _primitive_boxes(document, mesh):
        for corner in product(*zip(box_low, box_high)):
            point = _apply(world, corner)
            low = [min(a, b) for a, b in zip(low, point)]
            high = [max(a, b) for a, b in zip(high, point)]
    if low[0] == math.inf or not all(math.isfinite(value) for value in (*low, *high)):
        return None
    return [round(value, _DIGITS) for value in low], [round(value, _DIGITS) for value in high]
