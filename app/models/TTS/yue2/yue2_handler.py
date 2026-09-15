import os
from pathlib import Path

from shared.utils import files_locator as fl


ARCHITECTURE = "yue2"
REPO_ID = "DeepBeepMeep/TTS"
TEXT_ENCODER_FOLDER = "YuE2_AR"
ASSETS = ["vae_config.json", "YuE2_VAE_bf16.safetensors"]
REVISION = "864a479cbf3e810e1b2c1993b438510750e383b2"
PROMPT = "[Verse]\nMorning light across the bay\nWe watch the shadows drift away\n[Chorus]\nStay with me until the dawn\nLet our little song go on"
STYLE = "English acoustic pop, warm female vocal, fingerpicked guitar, gentle drums, hopeful, 90 BPM"
INFOS = """Generate a new 48 kHz stereo song from literal lyrics and a separate music style.
Choose melody and chords, melody only, or direct generation. Duration is an upper
limit: YuE2 may finish earlier. Start with 32 steps and guidance 1.
This HocusPocus adapter supports lyrics/style generation. Audio covers, ABC imports
and score export are not exposed. Model weights: CC BY-NC 4.0 (non-commercial).
"""
PROMPT_INFOS = """Enter the words to sing, with [Verse], [Chorus] and [Bridge] on separate
lines. Put language, genre, instruments, mood, vocal character and tempo in Music
Style. Repeat chorus words explicitly. Prompt enhancement is off by default.
"""

class family_handler:
    @staticmethod
    def query_supported_types():
        return [ARCHITECTURE]

    @staticmethod
    def query_family_maps():
        return {}, {}

    @staticmethod
    def query_model_family():
        return "tts"

    @staticmethod
    def query_family_infos():
        return {"music": (2195, "Music"), "tts": (2200, "TTS")}

    @staticmethod
    def get_lora_dir(base_model_type):
        return ARCHITECTURE

    @staticmethod
    def query_model_def(base_model_type, model_def):
        return {
            "group": "music", "audio_only": True, "image_outputs": False,
            "sliding_window": False, "guidance_max_phases": 1,
            "no_negative_prompt": True, "inference_steps": True,
            "temperature": True, "top_k_slider": True, "top_p_slider": True,
            "embedded_guidance": False, "image_prompt_types_allowed": "",
            "profiles_dir": [ARCHITECTURE], "compile": False,
            "lm_engines": ["cg", "vllm"], "prompt_class": "Lyrics",
            "text_encoder_URLs": [f"https://huggingface.co/{REPO_ID}/resolve/{REVISION}/{TEXT_ENCODER_FOLDER}/YuE2_AR_{precision}.safetensors" for precision in ("bf16", "int8_convrot")],
            "text_encoder_folder": TEXT_ENCODER_FOLDER,
            "alt_prompt": {"label": "Music Style", "placeholder": "Language, genre, instruments, mood, vocal character and tempo", "lines": 3},
            "model_modes": {"choices": [("Melody and chords", 0), ("Melody only", 1), ("Direct generation", 2)], "default": 0, "label": "Composition Planning"},
            "duration_slider": {"label": "Maximum Song Duration (seconds)", "name": "Maximum Song Duration", "min": 1, "max": 600, "increment": 1, "default": 120},
            "default_num_inference_steps": 32, "default_guidance_scale": 1.0,
            "infos": INFOS, "prompt_infos": PROMPT_INFOS,
        }

    @staticmethod
    def query_model_files(computeList, base_model_type, model_def=None):
        return {"repoId": REPO_ID, "revision": REVISION, "sourceFolderList": ["yue2", TEXT_ENCODER_FOLDER], "fileList": [ASSETS, ["qwen.tiktoken"]]}

    @staticmethod
    def load_model(model_filename, model_type, base_model_type, model_def, dtype=None, VAE_dtype=None, save_quantized=False, profile=0, lm_decoder_engine="legacy", text_encoder_filename=None, **kwargs):
        from .pipeline import YuE2Pipeline
        paths = {name: fl.locate_file(os.path.join("yue2", name)) for name in ASSETS}
        acoustic_weights, = model_filename
        tokenizer_path = fl.locate_file(os.path.join(TEXT_ENCODER_FOLDER, "qwen.tiktoken"))
        pipeline = YuE2Pipeline(text_encoder_filename, acoustic_weights, tokenizer_path, paths["YuE2_VAE_bf16.safetensors"], paths["vae_config.json"], dtype, VAE_dtype, lm_decoder_engine)
        if lm_decoder_engine in ("cg", "vllm"):
            pipeline.text_encoder._budget = 0
        if save_quantized:
            from wgp import save_quantized_model
            save_quantized_model(pipeline.transformer, model_type, acoustic_weights, dtype, str(Path(__file__).parent / "yue2.json"), submodel_no=1)
        return pipeline, {"pipe": {"text_encoder": pipeline.text_encoder, "transformer": pipeline.transformer, "vae": pipeline.vae}}

    @staticmethod
    def update_default_settings(base_model_type, model_def, ui_defaults):
        ui_defaults.update({"prompt": PROMPT, "alt_prompt": STYLE, "audio_prompt_type": "", "duration_seconds": 120, "video_length": 0, "num_inference_steps": 32, "guidance_scale": 1.0, "temperature": 1.0, "top_k": 100, "top_p": 0.95, "model_mode": 0, "prompt_enhancer": "", "negative_prompt": "", "repeat_generation": 1, "multi_prompts_gen_type": 2})

    @staticmethod
    def validate_generative_prompt(base_model_type, model_def, inputs, one_prompt):
        if not one_prompt.strip() or not str(inputs.get("alt_prompt", "")).strip():
            return "YuE2 requires lyrics and a music style."
        if inputs.get("audio_prompt_type") or inputs.get("audio_guide") or inputs.get("custom_guide") or inputs.get("custom_settings"):
            return "This YuE2 adapter supports lyrics and style; source audio and scores are not supported."
        if not 1 <= inputs.get("duration_seconds", 0) <= 600:
            return "YuE2 maximum duration must be between 1 and 600 seconds."
        if inputs.get("guidance_scale", 0) < 1:
            return "YuE2 guidance must be at least 1."
        if inputs.get("model_mode", 0) not in (0, 1, 2):
            return "Choose melody and chords, melody only, or direct generation."
        return None
