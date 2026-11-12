"""A Series document card: real OFL letters on procedural paper.

``layout2d.card.kind`` ``document`` carries ``title``, ``body`` (at most 1200
characters), ``style`` (``letter``, ``typed``, ``newspaper``, ``telegram``,
``file``), optional ``date`` and ``signature``, and ``reveal`` (``static``,
``typewriter``, ``pan``). The body shrinks until it fits, and never below the
readable minimum at 1080p (28 px, scaled with the frame height). A body that
still overflows is painted at that minimum and reported as
``document_text_too_long``. ``typewriter`` reveals the body across the shot,
one share of the characters per frame. ``pan`` travels down the page. Title,
disclaimer and end cards do not come through here.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import numpy as np
from PIL import Image, ImageDraw, ImageFont

STYLES = ("letter", "typed", "newspaper", "telegram", "file")
REVEALS = ("static", "typewriter", "pan")
MIN_BODY_PX_AT_1080 = 28
_COLUMN = 0.46
_LEADING = 1.55
_MARGIN = 0.16

_ROOT = Path(__file__).resolve().parents[2] / "ui" / "public" / "fonts"
_FACE = {
    "letter": _ROOT / "caveat-latin.woff2",
    "typed": _ROOT / "CourierPrime-Regular.ttf",
    "newspaper": _ROOT / "playfair-display-latin.woff2",
    "telegram": _ROOT / "CourierPrime-Regular.ttf",
    "file": _ROOT / "playfair-display-latin.woff2",
}
_PAPER = {
    "letter": (244, 228, 196),
    "typed": (246, 242, 232),
    "newspaper": (224, 218, 204),
    "telegram": (242, 228, 168),
    "file": (230, 206, 160),
}
_INK = {
    "letter": (48, 36, 26),
    "typed": (22, 22, 22),
    "newspaper": (28, 26, 24),
    "telegram": (32, 28, 36),
    "file": (42, 32, 22),
}


class DocumentCardError(RuntimeError):
    pass


def minimum_body_px(height: int) -> int:
    """The smallest body size that stays readable. 28 px when the frame is 1080 tall."""
    return max(8, int(round(MIN_BODY_PX_AT_1080 * int(height) / 1080)))


def stored_document(card: dict[str, Any]) -> dict[str, Any]:
    """The card as a shot stores it. A bad style or reveal is refused."""
    style = card.get("style") or "letter"
    reveal = card.get("reveal") or "static"
    if style not in STYLES:
        raise ValueError("card style must be letter, typed, newspaper, telegram or file")
    if reveal not in REVEALS:
        raise ValueError("card reveal must be static, typewriter or pan")
    stored = {
        "kind": "document",
        "style": style,
        "reveal": reveal,
        "title": str(card.get("title") or "")[:200],
        "body": str(card.get("body") or "")[:1200],
    }
    for key, limit in (("date", 80), ("signature", 80)):
        text = str(card.get(key) or "").strip()
        if text:
            stored[key] = text[:limit]
    return stored


def revealed_characters(total: int, frame: int, frame_count: int) -> int:
    """How many characters of the body are on this frame. The last frame shows all of them."""
    if total <= 0 or frame_count <= 0:
        return 0
    frame = min(max(int(frame), 0), int(frame_count) - 1)
    return min(int(total), ((frame + 1) * int(total) + int(frame_count) - 1) // int(frame_count))


def pan_offset(travel: int, frame: int, frame_count: int) -> int:
    """Pixels the page has moved down by this frame. The last frame has travelled all the way."""
    if travel <= 0 or frame_count <= 1:
        return 0
    frame = min(max(int(frame), 0), int(frame_count) - 1)
    return int(travel) * frame // (int(frame_count) - 1)


def layout_document(card: dict[str, Any], *, width: int, height: int) -> dict[str, Any]:
    """Wrap the card at the largest size that fits, or at the readable minimum when it does not."""
    width, height = max(16, int(width)), max(16, int(height))
    style = card.get("style") if card.get("style") in STYLES else "letter"
    prepared = {**card, "style": style, "body": str(card.get("body") or "")[:1200]}
    minimum = minimum_body_px(height)
    preferred = max(minimum, int(round(42 * height / 1080)))
    chosen, rows, used, fits = minimum, [], 0, False
    for px in range(preferred, minimum - 1, -1):
        rows, used, overflow = _measure(prepared, px, width)
        if not overflow and used <= _available(style, height):
            chosen, fits = px, True
            break
    if not fits:
        rows, used, overflow = _measure(prepared, minimum, width)
        chosen = minimum
        fits = not overflow and used <= _available(style, height)
    return {"bodyPx": chosen, "fits": fits, "rows": rows, "used": used, "style": style,
            "body": prepared["body"], "width": width, "height": height}


def render_frame(card: dict[str, Any], frame: int, frame_count: int, *, width: int, height: int) -> Image.Image:
    """One frame of the card. The type size is the full text's, so a typewriter does not resize as it types."""
    laid = layout_document(card, width=width, height=height)
    return _frame(card, laid, _paper(laid["style"], laid["width"], laid["height"]), frame, frame_count)


def _frame(card: dict[str, Any], laid: dict[str, Any], paper: Image.Image, frame: int, frame_count: int) -> Image.Image:
    """The text of one frame on a copy of ``paper``. The paper and the layout are the same on every frame of a clip."""
    frames = max(1, int(frame_count))
    index = min(max(int(frame), 0), frames - 1)
    reveal = card.get("reveal") if card.get("reveal") in REVEALS else "static"
    body = laid["body"]
    if reveal == "typewriter":
        body = body[:revealed_characters(len(body), index, frames)]
    image = paper.copy()
    _draw(image, laid, body, index, frames, reveal)
    return image


def write_clip(card: dict[str, Any], path: Path, *, width: int, height: int, duration: float, fps: int = 24) -> None:
    """An h264 clip of the card. The paper and the layout are made once; each frame only draws its text, and a static
    reveal is one painted frame repeated. ffmpeg writes a hidden file beside ``path``, which replaces ``path`` only
    when the clip is complete: a write that fails halfway leaves nothing the cache would take."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise DocumentCardError("ffmpeg is not available")
    frames = max(1, int(round(float(duration) * int(fps))))
    reveal = card.get("reveal") if card.get("reveal") in REVEALS else "static"
    laid = layout_document(card, width=width, height=height)
    paper = _paper(laid["style"], laid["width"], laid["height"])
    temporary = path.with_name(f".{path.stem}-{uuid.uuid4().hex[:8]}{path.suffix}")
    command = [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{laid['width']}x{laid['height']}",
               "-r", str(int(fps)), "-i", "pipe:0", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", str(temporary)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    painted = None
    try:
        for frame in range(frames):
            if painted is None or reveal != "static":
                painted = _frame(card, laid, paper, frame, frames).tobytes()
            process.stdin.write(painted)
        process.stdin.close()
        _stderr = process.stderr.read()
        if process.wait(timeout=180) != 0:
            raise DocumentCardError("ffmpeg could not write the document")
        os.replace(temporary, path)
    except Exception:
        process.kill()
        raise
    finally:
        temporary.unlink(missing_ok=True)


def document_plate(root: str, shot: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any] | None:
    """The paper clip for a document shot, served from the workspace, or None for any other card."""
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    card = layout.get("card") if isinstance(layout.get("card"), dict) else None
    if not card or card.get("kind") != "document":
        return None
    width, height = int(spec["width"]), int(spec["height"])
    duration, fps = float(spec["duration"]), int(spec.get("fps") or 24)
    digest = hashlib.sha1(repr((card, width, height, round(duration, 3), fps)).encode()).hexdigest()[:16]
    folder = Path(root) / "series-documents"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{digest}.mp4"
    if not path.is_file():
        write_clip(card, path, width=width, height=height, duration=max(0.2, duration), fps=fps)
    workspace = str(spec.get("workspace") or "")
    source = f"/api/v1/file/{quote(f'series-documents/{digest}.mp4')}?workspace={quote(workspace)}"
    return {"source": source, "kind": "video", "focusX": 50.0}


def _load(style: str, px: int) -> ImageFont.FreeTypeFont:
    path = _FACE[style]
    if not path.is_file():
        raise DocumentCardError(f"missing face {path.name}")
    return ImageFont.truetype(str(path), max(8, int(px)))


def _wrap(text: str, font: ImageFont.FreeTypeFont, column: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines, line = [], words[0]
    for word in words[1:]:
        trial = f"{line} {word}"
        if font.getlength(trial) <= column:
            line = trial
        else:
            lines.append(line)
            line = word
    lines.append(line)
    return lines


def _line_overflow(lines: list[str], font: ImageFont.FreeTypeFont, column: int) -> bool:
    return any(font.getlength(line) > column + 0.5 for line in lines)


def _measure(card: dict[str, Any], px: int, width: int) -> tuple[list, int, bool]:
    style = card["style"]
    column = max(40, int(width * _COLUMN))
    body_font = _load(style, px)
    title_font = _load(style, max(px, int(round(px * 1.15))))
    small = _load(style, max(8, int(round(px * 0.85))))
    gap = max(6, px // 3)
    rows: list = []
    used, overflow = 0, False
    fields = (
        (str(card.get("title") or "").strip(), title_font, gap),
        (str(card.get("date") or "").strip(), small, gap),
        (str(card.get("body") or "").strip(), body_font, gap),
        (str(card.get("signature") or "").strip(), small, 0),
    )
    roles = ("title", "date", "body", "signature")
    for role, (text, font, after) in zip(roles, fields):
        if not text:
            continue
        lines = _wrap(text, font, column)
        overflow = overflow or _line_overflow(lines, font, column)
        line_height = max(1, int(round(px * _LEADING)))
        for line in lines:
            rows.append((role, line, font, used))
            used += line_height
        used += after
    return rows, used, overflow


def _available(style: str, height: int) -> int:
    margin = int(height * _MARGIN) * 2
    seal = int(height * 0.2) if style == "file" else 0
    return height - margin - seal


def _paper(style: str, width: int, height: int) -> Image.Image:
    color = _PAPER.get(style, _PAPER["letter"])
    seed = int.from_bytes(hashlib.sha1(f"{style}:{width}:{height}".encode()).digest()[:4], "big")
    rng = np.random.default_rng(seed)
    plane = np.empty((height, width, 3), dtype=np.int16)
    plane[:] = color
    plane += rng.integers(-12, 13, size=(height, width, 1), dtype=np.int16)
    y = np.linspace(0, 1, height)[:, None]
    x = np.linspace(0, 1, width)[None, :]
    edge = np.minimum(np.minimum(x, 1 - x), np.minimum(y, 1 - y))
    plane -= (10 - np.clip(edge * 50, 0, 10)).astype(np.int16)[..., None]
    for _stain in range(5):
        cy, cx = int(rng.integers(0, height)), int(rng.integers(0, width))
        radius = int(rng.integers(max(4, height // 14), max(5, height // 5)))
        shade = int(rng.integers(-22, 6))
        yy, xx = np.ogrid[:height, :width]
        plane[(yy - cy) ** 2 + (xx - cx) ** 2 <= radius ** 2] += shade
    np.clip(plane, 0, 255, out=plane)
    return Image.fromarray(plane.astype(np.uint8))


def _draw(image: Image.Image, laid: dict[str, Any], body: str, frame: int, frame_count: int, reveal: str) -> None:
    style, width, height = laid["style"], laid["width"], laid["height"]
    travel = max(0, int(laid["used"]) - _available(style, height))
    if reveal == "pan":
        travel = max(travel, int(height * 0.08))
    offset = pan_offset(travel, frame, frame_count) if reveal == "pan" else 0
    draw = ImageDraw.Draw(image)
    column = max(40, int(width * _COLUMN))
    x = (width - column) / 2
    top = int(height * _MARGIN) - offset
    ink = _INK.get(style, _INK["letter"])
    font = _load(style, laid["bodyPx"])
    body_lines = _wrap(body, font, column)
    body_index = 0
    for role, line, face, y_rel in laid["rows"]:
        if role == "body":
            if body_index >= len(body_lines):
                continue
            line = body_lines[body_index]
            body_index += 1
        draw.text((x, top + y_rel), line, font=face, fill=ink)
    _chrome(draw, laid, x, top, column, ink)
    if style == "file":
        _seal(draw, width, height)


def _chrome(draw: ImageDraw.ImageDraw, laid: dict[str, Any], x: float, top: int, column: int, ink: tuple[int, int, int]) -> None:
    """Title, date and signature stay put in the measured rows. The body is drawn by the caller from the reveal."""
    style = laid["style"]
    if style == "newspaper":
        draw.line((x, top - 6, x + column, top - 6), fill=ink, width=2)
    if style == "telegram":
        label = _load(style, max(12, laid["bodyPx"]))
        draw.text((x, max(4, top - laid["bodyPx"] - 8)), "TELEGRAMA", font=label, fill=ink)


def _seal(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    radius = max(18, int(height * 0.065))
    cx, cy = int(width * 0.78), int(height * 0.84)
    red = (138, 36, 36)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=red, width=max(2, radius // 12))
    font = _load("typed", max(10, radius // 4))
    draw.text((cx, cy), "ARCHIVO", font=font, fill=red, anchor="mm")
