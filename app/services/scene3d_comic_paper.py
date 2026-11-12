"""Printed-paper look for the comic chapter transition.

The cut frames must match the source, so the clean pictures stay as they are. Each panel also gets a
printed twin: newsprint colour, ink lines, a halftone screen in the shadows, the page's paper fibre and the
lamp that lights the whole page. The scene fades from the clean picture to the twin as the camera pulls
away, and back on the way in. The page itself is redrawn as a sheet of newsprint with hand-inked panel
borders, lying on a desk with two more pages under it. All of it is generated here: no third-party art.
"""
from __future__ import annotations

import math
from pathlib import Path

INK = (20, 17, 16)
PAPER = (240, 232, 214)
# The desk plane is this many times the page, so a yawing camera never sees its edge.
DESK_SPAN = 2.4


def _np():
    import numpy as np
    return np


def paper_fibre(width: int, height: int, seed: int):
    """Multiplicative paper texture around 1.0: soft blotches, short fibres and a fine grain."""
    import cv2
    np = _np()
    rng = np.random.default_rng(seed)
    small = rng.normal(0, 1, (max(2, height // 24), max(2, width // 24))).astype(np.float32)
    blotch = cv2.resize(cv2.GaussianBlur(small, (0, 0), 1.6), (width, height), interpolation=cv2.INTER_CUBIC)
    texture = 1.0 + 0.022 * blotch / max(1e-6, float(np.abs(blotch).max()))
    fibres = np.zeros((height, width), np.float32)
    for _ in range(max(40, width * height // 2600)):
        x, y = int(rng.integers(0, width)), int(rng.integers(0, height))
        angle, length = rng.uniform(0, math.pi), rng.uniform(4, 16)
        tip = (int(x + length * math.cos(angle)), int(y + length * math.sin(angle)))
        cv2.line(fibres, (x, y), tip, float(rng.choice([-1.0, 1.0])), 1, cv2.LINE_AA)
    texture += 0.035 * cv2.GaussianBlur(fibres, (0, 0), 0.6)
    texture += rng.normal(0, 0.012, (height, width)).astype(np.float32)
    return np.clip(texture, 0.85, 1.12)


def lamp(width: int, height: int, box=None):
    """Light from a lamp above the page's top-left corner. `box` is (x, y, w, h, page_w, page_h): a panel
    takes the part of the page's light where it lies, so the panels and the paper share one lamp."""
    np = _np()
    x0, y0, w, h, page_w, page_h = box if box else (0, 0, width, height, width, height)
    xs = (x0 + (np.arange(width, dtype=np.float32) + 0.5) * w / width) / page_w
    ys = (y0 + (np.arange(height, dtype=np.float32) + 0.5) * h / height) / page_h
    dist = np.hypot(xs[None, :] - 0.18, ys[:, None] + 0.12) / 1.25
    return (1.07 - 0.2 * np.clip(dist, 0, 1) ** 1.4).astype(np.float32)


def print_rgb(rgb, seed: int, box=None):
    """A frame as it would look printed: newsprint colour, ink lines, halftone in the shadows, paper, lamp."""
    import cv2
    np = _np()
    height, width = rgb.shape[:2]
    smooth = cv2.bilateralFilter(rgb, 7, 38, 7).astype(np.float32) / 255.0
    grey = smooth.mean(axis=2, keepdims=True)
    colour = grey + (smooth - grey) * 0.82
    colour = 0.07 + 0.88 * colour * np.array([1.0, 0.975, 0.92], np.float32)
    colour = _ink(colour, rgb, width)
    colour = _halftone(colour, width)
    shade = paper_fibre(width, height, seed) * lamp(width, height, box)
    return np.clip(colour * shade[..., None] * 255.0, 0, 255).astype(np.uint8)


def _ink(colour, rgb, width: int):
    import cv2
    np = _np()
    grey = cv2.GaussianBlur(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), (3, 3), 0)
    edges = cv2.Canny(grey, 70, 170)
    size = max(1, round(width / 720))
    if size > 1:
        edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    ink = cv2.GaussianBlur(edges.astype(np.float32) / 255.0, (0, 0), 0.6)[..., None] * 0.62
    return colour * (1 - ink) + np.array(INK, np.float32) / 255.0 * ink


def _halftone(colour, width: int):
    """Round dots on a 45° screen, larger where the picture is darker; the highlights stay clean."""
    np = _np()
    height = colour.shape[0]
    period = max(4.0, width / 92.0)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    u, v = (xs + ys) / math.sqrt(2) / period, (xs - ys) / math.sqrt(2) / period
    d = np.hypot(u - np.floor(u) - 0.5, v - np.floor(v) - 0.5) * period
    luma = colour @ np.array([0.299, 0.587, 0.114], np.float32)
    radius = period * 0.55 * np.sqrt(np.clip((0.62 - luma) / 0.62, 0, 1))
    dot = np.clip(radius - d + 0.5, 0, 1)[..., None]
    return colour * (1 - 0.24 * dot)


def print_picture(source: Path, dest: Path, seed: int, box=None) -> None:
    from PIL import Image
    np = _np()
    with Image.open(source) as opened:
        rgba = np.asarray(opened.convert("RGBA"))
    printed = print_rgb(np.ascontiguousarray(rgba[..., :3]), seed, box)
    _frame_ink(printed)
    Image.fromarray(np.dstack([printed, rgba[..., 3]])).save(dest)


def _frame_ink(rgb) -> None:
    """A thin ink line just inside the picture's edge, so it meets the page's border."""
    width = rgb.shape[1]
    line = max(2, round(width / 360))
    rgb[:line, :] = INK
    rgb[-line:, :] = INK
    rgb[:, :line] = INK
    rgb[:, -line:] = INK


def print_sticker(source: Path, dest: Path, seed: int, box=None) -> None:
    """The printed twin of a sticker: printed colour plus a white die-cut border and its cut edge."""
    import cv2
    from PIL import Image
    np = _np()
    with Image.open(source) as opened:
        rgba = np.asarray(opened.convert("RGBA"))
    height, width = rgba.shape[:2]
    printed = print_rgb(np.ascontiguousarray(rgba[..., :3]), seed, box).astype(np.float32)
    alpha = rgba[..., 3].astype(np.float32) / 255.0
    reach = max(3, round(min(width, height) / 130))
    solid = (alpha >= 0.5).astype(np.uint8)
    grown = cv2.dilate(solid, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * reach + 1, 2 * reach + 1)))
    border = cv2.GaussianBlur(grown.astype(np.float32), (0, 0), 0.8)
    paper = np.array(PAPER, np.float32) * paper_fibre(width, height, seed + 7)[..., None]
    rgb = printed * alpha[..., None] + paper * (1 - alpha[..., None])
    edge = np.clip(border * (1 - border) * 4, 0, 1)[..., None] * 0.55
    rgb = rgb * (1 - edge) + np.array((150, 140, 128), np.float32) * edge
    out_alpha = np.maximum(alpha, border)
    Image.fromarray(np.dstack([np.clip(rgb, 0, 255), out_alpha * 255]).astype(np.uint8)).save(dest)


def sticker_shadow(source: Path, dest: Path) -> None:
    """The sticker's soft shadow on its panel, thrown down and right by the page's lamp."""
    import cv2
    from PIL import Image
    np = _np()
    with Image.open(source) as opened:
        alpha = np.asarray(opened.convert("RGBA"))[..., 3].astype(np.float32) / 255.0
    height, width = alpha.shape
    shift = np.float32([[1, 0, width / 70], [0, 1, height / 60]])
    moved = cv2.warpAffine(alpha, shift, (width, height))
    soft = cv2.GaussianBlur(moved, (0, 0), max(2.0, min(width, height) / 90))
    shadow = np.zeros((height, width, 4), np.uint8)
    shadow[..., :3] = (12, 9, 8)
    shadow[..., 3] = np.clip(soft * 0.5 * 255, 0, 255).astype(np.uint8)
    Image.fromarray(shadow).save(dest)


def newsprint_page(page_w: int, page_h: int, cells: list[dict], rim: int, seed: int, scale: int = 2):
    """The page as a sheet of newsprint (RGBA) with hand-inked borders. The dark rim of the layout becomes
    transparent, so the desk shows around the sheet's slightly uneven edge."""
    import cv2
    np = _np()
    width, height = page_w * scale, page_h * scale
    sheet = np.array(PAPER, np.float32) * (paper_fibre(width, height, seed) * lamp(width, height))[..., None]
    rim = max(1, rim * scale)
    alpha = np.zeros((height, width), np.float32)
    rng = np.random.default_rng(seed + 1)
    corners = np.array([[rim, rim], [width - rim, rim], [width - rim, height - rim], [rim, height - rim]], np.float32)
    corners += rng.uniform(-1.5, 1.5, corners.shape).astype(np.float32) * scale
    cv2.fillPoly(alpha, [corners.astype(np.int32)], 1.0, cv2.LINE_AA)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 0.7)
    edge_tone = cv2.GaussianBlur(alpha, (0, 0), 6 * scale)
    sheet *= (0.9 + 0.1 * edge_tone)[..., None]
    for cell in cells:
        _ink_border(sheet, cell, scale, rng)
    rgba = np.dstack([np.clip(sheet, 0, 255), alpha * 255]).astype(np.uint8)
    return rgba


def _ink_border(sheet, cell: dict, scale: int, rng) -> None:
    """A pen line around the cell, drawn twice with a little wobble so it reads as inked by hand."""
    import cv2
    np = _np()
    x, y, w, h = (cell[key] * scale for key in ("x", "y", "w", "h"))
    pad = 1.5 * scale
    for thickness in (3 * scale, 2 * scale):
        box = np.array([[x - pad, y - pad], [x + w + pad, y - pad], [x + w + pad, y + h + pad], [x - pad, y + h + pad]], np.float32)
        box += rng.uniform(-0.8, 0.8, box.shape).astype(np.float32) * scale
        cv2.polylines(sheet, [np.round(box * 4).astype(np.int32)], True, INK, int(thickness), cv2.LINE_AA, shift=2)


def desk_backdrop(page_w: int, page_h: int, seed: int, scale: float = 1.0):
    """Dark wood under the page, two more pages peeking out at an angle, and the page's soft shadow."""
    import cv2
    np = _np()
    width, height = int(page_w * DESK_SPAN * scale), int(page_h * DESK_SPAN * scale)
    rng = np.random.default_rng(seed + 3)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    warp = cv2.resize(rng.normal(0, 1, (12, 12)).astype(np.float32), (width, height), interpolation=cv2.INTER_CUBIC)
    rings = 0.5 + 0.5 * np.sin((xs / width * 9 + warp * 0.7 + ys / height * 0.6) * math.pi * 2)
    streak = cv2.resize(rng.normal(0, 1, (height // 4 + 1, 6)).astype(np.float32), (width, height), interpolation=cv2.INTER_LINEAR)
    wood = np.array((58, 36, 24), np.float32) * (0.82 + 0.16 * rings + 0.04 * streak)[..., None]
    centre = np.array([width / 2, height / 2], np.float32)
    page = np.array([page_w * scale, page_h * scale], np.float32)
    for angle, offset, tone in ((-5.5, (-0.06, 0.05), 0.78), (3.8, (0.07, -0.03), 0.86)):
        _paper_under(wood, centre + page * np.array(offset, np.float32), page, angle, tone)
    shadow = np.zeros((height, width), np.float32)
    corner = centre - page / 2 + page * np.array([0.02, 0.025], np.float32)
    cv2.rectangle(shadow, tuple(int(v) for v in corner), tuple(int(v) for v in corner + page), 1.0, -1)
    shadow = cv2.GaussianBlur(shadow, (0, 0), max(6.0, page[0] / 40))
    wood *= (1 - 0.55 * shadow)[..., None]
    light = np.hypot(xs / width - 0.32, ys / height - 0.25)
    wood *= np.clip(1.15 - 0.9 * light, 0.35, 1.15)[..., None]
    return np.clip(wood, 0, 255).astype(np.uint8)


def _paper_under(wood, centre, size, angle: float, tone: float) -> None:
    import cv2
    np = _np()
    box = cv2.boxPoints(((float(centre[0]), float(centre[1])), (float(size[0]), float(size[1])), angle))
    mask = np.zeros(wood.shape[:2], np.float32)
    cv2.fillPoly(mask, [box.astype(np.int32)], 1.0, cv2.LINE_AA)
    under = cv2.GaussianBlur(mask, (0, 0), 5)
    wood *= (1 - 0.35 * under)[..., None]
    sheet = np.array(PAPER, np.float32) * tone
    wood[:] = wood * (1 - mask[..., None]) + sheet * mask[..., None]
    # Faint panels printed on the pages underneath, so they read as more of the comic.
    turn = math.radians(angle)
    axis_x = np.array([math.cos(turn), math.sin(turn)], np.float32)
    axis_y = np.array([-math.sin(turn), math.cos(turn)], np.float32)
    for gx, gy, gw, gh in ((0.07, 0.05, 0.86, 0.36), (0.07, 0.44, 0.41, 0.24), (0.52, 0.44, 0.41, 0.24), (0.07, 0.71, 0.86, 0.24)):
        local = (np.array([gx + gw / 2, gy + gh / 2], np.float32) - 0.5) * size
        middle = centre + axis_x * local[0] + axis_y * local[1]
        panel = cv2.boxPoints(((float(middle[0]), float(middle[1])), (float(gw * size[0]), float(gh * size[1])), angle))
        cv2.fillPoly(wood, [panel.astype(np.int32)], tuple(float(c) * tone * 0.72 for c in PAPER), cv2.LINE_AA)
