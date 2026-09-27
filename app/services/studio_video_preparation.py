"""Provider-free preparation for the closed generation.video command.

Model catalog and installed-file checks run through injected callbacks.
``StudioVideoResources`` inspects canonical references. This boundary does
not download weights, schedule a worker or create a second queue.
"""

from __future__ import annotations

from copy import deepcopy
import math
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import HTTPException

from services.image_generation_commands import command_error
from services.studio_image_resources import validate_lora_multipliers
from services.video_generation_spec import VIDEO_MODEL_TYPES, WAN_T2V_ARCHITECTURES


_REFERENCE_FIELDS = (
    "image_start",
    "image_end",
    "image_refs",
    "video_guide",
    "video_mask",
    "video_source",
)


def _definition_for(model_definition, model_type: str) -> dict[str, Any]:
    if callable(model_definition):
        definition = model_definition(model_type)
    elif isinstance(model_definition, Mapping):
        definition = model_definition.get(model_type)
    else:
        definition = None
    if not isinstance(definition, Mapping):
        raise ValueError("Choose an installed Wan 2.1 Text2Video model from the catalog")
    return deepcopy(dict(definition))


def _finite(value: Any, field: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"input.params.{field} must be a finite number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"input.params.{field} must be a finite number")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"input.params.{field} is below the model's declared minimum")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"input.params.{field} exceeds the model's declared maximum")
    return parsed


def _has_reference(value) -> bool:
    if value in (None, "", []):
        return False
    if isinstance(value, list):
        return any(item not in (None, "") for item in value)
    return True


def _validate_model(
    model_type: str,
    definition: Mapping[str, Any],
    model_downloaded: Callable[[str], bool],
) -> None:
    if model_type not in VIDEO_MODEL_TYPES:
        raise ValueError("Choose a registered Wan 2.1 Text2Video model")
    if definition.get("image_outputs") or definition.get("audio_only") or definition.get("returns_audio"):
        raise ValueError("The selected model is not a Wan 2.1 Text2Video handler")
    architecture = definition.get("architecture")
    if architecture is not None and str(architecture) not in WAN_T2V_ARCHITECTURES:
        raise ValueError("The selected model definition is not a Wan 2.1 Text2Video architecture")
    if architecture is None and definition.get("t2v_class") is not True:
        raise ValueError("The selected model definition is not a Wan 2.1 Text2Video handler")
    if not callable(model_downloaded) or not model_downloaded(model_type):
        raise command_error(
            409,
            "model_unavailable",
            "Required Wan 2.1 Text2Video model files are not installed; install them before submitting",
        )


def _validate_frames(working: dict[str, Any], definition: Mapping[str, Any]) -> None:
    length = working.get("video_length")
    if type(length) is not int:
        raise ValueError("input.params.video_length must be an integer frame count")
    minimum = int(definition.get("frames_minimum", 5) or 5)
    step = int(definition.get("frames_steps", 4) or 4)
    maximum = definition.get("frames_maximum")
    if length < minimum:
        raise ValueError("input.params.video_length is below the model's declared minimum")
    if maximum is not None and length > int(maximum):
        raise ValueError("input.params.video_length exceeds the model's declared maximum")
    if step > 0 and (length - minimum) % step:
        raise ValueError("input.params.video_length must follow the model's frame step")


def _validate_sampling(working: dict[str, Any], definition: Mapping[str, Any]) -> int:
    steps = working.get("num_inference_steps")
    if type(steps) is not int or steps < 1:
        raise ValueError("input.params.num_inference_steps must be a positive integer")
    lower = definition.get("inference_steps_min")
    upper = definition.get("inference_steps_max")
    if lower is not None and steps < int(lower):
        raise ValueError("input.params.num_inference_steps is below the model's declared minimum")
    if upper is not None and steps > int(upper):
        raise ValueError("input.params.num_inference_steps exceeds the model's declared maximum")
    _finite(working.get("guidance_scale"), "guidance_scale", minimum=0)
    phases = working.get("guidance_phases", 1)
    if type(phases) is not int or not 1 <= phases <= 3:
        raise ValueError("input.params.guidance_phases must be an integer from 1 to 3")
    maximum = definition.get("guidance_max_phases")
    if maximum is not None and phases > int(maximum):
        raise ValueError("input.params.guidance_phases exceeds the model's declared maximum")
    solver = working.get("sample_solver") or ""
    choices = definition.get("sample_solvers") or []
    allowed = [item[1] if isinstance(item, (list, tuple)) else str(item) for item in choices]
    if solver and allowed and solver not in allowed:
        raise ValueError("input.params.sample_solver is not supported by this model")
    if working.get("negative_prompt") and definition.get("no_negative_prompt"):
        raise ValueError("input.params.negative_prompt is not supported by this model")
    return max(1, int(maximum if maximum is not None else 1))


def _reject_unsupported_references(working: Mapping[str, Any]) -> None:
    active = [field for field in _REFERENCE_FIELDS if _has_reference(working.get(field))]
    if active:
        raise ValueError(
            "This Wan 2.1 Text2Video command does not accept image or video references"
        )


def prepare_studio_video(
    params,
    *,
    model_definition,
    model_downloaded,
    resources,
    execution_policy,
):
    """Return detached native video parameters and portable resource identities."""
    if not isinstance(params, dict):
        raise command_error(422, "invalid_studio_video_input", "Video parameters must be an object")
    working = deepcopy(params)
    try:
        workspace = working.get("workspace")
        if not isinstance(workspace, str) or not workspace.strip():
            raise ValueError("input.workspace must be an explicit output workspace")
        if not callable(execution_policy):
            raise TypeError("execution_policy must be a workspace policy callback")
        execution_policy(workspace)

        model_type = working.get("model_type")
        if not isinstance(model_type, str):
            raise ValueError("input.params.model_type must be a string")
        definition = _definition_for(model_definition, model_type)
        _validate_model(model_type, definition, model_downloaded)
        _validate_frames(working, definition)
        # T2V forbids sliding windows. primary_settings defaults
        # sliding_window_size to 129; validate_settings then returns None for
        # any longer admitted job, and _run_generation treats a skipped-only
        # queue as success with no file. Pin one window to the requested length.
        working["sliding_window_size"] = working["video_length"]
        working.setdefault("multi_prompts_gen_type", 2)
        phases = _validate_sampling(working, definition)
        if working.get("activated_loras") or working.get("loras_multipliers"):
            validate_lora_multipliers(working, phases)

        prepared, media = resources.prepare_media(working)
        if not isinstance(prepared, dict) or not isinstance(media, list):
            raise ValueError("video resource preparation returned invalid native parameters")
        prepared = deepcopy(prepared)
        media = deepcopy(media)
        _reject_unsupported_references(prepared)

        prepared["generation_mode"] = "video"
        prepared["image_mode"] = 0
        prepared["sliding_window_size"] = prepared["video_length"]
        prepared.setdefault("repeat_generation", 1)
        prepared.setdefault("batch_size", 1)
        prepared.setdefault("prompt_enhancer", "")
        prepared.setdefault("multi_prompts_gen_type", 2)
        loras = resources.prepare_loras(prepared, definition)
        return prepared, [*media, *deepcopy(loras)]
    except HTTPException:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise command_error(422, "invalid_studio_video_input", str(error)) from error


__all__ = ["prepare_studio_video"]
