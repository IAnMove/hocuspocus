"""The anime face for the lofted human head: the ``anime_head`` style, calibrated on painted heads.

Measured on the Qwen heads that read as anime: each eye is about 17 % of the face width and 9 % of the skull
height (an almond 1.5 times wider than tall, the outer corner a little higher), the eye line sits 58 % down the
skull, the mouth 84 % down and about a tenth of the skull wide, the brows a third of an eye above the lids.
The ``cute`` style (``blob_face_head``) keeps the round mascot eyes; this one draws almond eyes with a heavy
upper lash and its tail, the iris taller than the opening and shaded under the lid, a limbal ring, three
highlights, a thin lower lash, tapered brows that change per expression, a small nose, a small mouth and a
blush. Same kit shape: eleven poses, nine visemes, a blink; the picture's skull box is ``SKULL``.
"""
from __future__ import annotations

import math
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from services import blob_face as base
from services.blob_face_anime import _clip, _shade, anime_mouths
from services.blob_face_head import FIT, POSES, SKULL, TAPER, _s, layout as _cute_layout

SC = base.SCALE
EYE_Y, EYE_GAP, EYE_RX, EYE_RY = 528, 90, 60, 41
BROW_GAP, NOSE_Y, MOUTH_Y, MOUTH_H = 34, 646, 700, 190
BLUSH_Y, BLUSH_X = 652, 150
EYE_WHITE = (240, 242, 248, 255)
SHAPES = {"soft": {"tilt": 5, "wide": 1.0, "tall": 1.06}, "sharp": {"tilt": 13, "wide": 1.05, "tall": 0.88}}


def layout(pose: str) -> dict[str, Any]:
    return {"mouth": (512.0, float(MOUTH_Y), float(MOUTH_H))}


def _quad(p0, p1, p2, count: int = 12) -> list:
    out = []
    for i in range(count + 1):
        u = i / count
        out.append(((1 - u) ** 2 * p0[0] + 2 * u * (1 - u) * p1[0] + u * u * p2[0], (1 - u) ** 2 * p0[1] + 2 * u * (1 - u) * p1[1] + u * u * p2[1]))
    return out


def _opening(cx: float, sign: int, p: dict[str, Any], shape: dict) -> dict[str, Any]:
    """The eye opening as two curves (supersampled px): ``upper`` from the inner corner to the outer, ``lower`` back."""
    rx, ry = _s(EYE_RX) * shape["wide"], _s(EYE_RY) * shape["tall"] * p["open"]
    tilt = _s(shape["tilt"])
    cy = _s(EYE_Y)
    inner = (cx - sign * rx, cy + ry * 0.15)
    outer = (cx + sign * rx, cy - tilt)
    lid = p["lid"] + (0.12 if p["shape"] == "angry" else 0.0)
    top_y = cy - ry * (1.0 - lid * 1.6)
    upper = _quad(inner, (cx + sign * rx * 0.1, top_y - ry * 0.55), outer)
    lower = _quad(outer, (cx + sign * rx * 0.05, cy + ry * 1.35), inner)
    if p["shape"] == "angry":
        upper = [(x, y + (ry * 0.5) * max(0.0, 1 - abs(x - inner[0]) / (rx * 1.2))) for x, y in upper]
    if p["shape"] == "sad":
        upper = [(x, y + (ry * 0.45) * max(0.0, 1 - abs(x - outer[0]) / (rx * 1.2))) for x, y in upper]
    return {"upper": upper, "lower": lower, "inner": inner, "outer": outer, "rx": rx, "ry": ry, "cx": cx, "cy": cy, "lid": lid}


def _iris(size, o: dict, color, p: dict[str, Any]) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    gx, gy = p["gaze"]
    cx, cy = o["cx"] + o["rx"] * 0.22 * gx, o["cy"] + o["ry"] * 0.1 + o["ry"] * 0.3 * gy
    iw, ih = o["rx"] * 0.36 * p["pupil"] ** 0.2, o["ry"] * 0.82
    draw.ellipse((cx - iw * 1.06, cy - ih * 1.06, cx + iw * 1.06, cy + ih * 1.06), fill=_shade(color, 0.38))
    for k, (dy, hk) in zip((0.6, 1.0, 1.42), ((-0.05, 0.98), (0.08, 0.86), (0.34, 0.5))):
        draw.ellipse((cx - iw, cy - ih + ih * dy, cx + iw, cy + ih * hk + ih * dy), fill=_shade(color, k))
    pw, ph = iw * 0.42 * p["pupil"], ih * 0.46 * p["pupil"]
    draw.ellipse((cx - pw, cy - ph * 0.8, cx + pw, cy + ph * 1.1), fill=(20, 14, 26, 255))
    r1, r2, r3 = iw * 0.4, iw * 0.16, iw * 0.11
    draw.ellipse((cx - iw * 0.45 - r1, cy - ih * 0.5 - r1, cx - iw * 0.45 + r1, cy - ih * 0.5 + r1), fill=(255, 255, 255, 255))
    draw.ellipse((cx + iw * 0.5 - r2, cy + ih * 0.45 - r2, cx + iw * 0.5 + r2, cy + ih * 0.45 + r2), fill=(255, 255, 255, 240))
    draw.ellipse((cx - iw * 0.05 - r3, cy + ih * 0.75 - r3, cx - iw * 0.05 + r3, cy + ih * 0.75 + r3), fill=_shade(color, 2.0)[:3] + (210,))
    return layer


def _eye(layer: Image.Image, cx: float, sign: int, traits: dict[str, Any], p: dict[str, Any]) -> None:
    lash = traits["lash"]
    shape = SHAPES[traits.get("face_shape", "soft")]
    o = _opening(cx, sign, p, shape)
    draw = ImageDraw.Draw(layer)
    width = max(4, int(traits["line"] * SC * 0.4))
    rx, ry = o["rx"], o["ry"]
    if p["shape"] == "arc":
        pts = _quad((cx - sign * rx * 0.95, o["cy"] + ry * 0.3), (cx, o["cy"] - ry * 1.5), (cx + sign * rx * 0.95, o["cy"] + ry * 0.3 - _s(shape["tilt"]) * 0.6))
        draw.line(pts, fill=lash, width=int(width * 2.4), joint="curve")
        draw.line((pts[-1][0], pts[-1][1], pts[-1][0] + sign * _s(16), pts[-1][1] - _s(12)), fill=lash, width=int(width * 1.8))
        return
    polygon = o["upper"] + o["lower"]
    mask = Image.new("L", layer.size, 0)
    ImageDraw.Draw(mask).polygon(polygon, fill=255)
    eye = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(eye).polygon(polygon, fill=EYE_WHITE)
    shade = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    top = min(y for _x, y in o["upper"])
    ImageDraw.Draw(shade).rectangle((cx - rx * 1.2, top - ry, cx + rx * 1.2, top + ry * 0.75), fill=(125, 135, 175, 110))
    eye.alpha_composite(_clip(_iris(layer.size, o, traits["eye_color"], p), mask))
    eye.alpha_composite(_clip(shade, mask))
    layer.alpha_composite(_clip(eye, mask))
    # lower lash: thin, on the outer two thirds; upper lash: heavy, thickest over the outer half, with a tail
    lower = o["lower"][: int(len(o["lower"]) * 0.7)]
    draw.line(lower, fill=lash, width=max(3, int(width * 0.8)), joint="curve")
    upper = o["upper"]
    for i in range(len(upper) - 1):
        w = width * (1.9 + 2.6 * (i / (len(upper) - 1)))
        draw.line((upper[i], upper[i + 1]), fill=lash, width=int(w))
    tail = o["outer"]
    flick = _quad((tail[0] - sign * _s(4), tail[1] + _s(3)), (tail[0] + sign * _s(10), tail[1] - _s(2)), (tail[0] + sign * _s(20), tail[1] - _s(14)), 6)
    for i in range(len(flick) - 1):
        draw.line((flick[i], flick[i + 1]), fill=lash, width=int(width * (2.4 - 1.6 * i / 5)))
    draw.line((tail[0] - sign * _s(14), tail[1] - _s(6), tail[0] - sign * _s(8), tail[1] - _s(16)), fill=lash, width=int(width * 1.0))
    draw.line((o["inner"][0], o["inner"][1], o["inner"][0] - sign * _s(6), o["inner"][1] + _s(6)), fill=lash, width=int(width * 1.2))
    # the crease above the lid
    crease = [(x, y - ry * 0.55) for x, y in upper[2:-2]]
    draw.line(crease, fill=_shade(traits["skin"], 0.8), width=max(2, width // 2), joint="curve")
    if p["shape"] == "sad":
        tx, ty = cx + sign * rx * 0.3, max(y for _x, y in o["lower"]) + _s(2)
        draw.ellipse((tx - _s(6), ty, tx + _s(6), ty + _s(24)), fill=(176, 214, 245, 230), outline=lash, width=max(2, width // 3))


def _brows(draw: ImageDraw.ImageDraw, traits: dict[str, Any], p: dict[str, Any]) -> None:
    if traits["brows"]["style"] == "none":
        return
    thick = max(4, int(traits["brows"]["thickness"] * SC * (0.5 if traits["brows"]["style"] == "thin" else 0.8)))
    shape = SHAPES[traits.get("face_shape", "soft")]
    y = _s(EYE_Y - EYE_RY - BROW_GAP + p["brow_dy"])
    rx = _s(EYE_RX) * shape["wide"]
    for sign in (-1, 1):
        cx = _s(512) + sign * _s(EYE_GAP)
        inner, outer = cx - sign * rx * 0.85, cx + sign * rx * 1.15
        tilt = p["tilt"] * rx * 0.45
        peak = (cx + sign * rx * 0.3, y - _s(10) - abs(tilt) * 0.1)
        pts = _quad((inner, y - tilt), peak, (outer, y + tilt * 0.35 - _s(shape["tilt"]) * 0.4), 10)
        for i in range(len(pts) - 1):
            w = thick * (1.0 - 0.6 * i / (len(pts) - 1))
            draw.line((pts[i], pts[i + 1]), fill=traits["lash"], width=max(2, int(w)))


def _nose(draw: ImageDraw.ImageDraw, traits: dict[str, Any]) -> None:
    if traits["nose"] == "none":
        return
    tone = _shade(traits["skin"], 0.72)
    cx, y = _s(520), _s(NOSE_Y)
    draw.line((cx - _s(3), y - _s(6), cx + _s(3), y + _s(6)), fill=tone, width=max(3, int(SC * 2.6)))
    draw.ellipse((cx - _s(4), y + _s(5), cx + _s(4), y + _s(10)), fill=tone)


def _mouth(draw: ImageDraw.ImageDraw, traits: dict[str, Any], p: dict[str, Any]) -> None:
    """The rest mouth in the base: a short curve, corners up for a smile and down for a frown. The closed viseme sprite
    lands on it; an open viseme covers it."""
    lift = p["corners"]
    width = max(4, int(traits["line"] * SC * 0.42))
    y = _s(MOUTH_Y)
    half = 30
    pts = [(_s(512) + _s(x), y - _s(8) * lift * ((x / half) ** 2) + _s(2) * lift * (1 - (x / half) ** 2)) for x in range(-half, half + 1, 2)]
    draw.line(pts, fill=traits["ink"], width=width, joint="curve")
    if lift > 0.6:
        draw.line((pts[0][0], pts[0][1], pts[0][0] - _s(4), pts[0][1] - _s(6)), fill=traits["ink"], width=width)
        draw.line((pts[-1][0], pts[-1][1], pts[-1][0] + _s(4), pts[-1][1] - _s(6)), fill=traits["ink"], width=width)


def _blush(image: Image.Image, traits: dict[str, Any], p: dict[str, Any]) -> None:
    strength = p["blush"] if traits["blush"] else (p["blush"] if p["blush"] > 1.5 else 0.0)
    if strength <= 0:
        return
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    alpha = min(190, int(60 * strength))
    for sign in (-1, 1):
        cx, y = _s(512) + sign * _s(BLUSH_X), _s(BLUSH_Y)
        draw.ellipse((cx - _s(64), y - _s(22), cx + _s(64), y + _s(22)), fill=(255, 118, 132, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(_s(18)))
    if strength > 1.5:
        lines = ImageDraw.Draw(layer)
        for sign in (-1, 1):
            for k in range(3):
                x = _s(512) + sign * _s(BLUSH_X - 26 + 26 * k)
                lines.line((x, _s(BLUSH_Y - 18), x + sign * _s(8), _s(BLUSH_Y + 18)), fill=(214, 80, 100, 190), width=max(2, int(SC * 1.8)))
    image.alpha_composite(layer)


def _lids(image: Image.Image, traits: dict[str, Any], p: dict[str, Any]) -> None:
    """The blink: skin over the opening, a closed lash curve that follows the lower lid, the tail kept."""
    width = max(4, int(traits["line"] * SC * 0.4))
    shape = SHAPES[traits.get("face_shape", "soft")]
    skin = tuple(traits["skin"][:3])
    patch = Image.new("RGBA", image.size, (*skin, 0))
    pdraw = ImageDraw.Draw(patch)
    for sign in (-1, 1):
        o = _opening(_s(512) + sign * _s(EYE_GAP), sign, POSES["neutral"], shape)
        pdraw.polygon([(x, y - _s(14)) for x, y in o["upper"]] + [(x, y + _s(8)) for x, y in o["lower"]], fill=(*skin, 255))
        pdraw.ellipse((o["cx"] - o["rx"] * 1.25, o["cy"] - o["ry"] * 2.2, o["cx"] + o["rx"] * 1.25, o["cy"] + o["ry"] * 1.6), fill=(*skin, 255))
    patch = patch.filter(ImageFilter.GaussianBlur(_s(5)))
    image.alpha_composite(patch)
    draw = ImageDraw.Draw(image)
    for sign in (-1, 1):
        o = _opening(_s(512) + sign * _s(EYE_GAP), sign, POSES["neutral"], shape)
        pts = _quad((o["inner"][0], o["cy"] + o["ry"] * 0.4), (o["cx"], o["cy"] + o["ry"] * 0.95), (o["outer"][0], o["cy"] + o["ry"] * 0.25))
        draw.line(pts, fill=traits["lash"], width=int(width * 2.0), joint="curve")
        draw.line((pts[-1][0], pts[-1][1], pts[-1][0] + sign * _s(14), pts[-1][1] - _s(8)), fill=traits["lash"], width=int(width * 1.6))


def draw_pose(traits: dict[str, Any], pose: str, *, lids_only: bool = False) -> Image.Image:
    p = POSES[pose]
    image = Image.new("RGBA", (base.CANVAS * SC, base.CANVAS * SC), (0, 0, 0, 0))
    if lids_only:
        _lids(image, traits, p)
    else:
        _blush(image, traits, p)
        draw = ImageDraw.Draw(image)
        for sign in (-1, 1):
            _eye(image, _s(512) + sign * _s(EYE_GAP), sign, traits, p)
        _brows(draw, traits, p)
        _nose(draw, traits)
        _mouth(draw, traits, p)
    return image.resize((base.CANVAS, base.CANVAS), Image.LANCZOS)


def anime_head_kit(look: dict[str, Any]) -> dict[str, Any]:
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
