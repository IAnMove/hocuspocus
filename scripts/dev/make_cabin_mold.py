"""Writes the vehicle-cabin molds: ``cabina`` (the shape, neutral skin), ``coche_interior`` (a car) and ``cabina_nave`` (a spaceship cockpit).

The molds are data, this is how they are authored: ``python scripts/dev/make_cabin_mold.py``. One geometry, three skins. Sizes: x = width, z = depth
(the windshield is the back wall, the occupants face -z), y = height (metres, ``medium``). Two front seats (cushion, bolsters, raked back, headrest), a
centre console, a dashboard with an instrument binnacle, a radio stack, vents and a glovebox, a tilted steering wheel (a ring of turned slats) or a
yoke, pillars with a B-pillar between two windows on each side, window frames, door cards. The windows are four surfaces (``windshield``,
``window_left``, ``window_right``, ``window_rear``), each skinned with a ``view`` that moves by itself (see ``roomViews.ts``); the materials are
``pattern`` tiles the room paints itself (``roomPatterns.ts``), so the default skin needs no picture and no clip.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "app" / "shared" / "set_molds"
W, D, H = 2.1, 3.0, 1.45
SEAT_X = 0.5
SEAT_TOP = 0.36                           # the cushion top: a sit mark's y
RAKE = 0.26                               # the seat backs lean back this many radians
WHEEL = (-SEAT_X, 0.88, -0.78)            # centre of the steering wheel
WHEEL_TILT = -0.5                         # about X: the top leans away from the driver
WHEEL_R, SLATS = 0.19, 20

# The side windows: (centre z, width) of the door window and the rear quarter window, sill and height. A B-pillar stands between them.
SIDE_WINDOWS = ((-0.52, 1.0), (0.66, 0.78))
SILL, GLASS_H = 0.42, 0.72
WINDSHIELD = (0.0, 1.62, 0.5, 0.78)       # centre x, width, sill, height
REAR = (0.0, 1.3, 0.55, 0.62)

SURFACES = ["floor", "ceiling", "wall_back", "wall_left", "wall_right", "wall_front", "windshield", "window_left", "window_right", "window_rear",
            "seat_front", "seat_top", "console_front", "console_top", "dash_front", "dash_top", "cluster_front", "cluster_top", "radio_front", "radio_top",
            "wheel_front", "wheel_top", "trim_front", "trim_top", "pillar_front", "pillar_top", "glow_front", "glow_top"]


class Cabin:
    def __init__(self) -> None:
        self.blocks: list[dict] = []

    def block(self, id_: str, kind: str, surfaces: tuple[str, str], x: float, y: float, z: float, w: float, h: float, d: float, rot=None) -> None:
        entry = {"id": id_, "kind": kind, "box": [round(x, 3), round(y, 3), round(z, 3), round(w, 3), round(h, 3), round(d, 3)], "surfaces": list(surfaces)}
        if rot and any(abs(a) > 1e-9 for a in rot):
            entry["rot"] = [round(a, 4) for a in rot]
        self.blocks.append(entry)

    def raked(self, id_: str, kind: str, surfaces: tuple[str, str], x: float, s0: float, s1: float, w: float, thick: float, forward: float = 0.0) -> None:
        """A slab laid along a seat back: from ``s0`` to ``s1`` metres up its axis, ``thick`` deep, ``forward`` metres in front of the axis."""
        sin, cos = math.sin(RAKE), math.cos(RAKE)
        s = (s0 + s1) / 2
        cy = SEAT_TOP + s * cos + forward * sin
        cz = 0.05 + s * sin - forward * cos
        self.block(id_, kind, surfaces, x, cy - (s1 - s0) / 2, cz, w, s1 - s0, thick, (RAKE, 0, 0))

    def seat(self, name: str, x: float) -> None:
        seat = ("seat_front", "seat_top")
        self.block(f"seat_{name}", "seat", seat, x, 0.0, -0.22, 0.5, SEAT_TOP, 0.56)
        for side in (-1, 1):
            self.block(f"seat_{name}_bolster_{'l' if side < 0 else 'r'}", "seat", seat, x + side * 0.235, SEAT_TOP, -0.24, 0.07, 0.08, 0.5, (0.0, 0.0, side * 0.12))
        self.raked(f"seatback_{name}", "seat", seat, x, 0.02, 0.52, 0.4, 0.1)
        for side in (-1, 1):
            self.raked(f"seatback_{name}_wing_{'l' if side < 0 else 'r'}", "seat", seat, x + side * 0.235, 0.05, 0.58, 0.075, 0.17, 0.035)
        for side in (-1, 1):
            self.raked(f"headrest_{name}_post_{'l' if side < 0 else 'r'}", "trim", ("trim_front", "trim_top"), x + side * 0.07, 0.56, 0.62, 0.025, 0.025)
        self.raked(f"headrest_{name}", "seat", seat, x, 0.6, 0.76, 0.22, 0.1, 0.012)      # behind the neck, below the head: a seated 1.8 m person keeps the whole head in view
        self.raked(f"seatback_{name}_shoulder", "seat", seat, x, 0.5, 0.58, 0.34, 0.1)

    def window_frame_side(self, sign: int, label: str, zc: float, width: float) -> None:
        x, wall = sign * (W / 2 - 0.02), ("trim_front", "trim_top")
        t = 0.05
        self.block(f"frame_{'l' if sign < 0 else 'r'}_{label}_sill", "trim", wall, x, SILL - t, zc, 0.04, t, width + 2 * t)
        self.block(f"frame_{'l' if sign < 0 else 'r'}_{label}_top", "trim", wall, x, SILL + GLASS_H, zc, 0.04, t, width + 2 * t)

    def pillars(self) -> None:
        pillar = ("pillar_front", "pillar_top")
        for name, sign in (("l", -1), ("r", 1)):
            x = sign * (W / 2 - 0.035)
            gap_a = SIDE_WINDOWS[0][0] + SIDE_WINDOWS[0][1] / 2
            gap_b = SIDE_WINDOWS[1][0] - SIDE_WINDOWS[1][1] / 2
            self.block(f"pillar_b_{name}", "trim", pillar, x, 0.0, (gap_a + gap_b) / 2, 0.07, H, gap_b - gap_a + 0.02)
            self.block(f"pillar_c_{name}", "trim", pillar, x, 0.0, D / 2 - 0.12, 0.07, H, 0.24)
            self.block(f"pillar_a_{name}", "trim", pillar, sign * 0.88, 0.5, -1.42, 0.13, 0.93, 0.14, (0, 0, -sign * 0.2))
            self.block(f"door_pull_{name}", "trim", ("trim_front", "trim_top"), x - sign * 0.01, 0.66, -0.2, 0.05, 0.05, 0.28)
            self.block(f"armrest_{name}", "trim", pillar, sign * 0.97, 0.6, -0.2, 0.1, 0.06, 0.8)
            self.block(f"kick_{name}", "trim", pillar, x, 0.0, -0.1, 0.06, 0.3, 2.2)
            self.block(f"header_side_{name}", "trim", pillar, x, SILL + GLASS_H + 0.05, 0.0, 0.06, H - SILL - GLASS_H - 0.05, D - 0.1)
        self.block("header", "trim", pillar, 0.0, WINDSHIELD[2] + WINDSHIELD[3], -D / 2 + 0.045, W - 0.1, H - WINDSHIELD[2] - WINDSHIELD[3], 0.08)
        self.block("rear_header", "trim", pillar, 0.0, REAR[2] + REAR[3], D / 2 - 0.045, W - 0.1, H - REAR[2] - REAR[3], 0.08)

    def dashboard(self) -> None:
        dash = ("dash_front", "dash_top")
        self.block("dashboard", "dashboard", dash, 0.0, 0.0, -1.22, 1.9, 0.58, 0.55)
        self.block("dash_pad", "dashboard", dash, 0.0, 0.58, -1.25, 1.9, 0.1, 0.48)
        self.block("glovebox", "dashboard", dash, SEAT_X, 0.28, -0.94, 0.5, 0.22, 0.02)
        for i, x in enumerate((-0.15, 0.0, 0.15)):
            self.block(f"vent_{i}", "trim", ("trim_front", "trim_top"), x, 0.6, -1.0, 0.1, 0.04, 0.02)
        self.block("vent_l", "trim", ("trim_front", "trim_top"), -0.88, 0.55, -0.99, 0.08, 0.05, 0.02)
        self.block("vent_r", "trim", ("trim_front", "trim_top"), 0.88, 0.55, -0.99, 0.08, 0.05, 0.02)
        self.block("binnacle", "dashboard", ("cluster_front", "cluster_top"), -SEAT_X, 0.68, -1.12, 0.52, 0.2, 0.2, (-0.2, 0, 0))
        self.block("radio", "dashboard", ("radio_front", "radio_top"), 0.0, 0.4, -0.96, 0.34, 0.3, 0.08)
        self.block("console", "console", ("console_front", "console_top"), 0.0, 0.0, -0.22, 0.2, 0.4, 0.7)
        self.block("shifter", "console", ("console_front", "console_top"), 0.0, 0.4, -0.45, 0.05, 0.14, 0.05, (0.35, 0, 0))
        self.block("cupholder", "console", ("trim_front", "trim_top"), 0.0, 0.4, -0.08, 0.14, 0.02, 0.14)

    def wheel(self) -> None:
        cx, cy, cz = WHEEL
        c, s = math.cos(WHEEL_TILT), math.sin(WHEEL_TILT)
        on_wheel = lambda px, py: (cx + px, cy + py * c, cz + py * s)
        wheel = ("wheel_front", "wheel_top")
        for k in range(SLATS):
            t = 2 * math.pi * k / SLATS
            x, y, z = on_wheel(WHEEL_R * math.cos(t), WHEEL_R * math.sin(t))
            self.block(f"wheel_rim_{k}", "wheel", wheel, x, y - 0.02, z, 0.085, 0.04, 0.04, (WHEEL_TILT, 0, t + math.pi / 2))
        self.block("wheel_hub", "wheel", wheel, cx, cy - 0.05, cz, 0.12, 0.1, 0.07, (WHEEL_TILT, 0, 0))
        for k, t in enumerate((math.pi, 0.0, 1.5 * math.pi)):
            x, y, z = on_wheel(WHEEL_R / 2 * math.cos(t), WHEEL_R / 2 * math.sin(t))
            self.block(f"wheel_spoke_{k}", "wheel", wheel, x, y - 0.015, z, WHEEL_R, 0.03, 0.03, (WHEEL_TILT, 0, t))
        self.block("wheel_column", "wheel", wheel, cx, 0.6, -0.95, 0.1, 0.2, 0.3)

    def yoke(self) -> None:
        cx, cy, cz = WHEEL
        wheel = ("wheel_front", "wheel_top")
        self.block("yoke_column", "wheel", wheel, cx, 0.5, -1.0, 0.07, 0.4, 0.07)
        self.block("yoke_bar", "wheel", wheel, cx, cy - 0.015, cz, 0.42, 0.03, 0.03, (WHEEL_TILT, 0, 0))
        for side in (-1, 1):
            self.block(f"yoke_grip_{'l' if side < 0 else 'r'}", "wheel", wheel, cx + side * 0.21, cy - 0.07, cz + 0.02, 0.05, 0.16, 0.05, (WHEEL_TILT, 0, side * 0.2))

    def trim_ceiling(self, mirror: bool) -> None:
        trim = ("trim_front", "trim_top")
        for name, sign in (("l", -1), ("r", 1)):
            self.block(f"visor_{name}", "trim", ("pillar_front", "pillar_top"), sign * SEAT_X, 1.37, -1.3, 0.36, 0.04, 0.2)
        if mirror:
            self.block("mirror", "trim", trim, 0.0, 1.27, -1.36, 0.24, 0.07, 0.04)
            self.block("mirror_stalk", "trim", trim, 0.0, 1.33, -1.4, 0.03, 0.09, 0.03)
        self.block("dome_light", "trim", ("glow_front", "glow_top"), 0.0, 1.43, 0.0, 0.2, 0.02, 0.14)

    def cockpit_panels(self) -> None:
        """A spaceship's glowing side consoles and overhead panel; the car skips them."""
        glow = ("glow_front", "glow_top")
        for name, sign in (("l", -1), ("r", 1)):
            self.block(f"side_console_{name}", "console", ("console_front", "console_top"), sign * 0.9, 0.0, -0.45, 0.16, 0.55, 0.9)
            self.block(f"side_panel_{name}", "console", glow, sign * 0.86, 0.55, -0.45, 0.1, 0.03, 0.7, (0, 0, -sign * 0.5))
        self.block("overhead_panel", "console", glow, 0.0, 1.38, -1.0, 1.0, 0.05, 0.3)


def windows() -> list[dict]:
    out = []
    for wall in ("left", "right"):
        for zc, width in SIDE_WINDOWS:
            out.append({"wall": wall, "kind": "window", "x": round((zc + D / 2) / D, 4), "width": width, "height": GLASS_H, "sill": SILL, "surface": f"window_{wall}"})
    out.append({"wall": "back", "kind": "window", "x": round(WINDSHIELD[0] / W + 0.5, 4), "width": WINDSHIELD[1], "height": WINDSHIELD[3], "sill": WINDSHIELD[2], "surface": "windshield"})
    out.append({"wall": "front", "kind": "window", "x": round(REAR[0] / W + 0.5, 4), "width": REAR[1], "height": REAR[3], "sill": REAR[2], "surface": "window_rear"})
    return out


def skin(variant: str) -> dict:
    view = "space" if variant == "ship" else "road_night"
    window = {"view": view}
    if variant == "ship":
        s = {"floor": {"pattern": "metal", "color": "#3a3f48"}, "ceiling": {"pattern": "metal", "color": "#4a505b"}, "wall_back": {"pattern": "metal", "color": "#30353d"},
             "wall_left": {"pattern": "metal", "color": "#444a55"}, "wall_right": {"pattern": "metal", "color": "#444a55"}, "wall_front": {"pattern": "metal", "color": "#30353d"},
             "seat_front": {"pattern": "fabric", "color": "#3a4a66"}, "seat_top": {"pattern": "fabric", "color": "#44557a"},
             "console_front": {"pattern": "metal", "color": "#2a2e36"}, "console_top": {"pattern": "metal", "color": "#363b45"},
             "dash_front": {"pattern": "metal", "color": "#2d323b"}, "dash_top": {"pattern": "plastic", "color": "#20242b"},
             "cluster_front": {"pattern": "dials", "color": "#8fe8ff"}, "cluster_top": {"color": "#101419"}, "radio_front": {"pattern": "radio", "color": "#7dffc0"}, "radio_top": {"color": "#101419"},
             "wheel_front": {"pattern": "plastic", "color": "#1a1d22"}, "wheel_top": {"pattern": "plastic", "color": "#262a31"},
             "trim_front": {"pattern": "metal", "color": "#6a7280"}, "trim_top": {"pattern": "metal", "color": "#757e8c"},
             "pillar_front": {"pattern": "metal", "color": "#3b414c"}, "pillar_top": {"pattern": "metal", "color": "#444b57"}, "glow_front": {"color": "#7fe8ff"}, "glow_top": {"color": "#bff6ff"}}
    else:
        s = {"floor": {"pattern": "carpet", "color": "#2c2c30"}, "ceiling": {"pattern": "fabric", "color": "#2a2928"}, "wall_back": {"pattern": "plastic", "color": "#2a2b30"},
             "wall_left": {"pattern": "plastic", "color": "#24272c"}, "wall_right": {"pattern": "plastic", "color": "#24272c"}, "wall_front": {"pattern": "plastic", "color": "#2a2b2f"},
             "seat_front": {"pattern": "leather", "color": "#2a1f19"}, "seat_top": {"pattern": "leather", "color": "#33261d"},
             "console_front": {"pattern": "plastic", "color": "#2c2d32"}, "console_top": {"pattern": "plastic", "color": "#34363c"},
             "dash_front": {"pattern": "plastic", "color": "#2f3238"}, "dash_top": {"pattern": "plastic", "color": "#25272c"},
             "cluster_front": {"pattern": "dials", "color": "#ffffff"}, "cluster_top": {"color": "#14161b"}, "radio_front": {"pattern": "radio", "color": "#ffffff"}, "radio_top": {"color": "#14161b"},
             "wheel_front": {"pattern": "plastic", "color": "#17181c"}, "wheel_top": {"pattern": "plastic", "color": "#202228"},
             "trim_front": {"pattern": "metal", "color": "#6c7078"}, "trim_top": {"pattern": "metal", "color": "#7a7e86"},
             "pillar_front": {"pattern": "fabric", "color": "#2c2e33"}, "pillar_top": {"pattern": "fabric", "color": "#35373c"}, "glow_front": {"color": "#fff1c8"}, "glow_top": {"color": "#fff6dc"}}
    s.update({"windshield": window, "window_left": window, "window_right": window, "window_rear": window})
    return s


def build(variant: str) -> dict:
    cabin = Cabin()
    for name, x in (("driver", -SEAT_X), ("passenger", SEAT_X)):
        cabin.seat(name, x)
    cabin.dashboard()
    if variant == "ship":
        cabin.yoke()
        cabin.cockpit_panels()
    else:
        cabin.wheel()
    cabin.pillars()
    for sign in (-1, 1):
        for label, (zc, width) in zip("ab", SIDE_WINDOWS):
            cabin.window_frame_side(sign, label, zc, width)
    cabin.trim_ceiling(mirror=variant != "ship")
    ids = {"cabina": ("cabina", {"es": "Cabina de vehículo", "en": "Vehicle cabin"}, "car"), "coche": ("coche_interior", {"es": "Interior de coche", "en": "Car interior"}, "car"),
           "ship": ("cabina_nave", {"es": "Cabina de nave", "en": "Spaceship cockpit"}, "ship")}
    id_, title, look = ids[variant]
    return {
        "id": id_, "title": title, "kind": "interior",
        "sizes": {"small": [1.8, 2.5, 1.25], "medium": [W, D, H], "large": [2.6, 3.9, 1.8]},
        "walls": ["back", "left", "right", "front"],
        "openings": windows(), "blocks": cabin.blocks, "surfaces": SURFACES,
        "marks": [
            {"id": "speaker_a", "pose": "sit", "position": [-SEAT_X, 0, -0.25], "facing": 180},
            {"id": "speaker_b", "pose": "sit", "position": [SEAT_X, 0, -0.25], "facing": 180},
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
        "defaultSkin": skin("ship" if look == "ship" else "car"),
    }


if __name__ == "__main__":
    for variant in ("cabina", "coche", "ship"):
        mold = build(variant)
        path = OUT / f"{mold['id']}.json"
        path.write_text(json.dumps(mold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(path.name, len(mold["blocks"]), "blocks")
