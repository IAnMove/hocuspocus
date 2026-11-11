"""The furniture of a stage's room (``room.mold.blocks``: a bed, a sofa, desks, benches), as things ``rest`` and ``beside``
can name.

A stage card (``stage-dormitorio``…) draws its furniture as boxes of the set, not as objects: ``box`` is ``[x, y, z,
width, height, depth]`` in scene metres (``roomSet.ts``: centred on x and z, standing on y, front toward +z). A block that
a library model replaced (``room.libraryBlocks``) is an object of the scene and is left out. A box's top is where a
person sits on a bed, a stool, a low bench or a desk; a box drawn for a chair, an armchair or a sofa is as tall as its
back, so its seat is taken at ``SEAT_SHARE`` of its height and the seat finder says it guessed.
"""
from __future__ import annotations

import numpy as np

from services.world3d_mesh_solid import Mesh
from services.world3d_slot_frame import SlotFrame

SEAT_SHARE = {"chair": 0.52, "armchair": 0.52, "sofa": 0.55}
_TALL_BENCH = 0.6           # a bench box taller than this has a back drawn into it


def room_blocks(document: dict) -> dict[str, dict]:
    """Block id -> block, for the blocks the room still draws itself."""
    room = document.get("room") if isinstance(document.get("room"), dict) else {}
    mold = room.get("mold") if isinstance(room.get("mold"), dict) else {}
    replaced = set(room.get("libraryBlocks") or []) if isinstance(room.get("libraryBlocks"), list) else set()
    found = {}
    for block in mold.get("blocks") or []:
        box = block.get("box") if isinstance(block, dict) else None
        if isinstance(block.get("id"), str) and block["id"] not in replaced and isinstance(box, list) and len(box) == 6 \
                and all(type(value) in (int, float) for value in box) and min(box[3:]) > 0:
            found[block["id"]] = block
    return found


def block_slot(block: dict) -> dict:
    """A stand-in slot for a block: where it is, as the scene draws it (no turn, no scale)."""
    return {"id": block["id"], "media": "model3d", "position": [0.0, 0.0, 0.0], "rotationY": 0.0, "scale": 1.0, "roomBlock": True,
            "kind": block.get("kind")}


def block_box(block: dict) -> dict:
    x, y, z, width, height, depth = (float(value) for value in block["box"])
    low, high = [x - width / 2, y, z - depth / 2], [x + width / 2, y + height, z + depth / 2]
    return {"ok": True, "min": low, "max": high, "size": [width, height, depth], "center": [x, y + height / 2, z], "bottomY": y}


def block_parts(block: dict) -> list[dict]:
    box = block_box(block)
    return [{"index": 0, "node": 0, "name": block["id"], "min": box["min"], "max": box["max"]}]


def block_mesh(block: dict) -> Mesh:
    from services.procedural_3d.furniture import _box
    box = block_box(block)
    vertices, _normals = _box(box["min"], box["max"])
    triangles = np.asarray(vertices, dtype=np.float64).reshape(-1, 3, 3)
    return Mesh(triangles, np.zeros(len(triangles), dtype=np.int32), [block["id"]], np.asarray(box["min"]), np.asarray(box["max"]))


def block_frame() -> SlotFrame:
    return SlotFrame(1.0, np.eye(3), np.zeros(3))


def block_seat(block: dict):
    """The seat of a block drawn as tall as its back (a chair, a sofa, a high bench), or None to read its top."""
    from services.world3d_seats import Surface
    kind = str(block.get("kind") or "")
    box = block_box(block)
    share = SEAT_SHARE.get(kind) or (0.55 if kind == "bench" and box["size"][1] > _TALL_BENCH else None)
    if share is None:
        return None
    return Surface(box["min"][1] + share * box["size"][1], [box["min"][0], box["min"][2]], [box["max"][0], box["max"][2]], "block",
                   guessed=True, name=block["id"], front=[0.0, 1.0])
