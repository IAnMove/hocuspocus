"""Writes app/shared/set_molds/dormitorio.json: a bedroom that reads as one (bed with headboard, pillows and a duvet, two bedside tables with lamps,
a wardrobe that faces the room, a window with a frame, a sill and curtains, a door with its frame, a rug, a picture, skirting, a ceiling lamp).

The mold is data, this is how it is authored: ``python scripts/dev/make_bedroom_mold.py``. Medium size, metres: x = width, z = depth (the headboard is on
the back wall, -z), y = height. The block ids ``bed`` / ``nightstand`` / ``wardrobe``, the skin surfaces they had, the marks and the seven cameras are the
old mold's, so earlier skins, scenes and cards keep working. ``bed`` is the mattress, its top is 0.55 m; the duvet (top 0.70) and the pillows are soft
blocks: a figure lying on or in them is not a collision. The default skin is painted by the room itself (``pattern``), the window shows a daytime view
that moves a little (``view``): nothing here needs a picture.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "app" / "shared" / "set_molds" / "dormitorio.json"
W, D, H = 6.0, 6.0, 3.0
HALF = math.pi / 2
WOOD = ("nightstand_front", "nightstand_top")
TRIM = ("trim_front", "trim_top")

blocks: list[dict] = []


def block(id_: str, kind: str, surfaces: tuple[str, str], x: float, y: float, z: float, w: float, h: float, d: float, rot=None) -> None:
    entry = {"id": id_, "kind": kind, "box": [round(x, 3), round(y, 3), round(z, 3), round(w, 3), round(h, 3), round(d, 3)], "surfaces": list(surfaces)}
    if rot and any(abs(a) > 1e-9 for a in rot):
        entry["rot"] = [round(a, 4) for a in rot]
    blocks.append(entry)


# --- the bed: frame, mattress (id `bed`, top 0.55), headboard, two pillows, a duvet with its turned-down sheet --------------------
block("bed_frame", "bed", ("headboard_front", "headboard_top"), 0.0, 0.0, -1.95, 1.76, 0.3, 2.06)
block("bed", "bed", ("bed_front", "bed_top"), 0.0, 0.3, -1.95, 1.66, 0.25, 1.98)
block("headboard", "bed", ("headboard_front", "headboard_top"), 0.0, 0.3, -2.965, 1.86, 0.95, 0.07)
for name, x in (("l", -0.33), ("r", 0.33)):
    block(f"pillow_{name}", "pillow", ("pillow_front", "pillow_top"), x, 0.55, -2.66, 0.7, 0.14, 0.38, (0.12, 0, 0.04 if x > 0 else -0.04))
block("duvet", "duvet", ("duvet_front", "duvet_top"), 0.0, 0.5, -1.5, 1.78, 0.2, 1.62)
block("duvet_fold", "duvet", ("bed_front", "bed_top"), 0.0, 0.62, -2.28, 1.76, 0.11, 0.26)

# --- bedside tables with lamps (the first is `nightstand`) ----------------------------------------------------------------------
for name, x in (("", 1.35), ("_l", -1.35)):
    block(f"nightstand{name}", "nightstand", WOOD, x, 0.0, -2.6, 0.5, 0.62, 0.5)
    block(f"drawer{name}", "trim", TRIM, x, 0.3, -2.345, 0.4, 0.18, 0.02)
    block(f"drawer_knob{name}", "trim", TRIM, x, 0.37, -2.325, 0.06, 0.03, 0.02)
    block(f"lamp_base{name}", "lamp", TRIM, x, 0.62, -2.72, 0.1, 0.18, 0.1)
    block(f"lamp_shade{name}", "lamp", ("lamp_front", "lamp_top"), x, 0.78, -2.72, 0.28, 0.22, 0.28)

# --- the wardrobe faces the room from the right wall (turned a quarter): body, two doors, handles, cornice ----------------------
WX, WZ = 2.68, -1.3                         # centre of the body in plan
block("wardrobe", "wardrobe", ("wardrobe_front", "wardrobe_top"), WX, 0.0, WZ, 1.6, 2.2, 0.62, (0, -HALF, 0))
for name, dz in (("a", -0.4), ("b", 0.4)):
    block(f"wardrobe_door_{name}", "wardrobe", ("wardrobe_front", "wardrobe_top"), WX - 0.325, 0.12, WZ + dz, 0.76, 1.96, 0.03, (0, -HALF, 0))
    block(f"wardrobe_handle_{name}", "trim", TRIM, WX - 0.345, 0.95, WZ + dz * 0.2, 0.03, 0.3, 0.03, (0, -HALF, 0))
block("wardrobe_cornice", "wardrobe", ("wardrobe_front", "wardrobe_top"), WX - 0.03, 2.2, WZ, 1.68, 0.08, 0.66, (0, -HALF, 0))

# --- the window (left wall, z -1.05 .. 0.45, y 0.96 .. 2.26): frame, mullion, transom, sill, curtains with their rod ----------
WZC = -0.3
block("window_sill", "trim", TRIM, -2.9, 0.92, WZC, 0.2, 0.04, 1.8)
block("window_frame_top", "trim", TRIM, -2.97, 2.26, WZC, 0.06, 0.05, 1.7)
block("window_frame_a", "trim", TRIM, -2.97, 0.96, WZC - 0.77, 0.06, 1.3, 0.05)
block("window_frame_b", "trim", TRIM, -2.97, 0.96, WZC + 0.77, 0.06, 1.3, 0.05)
block("window_mullion", "trim", TRIM, -2.975, 0.96, WZC, 0.03, 1.3, 0.04)
block("window_transom", "trim", TRIM, -2.975, 1.62, WZC, 0.03, 0.04, 1.5)
block("curtain_rod", "trim", TRIM, -2.9, 2.5, WZC, 0.05, 0.04, 2.4)
for name, dz in (("a", -1.0), ("b", 1.0)):
    block(f"curtain_{name}", "curtain", ("curtain_front", "curtain_top"), -2.9, 0.1, WZC + dz, 0.12, 2.42, 0.44)

# --- the door (right wall, z 1.05 .. 1.95): frame and handle; skirting, rug, picture, ceiling lamp ---------------------------
block("door_frame_a", "trim", TRIM, 2.97, 0.0, 1.0, 0.06, 2.15, 0.1)
block("door_frame_b", "trim", TRIM, 2.97, 0.0, 2.0, 0.06, 2.15, 0.1)
block("door_frame_top", "trim", TRIM, 2.97, 2.1, 1.5, 0.06, 0.08, 1.1)
block("door_handle", "trim", TRIM, 2.94, 1.0, 1.15, 0.05, 0.04, 0.14)
block("skirting_back", "trim", TRIM, 0.0, 0.0, -2.985, 5.9, 0.12, 0.03)
block("skirting_left", "trim", TRIM, -2.985, 0.0, 0.0, 0.03, 0.12, 5.9)
block("skirting_right_a", "trim", TRIM, 2.985, 0.0, -1.0, 0.03, 0.12, 3.9)
block("skirting_right_b", "trim", TRIM, 2.985, 0.0, 2.5, 0.03, 0.12, 1.0)
block("skirting_front", "trim", TRIM, 0.0, 0.0, 2.985, 5.9, 0.12, 0.03)
block("rug", "rug", ("rug_front", "rug_top"), 0.0, 0.0, -0.45, 3.2, 0.012, 2.5)
block("picture_frame", "art", TRIM, 0.0, 1.5, -2.975, 1.2, 0.8, 0.02)
block("picture", "art", ("art_front", "art_top"), 0.0, 1.55, -2.96, 1.04, 0.7, 0.02)
block("ceiling_lamp", "lamp", ("lamp_front", "lamp_top"), 0.0, 2.9, 0.0, 0.46, 0.1, 0.46)

SURFACES = ["floor", "ceiling", "wall_back", "wall_left", "wall_right", "wall_front", "window_view", "door",
            "bed_front", "bed_top", "duvet_front", "duvet_top", "pillow_front", "pillow_top", "headboard_front", "headboard_top",
            "nightstand_front", "nightstand_top", "wardrobe_front", "wardrobe_top", "trim_front", "trim_top", "curtain_front", "curtain_top",
            "rug_front", "rug_top", "lamp_front", "lamp_top", "art_front", "art_top"]

SKIN = {
    "floor": {"pattern": "wood", "color": "#8c6a45"}, "ceiling": {"pattern": "plaster", "color": "#ece6da"},
    "wall_back": {"pattern": "plaster", "color": "#d2c6b0"}, "wall_left": {"pattern": "plaster", "color": "#d2c6b0"},
    "wall_right": {"pattern": "plaster", "color": "#d2c6b0"}, "wall_front": {"pattern": "plaster", "color": "#d2c6b0"},
    "window_view": {"view": "day_window"}, "door": {"pattern": "wood", "color": "#7a5638"},
    "bed_front": {"pattern": "fabric", "color": "#ece7de"}, "bed_top": {"pattern": "fabric", "color": "#f2eee6"},
    "duvet_front": {"pattern": "quilt", "color": "#46618c"}, "duvet_top": {"pattern": "quilt", "color": "#52709c"},
    "pillow_front": {"pattern": "fabric", "color": "#f4f0e8"}, "pillow_top": {"pattern": "fabric", "color": "#f4f0e8"},
    "headboard_front": {"pattern": "wood", "color": "#5a3b26"}, "headboard_top": {"pattern": "wood", "color": "#5a3b26"},
    "nightstand_front": {"pattern": "wood", "color": "#6e4d33"}, "nightstand_top": {"pattern": "wood", "color": "#74533a"},
    "wardrobe_front": {"pattern": "wood", "color": "#5a4030"}, "wardrobe_top": {"pattern": "wood", "color": "#5a4030"},
    "trim_front": {"pattern": "plastic", "color": "#e6dfd1"}, "trim_top": {"pattern": "plastic", "color": "#eee8da"},
    "curtain_front": {"pattern": "fabric", "color": "#8a3b3f"}, "curtain_top": {"pattern": "fabric", "color": "#8a3b3f"},
    "rug_front": {"pattern": "carpet", "color": "#7a4d3d"}, "rug_top": {"pattern": "carpet", "color": "#7a4d3d"},
    "lamp_front": {"color": "#fff1cf"}, "lamp_top": {"color": "#fff6dc"},
    "art_front": {"color": "#3d6a8a"}, "art_top": {"color": "#496f8d"},
}

mold = {
    "id": "dormitorio",
    "title": {"es": "Dormitorio", "en": "Bedroom"},
    "kind": "interior",
    "sizes": {"small": [4.8, 4.8, 2.7], "medium": [W, D, H], "large": [7.5, 7.5, 3.36]},
    "walls": ["back", "left", "right", "front"],
    "openings": [{"wall": "left", "kind": "window", "x": 0.45, "width": 1.5, "height": 1.3, "sill": 0.96},
                 {"wall": "right", "kind": "door", "x": 0.75, "width": 0.9, "height": 2.1}],
    "blocks": blocks,
    "surfaces": SURFACES,
    "marks": [
        {"id": "speaker_a", "pose": "stand", "position": [-1.2, 0, -0.6], "facing": 0},
        {"id": "speaker_b", "pose": "stand", "position": [0.6, 0, 0.6], "facing": 180},
        {"id": "entrance", "pose": "stand", "position": [2.4, 0, 2.1], "facing": 180},
    ],
    "cameras": [
        {"id": "two_shot", "position": [0, 1.7, 2.8], "lookAt": [-1.2, 1.1, -0.6], "fov": 65},
        {"id": "ots_a", "position": [-2.1, 1.6, -1.5], "lookAt": [0.6, 1.1, 0.6], "fov": 50},
        {"id": "ots_b", "position": [2.1, 1.6, 1.5], "lookAt": [-1.2, 1.1, -0.6], "fov": 50},
        {"id": "wide", "position": [0, 2.75, 2.85], "lookAt": [-1.2, 1.1, -0.6], "fov": 65},
        {"id": "close_1", "position": [-0.9, 1.6, 1.32], "lookAt": [-1.2, 1.1, -0.6], "fov": 50},
        {"id": "close_2", "position": [0.9, 1.6, -1.32], "lookAt": [0.6, 1.1, 0.6], "fov": 50},
        {"id": "entrance", "position": [-2.4, 1.7, 1.8], "lookAt": [2.4, 1.1, 2.1], "fov": 50},
    ],
    "lights": "bar_warm",
    "propAnchors": [
        {"id": "table_left", "on": "nightstand_top", "position": [-1.35, 0.62, -2.45], "maxHeight": 0.6},
        {"id": "table_right", "on": "nightstand_top", "position": [1.35, 0.62, -2.45], "maxHeight": 0.6},
        {"id": "floor_corner", "on": "floor", "position": [-2.4, 0, 2.2], "maxHeight": 2},
        {"id": "wall_picture", "on": "wall_back", "position": [2.1, 1.4, -2.98], "maxHeight": 0.8},
    ],
    "defaultSkin": SKIN,
}

if __name__ == "__main__":
    OUT.write_text(json.dumps(mold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT.name, len(blocks), "blocks")
