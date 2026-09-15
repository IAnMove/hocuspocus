"""Provider-free preflight for the closed Studio music command.

This boundary checks the selected local native handler and model-declared
controls, then delegates canonical audio/LoRA inspection to the existing
``StudioSpeechResources`` implementation.  It does not load weights, call a
provider, submit a task or create a second queue.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping

from fastapi import HTTPException

from services.image_generation_commands import command_error
from services.music_model_contract import (
    ACE_DEFAULT,
    MUSIC3_LOCAL,
    YUE2_LOCAL,
    MusicModelError,
    assert_enqueue_guard,
    require_catalog_entry,
)
from services.lyrics_language import validate_lyrics_language
from services.studio_image_resources import validate_lora_multipliers
from services.studio_music_spec import STUDIO_MUSIC_MODEL_TYPES


_MODEL_DEFAULTS: dict[str, dict[str, Any]] = {
    YUE2_LOCAL: {
        "duration_seconds": 120.0, "num_inference_steps": 32,
        "guidance_scale": 1.0, "guidance_phases": 1,
    },
    ACE_DEFAULT: {
        "duration_seconds": 120.0,
        "num_inference_steps": 8,
        "guidance_scale": 1.0,
        "guidance_phases": 1,
    },
    MUSIC3_LOCAL: {
        "duration_seconds": 120.0,
        "num_inference_steps": 30,
        "guidance_scale": 1.7,
        "guidance_phases": 0,
    },
}
_AUDIO_REFERENCE_FIELDS = ("audio_guide", "audio_guide2", "audio_guide3",
                           "audio_guide4", "audio_guide5", "audio_guide6")


def _definition_for(model_definition, model_type: str) -> dict[str, Any]:
    if callable(model_definition):
        definition = model_definition(model_type)
    elif isinstance(model_definition, Mapping):
        definition = model_definition.get(model_type)
    else:
        definition = None
    if not isinstance(definition, dict):
        raise ValueError("Choose an installed local music model from the catalog")
    return deepcopy(definition)


def _finite(value: Any, field: str, *, minimum: float | None = None,
            maximum: float | None = None) -> float:
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


def _choice_values(choices: Any) -> list[Any]:
    if not isinstance(choices, (list, tuple)):
        return []
    values: list[Any] = []
    for item in choices:
        if isinstance(item, Mapping):
            item = item.get("value")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            item = item[1]
        values.append(item)
    return values


def _validate_model(model_type: str, definition: dict[str, Any], model_downloaded) -> None:
    if model_type not in STUDIO_MUSIC_MODEL_TYPES:
        raise ValueError("Choose a registered local music model; remote models use another operation")
    if definition.get("audio_only") is not True or definition.get("image_outputs"):
        raise ValueError("The selected model is not an audio-only music model")
    architecture = definition.get("architecture")
    if model_type == YUE2_LOCAL and architecture != YUE2_LOCAL:
        raise ValueError("The selected model definition does not match YuE2")
    if model_type == MUSIC3_LOCAL and architecture not in (None, MUSIC3_LOCAL):
        raise ValueError("The selected model definition does not match MiniMax-Music3")
    if model_type == ACE_DEFAULT and architecture is not None and "ace_step" not in str(architecture):
        raise ValueError("The selected model definition does not match ACE-Step")
    if not callable(model_downloaded) or not model_downloaded(model_type):
        raise command_error(409, "model_unavailable", "Required music model files are not installed; install them before submitting")


def _duration_bounds(model_type: str, definition: Mapping[str, Any]) -> tuple[float, float]:
    entry = require_catalog_entry(model_type)
    slider = definition.get("duration_slider")
    # ``duration_min`` in music_model_contract is the Story policy (20s).
    # Studio must use the selected native handler's declared slider instead:
    # both local handlers currently accept 5s, and a future handler may have a
    # different bound.  Keep the catalog maximum as a safety ceiling while
    # never raising the native minimum to satisfy Story's longer cue policy.
    # The two registered local handlers both declare a 5s native minimum. If
    # an older catalog projection omits the slider, retain that handler-backed
    # minimum rather than reopening the Story policy or accepting unsupported
    # sub-five-second requests.
    lower = 5.0
    upper = float(entry["duration_max"])
    if isinstance(slider, Mapping):
        if slider.get("min") is not None:
            lower = float(slider["min"])
        if slider.get("max") is not None:
            upper = min(upper, float(slider["max"]))
    if lower > upper:
        raise ValueError("The selected music model advertises invalid duration bounds")
    return lower, upper


def _fill_duration(working: dict[str, Any], model_type: str,
                   definition: Mapping[str, Any]) -> None:
    value = working.get("duration_seconds")
    if value is None:
        slider = definition.get("duration_slider")
        value = slider.get("default") if isinstance(slider, Mapping) else None
        value = _MODEL_DEFAULTS[model_type]["duration_seconds"] if value is None else value
        working["duration_seconds"] = value
    lower, upper = _duration_bounds(model_type, definition)
    _finite(value, "duration_seconds", minimum=lower, maximum=upper)


def _fill_steps(working: dict[str, Any], model_type: str,
                definition: Mapping[str, Any]) -> None:
    value = working.get("num_inference_steps")
    if value is None:
        value = _MODEL_DEFAULTS[model_type]["num_inference_steps"]
        working["num_inference_steps"] = value
    if type(value) is not int or value < 1:
        raise ValueError("input.params.num_inference_steps must be an integer from 1 upward")
    lower = definition.get("inference_steps_min")
    upper = definition.get("inference_steps_max")
    if lower is not None and value < int(lower):
        raise ValueError("input.params.num_inference_steps is below the model's declared minimum")
    if upper is not None and value > int(upper):
        raise ValueError("input.params.num_inference_steps exceeds the model's declared maximum")
    if model_type == MUSIC3_LOCAL and value > 100:
        raise ValueError("input.params.num_inference_steps exceeds MiniMax-Music3's maximum")


def _fill_guidance(working: dict[str, Any], model_type: str,
                   definition: Mapping[str, Any]) -> int:
    if working.get("guidance_scale") is None:
        working["guidance_scale"] = _MODEL_DEFAULTS[model_type]["guidance_scale"]
    _finite(working["guidance_scale"], "guidance_scale", minimum=1 if model_type == YUE2_LOCAL else 0, maximum=1000)
    if definition.get("lock_guidance_scale") and model_type == MUSIC3_LOCAL:
        expected = _MODEL_DEFAULTS[model_type]["guidance_scale"]
        if float(working["guidance_scale"]) != expected:
            raise ValueError("input.params.guidance_scale is locked by MiniMax-Music3")
    phases = working.get("guidance_phases")
    if phases is None:
        phases = definition.get("guidance_max_phases", _MODEL_DEFAULTS[model_type]["guidance_phases"])
        working["guidance_phases"] = int(phases)
    if type(phases) is not int or not 0 <= phases <= 16:
        raise ValueError("input.params.guidance_phases must be an integer from 0 to 16")
    maximum = definition.get("guidance_max_phases")
    if maximum is not None and phases > int(maximum):
        raise ValueError("input.params.guidance_phases exceeds the model's declared maximum")
    return max(1, int(maximum if maximum is not None else phases or 1))


def _validate_temperature(value: Any, definition: Mapping[str, Any]) -> None:
    if value is None:
        return
    _finite(value, "temperature", minimum=0, maximum=2)
    if definition.get("temperature") is False:
        raise ValueError("input.params.temperature is locked for this music model")


def _validate_top_sampling(working: dict[str, Any], definition: Mapping[str, Any]) -> None:
    top_p = working.get("top_p")
    if top_p is not None:
        _finite(top_p, "top_p", minimum=0, maximum=1)
        if not definition.get("top_p_slider"):
            raise ValueError("input.params.top_p is not supported by this music model")
    top_k = working.get("top_k")
    if top_k is not None:
        if type(top_k) is not int or top_k < 0:
            raise ValueError("input.params.top_k must be a non-negative integer")
        if not definition.get("top_k_slider"):
            raise ValueError("input.params.top_k is not supported by this music model")


def _validate_audio_sampling(working: dict[str, Any], definition: Mapping[str, Any]) -> None:
    for field in ("audio_scale", "alt_guidance_scale"):
        value = working.get(field)
        if value is None:
            continue
        _finite(value, field, minimum=0, maximum=1000)
        capability = "audio_scale_name" if field == "audio_scale" else "alt_guidance"
        if not definition.get(capability):
            raise ValueError(f"input.params.{field} is not supported by this music model")


def _validate_sampling(working: dict[str, Any], definition: Mapping[str, Any]) -> None:
    solver = working.get("sample_solver") or ""
    choices = _choice_values(definition.get("sample_solvers"))
    if solver and (not choices or solver not in choices):
        raise ValueError("input.params.sample_solver is not one of the model's declared choices")
    if working.get("negative_prompt") not in (None, ""):
        raise ValueError("input.params.negative_prompt is not supported by music models")
    _validate_temperature(working.get("temperature"), definition)
    _validate_top_sampling(working, definition)
    _validate_audio_sampling(working, definition)


def _validate_model_mode(working: dict[str, Any], definition: Mapping[str, Any]) -> None:
    value = working.get("model_mode")
    if value is None:
        modes = definition.get("model_modes")
        default = modes.get("default") if isinstance(modes, Mapping) else None
        if default is not None:
            working["model_mode"] = default
        return
    modes = definition.get("model_modes")
    choices = _choice_values(modes.get("choices") if isinstance(modes, Mapping) else None)
    if not choices or value not in choices:
        raise ValueError("input.params.model_mode is not one of the model's declared choices")


def _validate_music3_references(working: dict[str, Any], mode: str,
                                refs: Mapping[str, Any], active: Mapping[str, Any]) -> None:
    if mode or active:
        raise ValueError("MiniMax-Music3 does not support reference audio")
    for field in _AUDIO_REFERENCE_FIELDS:
        if refs[field] == "":
            working[field] = None


def _validate_ace_reference_slots(mode: str, refs: Mapping[str, Any],
                                  active: Mapping[str, Any],
                                  definition: Mapping[str, Any]) -> None:
    source = definition.get("audio_prompt_type_sources")
    choices = _choice_values(source.get("selection") if isinstance(source, Mapping) else None)
    if choices and mode not in choices:
        raise ValueError("input.params.audio_prompt_type is not a declared ACE-Step choice")
    extra = next((field for field in _AUDIO_REFERENCE_FIELDS[2:]
                  if refs[field] not in (None, "")), None)
    if extra is not None:
        raise ValueError(f"input.params.{extra} is not supported by ACE-Step music")
    required = (("A", "audio_guide"), ("B", "audio_guide2"))
    for marker, field in required:
        if marker in mode and not refs[field]:
            raise ValueError(f"input.params.audio_prompt_type requires {field}")
        if marker not in mode and refs[field]:
            raise ValueError(f"{field} requires its audio_prompt_type selector")
    if not mode and active:
        raise ValueError("audio references require an audio_prompt_type selector")


def _validate_audio_references(working: dict[str, Any], model_type: str,
                               definition: Mapping[str, Any]) -> None:
    mode = working.get("audio_prompt_type") or ""
    refs = {field: working.get(field) for field in _AUDIO_REFERENCE_FIELDS}
    active = {field: value for field, value in refs.items() if value not in (None, "")}
    if model_type == YUE2_LOCAL:
        if mode or active:
            raise ValueError("YuE2 supports lyrics/style generation without reference audio")
        return
    if model_type == MUSIC3_LOCAL:
        _validate_music3_references(working, mode, refs, active)
        return
    _validate_ace_reference_slots(mode, refs, active, definition)


def _setting_id(setting: Mapping[str, Any], index: int) -> str:
    for key in ("id", "param", "name"):
        value = setting.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower().replace(" ", "_")
    return f"custom_setting_{index + 1}"


def _validate_custom_value(key: str, value: Any, setting: Mapping[str, Any]) -> None:
    setting_type = str(setting.get("type", "text")).lower()
    if value == "" and setting_type in {"int", "float"}:
        return
    if setting_type == "int":
        if type(value) is not int:
            raise ValueError(f"input.params.custom_settings.{key} must be an integer")
        numeric = float(value)
    elif setting_type == "float":
        numeric = _finite(value, f"custom_settings.{key}")
    elif setting_type == "text":
        if not isinstance(value, str):
            raise ValueError(f"input.params.custom_settings.{key} must be text")
        numeric = None
    else:
        raise ValueError(f"input.params.custom_settings.{key} has an unsupported model setting type")
    if numeric is not None:
        lower = setting.get("min", setting.get("minimum"))
        upper = setting.get("max", setting.get("maximum"))
        if lower is not None and numeric < float(lower):
            raise ValueError(f"input.params.custom_settings.{key} is below its declared minimum")
        if upper is not None and numeric > float(upper):
            raise ValueError(f"input.params.custom_settings.{key} exceeds its declared maximum")


def _validate_custom_settings(working: dict[str, Any], definition: Mapping[str, Any]) -> None:
    values = working.get("custom_settings")
    if values in (None, {}):
        return
    definitions = definition.get("custom_settings")
    if not isinstance(definitions, list):
        raise ValueError("input.params.custom_settings is not supported by this music model")
    known = {_setting_id(item, index): item for index, item in enumerate(definitions)
             if isinstance(item, Mapping)}
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise ValueError("input.params.custom_settings contains an unknown model setting")
    for key, value in values.items():
        _validate_custom_value(key, value, known[key])


def _validate_loras(working: dict[str, Any], definition: Mapping[str, Any], phases: int) -> None:
    names = working.get("activated_loras") or []
    if (names or working.get("loras_multipliers")) and not definition.get("enabled_audio_lora"):
        raise ValueError("selected LoRAs are not supported by this music model")
    if names or working.get("loras_multipliers"):
        validate_lora_multipliers(working, phases)


def _validate_lyrics_guard(working: Mapping[str, Any]) -> None:
    language = working.get("lyrics_language") or ""
    report = validate_lyrics_language(
        str(working.get("prompt") or ""),
        str(language),
        instrumental=bool(working.get("_music_instrumental")),
    )
    assert_enqueue_guard({
        "lyrics": working.get("prompt", ""),
        "lyrics_language": language,
        "instrumental": bool(working.get("_music_instrumental")),
        "language_guard": report,
    })


def prepare_studio_music(params, *, model_definition, model_downloaded, resources,
                         execution_policy):
    """Return detached native music parameters and inspected resources."""
    if not isinstance(params, dict):
        raise command_error(422, "invalid_studio_music_input", "Music parameters must be an object")
    working = deepcopy(params)
    try:
        workspace = working.get("workspace")
        if not isinstance(workspace, str) or not workspace.strip():
            raise ValueError("input.workspace must be an explicit output workspace")
        execution_policy(workspace)
        model_type = working.get("model_type")
        if not isinstance(model_type, str):
            raise ValueError("input.params.model_type must be a string")
        definition = _definition_for(model_definition, model_type)
        _validate_model(model_type, definition, model_downloaded)
        _fill_duration(working, model_type, definition)
        _fill_steps(working, model_type, definition)
        phases = _fill_guidance(working, model_type, definition)
        _validate_sampling(working, definition)
        _validate_model_mode(working, definition)
        _validate_audio_references(working, model_type, definition)
        _validate_custom_settings(working, definition)
        _validate_lyrics_guard(working)
        _validate_loras(working, definition, phases)
        prepared, media = resources.prepare_media(working)
        loras = resources.prepare_loras(working, definition)
        if not isinstance(prepared, dict) or not isinstance(media, list) or not isinstance(loras, list):
            raise ValueError("music resource preparation returned invalid native parameters")
        return deepcopy(prepared), [*deepcopy(media), *deepcopy(loras)]
    except HTTPException:
        raise
    except (MusicModelError, OSError, TypeError, ValueError) as error:
        raise command_error(422, "invalid_studio_music_input", str(error)) from error


__all__ = ["prepare_studio_music"]
