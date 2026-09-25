import json
import math
import os

import torch
from accelerate import init_empty_weights
from diffusers import FlowMatchEulerDiscreteScheduler
from PIL import Image
from transformers import AutoTokenizer, Qwen3VLForConditionalGeneration, Qwen3VLProcessor

from mmgp import offload
from shared.utils import files_locator as fl
from shared.utils.utils import calculate_new_dimensions, convert_tensor_to_image

from .autoencoder_kl_qwenimage21 import AutoencoderKLQwenImage21
from .convert_diffusers_qwen21_vae import convert_qwen_image_21_vae_state_dict
from .pipeline_qwenimage21 import QwenImage21Pipeline
from .transformer_qwenimage21 import QwenImage21Transformer2DModel

_TRANSFORMER_CONFIG = os.path.join(os.path.dirname(__file__), "configs", "qwen_image_21.json")
_VAE_CONFIG = os.path.join(os.path.dirname(__file__), "configs", "qwen_image_21_vae.json")
_VAE_FILENAME = "qwen_image_2.1_vae_bf16.safetensors"
_TEXT_ENCODER_FOLDER = "Qwen3-VL-8B-Instruct"
# Viggle v0.2.1 raw sigma nodes; the pipeline applies resolution shifting.
_VIGGLE_TURBO_SIGMAS = (1.0, 0.9375, 0.875, 0.75, 0.5, 0.25)


def _remap_qwen3vl_comfy_keys(state_dict):
    """Comfy packs the LM under model.*; HuggingFace Qwen3-VL uses model.language_model.*."""
    remapped = {}
    for key, value in state_dict.items():
        if key.startswith(("model.layers.", "model.embed_tokens.", "model.norm.")):
            key = "model.language_model." + key[len("model."):]
        remapped[key] = value
    return remapped


def _locate_qwen21_vae(vae_checkpoint):
    """Comfy downloads the 2.1 VAE into ckpts/vae/; also accept a root-level copy."""
    if isinstance(vae_checkpoint, str) and "://" in vae_checkpoint:
        return fl.locate_file(vae_checkpoint)
    basename = os.path.basename(vae_checkpoint)
    for candidate in (vae_checkpoint, basename, os.path.join("vae", basename)):
        found = fl.locate_file(candidate, error_if_none=False)
        if found:
            return found
    return fl.locate_file(basename)


class model_factory:
    def __init__(
        self,
        checkpoint_dir,
        model_filename=None,
        model_type=None,
        model_def=None,
        base_model_type=None,
        text_encoder_filename=None,
        quantizeTransformer=False,
        save_quantized=False,
        dtype=torch.bfloat16,
        VAE_dtype=torch.float32,
        mixed_precision_transformer=False,
        VAE_upsampling=None,
    ):
        model_def = model_def or {}
        self.viggle_turbo = bool(model_def.get("qwen21_viggle_turbo"))
        transformer_filename = model_filename[0]
        text_encoder_folder = model_def.get("text_encoder_folder") or _TEXT_ENCODER_FOLDER
        tokenizer_path = fl.locate_folder(text_encoder_folder)
        if tokenizer_path is None:
            tokenizer_path = os.path.dirname(text_encoder_filename)
        processor_dir = tokenizer_path
        for candidate in (tokenizer_path, os.path.join(tokenizer_path, "processor")):
            if os.path.isfile(os.path.join(candidate, "preprocessor_config.json")):
                processor_dir = candidate
                break
        encoder_config = fl.locate_file(os.path.join(text_encoder_folder, "config.json"), error_if_none=False)
        if encoder_config is None:
            encoder_config = fl.locate_file(os.path.join(text_encoder_folder, "text_encoder", "config.json"))

        processor = Qwen3VLProcessor.from_pretrained(processor_dir)
        tokenizer = AutoTokenizer.from_pretrained(processor_dir)
        self.base_model_type = base_model_type

        with open(_TRANSFORMER_CONFIG, "r", encoding="utf-8") as handle:
            transformer_config = json.load(handle)
        transformer_config.pop("_diffusers_version", None)
        transformer_config.pop("_class_name", None)

        with init_empty_weights():
            transformer = QwenImage21Transformer2DModel(**transformer_config)

        source = model_def.get("source")
        offload.load_model_data(
            transformer,
            source if source is not None else transformer_filename,
            writable_tensors=False,
        )
        if source is not None:
            from wgp import save_model
            save_model(transformer, model_type, dtype, None)
        if save_quantized:
            from wgp import save_quantized_model
            save_quantized_model(transformer, model_type, model_filename[0], dtype, _TRANSFORMER_CONFIG)

        text_encoder = offload.fast_load_transformers_model(
            text_encoder_filename,
            writable_tensors=True,
            modelClass=Qwen3VLForConditionalGeneration,
            defaultConfigPath=encoder_config,
            preprocess_sd=_remap_qwen3vl_comfy_keys,
            ignore_unused_weights=True,
        )

        vae_override = model_def.get("vae_URL") or model_def.get("vae_URLs")
        if isinstance(vae_override, list):
            vae_override = vae_override[0] if vae_override else None
        if isinstance(vae_override, dict):
            vae_override = vae_override.get("URLs")
        vae_checkpoint = vae_override or _VAE_FILENAME
        vae = offload.fast_load_transformers_model(
            _locate_qwen21_vae(vae_checkpoint),
            writable_tensors=True,
            modelClass=AutoencoderKLQwenImage21,
            defaultConfigPath=_VAE_CONFIG,
            preprocess_sd=convert_qwen_image_21_vae_state_dict,
        )
        vae.to(dtype=VAE_dtype)

        scheduler = FlowMatchEulerDiscreteScheduler(
            base_image_seq_len=256,
            base_shift=0.5,
            invert_sigmas=False,
            max_image_seq_len=8192,
            max_shift=0.9,
            num_train_timesteps=1000,
            shift=1.0,
            shift_terminal=None if self.viggle_turbo else 0.02,
            stochastic_sampling=False,
            time_shift_type="exponential",
            use_beta_sigmas=False,
            use_dynamic_shifting=True,
            use_exponential_sigmas=False,
            use_karras_sigmas=False,
        )
        self.pipeline = QwenImage21Pipeline(scheduler, vae, text_encoder, processor, transformer)
        self.vae = vae
        self.text_encoder = text_encoder
        self.tokenizer = tokenizer
        self.transformer = transformer
        self.processor = processor

    @property
    def _interrupt(self):
        return self.pipeline.interrupt

    @_interrupt.setter
    def _interrupt(self, value):
        self.pipeline.interrupt = value

    def generate(
        self,
        seed: int | None = None,
        input_prompt: str = "a neon shop sign",
        n_prompt=None,
        sampling_steps: int = 40,
        input_ref_images=None,
        input_frames=None,
        input_masks=None,
        width=2048,
        height=2048,
        guide_scale: float = 1,
        fit_into_canvas=None,
        callback=None,
        loras_slists=None,
        batch_size=1,
        video_prompt_type="",
        VAE_tile_size=None,
        joint_pass=True,
        sample_solver="default",
        denoising_strength=1.0,
        masking_strength=1.0,
        model_mode=0,
        outpainting_dims=None,
        **kwargs,
    ):
        turbo = getattr(self, "viggle_turbo", False)
        if turbo and (sampling_steps != 6 or guide_scale != 1):
            raise ValueError("Qwen Image 2.1 Viggle Turbo requires 6 steps and CFG 1.")
        if n_prompt is None or len(n_prompt) == 0:
            n_prompt = " "

        from shared.qtypes.int8_convrot import install_native_lora_forwards
        install_native_lora_forwards(self.transformer)
        install_native_lora_forwards(self.text_encoder)

        if input_frames is not None:
            input_ref_images = [convert_tensor_to_image(input_frames)] + (
                [] if input_ref_images is None else input_ref_images
            )

        if input_ref_images:
            if turbo and len(input_ref_images) > 3:
                raise ValueError("Qwen Image 2.1 Viggle Turbo accepts at most 3 input images, including the edit source.")
            if "K" in (video_prompt_type or "") and input_ref_images:
                ref_w, ref_h = input_ref_images[0].size
                height, width = calculate_new_dimensions(height, width, ref_h, ref_w, fit_into_canvas, block_size=32)
            images = []
            for img in input_ref_images[:10]:
                if not isinstance(img, Image.Image):
                    img = convert_tensor_to_image(img)
                images.append(img)
        else:
            images = None

        image_mask = None if input_masks is None else convert_tensor_to_image(input_masks, mask_levels=True)
        image = self.pipeline(
            prompt=input_prompt,
            negative_prompt=n_prompt if guide_scale and guide_scale > 1 else None,
            image=images,
            image_mask=image_mask,
            width=width,
            height=height,
            num_inference_steps=sampling_steps,
            sigmas=list(_VIGGLE_TURBO_SIGMAS) if turbo else None,
            num_images_per_prompt=batch_size,
            true_cfg_scale=guide_scale,
            callback=callback,
            loras_slists=loras_slists,
            VAE_tile_size=VAE_tile_size,
            denoising_strength=denoising_strength,
            masking_strength=masking_strength,
            output_type="pt",
            return_dict=False,
            output_resolution=math.sqrt(width * height),
            generator=torch.Generator(device="cuda").manual_seed(seed),
        )
        if image is None:
            return None
        if isinstance(image, (list, tuple)):
            image = image[0]
        if isinstance(image, Image.Image):
            from shared.utils.utils import convert_image_to_tensor
            image = convert_image_to_tensor(image).unsqueeze(0)
        if image.ndim == 3:
            image = image.unsqueeze(0)
        return image.transpose(0, 1)
