"""A parametric 2D face for a semi-3D blob, drawn as a Character Kit.

The eyes, brows, nose, moustache and glasses are painted here, so the mouth and blink anchors are the
pixels that were drawn (``flat_rig_base._anchor``). The nine mouths are ``flat_rig.draw_mouth`` with
``rig_style`` for paper or ink, then tinted to the face's ink. Nothing is detected.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from services.character_kit_library import patch_character_kit, read_character_kit_library
from services.flat_rig import MAPPING, STATES, _save, _url, draw_mouth
from services.flat_rig_base import INK, _anchor
from services.flat_rig_look import rig_style

CANVAS = 1024
SCALE = 4
# The features are drawn at design size and the whole face is magnified about its centre, so the eyes and mouth fill the head.
ZOOM = 1.45
POSES = ("neutral", "angry", "surprised", "sad", "happy", "suspicious", "tired", "shout")
# brow dy (px), tilt (inner end; negative pulls it down), eye opening, mouth dy, mouth height scale
EXPRESSIONS = {
    "neutral": (0, 0.0, 1.0, 0, 1.0),
    "angry": (-8, -1.5, 0.7, 8, 1.02),
    "surprised": (-54, 0.35, 1.5, -8, 1.12),
    "sad": (22, 1.4, 0.8, 14, 0.96),
    "happy": (-26, 0.7, 0.85, -6, 1.06),
    "suspicious": (-4, -1.2, 0.5, 6, 0.94),
    "tired": (26, 0.3, 0.42, 18, 0.92),
    "shout": (-34, -0.7, 1.3, -12, 1.28),
}
EYE_Y, EYE_GAP, EYE_R = 392, 156, 62
# Mouth height leaves the medium opening (the hole, not the ink) at least 40 px on a 1024 face, including the smaller expressions.
NOSE_Y, MOUTH_Y, MOUTH_H = 520, 700, 340
EYE_SHAPES = ("dot", "oval", "halflid", "wide")
BROW_STYLES = ("thick", "thin", "none")
NOSES = ("none", "dot", "line", "bulb")
MOUSTACHES = ("none", "walrus", "pencil", "handlebar")
GLASSES = ("none", "round", "square")
MOUTH_LOOKS = ("paper", "ink")
STYLES = ("blob", "anime")
FRECKLES = ((-70, 28), (-54, 44), (-86, 48), (62, 30), (78, 46), (48, 52), (-40, 60), (36, 64))
STUBBLE = tuple((x, y) for x in range(-40, 41, 10) for y in (8, 20, 32))
WHITE = (250, 248, 242, 255)
SKIN = (243, 210, 181, 255)


class BlobFaceError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        self.code, self.status = code, status
        super().__init__(message)


def _choice(value: Any, allowed: tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise BlobFaceError("invalid_traits", f"{label} must be one of {', '.join(allowed)}")
    return str(value)


def _color(value: Any, label: str, default: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if value is None:
        return default
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        raise BlobFaceError("invalid_traits", f"{label} must be #rrggbb")
    try:
        rgb = tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))
    except ValueError as error:
        raise BlobFaceError("invalid_traits", f"{label} must be #rrggbb") from error
    return (rgb[0], rgb[1], rgb[2], 255)


def _number(value: Any, label: str, low: float, high: float, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= float(value) <= high:
        raise BlobFaceError("invalid_traits", f"{label} must be a number from {low:g} to {high:g}")
    return float(value)


def _eyes_trait(raw: Any) -> dict[str, Any]:
    eyes = {"shape": raw} if isinstance(raw, str) else raw
    if not isinstance(eyes, dict):
        raise BlobFaceError("invalid_traits", "eyes must be a shape or an object")
    gap = eyes.get("separation", eyes.get("gap"))
    return {"shape": _choice(eyes.get("shape", "oval"), EYE_SHAPES, "eyes"),
            "size": _number(eyes.get("size"), "eyes.size", 0.4, 2.2, 1),
            "separation": _number(gap, "eyes.separation", 0.6, 1.8, 1)}


def _group(raw: Any, label: str, allowed: tuple[str, ...], default: str) -> dict[str, Any]:
    group = {"style": raw} if isinstance(raw, str) else raw
    if not isinstance(group, dict):
        raise BlobFaceError("invalid_traits", f"{label} must be a style or an object")
    return group | {"style": _choice(group.get("style", default), allowed, label)}


def face_traits(value: Any) -> dict[str, Any]:
    """The drawing knobs. A string is the style; unknown styles are rejected."""
    raw = value if isinstance(value, dict) else {}
    brows = _group(raw.get("brows", "thin"), "brows", BROW_STYLES, "thin")
    moustache = _group(raw.get("moustache", "none"), "moustache", MOUSTACHES, "none")
    return {
        "eyes": _eyes_trait(raw.get("eyes", "oval")),
        "brows": {**brows, "thickness": _number(brows.get("thickness"), "brows.thickness", 1, 32, 20)},
        "nose": _choice(raw.get("nose", "dot"), NOSES, "nose"),
        "moustache": {**moustache, "color": _color(moustache.get("color"), "moustache.color", (58, 36, 24, 255))},
        "glasses": _choice(raw.get("glasses", "none"), GLASSES, "glasses"),
        "freckles": raw.get("freckles") is True, "stubble": raw.get("stubble") is True,
        "ink": _color(raw.get("ink"), "ink", INK), "line": _number(raw.get("line"), "line", 2, 28, 14),
        "mouth": _choice(raw.get("mouth", "paper"), MOUTH_LOOKS, "mouth"),
        "skin": _color(raw.get("skin"), "skin", SKIN),
        "style": _choice(raw.get("style", "blob"), STYLES, "style"),
        "eye_color": _color(raw.get("eyeColor"), "eyeColor", (74, 128, 214, 255)),
        "blush": raw.get("blush") is True if "blush" in raw else raw.get("style") == "anime",
    }


def _hex(color: tuple[int, int, int, int]) -> str:
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"


def public_traits(traits: dict[str, Any]) -> dict[str, Any]:
    """Traits as JSON: colours are ``#rrggbb``."""
    look = face_traits(traits) if "eyes" not in traits or isinstance(traits.get("eyes"), str) else traits
    if "ink" in look and isinstance(look["ink"], str):
        look = face_traits(traits)
    return {
        "eyes": dict(look["eyes"]), "brows": {"style": look["brows"]["style"], "thickness": look["brows"]["thickness"]},
        "nose": look["nose"], "moustache": {"style": look["moustache"]["style"], "color": _hex(look["moustache"]["color"])},
        "glasses": look["glasses"], "freckles": look["freckles"], "stubble": look["stubble"],
        "ink": _hex(look["ink"]), "line": look["line"], "mouth": look["mouth"], "skin": _hex(look["skin"]),
        "style": look["style"], "eyeColor": _hex(look["eye_color"]), "blush": look["blush"],
    }


def _layout(traits: dict[str, Any], pose: str) -> dict[str, Any]:
    brow_dy, tilt, eye_open, mouth_dy, mouth_scale = EXPRESSIONS[pose]
    mouth_h = MOUTH_H * mouth_scale
    mouth_y = MOUTH_Y + mouth_dy
    return {"gap": EYE_GAP * traits["eyes"]["separation"], "radius": EYE_R * traits["eyes"]["size"],
            "eye_open": eye_open, "brow_dy": brow_dy, "tilt": tilt, "nose_y": NOSE_Y,
            "mouth_y": mouth_y, "mouth_h": mouth_h,
            "mouth": (512.0, 512.0 + (mouth_y - 512.0) * ZOOM, float(mouth_h * ZOOM))}


def _s(value: float) -> float:
    return value * SCALE


def _eyes(draw: ImageDraw.ImageDraw, traits: dict[str, Any], layout: dict[str, Any]) -> None:
    shape, ink, line = traits["eyes"]["shape"], traits["ink"], max(2, int(traits["line"] * SCALE))
    radius, open_scale, y = _s(layout["radius"]), layout["eye_open"], _s(EYE_Y)
    for sign in (-1, 1):
        cx = _s(512 + sign * layout["gap"])
        rw, rh = radius, radius * open_scale
        if shape == "wide":
            rw, rh = rw * 1.12, rh * 1.2
        if shape == "halflid":
            rh *= 0.62
        if shape == "dot":
            draw.ellipse((cx - radius * 0.45, y - radius * 0.45, cx + radius * 0.45, y + radius * 0.45), fill=ink)
            continue
        draw.ellipse((cx - rw, y - rh, cx + rw, y + rh), fill=WHITE, outline=ink, width=line)
        pupil = radius * 0.38
        draw.ellipse((cx - pupil, y - pupil, cx + pupil, y + pupil), fill=ink)
        if shape == "halflid":
            draw.rectangle((cx - rw, y - rh - line, cx + rw, y - rh * 0.15), fill=ink)


def _brows(draw: ImageDraw.ImageDraw, traits: dict[str, Any], layout: dict[str, Any]) -> None:
    if traits["brows"]["style"] == "none":
        return
    thick = traits["brows"]["thickness"] * (1 if traits["brows"]["style"] == "thick" else 0.45)
    width, radius = max(2, int(thick * SCALE)), _s(layout["radius"])
    y, tilt = _s(EYE_Y - layout["radius"] - 18 + layout["brow_dy"]), layout["tilt"] * radius
    for sign in (-1, 1):
        cx = _s(512) + sign * _s(layout["gap"])
        outer, inner = cx + sign * radius * 1.15, cx - sign * radius * 1.05
        draw.line((outer, y + tilt * 0.25, inner, y - tilt), fill=traits["ink"], width=width)


def _nose(draw: ImageDraw.ImageDraw, traits: dict[str, Any], layout: dict[str, Any]) -> None:
    kind = traits["nose"]
    if kind == "none":
        return
    cx, y, radius = _s(512), _s(layout["nose_y"]), _s(22)
    line = max(2, int(traits["line"] * SCALE * 0.6))
    if kind == "dot":
        draw.ellipse((cx - radius * 0.45, y - radius * 0.35, cx + radius * 0.45, y + radius * 0.35), fill=traits["ink"])
    elif kind == "bulb":
        draw.ellipse((cx - radius, y - radius * 0.7, cx + radius, y + radius * 0.8), outline=traits["ink"], width=line)
    else:
        draw.line((cx, y - radius, cx, y + radius), fill=traits["ink"], width=line)


def _moustache(draw: ImageDraw.ImageDraw, traits: dict[str, Any], layout: dict[str, Any]) -> None:
    kind = traits["moustache"]["style"]
    if kind == "none":
        return
    color, y = traits["moustache"]["color"], _s(layout["nose_y"]) + _s(16)
    mouth_top = _s(layout["mouth_y"] - layout["mouth_h"] / 2) - _s(8)
    bottom, cx, width = min(y + _s(26), mouth_top), _s(512), _s(78)
    if bottom <= y + _s(4):
        bottom = y + _s(8)
    pen = max(2, int(4 * SCALE))
    if kind == "pencil":
        draw.line((cx - width * 0.55, y, cx + width * 0.55, y), fill=color, width=max(2, int(2.5 * SCALE)))
    elif kind == "handlebar":
        draw.arc((cx - width, y - _s(8), cx - _s(6), bottom + _s(10)), 200, 20, fill=color, width=pen)
        draw.arc((cx + _s(6), y - _s(8), cx + width, bottom + _s(10)), 160, 340, fill=color, width=pen)
    else:
        # The mouth sprite is tall, so clamping to its box reduced a walrus to a dash. Draw the walrus itself;
        # the mouth overlay covers only its own ink.
        # Two fat lobes that droop at the ends, with a notch in the middle: a walrus, not a bar.
        for sign in (-1, 1):
            for x0, y0, x1, y1 in ((_s(-4), y, _s(150), y + _s(70)), (_s(118), y + _s(20), _s(168), y + _s(78))):
                lo, hi = sorted((cx + sign * x0, cx + sign * x1))
                draw.ellipse((lo, y0, hi, y1), fill=color)


def _glasses(draw: ImageDraw.ImageDraw, traits: dict[str, Any], layout: dict[str, Any]) -> None:
    kind = traits["glasses"]
    if kind == "none":
        return
    line, radius = max(2, int(traits["line"] * SCALE * 0.7)), _s(layout["radius"]) * 1.55
    y, gap = _s(EYE_Y), _s(layout["gap"])
    for sign in (-1, 1):
        cx = _s(512) + sign * gap
        box = (cx - radius, y - radius * 0.82, cx + radius, y + radius * 0.82)
        if kind == "round":
            draw.ellipse(box, outline=traits["ink"], width=line)
        else:
            draw.rounded_rectangle(box, radius=max(1, int(_s(6))), outline=traits["ink"], width=line)
    bridge = gap - radius
    if bridge > _s(4):
        draw.line((_s(512) - bridge, y, _s(512) + bridge, y), fill=traits["ink"], width=line)


def _freckles(draw: ImageDraw.ImageDraw, traits: dict[str, Any], layout: dict[str, Any]) -> None:
    del layout
    if not traits["freckles"]:
        return
    for dx, dy in FRECKLES:
        cx, cy = _s(512 + dx), _s(EYE_Y + 36 + dy * 0.15)
        draw.ellipse((cx - _s(2.5), cy - _s(2), cx + _s(2.5), cy + _s(2)), fill=traits["ink"])


def _stubble(draw: ImageDraw.ImageDraw, traits: dict[str, Any], layout: dict[str, Any]) -> None:
    if not traits["stubble"]:
        return
    color = (*traits["ink"][:3], 170)
    top = _s(layout["mouth_y"] + layout["mouth_h"] / 2) + _s(6)
    for dx, dy in STUBBLE:
        x, y = _s(512 + dx), top + _s(dy)
        draw.line((x, y, x + _s(1), y + _s(5)), fill=color, width=max(1, SCALE // 2))


def _lids(draw: ImageDraw.ImageDraw, traits: dict[str, Any], layout: dict[str, Any]) -> None:
    """Opaque lids the size of the open eyes, so a blink covers the whites and the head reads as closed."""
    radius = _s(layout["radius"]) * (1.25 if traits["eyes"]["shape"] == "wide" else 1.08)
    y, gap, line = _s(EYE_Y), _s(layout["gap"]), max(2, int(traits["line"] * SCALE))
    for sign in (-1, 1):
        cx = _s(512) + sign * gap
        rw, rh = radius, radius * (1.15 if traits["eyes"]["shape"] != "dot" else 0.7)
        draw.ellipse((cx - rw, y - rh, cx + rw, y + rh), fill=traits["skin"])
        draw.arc((cx - rw * 0.9, y - rh * 0.2, cx + rw * 0.9, y + rh * 0.7), 200, 340, fill=traits["ink"], width=line)


def _draw_pose(traits: dict[str, Any], pose: str, *, lids_only: bool = False) -> Image.Image:
    image = Image.new("RGBA", (CANVAS * SCALE, CANVAS * SCALE), (0, 0, 0, 0))
    draw, layout = ImageDraw.Draw(image), _layout(traits, pose)
    if lids_only:
        _lids(draw, traits, layout)
    else:
        _freckles(draw, traits, layout)
        _eyes(draw, traits, layout)
        _brows(draw, traits, layout)
        _nose(draw, traits, layout)
        _moustache(draw, traits, layout)
        _glasses(draw, traits, layout)
        _stubble(draw, traits, layout)
    big = image.resize((round(CANVAS * ZOOM),) * 2, Image.LANCZOS)
    margin = (big.width - CANVAS) // 2
    return big.crop((margin, margin, margin + CANVAS, margin + CANVAS))


def _near_ink(pixel: tuple[int, int, int, int]) -> bool:
    return pixel[3] >= 8 and (pixel[0] - INK[0]) ** 2 + (pixel[1] - INK[1]) ** 2 + (pixel[2] - INK[2]) ** 2 < 48 ** 2


def _thicken_ink(image: Image.Image, radius: int) -> Image.Image:
    mask, source = Image.new("L", image.size, 0), image.load()
    target = mask.load()
    for y in range(image.height):
        for x in range(image.width):
            if _near_ink(source[x, y]):
                target[x, y] = 255
    grown, out = mask.filter(ImageFilter.MaxFilter(radius * 2 + 1)).load(), image.copy()
    pixels = out.load()
    for y in range(out.height):
        for x in range(out.width):
            if grown[x, y] and pixels[x, y][3] < 8:
                pixels[x, y] = INK
    return out


def _recolor(image: Image.Image, ink: tuple[int, int, int, int]) -> Image.Image:
    out = image.copy()
    pixels = out.load()
    for y in range(out.height):
        for x in range(out.width):
            pixel = pixels[x, y]
            if _near_ink(pixel):
                pixels[x, y] = (*ink[:3], pixel[3])
    return out


def _mouths(traits: dict[str, Any]) -> dict[str, Image.Image]:
    paper = traits["mouth"] == "paper"
    style = rig_style({"mouthStyle": traits["mouth"], "smile": 0.2 if paper else 0.0, "width": 0.7 if paper else 0.55})
    extra = max(int(traits["line"] - 10), 8)
    drawn = {}
    for state in STATES:
        image = draw_mouth(state, style)
        if extra:
            image = _thicken_ink(image, max(1, extra // 3 + 1))
        drawn[state] = _recolor(image, traits["ink"])
    return drawn


def paste_anchor(canvas: Image.Image, sprite: Image.Image, anchor: dict[str, float]) -> None:
    """Paint ``sprite`` where a talking cutout would (height = scale × the longer edge)."""
    edge = max(canvas.size)
    height = anchor["scale"] * edge
    width = height * sprite.width / max(1, sprite.height)
    x = canvas.width / 2 + anchor["offsetX"] * edge / 100 - width / 2
    y = canvas.height / 2 + anchor["offsetY"] * edge / 100 - height / 2
    resized = sprite.resize((max(1, int(round(width))), max(1, int(round(height)))), Image.LANCZOS)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(resized, (int(round(x)), int(round(y))))
    canvas.alpha_composite(layer)


def composite_mouth(pose: Image.Image, mouth: Image.Image, anchor: dict[str, float]) -> Image.Image:
    shot = pose.copy()
    paste_anchor(shot, mouth, anchor)
    return shot


def _sheet(poses: dict[str, Image.Image], mouths: dict[str, Image.Image], anchors: dict[str, dict]) -> Image.Image:
    cell, sheet = CANVAS // 4, Image.new("RGBA", (CANVAS, CANVAS // 2), (0, 0, 0, 0))
    for index, pose in enumerate(POSES):
        shot = composite_mouth(poses[pose], mouths["closed"], anchors[pose]["mouth"])
        sheet.paste(shot.resize((cell, cell), Image.LANCZOS), ((index % 4) * cell, (index // 4) * cell))
    return sheet


def face_kit(traits: Any) -> dict[str, Any]:
    """Images, exact anchors and the pixel layout. Nothing is written."""
    look = face_traits(traits)
    if look["style"] == "anime":
        from services.blob_face_anime import anime_kit
        return anime_kit(look)
    poses = {pose: _draw_pose(look, pose) for pose in POSES}
    blinks = {pose: _draw_pose(look, pose, lids_only=True) for pose in POSES}
    mouths = _mouths(look)
    anchors, layout = {}, {}
    eyes = _anchor(512, 512, CANVAS, CANVAS, CANVAS)
    for pose in POSES:
        placed = _layout(look, pose)
        anchors[pose] = {"mouth": _anchor(*placed["mouth"], CANVAS, CANVAS), "eyes": dict(eyes)}
        layout[pose] = {"mouth": placed["mouth"], "eyes": (512, 512, CANVAS)}
    return {"traits": look, "poses": poses, "blinks": blinks, "mouths": mouths, "anchors": anchors,
            "layout": layout, "mouthMapping": dict(MAPPING), "preview": _sheet(poses, mouths, anchors)}


def _kit_token(look: dict[str, Any], kit_id: str | None) -> str:
    if kit_id:
        return str(kit_id)
    payload = json.dumps(public_traits(look), sort_keys=True, separators=(",", ":"))
    return "blob-" + hashlib.sha256(payload.encode()).hexdigest()[:12]


def _asset(kit_id: str, title: str, label: str, image: Image.Image, workspace_dir: str, workspace: str,
           kind: str, width: int, height: int) -> dict[str, Any]:
    file = _save(image, workspace_dir, f"kit-{kit_id}-{label}")
    return {"id": f"{kit_id}-{label}"[:120], "name": f"{title} {label}"[:240], "source": _url(file, workspace),
            "kind": kind, "alphaStatus": "transparent", "reviewState": "approved", "workspace": workspace,
            "width": width, "height": height}


def save_face_kit(workspace_dir: str, workspace: str, traits: Any, *, name: str | None = None,
                  kit_id: str | None = None, base_revision: int | None = None) -> dict[str, Any]:
    """Write the face and store it with ``patch_character_kit``. The same traits keep the same kit id."""
    made = face_kit(traits)
    look, token = made["traits"], _kit_token(made["traits"], kit_id)
    title = (name or "Blob face").strip()[:240] or "Blob face"
    if base_revision is None:
        base_revision = int(read_character_kit_library(workspace_dir)["revision"])
    poses, anchors = {}, {}
    blink_neutral = None
    for pose, image in made["poses"].items():
        poses[pose] = _asset(token, title, pose, image, workspace_dir, workspace, "image", CANVAS, CANVAS)
        blink = _asset(token, title, f"{pose}-blink", made["blinks"][pose], workspace_dir, workspace, "overlay", CANVAS, CANVAS)
        anchors[pose] = {**made["anchors"][pose], "blinkSource": blink["source"]}
        if pose == "neutral":
            blink_neutral = blink
    anchors["base"] = dict(anchors["neutral"])
    mouth = {state: _asset(token, title, f"mouth-{state}", image, workspace_dir, workspace, "overlay", 512, 320)
             for state, image in made["mouths"].items()}
    kit = {"version": 1, "id": token, "name": title, "style": "cutout", "base": poses["neutral"], "poses": poses,
           "mouth": mouth, "eyes": {"blink": blink_neutral}, "anchors": anchors, "mouthMapping": dict(MAPPING),
           "provenance": [{"method": "blob-face", "traits": public_traits(look)}]}
    saved = patch_character_kit(workspace_dir, token, kit, base_revision=base_revision)
    preview = _url(_save(made["preview"], workspace_dir, f"kit-{token}-preview"), workspace)
    return {"kit_id": token, "poses": list(POSES), "preview": preview, "revision": saved["revision"],
            "character": saved["kits"][token]}
