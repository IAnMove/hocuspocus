"""Round-eyed cartoon face for a bald 3D head: the ``cute`` style (mascots, balls, slimes, small pets).

The picture is a whole-head frame (the skull box ``SKULL`` inside the 1024 canvas) so
``world3d.scene.face`` can project it from the front onto the egg head with ``fit``,
the way old 3D games swapped eye and mouth textures on a face region. Eleven poses
(the eight shared with the other styles plus ``smug``, ``shy`` and ``sleepy``), the
nine mouth visemes and a blink, all from traits: zero GPU, exact anchors, any skin,
eye colour or lash colour. Only the features are drawn; the skin is the 3D head's.
"""
from __future__ import annotations

from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from services import blob_face as base
from services.blob_face_anime import _clip, _shade, anime_mouths

SC = base.SCALE
# The skull box in the picture: centre and half-size in canvas pixels. ``fit`` is the same as fractions.
SKULL = {"cx": 512, "cy": 470, "rx": 300, "ry": 345}
FIT = [SKULL["cx"] / 1024, SKULL["cy"] / 1024, SKULL["rx"] / 1024, SKULL["ry"] / 1024]
TAPER = 0.35
# Feature placement on the skull, in canvas pixels: eyes a little under the middle, a tiny nose, a small mouth.
EYE_Y, EYE_GAP, EYE_RX, EYE_RY = 518, 116, 76, 94
BROW_Y, NOSE_Y, MOUTH_Y, MOUTH_H = 412, 596, 656, 230
BLUSH_Y, BLUSH_X = 580, 185
EYE_WHITE = (238, 240, 247, 255)
POSES: dict[str, dict[str, Any]] = {
    # open: eye height share; pupil: iris share; brow_dy: brow lift in px (negative is up); tilt: inner end up (+) or down (-)
    # lid: cover from the top (0-1); shape: open | arc | angry | sad; gaze: pupil shift (dx, dy) in eye shares; corners: mouth corner lift
    "neutral": {"open": 1.0, "pupil": 1.0, "brow_dy": 0, "tilt": 0.0, "lid": 0.0, "shape": "open", "gaze": (0, 0), "corners": 0.0, "blush": 1.0},
    "happy": {"open": 1.0, "pupil": 1.0, "brow_dy": -10, "tilt": 0.4, "lid": 0.0, "shape": "arc", "gaze": (0, 0), "corners": 1.0, "blush": 1.2},
    "sad": {"open": 0.92, "pupil": 1.1, "brow_dy": 6, "tilt": 1.3, "lid": 0.1, "shape": "sad", "gaze": (0, 0.1), "corners": -1.0, "blush": 0.8},
    "angry": {"open": 0.88, "pupil": 0.85, "brow_dy": 10, "tilt": -1.5, "lid": 0.0, "shape": "angry", "gaze": (0, 0), "corners": -0.6, "blush": 0.0},
    "surprised": {"open": 1.16, "pupil": 0.55, "brow_dy": -34, "tilt": 0.1, "lid": 0.0, "shape": "open", "gaze": (0, 0), "corners": 0.0, "blush": 0.6},
    "smug": {"open": 0.9, "pupil": 0.9, "brow_dy": -4, "tilt": -0.5, "lid": 0.42, "shape": "open", "gaze": (0.12, 0), "corners": 0.8, "blush": 0.4},
    "shy": {"open": 0.95, "pupil": 1.05, "brow_dy": 4, "tilt": 0.8, "lid": 0.14, "shape": "open", "gaze": (0.1, 0.12), "corners": 0.2, "blush": 2.2},
    "sleepy": {"open": 0.9, "pupil": 1.0, "brow_dy": 8, "tilt": 0.2, "lid": 0.62, "shape": "open", "gaze": (0, 0.1), "corners": -0.2, "blush": 0.6},
    "suspicious": {"open": 0.95, "pupil": 0.9, "brow_dy": 0, "tilt": -0.9, "lid": 0.4, "shape": "open", "gaze": (-0.1, 0), "corners": -0.3, "blush": 0.3},
    "tired": {"open": 0.92, "pupil": 0.95, "brow_dy": 14, "tilt": 0.3, "lid": 0.56, "shape": "open", "gaze": (0, 0.08), "corners": -0.4, "blush": 0.3},
    "shout": {"open": 1.1, "pupil": 0.8, "brow_dy": -8, "tilt": -0.8, "lid": 0.0, "shape": "angry", "gaze": (0, 0), "corners": -0.3, "blush": 0.5},
}


def _s(value: float) -> float:
    return value * SC


def layout(pose: str) -> dict[str, Any]:
    return {"mouth": (512.0, float(MOUTH_Y), float(MOUTH_H))}


def _eye_box(cx: float, ry: float) -> tuple[float, float, float, float]:
    return (_s(cx - EYE_RX), _s(EYE_Y) - ry, _s(cx + EYE_RX), _s(EYE_Y) + ry)


def _iris(size, box, color, p) -> Image.Image:
    """Three bands, a limbal ring, the pupil, a big and a small highlight and a bottom reflection."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    gx, gy = p["gaze"]
    cx, cy = (x0 + x1) / 2 + w * 0.18 * gx, y0 + h * 0.56 + h * 0.12 * gy
    iw, ih = w * 0.37, h * 0.43
    draw.ellipse((cx - iw * 1.04, cy - ih * 1.04, cx + iw * 1.04, cy + ih * 1.04), fill=_shade(color, 0.42))
    for k, (dy, hk) in zip((0.62, 1.0, 1.38), ((-0.06, 0.98), (0.04, 0.9), (0.26, 0.6))):
        draw.ellipse((cx - iw, cy - ih + ih * dy, cx + iw, cy + ih * hk + ih * dy), fill=_shade(color, k))
    pw, ph = iw * 0.4 * p["pupil"], ih * 0.46 * p["pupil"]
    draw.ellipse((cx - pw, cy - ph * 0.85, cx + pw, cy + ph * 1.05), fill=(22, 16, 28, 255))
    r1, r2, r3 = iw * 0.36, iw * 0.15, iw * 0.1
    draw.ellipse((cx - iw * 0.5 - r1, cy - ih * 0.5 - r1, cx - iw * 0.5 + r1, cy - ih * 0.5 + r1), fill=(255, 255, 255, 255))
    draw.ellipse((cx + iw * 0.45 - r2, cy + ih * 0.42 - r2, cx + iw * 0.45 + r2, cy + ih * 0.42 + r2), fill=(255, 255, 255, 235))
    draw.ellipse((cx - iw * 0.1 - r3, cy + ih * 0.72 - r3, cx - iw * 0.1 + r3, cy + ih * 0.72 + r3), fill=_shade(color, 1.9)[:3] + (200,))
    return layer


def _eye(layer: Image.Image, cx: float, sign: int, traits: dict[str, Any], p: dict[str, Any]) -> None:
    lash, ry = traits["lash"], _s(EYE_RY) * p["open"]
    box = _eye_box(cx, ry)
    draw = ImageDraw.Draw(layer)
    width = max(4, int(traits["line"] * SC * 0.45))
    if p["shape"] == "arc":
        # a closed happy eye: one thick arc curving up, with a lash flick
        draw.arc((box[0], box[1] + ry * 0.35, box[2], box[3] - ry * 0.1), 200, 340, fill=lash, width=int(width * 2.2))
        outer = box[2] if sign > 0 else box[0]
        draw.line((outer, box[1] + ry * 0.62, outer + sign * _s(16), box[1] + ry * 0.42), fill=lash, width=int(width * 1.6))
        return
    mask = Image.new("L", layer.size, 0)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    eye = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(eye).ellipse(box, fill=EYE_WHITE)
    # the upper third of the white sits in the lash's shadow
    shade = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(shade).ellipse((box[0], box[1] - ry * 0.2, box[2], box[1] + ry * 0.6), fill=(140, 150, 185, 95))
    eye.alpha_composite(_clip(shade, mask))
    eye.alpha_composite(_clip(_iris(layer.size, box, traits["eye_color"], p), mask))
    cover = p["lid"] + (0.12 if p["shape"] == "angry" else 0.0)
    skin = tuple(traits["skin"][:3]) + (255,)
    if cover:
        cut = box[1] + (box[3] - box[1]) * cover
        ImageDraw.Draw(eye).rectangle((box[0] - 4, box[1] - 4, box[2] + 4, cut), fill=skin)
    if p["shape"] in ("angry", "sad"):
        top, h = box[1], box[3] - box[1]
        edge = (box[2] if sign < 0 else box[0]) if p["shape"] == "angry" else (box[0] if sign < 0 else box[2])
        far = edge + (box[0] - box[2] if edge == box[2] else box[2] - box[0]) * 0.9
        depth = 0.42 if p["shape"] == "angry" else 0.3
        ImageDraw.Draw(eye).polygon([(edge, top - 4), (far, top - 4), (edge, top + h * depth)], fill=skin)
    layer.alpha_composite(_clip(eye, mask))
    # lower lash: a thin arc on the outer two thirds; upper lash: thick, with a flick and two small lashes
    draw.arc((box[0], box[1], box[2], box[3]), 20 if sign > 0 else 90, 90 if sign > 0 else 160, fill=lash, width=max(3, int(width * 0.9)))
    top_cut = box[1] + (box[3] - box[1]) * cover if cover else box[1]
    lash_box = (box[0] - _s(3), top_cut - ry * 0.02, box[2] + _s(3), top_cut + (box[3] - top_cut) * 0.7)
    draw.arc(lash_box, 188, 352, fill=lash, width=int(width * 3.8))
    outer_x = box[2] if sign > 0 else box[0]
    ly = lash_box[1] + (lash_box[3] - lash_box[1]) * 0.3
    draw.line((outer_x - sign * _s(2), ly, outer_x + sign * _s(22), ly - _s(16)), fill=lash, width=int(width * 2.2))
    draw.line((outer_x - sign * _s(14), ly - _s(10), outer_x - sign * _s(4), ly - _s(26)), fill=lash, width=int(width * 1.2))
    # the crease above the lid
    draw.arc((box[0] + _s(8), lash_box[1] - ry * 0.34, box[2] - _s(8), lash_box[1] + ry * 0.2), 215, 325, fill=_shade(traits["skin"], 0.78), width=max(2, width // 2))
    if p["shape"] == "sad":
        tx, ty = (box[0] + box[2]) / 2 + sign * _s(10), box[3] + _s(4)
        draw.ellipse((tx - _s(6), ty, tx + _s(6), ty + _s(26)), fill=(176, 214, 245, 230), outline=lash, width=max(2, width // 3))


def _brows(draw: ImageDraw.ImageDraw, traits: dict[str, Any], p: dict[str, Any]) -> None:
    if traits["brows"]["style"] == "none":
        return
    thick = max(3, int(traits["brows"]["thickness"] * SC * (0.62 if traits["brows"]["style"] == "thin" else 0.95)))
    y = _s(BROW_Y + p["brow_dy"])
    radius = _s(EYE_RX)
    for sign in (-1, 1):
        cx = _s(512) + sign * _s(EYE_GAP)
        outer, inner = cx + sign * radius * 1.1, cx - sign * radius * 0.75
        tilt = p["tilt"] * radius * 0.5
        mid = ((outer + inner) / 2, y - _s(8) - abs(tilt) * 0.15)
        draw.line((outer, y + tilt * 0.3, mid[0], mid[1]), fill=traits["lash"], width=thick, joint="curve")
        draw.line((mid[0], mid[1], inner, y - tilt), fill=traits["lash"], width=max(2, int(thick * 0.7)), joint="curve")


def _nose(draw: ImageDraw.ImageDraw, traits: dict[str, Any]) -> None:
    if traits["nose"] == "none":
        return
    tone = _shade(traits["skin"], 0.7)
    cx, y = _s(518), _s(NOSE_Y)
    draw.line((cx - _s(4), y - _s(2), cx + _s(3), y + _s(10)), fill=tone, width=max(3, int(SC * 3)))
    draw.ellipse((cx - _s(5), y + _s(8), cx + _s(5), y + _s(14)), fill=tone)


def _mouth_corners(draw: ImageDraw.ImageDraw, traits: dict[str, Any], p: dict[str, Any]) -> None:
    """The rest mouth drawn in the base: a short curve whose corners lift for a smile and drop for a frown. The closed
    viseme sprite lands on the same line; an open viseme covers it."""
    lift = p["corners"]
    width = max(4, int(traits["line"] * SC * 0.4))
    y = _s(MOUTH_Y)
    points = [(_s(512) + _s(x), y - _s(9) * lift * ((x / 34) ** 2) + _s(2) * lift * (1 - (x / 34) ** 2)) for x in range(-34, 35, 2)]
    draw.line(points, fill=traits["ink"], width=width, joint="curve")


def _blush(image: Image.Image, traits: dict[str, Any], p: dict[str, Any]) -> None:
    strength = p["blush"] if traits["blush"] else (p["blush"] if p["blush"] > 1.5 else 0.0)
    if strength <= 0:
        return
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    alpha = min(200, int(70 * strength))
    for sign in (-1, 1):
        cx, y = _s(512) + sign * _s(BLUSH_X), _s(BLUSH_Y)
        draw.ellipse((cx - _s(70), y - _s(28), cx + _s(70), y + _s(28)), fill=(255, 120, 135, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(_s(16)))
    if strength > 1.5:
        lines = ImageDraw.Draw(layer)
        for sign in (-1, 1):
            for k in range(3):
                x = _s(512) + sign * _s(BLUSH_X - 30 + 30 * k)
                lines.line((x, _s(BLUSH_Y - 22), x + sign * _s(10), _s(BLUSH_Y + 22)), fill=(214, 80, 100, 200), width=max(2, int(SC * 2)))
    image.alpha_composite(layer)


def _lids(image: Image.Image, traits: dict[str, Any], p: dict[str, Any]) -> None:
    """The blink: skin over the open eye, a closed lash line, lower lashes kept."""
    width = max(4, int(traits["line"] * SC * 0.45))
    skin = tuple(traits["skin"][:3])
    patch = Image.new("RGBA", image.size, (*skin, 0))
    pdraw = ImageDraw.Draw(patch)
    for sign in (-1, 1):
        box = _eye_box(512 + sign * EYE_GAP, _s(EYE_RY) * 1.1)
        pdraw.ellipse((box[0] - _s(8), box[1] - _s(14), box[2] + _s(8), box[3] + _s(4)), fill=(*skin, 255))
    patch = patch.filter(ImageFilter.GaussianBlur(_s(5)))
    image.alpha_composite(patch)
    draw = ImageDraw.Draw(image)
    for sign in (-1, 1):
        box = _eye_box(512 + sign * EYE_GAP, _s(EYE_RY) * 1.1)
        cy = _s(EYE_Y) + _s(EYE_RY) * 0.3
        draw.arc((box[0], cy - _s(30), box[2], cy + _s(30)), 20, 160, fill=traits["lash"], width=int(width * 1.8))
        outer = box[2] if sign > 0 else box[0]
        draw.line((outer, cy + _s(12), outer + sign * _s(14), cy + _s(4)), fill=traits["lash"], width=int(width * 1.2))


def draw_pose(traits: dict[str, Any], pose: str, *, lids_only: bool = False) -> Image.Image:
    p = POSES[pose]
    image = Image.new("RGBA", (base.CANVAS * SC, base.CANVAS * SC), (0, 0, 0, 0))
    if lids_only:
        _lids(image, traits, p)
    else:
        _blush(image, traits, p)
        draw = ImageDraw.Draw(image)
        for sign in (-1, 1):
            _eye(image, 512 + sign * EYE_GAP, sign, traits, p)
        _brows(draw, traits, p)
        _nose(draw, traits)
        _mouth_corners(draw, traits, p)
    return image.resize((base.CANVAS, base.CANVAS), Image.LANCZOS)


def head_kit(look: dict[str, Any]) -> dict[str, Any]:
    poses = {pose: draw_pose(look, pose) for pose in POSES}
    blinks = {pose: draw_pose(look, pose, lids_only=True) for pose in POSES}
    mouths = anime_mouths(look)
    anchors, placed_all = {}, {}
    eyes = base._anchor(512, 512, base.CANVAS, base.CANVAS, base.CANVAS)
    for pose in POSES:
        placed = layout(pose)
        anchors[pose] = {"mouth": base._anchor(*placed["mouth"], base.CANVAS, base.CANVAS), "eyes": dict(eyes)}
        placed_all[pose] = {"mouth": placed["mouth"], "eyes": (512, 512, base.CANVAS)}
    return {"traits": look, "poses": poses, "blinks": blinks, "mouths": mouths, "anchors": anchors, "layout": placed_all,
            "mouthMapping": dict(base.MAPPING), "preview": base._sheet(poses, mouths, anchors),
            "face": {"fit": list(FIT), "taper": TAPER, "poses": list(POSES), "shape": "mesh", "skin": base._hex(look["skin"])}}
