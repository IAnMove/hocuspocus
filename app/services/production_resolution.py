"""Validate spec.resolution and spec.enhance, and describe the 1920×1080 fill crop.

The unset default stays 1280×704, which is what clip jobs already send. The H3
model card's own default (1152×640) is allowed when the spec asks for it.
"""
from __future__ import annotations

FRAME_OK = ("1280x704", "1152x640", "1024x576", "1536x1024", "1024x1536")
CLIP_OK = ("1280x704", "1152x640", "1024x576")
ENHANCE_OK = ("flashvsr", "rife")
SCALES = (2, 4)
EXPORT = (1920, 1080)
_DEFAULT_CLIP = "1280x704"


def check_resolution(spec: dict) -> dict:
    """Reject an unknown frame size, clip size, enhance method or scale. Returns the same spec."""
    from services.music_production import ProductionError
    resolution = spec.get("resolution")
    if resolution is not None:
        if not isinstance(resolution, dict):
            raise ProductionError("invalid_spec", "spec.resolution must be an object")
        _member(resolution.get("frames"), FRAME_OK, "spec.resolution.frames", ProductionError)
        _member(resolution.get("clips"), CLIP_OK, "spec.resolution.clips", ProductionError)
    enhance = spec.get("enhance")
    if enhance is not None:
        if not isinstance(enhance, dict) or enhance.get("method") not in ENHANCE_OK:
            raise ProductionError("invalid_spec", "spec.enhance.method must be flashvsr or rife")
        scale = enhance.get("scale", 2)
        if scale not in SCALES:
            raise ProductionError("invalid_spec", "spec.enhance.scale must be 2 or 4")
    return spec


def frame_resolution(spec: dict, attempt: int, failure_text: str) -> str:
    """The start-frame size. An out-of-memory failure steps down the existing ladder."""
    from services.music_production import FRAME_RESOLUTIONS
    chosen = _pick(spec, "frames", FRAME_RESOLUTIONS[0])
    if "memory" in (failure_text or ""):
        return FRAME_RESOLUTIONS[min(attempt, len(FRAME_RESOLUTIONS) - 1)]
    return chosen


def clip_resolution(spec: dict) -> str:
    return _pick(spec, "clips", _DEFAULT_CLIP)


def crop_plan(spec: dict) -> dict:
    """How fit:fill places the clip resolution on a 1920×1080 scene."""
    source = clip_resolution(spec)
    width, height = _parse(source)
    source_ratio = width / height
    target_ratio = EXPORT[0] / EXPORT[1]
    if abs(source_ratio - target_ratio) < 0.01:
        crop = "none"
    elif source_ratio > target_ratio:
        crop = "horizontal"
    else:
        crop = "vertical"
    return {"source": source, "target": "1920x1080", "fit": "fill", "crop": crop}


def _member(value, allowed: tuple, label: str, error) -> None:
    if value is not None and value not in allowed:
        raise error("invalid_spec", f"{label} must be one of {', '.join(allowed)}")


def _pick(spec: dict, key: str, default: str) -> str:
    resolution = spec.get("resolution") if isinstance(spec.get("resolution"), dict) else {}
    value = resolution.get(key)
    allowed = FRAME_OK if key == "frames" else CLIP_OK
    if value in allowed:
        return value
    return default


def _parse(value: str) -> tuple[int, int]:
    width, _, height = value.partition("x")
    return int(width), int(height)
