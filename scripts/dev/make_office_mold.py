"""Writes app/shared/set_molds/despacho.json: an office / consulting room (a bookcase wall with painted books, a desk with a leather inlay and drawers, a chair
behind it, an armchair and a side table with a lamp for the visitor, a framed window with curtains, a framed door, a rug, a plant, diplomas, skirting).

The mold is data, this is how it is authored: ``python scripts/dev/make_office_mold.py``. Medium size, metres: x = width, z = depth (the bookcase is on the
back wall, -z), y = height. The old mold's block ids (``desk``, ``shelf``), surfaces, marks and seven cameras are kept, so earlier skins, scenes and cards keep
working. The default skin is painted by the room itself (``pattern``, the ``books`` face, a daytime ``view``): nothing here needs a picture.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "app" / "shared" / "set_molds" / "despacho.json"
W, D, H = 6.0, 5.0, 3.0
TRIM = ("trim_front", "trim_top")
LEATHER = ("chair_front", "chair_top")
WOOD = ("desk_front", "desk_top")

blocks: list[dict] = []


def block(id_: str, kind: str, surfaces: tuple[str, str], x: float, y: float, z: float, w: float, h: float, d: float, rot=None) -> None:
    entry = {"id": id_, "kind": kind, "box": [round(x, 3), round(y, 3), round(z, 3), round(w, 3), round(h, 3), round(d, 3)], "surfaces": list(surfaces)}
    if rot and any(abs(a) > 1e-9 for a in rot):
        entry["rot"] = [round(a, 4) for a in rot]
    blocks.append(entry)


# --- the bookcase on the back wall: a carcass (id `shelf`), a face of painted books, a cornice -------------------------------------
block("shelf", "shelf", ("shelf_front", "shelf_top"), 0.0, 0.0, -2.31, 3.0, 2.2, 0.34)
block("shelf_books", "shelf", ("books_front", "books_top"), 0.0, 0.12, -2.135, 2.76, 1.96, 0.01)
block("shelf_cornice", "shelf", ("shelf_front", "shelf_top"), 0.0, 2.2, -2.3, 3.1, 0.1, 0.38)

# --- the desk (id `desk`: the body, its top is 0.75 m), a leather inlay, drawer fronts, knobs ------------------------------------
block("desk", "desk", WOOD, 0.0, 0.0, -0.8, 1.8, 0.75, 0.8)
block("desk_inlay", "desk", ("inlay_front", "inlay_top"), 0.0, 0.75, -0.8, 1.56, 0.012, 0.6)
for name, x in (("a", -0.55), ("b", 0.55)):
    block(f"desk_drawer_{name}", "desk", ("desk_front", "desk_top"), x, 0.1, -0.395, 0.58, 0.5, 0.02)
    block(f"desk_knob_{name}", "trim", TRIM, x, 0.33, -0.375, 0.07, 0.04, 0.02)
block("desk_plinth", "desk", TRIM, 0.0, 0.0, -0.395, 1.74, 0.07, 0.02)

# --- the chair behind the desk (the `behind_desk` mark sits on it), an armchair and a side table with a lamp for the visitor -------
block("chair_seat", "chair", LEATHER, 0.0, 0.0, -1.5, 0.54, 0.45, 0.52)
block("chair_back", "chair", LEATHER, 0.0, 0.45, -1.78, 0.54, 0.58, 0.08, (0.1, 0, 0))
block("armchair", "chair", LEATHER, -1.9, 0.0, 0.3, 0.8, 0.42, 0.8)
block("armchair_back", "chair", LEATHER, -2.3, 0.42, 0.3, 0.12, 0.5, 0.8, (0, 0, 0.12))
for name, dz in (("a", -0.36), ("b", 0.36)):
    block(f"armchair_arm_{name}", "chair", LEATHER, -1.9, 0.42, 0.3 + dz, 0.8, 0.14, 0.1)
block("side_table", "desk", WOOD, -1.9, 0.0, 1.35, 0.45, 0.55, 0.45)
block("side_lamp_base", "lamp", TRIM, -1.9, 0.55, 1.35, 0.1, 0.18, 0.1)
block("side_lamp_shade", "lamp", ("lamp_front", "lamp_top"), -1.9, 0.71, 1.35, 0.28, 0.22, 0.28)

# --- the window (left wall, z -0.8 .. 0.8, y 0.9 .. 2.3): frame, mullion, sill, curtains with their rod; the door (right wall, z 0.55 .. 1.45) -----
block("window_sill", "trim", TRIM, -2.9, 0.86, 0.0, 0.2, 0.04, 1.9)
block("window_frame_top", "trim", TRIM, -2.97, 2.3, 0.0, 0.06, 0.05, 1.8)
for name, dz in (("a", -0.85), ("b", 0.85)):
    block(f"window_frame_{name}", "trim", TRIM, -2.97, 0.9, dz, 0.06, 1.4, 0.05)
block("window_mullion", "trim", TRIM, -2.975, 0.9, 0.0, 0.03, 1.4, 0.04)
block("curtain_rod", "trim", TRIM, -2.9, 2.55, 0.0, 0.05, 0.04, 2.6)
for name, dz in (("a", -1.15), ("b", 1.15)):
    block(f"curtain_{name}", "curtain", ("curtain_front", "curtain_top"), -2.9, 0.1, dz, 0.12, 2.5, 0.46)
block("door_frame_a", "trim", TRIM, 2.97, 0.0, 0.5, 0.06, 2.15, 0.1)
block("door_frame_b", "trim", TRIM, 2.97, 0.0, 1.5, 0.06, 2.15, 0.1)
block("door_frame_top", "trim", TRIM, 2.97, 2.1, 1.0, 0.06, 0.08, 1.1)
block("door_handle", "trim", TRIM, 2.94, 1.0, 0.65, 0.05, 0.04, 0.14)

# --- the rest of the room: rug, plant, diplomas, skirting, ceiling lamp ----------------------------------------------------------
block("rug", "rug", ("rug_front", "rug_top"), 0.2, 0.0, 0.3, 3.2, 0.012, 2.4)
block("plant_pot", "trim", ("plant_front", "plant_top"), 2.45, 0.0, -2.0, 0.34, 0.34, 0.34)
block("plant_leaves", "plant", ("leaf_front", "leaf_top"), 2.45, 0.34, -2.0, 0.55, 0.95, 0.55)
for name, dz in (("a", -1.9), ("b", -1.3), ("c", -0.7)):
    block(f"diploma_{name}", "art", ("art_front", "art_top"), -2.975, 1.5, dz, 0.03, 0.5, 0.38)
block("skirting_left", "trim", TRIM, -2.985, 0.0, 0.0, 0.03, 0.12, 4.9)
block("skirting_right_a", "trim", TRIM, 2.985, 0.0, -1.0, 0.03, 0.12, 3.0)
block("skirting_right_b", "trim", TRIM, 2.985, 0.0, 2.0, 0.03, 0.12, 1.0)
block("skirting_front", "trim", TRIM, 0.0, 0.0, 2.485, 5.9, 0.12, 0.03)
block("ceiling_lamp", "lamp", ("lamp_front", "lamp_top"), 0.0, 2.9, 0.0, 0.46, 0.1, 0.46)

SURFACES = ["floor", "ceiling", "wall_back", "wall_left", "wall_right", "wall_front", "window_view", "door", "desk_front", "desk_top", "shelf_front", "shelf_top",
            "books_front", "books_top", "inlay_front", "inlay_top", "chair_front", "chair_top", "trim_front", "trim_top", "curtain_front", "curtain_top",
            "rug_front", "rug_top", "lamp_front", "lamp_top", "plant_front", "plant_top", "leaf_front", "leaf_top", "art_front", "art_top"]

SKIN = {
    "floor": {"pattern": "wood", "color": "#8a6a46"}, "ceiling": {"pattern": "plaster", "color": "#ece6da"},
    "wall_back": {"pattern": "plaster", "color": "#a9b3a0"}, "wall_left": {"pattern": "plaster", "color": "#a9b3a0"},
    "wall_right": {"pattern": "plaster", "color": "#a9b3a0"}, "wall_front": {"pattern": "plaster", "color": "#a9b3a0"},
    "window_view": {"view": "day_window"}, "door": {"pattern": "wood", "color": "#6e4d33"},
    "desk_front": {"pattern": "wood", "color": "#71513a"}, "desk_top": {"pattern": "wood", "color": "#7a5a40"},
    "shelf_front": {"pattern": "wood", "color": "#523f32"}, "shelf_top": {"pattern": "wood", "color": "#523f32"},
    "books_front": {"pattern": "books", "color": "#ffffff"}, "books_top": {"color": "#2a2018"},
    "inlay_front": {"pattern": "leather", "color": "#2f4a3a"}, "inlay_top": {"pattern": "leather", "color": "#2f4a3a"},
    "chair_front": {"pattern": "leather", "color": "#4a2f22"}, "chair_top": {"pattern": "leather", "color": "#55392a"},
    "trim_front": {"pattern": "plastic", "color": "#e6dfd1"}, "trim_top": {"pattern": "plastic", "color": "#eee8da"},
    "curtain_front": {"pattern": "fabric", "color": "#7a4a2a"}, "curtain_top": {"pattern": "fabric", "color": "#7a4a2a"},
    "rug_front": {"pattern": "carpet", "color": "#6a3f36"}, "rug_top": {"pattern": "carpet", "color": "#6a3f36"},
    "lamp_front": {"color": "#fff1cf"}, "lamp_top": {"color": "#fff6dc"},
    "plant_front": {"color": "#a0562f"}, "plant_top": {"color": "#3b2a1e"}, "leaf_front": {"color": "#3f7a3e"}, "leaf_top": {"color": "#4c8c48"},
    "art_front": {"color": "#e8e1cf"}, "art_top": {"color": "#d9d0b8"},
}

mold = {
    "id": "despacho",
    "title": {"es": "Despacho", "en": "Office"},
    "kind": "interior",
    "sizes": {"small": [4, 4, 2.8], "medium": [W, D, H], "large": [9, 7, 3.4]},
    "walls": ["back", "left", "right", "front"],
    "openings": [{"wall": "left", "kind": "window", "x": 0.5, "width": 1.6, "height": 1.4, "sill": 0.9},
                 {"wall": "right", "kind": "door", "x": 0.7, "width": 0.9, "height": 2.1}],
    "blocks": blocks,
    "surfaces": SURFACES,
    "marks": [
        {"id": "behind_desk", "pose": "sit", "position": [0, 0, -1.5], "facing": 0},
        {"id": "visitor", "pose": "stand", "position": [0.4, 0, 0.6], "facing": 180},
        {"id": "door", "pose": "stand", "position": [2.6, 0, 0.8], "facing": -90},
    ],
    "cameras": [
        {"id": "two_shot", "position": [2.4, 1.7, 2.2], "lookAt": [0, 1, -0.5], "fov": 55},
        {"id": "ots_a", "position": [-0.6, 1.6, -1.9], "lookAt": [0.4, 1.1, 0.6], "fov": 45},
        {"id": "ots_b", "position": [0.9, 1.6, 1.2], "lookAt": [0, 1, -1.5], "fov": 45},
        {"id": "wide", "position": [0, 2.3, 2.3], "lookAt": [0, 1, -0.6], "fov": 70},
        {"id": "close_1", "position": [0, 1.5, 0.2], "lookAt": [0, 1.1, -1.5], "fov": 40},
        {"id": "close_2", "position": [0.4, 1.5, -1], "lookAt": [0.4, 1.2, 0.6], "fov": 40},
        {"id": "entrance", "position": [-2, 1.7, 1.8], "lookAt": [2.6, 1, 0.8], "fov": 60},
    ],
    "lights": "office_day",
    "propAnchors": [
        {"id": "desk_left", "on": "desk_top", "position": [-0.6, 0.76, -0.8], "maxHeight": 0.5},
        {"id": "desk_right", "on": "desk_top", "position": [0.6, 0.76, -0.8], "maxHeight": 0.5},
        {"id": "corner", "on": "floor", "position": [-2.6, 0, -2.1], "maxHeight": 2},
        {"id": "wall_picture", "on": "wall_back", "position": [2.2, 1.3, -2.48], "maxHeight": 0.9},
    ],
    "defaultSkin": SKIN,
}

if __name__ == "__main__":
    OUT.write_text(json.dumps(mold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT.name, len(blocks), "blocks")
