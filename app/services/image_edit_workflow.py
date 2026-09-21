"""Image capabilities and translation from Studio output mode to native edit mode."""
from copy import deepcopy


def image_edit_capabilities(definition):
    modes = definition.get("model_modes") or {}
    return {
        "image_source_support": bool(definition.get("inpaint_support") or definition.get("image_source_required")),
        "image_source_required": bool(definition.get("image_source_required")),
        "image_conditioning_required": bool(definition.get("image_conditioning_required")),
        "image_layer_count": definition.get("image_layer_count"),
        "image_edit_modes": modes if modes and set(modes.get("image_modes", [1, 2])) & {1, 2} else None,
        "outpaint_support": bool(set(definition.get("video_guide_outpainting") or []) & {1, 2}),
    }


def validate_image_edit(params, definition):
    source, mask = _selected(params.get("image_guide")), _selected(params.get("image_mask"))
    refs, margins = params.get("image_refs"), params.get("video_guide_outpainting")
    _validate_source(source, mask, refs, margins, definition)
    _validate_references(source, refs, bool(mask or margins), definition)
    _validate_edit_method(params, definition, bool(mask or margins))


def _validate_references(source, refs, editing, definition):
    limit = definition.get("max_image_refs")
    if limit is not None and len(refs or []) + int(source) > limit:
        raise ValueError(f"input.params.image_refs: at most {limit} input images are supported, including the source")
    if source and refs and editing and not definition.get("image_ref_inpaint"):
        raise ValueError("input.params.image_refs: this model does not support references during inpainting")


def _validate_source(source, mask, refs, margins, definition):
    if definition.get("image_source_required") and not source:
        raise ValueError("input.params.image_guide: this model requires a source image")
    if definition.get("image_conditioning_required") and not (source or refs):
        raise ValueError("input.params.image_guide: this model requires a source or reference image")
    if (mask or margins) and not source:
        raise ValueError("input.params.image_guide: masks and outpainting require a source image")
    if margins and not image_edit_capabilities(definition)["outpaint_support"]:
        raise ValueError("input.params.video_guide_outpainting: this model does not support outpainting")


def _validate_edit_method(params, definition, editing):
    choices = (definition.get("model_modes") or {}).get("choices") or []
    if editing and choices and params.get("model_mode") not in [choice[1] for choice in choices]:
        raise ValueError("input.params.model_mode: choose an inpainting method supported by this model")
    layers = definition.get("image_layer_count")
    if layers and not layers["min"] <= params.get("batch_size", layers["default"]) <= layers["max"]:
        raise ValueError("input.params.batch_size: layer count is outside this model's supported range")


def _selected(value):
    return any(value) if isinstance(value, list) else bool(value)


def native_image_edit_params(params, definition):
    """The public image contract stays mode 1; old inpainting engines need mode 2."""
    result = deepcopy(params)
    editing = _selected(result.get("image_guide")) and (_selected(result.get("image_mask")) or result.get("video_guide_outpainting"))
    modes = (definition.get("model_modes") or {}).get("image_modes", [])
    outpaint_modes = definition.get("video_guide_outpainting") or []
    needs_legacy_mode = (2 in modes and 1 not in modes) or (
        result.get("video_guide_outpainting") and 2 in outpaint_modes and 1 not in outpaint_modes)
    if editing and needs_legacy_mode:
        result["image_mode"] = 2
    return result
