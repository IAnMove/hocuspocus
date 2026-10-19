"""Prompt-type, SCAIL-2 and MiniMax H3 option helpers, moved verbatim from the full server.

``bind`` is called once from the full server. ``wgp`` is the engine. ``_get_cached_hardware``
is defined later in the full server, so the server passes a forwarder and this module
calls that. The prompt-type tables moved with the two normalisers that read them.
"""
from __future__ import annotations

from services import minimax_h3_service

wgp = None
_get_cached_hardware = None


def bind(**names):
    """Store the full server's engine and hardware lookup. Keyword arguments only."""
    global wgp, _get_cached_hardware
    wgp = names["wgp"]
    _get_cached_hardware = names["_get_cached_hardware"]


def _is_legacy_h3_model(model_type: str | None) -> bool:
    return str(model_type or "").strip() == minimax_h3_service.MODEL_ID

def _is_character_sheet_engine(body: dict | None) -> bool:
    return (
        isinstance(body, dict)
        and str(body.get("character_sheet_engine") or "").strip()
        == minimax_h3_service.CHARACTER_SHEET_ENGINE
    )

def _is_minimax_h3_model(model_type: str | None) -> bool:
    """Recognize every native H3 variant from the current model registry."""
    candidate = str(model_type or "").strip()
    if not candidate:
        return False
    try:
        model_def = wgp.get_model_def(candidate) or {}
    except Exception:
        model_def = {}
    return (
        candidate.lower().startswith("minimax_h3")
        or str(model_def.get("architecture") or "").lower().startswith("minimax_h3")
    )

# ── video_prompt_type normalization ─────────────────────────────────
# Maestro's video_prompt_type is a string of single-letter mode flags
# the wgp.py pipeline uses to decide what optional inputs are needed
# (e.g. "I" → image_refs required, "V" → video/image guide required).
# wgp.py rejects the job with a friendly UI error if a flag is set but
# the corresponding input is missing.
#
# Without this normalization, stale UI state can leave a flag set after
# its input got cleared — most commonly "I" persisting in localStorage
# after the user removed their reference image, causing every subsequent
# text-to-image gen to fail with "You must provide at least one
# Reference Image". The frontend should already be keeping the flag in
# sync with the inputs, but this defense-in-depth strip lets us recover
# from any UI bug that lets the inconsistent state through.
#
# The set is conservative — only flags where (a) we know the required
# input field name with confidence and (b) the wgp.py validation rejects
# the job rather than silently degrading. Adding too many strips here
# could mask other bugs, so we extend on demand.
_VPT_REQUIRED_INPUTS = {
    # flag → (param key in body, friendly label for log line)
    "I": ("image_refs", "image references"),
}


def _normalize_video_prompt_type(body: dict) -> None:
    """Strip video_prompt_type flags whose required input is missing.

    Mutates `body` in place. No-op when video_prompt_type isn't set or
    when all flags have their inputs.
    """
    vpt = body.get("video_prompt_type")
    if not isinstance(vpt, str) or not vpt:
        return

    new_vpt = vpt
    for flag, (input_key, label) in _VPT_REQUIRED_INPUTS.items():
        if flag not in new_vpt:
            continue
        input_val = body.get(input_key)
        # Treat missing, None, empty string, and empty list as absent.
        is_absent = (
            input_val is None
            or (isinstance(input_val, (list, tuple, str)) and len(input_val) == 0)
        )
        if is_absent:
            new_vpt = new_vpt.replace(flag, "")
            print(
                f"[Generate] Stripped '{flag}' from video_prompt_type "
                f"(no {label} attached) — was {vpt!r}, now {new_vpt!r}"
            )

    if new_vpt != vpt:
        body["video_prompt_type"] = new_vpt

# ── image_prompt_type normalization ──────────────────────────────────
# Sibling to video_prompt_type. wgp's image_prompt_type controls whether
# I2V (image-to-video) start/end frames are expected. When "S" is set
# but no image_start is attached, wgp rejects the job with "You must
# provide a Start Image" instead of falling back to T2V — even though
# Maestro's UX promises "no start image → T2V automatically."
#
# Stale UI state is the usual cause: model defaults, sidecar metadata
# from a previous re-roll, or the user clearing the start-image
# preview after the prompt_type was set. Strip the flag when its
# input is absent so the user gets the T2V fallback they expected.
_IPT_REQUIRED_INPUTS = {
    # flag → (param key in body, friendly label for log line)
    "S": ("image_start", "start image"),
    "E": ("image_end", "end image"),
}


def _normalize_image_prompt_type(body: dict) -> None:
    """Strip image_prompt_type flags whose required input is missing.

    Mutates `body` in place. No-op when image_prompt_type isn't set or
    when all flags have their inputs.

    Effect: a body with image_prompt_type='S' but no image_start gets
    its prompt_type rewritten to '' (or stripped of just 'S' if other
    flags survive), turning the job into T2V — matching Maestro's
    documented behavior of auto-falling-back to T2V when no start
    image is provided.
    """
    ipt = body.get("image_prompt_type")
    if not isinstance(ipt, str) or not ipt:
        return

    new_ipt = ipt
    for flag, (input_key, label) in _IPT_REQUIRED_INPUTS.items():
        if flag not in new_ipt:
            continue
        input_val = body.get(input_key)
        is_absent = (
            input_val is None
            or (isinstance(input_val, (list, tuple, str)) and len(input_val) == 0)
        )
        if is_absent:
            new_ipt = new_ipt.replace(flag, "")
            print(
                f"[Generate] Stripped '{flag}' from image_prompt_type "
                f"(no {label} attached) — was {ipt!r}, now {new_ipt!r}. "
                f"Falling back to {'T2V' if not new_ipt else 'I2V with remaining flags'}."
            )

    if new_ipt != ipt:
        body["image_prompt_type"] = new_ipt

def _minimax_h3_turbo_option(model_def: dict) -> dict | None:
    from services.h3_runtime_policy import turbo_option
    return turbo_option(model_def)

def _recommended_minimax_h3_encoder(model_type: str, model_def: dict) -> str:
    """Resolve H3's default encoder from actual kernel support and RAM."""

    variants = model_def.get("minimax_h3_text_encoder_variants") or {}
    fallback = str(model_def.get("minimax_h3_text_encoder_default") or "nvfp4_awq")
    if not variants:
        return fallback
    try:
        handler = wgp.get_model_handler(wgp.get_base_model_type(model_type))
        selected = handler.recommend_text_encoder(_get_cached_hardware(), model_def)
        if selected in variants:
            return selected
    except Exception as error:
        print(f"[MiniMax H3] Hardware-aware encoder recommendation failed: {error}")
    return fallback if fallback in variants else next(iter(variants))

def _minimax_h3_runtime_advisory(model_def: dict) -> dict | None:
    """Return a non-blocking Full-H3 hardware warning for Studio."""

    if not str((model_def or {}).get("architecture") or "").startswith(
        "minimax_h3"
    ):
        return None
    try:
        from models.minimax_h3.minimax_h3_handler import h3_runtime_preflight

        return h3_runtime_preflight(model_def, _get_cached_hardware())
    except Exception as error:
        print(f"[MiniMax H3] Runtime preflight unavailable: {error}")
        return None

def _normalize_scail2_inference_steps(value, default):
    """Clamp dedicated SCAIL-2 edit jobs to the UI's supported step range."""
    try:
        steps = int(float(value))
    except (TypeError, ValueError, OverflowError):
        steps = int(default)
    return min(50, max(1, steps))

def _normalize_scail2_guidance_scale(value, default=5.0):
    """Return a finite SCAIL-2 HQ guidance value accepted by the UI."""
    import math

    try:
        guidance = float(value)
    except (TypeError, ValueError, OverflowError):
        guidance = float(default)
    if not math.isfinite(guidance):
        guidance = float(default)
    return min(20.0, max(0.0, guidance))

def _extract_output_seed(filename):
    """Return the resolved seed embedded in a generated media filename."""
    import os
    import re

    match = re.search(r"(?:^|_)seed(\d+)(?:_|$)", os.path.splitext(filename)[0])
    return int(match.group(1)) if match else None
