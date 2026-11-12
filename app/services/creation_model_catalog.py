"""Pinned assets and provider-free contracts for the optional creation runtime."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = ROOT / "ckpts" / "creation_models"
FLUX_REPO = "black-forest-labs/flux-3-image-klein-comfy"
FLUX_REVISION = "61fb80f4ce5adf6708190e218611c28f8c083aaa"
DRAMA_REPO = "PedroMarinhoDev/Drama-3-ComfyUI"
DRAMA_REVISION = "9063c072019aa578895e51adb5489c6cd2c834b0"
MODEL_TYPES = ("flux3_klein", "flux3_klein_edit", "drama3_voicedesign", "drama3_base")
FLUX_FILES = (
    "diffusion_models/flux3_image_klein_sd_int8_convrot.safetensors",
    "text_encoders/qwen3vl_4b_int8_convrot.safetensors",
    "vae/flux2-vae.safetensors",
)
DRAMA_FILES = ("diffusion_models/drama3_int8experts_bf16.safetensors", "vae/drama3_codec.safetensors")


def assets(model_type):
    if model_type not in MODEL_TYPES:
        raise ValueError("Unknown creation model")
    flux = model_type.startswith("flux3_")
    return (FLUX_REPO, FLUX_REVISION, FLUX_FILES) if flux else (DRAMA_REPO, DRAMA_REVISION, DRAMA_FILES)


def models_sharing_assets(model_type):
    if model_type not in MODEL_TYPES:
        return {model_type}
    return {name for name in MODEL_TYPES if assets(name) == assets(model_type)}


def model_definition(model_type):
    flux = model_type.startswith("flux3_")
    definition = {
        "creation_sidecar": True, "compile": False, "sliding_window": False,
        "group": "flux3" if flux else "tts",
        "image_outputs": flux, "audio_only": not flux, "no_negative_prompt": True,
        "guidance_max_phases": 1, "lock_guidance_scale": True,
        "image_prompt_types_allowed": "", "lora_support": False,
        "required_model_assets": ["creation_models/" + name for name in assets(model_type)[2]],
        "selector_help": "Install FLUX 3 / Drama 3 Support from Pinokio → Advanced, then download this model in Settings.",
        "profiles_dir": [model_type],
    }
    if flux:
        definition.update(inference_steps=True, inference_steps_min=4, inference_steps_max=50,
                          sample_solvers=[("Euler", "euler"), ("ER-SDE", "er_sde")],
                          max_image_refs=10, fit_into_canvas_image_refs=0)
        if model_type.endswith("_edit"):
            definition.update(image_conditioning_required=True, image_source_required=True,
                              image_ref_choices={"choices": [("No extra references", ""), ("Reference images", "I")],
                                                 "letters_filter": "I", "default": ""},
                              at_least_one_image_ref_needed=False)
    else:
        definition.update(inference_steps=False, temperature=True, top_p_slider=True, top_k_slider=True, max_voice_count=1,
                          duration_slider={"label": "Maximum seconds per text chunk", "min": 1,
                                           "max": 180, "default": 60, "increment": 1},
                          preserve_empty_prompt_lines=True,
                          custom_settings=[{"id": "expert_cache_gb", "type": "float",
                                            "label": "Expert GPU cache in GB (0 = automatic)", "name": "Expert GPU cache"}])
        if model_type.endswith("_base"):
            definition.update(any_audio_prompt=True, audio_prompt_choices=True,
                              audio_prompt_type_sources={"selection": ["A"], "labels": {"A": "Reference voice"},
                                                         "letters_filter": "A", "default": "A"},
                              audio_guide_label="Reference recording",
                              alt_prompt={"label": "Exact reference transcript", "lines": 3})
        else:
            definition["alt_prompt"] = {"label": "Voice direction (optional)", "lines": 2}
    return definition


def download_definitions(model_type):
    repo, revision, files = assets(model_type)
    # The native downloader resolves filenames relative to its checkpoint root.
    return [{"repoId": repo, "revision": revision,
             "sourceFolderList": [str(Path(name).parent).replace("\\", "/") if model_type.startswith("flux3_") else ""],
             "targetFolderList": ["creation_models/" + str(Path(name).parent).replace("\\", "/")],
             "fileList": [[Path(name).name]]} for name in files]


def _validate_edit_controls(params):
    if params.get("spatial_upsampling") or params.get("temporal_upsampling"):
        raise ValueError("Use Tools to upscale creation-model outputs after generation")
    # WanGP uses '#' for its inactive outpainting control.
    margin_text = str(params.get("video_guide_outpainting") or "").strip()
    has_margins = bool(margin_text) and not margin_text.startswith("#") and any(float(value) != 0 for value in margin_text.split())
    mask = params.get("image_mask")
    has_mask = any(mask) if isinstance(mask, list) else bool(mask)
    if params.get("activated_loras") or has_mask or has_margins:
        raise ValueError("This creation runtime does not support additional LoRAs, masks or outpainting")


def validate(params):
    model = params.get("model_type", "")
    if model not in MODEL_TYPES:
        raise ValueError("Unknown creation model")
    if not str(params.get("prompt") or "").strip():
        raise ValueError("Prompt cannot be empty")
    _validate_edit_controls(params)
    if model.startswith("flux3_"):
        refs = list(params.get("image_refs") or [])
        if params.get("image_guide"):
            refs.insert(0, params["image_guide"])
        if len(refs) > 10:
            raise ValueError("FLUX 3 accepts at most ten images, including the source")
        if model.endswith("_edit") and not refs:
            raise ValueError("FLUX 3 Edit requires an image")
        if not model.endswith("_edit") and refs:
            raise ValueError("Choose FLUX 3 Klein Edit to use references")
    elif model.endswith("_base"):
        if not params.get("audio_guide") or not str(params.get("alt_prompt") or "").strip():
            raise ValueError("Drama 3 cloning requires a recording and its exact transcript")
    else:
        if params.get("audio_guide"):
            raise ValueError("Choose Drama 3 Voice Clone to use a recording")
    cache = (params.get("custom_settings") or {}).get("expert_cache_gb", 0)
    if isinstance(cache, bool) or not isinstance(cache, (int, float)) or not 0 <= cache <= 16:
        raise ValueError("Expert GPU cache must be between 0 and 16 GB")
