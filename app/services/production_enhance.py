"""Plan a FlashVSR pass or recommend RIFE. Neither runs unless an upscaler is injected.

RIFE is a recommendation when packet-time smoothness already failed. It is not started.
FlashVSR uses the existing tools_upscale method name ``flashvsr2``. Extra minutes for
either method are the provisional default in production_estimate, not a measured SSIM.
"""
from __future__ import annotations

from typing import Any

FLASHVSR_METHOD = "flashvsr2"


def enhance_clips(production: Any, spec: dict) -> None:
    enhance = spec.get("enhance") if isinstance(spec.get("enhance"), dict) else None
    if not enhance:
        return
    if enhance.get("method") == "rife":
        _recommend_rife(production)
        return
    if enhance.get("method") != "flashvsr":
        return
    upscaler = getattr(production, "upscaler", None)
    if upscaler is None:
        production.log("enhance planned, not run")
        return
    scale = enhance.get("scale") if enhance.get("scale") in (2, 4) else 2
    for key, clip in list((production.state.get("clips") or {}).items()):
        file = clip.get("file") if isinstance(clip, dict) else None
        if file:
            upscaler(file, method=FLASHVSR_METHOD, scale=scale)
    production.state["enhance"] = {"method": FLASHVSR_METHOD, "scale": scale, "ran": True}


def _recommend_rife(production: Any) -> None:
    if _smoothness_failed(production.state):
        production.state["rife_recommended"] = True


def _smoothness_failed(state: dict) -> bool:
    bucket = state.get("smoothness") if isinstance(state.get("smoothness"), dict) else {}
    final = bucket.get("final")
    if isinstance(final, dict) and final.get("verdict") == "fail":
        return True
    for name in ("clip", "scene"):
        reports = bucket.get(name)
        if isinstance(reports, dict) and any(isinstance(item, dict) and item.get("verdict") == "fail" for item in reports.values()):
            return True
    return False
