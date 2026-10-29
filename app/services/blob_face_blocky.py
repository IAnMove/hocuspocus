"""Faces for blocky people: the ``blocky`` kit style, a pixel face (voxel) or a rounded one (roblox).

The picture is the whole front of the head's box, so the face quad is mapped to it end to end (``fit`` 0.5). Eleven poses (the
same names as the other 3D heads), nine mouth shapes for the lipsync and a blink, all from the look: eye colour, the skin and
the hair colour for the fringe. Only the features and the hair band are drawn; the skin is the head's. No GPU."""
from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from services import blob_face as base
from services.blob_face_head import POSES

CELL = 128                       # a voxel face is an 8 x 8 grid of 128 px cells on the 1024 picture
SMALL = 1.0                      # (the mouth sprite is 512 x 320 and drawn at the same scale as the picture)
WHITE, DARK = (250, 250, 250, 255), (36, 30, 40, 255)
# per pose: the eye opening in cells (0.2 is a closed line), the brow lift in cells (negative is up) and tilt (+ inner end up),
# the mouth corner lift in cells (+ is a smile) and how wide the rest mouth is, the gaze shift in cells
EXPRESSIONS: dict[str, dict[str, Any]] = {
    "neutral": {"open": 1.0, "brow": 0.0, "tilt": 0.0, "corners": 0.0, "mouth": 2.0, "gaze": 0.0},
    "happy": {"open": 0.45, "brow": -0.3, "tilt": 0.0, "corners": 0.5, "mouth": 3.0, "gaze": 0.0},
    "sad": {"open": 0.8, "brow": 0.2, "tilt": 0.4, "corners": -0.5, "mouth": 2.0, "gaze": 0.0},
    "angry": {"open": 0.7, "brow": 0.15, "tilt": -0.45, "corners": -0.3, "mouth": 2.4, "gaze": 0.0},
    "surprised": {"open": 1.5, "brow": -0.7, "tilt": 0.0, "corners": 0.0, "mouth": 1.0, "gaze": 0.0},
    "smug": {"open": 0.6, "brow": -0.1, "tilt": -0.2, "corners": 0.4, "mouth": 2.4, "gaze": 0.35},
    "shy": {"open": 0.9, "brow": 0.1, "tilt": 0.2, "corners": 0.2, "mouth": 1.6, "gaze": -0.35},
    "sleepy": {"open": 0.3, "brow": 0.1, "tilt": 0.0, "corners": -0.1, "mouth": 1.6, "gaze": 0.0},
    "suspicious": {"open": 0.55, "brow": 0.0, "tilt": -0.3, "corners": -0.2, "mouth": 2.0, "gaze": -0.35},
    "tired": {"open": 0.4, "brow": 0.25, "tilt": 0.1, "corners": -0.3, "mouth": 2.0, "gaze": 0.0},
    "shout": {"open": 1.1, "brow": -0.2, "tilt": -0.4, "corners": -0.2, "mouth": 2.6, "gaze": 0.0},
}
assert set(EXPRESSIONS) == set(POSES)


def _roblox(look: dict[str, Any]) -> bool:
    return look.get("blocky") == "roblox"


def _eye(draw: ImageDraw.ImageDraw, look: dict[str, Any], sign: int, p: dict[str, Any], colour: tuple) -> None:
    """One eye; ``sign`` is -1 for the viewer's left."""
    cx = 512 + sign * (1.55 * CELL if not _roblox(look) else 1.15 * CELL)
    cy = (3.9 if not _roblox(look) else 3.7) * CELL
    height = p["open"] * (CELL if not _roblox(look) else 0.72 * CELL)
    gaze = p["gaze"] * CELL * 0.4
    if _roblox(look):
        draw.ellipse((cx + gaze - 0.2 * CELL, cy - height / 2, cx + gaze + 0.2 * CELL, cy + height / 2), fill=DARK)
        return
    # voxel: two cells, the white on the inner side and the iris on the outer, the shape of a pixel eye
    for k in (0, 1):
        x0 = cx - CELL + k * CELL
        shift = gaze if k == 1 else gaze * 0.5
        draw.rectangle((x0 + shift * 0.2, cy - height / 2, x0 + CELL - 1 + shift * 0.2, cy + height / 2), fill=WHITE if k == (0 if sign > 0 else 1) else colour)


def _brows(draw: ImageDraw.ImageDraw, look: dict[str, Any], p: dict[str, Any]) -> None:
    ink = tuple(look["lash"][:3]) + (255,)
    for sign in (-1, 1):
        cx = 512 + sign * (1.55 * CELL if not _roblox(look) else 1.15 * CELL)
        y = (2.85 if not _roblox(look) else 2.9) * CELL + p["brow"] * CELL
        inner = -p["tilt"] * CELL * 0.5
        outer = p["tilt"] * CELL * 0.5
        thick = 0.3 * CELL if not _roblox(look) else 0.12 * CELL
        if _roblox(look):
            draw.line((cx - sign * 0.3 * CELL, y + inner * -sign * 0.0 + (outer if sign < 0 else inner), cx + sign * 0.3 * CELL, y + (inner if sign < 0 else outer)), fill=ink, width=int(thick))
        else:
            draw.rectangle((cx - CELL, y + (outer if sign < 0 else inner) * 0.6, cx, y + thick + (outer if sign < 0 else inner) * 0.6), fill=ink)
            draw.rectangle((cx, y + (inner if sign < 0 else outer) * 0.6, cx + CELL, y + thick + (inner if sign < 0 else outer) * 0.6), fill=ink)


def _rest_mouth(draw: ImageDraw.ImageDraw, look: dict[str, Any], p: dict[str, Any]) -> None:
    y = (6.2 if not _roblox(look) else 5.7) * CELL
    width = p["mouth"] * CELL
    lift = (p["corners"] + (0.28 if _roblox(look) else 0.0)) * CELL   # a roblox face smiles at rest
    if _roblox(look):
        points = [(512 + x * width / 2, y + lift * (1 - x * x) * 0.9 - lift * 0.4) for x in [i / 12 - 1 for i in range(25)]]
        draw.line(points, fill=DARK, width=int(0.14 * CELL), joint="curve")
        return
    draw.rectangle((512 - width / 2, y, 512 + width / 2, y + 0.38 * CELL), fill=DARK)
    if lift:   # the corner pixels step up (a smile) or down
        for sign in (-1, 1):
            x = 512 + sign * width / 2
            draw.rectangle((x - (0 if sign > 0 else 0.38 * CELL), y - lift, x + (0.38 * CELL if sign > 0 else 0), y - lift + 0.38 * CELL), fill=DARK)


def _fringe(draw: ImageDraw.ImageDraw, look: dict[str, Any]) -> None:
    if _roblox(look):
        return
    hair = tuple(look["hair"][:3]) + (255,)
    draw.rectangle((0, 0, 1023, 1.0 * CELL), fill=hair)
    for x in (0, 7):   # a fringe that steps down at the temples, like the pixel hair of the sides
        draw.rectangle((x * CELL, 0, (x + 1) * CELL, 2.0 * CELL), fill=hair)


def draw_pose(look: dict[str, Any], pose: str, *, lids_only: bool = False) -> Image.Image:
    p = EXPRESSIONS[pose]
    image = Image.new("RGBA", (base.CANVAS, base.CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    colour = tuple(look["eye_color"][:3]) + (255,)
    if lids_only:
        skin = tuple(look["skin"][:3]) + (255,)
        for sign in (-1, 1):
            cx = 512 + sign * (1.55 * CELL if not _roblox(look) else 1.15 * CELL)
            cy = (3.9 if not _roblox(look) else 3.7) * CELL
            draw.rectangle((cx - 1.15 * CELL, cy - 0.75 * CELL, cx + 1.15 * CELL, cy + 0.75 * CELL), fill=skin)
            draw.rectangle((cx - CELL, cy - 0.08 * CELL, cx + CELL, cy + 0.12 * CELL), fill=DARK)
        return image
    _fringe(draw, look)
    for sign in (-1, 1):
        _eye(draw, look, sign, p, colour)
    _brows(draw, look, p)
    _rest_mouth(draw, look, p)
    return image


def blocky_mouths(look: dict[str, Any]) -> dict[str, Image.Image]:
    """The nine mouth shapes of the lipsync on a 512 x 320 sprite (1 cell is 128 px, the sprite is 4 cells wide)."""
    from services.flat_rig_base import STATES

    rounded = _roblox(look)
    inner, teeth, tongue = (96, 30, 40, 255), (250, 248, 240, 255), (222, 98, 110, 255)
    out: dict[str, Image.Image] = {}

    def box(draw, w, h, fill, dy=0.0, radius=0.0):
        x0, y0 = 256 - w * CELL / 2, 160 + dy * CELL - h * CELL / 2
        if rounded:
            draw.rounded_rectangle((x0, y0, x0 + w * CELL, y0 + h * CELL), radius=max(2, int(min(w, h) * CELL * (0.5 if radius else 0.3))), fill=fill)
        else:
            draw.rectangle((x0, y0, x0 + w * CELL, y0 + h * CELL), fill=fill)

    for state in STATES:
        image = Image.new("RGBA", (512, 320), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        if state in ("closed", "pressed") and rounded:   # a roblox mouth at rest is the smile
            wide = 1.9 if state == "closed" else 2.3
            points = [(256 + (i / 12 - 1) * wide * CELL / 2, 160 + 0.22 * CELL * (1 - (i / 12 - 1) ** 2)) for i in range(25)]
            draw.line(points, fill=DARK, width=int(0.14 * CELL), joint="curve")
        elif state == "closed":
            box(draw, 2.0, 0.38, DARK)
        elif state == "pressed":
            box(draw, 2.4, 0.3, DARK)
        elif state == "small":
            box(draw, 1.5, 0.8, inner)
        elif state == "medium":
            box(draw, 2.4, 1.0, inner)
            box(draw, 2.2, 0.28, teeth, -0.3)
        elif state == "wide":
            box(draw, 3.2, 1.3, inner)
            box(draw, 3.0, 0.3, teeth, -0.42)
            box(draw, 1.8, 0.34, tongue, 0.42)
        elif state == "round":
            box(draw, 1.2, 1.3, inner, 0.0, 1.0)
        elif state == "pucker":
            box(draw, 0.8, 0.8, inner, 0.0, 1.0)
        elif state == "bite":
            box(draw, 2.4, 0.5, teeth)
            box(draw, 2.4, 0.16, DARK, 0.3)
        else:   # tongue
            box(draw, 2.0, 0.9, inner)
            box(draw, 1.2, 0.5, tongue, 0.2)
        out[state] = image
    return out


def blocky_kit(look: dict[str, Any]) -> dict[str, Any]:
    poses = {pose: draw_pose(look, pose) for pose in POSES}
    blinks = {pose: draw_pose(look, pose, lids_only=True) for pose in POSES}
    mouths = blocky_mouths(look)
    mouth_y = (6.5 if not _roblox(look) else 6.0) * CELL
    anchors, placed_all = {}, {}
    eyes = base._anchor(512, 512, base.CANVAS, base.CANVAS, base.CANVAS)
    for pose in POSES:
        placed = (512.0, float(mouth_y), 512.0)
        anchors[pose] = {"mouth": base._anchor(*placed, base.CANVAS, base.CANVAS), "eyes": dict(eyes)}
        placed_all[pose] = {"mouth": placed, "eyes": (512, 512, base.CANVAS)}
    return {"traits": look, "poses": poses, "blinks": blinks, "mouths": mouths, "anchors": anchors, "layout": placed_all,
            "mouthMapping": dict(base.MAPPING), "preview": base._sheet(poses, mouths, anchors),
            "face": {"fit": [0.5, 0.5, 0.5, 0.5], "taper": 0.0, "poses": list(POSES), "shape": "mesh", "skin": base._hex(look["skin"])}}
