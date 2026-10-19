"""To calibrate a plate's stage (``series_stage``) by looking: a grid drawn over it and a cheap guess of the horizon.

``grid_image`` draws lines every 10 % of the plate (labelled with the fraction, from the top and from the left, with small ticks
every 2 % on the edges) so the person calibrating reads ``horizon``, the base and the top of a reference object off the picture
instead of guessing them. With a stage (the saved one, or a proposal) it also draws what that stage says: the horizon, the
reference's base and top, the far floor line and three 1.75 m scale bars at depth 0, 0.5 and 1, so one can see at a glance
whether the numbers fit the picture before saving them.

``suggest_horizon`` is a help, not the truth. An interior has no visible horizon (it is where the camera's eye height falls, about
1.6 m up any wall), and a painted plate is rarely in correct perspective. It tries two cheap things and says how far to trust them:
the point where slanted straight lines (floor boards, wall bases, ceiling edges) converge, and the strongest horizontal boundary
(sky and ground in an open place). In a room the second one finds the wall-floor junction, not the horizon: the suggestion says so.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from services import series_stage as stage_math

MAX_WIDTH = 1280
STEPS = (0.05, 0.25)
# Where the scale bars stand (x, depth) and the height they show.
BARS = ((0.2, 0.0), (0.5, 0.5), (0.8, 1.0))
BAR_M = 1.75
_WORK_WIDTH = 640
_MIN_ANGLE, _MAX_ANGLE = 10.0, 80.0
_MAX_LINES = 220


def load_plate(path: str | Path) -> Image.Image:
    with Image.open(path) as opened:
        return opened.convert("RGB")


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow before 10.1 has one size only
        return ImageFont.load_default()


def _label(draw: ImageDraw.ImageDraw, at: tuple[float, float], text: str, font: ImageFont.ImageFont, ink: tuple[int, int, int]) -> None:
    left, top, right, bottom = draw.textbbox(at, text, font=font)
    draw.rectangle((left - 2, top - 1, right + 2, bottom + 1), fill=(0, 0, 0))
    draw.text(at, text, font=font, fill=ink)


def _grid(draw: ImageDraw.ImageDraw, size: tuple[int, int], step: float, font: ImageFont.ImageFont) -> None:
    width, height = size
    count = int(round(1 / step))
    for index in range(1, count):
        value = index * step
        y, x = round(value * height), round(value * width)
        major = abs(value * 2 - round(value * 2)) < 1e-6
        draw.line((0, y, width, y), fill=(255, 235, 0), width=2 if major else 1)
        draw.line((x, 0, x, height), fill=(0, 220, 255), width=2 if major else 1)
        _label(draw, (4, y + 2), f"{value:.2f}".rstrip("0").rstrip("."), font, (255, 235, 0))
        _label(draw, (x + 3, 3), f"{value:.2f}".rstrip("0").rstrip("."), font, (0, 220, 255))
    for tick in range(0, 51):
        y = round(tick * 0.02 * height)
        long = tick % 5 == 0
        draw.line((0, y, 12 if long else 6, y), fill=(255, 235, 0), width=1)
        draw.line((width - (12 if long else 6), y, width, y), fill=(255, 235, 0), width=1)


def _hline(draw: ImageDraw.ImageDraw, size: tuple[int, int], value: float, text: str, font: ImageFont.ImageFont,
           ink: tuple[int, int, int], width: int = 3, dashed: bool = False) -> None:
    w, h = size
    y = round(value * h)
    if dashed:
        for start in range(0, w, 24):
            draw.line((start, y, min(w, start + 12), y), fill=ink, width=width)
    else:
        draw.line((0, y, w, y), fill=ink, width=width)
    _label(draw, (w - 8 - draw.textlength(text, font=font), y - 18 if y > 22 else y + 3), text, font, ink)


def _stage(draw: ImageDraw.ImageDraw, size: tuple[int, int], stage: dict[str, Any], font: ImageFont.ImageFont) -> None:
    ref = stage["ref"]
    _hline(draw, size, stage["horizon"], f"horizon {stage['horizon']:g}", font, (255, 0, 255))
    _hline(draw, size, ref["baseY"], f"ref base {ref['baseY']:g}", font, (60, 255, 60))
    _hline(draw, size, ref["baseY"] - ref["heightPct"], f"ref top {ref['baseY'] - ref['heightPct']:.2f} ({ref['heightM']:g} m)", font, (60, 255, 60), dashed=True)
    far = stage.get("floorTop", ref["baseY"])
    if far != ref["baseY"]:
        _hline(draw, size, far, f"far floor {far:g}", font, (255, 140, 0))
    width, height = size
    for x, depth in BARS:
        feet = far + (stage_math.FEET / 100 - far) * depth
        top = feet - stage_math.perspective_height(stage, BAR_M, feet)
        px = round(x * width)
        draw.line((px, round(feet * height), px, round(top * height)), fill=(255, 60, 60), width=5)
        draw.line((px - 14, round(top * height), px + 14, round(top * height)), fill=(255, 60, 60), width=5)
        draw.line((px - 14, round(feet * height), px + 14, round(feet * height)), fill=(255, 60, 60), width=5)
        _label(draw, (px + 10, round(top * height)), f"{BAR_M:g} m, depth {depth:g}", font, (255, 120, 120))


def grid_image(image: Image.Image, *, step: float = 0.1, stage: dict[str, Any] | None = None) -> Image.Image:
    """The plate (at most ``MAX_WIDTH`` wide) with lines every ``step`` of it and, given a ``stage``, what the stage says."""
    if not STEPS[0] <= step <= STEPS[1]:
        raise ValueError(f"step must be from {STEPS[0]} to {STEPS[1]} (a fraction of the plate)")
    scaled = image.convert("RGB")
    if scaled.width > MAX_WIDTH:
        scaled = scaled.resize((MAX_WIDTH, round(scaled.height * MAX_WIDTH / scaled.width)), Image.LANCZOS)
    layer = Image.new("RGBA", scaled.size, (0, 0, 0, 0))
    draw, font = ImageDraw.Draw(layer), _font(max(12, scaled.height // 36))
    _grid(draw, scaled.size, step, font)
    if stage:
        _stage(draw, scaled.size, stage, font)
    return Image.alpha_composite(scaled.convert("RGBA"), layer).convert("RGB")


# The horizon guess ----------------------------------------------------------------------------------------------------------


def _work(image: Image.Image) -> np.ndarray:
    small = image.convert("L")
    if small.width > _WORK_WIDTH:
        small = small.resize((_WORK_WIDTH, round(small.height * _WORK_WIDTH / small.width)), Image.BILINEAR)
    return np.asarray(small, dtype=np.float32)


def _slanted_lines(gray: np.ndarray) -> list[tuple[float, float, float, float, float]]:
    """Straight segments (x1, y1, x2, y2, length) that slope between 10 and 80 degrees: the ones that can recede to a horizon."""
    try:
        import cv2
    except ImportError:
        return []
    picture = gray.astype(np.uint8)
    median = float(np.median(picture))
    edges = cv2.Canny(cv2.GaussianBlur(picture, (3, 3), 0), max(10, 0.66 * median), max(40, 1.33 * median))
    width = gray.shape[1]
    found = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=50, minLineLength=int(width * 0.08), maxLineGap=int(width * 0.012))
    lines = []
    for x1, y1, x2, y2 in (found[:, 0] if found is not None else []):
        angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        angle = min(angle, 180 - angle)
        if _MIN_ANGLE <= angle <= _MAX_ANGLE:
            lines.append((float(x1), float(y1), float(x2), float(y2), float(np.hypot(x2 - x1, y2 - y1))))
    return sorted(lines, key=lambda line: -line[4])[:_MAX_LINES]


def _crossings(lines: list[tuple[float, float, float, float, float]], size: tuple[int, int]) -> list[tuple[float, float, int, int]]:
    """(y as a fraction of the height, weight, line a, line b) where two lines of clearly different slope meet near the picture."""
    height, width = size
    found = []
    for a in range(len(lines)):
        ax1, ay1, ax2, ay2, alen = lines[a]
        for b in range(a + 1, len(lines)):
            bx1, by1, bx2, by2, blen = lines[b]
            denominator = (ax1 - ax2) * (by1 - by2) - (ay1 - ay2) * (bx1 - bx2)
            if abs(denominator) < 1e-6:
                continue
            cross_a, cross_b = ax1 * ay2 - ay1 * ax2, bx1 * by2 - by1 * bx2
            x = (cross_a * (bx1 - bx2) - (ax1 - ax2) * cross_b) / denominator
            y = (cross_a * (by1 - by2) - (ay1 - ay2) * cross_b) / denominator
            if -width <= x <= 2 * width and 0 <= y <= 0.95 * height:
                found.append((y / height, min(alen, blen), a, b))
    return found


def _vanishing(gray: np.ndarray) -> dict[str, Any] | None:
    lines = _slanted_lines(gray)
    if len(lines) < 4:
        return None
    crossings = _crossings(lines, gray.shape)
    if not crossings:
        return None
    ys = np.array([item[0] for item in crossings])
    weights = np.array([item[1] for item in crossings])
    bins = np.arange(0, 0.96, 0.01)
    score = np.array([weights[np.abs(ys - center) <= 0.02].sum() for center in bins])
    peak = float(bins[int(np.argmax(score))])
    near = np.abs(ys - peak) <= 0.03
    if not near.any():
        return None
    horizon = float(np.average(ys[near], weights=weights[near]))
    supporting = {index for item, inside in zip(crossings, near) if inside for index in item[2:]}
    share = float(weights[near].sum() / weights.sum())
    confidence = "medium" if len(supporting) >= 8 and share >= 0.3 else "low"
    return {"kind": "converging_lines", "horizon": round(horizon, 3), "confidence": confidence, "lines": len(supporting), "share": round(share, 2)}


def _strongest_edge(gray: np.ndarray) -> dict[str, Any] | None:
    rows = gray.mean(axis=1)
    height = len(rows)
    window = max(3, round(height * 0.015))
    scores = np.zeros(height)
    for y in range(window, height - window):
        scores[y] = abs(rows[y:y + window].mean() - rows[y - window:y].mean())
    low, high = round(height * 0.05), round(height * 0.9)
    inside = scores[low:high]
    if not inside.size or inside.max() < 2:
        return None
    y = low + int(np.argmax(inside))
    typical = float(np.median(inside)) + 1e-3
    return {"kind": "horizontal_edge", "horizon": round(y / height, 3), "confidence": "low", "contrast": round(float(inside.max() / typical), 1)}


def suggest_horizon(image: Image.Image) -> dict[str, Any]:
    """{"suggestion": {horizon, kind, confidence} | None, "candidates": [...], "note": str}: a guess to check against the grid.

    Converging lines (floor boards, wall bases) give the horizon of a room or a street; the strongest horizontal boundary gives the
    horizon of an open place (sky meeting ground) and, in a room, the wall-floor junction, which is NOT the horizon."""
    gray = _work(image)
    candidates = [item for item in (_vanishing(gray), _strongest_edge(gray)) if item]
    lines = next((item for item in candidates if item["kind"] == "converging_lines" and item["confidence"] == "medium"), None)
    chosen = lines or next(iter(candidates), None)
    note = ("A guess, not the truth. A room has no visible horizon: it is the camera's eye height, about 1.6 m up any wall, so read it "
            "from the grid (a person that tall has their eyes on it at any distance). A horizontal edge in a room is the wall-floor junction.")
    return {"suggestion": chosen, "candidates": candidates, "note": note}
