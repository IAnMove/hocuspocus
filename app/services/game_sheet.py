"""Pack keyed cycles into a TexturePacker sheet with Aseprite frame tags.

One animation is one row. Every cell is the same size: the largest frame,
plus ``pad`` on each side, rounded up to the pixel grid. Frames sit
bottom-center in their cell, so the atlas pivot is true for every height.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def uniform_cell(all_frames, grid, pad) -> tuple[int, int]:
    """Return ``(width, height)`` of the cell.

    Each side is the max frame side plus ``pad`` on both edges, then rounded
    up to a multiple of ``grid``.
    """
    content_w, content_h = _max_frame_size(all_frames)
    margin = int(pad) * 2
    return (_round_up(content_w + margin, grid), _round_up(content_h + margin, grid))


def pack_rows(animations, cell) -> tuple[Image.Image, dict]:
    """Place one row per animation in ``cell`` of ``(width, height)``.

    Each frame is centered horizontally and its bottom row sits on the bottom
    row of the cell, which is the atlas pivot. Frames of different heights
    therefore share the same feet line. Names must be unique: a repeated name
    raises ``ValueError``. The atlas is a TexturePacker hash plus Aseprite
    ``frameTags``. ``duration`` is ``round(1000 / fps)`` milliseconds. Tag
    ``from`` / ``to`` are inclusive indices in row-major order across the
    whole sheet.
    """
    _check_unique_names(animations)
    cell_w, cell_h = int(cell[0]), int(cell[1])
    cols = _column_count(animations)
    rows = len(animations)
    width = cell_w * cols
    height = cell_h * rows
    sheet = np.zeros((height if height > 0 else 1, width if width > 0 else 1, 4), dtype=np.uint8)
    frames_json: dict = {}
    tags: list = []
    loops: dict = {}
    cursor = 0
    for row, animation in enumerate(animations):
        cursor = _pack_row(sheet, animation, row, cell_w, cell_h, cursor, frames_json, tags, loops)
    image = Image.fromarray(sheet)
    if width > 0 and height > 0:
        image = image.crop((0, 0, width, height))
    return image, _atlas(frames_json, tags, cell_w, cell_h, width, height, loops)


def write_gif_preview(frames, fps, scale, path) -> None:
    """Write a looping GIF. Nearest-neighbor when ``scale != 1``. ``loop=0``."""
    images = [_gif_frame(_scaled_rgba(frame, scale)) for frame in frames]
    if not images:
        raise ValueError("write_gif_preview needs at least one frame")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    duration = _duration_ms(fps)
    images[0].save(
        destination,
        save_all=True,
        append_images=images[1:],
        duration=duration,
        loop=0,
        disposal=2,
        transparency=255,
        optimize=False,
    )


def _max_frame_size(frames) -> tuple[int, int]:
    width = 0
    height = 0
    for frame in frames:
        image = np.asarray(frame)
        height = max(height, int(image.shape[0]))
        width = max(width, int(image.shape[1]))
    return width, height


def _check_unique_names(animations) -> None:
    seen: set[str] = set()
    for animation in animations:
        name = str(animation["name"])
        if name in seen:
            raise ValueError(f"duplicate animation name {name!r}; frame keys and tags would collide")
        seen.add(name)


def _round_up(value: int, grid) -> int:
    size = max(0, int(value))
    step = int(grid)
    if step <= 1:
        return size
    return ((size + step - 1) // step) * step


def _column_count(animations) -> int:
    widest = 0
    for animation in animations:
        widest = max(widest, len(list(animation.get("frames") or [])))
    return widest


def _duration_ms(fps) -> int:
    rate = float(fps)
    if rate <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    return int(round(1000.0 / rate))


def _rgba_array(frame) -> np.ndarray:
    if isinstance(frame, Image.Image):
        return np.asarray(frame.convert("RGBA"))
    image = np.asarray(frame)
    if image.ndim == 3 and image.shape[2] == 4:
        return np.ascontiguousarray(image, dtype=np.uint8)
    if image.ndim == 3 and image.shape[2] == 3:
        color = np.ascontiguousarray(image, dtype=np.uint8)
        alpha = np.full(color.shape[:2] + (1,), 255, dtype=np.uint8)
        return np.concatenate([color, alpha], axis=2)
    raise ValueError("expected an RGB or RGBA frame")


def _paste_bottom_center(sheet: np.ndarray, frame, col: int, row: int, cell_w: int, cell_h: int) -> None:
    """Center the frame horizontally and put its last row on the cell's last row.

    A frame larger than the cell is clipped to the cell; the bottom rows stay.
    """
    image = _rgba_array(frame)
    src_h, src_w = image.shape[:2]
    cell_x, cell_y = col * cell_w, row * cell_h
    dst_x = cell_x + (cell_w - src_w) // 2
    dst_y = cell_y + cell_h - src_h
    src_x0 = max(0, cell_x - dst_x)
    src_y0 = max(0, cell_y - dst_y)
    dst_x0 = max(cell_x, dst_x)
    dst_y0 = max(cell_y, dst_y)
    copy_w = min(src_w - src_x0, sheet.shape[1] - dst_x0, cell_x + cell_w - dst_x0)
    copy_h = min(src_h - src_y0, sheet.shape[0] - dst_y0, cell_y + cell_h - dst_y0)
    if copy_w > 0 and copy_h > 0:
        sheet[dst_y0:dst_y0 + copy_h, dst_x0:dst_x0 + copy_w] = image[
            src_y0:src_y0 + copy_h, src_x0:src_x0 + copy_w
        ]


def _record(x: int, y: int, cell_w: int, cell_h: int, duration: int) -> dict:
    rect = {"x": int(x), "y": int(y), "w": int(cell_w), "h": int(cell_h)}
    return {
        "frame": dict(rect),
        "rotated": False,
        "trimmed": False,
        "spriteSourceSize": {"x": 0, "y": 0, "w": int(cell_w), "h": int(cell_h)},
        "sourceSize": {"w": int(cell_w), "h": int(cell_h)},
        "duration": int(duration),
    }


def _pack_row(sheet, animation, row, cell_w, cell_h, cursor, frames_json, tags, loops) -> int:
    name = str(animation["name"])
    anim_frames = list(animation.get("frames") or [])
    duration = _duration_ms(animation.get("fps", 1))
    loops[name] = bool(animation.get("loop", False))
    if anim_frames:
        tags.append({
            "name": name,
            "from": cursor,
            "to": cursor + len(anim_frames) - 1,
            "direction": "forward",
        })
    for col, frame in enumerate(anim_frames):
        _paste_bottom_center(sheet, frame, col, row, cell_w, cell_h)
        frames_json[f"{name}_{col}"] = _record(col * cell_w, row * cell_h, cell_w, cell_h, duration)
        cursor += 1
    return cursor


def _atlas(frames, tags, cell_w, cell_h, width, height, loops) -> dict:
    return {
        "frames": frames,
        "meta": {
            "app": "HocusPocus",
            "version": "1",
            "image": "",
            "format": "RGBA8888",
            "size": {"w": int(width), "h": int(height)},
            "scale": "1",
            "frameTags": tags,
            "pivot": {"x": int(cell_w) // 2, "y": int(cell_h) - 1},
            "mirror": True,
            "loop": loops,
        },
    }


def _scaled_rgba(frame, scale) -> Image.Image:
    image = Image.fromarray(_rgba_array(frame))
    factor = float(scale)
    if factor == 1:
        return image
    width = max(1, int(round(image.width * factor)))
    height = max(1, int(round(image.height * factor)))
    return image.resize((width, height), Image.Resampling.NEAREST)


def _gif_frame(image: Image.Image) -> Image.Image:
    """Palette image with index 255 reserved for pixels whose alpha is below 128."""
    rgba = image.convert("RGBA")
    colors = rgba.convert("P", palette=Image.Palette.ADAPTIVE, colors=255)
    alpha = rgba.getchannel("A")
    colors.paste(255, mask=alpha.point(lambda value: 255 if value < 128 else 0))
    return colors
