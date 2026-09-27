"""Adapt the pinned WanGP H3 family without replacing Maestro's H3/PDD."""

from shared.wangp1272.assets import pin_downloads, pin_urls
from .minimax_h3_handler import family_handler as UpstreamHandler
from .viggle import VIGGLE_ARCHITECTURE


class family_handler(UpstreamHandler):
    @staticmethod
    def query_supported_types():
        return [name for name in UpstreamHandler.query_supported_types() if "tts_" not in name]

    @staticmethod
    def query_model_family():
        return "h3_advanced"

    @staticmethod
    def query_family_infos():
        return {"h3_advanced": (71, "H3 Advanced / Viggle")}

    @staticmethod
    def register_lora_cli_args(parser, lora_root):
        # The established H3 handler owns the shared LoRA-directory argument.
        pass

    @staticmethod
    def query_model_def(base_model_type, model_def):
        result = pin_urls(UpstreamHandler.query_model_def(base_model_type, model_def))
        result.update(wangp_1272=True, compile=False, single_block_prompt=True, sol_attention=True)
        result.update(frame_alignment_modulus=17, frame_alignment_remainder=5,
                      frame_alignment_mode="ceil", sliding_window_exact_total_frames=True,
                      sliding_window_trim_to_requested=True)
        result["profiles_dir"] = ["h3_advanced_vdn"] if model_def.get('vdn') else ["h3_advanced"]
        if base_model_type != VIGGLE_ARCHITECTURE:
            # Keep the larger Qwen encoder off the default 24 GB GPU path.
            result["text_encoder_URLs"] = pin_urls(["https://huggingface.co/DeepBeepMeep/MiniMax-H3/resolve/main/Qwen3-VL-32B-Instruct/qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf"])
        result["wangp_1272_capabilities"] = {
            "viggle": base_model_type == VIGGLE_ARCHITECTURE,
            "two_phase": base_model_type != VIGGLE_ARCHITECTURE,
            "grouped_mask": base_model_type != VIGGLE_ARCHITECTURE,
            "audio_refinement": base_model_type != VIGGLE_ARCHITECTURE,
            "vdn": bool(model_def.get("vdn")),
        }
        if base_model_type == VIGGLE_ARCHITECTURE:
            result.update(profiles_dir=[VIGGLE_ARCHITECTURE], prompt_enhancer_def=None,
                          fixed_prompt_label="Viggle character replacement", sol_attention=False, frames_maximum=124)
        return result

    @staticmethod
    def load_model(*args, **kwargs):
        if kwargs.get("save_quantized"):
            raise ValueError("H3 Advanced checkpoint export is unsupported; use the published quantized weights")
        return UpstreamHandler.load_model(*args, **kwargs)

    @staticmethod
    def query_model_files(computeList, base_model_type, model_def=None):
        return pin_downloads(UpstreamHandler.query_model_files(computeList, base_model_type, model_def))

    @staticmethod
    def validate_generative_settings(base_model_type, model_def, inputs):
        from shared.wangp1272.compat import get_outpainting_dims
        try:
            get_outpainting_dims(inputs.get('video_guide_outpainting'))
        except ValueError as error:
            return str(error)
        if base_model_type == VIGGLE_ARCHITECTURE:
            if not inputs.get("image_refs"):
                return "Viggle requires one edited frame from the Control Video"
            if len(inputs["image_refs"]) != 1:
                return "Viggle requires exactly one edited reference frame"
            if any(inputs.get(key) for key in ('activated_loras', 'video_mask', 'image_start', 'image_end', 'video_source', 'audio_guide', 'audio_guide2')):
                return "Viggle accepts its Control Video and one edited frame; remove additional LoRAs, masks, anchors and audio guides"
            inputs.update(num_inference_steps=3, sample_solver="euler", flow_shift=3.0,
                          guidance_scale=1.0, guidance_phases=1, sliding_window_size=124,
                          sliding_window_overlap=18, sliding_window_discard_last_frames=0,
                          video_prompt_type='IVU', audio_prompt_type='', force_fps='24',
                          prompt="Viggle character replacement", prompt_enhancer="", remove_background_images_ref=0)
        inputs.setdefault("frame_scheduler", None)
        return UpstreamHandler.validate_generative_settings(base_model_type, model_def, inputs)
