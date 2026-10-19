"""VoxCPM2's own sampling recipe at the speech request boundary."""

VOXCPM2_MODELS = frozenset({"voxcpm2_voicedesign", "voxcpm2_base"})
# The default voice-design model of generators that make a voice from traits (games).
DEFAULT_VOICE_DESIGN_MODEL = "voxcpm2_voicedesign"
DEFAULT_STEPS = 10
DEFAULT_GUIDANCE = 2.0


def prepare_voxcpm2_speech(params, definition):
    """Callers that leave sampling unset (series lines, Wizard, MCP) get the model's recipe.

    The speech spec keeps only what the caller sent, and zero steps is the sentinel of
    models without a step control; VoxCPM2 has one (4-30, default 10, guidance 2).
    """
    if params.get("model_type") not in VOXCPM2_MODELS:
        return
    if not str(definition.get("architecture", "")).startswith("voxcpm2"):
        raise ValueError("The selected model definition does not match VoxCPM2")
    if not params.get("num_inference_steps"):
        params["num_inference_steps"] = DEFAULT_STEPS
    params.setdefault("guidance_scale", DEFAULT_GUIDANCE)
