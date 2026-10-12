"""WanGP family handler for VoxCPM2 (OpenBMB, 2B, 30 languages, 48 kHz).

Two model types share one checkpoint and follow the Qwen3 TTS conventions:

* ``voxcpm2_voicedesign`` - a voice from a description (``alt_prompt``), like
  ``qwen3_tts_voicedesign``.
* ``voxcpm2_base`` - a voice cloned from a reference recording (``audio_guide``), with the
  reference transcript(s) in ``alt_prompt`` (one line per speaker), like ``qwen3_tts_base``;
  ``Speaker 1:`` / ``Speaker 2:`` lines make a two-voice dialogue.
"""
import os
import re

from shared.utils import files_locator as fl

from .prompt_enhancers import TTS_MONOLOGUE_PROMPT, TTS_QWEN3_DIALOGUE_PROMPT

VOXCPM2_REPO = "openbmb/VoxCPM2"
# Hugging Face revision of openbmb/VoxCPM2 (2026-08-18).
VOXCPM2_REVISION = "32279effe8c19989596f05d353d1447f51d9e915"
VOXCPM2_FOLDER = "voxcpm2"
VOXCPM2_FILES = [
    "config.json",
    "model.safetensors",
    "audiovae.pth",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
]
VOXCPM2_TYPES = ("voxcpm2_voicedesign", "voxcpm2_base")
VOXCPM2_DURATION_SLIDER = {
    "label": "Max duration (seconds)",
    "min": 1,
    "max": 600,
    "increment": 1,
    "default": 60,
}
VOXCPM2_AUDIO_PROMPT_TYPE_SOURCES = {
    "selection": ["A", "AB"],
    "labels": {
        "A": "Voice cloning of 1 speaker",
        "AB": "Voice cloning of 2 speakers (Speaker 1 and Speaker 2)",
    },
    "letters_filter": "AB",
    "default": "A",
}
AUTO_SPLIT_SETTING_ID = "auto_split_every_s"
AUTO_SPLIT_MIN_SECONDS = 5.0
AUTO_SPLIT_MAX_SECONDS = 90.0
STYLE_SETTING_ID = "style"
STYLE_MAX_CHARS = 300
VOXCPM2_BASE_CUSTOM_SETTINGS = [
    {
        "id": STYLE_SETTING_ID,
        "label": "Style direction (optional): how the cloned voice should speak, e.g. whispering, excited, slower. With a direction the reference transcript is not used.",
        "name": "Style direction",
        "type": "text",
    },
    {
        "id": AUTO_SPLIT_SETTING_ID,
        "label": "Auto Split Every s (5-90, optional), for very long speeches.",
        "name": "Auto Split Every s",
        "type": "float",
    },
]
STEPS_MIN, STEPS_MAX = 4, 30
CFG_MIN, CFG_MAX = 1.0, 5.0


def get_voxcpm2_model_def(base_model_type: str) -> dict:
    common = {
        "audio_only": True,
        "image_outputs": False,
        "sliding_window": False,
        "guidance_max_phases": 1,
        "no_negative_prompt": True,
        "inference_steps": True,
        "inference_steps_min": STEPS_MIN,
        "inference_steps_max": STEPS_MAX,
        "temperature": False,
        "image_prompt_types_allowed": "",
        "supports_early_stop": True,
        "profiles_dir": [base_model_type],
        "duration_slider": dict(VOXCPM2_DURATION_SLIDER),
        "text_prompt_enhancer_instructions": TTS_MONOLOGUE_PROMPT,
        "text_prompt_enhancer_max_tokens": 512,
        "prompt_enhancer_button_label": "Write",
        "compile": False,
        "parent_model_type": "voxcpm2_base",
        "pause_between_sentences": True,
        "preserve_empty_prompt_lines": True,
        "required_model_assets": [f"{VOXCPM2_FOLDER}/{name}" for name in VOXCPM2_FILES],
        "prompt_enhancer_def": {
            "selection": ["T", "T1"] if base_model_type == "voxcpm2_base" else ["T"],
            "labels": {
                "T": "A Speech based on current Prompt",
                "T1": "A Dialogue between two People based on current Prompt",
            },
            "default": "T",
        },
    }
    if base_model_type == "voxcpm2_voicedesign":
        return {
            **common,
            "alt_prompt": {
                "label": "Voice description",
                "placeholder": "young woman from Madrid, warm and lively voice, clear diction",
                "lines": 2,
            },
        }
    return {
        **common,
        "alt_prompt": {
            "label": "Reference transcript(s) (optional, two-speaker: one per line)",
            "placeholder": "Speaker 1 reference transcript\nSpeaker 2 reference transcript",
            "lines": 3,
        },
        "any_audio_prompt": True,
        "audio_prompt_choices": True,
        "audio_prompt_type_sources": dict(VOXCPM2_AUDIO_PROMPT_TYPE_SOURCES),
        "custom_settings": [one.copy() for one in VOXCPM2_BASE_CUSTOM_SETTINGS],
        "text_prompt_enhancer_instructions1": TTS_QWEN3_DIALOGUE_PROMPT,
        "text_prompt_enhancer_max_tokens1": 512,
        "audio_guide_label": "Speaker 1 reference voice",
        "audio_guide2_label": "Speaker 2 reference voice",
    }


def get_voxcpm2_download_def() -> list[dict]:
    return [{
        "repoId": VOXCPM2_REPO,
        "revision": VOXCPM2_REVISION,
        "sourceFolderList": [""],
        "targetFolderList": [VOXCPM2_FOLDER],
        "fileList": [list(VOXCPM2_FILES)],
    }]


def _validate_auto_split(inputs) -> str | None:
    custom = inputs.get("custom_settings")
    if custom is None:
        return None
    if not isinstance(custom, dict):
        return "Custom settings must be a dictionary."
    style = custom.get(STYLE_SETTING_ID)
    if style is not None and (not isinstance(style, str) or len(style) > STYLE_MAX_CHARS):
        return f"Style direction must be text of at most {STYLE_MAX_CHARS} characters."
    raw = custom.get(AUTO_SPLIT_SETTING_ID)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        custom.pop(AUTO_SPLIT_SETTING_ID, None)
        return None
    try:
        if isinstance(raw, bool):
            raise ValueError()
        seconds = float(raw)
    except (TypeError, ValueError):
        seconds = -1.0
    if not AUTO_SPLIT_MIN_SECONDS <= seconds <= AUTO_SPLIT_MAX_SECONDS:
        return (f"Auto Split Every s must be between {int(AUTO_SPLIT_MIN_SECONDS)} and "
                f"{int(AUTO_SPLIT_MAX_SECONDS)} seconds.")
    custom[AUTO_SPLIT_SETTING_ID] = seconds
    return None


def _validate_recipe(inputs) -> str | None:
    steps = inputs.get("num_inference_steps")
    if steps is not None and not (isinstance(steps, int) and STEPS_MIN <= steps <= STEPS_MAX):
        return f"VoxCPM2 uses {STEPS_MIN}-{STEPS_MAX} inference steps (10 by default)."
    cfg = inputs.get("guidance_scale")
    if cfg is not None and not (isinstance(cfg, (int, float)) and CFG_MIN <= float(cfg) <= CFG_MAX):
        return f"VoxCPM2 guidance must be between {CFG_MIN:g} and {CFG_MAX:g} (2 by default)."
    return None


class family_handler:
    @staticmethod
    def query_supported_types():
        return list(VOXCPM2_TYPES)

    @staticmethod
    def query_family_maps():
        return {}, {}

    @staticmethod
    def query_model_family():
        return "tts"

    @staticmethod
    def query_family_infos():
        return {"tts": (200, "TTS")}

    @staticmethod
    def register_lora_cli_args(parser, lora_root):
        parser.add_argument(
            "--lora-dir-voxcpm2",
            type=str,
            default=None,
            help=f"Path to a directory that contains VoxCPM2 settings (default: {os.path.join(lora_root, 'voxcpm2')})",
        )

    @staticmethod
    def get_lora_dir(base_model_type, args, lora_root):
        return getattr(args, "lora_dir_voxcpm2", None) or os.path.join(lora_root, "voxcpm2")

    @staticmethod
    def query_model_def(base_model_type, model_def):
        return get_voxcpm2_model_def(base_model_type)

    @staticmethod
    def query_model_files(computeList, base_model_type, model_def=None):
        return get_voxcpm2_download_def()

    @staticmethod
    def load_model(model_filename, model_type, base_model_type, model_def, quantizeTransformer=False,
                   text_encoder_quantization=None, dtype=None, VAE_dtype=None, mixed_precision_transformer=False,
                   save_quantized=False, submodel_no_list=None, text_encoder_filename=None, profile=0, **kwargs):
        from .voxcpm2.pipeline import VoxCPM2Pipeline

        model_dir = fl.locate_folder(VOXCPM2_FOLDER, error_if_none=False)
        if model_dir is None:
            raise FileNotFoundError(f"VoxCPM2 weights folder '{VOXCPM2_FOLDER}' is missing; download {VOXCPM2_REPO}.")
        pipeline = VoxCPM2Pipeline(model_dir, base_model_type)
        return pipeline, {"transformer": pipeline.model}

    @staticmethod
    def fix_settings(base_model_type, settings_version, model_def, ui_defaults):
        ui_defaults.setdefault("alt_prompt", "")
        ui_defaults.setdefault("audio_prompt_type", "A" if base_model_type == "voxcpm2_base" else "")
        ui_defaults.setdefault("num_inference_steps", 10)
        ui_defaults.setdefault("guidance_scale", 2.0)
        if base_model_type == "voxcpm2_base":
            ui_defaults.setdefault("pause_seconds", 0.5)
            if str(ui_defaults.get("audio_prompt_type") or "A").upper() not in ("A", "AB"):
                ui_defaults["audio_prompt_type"] = "A"

    @staticmethod
    def update_default_settings(base_model_type, model_def, ui_defaults):
        ui_defaults.update({
            "audio_prompt_type": "A" if base_model_type == "voxcpm2_base" else "",
            "alt_prompt": "" if base_model_type == "voxcpm2_base" else "young woman from Madrid, warm and lively voice, clear diction",
            "duration_seconds": VOXCPM2_DURATION_SLIDER["default"],
            "pause_seconds": 0.5,
            "repeat_generation": 1,
            "video_length": 0,
            "num_inference_steps": 10,
            "guidance_scale": 2.0,
            "negative_prompt": "",
            "multi_prompts_gen_type": 2,
        })

    @staticmethod
    def validate_generative_prompt(base_model_type, model_def, inputs, one_prompt):
        if one_prompt is None or not str(one_prompt).strip():
            return "Prompt text cannot be empty for VoxCPM2."
        if base_model_type != "voxcpm2_base":
            return None
        if inputs.get("audio_guide") is None:
            return "VoxCPM2 voice clone requires Speaker 1 reference audio."
        tags = {int(m.group(1)) for m in re.finditer(r"Speaker\s*(\d+)\s*:", str(one_prompt), flags=re.IGNORECASE)}
        if "B" in str(inputs.get("audio_prompt_type", "A") or "A").upper():
            if inputs.get("audio_guide2") is None:
                return "Two-speaker mode requires Speaker 2 reference audio."
            if tags != {1, 2}:
                return "Two-speaker mode requires prompt lines using Speaker 1: and Speaker 2:."
        elif tags:
            return "Speaker-tag dialogue requires two-speaker mode (set audio prompt mode to Dialogue)."
        return None

    @staticmethod
    def validate_generative_settings(base_model_type, model_def, inputs):
        return _validate_recipe(inputs) or (_validate_auto_split(inputs) if base_model_type == "voxcpm2_base" else None)
