"""Writes app/shared/set_molds/cabina.json: a vehicle cabin (car front, van, cab, cockpit) made of turned blocks.

The mold is data, this is how it is authored: ``python scripts/dev/make_cabin_mold.py``. Sizes: x = width, z = depth (the windshield
is the back wall, the occupants face -z), y = height (metres, ``medium``). Two front seats with raked backs and headrests, a
centre console, a dashboard with an instrument binnacle, a radio stack and a tilted steering wheel (a ring of turned slats),
pillars, a mirror, visors and door armrests. Windows share three surfaces (windshield, window_side, window_rear) so one skin
paints every pane. Skin it for a car, a van, a lorry cab or a spaceship cockpit; the geometry stays.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "app" / "shared" / "set_molds" / "cabina.json"
W, D, H = 2.1, 3.0, 1.45
SEAT_X = 0.5
WHEEL = (-SEAT_X, 0.88, -0.78)          # centre of the steering wheel
WHEEL_TILT = -0.5                       # about X: the top leans away from the driver
WHEEL_R = 0.19
SLATS = 14
RAKE = 0.26                              # seat backs lean back this many radians

blocks: list[dict] = []


def block(id_: str, kind: str, surfaces: tuple[str, str], x: float, y: float, z: float, w: float, h: float, d: float, rot=None) -> None:
    entry = {"id": id_, "kind": kind, "box": [round(x, 3), round(y, 3), round(z, 3), round(w, 3), round(h, 3), round(d, 3)], "surfaces": list(surfaces)}
    if rot and any(abs(a) > 1e-9 for a in rot):
        entry["rot"] = [round(a, 4) for a in rot]
    blocks.append(entry)


# --- seats -------------------------------------------------------------------------------------------------------------
for name, x in (("driver", -SEAT_X), ("passenger", SEAT_X)):
    block(f"seat_{name}", "seat", ("seat_front", "seat_top"), x, 0.0, -0.22, 0.52, 0.36, 0.56)
    block(f"seatback_{name}", "seat", ("seat_front", "seat_top"), x, 0.36, 0.09, 0.52, 0.62, 0.13, (RAKE, 0, 0))
    block(f"headrest_{name}", "seat", ("seat_front", "seat_top"), x, 0.97, 0.15, 0.26, 0.2, 0.1, (RAKE, 0, 0))
block("console", "console", ("console_front", "console_top"), 0.0, 0.0, -0.22, 0.2, 0.4, 0.7)
block("handbrake", "console", ("console_front", "console_top"), 0.0, 0.4, -0.45, 0.05, 0.16, 0.05, (0.35, 0, 0))

# --- dashboard ---------------------------------------------------------------------------------------------------------
block("dashboard", "dashboard", ("dash_front", "dash_top"), 0.0, 0.0, -1.22, 1.9, 0.58, 0.55)
block("dash_pad", "dashboard", ("dash_front", "dash_top"), 0.0, 0.58, -1.25, 1.9, 0.1, 0.48)
block("binnacle", "dashboard", ("cluster_front", "cluster_top"), -SEAT_X, 0.68, -1.12, 0.52, 0.2, 0.2, (-0.2, 0, 0))
block("radio", "dashboard", ("radio_front", "radio_top"), 0.0, 0.42, -0.96, 0.34, 0.3, 0.08)

# --- steering wheel: a ring of turned slats, a hub and three spokes, all leaning with the wheel ------------------------------
cx, cy, cz = WHEEL
c, s = math.cos(WHEEL_TILT), math.sin(WHEEL_TILT)


def on_wheel(px: float, py: float) -> tuple[float, float, float]:
    """A point of the wheel's own plane, in the cabin: tilted about X and moved to the wheel's centre."""
    return cx + px, cy + py * c, cz + py * s


for k in range(SLATS):
    t = 2 * math.pi * k / SLATS
    x, y, z = on_wheel(WHEEL_R * math.cos(t), WHEEL_R * math.sin(t))
    block(f"wheel_rim_{k}", "wheel", ("wheel_front", "wheel_top"), x, y - 0.0225, z, 0.1, 0.045, 0.045, (WHEEL_TILT, 0, t + math.pi / 2))
block("wheel_hub", "wheel", ("wheel_front", "wheel_top"), cx, cy - 0.05, cz, 0.12, 0.1, 0.07, (WHEEL_TILT, 0, 0))
for k, t in enumerate((math.pi, 0.0, 1.5 * math.pi)):
    x, y, z = on_wheel(WHEEL_R / 2 * math.cos(t), WHEEL_R / 2 * math.sin(t))
    block(f"wheel_spoke_{k}", "wheel", ("wheel_front", "wheel_top"), x, y - 0.015, z, WHEEL_R, 0.03, 0.03, (WHEEL_TILT, 0, t))
block("wheel_column", "wheel", ("wheel_front", "wheel_top"), cx, 0.6, -0.95, 0.1, 0.2, 0.3)

# --- trim: pillars, mirror, visors, armrests -------------------------------------------------------------------------------
for name, sign in (("l", -1), ("r", 1)):
    block(f"pillar_a_{name}", "trim", ("trim_front", "trim_top"), sign * 0.95, 0.8, -1.42, 0.12, 0.62, 0.14, (0, 0, -sign * 0.2))
    block(f"visor_{name}", "trim", ("trim_front", "trim_top"), sign * SEAT_X, 1.37, -1.3, 0.36, 0.04, 0.2)
    block(f"armrest_{name}", "trim", ("trim_front", "trim_top"), sign * 0.97, 0.62, -0.2, 0.1, 0.06, 0.8)
block("mirror", "trim", ("trim_front", "trim_top"), 0.0, 1.3, -1.38, 0.24, 0.07, 0.04)
block("mirror_stalk", "trim", ("trim_front", "trim_top"), 0.0, 1.35, -1.42, 0.03, 0.09, 0.03)

SURFACES = ["floor", "ceiling", "wall_back", "wall_left", "wall_right", "wall_front", "windshield", "window_side", "window_rear",
            "seat_front", "seat_top", "console_front", "console_top", "dash_front", "dash_top", "cluster_front", "cluster_top", "radio_front", "radio_top",
            "wheel_front", "wheel_top", "trim_front", "trim_top"]

SKIN = {
    "floor": "#2a2b2f", "ceiling": "#8d8a84", "wall_back": "#3a3c41", "wall_left": "#34363b", "wall_right": "#34363b", "wall_front": "#34363b",
    "windshield": "#9fbfe6", "window_side": "#9ab9dc", "window_rear": "#9ab9dc",
    "seat_front": "#2c2e34", "seat_top": "#34363d", "console_front": "#26282d", "console_top": "#2d3036", "dash_front": "#30333a", "dash_top": "#3a3d45",
    "cluster_front": "#14161b", "cluster_top": "#1c1e24", "radio_front": "#101216", "radio_top": "#1c1e24",
    "wheel_front": "#17181c", "wheel_top": "#202228", "trim_front": "#45484f", "trim_top": "#4d5058",
}

windows = [("back", "window", 0.5, 1.75, 0.55, 0.8, "windshield")]
for wall in ("left", "right"):
    windows += [(wall, "window", 0.417, 1.15, 0.4, 0.82, "window_side"), (wall, "window", 0.783, 0.9, 0.4, 0.82, "window_side")]
windows.append(("front", "window", 0.5, 1.4, 0.38, 0.85, "window_rear"))

mold = {
    "id": "cabina",
    "title": {"es": "Cabina de vehículo", "en": "Vehicle cabin"},
    "kind": "interior",
    "sizes": {"small": [1.8, 2.5, 1.25], "medium": [W, D, H], "large": [2.6, 3.9, 1.8]},
    "walls": ["back", "left", "right", "front"],
    "openings": [{"wall": w, "kind": k, "x": x, "width": wd, "height": ht, "sill": sill, "surface": surface} for w, k, x, wd, ht, sill, surface in windows],
    "blocks": blocks,
    "surfaces": SURFACES,
    "marks": [
        {"id": "speaker_a", "pose": "sit", "position": [-SEAT_X, 0, -0.25], "facing": 0},
        {"id": "speaker_b", "pose": "sit", "position": [SEAT_X, 0, -0.25], "facing": 0},
        {"id": "entrance", "pose": "stand", "position": [0.8, 0, 0.95], "facing": 270},
    ],
    "cameras": [
        {"id": "two_shot", "position": [0.0, 1.2, 1.25], "lookAt": [0.0, 0.95, -0.25], "fov": 58},
        {"id": "ots_a", "position": [-0.42, 1.2, 0.5], "lookAt": [0.5, 0.98, -0.25], "fov": 48},
        {"id": "ots_b", "position": [0.42, 1.2, 0.5], "lookAt": [-0.5, 0.98, -0.25], "fov": 48},
        {"id": "wide", "position": [0.0, 1.28, 1.3], "lookAt": [0.0, 0.9, -0.6], "fov": 72},
        {"id": "close_1", "position": [0.28, 1.14, 0.45], "lookAt": [-0.5, 1.02, -0.25], "fov": 38},
        {"id": "close_2", "position": [-0.28, 1.14, 0.45], "lookAt": [0.5, 1.02, -0.25], "fov": 38},
        {"id": "entrance", "position": [-0.85, 1.15, 0.9], "lookAt": [0.85, 1.0, 0.9], "fov": 50},
    ],
    "lights": "cabin",
    "propAnchors": [
        {"id": "table_left", "on": "dash_top", "position": [-0.5, 0.68, -1.25], "maxHeight": 0.4},
        {"id": "table_right", "on": "dash_top", "position": [0.5, 0.68, -1.25], "maxHeight": 0.4},
        {"id": "floor_corner", "on": "floor", "position": [0.0, 0, 0.9], "maxHeight": 0.9},
        {"id": "wall_picture", "on": "wall_front", "position": [0.0, 1.0, 1.48], "maxHeight": 0.3},
    ],
    "defaultSkin": {name: {"color": color} for name, color in SKIN.items()},
}

if __name__ == "__main__":
    OUT.write_text(json.dumps(mold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUT, len(blocks), "blocks")
