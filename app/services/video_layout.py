"""Video Editor frame fit: letterbox, cover crop, or a blurred fill.

Filter strings are built only from clamped numbers. Clip fields stay optional
so a montage saved before these knobs existed round-trips unchanged.
"""

from __future__ import annotations

from typing import Any

FITS = ("fit", "fill", "blur")
DEFAULT_FOCUS = 50.0
DEFAULT_BLUR_AMOUNT = 0.65
DEFAULT_BACKGROUND_DIM = 0.4
_KNOBS = (
    ("focus_x", "focusX", 0.0, 100.0),
    ("focus_y", "focusY", 0.0, 100.0),
    ("blur_amount", "blurAmount", 0.0, 1.0),
    ("background_dim", "backgroundDim", 0.0, 1.0),
)


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _clamp(number: float, low: float, high: float) -> float:
    return max(low, min(high, number))


def stamp_layout(clip: dict[str, Any]) -> dict[str, Any]:
    """Canonicalise ``fit`` and optional snake_case knobs on an export clip."""
    fit = clip.get("fit")
    clip["fit"] = fit if fit in FITS else "fit"
    for snake, camel, low, high in _KNOBS:
        present = snake in clip or camel in clip
        raw = clip.get(snake) if snake in clip else clip.get(camel)
        clip.pop(camel, None)
        if not present:
            continue
        number = _optional_float(raw)
        if number is None:
            clip.pop(snake, None)
            continue
        clip[snake] = _clamp(number, low, high)
    return clip


def read_layout(clip: dict[str, Any]) -> tuple[str, float, float, float, float]:
    """Return fit plus focus and blur knobs, using defaults when omitted."""
    stamped = stamp_layout(dict(clip))
    return (
        str(stamped["fit"]),
        float(stamped.get("focus_x", DEFAULT_FOCUS)),
        float(stamped.get("focus_y", DEFAULT_FOCUS)),
        float(stamped.get("blur_amount", DEFAULT_BLUR_AMOUNT)),
        float(stamped.get("background_dim", DEFAULT_BACKGROUND_DIM)),
    )


def _fit_chain(width: int, height: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        "setsar=1,format=yuv420p"
    )


def _bounded_crop(fraction: float, axis: str) -> str:
    size = "iw-ow" if axis == "x" else "ih-oh"
    return f"max(0\\,min({size}\\,({size})*{fraction:.6f}))"


def _fill_chain(width: int, height: int, focus_x: float, focus_y: float) -> str:
    x = _bounded_crop(_clamp(focus_x, 0.0, 100.0) / 100.0, "x")
    y = _bounded_crop(_clamp(focus_y, 0.0, 100.0) / 100.0, "y")
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:{x}:{y},setsar=1,format=yuv420p"
    )


def _blur_chain(width: int, height: int, blur_amount: float, background_dim: float) -> str:
    sigma = 2.0 + _clamp(blur_amount, 0.0, 1.0) * 38.0
    brightness = -0.5 * _clamp(background_dim, 0.0, 1.0)
    return (
        "split[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma={sigma:.4f},eq=brightness={brightness:.4f}[bg];"
        f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2,"
        "setsar=1,format=yuv420p"
    )


def layout_filter(
    width: int,
    height: int,
    fit: str,
    *,
    focus_x: float = DEFAULT_FOCUS,
    focus_y: float = DEFAULT_FOCUS,
    blur_amount: float = DEFAULT_BLUR_AMOUNT,
    background_dim: float = DEFAULT_BACKGROUND_DIM,
) -> str:
    """FFmpeg chain placed in front of trim/fps. Blur starts with ``split``."""
    if fit == "fill":
        return _fill_chain(width, height, focus_x, focus_y)
    if fit == "blur":
        return _blur_chain(width, height, blur_amount, background_dim)
    return _fit_chain(width, height)
