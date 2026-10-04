"""Reject image inputs that the native selectors would discard."""

from services.model_selectors import conditioning_hint


def validate_image_selectors(params, definition):
    image_selector = params.get("image_prompt_type") or ""
    video_selector = params.get("video_prompt_type") or ""
    selectors = {
        "image_refs": "I" in video_selector,
        "image_guide": "V" in video_selector,
        "image_mask": all(letter in video_selector for letter in "VA") and "U" not in video_selector,
        "image_start": "S" in image_selector,
        "image_end": "E" in image_selector,
    }
    for field, enabled in selectors.items():
        _validate_selected_field(field, params.get(field), enabled, definition)
    if selectors["image_end"] and not definition.get("end_frames_always_enabled"):
        if not any(letter in image_selector for letter in "SVL"):
            raise ValueError("input.params.image_end: this model requires a start frame selector for end frames")


def _validate_selected_field(field, value, enabled, definition):
    values = value if isinstance(value, list) else [value]
    selected = any(values)
    generated_start = field == "image_start" and definition.get("black_frame")
    if selected and not enabled:
        hint = conditioning_hint(field, definition)
        raise ValueError(
            f"input.params.{field}: its native conditioning selector must be enabled.{hint}"
        )
    if enabled and not selected and not generated_start:
        raise ValueError(f"input.params.{field}: its conditioning selector requires an image")
    if enabled and selected and any(item == "" for item in values):
        raise ValueError(f"input.params.{field}: empty frame slots are not supported in image generation")
