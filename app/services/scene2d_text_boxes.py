"""Approximate Video 2D text and lyric boxes for validate.

Boxes are percentages of the frame. The block is centered on the anchor, matching
``paintV2Cue``: align only shifts shorter lines inside that block, so the union
still follows font, size, maxWidth and box padding. Plate boxes cover the frame.
Rotation is ignored. Contrast ratios come from sampled pixels, never from a guess.
"""
from __future__ import annotations

import os
from typing import Any

_CAP = 0.72
_ADVANCE = {"sans": 0.5, "mono": 0.6, "display": 0.55, "condensed": 0.4, "serif": 0.48, "hand": 0.5, "marker": 0.52}
_VISUAL = frozenset({"image", "video", "overlay", "model3d", "effect"})
_TEXT_COLOR = "#ffe3a0"
_LYRIC_COLOR = "#f4efe6"
_CONTRAST_MIN = 3.0


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or abs(number) == float("inf"):
        return None
    return number


def _issue(code: str, path: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "path": path, "message": message, **extra}


def _frame(document: dict) -> tuple[float, float]:
    width = _number(document.get("width")) or 1280.0
    height = _number(document.get("height")) or 720.0
    return (width if width > 0 else 1280.0), (height if height > 0 else 720.0)


def _advance(font: Any) -> float:
    return _ADVANCE.get(font, 0.5) if isinstance(font, str) else 0.5


def _wrap(text: str, advance_px: float, max_px: float) -> tuple[list[str], float]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = [word for word in paragraph.split() if word]
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            trial = word if not current else f"{current} {word}"
            if current and max_px > 0 and len(trial) * advance_px > max_px:
                lines.append(current)
                current = word
            else:
                current = trial
        lines.append(current)
    widest = max((len(line) * advance_px for line in lines), default=advance_px)
    return lines or [""], widest


def _padding(box: Any, line_px: float, frame_w: float, frame_h: float) -> tuple[float, float]:
    if not isinstance(box, dict) or box.get("kind") in {None, "none", "underline", "plate"}:
        return 0.0, 0.0
    padding = _number(box.get("padding")) or 0.0
    pad_px = max(0.0, padding) * line_px
    return pad_px / frame_w * 100.0, pad_px / frame_h * 100.0


def _ink_box(anchor_x: float, anchor_y: float, block_w: float, block_h: float, pad_x: float, pad_y: float) -> dict[str, float]:
    return {
        "left": anchor_x - block_w / 2.0 - pad_x,
        "right": anchor_x + block_w / 2.0 + pad_x,
        "top": anchor_y - block_h / 2.0 - pad_y,
        "bottom": anchor_y + block_h / 2.0 + pad_y,
    }


def _measure(text: str, spec: dict[str, Any], frame_w: float, frame_h: float) -> dict[str, float] | None:
    if not isinstance(text, str) or not text.strip():
        return None
    size = _number(spec.get("size"))
    if size is None or size <= 0:
        return None
    anchor_x = _number(spec.get("x"))
    anchor_y = _number(spec.get("y"))
    if anchor_x is None or anchor_y is None:
        return None
    box = spec.get("box")
    if isinstance(box, dict) and box.get("kind") == "plate":
        return {"left": 0.0, "top": 0.0, "right": 100.0, "bottom": 100.0}
    advance = _advance(spec.get("font"))
    size_px = frame_h * size / 100.0
    advance_px = size_px * advance
    max_width = _number(spec.get("maxWidth"))
    max_px = frame_w * max_width / 100.0 if max_width is not None else 0.0
    _lines, widest = _wrap(text, advance_px, max_px)
    scale = 1.0
    if max_width is None and widest > frame_w * 0.86:
        scale = frame_w * 0.86 / widest
    widest *= scale
    line_factor = _number(spec.get("lineHeight")) or 1.12
    count = max(1, len(_lines))
    ink = size * scale * _CAP
    leading = size * scale * line_factor
    block_h = ink if count == 1 else ink + (count - 1) * leading
    if _number(spec.get("visibleLines")) == 2:
        block_h += leading
    pad_x, pad_y = _padding(box, size_px * scale * line_factor, frame_w, frame_h)
    return _ink_box(anchor_x, anchor_y, widest / frame_w * 100.0, block_h, pad_x, pad_y)


def _timing(node: dict, fallback_end: float | None) -> tuple[float, float] | None:
    start = _number(node.get("start"))
    end = _number(node.get("end"))
    if start is None:
        start = 0.0
    if end is None:
        end = fallback_end
    if end is None or end <= start:
        return None
    return start, end


def _hex(value: Any, fallback: str) -> str:
    if isinstance(value, str) and len(value) == 7 and value.startswith("#") and all(char in "0123456789abcdefABCDEF" for char in value[1:]):
        return value
    return fallback


def _text_defaults(cue: dict) -> dict[str, Any]:
    spec = {"x": 50, "y": 82, "size": 9, "font": "sans", "align": "center", "lineHeight": 1.12}
    spec.update({key: cue[key] for key in spec if key in cue})
    for key in ("maxWidth", "box", "visibleLines"):
        if key in cue:
            spec[key] = cue[key]
    return spec


def text_placements(document: dict) -> list[dict[str, Any]]:
    frame_w, frame_h = _frame(document)
    texts = document.get("texts")
    if not isinstance(texts, list):
        return []
    placed = []
    for index, cue in enumerate(texts):
        if not isinstance(cue, dict):
            continue
        timing = _timing(cue, None)
        bounds = _measure(str(cue.get("text") or ""), _text_defaults(cue), frame_w, frame_h)
        if timing is None or bounds is None:
            continue
        placed.append({"path": f"texts[{index}]", "kind": "text", "start": timing[0], "end": timing[1], "color": _hex(cue.get("color"), _TEXT_COLOR), **bounds})
    return placed


def _lyric_text(line: dict) -> str:
    words = line.get("words")
    if not isinstance(words, list):
        return ""
    return " ".join(str(word.get("text") or "") for word in words if isinstance(word, dict)).strip()


def lyric_placements(document: dict) -> list[dict[str, Any]]:
    lyrics = document.get("lyrics")
    if not isinstance(lyrics, dict):
        return []
    style = lyrics.get("style") if isinstance(lyrics.get("style"), dict) else {}
    spec = {"x": 50, "y": 78, "size": 7, "font": "sans", "align": "center", "maxWidth": 80, "lineHeight": 1.25}
    spec.update({key: style[key] for key in spec if key in style})
    if style.get("visibleLines") == 2:
        spec["visibleLines"] = 2
    if isinstance(style.get("box"), dict):
        spec["box"] = style["box"]
    frame_w, frame_h = _frame(document)
    lines = lyrics.get("lines")
    if not isinstance(lines, list):
        return []
    placed = []
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            continue
        timing = _timing(line, None)
        bounds = _measure(_lyric_text(line), spec, frame_w, frame_h)
        if timing is None or bounds is None:
            continue
        placed.append({
            "path": f"lyrics.lines[{index}]", "kind": "lyric", "start": timing[0], "end": timing[1],
            "color": _hex(style.get("color"), _LYRIC_COLOR), **bounds,
        })
    return placed


def _hits(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if first["start"] >= second["end"] or second["start"] >= first["end"]:
        return False
    return first["left"] < second["right"] and second["left"] < first["right"] and first["top"] < second["bottom"] and second["top"] < first["bottom"]


def _outside(box: dict[str, Any]) -> bool:
    return box["left"] < -0.05 or box["top"] < -0.05 or box["right"] > 100.05 or box["bottom"] > 100.05


def _pair_warnings(texts: list[dict[str, Any]], lyrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings = []
    for index, cue in enumerate(texts):
        for other in texts[index + 1:]:
            if _hits(cue, other):
                warnings.append(_issue("text_overlap", cue["path"], f"{cue['path']} overlaps {other['path']}."))
    for index, line in enumerate(lyrics):
        for cue in texts:
            if _hits(line, cue):
                warnings.append(_issue("lyrics_overlap", line["path"], f"{line['path']} overlaps {cue['path']}."))
        for other in lyrics[index + 1:]:
            if _hits(line, other):
                warnings.append(_issue("lyrics_overlap", line["path"], f"{line['path']} overlaps {other['path']}."))
    return warnings


def _frame_warnings(placed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings = []
    for box in placed:
        if _outside(box):
            warnings.append(_issue("text_outside_frame", box["path"], "Text box extends outside the frame."))
    return warnings


def _zones(document: dict) -> list[dict[str, Any]]:
    raw = document.get("reservedZones")
    if not isinstance(raw, list):
        return []
    zones = []
    for index, zone in enumerate(raw):
        if not isinstance(zone, dict):
            continue
        x, y = _number(zone.get("x")), _number(zone.get("y"))
        width, height = _number(zone.get("width")), _number(zone.get("height"))
        if None in {x, y, width, height} or width <= 0 or height <= 0:
            continue
        zones.append({
            "path": f"reservedZones[{index}]",
            "id": zone.get("id") if isinstance(zone.get("id"), str) else "",
            "left": x, "top": y, "right": x + width, "bottom": y + height,
        })
    return zones


def _zone_warnings(placed: list[dict[str, Any]], zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings = []
    for box in placed:
        for zone in zones:
            probe = {"start": box["start"], "end": box["end"], **zone}
            if _hits(box, probe):
                label = zone["id"] or zone["path"]
                warnings.append(_issue("reserved_zone", box["path"], f"{box['path']} enters reserved zone {label}.", zone=zone["path"]))
    return warnings


def _visible_layer(layer: Any) -> bool:
    return isinstance(layer, dict) and layer.get("visible") is not False and layer.get("type") in _VISUAL


def _layer_window(layer: dict, duration: float) -> tuple[float, float] | None:
    animation = layer.get("animation") if isinstance(layer.get("animation"), dict) else None
    if animation is None:
        return (0.0, duration)
    local = _number(animation.get("duration"))
    if local is None or local <= 0:
        return (0.0, duration)
    offset = _number(animation.get("offset")) or 0.0
    speed = _number(animation.get("speed")) or 1.0
    if speed <= 0:
        speed = 1.0
    trim_start = _number(animation.get("trimStart")) or 0.0
    trim_end = _number(animation.get("trimEnd"))
    if trim_end is None:
        trim_end = local
    trim_start = min(max(0.0, trim_start), max(local - 0.01, 0.0))
    trim_end = min(local, max(trim_start + 0.01, trim_end))
    end = duration if animation.get("loop") is True else offset + (trim_end - trim_start) / speed
    start, end = max(0.0, offset), min(duration, end)
    if end - start <= 0.01:
        return None
    return start, end


def _merge(spans: list[tuple[float, float]]) -> list[list[float]]:
    merged: list[list[float]] = []
    for start, end in sorted(spans):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return merged


def _empty_warnings(document: dict, placements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    duration = _number(document.get("duration"))
    if duration is None or duration <= 2:
        return []
    spans: list[tuple[float, float]] = []
    layers = document.get("layers")
    if isinstance(layers, list):
        for layer in layers:
            if not _visible_layer(layer):
                continue
            window = _layer_window(layer, duration)
            if window is not None:
                spans.append(window)
    for box in placements:
        start, end = max(0.0, box["start"]), min(duration, box["end"])
        if end > start:
            spans.append((start, end))
    cursor = 0.0
    warnings = []
    for start, end in _merge(spans):
        if start - cursor > 2:
            warnings.append(_issue("empty_timespan", "duration", f"No visible layer or text from {cursor:g}s to {start:g}s.", start=cursor, end=start))
        cursor = max(cursor, end)
    if duration - cursor > 2:
        warnings.append(_issue("empty_timespan", "duration", f"No visible layer or text from {cursor:g}s to {duration:g}s.", start=cursor, end=duration))
    return warnings


def layout_warnings(document: dict) -> list[dict[str, Any]]:
    texts = text_placements(document)
    lyrics = lyric_placements(document)
    placed = [*texts, *lyrics]
    return [
        *_frame_warnings(placed),
        *_pair_warnings(texts, lyrics),
        *_zone_warnings(placed, _zones(document)),
        *_empty_warnings(document, texts),
    ]


def _channel(value: float) -> float:
    scale = value / 255.0
    if scale <= 0.04045:
        return scale / 12.92
    return ((scale + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[int, int, int]) -> float:
    red, green, blue = rgb
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast_ratio(foreground: tuple[int, int, int], background: tuple[int, int, int]) -> float:
    first, second = luminance(foreground), luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _sample(pixels: bytes, width: int, height: int, box: dict[str, Any]) -> tuple[int, int, int] | None:
    x0 = max(0, min(width - 1, int(box["left"] / 100.0 * width)))
    x1 = max(x0 + 1, min(width, int(box["right"] / 100.0 * width)))
    y0 = max(0, min(height - 1, int(box["top"] / 100.0 * height)))
    y1 = max(y0 + 1, min(height, int(box["bottom"] / 100.0 * height)))
    total = [0, 0, 0]
    count = 0
    for y in range(y0, y1):
        row = y * width * 3
        for x in range(x0, x1):
            index = row + x * 3
            total[0] += pixels[index]
            total[1] += pixels[index + 1]
            total[2] += pixels[index + 2]
            count += 1
    if count == 0:
        return None
    return total[0] // count, total[1] // count, total[2] // count


def contrast_warnings(placements: list[dict[str, Any]], pixels: bytes, width: int, height: int) -> list[dict[str, Any]]:
    """Warn when sampled background luminance versus the text color is under 3:1."""
    warnings = []
    if width <= 0 or height <= 0 or len(pixels) < width * height * 3:
        return warnings
    for box in placements:
        background = _sample(pixels, width, height, box)
        if background is None:
            continue
        ratio = contrast_ratio(_rgb(box["color"]), background)
        if ratio < _CONTRAST_MIN:
            warnings.append(_issue(
                "text_low_contrast", box["path"],
                f"{box['path']} contrast is {ratio:.2f}:1, under 3:1.",
                ratio=round(ratio, 2),
            ))
    return warnings


def contrast_skip_reason() -> str | None:
    """Why a painted frame was not sampled. None means the painter can start.

    Validate does not invent a ratio when this returns a reason. Pytest skips
    the painter unless HOCUS_VALIDATE_CONTRAST=1 so unit tests stay on the
    geometry checks and on contrast_warnings() with a real pixel buffer.
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("HOCUS_VALIDATE_CONTRAST") != "1":
        return "contrast sample skipped under pytest; set HOCUS_VALIDATE_CONTRAST=1 to paint"
    try:
        from services.video2d_preview import painter_block_reason
    except ImportError as error:
        return f"painter import failed: {error}"
    return painter_block_reason()


def painted_contrast_warnings(document: dict, placements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if contrast_skip_reason() or not placements:
        return []
    try:
        from fastapi import HTTPException
        from services.video2d_preview import PreviewError
    except ImportError:
        return []
    try:
        import io
        from copy import deepcopy

        from PIL import Image

        from services.video2d_preview import paint_contact_sheet, preview_frame_size
        background = deepcopy(document)
        background.pop("texts", None)
        background.pop("lyrics", None)
        duration = _number(background.get("duration")) or 1.0
        size = preview_frame_size(background)
        png = paint_contact_sheet(background, [min(0.05, duration)], size)
        image = Image.open(io.BytesIO(png)).convert("RGB")
    except (ImportError, OSError, ValueError, PreviewError, HTTPException):
        return []
    return contrast_warnings(placements, image.tobytes(), image.width, image.height)


__all__ = [
    "contrast_ratio",
    "contrast_skip_reason",
    "contrast_warnings",
    "layout_warnings",
    "luminance",
    "lyric_placements",
    "painted_contrast_warnings",
    "text_placements",
]
