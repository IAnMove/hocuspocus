"""Optional spec.resolution and spec.enhance.

Omitted resolution keeps today's 1280x704 frames and clips. There is no
video_upsampling field. wangp_submission calls
shared.wangp1272.processors.validate_selection for spatial_upsampling and
temporal_upsampling. FlashVSR scale 2 is the spatial value ``flashvsr2``
and RIFE scale 2 is the temporal value ``rife2``, both already in
tools_upscale.TOOL_UPSCALE_METHODS. The GPU worker is
tools_upscale.run_tool_upscale. enhance_clip only validates and then calls
an injected upscaler, which stands in for that worker. It does not queue
or start FlashVSR or RIFE.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

DEFAULT_RESOLUTION = "1280x704"
EXPORT_WIDTH = 1920
EXPORT_HEIGHT = 1080
# Not a measured FlashVSR or RIFE time. dry_run labels the line measured=false.
_UNMEASURED_MINUTES_PER_CLIP = 5
_METHODS = frozenset({"flashvsr", "rife"})
_DEFAULTS = Path(__file__).resolve().parents[1] / "defaults" / "minimax_h3_fused_turbo.json"


def check_spec(spec: dict) -> None:
    """Raise ProductionError invalid_spec. Called from validate_spec."""
    _check_resolution(spec)
    _check_enhance(spec)


def legal_resolutions() -> frozenset[str]:
    """H3 defaults file plus music_production.FRAME_RESOLUTIONS. No models import."""
    from services.music_production import FRAME_RESOLUTIONS

    return frozenset(FRAME_RESOLUTIONS) | _defaults_resolutions()


def resolved_resolution(spec: Any) -> dict[str, str]:
    """frames and clips. A missing side stays 1280x704."""
    raw = spec.get("resolution") if isinstance(spec, dict) and isinstance(spec.get("resolution"), dict) else {}
    legal = legal_resolutions()
    return {name: _known(raw.get(name), legal) for name in ("frames", "clips")}


def enhance_cost(spec: Any) -> list[dict[str, Any]]:
    """One dry_run warning when enhance is valid. Otherwise nothing, so minutes stay put."""
    enhance = _valid_enhance(spec)
    if enhance is None:
        return []
    clips = _h3_clips(spec)
    return [{
        "code": "enhance",
        "method": enhance["method"],
        "scale": 2,
        "clips": clips,
        "extra_minutes": float(clips * _UNMEASURED_MINUTES_PER_CLIP),
        "measured": False,
    }]


def enhance_clip(path: str, spec: Any, *, upscaler: Callable[..., str] | None = None) -> str:
    """Return path when enhance is absent. Otherwise validate and call upscaler."""
    if not isinstance(spec, dict) or not isinstance(spec.get("enhance"), dict):
        return path
    check_spec(spec)
    spatial, temporal = _upsampling_pair(spec["enhance"])
    error = _selection_error(spatial, temporal)
    if error:
        from services.music_production import ProductionError

        raise ProductionError("invalid_spec", error)
    if upscaler is None:
        from services.music_production import ProductionError

        raise ProductionError("enhance_unavailable", "clip enhance is not queued here; pass an upscaler")
    result = upscaler(path, spatial or temporal)
    if not isinstance(result, str) or not result:
        from services.music_production import ProductionError

        raise ProductionError("enhance_failed", "upscaler returned no path")
    return result


def crop_report(width: int, height: int, out_w: int, out_h: int) -> dict[str, float]:
    """fit:fill crop in source pixels. 1280x704 into 1920x1080 is 1.818:1 into 1.778:1."""
    if min(width, height, out_w, out_h) <= 0:
        raise ValueError("crop sizes must be positive")
    scale = max(out_w / width, out_h / height)
    return {
        "width": float(width),
        "height": float(height),
        "out_w": float(out_w),
        "out_h": float(out_h),
        "source_aspect": round(width / height, 3),
        "output_aspect": round(out_w / out_h, 3),
        "scale": scale,
        "crop_x": _axis(width, out_w, scale),
        "crop_y": _axis(height, out_h, scale),
    }


def clip_crop(spec: Any) -> dict[str, Any]:
    """Origin clip size and the 1920x1080 fit:fill crop. No image is opened."""
    size = resolved_resolution(spec)["clips"]
    width_s, _, height_s = size.partition("x")
    report = crop_report(int(width_s), int(height_s), EXPORT_WIDTH, EXPORT_HEIGHT)
    report["resolution"] = size
    return report


def _check_resolution(spec: dict) -> None:
    raw = spec.get("resolution", None)
    if raw is None:
        return
    if not isinstance(raw, dict):
        _bad("spec.resolution must be an object")
    legal = legal_resolutions()
    listed = ", ".join(sorted(legal))
    for name in ("frames", "clips"):
        if name not in raw:
            continue
        value = raw[name]
        if not isinstance(value, str) or value not in legal:
            _bad(f"spec.resolution.{name} must be one of {listed}")


def _check_enhance(spec: dict) -> None:
    raw = spec.get("enhance", None)
    if raw is None:
        return
    if not isinstance(raw, dict):
        _bad("spec.enhance must be an object")
    method, scale = raw.get("method"), raw.get("scale")
    if method not in _METHODS or scale != 2:
        _bad("spec.enhance needs method flashvsr or rife and scale 2")
    token = f"{method}{int(scale)}"
    from services.tools_upscale import TOOL_UPSCALE_METHODS

    if token not in TOOL_UPSCALE_METHODS:
        _bad(f"spec.enhance {token} is not a tools.upscale method")


def _valid_enhance(spec: Any) -> dict | None:
    if not isinstance(spec, dict) or not isinstance(spec.get("enhance"), dict):
        return None
    enhance = spec["enhance"]
    if enhance.get("method") not in _METHODS or enhance.get("scale") != 2:
        return None
    return enhance


def _h3_clips(spec: dict) -> int:
    shots = spec.get("shots")
    if not isinstance(shots, list):
        return 0
    return sum(1 for shot in shots if isinstance(shot, dict) and shot.get("kind") == "h3")


def _known(value: Any, legal: frozenset[str]) -> str:
    if isinstance(value, str) and value in legal:
        return value
    return DEFAULT_RESOLUTION


def _defaults_resolutions() -> frozenset[str]:
    data = json.loads(_DEFAULTS.read_text(encoding="utf-8"))
    found = data.get("resolution") if isinstance(data, dict) else None
    return frozenset({found}) if isinstance(found, str) and found else frozenset()


def _upsampling_pair(enhance: dict) -> tuple[str, str]:
    token = f"{enhance['method']}{int(enhance['scale'])}"
    if enhance["method"] == "rife":
        return "", token
    return token, ""


def _selection_error(spatial: str, temporal: str) -> str:
    from shared.wangp1272.processors import validate_selection

    error = validate_selection(spatial, temporal, False)
    return error if isinstance(error, str) else ""


def _axis(size: float, out: float, scale: float) -> float:
    crop = (size - out / scale) / 2
    return 0.0 if abs(crop) < 1e-9 else crop


def _bad(message: str) -> None:
    from services.music_production import ProductionError

    raise ProductionError("invalid_spec", message)
