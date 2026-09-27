"""AuK's fixed Flash schedule and literal single-reference request boundary."""


def prepare_auk_speech(params, definition):
    if params.get("model_type") not in {"auk", "auk_flash"}:
        return
    if definition.get("architecture") != "auk":
        raise ValueError("The selected model definition does not match AuK")
    if params.get("audio_prompt_type", "") not in {"", "A"}:
        raise ValueError("AuK accepts one source audio or instruction-only speech")
    if params.get("_tts_voice_count", 0) or any(
        params.get(f"_tts_speaker_name{index}") for index in range(1, 7)
    ):
        raise ValueError("AuK uses literal instructions, without speaker-name substitutions")
    flash = params["model_type"] == "auk_flash"
    if bool(definition.get("auk_flash")) != flash:
        raise ValueError("The selected AuK checkpoint does not match its sampling recipe")
    if flash:
        params.update(num_inference_steps=4, guidance_scale=0, guidance_phases=0)
    elif not params.get("num_inference_steps"):
        params["num_inference_steps"] = 32
