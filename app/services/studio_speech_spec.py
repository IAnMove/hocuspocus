"""Closed, provider-free contract for the Studio speech command.

The browser has one native parameter map for all Studio modes.  A speech
command must freeze the speech part of that map before model lookup, resource
inspection, task admission or worker effects.  This module owns that boundary;
the model handler remains the authority for provider-specific generation
validation.

The v2 envelope is::

    {
        "version": 2,
        "operation": "generation.speech",
        "intent_id": "...",
        "input": {
            "workspace": "...",
            "params": {"prompt": "...", "model_type": "...", ...}
        }
    }

``original`` is an immutable detached copy of the submitted envelope.  The
``effective`` map contains only deterministic adapter defaults; model-derived
defaults are applied by the preparation boundary.  The fingerprint covers
the effective operation, workspace and native parameters, while excluding
the transport intent and caller metadata.

Audio references are syntax-checked here and resolved by
``StudioSpeechResources`` later.  No filesystem path, model catalog, provider
or provenance authority is consulted in this module.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from services.image_generation_spec import ImageGenerationSpecError
from services.studio_image_spec import _validate_reference


SCHEMA_VERSION = 2
FINGERPRINT_VERSION = 2
OPERATION = "generation.speech"

_MAX_ID_LENGTH = 240
_MAX_INTENT_LENGTH = 160
_MAX_PROMPT_LENGTH = 200_000
_MAX_LORA_COUNT = 64
_MAX_VOICE_COUNT = 6

# These are adapter-owned values.  They describe the native selectors that
# make an audio submission unambiguous.  Duration, model mode and model
# custom settings stay model-owned and are filled during preflight.
STUDIO_SPEECH_DEFAULTS: dict[str, Any] = {
    "generation_mode": "audio",
    "_audio_sub_mode": "speech",
    "video_length": 0,
    "image_mode": 0,
    "multi_prompts_gen_type": 2,
    "negative_prompt": "",
    "repeat_generation": 1,
    "activated_loras": [],
    "loras_multipliers": "",
    "audio_prompt_type": "",
    "prompt_enhancer": "",
    "minimax_h3_turbo_mode": False,
    "_tts_speaker_name1": "",
    "_tts_speaker_name2": "",
    "_tts_speaker_name3": "",
    "_tts_speaker_name4": "",
    "_tts_speaker_name5": "",
    "_tts_speaker_name6": "",
    "_tts_voice_count": 0,
}

# The allowlist is intentionally explicit.  Several music and sound-effect
# handlers advertise ``audio_only`` and the same ``tts`` family, so that
# metadata alone cannot safely turn this speech operation into a music/SFX
# operation.  New handlers need a deliberate registration here.
SPEECH_MODEL_TYPES = frozenset(
    {
        "auk",
        "auk_flash",
        "kugelaudio_0_open",
        "qwen3_tts_customvoice",
        "qwen3_tts_voicedesign",
        "qwen3_tts_base",
        "chatterbox",
        "index_tts2",
        "scenema_audio",
        "dramabox_audio",
    }
)

INACTIVE_SPEECH_FIELDS = (
    "image_mode",
    "video_length",
    "minimax_h3_turbo_mode",
    "image_start",
    "image_end",
    "image_refs",
    "image_guide",
    "image_mask",
    "video_guide",
    "video_mask",
    "video_source",
    "audio_source",
    "MMAudio_setting",
    "MMAudio_prompt",
    "MMAudio_neg_prompt",
    "h3_ref_videos",
    "h3_ref_audios",
    "minimax_h3_references",
    "spatial_upsampling",
    "temporal_upsampling",
    "wangp_processor_settings",
)

EXCLUDED_SPEECH_FIELDS = (
    "actor",
    "client",
    "permission",
    "provenance",
    "workspace inside input.params",
    "filesystem paths",
    "free-form provider payloads",
    "music and SFX model types",
    "video, avatar and model3d controls",
)

SUPPORTED_INPUT_FIELDS = (
    "prompt",
    "alt_prompt",
    "model_type",
    "resolution",
    "video_length",
    "num_inference_steps",
    "guidance_scale",
    "seed",
    "image_mode",
    "generation_mode",
    "negative_prompt",
    "repeat_generation",
    "activated_loras",
    "loras_multipliers",
    "audio_prompt_type",
    "audio_guide",
    "audio_guide2",
    "audio_guide3",
    "audio_guide4",
    "audio_guide5",
    "audio_guide6",
    "audio_source",
    "_audio_sub_mode",
    "_tts_original_prompt",
    "_tts_speaker_name1",
    "_tts_speaker_name2",
    "_tts_speaker_name3",
    "_tts_speaker_name4",
    "_tts_speaker_name5",
    "_tts_speaker_name6",
    "_tts_voice_count",
    "duration_seconds",
    "pause_seconds",
    "temperature",
    "top_p",
    "top_k",
    "audio_scale",
    "audio_guidance_scale",
    "alt_scale",
    "guidance_phases",
    "flow_shift",
    "sample_solver",
    "settings_version",
    "prompt_enhancer",
    "model_mode",
    "custom_settings",
    "tts_dynaudnorm",
    "tts_comp_threshold",
    "tts_comp_attack",
    "tts_comp_release",
    "tts_comp_makeup",
    "multi_prompts_gen_type",
    "minimax_h3_turbo_mode",
    "image_start",
    "image_end",
    "image_refs",
    "image_guide",
    "image_mask",
    "video_guide",
    "video_mask",
    "video_source",
    "spatial_upsampling",
    "temporal_upsampling",
    "wangp_processor_settings",
    "MMAudio_setting",
    "MMAudio_prompt",
    "MMAudio_neg_prompt",
    "h3_ref_videos",
    "h3_ref_audios",
    "minimax_h3_references",
)


class StudioSpeechSpecError(ImageGenerationSpecError):
    """Validation error for the closed Studio speech envelope."""


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=False)


_Identity = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=_MAX_ID_LENGTH),
]
_Workspace = Annotated[
    StrictStr,
    StringConstraints(
        min_length=1,
        max_length=_MAX_ID_LENGTH,
        pattern=r"^(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)$",
    ),
]
_WorkspaceCollectionId = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=200),
]
_IntentId = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=_MAX_INTENT_LENGTH),
]
_Prompt = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=_MAX_PROMPT_LENGTH),
]
_Text = Annotated[StrictStr, StringConstraints(max_length=_MAX_PROMPT_LENGTH)]
_ShortText = Annotated[StrictStr, StringConstraints(max_length=8192)]
_ModelMode = Annotated[StrictStr, StringConstraints(max_length=256)]
_AudioPromptType = Annotated[
    StrictStr,
    StringConstraints(max_length=32, pattern=r"^[A-Za-z0-9]*$"),
]
_NonNegativeInt = Annotated[StrictInt, Field(ge=0, le=100_000)]
_Count = Annotated[StrictInt, Field(ge=1, le=100)]
_VoiceCount = Annotated[StrictInt, Field(ge=0, le=_MAX_VOICE_COUNT)]
_Seed = Annotated[StrictInt, Field(ge=-(2**63), le=2**63 - 1)]
_Finite = Annotated[StrictFloat, Field(allow_inf_nan=False)]
_CustomFloat = Annotated[StrictFloat, Field(allow_inf_nan=False)]
_NonNegativeFinite = Annotated[
    StrictFloat,
    Field(ge=0, allow_inf_nan=False),
]
_Guidance = Annotated[
    StrictFloat,
    Field(ge=0, le=1000, allow_inf_nan=False),
]
_Zero = Annotated[StrictInt, Field(ge=0, le=0)]
_DialogueMode = Annotated[StrictInt, Field(ge=2, le=2)]
_TtsDynaudnorm = Annotated[StrictInt, Field(ge=0, le=1)] | StrictBool


class StudioSpeechCustomSettings(_ClosedModel):
    """Typed union of custom settings exposed by speech handlers.

    The selected model still owns which subset is valid and its metadata
    ranges.  Keeping the known IDs closed here prevents arbitrary nested JSON
    from crossing the command boundary while allowing each speech handler's
    currently published setting family.
    """

    auto_split_every_s: _CustomFloat | Literal[""] | None = None
    exaggeration: _CustomFloat | None = None
    pace: _CustomFloat | None = None
    vc_steps: StrictInt | None = None
    vc_cfg_rate: _CustomFloat | None = None
    duration_multiplier: _CustomFloat | None = None


def _check_required_speech_texts(params: Any) -> None:
    for field in ("prompt", "model_type", "resolution"):
        if not getattr(params, field).strip():
            raise ValueError(f"{field} must contain a non-blank value")


def _check_speech_prompt_metadata(params: Any) -> None:
    if params.tts_original_prompt is None and "tts_original_prompt" in params.model_fields_set:
        raise ValueError("_tts_original_prompt must be a string when supplied")


def _check_speech_ranges(params: Any) -> None:
    if params.pause_seconds is not None and params.pause_seconds > 2:
        raise ValueError("pause_seconds must be between 0 and 2 seconds")
    if params.temperature is not None and params.temperature > 2:
        raise ValueError("temperature must be at most 2")
    if params.tts_comp_threshold is not None and not -50 <= params.tts_comp_threshold <= -10:
        raise ValueError("tts_comp_threshold must be between -50 and -10")
    if params.tts_comp_release is not None and params.tts_comp_release > 500:
        raise ValueError("tts_comp_release must be at most 500")
    if params.tts_comp_makeup is not None and params.tts_comp_makeup > 12:
        raise ValueError("tts_comp_makeup must be at most 12")


class StudioSpeechParams(_ClosedModel):
    """Typed native speech parameters emitted by Studio."""

    prompt: _Prompt
    alt_prompt: _Text = ""
    model_type: _Identity
    resolution: Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]

    # Speech jobs retain the common native selectors as explicit inactive
    # sentinels.  They are exact zero values, not a mode inferred from a
    # missing image field.
    video_length: _Zero = 0
    num_inference_steps: _NonNegativeInt = 0
    guidance_scale: _Guidance = 1.0
    seed: _Seed = -1
    image_mode: _Zero = 0
    generation_mode: Literal["audio"] = "audio"
    negative_prompt: _Text = ""
    repeat_generation: _Count = 1
    activated_loras: list[Annotated[StrictStr, StringConstraints(min_length=1, max_length=8192)]] = Field(
        default_factory=list, max_length=_MAX_LORA_COUNT
    )
    loras_multipliers: _ShortText = ""
    multi_prompts_gen_type: _DialogueMode = 2

    # Native speech selectors and canonical reference URLs/asset IDs.  Empty
    # string and null are retained as inactive sentinels; paths are rejected
    # by the validator below and resolved only by StudioSpeechResources.
    audio_prompt_type: _AudioPromptType = ""
    audio_guide: StrictStr | None = None
    audio_guide2: StrictStr | None = None
    audio_guide3: StrictStr | None = None
    audio_guide4: StrictStr | None = None
    audio_guide5: StrictStr | None = None
    audio_guide6: StrictStr | None = None
    audio_source: Literal["", None] = None

    # Studio keeps stale image/video controls in its shared state when the
    # user switches to speech.  They are accepted only as explicit inactive
    # sentinels so a restored speech snapshot is not silently truncated.
    image_start: Literal["", None] | list[StrictStr] = None
    image_end: Literal["", None] | list[StrictStr] = None
    image_refs: list[StrictStr] | None = None
    image_guide: Literal["", None] | list[StrictStr] = None
    image_mask: Literal["", None] | list[StrictStr] = None
    video_guide: Literal["", None] = None
    video_mask: Literal["", None] = None
    video_source: Literal["", None] = None
    spatial_upsampling: Literal["", None] = ""
    temporal_upsampling: Literal["", None] = ""
    wangp_processor_settings: dict[str, Any] | None = None
    MMAudio_setting: _Zero | None = None
    MMAudio_prompt: Literal["", None] = None
    MMAudio_neg_prompt: Literal["", None] = None
    h3_ref_videos: list[StrictStr] | None = None
    h3_ref_audios: list[StrictStr] | None = None
    minimax_h3_references: list[StrictStr] | None = None

    # Private UI fields are aliases because Pydantic field names cannot begin
    # with an underscore.  JSON serialization uses the native aliases.
    audio_sub_mode: Literal["speech"] = Field("speech", alias="_audio_sub_mode")
    tts_original_prompt: _Text | None = Field(None, alias="_tts_original_prompt")
    tts_speaker_name1: _Text | None = Field("", alias="_tts_speaker_name1")
    tts_speaker_name2: _Text | None = Field("", alias="_tts_speaker_name2")
    tts_speaker_name3: _Text | None = Field("", alias="_tts_speaker_name3")
    tts_speaker_name4: _Text | None = Field("", alias="_tts_speaker_name4")
    tts_speaker_name5: _Text | None = Field("", alias="_tts_speaker_name5")
    tts_speaker_name6: _Text | None = Field("", alias="_tts_speaker_name6")
    tts_voice_count: _VoiceCount = Field(0, alias="_tts_voice_count")

    # Model-owned timing and sampling controls.  Duration zero is a real
    # native sentinel for DramaBox and therefore remains valid here.
    duration_seconds: _NonNegativeFinite | None = None
    pause_seconds: _NonNegativeFinite | None = None
    temperature: _NonNegativeFinite | None = None
    top_p: Annotated[StrictFloat, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    top_k: _NonNegativeInt | None = None
    audio_scale: _Finite | None = None
    audio_guidance_scale: _Finite | None = None
    alt_scale: _Finite | None = None
    guidance_phases: Annotated[StrictInt, Field(ge=0, le=16)] = 1
    flow_shift: _Finite | None = None
    sample_solver: _ShortText = ""
    settings_version: _NonNegativeFinite | None = None
    # Speech text must reach TTS literally.  Prompt enhancement is a visual
    # generation feature and an active value would rewrite the speaker text.
    prompt_enhancer: Literal["", None] = ""
    model_mode: _ModelMode | None = None
    custom_settings: StudioSpeechCustomSettings | None = None

    # Studio's audio UI currently serializes this checkbox as integer 0/1;
    # older snapshots may contain a JSON boolean.  Both are typed and bounded.
    tts_dynaudnorm: _TtsDynaudnorm | None = None
    tts_comp_threshold: _Finite | None = None
    tts_comp_attack: _NonNegativeFinite | None = None
    tts_comp_release: _NonNegativeFinite | None = None
    tts_comp_makeup: _NonNegativeFinite | None = None

    # H3's inert sentinel appears in the shared Studio state.  A true value is
    # a different video/audio operation and must fail closed here.
    minimax_h3_turbo_mode: StrictBool | None = None

    @field_validator(
        "audio_guide",
        "audio_guide2",
        "audio_guide3",
        "audio_guide4",
        "audio_guide5",
        "audio_guide6",
    )
    @classmethod
    def _check_audio_reference(cls, value):
        if value in (None, ""):
            return value
        return _validate_reference(value)

    @field_validator("activated_loras")
    @classmethod
    def _check_lora_names(cls, values):
        for value in values:
            if not value.strip() or "/" in value or "\\" in value or value in {".", ".."}:
                raise ValueError("activated_loras must contain exact catalog names")
        return values

    @field_validator(
        "image_start",
        "image_end",
        "image_guide",
        "image_mask",
    )
    @classmethod
    def _check_inactive_image_slots(cls, value):
        if value is None or value == "":
            return value
        if isinstance(value, list) and all(item == "" for item in value):
            return value
        raise ValueError("image references are inactive in speech mode")

    @field_validator("image_refs", "h3_ref_videos", "h3_ref_audios", "minimax_h3_references")
    @classmethod
    def _check_inactive_reference_lists(cls, value):
        if value is None or value == [] or (isinstance(value, list) and all(item == "" for item in value)):
            return value
        raise ValueError("reference lists are inactive in speech mode")

    @field_validator("wangp_processor_settings")
    @classmethod
    def _check_inactive_processor_settings(cls, value):
        if value is None or value == {}:
            return value
        raise ValueError("processor settings are inactive in speech mode")

    @field_validator("tts_original_prompt")
    @classmethod
    def _check_original_prompt(cls, value):
        if value is None:
            # Omission is handled by freeze_studio_speech_spec.  Explicit
            # JSON null is not a valid native TTS text field.
            return value
        return value

    @field_validator("minimax_h3_turbo_mode")
    @classmethod
    def _check_inactive_turbo(cls, value):
        if value is True:
            raise ValueError("minimax_h3_turbo_mode must be false or null for speech")
        return value

    @model_validator(mode="after")
    def _check_semantics(self):
        _check_required_speech_texts(self)
        _check_speech_prompt_metadata(self)
        _check_speech_ranges(self)
        return self


class StudioSpeechInput(_ClosedModel):
    workspace: _Workspace
    workspace_collection_id: _WorkspaceCollectionId | None = None
    params: StudioSpeechParams

    @model_validator(mode="after")
    def _check_collection_id(self):
        if self.workspace_collection_id is not None and not self.workspace_collection_id.strip():
            raise ValueError("workspace_collection_id must contain a non-blank value")
        return self


class _StudioSpeechEnvelope(_ClosedModel):
    version: Literal[SCHEMA_VERSION]
    operation: Literal[OPERATION]
    intent_id: _IntentId
    input: StudioSpeechInput

    @model_validator(mode="after")
    def _check_intent(self):
        if not self.intent_id.strip():
            raise ValueError("intent_id must contain a non-blank value")
        return self


def _validation_error(exc: ValidationError) -> StudioSpeechSpecError:
    details: list[dict[str, Any]] = []
    messages: list[str] = []
    for error in exc.errors(include_input=False):
        location = ".".join(str(part) for part in error.get("loc", ())) or "command"
        message = str(error.get("msg") or "Invalid value")
        details.append({"loc": location, "message": message, "type": error.get("type")})
        messages.append(f"{location}: {message}")
    return StudioSpeechSpecError(
        "; ".join(messages) or "Invalid Studio speech generation command",
        details=details,
    )


def _canonical_content(effective: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "operation": OPERATION,
        "input": deepcopy(effective["input"]),
    }


def _fingerprint(content: dict[str, Any]) -> str:
    encoded = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def freeze_studio_speech_spec(command: Any) -> dict[str, Any]:
    """Validate and detach one Studio speech command without side effects."""
    if type(command) is not dict:
        raise StudioSpeechSpecError("Studio speech generation command must be an object")
    try:
        envelope = _StudioSpeechEnvelope.model_validate(command)
    except ValidationError as exc:
        raise _validation_error(exc) from exc

    original = deepcopy(command)
    explicit_params = envelope.input.params.model_dump(
        mode="json", by_alias=True, exclude_unset=True
    )
    effective_params = deepcopy(explicit_params)
    for key, value in STUDIO_SPEECH_DEFAULTS.items():
        effective_params.setdefault(key, deepcopy(value))
    # The original prompt is a native bookkeeping field.  When Studio omits
    # it, the effective projection gets the literal prompt; an explicit value
    # is preserved byte-for-byte in ``original`` and by its own field.
    effective_params.setdefault("_tts_original_prompt", explicit_params["prompt"])

    effective = {
        "version": SCHEMA_VERSION,
        "operation": OPERATION,
        "intent_id": envelope.intent_id,
        "input": {
            "workspace": envelope.input.workspace,
            "params": effective_params,
        },
    }
    explicit_input = envelope.input.model_dump(mode="json", exclude_unset=True)
    if "workspace_collection_id" in explicit_input:
        effective["input"]["workspace_collection_id"] = explicit_input["workspace_collection_id"]
    content = _canonical_content(effective)
    return {
        "original": original,
        "effective": effective,
        "fingerprint_version": FINGERPRINT_VERSION,
        "fingerprint": _fingerprint(content),
    }


def studio_speech_schema() -> dict[str, Any]:
    """Return the discovery schema for the implemented speech boundary."""
    input_schema = StudioSpeechInput.model_json_schema()
    envelope_schema = _StudioSpeechEnvelope.model_json_schema()
    return {
        "version": SCHEMA_VERSION,
        "operation": OPERATION,
        "intent_id": envelope_schema["properties"]["intent_id"],
        "input": input_schema,
        "supported_input_fields": list(SUPPORTED_INPUT_FIELDS),
        "speech_model_types": sorted(SPEECH_MODEL_TYPES),
        "effects": deepcopy(STUDIO_SPEECH_DEFAULTS),
        "inactive": list(INACTIVE_SPEECH_FIELDS),
        "excluded": list(EXCLUDED_SPEECH_FIELDS),
    }


# Compatibility aliases used by discovery/adapters in the shared command
# slices.  They point to this one contract and do not create another schema.
StudioSpeechGenerationInput = StudioSpeechInput
StudioSpeechGenerationParams = StudioSpeechParams
speech_generation_schema_v2 = studio_speech_schema


__all__ = [
    "EXCLUDED_SPEECH_FIELDS",
    "FINGERPRINT_VERSION",
    "INACTIVE_SPEECH_FIELDS",
    "OPERATION",
    "SCHEMA_VERSION",
    "SPEECH_MODEL_TYPES",
    "STUDIO_SPEECH_DEFAULTS",
    "SUPPORTED_INPUT_FIELDS",
    "StudioSpeechGenerationInput",
    "StudioSpeechGenerationParams",
    "StudioSpeechCustomSettings",
    "StudioSpeechInput",
    "StudioSpeechParams",
    "StudioSpeechSpecError",
    "freeze_studio_speech_spec",
    "speech_generation_schema_v2",
    "studio_speech_schema",
]
