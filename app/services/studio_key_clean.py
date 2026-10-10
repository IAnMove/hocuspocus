"""Adaptive screen key for ``studio.key``: no haze, no spill.

A generated "green screen" is rarely pure green. A backdrop of (48, 155, 80)
is only 0.29 green over its other channels, and the fixed key (transparent
from 0.37) leaves it at alpha 80: the whole background becomes a coloured
haze. This module reads the screen from the image border instead:

1. ``measure_screen`` takes the border ring's screen-like pixels and returns
   their median colour and how strongly they lean to the screen channel.
2. ``clean_rgba`` keys relative to that strength (transparent from 75 % of
   it, opaque below 35 %; a strong screen keeps the fixed key's numbers),
   then clears every backdrop pixel connected to the border that is at least
   half as screen-coloured (a vignetted corner, a shadow on the screen).
3. Edge pixels are decontaminated (the screen colour is subtracted by their
   alpha) and the screen channel is clamped, which removes the screen's spill
   from the figure's rim.

``KeyReport`` counts the result: the share of semi-transparent pixels (alpha
6-199) left in the image is the haze an agent should look at.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_FIXED_START = 0.12
_FIXED_END = 0.37
_OPAQUE_SHARE = 0.35
_CLEAR_SHARE = 0.75
_FLOOD_SHARE = 0.5
_SCREEN_LIKE = 0.05
_MIN_STRENGTH = 0.12
_MIN_BORDER_SHARE = 0.25
_DESPILL_GAIN = 1.02
_DESPILL_LIFT = 0.02
_SEMI_LOW = 5
_SEMI_HIGH = 200
HAZE_SHARE = 0.2


@dataclass(frozen=True)
class Screen:
    """The screen as the border shows it: its colour (0-1 RGB) and strength."""

    color: tuple[float, float, float]
    strength: float

    @property
    def hex(self) -> str:
        return "#" + "".join(f"{int(round(channel * 255)):02x}" for channel in self.color)


def keyness(color: np.ndarray, screen: str) -> np.ndarray:
    """How much each pixel leans to the screen channel, -1..1."""
    red, green, blue = color[..., 0], color[..., 1], color[..., 2]
    if screen == "magenta":
        return np.minimum(red, blue) - green
    if screen == "blue":
        return blue - np.maximum(red, green)
    return green - np.maximum(red, blue)


def _ring(height: int, width: int) -> np.ndarray:
    thickness = max(1, min(height, width) // 100)
    ring = np.zeros((height, width), dtype=bool)
    ring[:thickness], ring[-thickness:] = True, True
    ring[:, :thickness], ring[:, -thickness:] = True, True
    return ring


def measure_screen(rgb: np.ndarray, screen: str) -> Screen | None:
    """The screen colour from the border ring, or None when the border shows no screen."""
    color = np.asarray(rgb, dtype=np.float32)[..., :3] / 255.0
    ring = _ring(*color.shape[:2])
    border, lean = color[ring], keyness(color, screen)[ring]
    screen_like = lean > _SCREEN_LIKE
    if not screen_like.any() or screen_like.mean() < _MIN_BORDER_SHARE:
        return None
    strength = float(np.median(lean[screen_like]))
    if strength < _MIN_STRENGTH:
        return None
    median = np.median(border[screen_like], axis=0)
    return Screen(color=(float(median[0]), float(median[1]), float(median[2])), strength=strength)


def thresholds(found: Screen | None) -> tuple[float, float]:
    """Where the matte starts and ends; a strong (or unknown) screen keeps the fixed key."""
    if found is None:
        return _FIXED_START, _FIXED_END
    return min(_FIXED_START, _OPAQUE_SHARE * found.strength), min(_FIXED_END, _CLEAR_SHARE * found.strength)


def _border_connected(mask: np.ndarray) -> np.ndarray | None:
    """Pixels of ``mask`` connected to the image border; None without scipy."""
    try:
        from scipy import ndimage
    except ImportError:
        return None
    labels, count = ndimage.label(mask)
    if count == 0:
        return np.zeros_like(mask)
    ring = _ring(*mask.shape)
    touching = np.unique(labels[ring & mask])
    return np.isin(labels, touching[touching > 0])


def _decontaminate(color: np.ndarray, alpha: np.ndarray, found: Screen) -> np.ndarray:
    """Take the screen colour out of edge pixels: observed = alpha * figure + (1 - alpha) * screen."""
    edge = (alpha > 0.02) & (alpha < 0.98)
    if not edge.any():
        return color
    cleaned = np.array(color, copy=True)
    plate = np.asarray(found.color, dtype=np.float32)
    weight = alpha[edge][:, None]
    cleaned[edge] = np.clip((color[edge] - (1.0 - weight) * plate) / weight, 0.0, 1.0)
    return cleaned


def despill(color: np.ndarray, screen: str) -> np.ndarray:
    """Clamp the screen channel(s) to the others, as the fixed key does."""
    out = np.array(color, copy=True)
    red, green, blue = color[..., 0], color[..., 1], color[..., 2]
    if screen == "magenta":
        excess = np.clip(np.minimum(red, blue) - (green * _DESPILL_GAIN + _DESPILL_LIFT), 0.0, None)
        out[..., 0], out[..., 2] = red - excess, blue - excess
        return out
    index = 1 if screen == "green" else 2
    others = np.maximum(red, blue) if index == 1 else np.maximum(red, green)
    out[..., index] = np.minimum(color[..., index], others * _DESPILL_GAIN + _DESPILL_LIFT)
    return out


@dataclass
class KeyOptions:
    screen: str = "green"
    adaptive: bool = True
    despill: bool = True


def clean_rgba(rgb: np.ndarray, options: KeyOptions, found: Screen | None) -> tuple[np.ndarray, bool]:
    """Key one RGB frame against the measured screen. Returns RGBA and whether the border flood ran."""
    color = np.asarray(rgb, dtype=np.float32)[..., :3] / 255.0
    lean = keyness(color, options.screen)
    start, end = thresholds(found if options.adaptive else None)
    alpha = 1.0 - np.clip((lean - start) / max(end - start, 1e-6), 0.0, 1.0)
    flooded = False
    if options.adaptive and found is not None:
        backdrop = _border_connected(lean >= _FLOOD_SHARE * found.strength)
        if backdrop is not None:
            alpha[backdrop] = 0.0
            flooded = True
    if options.despill:
        if options.adaptive and found is not None:
            color = _decontaminate(color, alpha, found)
        color = despill(color, options.screen)
    rgba = np.concatenate([color, alpha[..., None]], axis=-1)
    return np.clip(np.rint(rgba * 255.0), 0, 255).astype(np.uint8), flooded


class KeyReport:
    """Counts of the keyed alpha over every frame, and what the key read from the border."""

    def __init__(self, options: KeyOptions | None, found: Screen | None) -> None:
        self.options, self.found = options, found
        self.pixels = self.transparent = self.semi = 0
        self.flooded = False

    def add(self, alpha: np.ndarray, flooded: bool = False) -> None:
        self.pixels += int(alpha.size)
        self.transparent += int(np.count_nonzero(alpha <= _SEMI_LOW))
        self.semi += int(np.count_nonzero((alpha > _SEMI_LOW) & (alpha < _SEMI_HIGH)))
        self.flooded = self.flooded or flooded

    def as_dict(self) -> dict:
        semi = round(self.semi / self.pixels, 4) if self.pixels else 0.0
        report = {
            "semiTransparentShare": semi,
            "transparentShare": round(self.transparent / self.pixels, 4) if self.pixels else 0.0,
            "haze": semi >= HAZE_SHARE,
        }
        if self.options is None:
            return report
        report.update({
            "adaptive": self.options.adaptive, "despill": self.options.despill, "borderFlood": self.flooded,
            "screenColor": self.found.hex if self.found else None,
            "screenStrength": round(self.found.strength, 3) if self.found else None,
        })
        if self.options.adaptive and self.found is None:
            report["note"] = "No screen colour on the image border: the fixed key was used."
        if report["haze"]:
            report["note"] = ("A large share of the image is semi-transparent: the screen is uneven or the wrong "
                              "mode was used. Try another mode, or regenerate the image on a flatter screen.")
        return report
