"""A painted bald face (a Qwen picture) as the base of an ``anime_head`` kit: the ``qwen`` face source.

The picture is keyed by the caller (``image.remove_background``) and read here: its anime landmarks give the eye
centres and the mouth; the picture is scaled and moved so they land on the ``anime_head`` layout (eye line, eye
gap, mouth), and the skull box of that layout is the kit's ``fit``. The eleven expressions keep the painted
eyes: a measured drift of 1–3 % and a ±35 % eye size between separately edited pictures reads as a different
person, so the expressions are overlays on one picture instead: the painted brows are covered with skin and
redrawn (tapered, tilted per pose), lids close over the painted eyes (a happy arc, half lids, angry and sad
wedges, the blink), tears, blush and the rest mouth come from the programmatic drawer. The mouth visemes are the
same nine sprites. Same kit shape, same anchors, same ``fit``: ``world3d.scene.face`` cannot tell the sources apart.
"""
from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from services import blob_face as base
from services.blob_face_anime import _shade, anime_mouths
from services.blob_face_anime_head import (
    EYE_GAP, EYE_RX, EYE_RY, EYE_Y, MOUTH_Y, SHAPES, _blush, _brows, _lids, _mouth, _opening, _quad, _s, layout,
)
from services.blob_face_head import FIT, POSES, TAPER

SC = base.SCALE


class QwenFaceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _points(image: Image.Image) -> list | None:
    from services.anime_face_landmarks import detect

    found = detect(image)
    return found["points"] if found and found.get("points") else None


def _prior(image: Image.Image) -> dict[str, Any]:
    """Where a bald front-facing head keeps its features, from the silhouette alone: the eye line is the skull's widest
    row, the chin is where the width falls to the neck, the mouth sits a fifth of the way back up from the chin."""
    import numpy as np

    alpha = np.asarray(image.convert("RGBA"))[:, :, 3] > 128
    rows = np.where(alpha.any(axis=1))[0]
    if rows.size == 0:
        raise QwenFaceError("face_not_found", "The picture is empty")
    top = int(rows[0])
    widths = alpha.sum(axis=1)
    widest = int(np.argmax(widths[top: top + int(alpha.shape[0] * 0.6)]) + top)
    width = float(widths[widest])
    below = np.where(widths[widest:] < width * 0.62)[0]
    chin = int(widest + below[0]) if below.size else int(widest + (widest - top) * 1.1)
    cols = np.where(alpha[widest])[0]
    cx = float((cols[0] + cols[-1]) / 2)
    head_h = float(chin - top)
    # a bald skull is widest above the eyes: the eye line is about 0.7 of the way from the crown to the chin
    eye_y = top + head_h * 0.7
    mouth_y = top + head_h * 0.9
    eye_w, eye_h, gap = width * 0.24, head_h * 0.13, width * 0.19
    boxes = {"left_box": (cx - gap - eye_w / 2, eye_y - eye_h / 2, cx - gap + eye_w / 2, eye_y + eye_h / 2),
             "right_box": (cx + gap - eye_w / 2, eye_y - eye_h / 2, cx + gap + eye_w / 2, eye_y + eye_h / 2),
             "mouth_box": (cx - width * 0.08, mouth_y - head_h * 0.025, cx + width * 0.08, mouth_y + head_h * 0.025)}
    return {"left": (cx - gap, eye_y), "right": (cx + gap, eye_y), "mouth": (cx, mouth_y), "brow_y": eye_y - eye_h * 1.1, **boxes}


def _whites(image: Image.Image) -> dict[str, Any]:
    """Without landmarks: the silhouette prior, refined by the flat rig's hinted eye and mouth search when it finds them."""
    import numpy as np
    from services.flat_rig import find_mouth
    from services.flat_rig_eyes import find_eyes

    prior = _prior(image)
    rgba = np.asarray(image.convert("RGBA"))
    rgb, alpha = rgba[:, :, :3], rgba[:, :, 3]
    found = dict(prior)
    try:
        pair, _mask = find_eyes(rgb, alpha, near=((prior["left"][0] + prior["right"][0]) / 2, prior["left"][1]))
        x0, y0, x1, y1 = [float(v) for v in pair]
        mid, eye_h = (x0 + x1) / 2, y1 - y0
        prior_pair = (prior["right_box"][2] - prior["left_box"][0])
        # a pair the rig found is trusted only when it is the eyes the prior expects, not two highlights inside one eye
        if 0.7 < (x1 - x0) / max(1.0, prior_pair) < 1.35 and eye_h >= alpha.shape[0] * 0.03:
            found.update({"left_box": (x0, y0, mid - eye_h * 0.1, y1), "right_box": (mid + eye_h * 0.1, y0, x1, y1),
                          "left": ((x0 + mid) / 2, (y0 + y1) / 2), "right": ((mid + x1) / 2, (y0 + y1) / 2), "brow_y": y0 - eye_h * 0.55})
            try:
                mouth_box, _mmask, _bg = find_mouth(rgb, alpha, pair, near=prior["mouth"])
                mx0, my0, mx1, my1 = [float(v) for v in mouth_box]
                if abs((my0 + my1) / 2 - prior["mouth"][1]) < eye_h * 2.5:
                    found.update({"mouth": ((mx0 + mx1) / 2, (my0 + my1) / 2), "mouth_box": (mx0, my0, mx1, my1)})
            except Exception:
                pass
    except Exception:
        pass
    return found


def measure(image: Image.Image) -> dict[str, Any]:
    """Eye centres, eye boxes, brow line and mouth centre of the painted face, in picture pixels: the anime landmarks
    when the component is installed, else the flat rig's white-of-the-eyes search."""
    pts = _points(image)
    if pts is None:
        return _whites(image)
    left = [pts[i] for i in range(11, 17)]
    right = [pts[i] for i in range(17, 23)]
    mouth = [pts[i] for i in range(23, 28)]
    brows = [pts[i] for i in range(5, 11)]

    def centre(group):
        return (sum(p[0] for p in group) / len(group), sum(p[1] for p in group) / len(group))

    def box(group):
        return (min(p[0] for p in group), min(p[1] for p in group), max(p[0] for p in group), max(p[1] for p in group))

    return {"left": centre(left), "right": centre(right), "left_box": box(left), "right_box": box(right),
            "mouth": centre(mouth), "mouth_box": box(mouth), "brow_y": sum(p[1] for p in brows) / len(brows)}


def _warp(picture: Image.Image, m: dict[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    """Scale and move the picture so its eye centres sit on the layout's eye line and gap and its mouth on the mouth line."""
    eye_mid = ((m["left"][0] + m["right"][0]) / 2, (m["left"][1] + m["right"][1]) / 2)
    gap = abs(m["right"][0] - m["left"][0]) / 2
    drop = m["mouth"][1] - eye_mid[1]
    sx = EYE_GAP / max(gap, 1.0)
    sy = (MOUTH_Y - EYE_Y) / max(drop, 1.0)
    sy = max(sx * 0.8, min(sx * 1.25, sy))             # keep the face's own proportions within reason
    w, h = picture.size
    scaled = picture.resize((max(1, int(w * sx)), max(1, int(h * sy))), Image.LANCZOS)
    dx, dy = 512 - eye_mid[0] * sx, EYE_Y - eye_mid[1] * sy
    canvas = Image.new("RGBA", (base.CANVAS, base.CANVAS), (0, 0, 0, 0))
    canvas.alpha_composite(scaled, (int(round(dx)), int(round(dy))))
    boxes = {}
    for key in ("left_box", "right_box", "mouth_box"):
        x0, y0, x1, y1 = m[key]
        boxes[key] = (x0 * sx + dx, y0 * sy + dy, x1 * sx + dx, y1 * sy + dy)
    return canvas, {"boxes": boxes, "brow_y": m["brow_y"] * sy + dy, "scale": (sx, sy)}


def _cover(image: Image.Image, skin, boxes, margin: float, blur: float) -> None:
    """Skin over the painted brows (and whatever else is given), feathered."""
    patch = Image.new("RGBA", image.size, (*skin, 0))
    draw = ImageDraw.Draw(patch)
    for x0, y0, x1, y1 in boxes:
        draw.rounded_rectangle((x0 - margin, y0 - margin, x1 + margin, y1 + margin), radius=margin, fill=(*skin, 255))
    image.alpha_composite(patch.filter(ImageFilter.GaussianBlur(blur)))


def _lid_overlays(image: Image.Image, traits: dict[str, Any], p: dict[str, Any], placed: dict[str, Any]) -> None:
    """Lids over the painted eyes: the layout's eye openings decide how much of the eye the lids cover."""
    draw = ImageDraw.Draw(image)
    skin = tuple(traits["skin"][:3]) + (255,)
    lash = traits["lash"]
    width = max(4, int(traits["line"] * SC * 0.4))
    shape = SHAPES[traits.get("face_shape", "soft")]
    for sign, key in ((-1, "left_box"), (1, "right_box")):
        x0, y0, x1, y1 = placed["boxes"][key]
        cx, cy = _s((x0 + x1) / 2), _s((y0 + y1) / 2)
        rx, ry = _s(x1 - x0) / 2 * 1.15, _s(y1 - y0) / 2 * 1.2
        o = _opening(cx, sign, p, shape)
        cover = o["lid"]
        if p["shape"] == "arc":
            draw.ellipse((cx - rx * 1.1, cy - ry * 1.3, cx + rx * 1.1, cy + ry * 1.3), fill=skin)
            pts = _quad((cx - sign * rx * 0.95, cy + ry * 0.2), (cx, cy - ry * 1.3), (cx + sign * rx * 0.95, cy + ry * 0.2 - _s(shape["tilt"]) * 0.6))
            draw.line(pts, fill=lash, width=int(width * 2.4), joint="curve")
            continue
        if cover > 0:
            cut = cy - ry + 2 * ry * cover * 0.9
            draw.rectangle((cx - rx * 1.2, cy - ry * 1.4, cx + rx * 1.2, cut), fill=skin)
            draw.line((cx - rx * 1.05, cut, cx + rx * 1.05, cut), fill=lash, width=int(width * 2.0))
        if p["shape"] in ("angry", "sad"):
            inner_x = cx - sign * rx
            edge = inner_x if p["shape"] == "angry" else cx + sign * rx
            far = edge + (sign if p["shape"] == "angry" else -sign) * rx * 1.6
            depth = 0.55 if p["shape"] == "angry" else 0.4
            draw.polygon([(edge, cy - ry * 1.3), (far, cy - ry * 1.3), (edge, cy - ry + 2 * ry * depth)], fill=skin)
            draw.line((edge, cy - ry + 2 * ry * depth, far, cy - ry * 1.3), fill=lash, width=int(width * 1.6))
        if p["shape"] == "sad":
            tx, ty = cx + sign * rx * 0.3, cy + ry + _s(4)
            draw.ellipse((tx - _s(6), ty, tx + _s(6), ty + _s(24)), fill=(176, 214, 245, 230), outline=lash, width=max(2, width // 3))


def draw_pose(traits: dict[str, Any], pose: str, warped: Image.Image, placed: dict[str, Any], *, lids_only: bool = False) -> Image.Image:
    p = POSES[pose]
    image = Image.new("RGBA", (base.CANVAS * SC, base.CANVAS * SC), (0, 0, 0, 0))
    skin = tuple(traits["skin"][:3])
    if lids_only:
        # the blink: skin over the painted eyes, then the closed lash curve of the layout
        boxes = [tuple(_s(v) for v in placed["boxes"][key]) for key in ("left_box", "right_box")]
        _cover(image, skin, boxes, _s(10), _s(5))
        _lids(image, traits, p)
        return image.resize((base.CANVAS, base.CANVAS), Image.LANCZOS)
    image.alpha_composite(warped.resize(image.size, Image.LANCZOS))
    # the painted brows go; the layout's brows come back, tilted per pose
    brow_h = _s(EYE_RY) * 0.9
    boxes = [(_s(x0) - _s(8), _s(placed["brow_y"]) - brow_h, _s(x1) + _s(8), _s(placed["brow_y"]) + brow_h) for x0, _y0, x1, _y1 in (placed["boxes"]["left_box"], placed["boxes"]["right_box"])]
    _cover(image, skin, boxes, _s(6), _s(6))
    _blush(image, traits, p)
    draw = ImageDraw.Draw(image)
    _lid_overlays(image, traits, p, placed)
    _brows(draw, traits, p)
    if p["corners"] != 0.0:
        # the rest mouth: the painted one stays for neutral; a smile or a frown is drawn over it
        mx0, my0, mx1, my1 = placed["boxes"]["mouth_box"]
        _cover(image, skin, [(_s(mx0) - _s(6), _s(my0) - _s(6), _s(mx1) + _s(6), _s(my1) + _s(6))], _s(4), _s(4))
        _mouth(draw, traits, p)
    return image.resize((base.CANVAS, base.CANVAS), Image.LANCZOS)


def _painted_skin(picture: Image.Image, m: dict[str, Any]) -> tuple[int, int, int, int]:
    """The painting's own skin: the median colour of the cheeks under the eyes."""
    import numpy as np

    rgba = np.asarray(picture.convert("RGBA"))
    samples = []
    for key in ("left_box", "right_box"):
        x0, y0, x1, y1 = [int(v) for v in m[key]]
        h = max(4, y1 - y0)
        patch = rgba[y1 + h // 2: y1 + h * 2, x0: x1]
        if patch.size:
            opaque = patch[patch[:, :, 3] > 200]
            if len(opaque):
                samples.append(opaque[:, :3])
    if not samples:
        return (243, 203, 164, 255)
    stacked = np.concatenate(samples)
    return tuple(int(v) for v in np.median(stacked, axis=0)) + (255,)


def qwen_kit(look: dict[str, Any], picture: Image.Image) -> dict[str, Any]:
    """Kit images from one keyed bald picture. Raises ``QwenFaceError`` when no face is found."""
    m = measure(picture)
    look = {**look, "skin": _painted_skin(picture, m)}
    warped, placed = _warp(picture.convert("RGBA"), m)
    poses = {pose: draw_pose(look, pose, warped, placed) for pose in POSES}
    blinks = {pose: draw_pose(look, pose, warped, placed, lids_only=True) for pose in POSES}
    mouths = anime_mouths(look)
    anchors, placed_all = {}, {}
    eyes = base._anchor(512, 512, base.CANVAS, base.CANVAS, base.CANVAS)
    for pose in POSES:
        at = layout(pose)
        anchors[pose] = {"mouth": base._anchor(*at["mouth"], base.CANVAS, base.CANVAS), "eyes": dict(eyes)}
        placed_all[pose] = {"mouth": at["mouth"], "eyes": (512, 512, base.CANVAS)}
    return {"traits": look, "poses": poses, "blinks": blinks, "mouths": mouths, "anchors": anchors, "layout": placed_all,
            "mouthMapping": dict(base.MAPPING), "preview": base._sheet(poses, mouths, anchors),
            "face": {"fit": list(FIT), "taper": TAPER, "poses": list(POSES), "shape": "mesh", "skin": base._hex(look["skin"]),
                     "source": "qwen", "landmarks": {k: [round(v, 1) for v in placed["boxes"][k]] for k in placed["boxes"]}}}
