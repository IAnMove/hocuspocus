"""UI options for one model type.

``get_model_options`` is the full server's function, moved verbatim.
``configure`` binds the engine and the MiniMax H3 helpers that stay in the
launch module.
"""
from __future__ import annotations

from fastapi import HTTPException

from services import minimax_h3_service, model3d_service

wgp = None
_is_legacy_h3_model = None
_recommended_minimax_h3_encoder = None
_minimax_h3_turbo_option = None
_minimax_h3_runtime_advisory = None


def configure(
    *,
    engine,
    is_legacy_h3_model,
    recommended_minimax_h3_encoder,
    minimax_h3_turbo_option,
    minimax_h3_runtime_advisory,
) -> None:
    """Bind the engine and the H3 helpers the options payload still calls."""
    global wgp, _is_legacy_h3_model, _recommended_minimax_h3_encoder
    global _minimax_h3_turbo_option, _minimax_h3_runtime_advisory
    wgp = engine
    _is_legacy_h3_model = is_legacy_h3_model
    _recommended_minimax_h3_encoder = recommended_minimax_h3_encoder
    _minimax_h3_turbo_option = minimax_h3_turbo_option
    _minimax_h3_runtime_advisory = minimax_h3_runtime_advisory


def get_model_options(model_type: str):
    """Return UI-relevant model options for dynamic rendering."""
    from services.image_edit_workflow import image_edit_capabilities
    from services.model_selectors import selector_catalog
    if _is_legacy_h3_model(model_type):
        return dict(minimax_h3_service.MODEL_OPTIONS)
    if model_type in model3d_service.MODEL_BY_ID:
        return {
            "model_type": model_type,
            "architecture": "hunyuan3d",
            "guidance_max_phases": 1,
            "lock_guidance_phases": False,
            "sliding_window": False,
            "motion_amplitude": False,
            "flow_shift": False,
            "tea_cache": False,
            "returns_audio": False,
            "any_audio_prompt": False,
            "audio_scale_name": "",
            "lock_inference_steps": False,
            "lock_guidance_scale": False,
            "no_negative_prompt": True,
            "i2v_class": False,
            "fps": 0,
        }
    md = wgp.get_model_def(model_type)
    if md is None:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_type}")

    # Get ui_defaults for fallback values (model handlers set these for their UIs)
    try:
        _ui_defaults = wgp.get_default_settings(model_type) or {}
    except Exception:
        _ui_defaults = {}

    # Helper to safely extract choice configs (dict or None)
    # Human-readable labels for guide_preprocessing codes
    _GUIDE_LABELS = {
        "": "None",
        "UV": "Keep Unchanged",
        "PV": "Transfer Pose",
        "DV": "Transfer Depth",
        "EV": "Transfer Canny Edges",
        "SV": "Transfer Shapes",
        "LV": "Transfer Flow",
        "CV": "Recolorize",
        "MV": "Inpainting",
        "V": "Raw Format",
        "PDV": "Transfer Pose + Depth",
        "PSV": "Transfer Pose + Shapes",
        "PLV": "Transfer Pose + Flow",
    }

    def extract_choice(key):
        val = md.get(key)
        if not isinstance(val, dict):
            return None
        result = {}
        for k in ("selection", "choices", "labels", "default", "label", "show_label", "letters_filter"):
            if k in val:
                result[k] = val[k]
        # Auto-inject labels for guide_preprocessing if not provided by model
        if key == "guide_preprocessing" and "labels" not in result and "selection" in result:
            result["labels"] = {code: _GUIDE_LABELS.get(code, code) for code in result["selection"]}
        return result if result else None

    # Extract sample_solvers as list of [label, value] tuples
    solvers = md.get("sample_solvers")
    if isinstance(solvers, list) and len(solvers) > 0:
        # WanGP stores them as list of (label, value) tuples
        solvers = [[s[0], s[1]] if isinstance(s, (list, tuple)) else [str(s), str(s)] for s in solvers]
    else:
        solvers = None

    _h3_encoder_variants = md.get("minimax_h3_text_encoder_variants") or {}
    _h3_encoder_default = (
        _recommended_minimax_h3_encoder(model_type, md)
        if _h3_encoder_variants
        else None
    )

    return {
        "model_type": model_type,
        "architecture": md.get("architecture", model_type),
        "guidance_max_phases": md.get("guidance_max_phases", 1),
        "lock_guidance_phases": md.get("lock_guidance_phases", False),

        # Boolean flags
        "sliding_window": md.get("sliding_window", False),
        "video_continuation": md.get("video_continuation", False),
        "motion_amplitude": md.get("motion_amplitude", False),
        "flow_shift": bool(md.get("flow_shift", False)),
        "tea_cache": md.get("tea_cache", False),
        "first_block_cache": md.get("first_block_cache", False),
        "skip_steps_multiplier_choices": [
            [str(choice[0]), float(choice[1])]
            for choice in md.get("skip_steps_multiplier_choices", [])
            if isinstance(choice, (list, tuple)) and len(choice) >= 2
        ] or None,
        "skip_steps_multiplier_label": md.get(
            "skip_steps_multiplier_label",
            "Cache Strength",
        ),
        "default_skip_steps_multiplier": _ui_defaults.get(
            "skip_steps_multiplier",
            0.08,
        ),
        "default_skip_steps_start_step_perc": _ui_defaults.get(
            "skip_steps_start_step_perc",
            25,
        ),
        "returns_audio": md.get("returns_audio", False),
        "any_audio_prompt": md.get("any_audio_prompt", False),
        "audio_scale_name": md.get("audio_scale_name", ""),
        "lock_inference_steps": md.get("lock_inference_steps", False),
        "inference_steps_min": md.get("inference_steps_min", 1),
        "inference_steps_max": md.get("inference_steps_max", 50),
        "lock_guidance_scale": md.get("lock_guidance_scale", False),
        "no_negative_prompt": md.get("no_negative_prompt", False),
        "i2v_class": md.get("i2v_class", False),
        "t2v_class": md.get("t2v_class", False),
        "image_outputs": md.get("image_outputs", False),
        "supports_end_frame": "E" in md.get("image_prompt_types_allowed", ""),
        # Raw conditioning letters let Studio expose only compatible sub-modes.
        "image_prompt_types_allowed": md.get("image_prompt_types_allowed", ""),
        "minimax_h3_semantic_bridge": md.get("minimax_h3_semantic_bridge", False),
        "wangp_1272": md.get("wangp_1272", False),
        "wangp_1272_capabilities": md.get("wangp_1272_capabilities", {}),
        "minimax_h3_fused_turbo": md.get("minimax_h3_fused_turbo", False),
        "omni_reference": md.get("omni_reference", False),
        "omni_reference_limits": md.get("omni_reference_limits"),
        "omni_reference_detail_choices": md.get("omni_reference_detail_choices"),
        "omni_reference_detail_default": md.get("omni_reference_detail_default", "match"),
        "minimax_h3_text_encoder_choices": [
            {
                "value": key,
                "label": (
                    f"{value.get('name', key)} (Recommended)"
                    if key == _h3_encoder_default
                    else value.get("name", key)
                ),
                "size_hint": value.get("size_hint", ""),
                "recommended": key == _h3_encoder_default,
            }
            for key, value in _h3_encoder_variants.items()
        ] or None,
        "minimax_h3_text_encoder_default": _h3_encoder_default,
        "minimax_h3_turbo": _minimax_h3_turbo_option(md),
        "minimax_h3_runtime_advisory": _minimax_h3_runtime_advisory(md),
        "resolution_presets": md.get("resolution_presets"),
        "resolution_preset_order": md.get("resolution_preset_order"),
        "supports_auto_aspect": md.get("supports_auto_aspect", False),

        # Choice configs
        "guide_preprocessing": extract_choice("guide_preprocessing"),
        "guide_custom_choices": extract_choice("guide_custom_choices"),
        # What the guide video *is* to this model. A control video and a reference clip are different
        # things and the handler names it; without this the UI calls every one of them a Control Video.
        "video_guide_label": md.get("video_guide_label"),
        "image_ref_choices": extract_choice("image_ref_choices"),
        "audio_prompt_type_sources": extract_choice("audio_prompt_type_sources"),

        # Image reference options
        "background_removal_label": md.get("background_removal_label"),
        "max_image_refs": md.get("max_image_refs"),
        "inpaint_support": bool(md.get("inpaint_support", False)),
        "image_ref_inpaint": bool(md.get("image_ref_inpaint", False)),
        **image_edit_capabilities(md),
        "model_name": md.get("name") or model_type,
        "native_rgba": bool(md.get("native_rgba", False)),
        "sample_solvers": solvers,

        # Self refiner
        "self_refiner": md.get("self_refiner", False),
        "self_refiner_max_plans": md.get("self_refiner_max_plans", 1),

        # LTX-2 Dev pipeline capabilities (for guidance controls in Advanced Settings)
        "perturbation": md.get("perturbation", False),
        "reference_pipeline": md.get("reference_pipeline", False),
        "cfg_star": md.get("cfg_star", False),
        "adaptive_projected_guidance": md.get("adaptive_projected_guidance", False),
        "audio_guidance": md.get("audio_guidance", False),

        # Sliding window
        "sliding_window_defaults": md.get("sliding_window_defaults"),
        "sliding_window_memory_policy": md.get(
            "sliding_window_memory_policy"
        ),
        "director_memory_policy": md.get("director_memory_policy"),
        "sliding_window_auto_prompt_pacing": md.get(
            "sliding_window_auto_prompt_pacing", False
        ),

        # Timing
        "fps": md.get("fps", 16),
        "frames_minimum": md.get("frames_minimum", 5),
        "frames_steps": md.get("frames_steps", 4),
        "frames_maximum": md.get("frames_maximum"),

        # Model defaults (sent to frontend so UI can apply them on model selection)
        # Check model def first, then fall back to ui_defaults from the handler
        "default_num_inference_steps": md.get("num_inference_steps") or _ui_defaults.get("num_inference_steps"),
        "default_guidance_scale": md.get("guidance_scale") or _ui_defaults.get("guidance_scale"),
        # Read ONLY from ui_defaults: model_def's "flow_shift" is a boolean
        # capability flag (whether to show the control), not a value.
        "default_flow_shift": _ui_defaults.get("flow_shift"),
        # The model's declared temporal grid, so the UI can mirror
        # align_model_frame_count instead of guessing. Absent (modulus 0) for
        # models that declare none, and the UI then leaves frame counts alone.
        "frame_alignment_modulus": int(md.get("frame_alignment_modulus", 0) or 0),
        "frame_alignment_remainder": int(md.get("frame_alignment_remainder", 1)),
        "frame_alignment_mode": str(md.get("frame_alignment_mode", "floor")).lower(),
        "frames_maximum": md.get("frames_maximum"),
        "hide_resolution_presets": md.get("hide_resolution_presets", False),

        # Image/video conditioning strength
        "input_video_strength_label": md.get("input_video_strength", ""),

        # Post-processing capabilities
        "vae_upsampler_modes": md.get("vae_upsampler", []),

        # TTS-specific
        "audio_only": md.get("audio_only", False),
        "duration_slider": md.get("duration_slider"),
        "pause_between_sentences": md.get("pause_between_sentences", False),
        "temperature_enabled": md.get("temperature", False),
        "custom_settings_def": md.get("custom_settings"),
        # Voice-count-driven audio mode (KugelAudio + Scenema): the UI hides
        # the manual Audio Mode ChoiceControl when this is True, since the
        # voice-slot buttons are the sole source of truth for audio_prompt_type.
        "audio_mode_from_voice_count": md.get("audio_mode_from_voice_count", False),
        # Max voice slots the model accepts. UI caps the "Add Voice" button
        # at this number. Defaults to 6 (Kugel); Scenema sets 2.
        "max_voice_count": md.get("max_voice_count"),
        "selectors": selector_catalog(md),
    }
