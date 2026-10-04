"""Rig a flat cutout character so it can talk: one call from a keyed pose to a Character Kit.

For each pose (an RGBA image with the background keyed out) this finds the two
white eyes and the painted mouth under them, wipes that mouth by inpainting,
and measures pose-local anchors. It then draws nine paper mouths and a blink
made from the base pose's own eye shapes. The result is saved on the kit.

It suits flat styles with light eyes on a plain face (paper cutout, simple
cartoon). A face that is a screen (a laptop or robot character) uses
``screen``: light marks on a dark screen. When no painted mouth is found the
mouth is placed under the eyes and nothing is wiped; the result says so.

Ported from the agent script that rigged the six "Uncanny Valley" characters.
Only OpenCV, numpy and Pillow are needed.
"""
from __future__ import annotations

import copy
import hashlib
import io
import math
import os
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np
from PIL import Image, ImageDraw

from services.character_kit_library import patch_character_kit, read_character_kit_library

STATES = ("closed", "small", "wide", "round", "pressed", "medium", "pucker", "bite", "tongue")
MAPPING = {"rest": "closed", "M": "pressed", "A": "wide", "E": "medium", "I": "small",
           "O": "round", "U": "pucker", "F": "bite", "L": "tongue"}
SPRITE = (512, 320)
INK, CAVITY = (34, 22, 20, 255), (92, 26, 30, 255)
TEETH, TONGUE = (250, 248, 240, 255), (222, 98, 110, 255)
SCREEN_INK, SCREEN_CAVITY = (245, 250, 255, 255), (10, 22, 70, 255)
STYLE_LIMITS = {"smile": (-1.0, 1.0, 0.15), "smirk": (0.0, 1.0, 0.0), "width": (0.3, 0.9, 0.62),
                "mouth_scale": (0.4, 1.2, 0.78)}
MAX_PIXELS = 16_777_216
_CROSS = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))


class FlatRigError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def rig_style(value: Any) -> dict[str, Any]:
    """Mouth look: ``smile`` -1..1, ``smirk`` 0..1, ``width`` and ``mouth_scale``; ``screen`` for a screen face."""
    raw = value if isinstance(value, dict) else {}
    style: dict[str, Any] = {"screen": raw.get("screen") is True}
    for key, (low, high, default) in STYLE_LIMITS.items():
        number = raw.get(key, default)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not low <= float(number) <= high:
            raise FlatRigError("invalid_style", f"style.{key} must be a number from {low} to {high}")
        style[key] = float(number)
    return style


# Masks ----------------------------------------------------------------------

def _mask(value: np.ndarray) -> np.ndarray:
    return value.astype(np.uint8)


def _open(mask: np.ndarray, iterations: int) -> np.ndarray:
    return cv2.morphologyEx(_mask(mask), cv2.MORPH_OPEN, _CROSS, iterations=iterations) > 0


def _close(mask: np.ndarray, iterations: int) -> np.ndarray:
    return cv2.morphologyEx(_mask(mask), cv2.MORPH_CLOSE, _CROSS, iterations=iterations) > 0


def _dilate(mask: np.ndarray, iterations: int) -> np.ndarray:
    return cv2.dilate(_mask(mask), _CROSS, iterations=iterations) > 0


def _components(mask: np.ndarray) -> tuple[np.ndarray, list[dict[str, int]]]:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(_mask(mask), connectivity=8)
    found = []
    for label in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[label])
        found.append({"label": label, "size": area, "x0": x, "y0": y, "x1": x + w, "y1": y + h})
    return labels, found


def _clean_alpha(image: Image.Image) -> Image.Image:
    """Drop faint keyed speckles and keep the figure (every part over 2 % of the largest)."""
    pixels = np.array(image)
    alpha = pixels[..., 3]
    alpha[alpha < 64] = 0
    labels, parts = _components(alpha > 0)
    if len(parts) > 1:
        largest = max(part["size"] for part in parts)
        keep = np.isin(labels, [part["label"] for part in parts if part["size"] > largest * 0.02])
        alpha[~keep] = 0
    pixels[..., 3] = alpha
    return Image.fromarray(pixels)


def crop_figure(image: Image.Image, margin: float = 0.02) -> Image.Image:
    image = _clean_alpha(image.convert("RGBA"))
    alpha = np.array(image)[..., 3]
    ys, xs = np.nonzero(alpha > 128)
    if not len(xs):
        raise FlatRigError("not_keyed", "The pose has no visible figure; key its background first")
    pad = int(max(image.size) * margin)
    return image.crop((max(0, xs.min() - pad), max(0, ys.min() - pad),
                       min(image.width, xs.max() + pad + 1), min(image.height, ys.max() + pad + 1)))


# Features -------------------------------------------------------------------

def _eye_pair(parts: list[dict[str, int]]) -> tuple[dict[str, int], dict[str, int]]:
    best = None
    for i in range(min(4, len(parts))):
        for j in range(i + 1, min(5, len(parts))):
            a, b = parts[i], parts[j]
            ratio = min(a["size"], b["size"]) / max(a["size"], b["size"])
            vertical = abs((a["y0"] + a["y1"]) - (b["y0"] + b["y1"])) / 2
            if ratio > 0.45 and vertical < (a["y1"] - a["y0"]) * 0.6 and (not best or a["size"] + b["size"] > best[0]):
                best = (a["size"] + b["size"], a, b)
    return (best[1], best[2]) if best else (parts[0], parts[1])


def find_eyes(rgb: np.ndarray, alpha: np.ndarray, top_fraction: float = 0.55):
    """The two largest white blobs of similar size side by side, in the top of the figure."""
    height, width = alpha.shape
    white = (rgb.min(axis=2) > 218) & (alpha > 200)
    white[int(height * top_fraction):] = False
    labels, parts = _components(_open(white, 2))
    parts = sorted((part for part in parts if part["size"] > width * height * 0.0015), key=lambda part: -part["size"])
    if len(parts) < 2:
        raise FlatRigError("eyes_not_found", "Two light eyes were not found in the top half of the pose")
    left, right = sorted(_eye_pair(parts), key=lambda part: part["x0"])
    mask = (labels == left["label"]) | (labels == right["label"])
    box = (min(left["x0"], right["x0"]), min(left["y0"], right["y0"]),
           max(left["x1"], right["x1"]), max(left["y1"], right["y1"]))
    return box, mask


def _mouth_marks(region: np.ndarray, inside: np.ndarray, eye_height: int, screen: bool):
    lum = region @ np.array([0.299, 0.587, 0.114])
    if screen:
        mark = (region.min(axis=2) > 200) & inside
        top = region[: max(4, int(eye_height * 0.25))]
        background = np.median(top[top.min(axis=2) < 200], axis=0)
        return mark, mark, background
    lighter = inside & (lum > np.percentile(lum[inside], 40))
    # A perfectly flat fill has no pixel above its own percentile; paper texture always does.
    background = np.median(region[lighter if lighter.any() else inside], axis=0)
    skin = float(background @ np.array([0.299, 0.587, 0.114]))
    return (lum < skin * 0.62) & inside, (lum < skin * 0.5) & inside, background


def find_mouth(rgb: np.ndarray, alpha: np.ndarray, eyes_box, screen: bool = False):
    """Dark marks under the eyes that the face colour surrounds (so collars and jaws are skipped)."""
    x0, _y0, x1, y1 = eyes_box
    eye_height, eye_width = y1 - eyes_box[1], x1 - x0
    ry0, ry1 = int(y1 + eye_height * 0.12), int(y1 + eye_height * 1.35)
    rx0, rx1 = int(x0 + eye_width * 0.05), int(x1 - eye_width * 0.05)
    region = rgb[ry0:ry1, rx0:rx1].astype(float)
    inside = alpha[ry0:ry1, rx0:rx1] > 200
    if not inside.any():
        raise FlatRigError("mouth_not_found", "No face was found under the eyes")
    mark, dark, background = _mouth_marks(region, inside, eye_height, screen)
    face = _close(np.abs(region - background).sum(axis=2) < 60, 6)
    labels, parts = _components(_close(mark, 2))
    good = []
    for part in parts:
        piece = labels[part["y0"]:part["y1"], part["x0"]:part["x1"]] == part["label"]
        if part["size"] < 12 or not dark[part["y0"]:part["y1"], part["x0"]:part["x1"]][piece].any():
            continue
        ring = face[max(0, part["y0"] - 6):part["y1"] + 6, max(0, part["x0"] - 6):part["x1"] + 6]
        if ring.mean() >= 0.55:
            good.append(part)
    if not good:
        raise FlatRigError("mouth_not_found", "No painted mouth was found under the eyes")
    centre = (rx1 - rx0) / 2
    good.sort(key=lambda part: part["y0"] + abs((part["x0"] + part["x1"]) / 2 - centre) * 0.5)
    band = (good[0]["y0"] + good[0]["y1"]) / 2
    # A smirk or a long line can break into pieces: keep every mark on the same row.
    chosen = [part for part in good if abs((part["y0"] + part["y1"]) / 2 - band) < eye_height * 0.14]
    mask = np.zeros(alpha.shape, bool)
    for part in chosen:
        mask[ry0:ry1, rx0:rx1] |= labels == part["label"]
    ys, xs = np.nonzero(mask)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1), mask, background


def wipe(image: Image.Image, mask: np.ndarray, grow: int) -> Image.Image:
    pixels = np.array(image)
    bgr = cv2.cvtColor(pixels[..., :3], cv2.COLOR_RGB2BGR)
    area = _dilate(mask, grow).astype(np.uint8) * 255
    pixels[..., :3] = cv2.cvtColor(cv2.inpaint(bgr, area, max(3, grow + 2), cv2.INPAINT_TELEA), cv2.COLOR_BGR2RGB)
    return Image.fromarray(pixels)


# Drawing --------------------------------------------------------------------

def _arc(draw, centre, width, curve, height, ink, thickness, smirk=0.0) -> None:
    cx, cy = centre
    points = []
    for i in range(41):
        t = i / 40 * 2 - 1
        # curve > 0 smiles; smirk lifts the right corner.
        y = cy + curve * (1 - t * t) * height * 0.32 - curve * height * 0.16 - smirk * max(0.0, t) ** 2 * height * 0.28
        points.append((cx + t * width / 2, y))
    draw.line(points, fill=ink, width=thickness, joint="curve")
    radius = thickness / 2
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=ink)


def _paste_inside(image, outline, fill, box_or_ellipse, kind) -> None:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).polygon(outline, fill=255)
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    getattr(ImageDraw.Draw(layer), kind)(box_or_ellipse, fill=fill)
    clip = Image.composite(layer, Image.new("RGBA", image.size, (0, 0, 0, 0)), mask)
    image.paste(layer, (0, 0), clip.split()[3])


def _open_mouth(image, draw, centre, width, height, style, ink, cavity, thickness, *, teeth=True, tongue=True) -> None:
    """A D-shaped open mouth: flatter top lip, round bottom."""
    ox, oy = centre
    outline = [(ox - math.cos(math.pi * i / 59) * width / 2, oy + math.sin(math.pi * i / 59) * height / 2) for i in range(60)]
    outline += [(ox + width / 2 - i / 29 * width, oy - (1 - (2 * i / 29 - 1) ** 2) * height * 0.125) for i in range(30)]
    draw.polygon(outline, fill=cavity)
    if teeth and not style["screen"]:
        _paste_inside(image, outline, TEETH, (ox - width / 2, oy - height, ox + width / 2, oy + height * 0.12), "rectangle")
    if tongue and not style["screen"]:
        _paste_inside(image, outline, TONGUE, (ox - width * 0.28, oy + height * 0.12, ox + width * 0.28, oy + height * 0.75), "ellipse")
    draw.line(outline + [outline[0]], fill=ink, width=thickness, joint="curve")


def draw_mouth(state: str, style: dict[str, Any]) -> Image.Image:
    """One paper mouth sprite (512×320, transparent), drawn at 4× and reduced for smooth edges."""
    width, height, k = SPRITE[0], SPRITE[1], 4
    image = Image.new("RGBA", (width * k, height * k), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    cx, cy, h = width * k / 2, height * k / 2, height * k
    base = width * k * style["width"]
    line = max(2, int(h * 0.045))
    ink, cavity = (SCREEN_INK, SCREEN_CAVITY) if style["screen"] else (INK, CAVITY)

    def opened(w, oh, shift=0.0, **flags):
        _open_mouth(image, draw, (cx, cy + shift * h), w, oh, style, ink, cavity, line, **flags)

    if state == "closed":
        _arc(draw, (cx, cy), base * 0.78, style["smile"], h, ink, line, style["smirk"])
    elif state == "pressed":
        _arc(draw, (cx, cy), base * 0.62, 0.02, h, ink, int(line * 1.5))
    elif state == "small":
        opened(base * 0.5, h * 0.22, tongue=False)
    elif state == "medium":
        opened(base * 0.72, h * 0.34)
    elif state == "wide":
        opened(base * 0.86, h * 0.58, 0.05)
    elif state in ("round", "pucker"):
        r = h * (0.22 if state == "round" else 0.13)
        draw.ellipse((cx - r * (0.9 if state == "round" else 0.85), cy - r, cx + r * (0.9 if state == "round" else 0.85), cy + r),
                     fill=cavity, outline=ink, width=line if state == "round" else int(line * 1.2))
    elif state == "bite":
        w2, h2 = base * 0.6, h * 0.2
        draw.rounded_rectangle((cx - w2 / 2, cy - h2 / 2, cx + w2 / 2, cy + h2 / 2), radius=h2 / 2, fill=cavity, outline=ink, width=line)
        if not style["screen"]:
            draw.rectangle((cx - w2 / 2 + line, cy - h2 / 2 + line, cx + w2 / 2 - line, cy + h2 * 0.1), fill=TEETH)
        draw.line((cx - w2 / 2, cy + h2 * 0.18, cx + w2 / 2, cy + h2 * 0.18), fill=ink, width=line)
    elif state == "tongue":
        opened(base * 0.62, h * 0.32, tongue=False)
        if not style["screen"]:
            draw.ellipse((cx - base * 0.14, cy - h * 0.06, cx + base * 0.14, cy + h * 0.12), fill=TONGUE, outline=ink, width=max(2, line // 2))
    else:
        raise FlatRigError("invalid_state", f"Unknown mouth state {state}")
    return image.resize(SPRITE, Image.LANCZOS)


def blink_sprite(rgb: np.ndarray, eyes: np.ndarray, fallback, screen: bool = False) -> Image.Image:
    """Closed eyes: each eye covered with the colour around it, plus a lid line."""
    height, width = eyes.shape
    k = 4
    image = Image.new("RGBA", (width * k, height * k), (0, 0, 0, 0))
    labels, parts = _components(eyes)
    parts = sorted(parts, key=lambda part: -part["size"])[:2]
    grow = max(4, int(min(height, width) * 0.05))
    line = max(3, int(height * k * 0.035))
    colour = SCREEN_INK if screen else INK
    for part in parts:
        cover = _dilate(labels == part["label"], grow)
        ring = _dilate(cover, grow) & ~cover
        local = np.median(rgb[ring], axis=0) if ring.any() else np.array(fallback)
        mask = Image.fromarray((cover * 255).astype(np.uint8)).resize((width * k, height * k), Image.BILINEAR)
        image.paste(Image.new("RGBA", image.size, tuple(int(v) for v in local) + (255,)), (0, 0), mask)
    draw = ImageDraw.Draw(image)
    for part in parts:
        x0, x1 = part["x0"] * k, part["x1"] * k
        lid = (part["y0"] + (part["y1"] - part["y0"]) * 0.58) * k
        sag = (part["y1"] - part["y0"]) * k * 0.1
        points = [(x0 + (x1 - x0) * (0.08 + 0.84 * t / 20), lid + math.sin(math.pi * t / 20) * sag) for t in range(21)]
        draw.line(points, fill=colour, width=line, joint="curve")
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - line / 2, y - line / 2, x + line / 2, y + line / 2), fill=colour)
    return image.resize((width, height), Image.LANCZOS)


# One pose -------------------------------------------------------------------

def _anchor(cx: float, cy: float, size: float, width: int, height: int) -> dict[str, float]:
    edge = max(width, height)
    return {"offsetX": round((cx - width / 2) / edge * 100, 3), "offsetY": round((cy - height / 2) / edge * 100, 3),
            "scale": round(size / edge, 5), "rotation": 0.0}


def rig_pose(image: Image.Image, style: dict[str, Any]) -> dict[str, Any]:
    """Crop, find the face, wipe the painted mouth and measure anchors for one keyed pose."""
    if image.width * image.height > MAX_PIXELS:
        raise FlatRigError("image_too_large", "Use a pose image up to 16 megapixels")
    figure = crop_figure(image)
    pixels = np.array(figure)
    rgb, alpha = pixels[..., :3], pixels[..., 3]
    eyes_box, eyes_mask = find_eyes(rgb, alpha)
    ex0, ey0, ex1, ey1 = eyes_box
    try:
        mouth_box, mouth_mask, background = find_mouth(rgb, alpha, eyes_box, style["screen"])
        rigged, wiped = wipe(figure, mouth_mask, max(4, int((ey1 - ey0) * 0.08))), True
        mx, my = (mouth_box[0] + mouth_box[2]) / 2, (mouth_box[1] + mouth_box[3]) / 2
    except FlatRigError as error:
        if error.code != "mouth_not_found":
            raise
        # Under the eyes, where a cutout mouth usually sits; nothing painted to wipe.
        rigged, wiped, mouth_box = figure, False, None
        mx, my = (ex0 + ex1) / 2, ey1 + (ey1 - ey0) * 0.75
        ring = alpha[ey1:min(alpha.shape[0], ey1 + (ey1 - ey0)), ex0:ex1] > 200
        background = np.median(rgb[ey1:min(alpha.shape[0], ey1 + (ey1 - ey0)), ex0:ex1][ring], axis=0) if ring.any() else np.array([200, 160, 130])
    width, height = rigged.size
    sprite_width = (ex1 - ex0) * style["mouth_scale"]
    pad = int((ey1 - ey0) * 0.25)
    bx0, by0, bx1, by1 = max(0, ex0 - pad), max(0, ey0 - pad), min(width, ex1 + pad), min(height, ey1 + pad)
    return {
        "image": rigged, "width": width, "height": height, "wiped": wiped,
        "mouth": _anchor(mx, my, sprite_width * SPRITE[1] / SPRITE[0], width, height),
        "eyes": _anchor((bx0 + bx1) / 2, (by0 + by1) / 2, by1 - by0, width, height),
        "blink": blink_sprite(rgb[by0:by1, bx0:bx1], eyes_mask[by0:by1, bx0:bx1], background, style["screen"]),
        "eyes_box": list(eyes_box), "mouth_box": list(mouth_box) if mouth_box else None,
    }


def place(base: Image.Image, overlay: Image.Image, anchor: dict[str, float]) -> Image.Image:
    """Composite ``overlay`` on ``base`` the way the kit binds it (height = scale × longer edge)."""
    out = base.copy()
    edge = max(out.size)
    h = max(1, int(round(anchor["scale"] * edge)))
    w = max(1, int(round(h * overlay.width / overlay.height)))
    cx, cy = out.width / 2 + anchor["offsetX"] * edge / 100, out.height / 2 + anchor["offsetY"] * edge / 100
    out.alpha_composite(overlay.resize((w, h), Image.LANCZOS), (int(round(cx - w / 2)), int(round(cy - h / 2))))
    return out


def review_sheet(poses: dict[str, dict[str, Any]], mouths: dict[str, Image.Image], blink: Image.Image, height: int = 360) -> Image.Image:
    """Per pose: the rig with its rest mouth, then an open mouth with the blink, on white."""
    tiles = []
    for rig in poses.values():
        rest = place(rig["image"], mouths["closed"], rig["mouth"])
        # The kit has one blink, from the base pose, placed with each pose's eye anchor.
        talk = place(place(rig["image"], mouths["wide"], rig["mouth"]), blink, rig["eyes"])
        for frame in (rest, talk):
            tiles.append(frame.resize((max(1, int(frame.width * height / frame.height)), height), Image.LANCZOS))
    sheet = Image.new("RGBA", (sum(tile.width for tile in tiles) + 8 * (len(tiles) + 1), height + 16), (255, 255, 255, 255))
    x = 8
    for tile in tiles:
        sheet.alpha_composite(tile, (x, 8))
        x += tile.width + 8
    return sheet


# A whole kit ----------------------------------------------------------------

def _workspace_file(source: str, workspace: str, workspace_dir: str) -> str:
    parsed = urlparse(source)
    if not parsed.path.startswith("/api/v1/file/"):
        raise FlatRigError("unsupported_source", "Pose images must be workspace files (/api/v1/file/...)")
    owner = (parse_qs(parsed.query).get("workspace") or [workspace])[0]
    if owner != workspace:
        raise FlatRigError("unsupported_source", "Pose images must belong to this workspace")
    name = unquote(parsed.path[len("/api/v1/file/"):])
    root = os.path.realpath(workspace_dir)
    path = os.path.realpath(os.path.join(root, name))
    if os.path.dirname(path) != root and not path.startswith(root + os.sep):
        raise FlatRigError("unsupported_source", "Pose images must stay inside the workspace")
    if not os.path.isfile(path):
        raise FlatRigError("missing_source", f"Pose image is missing: {name}", 409)
    return path


def _save(image: Image.Image, directory: str, stem: str) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()
    name = f"{stem}-{hashlib.sha256(data).hexdigest()[:8]}.png"
    with open(os.path.join(directory, name), "wb") as handle:
        handle.write(data)
    return name


def _url(name: str, workspace: str) -> str:
    return f"/api/v1/file/{name}?workspace={workspace}"


def _original_sources(kit: dict[str, Any]) -> dict[str, str]:
    """A re-rig starts from the images with painted mouths, recorded by the first rig."""
    for entry in reversed(kit.get("provenance") or []):
        if entry.get("method") == "flat-rig" and isinstance(entry.get("sources"), dict):
            return dict(entry["sources"])
    return {}


def _overlay(kit_id: str, name: str, label: str, file: str, workspace: str) -> dict[str, Any]:
    return {"id": f"{kit_id}-{label}"[:120], "name": f"{name} {label}"[:240], "source": _url(file, workspace),
            "kind": "overlay", "alphaStatus": "transparent", "reviewState": "approved", "workspace": workspace}


def _rig_poses(kit: dict[str, Any], style, workspace: str, workspace_dir: str, pose_ids):
    originals = _original_sources(kit)
    assets = {"base": kit.get("base"), **(kit.get("poses") or {})}
    wanted = list(pose_ids) if pose_ids else [pose for pose, asset in assets.items() if asset]
    if "base" not in wanted or not assets.get("base"):
        raise FlatRigError("missing_base", "Approve a base pose before rigging; the blink comes from it", 409)
    rigs, sources = {}, {}
    for pose in wanted:
        if not assets.get(pose):
            raise FlatRigError("unknown_pose", f"The character has no pose {pose}")
        sources[pose] = originals.get(pose) or assets[pose]["source"]
        with Image.open(_workspace_file(sources[pose], workspace, workspace_dir)) as image:
            try:
                rigs[pose] = rig_pose(image, style)
            except FlatRigError as error:
                raise FlatRigError(error.code, f"Pose {pose}: {error}", error.status) from error
    return rigs, sources


def rig_character(workspace_dir: str, workspace: str, kit_id: str, *, base_revision: int,
                  style: Any = None, pose_ids: list[str] | None = None) -> dict[str, Any]:
    """Rig the kit's base and poses, write the images to the workspace and save the kit."""
    library = read_character_kit_library(workspace_dir)
    kit = copy.deepcopy((library.get("kits") or {}).get(kit_id))
    if kit is None:
        raise FlatRigError("character_not_found", "Character not found", 404)
    look = rig_style(style)
    rigs, sources = _rig_poses(kit, look, workspace, workspace_dir, pose_ids)
    mouths = {state: draw_mouth(state, look) for state in STATES}
    name = kit.get("name") or kit_id
    kit["mouth"] = {state: _overlay(kit_id, name, f"mouth-{state}", _save(mouths[state], workspace_dir, f"kit-{kit_id}-mouth-{state}"), workspace)
                    for state in STATES}
    kit["mouthMapping"] = dict(MAPPING)
    blink_file = _save(rigs["base"]["blink"], workspace_dir, f"kit-{kit_id}-blink")
    kit["eyes"] = {"blink": _overlay(kit_id, name, "blink", blink_file, workspace)}
    anchors = dict(kit.get("anchors") or {})
    for pose, rig in rigs.items():
        file = _save(rig["image"], workspace_dir, f"kit-{kit_id}-{pose}-rig")
        target = kit["base"] if pose == "base" else kit["poses"][pose]
        target.update({"source": _url(file, workspace), "width": rig["width"], "height": rig["height"],
                       "alphaStatus": "transparent", "workspace": workspace})
        anchors[pose] = {"mouth": rig["mouth"], "eyes": rig["eyes"]}
    kit["anchors"] = anchors
    kit["style"] = "cutout"
    sheet = _save(review_sheet(rigs, mouths, rigs["base"]["blink"]), workspace_dir, f"kit-{kit_id}-rig-review")
    unwiped = sorted(pose for pose, rig in rigs.items() if not rig["wiped"])
    kit["provenance"] = [*(kit.get("provenance") or []), {
        "method": "flat-rig", "sources": {**_original_sources(kit), **sources}, "style": look,
        "unwipedPoses": unwiped, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }]
    saved = patch_character_kit(workspace_dir, kit_id, kit, base_revision=base_revision)
    return {
        "revision": saved.get("revision"), "character": saved["kits"][kit_id],
        "review": _url(sheet, workspace), "unwipedPoses": unwiped,
        "poses": {pose: {"mouth": rig["mouth"], "eyes": rig["eyes"], "wiped": rig["wiped"]} for pose, rig in rigs.items()},
    }
