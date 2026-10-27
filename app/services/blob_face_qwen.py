"""A painted bald face (a Qwen picture) as the base of an ``anime_head`` kit: the ``qwen`` face source.

The picture is keyed by the caller (``image.remove_background``) and read here: its landmarks (or the silhouette
prior for a bald head) give the two eyes, which are cut out with a feathered edge and pasted inside the drawn
openings of the ``anime_head`` face; lids, lashes, crease, brows, nose, mouth, blush and blink are the drawn ones,
so the eleven expressions are as consistent as the drawn style and nothing of the painting is lit twice. Why not
the whole painting or Qwen-edited expressions: pasting the painting re-lights its shading and projects its
contours onto the skull's cheeks, and separately edited expressions drift (measured on ``bald_hana_31``: eyes
0.8–2.5 % of the picture, mouth 0.1–3.2 %, eye size ±35 %). Same kit shape, same anchors, same ``fit``:
``world3d.scene.face`` cannot tell the sources apart.
"""
from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from services import blob_face as base

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


def _eye_crops(picture: Image.Image, m: dict[str, Any]) -> dict[int, Image.Image]:
    """The two painted eyes, cut with a 12 % margin and a feathered edge, keyed to the drawn opening later."""
    crops = {}
    for sign, key in ((-1, "left_box"), (1, "right_box")):
        x0, y0, x1, y1 = m[key]
        mx, my = (x1 - x0) * 0.12, (y1 - y0) * 0.35
        box = (max(0, int(x0 - mx)), max(0, int(y0 - my)), min(picture.width, int(x1 + mx)), min(picture.height, int(y1 + my)))
        crop = picture.crop(box).convert("RGBA")
        mask = Image.new("L", crop.size, 0)
        ImageDraw.Draw(mask).ellipse((2, 2, crop.width - 3, crop.height - 3), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(max(2, crop.width // 24)))
        crop.putalpha(mask)
        crops[sign] = crop
    return crops


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
    """Kit images from one keyed bald picture: its painted eyes inside the drawn face (eyes-only hybrid). Raises
    ``QwenFaceError`` when no face is found."""
    from services.blob_face_anime_head import anime_head_kit

    m = measure(picture)
    look = {**look, "skin": _painted_skin(picture, m)}
    made = anime_head_kit(look, eye_art=_eye_crops(picture, m))
    made["face"] = {**made["face"], "source": "qwen", "landmarks": {k: [round(v, 1) for v in m[k]] for k in ("left_box", "right_box", "mouth_box")}}
    return made
