"""Anime look for the blob face: tall eyes with a coloured iris and two highlights, a thick upper lash, thin brows,
a tiny nose, small mouths and a blush. Same kit shape as ``blob_face`` (8 poses, 9 mouths, blink, exact anchors);
only the drawing differs. Imported lazily by ``blob_face.face_kit`` when ``traits.style`` is ``anime``."""
from __future__ import annotations

from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from services import blob_face as base
from services.flat_rig import STATES

SC = base.SCALE
# Drawn for the wide cap (96 x 116 degrees, see ``blob_face_scene.ANIME_SPAN``) at the final size: no zoom.
# Eyes sit at 55 percent of the head height, the mouth at 74, and each eye is about a fifth of the head width.
ZOOM = 1.0
EYE_Y, EYE_GAP, EYE_RX, EYE_RY = 562, 232, 120, 150
NOSE_Y, MOUTH_Y, MOUTH_H = 668, 772, 250
BLUSH_Y, BLUSH_X = 752, 292
EYE_WHITE = (252, 250, 255, 255)
LASH_FLICK = 26
# pose: eye openness, pupil scale, brow height offset, brow tilt (+ inner end up), lid cover (0-1 from the top), shape
POSES: dict[str, dict[str, Any]] = {
    "neutral": {"open": 1.0, "pupil": 1.0, "brow_dy": 0, "tilt": 0.0, "lid": 0.0, "shape": "open", "mouth_dy": 0, "mouth_k": 1.0},
    "angry": {"open": 0.86, "pupil": 0.86, "brow_dy": 6, "tilt": -1.5, "lid": 0.0, "shape": "angry", "mouth_dy": 4, "mouth_k": 0.95},
    "surprised": {"open": 1.2, "pupil": 0.55, "brow_dy": -40, "tilt": 0.15, "lid": 0.0, "shape": "open", "mouth_dy": 6, "mouth_k": 1.05},
    "sad": {"open": 1.0, "pupil": 1.15, "brow_dy": 8, "tilt": 1.4, "lid": 0.0, "shape": "sad", "mouth_dy": 8, "mouth_k": 0.9},
    "happy": {"open": 1.0, "pupil": 1.0, "brow_dy": -16, "tilt": 0.5, "lid": 0.0, "shape": "arc", "mouth_dy": 0, "mouth_k": 1.05},
    "suspicious": {"open": 0.95, "pupil": 0.9, "brow_dy": 0, "tilt": -0.9, "lid": 0.42, "shape": "open", "mouth_dy": 4, "mouth_k": 0.9},
    "tired": {"open": 0.95, "pupil": 0.95, "brow_dy": 16, "tilt": 0.3, "lid": 0.58, "shape": "open", "mouth_dy": 8, "mouth_k": 0.85},
    "shout": {"open": 1.1, "pupil": 0.8, "brow_dy": -12, "tilt": -0.8, "lid": 0.0, "shape": "angry", "mouth_dy": -6, "mouth_k": 1.25},
}


def _s(value: float) -> float:
    return value * SC


def _shade(color: tuple[int, ...], k: float) -> tuple[int, int, int, int]:
    return (min(255, int(color[0] * k)), min(255, int(color[1] * k)), min(255, int(color[2] * k)), 255)


def layout(pose: str) -> dict[str, Any]:
    p = POSES[pose]
    mouth_y = MOUTH_Y + p["mouth_dy"]
    mouth_h = MOUTH_H * p["mouth_k"]
    return {"mouth": (512.0, 512.0 + (mouth_y - 512.0) * ZOOM, float(mouth_h * ZOOM))}


def _eye_box(cx: float, ry: float) -> tuple[float, float, float, float]:
    return (_s(cx - EYE_RX), _s(EYE_Y) - ry, _s(cx + EYE_RX), _s(EYE_Y) + ry)


def _clip(layer: Image.Image, mask: Image.Image) -> Image.Image:
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    out.paste(layer, (0, 0), mask)
    return out


def _iris(size: tuple[int, int], box: tuple[float, float, float, float], color: tuple[int, int, int, int], pupil: float) -> Image.Image:
    """Iris in three bands (dark top, base, light bottom), pupil, a big and a small highlight."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, y0 + h * 0.56
    iw, ih = w * 0.46, h * 0.46
    for k, (dy, hk) in zip((0.55, 1.0, 1.28), ((-0.08, 1.0), (0.0, 0.86), (0.2, 0.52))):
        draw.ellipse((cx - iw, cy - ih + ih * dy, cx + iw, cy + ih * hk + ih * dy), fill=_shade(color, k))
    pw, ph = iw * 0.46 * pupil, ih * 0.52 * pupil
    draw.ellipse((cx - pw, cy - ph * 0.9, cx + pw, cy + ph * 1.1), fill=base.INK)
    r1, r2 = iw * 0.34, iw * 0.15
    draw.ellipse((cx - iw * 0.52 - r1, cy - ih * 0.55 - r1, cx - iw * 0.52 + r1, cy - ih * 0.55 + r1), fill=EYE_WHITE)
    draw.ellipse((cx + iw * 0.42 - r2, cy + ih * 0.5 - r2, cx + iw * 0.42 + r2, cy + ih * 0.5 + r2), fill=EYE_WHITE)
    return layer


def _lash(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], sign: int, ink, width: float) -> None:
    """Thick upper lash along the top of the eye with an outward flick."""
    x0, y0, x1, y1 = box
    arc_box = (x0, y0, x1, y1 + (y1 - y0) * 0.1)
    draw.arc(arc_box, 195, 345, fill=ink, width=int(width))
    outer_x = x1 if sign > 0 else x0
    draw.line((outer_x - sign * _s(4), y0 + (y1 - y0) * 0.36, outer_x + sign * _s(LASH_FLICK), y0 + (y1 - y0) * 0.22), fill=ink, width=int(width * 0.8))


def _eye(layer: Image.Image, cx: float, sign: int, traits: dict[str, Any], p: dict[str, Any]) -> None:
    ink, ry = traits["ink"], _s(EYE_RY) * p["open"]
    box = _eye_box(cx, ry)
    draw = ImageDraw.Draw(layer)
    width = max(4, int(traits["line"] * SC * 0.5))
    if p["shape"] == "arc":
        draw.arc((box[0], box[1] + ry * 0.2, box[2], box[3] - ry * 0.2), 200, 340, fill=ink, width=int(width * 1.8))
        return
    mask = Image.new("L", layer.size, 0)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    eye = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(eye).ellipse(box, fill=EYE_WHITE)
    eye.alpha_composite(_clip(_iris(layer.size, box, traits["eye_color"], p["pupil"]), mask))
    cover = p["lid"] + (0.12 if p["shape"] == "angry" else 0.0)
    if cover:
        lid = ImageDraw.Draw(eye)
        cut = box[1] + (box[3] - box[1]) * cover
        lid.rectangle((box[0] - 4, box[1] - 4, box[2] + 4, cut), fill=traits["skin"])
    if p["shape"] in ("angry", "sad"):
        # A wedge of skin over one top corner makes the eye slant: the inner one for angry, the outer one for sad.
        top, h = box[1], box[3] - box[1]
        edge = (box[2] if sign < 0 else box[0]) if p["shape"] == "angry" else (box[0] if sign < 0 else box[2])
        far = edge + (box[0] - box[2] if edge == box[2] else box[2] - box[0]) * 0.9
        depth = 0.42 if p["shape"] == "angry" else 0.30
        ImageDraw.Draw(eye).polygon([(edge, top - 4), (far, top - 4), (edge, top + h * depth)], fill=traits["skin"])
    layer.alpha_composite(_clip(eye, mask))
    draw.ellipse(box, outline=_shade(ink, 1.0), width=max(3, width))
    _lash(draw, box, sign, ink, width * 3.4)
    if p["shape"] == "sad":
        tx, ty = (box[0] + box[2]) / 2 + sign * _s(8), box[3] + _s(6)
        draw.ellipse((tx - _s(7), ty, tx + _s(7), ty + _s(30)), fill=(176, 214, 245, 255), outline=ink, width=max(2, width // 3))


def _brows(draw: ImageDraw.ImageDraw, traits: dict[str, Any], p: dict[str, Any]) -> None:
    if traits["brows"]["style"] == "none":
        return
    thick = max(3, int(traits["brows"]["thickness"] * SC * (0.62 if traits["brows"]["style"] == "thin" else 0.9)))
    y = _s(EYE_Y - EYE_RY - 38 + p["brow_dy"])
    radius = _s(EYE_RX)
    for sign in (-1, 1):
        cx = _s(512) + sign * _s(EYE_GAP)
        outer, inner = cx + sign * radius * 1.05, cx - sign * radius * 0.8
        tilt = p["tilt"] * radius * 0.55
        mid = ((outer + inner) / 2, y - _s(7) - abs(tilt) * 0.2)
        draw.line((outer, y + tilt * 0.35, mid[0], mid[1], inner, y - tilt), fill=traits["ink"], width=thick, joint="curve")


def _nose(draw: ImageDraw.ImageDraw, traits: dict[str, Any]) -> None:
    if traits["nose"] == "none":
        return
    tone = _shade(traits["skin"], 0.72)
    cx, y = _s(512), _s(NOSE_Y)
    draw.line((cx - _s(5), y, cx + _s(2), y + _s(16), cx + _s(10), y + _s(14)), fill=tone, width=max(3, int(SC * 3.2)), joint="curve")


def _blush(image: Image.Image, traits: dict[str, Any]) -> None:
    if not traits["blush"]:
        return
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for sign in (-1, 1):
        cx, y = _s(512) + sign * _s(BLUSH_X), _s(BLUSH_Y)
        draw.ellipse((cx - _s(96), y - _s(42), cx + _s(96), y + _s(42)), fill=(255, 128, 138, 120))
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(_s(14))))


def draw_pose(traits: dict[str, Any], pose: str, *, lids_only: bool = False) -> Image.Image:
    p = POSES[pose]
    image = Image.new("RGBA", (base.CANVAS * SC, base.CANVAS * SC), (0, 0, 0, 0))
    if lids_only:
        _lids(image, traits, p)
    else:
        _blush(image, traits)
        draw = ImageDraw.Draw(image)
        for sign in (-1, 1):
            _eye(image, 512 + sign * EYE_GAP, sign, traits, p)
        _brows(draw, traits, p)
        _nose(draw, traits)
        if traits["glasses"] != "none":
            _glasses(draw, traits)
    return image.resize((base.CANVAS, base.CANVAS), Image.LANCZOS)


def _glasses(draw: ImageDraw.ImageDraw, traits: dict[str, Any]) -> None:
    width = max(4, int(traits["line"] * SC * 0.5))
    for sign in (-1, 1):
        cx = _s(512) + sign * _s(EYE_GAP)
        box = (cx - _s(EYE_RX * 1.4), _s(EYE_Y - EYE_RY * 1.12), cx + _s(EYE_RX * 1.4), _s(EYE_Y + EYE_RY * 1.12))
        if traits["glasses"] == "square":
            draw.rounded_rectangle(box, radius=int(_s(18)), outline=traits["ink"], width=width)
        else:
            draw.ellipse(box, outline=traits["ink"], width=width)
    draw.line((_s(512) - _s(EYE_GAP - EYE_RX * 1.4), _s(EYE_Y), _s(512) + _s(EYE_GAP - EYE_RX * 1.4), _s(EYE_Y)), fill=traits["ink"], width=width)


def _lids(image: Image.Image, traits: dict[str, Any], p: dict[str, Any]) -> None:
    """Opaque lids over the open eyes (skin colour) and a closed lash line, so a blink hides iris and whites."""
    width = max(4, int(traits["line"] * SC * 0.5))
    skin = tuple(traits["skin"][:3])
    # The lid patch fades out at its rim. A flat decal is a little brighter or darker than the shaded head, and a hard edge shows it.
    patch = Image.new("RGBA", image.size, (*skin, 0))
    pdraw = ImageDraw.Draw(patch)
    for sign in (-1, 1):
        box = _eye_box(512 + sign * EYE_GAP, _s(EYE_RY) * 1.08)
        pdraw.ellipse((box[0] - _s(4), box[1] - _s(4), box[2] + _s(4), box[3] + _s(4)), fill=(*skin, 255))
    patch = patch.filter(ImageFilter.GaussianBlur(_s(5)))
    image.alpha_composite(patch)
    draw = ImageDraw.Draw(image)
    for sign in (-1, 1):
        box = _eye_box(512 + sign * EYE_GAP, _s(EYE_RY) * 1.08)
        cy = _s(EYE_Y) + _s(EYE_RY) * 0.18
        draw.arc((box[0], cy - _s(26), box[2], cy + _s(26)), 20, 160, fill=traits["ink"], width=int(width * 1.7))


def _mouth_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (512 * 4, 320 * 4), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


MOUTH_GAIN = 2.4


def _pt(x: float, y: float) -> tuple[float, float]:
    """Sprite point, supersampled 4x. Small anime mouths vanish at video size, so shapes are drawn 2.4x."""
    return (256 + x * MOUTH_GAIN) * 4, (160 + y * MOUTH_GAIN) * 4


def _shape(draw: ImageDraw.ImageDraw, points, fill, outline, width) -> None:
    draw.polygon([_pt(x, y) for x, y in points], fill=fill)
    draw.line([_pt(x, y) for x, y in points + [points[0]]], fill=outline, width=width, joint="curve")


def _bowl(hw: float, top: float, bottom: float, flat: float = 3.0) -> list[tuple[float, float]]:
    """An open mouth: a flat upper lip that dips a little at the corners, a rounded lower edge."""
    pts = [(-hw + 2 * hw * i / 24, top + flat * ((i - 12) / 12) ** 2) for i in range(25)]
    depth = bottom - top
    for i in range(24, -1, -1):
        u = (i - 12) / 12
        pts.append((u * hw, top + depth * (1 - abs(u) ** 2.4) ** 0.5))
    return pts


def anime_mouths(traits: dict[str, Any]) -> dict[str, Image.Image]:
    ink = traits["ink"]
    inner, tongue, teeth, lip = (150, 52, 66, 255), (240, 126, 138, 255), (255, 252, 250, 255), (232, 138, 146, 255)
    line = 9
    out: dict[str, Image.Image] = {}
    for state in STATES:
        image, draw = _mouth_canvas()
        if state == "closed":
            draw.line([_pt(x, 4 * ((x / 34) ** 2) - 2) for x in range(-34, 35, 2)], fill=ink, width=line * 4 // 2 + 6, joint="curve")
        elif state == "pressed":
            draw.line([_pt(-26, 0), _pt(26, 0)], fill=ink, width=line * 4 // 2 + 10)
        elif state == "small":
            _shape(draw, _bowl(30, -8, 12, 1.5), inner, ink, line * 2)
            draw.rectangle([*_pt(-22, -7), *_pt(22, -2)], fill=teeth)
        elif state == "medium":
            _shape(draw, _bowl(38, -14, 22, 2.0), inner, ink, line * 2)
            draw.rectangle([*_pt(-30, -13), *_pt(30, -5)], fill=teeth)
            draw.ellipse([*_pt(-18, 8), *_pt(18, 24)], fill=tongue)
        elif state == "wide":
            _shape(draw, _bowl(54, -22, 40, 3.0), inner, ink, line * 2)
            draw.rectangle([*_pt(-44, -21), *_pt(44, -8)], fill=teeth)
            draw.ellipse([*_pt(-30, 14), *_pt(30, 44)], fill=tongue)
        elif state == "round":
            draw.ellipse([*_pt(-24, -30), *_pt(24, 32)], fill=inner, outline=ink, width=line * 2)
            draw.ellipse([*_pt(-12, 6), *_pt(12, 26)], fill=tongue)
        elif state == "pucker":
            draw.ellipse([*_pt(-15, -15), *_pt(15, 15)], fill=inner, outline=ink, width=line * 2)
        elif state == "bite":
            draw.rectangle([*_pt(-34, -12), *_pt(34, 4)], fill=teeth, outline=ink, width=line)
            draw.pieslice([*_pt(-30, -2), *_pt(30, 30)], 0, 180, fill=lip, outline=ink, width=line)
        else:  # tongue
            _shape(draw, _bowl(34, -12, 20, 2.0), inner, ink, line * 2)
            draw.rectangle([*_pt(-26, -11), *_pt(26, -4)], fill=teeth)
            draw.ellipse([*_pt(-14, -6), *_pt(14, 18)], fill=tongue)
        out[state] = image.resize((512, 320), Image.LANCZOS)
    return out


def anime_kit(look: dict[str, Any]) -> dict[str, Any]:
    poses = {pose: draw_pose(look, pose) for pose in base.POSES}
    blinks = {pose: draw_pose(look, pose, lids_only=True) for pose in base.POSES}
    mouths = anime_mouths(look)
    anchors, placed_all = {}, {}
    eyes = base._anchor(512, 512, base.CANVAS, base.CANVAS, base.CANVAS)
    for pose in base.POSES:
        placed = layout(pose)
        anchors[pose] = {"mouth": base._anchor(*placed["mouth"], base.CANVAS, base.CANVAS), "eyes": dict(eyes)}
        placed_all[pose] = {"mouth": placed["mouth"], "eyes": (512, 512, base.CANVAS)}
    return {"traits": look, "poses": poses, "blinks": blinks, "mouths": mouths, "anchors": anchors, "layout": placed_all,
            "mouthMapping": dict(base.MAPPING), "preview": base._sheet(poses, mouths, anchors)}
