"""Provider-free preparation for the closed Studio speech command.

The preparation boundary validates only facts declared by the selected native
handler, checks that speech references and settings are coherent, and asks the
existing ``StudioSpeechResources`` object to inspect canonical media/LoRAs.
It returns detached native parameters and resource identities; it does not
load a model, schedule a worker or create a second queue.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any, Mapping

from fastapi import HTTPException

from services.image_generation_commands import command_error
from services.studio_image_resources import validate_lora_multipliers
from services.studio_speech_spec import SPEECH_MODEL_TYPES
from services.auk_speech_contract import prepare_auk_speech


_AUDIO_REFERENCE_FIELDS = tuple(
    ["audio_guide"] + [f"audio_guide{index}" for index in range(2, 7)]
)
_AUDIO_MODE_FLAGS = frozenset({"N", "V"})


def _definition_for(model_definition, model_type: str) -> dict[str, Any]:
    if callable(model_definition):
        definition = model_definition(model_type)
    elif isinstance(model_definition, Mapping):
        definition = model_definition.get(model_type)
    else:
        definition = None
    if not isinstance(definition, dict):
        raise ValueError("Choose an installed speech model from the model catalog")
    return deepcopy(definition)


def _finite_number(value, field: str, *, minimum: float | None = None,
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


def _choice_values(choices) -> list[str]:
    if not isinstance(choices, (list, tuple)):
        return []
    values: list[str] = []
    for item in choices:
        if isinstance(item, Mapping):
            value = item.get("value")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            value = item[1]
        else:
            value = item
        if isinstance(value, str):
            values.append(value)
    return values


def _model_mode(working: dict[str, Any], definition: dict[str, Any]) -> None:
    mode = working.get("model_mode")
    if mode is not None and not isinstance(mode, str):
        raise ValueError("input.params.model_mode must be a string or null")
    modes = definition.get("model_modes")
    if not isinstance(modes, Mapping):
        if mode not in (None, ""):
            raise ValueError("input.params.model_mode is not supported by this speech model")
        return

    choices = _choice_values(modes.get("choices"))
    default = modes.get("default")
    if mode in (None, ""):
        if isinstance(default, str) and default != "":
            if choices and default not in choices:
                raise ValueError("the speech model advertises an invalid model_mode default")
            working["model_mode"] = default
        return
    if choices and mode not in choices:
        raise ValueError("input.params.model_mode is not one of the model's declared choices")


def _duration(working: dict[str, Any], definition: dict[str, Any]) -> None:
    value = working.get("duration_seconds")
    slider = definition.get("duration_slider")
    if not isinstance(slider, Mapping):
        if value is not None:
            _finite_number(value, "duration_seconds", minimum=0)
        return
    if value is None:
        # ``default=0`` is meaningful for DramaBox (auto duration), so test
        # key presence rather than using truthiness.
        for key in ("default", "max"):
            if key in slider and slider[key] is not None:
                value = slider[key]
                break
        if value is None:
            value = 600
        working["duration_seconds"] = value
    minimum = slider.get("min")
    maximum = slider.get("max")
    _finite_number(value, "duration_seconds", minimum=float(minimum) if minimum is not None else 0,
                   maximum=float(maximum) if maximum is not None else None)


def _validate_inference_steps(steps: Any, definition: dict[str, Any]) -> None:
    if type(steps) is not int or steps < 0:
        raise ValueError("input.params.num_inference_steps must be a non-negative integer")
    # Most speech handlers expose no step control and use the zero sentinel.
    # Scenema is the declared exception: its locked native profile forces its
    # own fixed step count (currently eight) even though the control is not
    # user-editable.  Preserve that model-owned value for the native facade.
    if definition.get("inference_steps") is False and steps != 0 and not definition.get("lock_inference_steps"):
        raise ValueError("input.params.num_inference_steps must be zero for this speech model")
    if definition.get("inference_steps") is not False:
        lower = definition.get("inference_steps_min")
        upper = definition.get("inference_steps_max")
        if lower is not None and steps < int(lower):
            raise ValueError("input.params.num_inference_steps is below the model's declared minimum")
        if upper is not None and steps > int(upper):
            raise ValueError("input.params.num_inference_steps exceeds the model's declared maximum")


def _sampling_phases(working: dict[str, Any], definition: dict[str, Any]):
    if "guidance_phases" not in working:
        declared_phases = definition.get("guidance_max_phases")
        working["guidance_phases"] = int(declared_phases) if declared_phases is not None else 1
    phases = working.get("guidance_phases", 1)
    if type(phases) is not int or not 0 <= phases <= 16:
        raise ValueError("input.params.guidance_phases must be an integer from 0 to 16")
    maximum = definition.get("guidance_max_phases")
    if maximum is not None and phases > int(maximum):
        raise ValueError("input.params.guidance_phases exceeds the model's declared maximum")
    return maximum


def _validate_sampling_scalars(working: dict[str, Any], definition: dict[str, Any]) -> None:
    solver = working.get("sample_solver", "")
    choices = _choice_values(definition.get("sample_solvers"))
    if solver and choices and solver not in choices:
        raise ValueError("input.params.sample_solver is not one of the model's declared choices")

    if working.get("negative_prompt") and definition.get("no_negative_prompt"):
        raise ValueError("input.params.negative_prompt is not supported by this speech model")
    temperature = working.get("temperature")
    if temperature is not None:
        _finite_number(temperature, "temperature", minimum=0)
        if definition.get("temperature") is False:
            raise ValueError("input.params.temperature is locked for this speech model")
    pause = working.get("pause_seconds")
    if pause is not None:
        _finite_number(pause, "pause_seconds", minimum=0, maximum=2)
        if not definition.get("pause_between_sentences"):
            raise ValueError("input.params.pause_seconds is not supported by this speech model")


def _validate_top_sampling_field(
    field: str, value: Any, capability: str, definition: dict[str, Any]
) -> None:
    if value is None:
        return
    if not definition.get(capability):
        raise ValueError(f"input.params.{field} is not supported by this speech model")
    if field == "top_p":
        _finite_number(value, field, minimum=0, maximum=1)
    elif type(value) is not int or value < 0:
        raise ValueError("input.params.top_k must be a non-negative integer")


def _validate_sampling_options(working: dict[str, Any], definition: dict[str, Any]) -> None:
    _validate_sampling_scalars(working, definition)
    for field, capability in (("top_p", "top_p_slider"), ("top_k", "top_k_slider")):
        _validate_top_sampling_field(field, working.get(field), capability, definition)


def _sampling(working: dict[str, Any], definition: dict[str, Any]) -> int:
    steps = working.get("num_inference_steps", 0)
    working.setdefault("num_inference_steps", 0)
    _validate_inference_steps(steps, definition)
    maximum = _sampling_phases(working, definition)
    _validate_sampling_options(working, definition)
    return max(1, int(maximum if maximum is not None else 1))


def _strip_audio_modifier_flags(
    mode: str, source: Mapping[str, Any] | None,
    definition: Mapping[str, Any] | None,
) -> str:
    custom_flags = source.get("custom_flags") if source else None
    if isinstance(custom_flags, Mapping):
        for flag in custom_flags:
            if isinstance(flag, str) and flag:
                mode = mode.replace(flag.upper(), "")
    custom = definition.get("audio_prompt_type_custom_option") if definition else None
    custom_flag = custom.get("flag") if isinstance(custom, Mapping) else None
    if isinstance(custom_flag, str) and custom_flag:
        mode = mode.replace(custom_flag.upper(), "")
    return mode


def _base_audio_mode(value: str, source: Mapping[str, Any] | None,
                     definition: Mapping[str, Any] | None = None) -> str:
    mode = value.upper()
    mode_without_modifiers = "".join(char for char in mode if char not in _AUDIO_MODE_FLAGS)
    # A mode already present in the native selection is a complete value
    # (Scenema's A2/AB2 include the SeedVC ``2`` flag).  Strip custom flags
    # only when they are being used as standalone modifiers.
    selections = _choice_values(source.get("selection")) if source else []
    if mode_without_modifiers in selections:
        return mode_without_modifiers
    mode = _strip_audio_modifier_flags(mode_without_modifiers, source, definition)
    return "".join(char for char in mode if char not in _AUDIO_MODE_FLAGS)


def _voice_mode_for_count(count: int, selection: list[str]) -> str:
    if not selection:
        return ""
    if count <= 0:
        return selection[0]
    if count == 1:
        return selection[min(1, len(selection) - 1)]
    return selection[min(2, len(selection) - 1)]


def _audio_mode_source(
    definition: dict[str, Any],
) -> tuple[Mapping[str, Any] | None, list[str]]:
    source = definition.get("audio_prompt_type_sources")
    source = source if isinstance(source, Mapping) else None
    selection = _choice_values(source.get("selection")) if source else []
    # Some model definitions use a plain string list for selection and the
    # helper above deliberately handles only native list/tuple values.
    if source and not selection and isinstance(source.get("selection"), list):
        selection = [item for item in source["selection"] if isinstance(item, str)]
    if source and not selection:
        raise ValueError("the speech model advertises no audio prompt choices")
    return source, selection


def _audio_mode_default(
    working: dict[str, Any], raw_mode: str, source: Mapping[str, Any] | None
) -> str:
    mode = raw_mode
    if not mode and source and isinstance(source.get("default"), str):
        mode = source["default"]
        if mode:
            working["audio_prompt_type"] = mode
    return mode


def _speech_audio_mode(
    working: dict[str, Any], definition: dict[str, Any]
) -> tuple[str, str, Mapping[str, Any] | None, list[str]]:
    raw_mode = working.get("audio_prompt_type") or ""
    if not isinstance(raw_mode, str):
        raise ValueError("input.params.audio_prompt_type must be a string")
    source, selection = _audio_mode_source(definition)
    mode = _audio_mode_default(working, raw_mode, source)
    base = _base_audio_mode(mode, source, definition)
    return mode, base, source, selection


def _validate_declared_audio_mode(
    mode: str,
    base: str,
    source: Mapping[str, Any] | None,
    definition: dict[str, Any],
    selection: list[str],
) -> None:
    if source:
        custom = definition.get("audio_prompt_type_custom_option")
        custom_flag = custom.get("flag") if isinstance(custom, Mapping) else None
        source_custom_flags = source.get("custom_flags")
        has_source_custom = (
            isinstance(source_custom_flags, Mapping)
            and any(isinstance(flag, str) and flag and flag.upper() in mode.upper()
                    for flag in source_custom_flags)
        )
        if base not in selection:
            # A custom-only flag (DramaBox's ``0``) has an empty base and is
            # valid alongside the selected empty mode.
            if not (
                not base
                and (
                    (isinstance(custom_flag, str) and custom_flag.upper() in mode.upper())
                    or has_source_custom
                )
            ):
                raise ValueError("input.params.audio_prompt_type is not a declared model choice")
    elif mode and mode not in {"A", "AN", "AV"}:
        # Chatterbox exposes any_audio_prompt but no choice map; its native
        # handler accepts its historical A selector and no other mode.
        raise ValueError("input.params.audio_prompt_type is not supported by this speech model")


def _validate_voice_count(
    working: dict[str, Any], definition: dict[str, Any], mode: str,
    source: Mapping[str, Any] | None, selection: list[str],
) -> int:
    count = working.get("_tts_voice_count", 0)
    if type(count) is not int or not 0 <= count <= 6:
        raise ValueError("input.params._tts_voice_count must be an integer from 0 to 6")
    maximum_count = definition.get("max_voice_count")
    if maximum_count is not None and count > int(maximum_count):
        raise ValueError("input.params._tts_voice_count exceeds the model's voice limit")

    if definition.get("audio_mode_from_voice_count"):
        expected = _voice_mode_for_count(count, selection)
        if _base_audio_mode(mode, source, definition) != expected:
            raise ValueError("input.params.audio_prompt_type must match the selected voice count")
    return count


def _audio_reference_state(
    working: dict[str, Any], definition: dict[str, Any], count: int
) -> tuple[dict[str, Any], int]:
    refs = {field: working.get(field) for field in _AUDIO_REFERENCE_FIELDS}
    highest_ref = 0
    for index, field in enumerate(_AUDIO_REFERENCE_FIELDS, start=1):
        value = refs[field]
        if value not in (None, ""):
            highest_ref = index
            if definition.get("audio_mode_from_voice_count") and count < index:
                raise ValueError(f"input.params.{field} requires that voice slot to be selected")
    if highest_ref and definition.get("audio_mode_from_voice_count") and count < highest_ref:
        raise ValueError("audio references exceed the selected voice count")
    return refs, highest_ref


def _validate_primary_audio_references(refs: dict[str, Any], base: str) -> None:
    needs_first = "A" in base or base == "2"
    needs_second = "B" in base or base == "2"
    if needs_first and not refs["audio_guide"]:
        raise ValueError("input.params.audio_prompt_type requires audio_guide")
    if needs_second and not refs["audio_guide2"]:
        raise ValueError("input.params.audio_prompt_type requires audio_guide2")
    if refs["audio_guide"] and not needs_first:
        raise ValueError("audio_guide is selected but audio_prompt_type has no first reference")
    if refs["audio_guide2"] and not needs_second:
        raise ValueError("audio_guide2 is selected but audio_prompt_type has no second reference")


def _validate_additional_audio_references(refs: dict[str, Any], base: str) -> None:
    for index in range(3, 7):
        if refs[f"audio_guide{index}"] and "B" not in base:
            raise ValueError(f"audio_guide{index} requires a multi-voice audio_prompt_type")


def _validate_audio_reference_modes(
    refs: dict[str, Any], base: str, source: Mapping[str, Any] | None
) -> None:
    # Explicit model choices are the evidence that A/B references are active.
    # Models without a choice map (Chatterbox) leave reference requirements to
    # their native handler instead of this adapter inventing one.
    if source:
        _validate_primary_audio_references(refs, base)
        _validate_additional_audio_references(refs, base)


def _validate_audio_prompts(working: dict[str, Any], definition: dict[str, Any]) -> None:
    mode, base, source, selection = _speech_audio_mode(working, definition)
    _validate_declared_audio_mode(mode, base, source, definition, selection)
    count = _validate_voice_count(working, definition, mode, source, selection)
    refs, _ = _audio_reference_state(working, definition, count)
    _validate_audio_reference_modes(refs, base, source)


def _setting_id(setting: Mapping[str, Any], index: int) -> str:
    explicit = setting.get("id")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    name = setting.get("name")
    if isinstance(name, str) and name.strip():
        normalized = re.sub(r"[^a-z0-9_]+", "_", name.strip().lower()).strip("_")
        if normalized:
            return normalized
    return f"custom_setting_{index + 1}"


def _custom_setting_definitions(definition: dict[str, Any]):
    definitions = definition.get("custom_settings")
    if not isinstance(definitions, list):
        definitions = definition.get("custom_settings_def")
    return definitions if isinstance(definitions, list) else None


def _validate_custom_setting_range(key: str, numeric: float | None, setting: Mapping[str, Any]) -> None:
    if numeric is None:
        return
    lower = setting.get("min", setting.get("minimum"))
    upper = setting.get("max", setting.get("maximum"))
    if lower is not None and numeric < float(lower):
        raise ValueError(f"input.params.custom_settings.{key} is below its declared minimum")
    if upper is not None and numeric > float(upper):
        raise ValueError(f"input.params.custom_settings.{key} exceeds its declared maximum")


def _validate_custom_setting(key: str, value: Any, setting: Mapping[str, Any]) -> None:
    setting_type = str(setting.get("type", "text")).lower()
    if value == "" and setting_type in {"int", "float"}:
        # The Studio numeric control uses an empty string while a
        # selectable setting is inactive; native handlers remove it.
        return
    if setting_type == "int":
        if type(value) is not int:
            raise ValueError(f"input.params.custom_settings.{key} must be an integer")
        numeric = float(value)
    elif setting_type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"input.params.custom_settings.{key} must be a number")
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"input.params.custom_settings.{key} must be finite")
    elif setting_type == "bool":
        if type(value) is not bool:
            raise ValueError(f"input.params.custom_settings.{key} must be boolean")
        numeric = None
    else:
        if not isinstance(value, str):
            raise ValueError(f"input.params.custom_settings.{key} must be text")
        numeric = None
    _validate_custom_setting_range(key, numeric, setting)


def _validate_custom_settings(working: dict[str, Any], definition: dict[str, Any]) -> None:
    values = working.get("custom_settings")
    if values is None:
        return
    if not isinstance(values, dict):
        raise ValueError("input.params.custom_settings must be an object")
    definitions = _custom_setting_definitions(definition)
    if not isinstance(definitions, list):
        if values:
            raise ValueError("input.params.custom_settings is not supported by this speech model")
        return
    known = {_setting_id(item, index): item for index, item in enumerate(definitions) if isinstance(item, Mapping)}
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise ValueError("input.params.custom_settings contains an unknown model setting")
    for key, value in values.items():
        _validate_custom_setting(key, value, known[key])


def _validate_loras(working: dict[str, Any], definition: dict[str, Any], phases: int) -> None:
    names = working.get("activated_loras") or []
    if names and not definition.get("enabled_audio_lora"):
        raise ValueError("selected LoRAs are not supported by this speech model")
    if names or working.get("loras_multipliers"):
        validate_lora_multipliers(working, phases)


def _validate_speech_model(model_type: str, definition: dict[str, Any], model_downloaded) -> None:
    if model_type not in SPEECH_MODEL_TYPES:
        raise ValueError("Choose a registered speech model; music and SFX models use another operation")
    if definition.get("audio_only") is not True or definition.get("image_outputs"):
        raise ValueError("The selected model is not an audio-only speech model")
    if not model_downloaded(model_type):
        raise command_error(409, "model_unavailable", "Required speech model files are not installed; install them before submitting")


def prepare_studio_speech(params, *, model_definition, model_downloaded, resources,
                          execution_policy):
    """Return detached native speech parameters and inspected resources.

    ``params`` is normally the effective output of
    :func:`freeze_studio_speech_spec`; accepting a mapping directly keeps this
    boundary easy to test and lets the native facade supply its own snapshot.
    """
    if not isinstance(params, dict):
        raise command_error(422, "invalid_studio_speech_input", "Speech parameters must be an object")
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
        _validate_speech_model(model_type, definition, model_downloaded)
        prepare_auk_speech(working, definition)
        phases = _sampling(working, definition)
        _model_mode(working, definition)
        _duration(working, definition)
        _validate_audio_prompts(working, definition)
        _validate_custom_settings(working, definition)
        _validate_loras(working, definition, phases)
        prepared, media = resources.prepare_media(working)
        loras = resources.prepare_loras(working, definition)
        if not isinstance(prepared, dict):
            raise ValueError("speech resource preparation returned invalid native parameters")
        return deepcopy(prepared), [*deepcopy(media), *deepcopy(loras)]
    except HTTPException:
        raise
    except (OSError, ValueError) as error:
        raise command_error(422, "invalid_studio_speech_input", str(error)) from error


__all__ = ["prepare_studio_speech"]
