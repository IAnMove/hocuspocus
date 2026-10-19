"""Catalog adapter; execution belongs to the existing generation worker."""
from services.creation_model_catalog import MODEL_TYPES, model_definition, download_definitions, validate


class family_handler:
    @staticmethod
    def query_supported_types():
        return list(MODEL_TYPES)

    @staticmethod
    def query_family_maps():
        return {}, {}

    @staticmethod
    def query_model_family():
        return "creation_models"

    @staticmethod
    def query_family_infos():
        return {"creation_models": (72, "FLUX 3 / Drama 3"), "flux3": (102, "FLUX 3")}

    @staticmethod
    def register_lora_cli_args(parser, lora_root):
        pass

    @staticmethod
    def get_lora_dir(base_model_type, args, lora_root):
        return lora_root

    @staticmethod
    def query_model_def(base_model_type, model_def):
        return model_definition(base_model_type)

    @staticmethod
    def query_model_files(computeList, base_model_type, model_def=None):
        return download_definitions(base_model_type)

    @staticmethod
    def update_default_settings(base_model_type, model_def, ui_defaults):
        flux = base_model_type.startswith("flux3_")
        ui_defaults.update(num_inference_steps=16 if flux else 0, guidance_scale=1.0,
                           video_length=0, image_mode=1 if flux else 0,
                           resolution="1024x1024", repeat_generation=1,
                           multi_prompts_gen_type=2, negative_prompt="")
        if not flux:
            ui_defaults.update(duration_seconds=60, temperature=1.0, top_p=0.9, top_k=30,
                               alt_prompt="", audio_prompt_type="A" if base_model_type.endswith("_base") else "")

    @staticmethod
    def fix_settings(base_model_type, settings_version, model_def, ui_defaults):
        pass

    @staticmethod
    def validate_generative_settings(base_model_type, model_def, inputs):
        try:
            validate({**inputs, "model_type": base_model_type})
        except (ValueError, TypeError) as error:
            return str(error)

    @staticmethod
    def load_model(*args, **kwargs):
        raise RuntimeError("FLUX 3 / Drama 3 must run through the isolated creation service")
