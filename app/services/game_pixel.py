"""Deterministic pixel-art post process.

``to_pixel`` follows the game-assets brief, section 3.6, in that order.
OKLab ΔE is the Euclidean distance times 100, so a threshold of 10 is an
OKLab distance of 0.10.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

_BAYER_4 = np.array(
    [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
    dtype=np.float32,
)
_BAYER_OFFSET = (_BAYER_4 + 0.5) / 16.0 - 0.5
# Pixels per nearest-color pass. The N×K×3 difference array stays near 12 MB at 16 colors.
_CHUNK = 65536


def _as_rgba(image: Any) -> np.ndarray:
    if isinstance(image, Image.Image):
        return np.asarray(image.convert("RGBA"))
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[2] not in (3, 4):
        raise ValueError("expected an RGB or RGBA image")
    if array.shape[2] == 3:
        alpha = np.full(array.shape[:2] + (1,), 255, dtype=np.uint8)
        array = np.concatenate([array.astype(np.uint8), alpha], axis=2)
    return np.asarray(array, dtype=np.uint8)


def _srgb_to_linear(channel: np.ndarray) -> np.ndarray:
    value = channel.astype(np.float32) / 255.0
    return np.where(value <= 0.04045, value / 12.92, ((value + 0.055) / 1.055) ** 2.4)


def oklab(rgb_array: np.ndarray) -> np.ndarray:
    """Convert uint8 RGB (any shape ending in 3) to OKLab."""
    red, green, blue = (_srgb_to_linear(rgb_array[..., index]) for index in range(3))
    long = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue
    medium = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue
    short = 0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue
    long, medium, short = np.cbrt(long), np.cbrt(medium), np.cbrt(short)
    lightness = 0.2104542553 * long + 0.7936177850 * medium - 0.0040720468 * short
    green_red = 1.9779984951 * long - 2.4285922050 * medium + 0.4505937099 * short
    blue_yellow = 0.0259040371 * long + 0.7827717662 * medium - 0.8086757660 * short
    return np.stack([lightness, green_red, blue_yellow], axis=-1).astype(np.float32)


def _parse_palette(palette: list[str]) -> np.ndarray:
    colors = []
    for item in palette:
        text = item.strip().lstrip("#")
        if len(text) != 6:
            raise ValueError(f"palette color must be #rrggbb, got {item}")
        colors.append([int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)])
    return np.asarray(colors, dtype=np.uint8)


def _hex_color(rgb: np.ndarray) -> str:
    red, green, blue = (int(channel) for channel in rgb)
    return f"#{red:02x}{green:02x}{blue:02x}"


def _nearest(flat_lab: np.ndarray, palette_lab: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Nearest palette index and its OKLab distance per row, ``_CHUNK`` rows at a time."""
    count = flat_lab.shape[0]
    index = np.empty(count, dtype=np.intp)
    distance = np.empty(count, dtype=np.float32)
    for start in range(0, count, _CHUNK):
        part = flat_lab[start:start + _CHUNK]
        norms = np.linalg.norm(part[:, None, :] - palette_lab[None, :, :], axis=2)
        index[start:start + _CHUNK] = norms.argmin(axis=1)
        distance[start:start + _CHUNK] = norms.min(axis=1)
    return index, distance


def nearest_palette(rgb: np.ndarray, palette_lab: np.ndarray) -> np.ndarray:
    """Index of the nearest OKLab palette color for every RGB pixel."""
    index, _ = _nearest(oklab(rgb).reshape(-1, 3), palette_lab)
    return index.reshape(rgb.shape[:-1])


def median_cut(rgba: np.ndarray, colors: int) -> list[str]:
    """Deterministic median cut of the opaque pixels. The same image returns the same list."""
    image = _as_rgba(rgba)
    opaque = image[image[..., 3] >= 128][..., :3].astype(np.float32)
    if colors <= 0 or len(opaque) == 0:
        return []
    buckets = [opaque]
    while len(buckets) < colors:
        spans = []
        for bucket in buckets:
            span = bucket.max(axis=0) - bucket.min(axis=0) if len(bucket) else np.zeros(3)
            spans.append(float(span.max()) if len(bucket) > 1 else -1.0)
        chosen = int(np.argmax(spans))
        if spans[chosen] <= 0:
            break
        bucket = buckets.pop(chosen)
        channel = int(np.argmax(bucket.max(axis=0) - bucket.min(axis=0)))
        ordered = bucket[np.argsort(bucket[:, channel], kind="mergesort")]
        middle = len(ordered) // 2
        buckets.append(ordered[:middle])
        buckets.append(ordered[middle:])
    found = []
    for bucket in buckets:
        mean = np.clip(np.rint(bucket.mean(axis=0)), 0, 255).astype(np.uint8)
        found.append(_hex_color(mean))
    return found


def _majority(colors: np.ndarray, opaque: np.ndarray) -> np.ndarray:
    """Replace an opaque color that matches none of its 8 neighbors with the neighbor mode."""
    padded = np.pad(colors, 1, constant_values=-1)
    opaque_pad = np.pad(opaque, 1, constant_values=False)
    updated = colors.copy()
    ys, xs = np.nonzero(opaque)
    for y, x in zip(ys.tolist(), xs.tolist()):
        window = padded[y:y + 3, x:x + 3].copy()
        mask = opaque_pad[y:y + 3, x:x + 3].copy()
        window[1, 1] = -1
        mask[1, 1] = False
        neighbors = window[mask]
        if len(neighbors) == 0 or np.any(neighbors == colors[y, x]):
            continue
        values, counts = np.unique(neighbors, return_counts=True)
        updated[y, x] = int(values[int(np.argmax(counts))])
    return updated


def _outline(index: np.ndarray, opaque: np.ndarray, outline: str, darkest: int) -> tuple[np.ndarray, np.ndarray]:
    """Paint ``darkest`` on every transparent pixel with an opaque 4-neighbor."""
    if outline in (None, "none", ""):
        return index, opaque
    if outline not in ("dark-1px", "black-1px"):
        raise ValueError(f"unknown outline {outline}")
    padded = np.pad(opaque, 1, constant_values=False)
    touches = (
        padded[0:-2, 1:-1] | padded[2:, 1:-1] | padded[1:-1, 0:-2] | padded[1:-1, 2:]
    )
    paint = ~opaque & touches
    next_index = index.copy()
    next_opaque = opaque.copy()
    next_index[paint] = darkest
    next_opaque[paint] = True
    return next_index, next_opaque


def _bayer_shift(rgb: np.ndarray, strength: float) -> np.ndarray:
    """Add the 4×4 Bayer offset, ±32 levels at strength 1, to unsnapped RGB."""
    height, width = rgb.shape[:2]
    tile = np.tile(_BAYER_OFFSET, (height // 4 + 1, width // 4 + 1))[:height, :width]
    shifted = np.clip(rgb.astype(np.float32) + tile[..., None] * (64.0 * float(strength)), 0, 255)
    return np.rint(shifted).astype(np.uint8)


def bayer_dither(rgb: np.ndarray, palette: np.ndarray, strength: float) -> np.ndarray:
    """Ordered 4×4 dither of unsnapped RGB, then snap onto the palette."""
    if strength <= 0:
        return rgb
    palette_lab = oklab(palette.reshape(-1, 1, 3)).reshape(-1, 3)
    return palette[nearest_palette(_bayer_shift(rgb, strength), palette_lab)]


def _downscale(image: np.ndarray, scale: int) -> np.ndarray:
    factor = max(1, int(scale))
    if factor == 1:
        return image
    height = max(1, image.shape[0] // factor)
    width = max(1, image.shape[1] // factor)
    return np.asarray(Image.fromarray(image).resize((width, height), Image.Resampling.BOX))


def _resolve_palette(rgb: np.ndarray, binary: np.ndarray, palette: list[str] | None, colors: int) -> np.ndarray:
    if palette:
        return _parse_palette(palette)
    alpha = np.where(binary, 255, 0).astype(np.uint8)
    found = _parse_palette(median_cut(np.concatenate([rgb, alpha[..., None]], axis=2), colors))
    return found if len(found) else np.zeros((1, 3), dtype=np.uint8)


def _dither_strength(dither: bool | float) -> float:
    if dither is True:
        return 1.0
    return max(0.0, float(dither or 0.0))


def _interior_index(rgb: np.ndarray, opaque: np.ndarray, palette_lab: np.ndarray, strength: float) -> np.ndarray:
    """Palette index of the opaque pixels.

    With dither the Bayer offset moves the reduced RGB before the
    nearest-color step, and the 8-neighbor majority clean is skipped so the
    pattern survives. Without dither it is the nearest color plus that clean.
    """
    index = np.zeros(opaque.shape, dtype=np.int16)
    if not opaque.any():
        return index
    if strength > 0:
        index[opaque] = nearest_palette(_bayer_shift(rgb, strength)[opaque], palette_lab)
        return index
    index[opaque] = nearest_palette(rgb[opaque], palette_lab)
    return _majority(index, opaque)


def _outline_palette(palette_rgb: np.ndarray, palette_lab: np.ndarray, outline: str) -> tuple[np.ndarray, int]:
    """Palette for the output and the outline index: appended black, or the darkest color."""
    if outline == "black-1px":
        return np.vstack([palette_rgb, np.zeros((1, 3), dtype=np.uint8)]), len(palette_rgb)
    return palette_rgb, int(np.argmin(palette_lab[:, 0]))


def to_pixel(rgba: Any, scale: int, palette: list[str] | None, outline: str, dither: bool | float, colors: int = 16) -> np.ndarray:
    """Reduce, quantize, clean, outline and optionally dither. See section 3.6.

    Dither is applied to the reduced RGB before the nearest-palette step, so
    it changes the interior; outline pixels always keep the outline color.
    Transparent pixels come back as (0, 0, 0, 0).
    """
    reduced = _downscale(_as_rgba(rgba), scale)
    rgb = reduced[..., :3]
    binary = reduced[..., 3] >= 128
    palette_rgb = _resolve_palette(rgb, binary, palette, colors)
    palette_lab = oklab(palette_rgb.reshape(-1, 1, 3)).reshape(-1, 3)
    opaque = binary & (_neighbor_count(binary) >= 2)
    index = _interior_index(rgb, opaque, palette_lab, _dither_strength(dither))
    output_rgb, darkest = _outline_palette(palette_rgb, palette_lab, outline)
    index, visible = _outline(index, opaque, outline, darkest)
    color = output_rgb[index]
    color[~visible] = 0
    return np.concatenate([color, np.where(visible, 255, 0).astype(np.uint8)[..., None]], axis=2)


def _neighbor_count(opaque: np.ndarray) -> np.ndarray:
    padded = np.pad(opaque, 1, constant_values=False)
    height, width = opaque.shape
    count = np.zeros((height, width), dtype=np.int16)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            count += padded[1 + dy:1 + dy + height, 1 + dx:1 + dx + width]
    return count


def preview_nearest(rgba: Any, factor: int = 4) -> np.ndarray:
    """Scale a pixel image up with nearest-neighbor sampling."""
    image = _as_rgba(rgba)
    scaled = Image.fromarray(image).resize(
        (image.shape[1] * factor, image.shape[0] * factor), Image.Resampling.NEAREST,
    )
    return np.asarray(scaled)


def _screen_fringe(rgb: np.ndarray, screen: str) -> np.ndarray:
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    if screen == "green":
        return (green > 180) & (red < 120) & (blue < 120)
    if screen == "blue":
        return (blue > 180) & (red < 120) & (green < 140)
    return (red > 200) & (blue > 200) & (green < 90)


def pixel_metrics(rgba_before: Any, palette: list[str], screen: str = "magenta") -> dict[str, float | int]:
    """offPalettePct, haloPct and the palette size, measured before quantization."""
    image = _as_rgba(rgba_before)
    opaque = image[..., 3] >= 128
    palette_rgb = _parse_palette(palette) if palette else np.zeros((1, 3), dtype=np.uint8)
    palette_lab = oklab(palette_rgb.reshape(-1, 1, 3)).reshape(-1, 3)
    off_palette = 0.0
    if opaque.any():
        _, distance = _nearest(oklab(image[..., :3][opaque]), palette_lab)
        off_palette = float((distance * 100.0 > 10.0).mean() * 100.0)
    fringe = opaque & (_neighbor_count(~opaque) > 0)
    halo = 0.0
    if fringe.any():
        halo = float(_screen_fringe(image[..., :3], screen)[fringe].mean() * 100.0)
    return {"offPalettePct": off_palette, "haloPct": halo, "colors": int(len(palette_rgb))}
