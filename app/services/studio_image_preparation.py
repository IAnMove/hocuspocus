"""Read-only model/resource preflight for full Studio image commands."""
from copy import deepcopy

from services.image_generation_commands import command_error, validate_image_model
from services.studio_image_resources import validate_lora_multipliers
from services.studio_image_conditioning import validate_image_selectors


def _has_reference(value):
    return any(value) if isinstance(value, list) else bool(value)


def _validate_conditioning(params, definition):
    if params.get("image_refs") and not definition.get("image_ref_choices"):
        raise ValueError("input.params.image_refs: the model does not support image references")
    allowed = definition.get("image_prompt_types_allowed", "")
    for field, letter in (("image_start", "S"), ("image_end", "E")):
        if _has_reference(params.get(field)) and letter not in allowed:
            raise ValueError(f"input.params.{field}: the model does not support this frame input")
    if _has_reference(params.get("image_mask")) and not definition.get("inpaint_support"):
        raise ValueError("input.params.image_mask: the model does not support inpainting")
    if params.get("negative_prompt") and definition.get("no_negative_prompt"):
        raise ValueError("input.params.negative_prompt: the model does not use a negative prompt")
    maximum = definition.get("guidance_max_phases", 1)
    if params.get("guidance_phases", 1) > maximum:
        raise ValueError("input.params.guidance_phases exceeds the model's supported phases")
    return maximum


def _validate_processors(params, capabilities, validate_selection, validated_settings):
    spatial = params.get("spatial_upsampling", "")
    temporal = params.get("temporal_upsampling", "")
    error = validate_selection(spatial, temporal, True)
    if error:
        raise ValueError(error)
    if spatial:
        selected = next((item for item in capabilities() if item["value"] == spatial and item["kind"] == "spatial"), None)
        if not selected or not selected.get("enabled") or "image" not in selected.get("media", []):
            raise ValueError("input.params.spatial_upsampling: select an installed image processor")
    submitted = params.get("wangp_processor_settings") or {}
    resolved = validated_settings(spatial, submitted)
    if set(submitted) != set(resolved):
        raise ValueError("input.params.wangp_processor_settings contains settings not supported by the selected processor")


def _validate_model_options(params, definition):
    steps = params["num_inference_steps"]
    if steps < definition.get("inference_steps_min", 1) or steps > definition.get("inference_steps_max", 1000):
        raise ValueError("input.params.num_inference_steps is outside this model's declared range")
    solver = params.get("sample_solver")
    choices = definition.get("sample_solvers") or []
    allowed = [item[1] if isinstance(item, (list, tuple)) else str(item) for item in choices]
    if solver and allowed and solver not in allowed:
        raise ValueError("input.params.sample_solver is not supported by this model")
    if params.get("skip_steps_cache_type") == "first_block" and not definition.get("first_block_cache"):
        raise ValueError("input.params.skip_steps_cache_type: this model does not support first-block caching")


def prepare_studio_image(params, *, model_definition, model_downloaded, resources,
                         execution_policy, processor_capabilities, validate_processors,
                         processor_settings, missing_model_files=None):
    """Return detached native parameters and inspected identities before admission."""
    execution_policy(params["workspace"])
    definition = validate_image_model(params, model_definition=model_definition,
                                      model_downloaded=model_downloaded, allow_references=True,
                                      missing_model_files=missing_model_files)
    try:
        maximum_phases = _validate_conditioning(params, definition)
        validate_image_selectors(params, definition)
        _validate_model_options(params, definition)
        validate_lora_multipliers(params, maximum_phases)
        _validate_processors(params, processor_capabilities, validate_processors, processor_settings)
        working, media = resources.prepare_media(params)
        loras = resources.prepare_loras(params, definition)
        return deepcopy(working), [*media, *loras]
    except (ValueError, OSError) as error:
        raise command_error(422, "invalid_studio_input", str(error)) from error
