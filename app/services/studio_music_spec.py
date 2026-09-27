"""Closed, provider-free contract for the Studio music command.

Studio uses one native parameter map for image, speech and music.  This
module freezes the music subset before model lookup, media inspection or task
admission.  It keeps the literal lyrics and caption separate from the
effective native selectors and never calls the older ``freeze_music_spec``;
that helper intentionally normalizes Story requests and is not the Studio
snapshot authority.

The versioned envelope is::

    {
        "version": 2,
        "operation": "generation.music",
        "intent_id": "...",
        "input": {
            "workspace": "...",
            "workspace_collection_id": "...",
            "params": {"model_type": "...", "prompt": "...", ...}
        }
    }

Only the two local model IDs with a native music handler are registered in
this first vertical.  Availability, model-specific defaults and resource
identity are checked by :mod:`studio_music_preparation`.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
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
from services.music_model_contract import ACE_DEFAULT, GUIDE_REVISION, MUSIC3_LOCAL, YUE2_LOCAL
from services.studio_image_spec import _validate_reference


SCHEMA_VERSION = 2
FINGERPRINT_VERSION = 2
OPERATION = "generation.music"
STUDIO_MUSIC_SCHEMA_VERSION = SCHEMA_VERSION
STUDIO_MUSIC_OPERATION = OPERATION

_MAX_ID_LENGTH = 240
_MAX_INTENT_LENGTH = 160
_MAX_PROMPT_LENGTH = 200_000
_MAX_SHORT_TEXT_LENGTH = 8_192
_MAX_LORA_COUNT = 64

# This is deliberately an exact registration.  ``music_model_contract`` also
# knows remote/community IDs and ACE aliases for Story compatibility; this
# local command must never route one of those IDs to the generic music worker.
STUDIO_MUSIC_MODEL_TYPES = frozenset({ACE_DEFAULT, MUSIC3_LOCAL, YUE2_LOCAL})
MUSIC_MODEL_TYPES = STUDIO_MUSIC_MODEL_TYPES

# These defaults are adapter-owned and contain no model-derived values.  The
# preparation boundary fills duration, step count, guidance and custom model
# settings from the selected native definition.
STUDIO_MUSIC_DEFAULTS: dict[str, Any] = {
    "generation_mode": "audio",
    "_audio_sub_mode": "music",
    "video_length": 0,
    "image_mode": 0,
    "multi_prompts_gen_type": 2,
    "negative_prompt": "",
    "repeat_generation": 1,
    "batch_size": 1,
    "activated_loras": [],
    "loras_multipliers": "",
    "audio_prompt_type": "",
    "prompt_enhancer": "",
    "_music_description": "",
    "_music_instrumental": False,
    "_tts_speaker_name1": "",
    "_tts_speaker_name2": "",
    "_tts_speaker_name3": "",
    "_tts_speaker_name4": "",
    "_tts_speaker_name5": "",
    "_tts_speaker_name6": "",
    "_tts_voice_count": 0,
}

SUPPORTED_INPUT_FIELDS = (
    "prompt",
    "alt_prompt",
    "model_type",
    "resolution",
    "lyrics_language",
    "video_length",
    "num_inference_steps",
    "guidance_scale",
    "seed",
    "image_mode",
    "generation_mode",
    "negative_prompt",
    "repeat_generation",
    "batch_size",
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
    "duration_seconds",
    "temperature",
    "top_p",
    "top_k",
    "audio_scale",
    "alt_guidance_scale",
    "guidance_phases",
    "sample_solver",
    "settings_version",
    "prompt_enhancer",
    "model_mode",
    "custom_settings",
    "multi_prompts_gen_type",
    "_audio_sub_mode",
    "_music_description",
    "_music_instrumental",
    "_tts_original_prompt",
    "_tts_speaker_name1",
    "_tts_speaker_name2",
    "_tts_speaker_name3",
    "_tts_speaker_name4",
    "_tts_speaker_name5",
    "_tts_speaker_name6",
    "_tts_voice_count",
)

# Shared Studio fields that are harmless only as sentinels are documented so
# a caller can project a form deliberately.  They are not accepted as free
# command fields: the closed model below only accepts the explicitly typed
# music fields.
INACTIVE_MUSIC_FIELDS = (
    "image_mode=0",
    "video_length=0",
    "generation_mode=audio",
    "_audio_sub_mode=music",
    "multi_prompts_gen_type=2",
    "repeat_generation=1",
    "batch_size=1",
    "negative_prompt=empty",
    "prompt_enhancer=empty_or_null",
    "_tts_speaker_name1..6=empty_or_null",
    "_tts_voice_count=0",
    "audio_guide3..6=empty_or_null",
    "audio_source=empty_or_null",
)

EXCLUDED_MUSIC_FIELDS = (
    "actor",
    "client",
    "permission",
    "provenance",
    "workspace inside input.params",
    "filesystem paths",
    "free-form provider payloads",
    "remote MiniMax and community model IDs",
    "speech voice names, voice counts and voice-clone controls",
    "SFX/MMAudio, video, image, avatar and model3d controls",
    "LLM song-writing or prompt enhancement",
)


class StudioMusicSpecError(ImageGenerationSpecError):
    """Validation error for the closed Studio music envelope."""


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
_ShortText = Annotated[StrictStr, StringConstraints(max_length=_MAX_SHORT_TEXT_LENGTH)]
_Name = Annotated[StrictStr, StringConstraints(min_length=1, max_length=_MAX_SHORT_TEXT_LENGTH)]
_Steps = Annotated[StrictInt, Field(ge=0, le=1000)]
_Seed = Annotated[StrictInt, Field(ge=-(2**63), le=2**63 - 1)]
_One = Annotated[StrictInt, Field(ge=1, le=1)]
_Two = Annotated[StrictInt, Field(ge=2, le=2)]
_Zero = Annotated[StrictInt, Field(ge=0, le=0)]
_PhaseCount = Annotated[StrictInt, Field(ge=0, le=16)]
_NonNegativeFinite = Annotated[StrictFloat, Field(ge=0, allow_inf_nan=False)]
_Guidance = Annotated[StrictFloat, Field(ge=0, le=1000, allow_inf_nan=False)]
_Unit = Annotated[StrictFloat, Field(ge=0, le=1, allow_inf_nan=False)]


class StudioMusicCustomSettings(_ClosedModel):
    """Closed ACE-Step custom setting IDs shared by the native handler."""

    bpm: Annotated[StrictInt, Field(ge=30, le=300)] | Literal[""] | None = None
    keyscale: _ShortText | None = None
    timesignature: Literal[2, 3, 4, 6, ""] | None = None
    language: _ShortText | None = None


def _non_blank(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must contain a non-blank value")


def _check_active_tts_metadata(params: Any) -> None:
    for index in range(1, 7):
        if getattr(params, f"tts_speaker_name{index}") not in (None, ""):
            raise ValueError("TTS voice names are inactive in music mode")
    if params.tts_voice_count != 0:
        raise ValueError("input.params._tts_voice_count must be zero in music mode")
    if params.tts_original_prompt is None and "tts_original_prompt" in params.model_fields_set:
        raise ValueError("_tts_original_prompt must be a string when supplied")


class StudioMusicParams(_ClosedModel):
    """Strict native music parameters emitted by Studio."""

    prompt: _Prompt
    alt_prompt: _Text = ""
    model_type: _Identity
    # Resolution is carried by the shared Studio form but is not interpreted
    # by either native music handler.  If present, it remains literal.
    resolution: _ShortText | None = None
    lyrics_language: _ShortText | None = None

    video_length: _Zero = 0
    num_inference_steps: _Steps | None = None
    guidance_scale: _Guidance | None = None
    seed: _Seed = -1
    image_mode: _Zero = 0
    generation_mode: Literal["audio"] = "audio"
    negative_prompt: Literal["", None] = ""
    repeat_generation: _One = 1
    batch_size: _One = 1
    activated_loras: list[_Name] = Field(default_factory=list, max_length=_MAX_LORA_COUNT)
    loras_multipliers: _ShortText = ""
    multi_prompts_gen_type: _Two = 2

    # ACE-Step 1.5 exposes these exact source selectors.  MiniMax-Music3
    # rejects all non-empty values during model preflight.
    audio_prompt_type: Literal["", "A", "B", "AB"] = ""
    audio_guide: StrictStr | None = None
    audio_guide2: StrictStr | None = None
    audio_guide3: StrictStr | None = None
    audio_guide4: StrictStr | None = None
    audio_guide5: StrictStr | None = None
    audio_guide6: StrictStr | None = None
    audio_source: Literal["", None] = None

    duration_seconds: _NonNegativeFinite | None = None
    temperature: _NonNegativeFinite | None = None
    top_p: _Unit | None = None
    top_k: _Steps | None = None
    audio_scale: _Guidance | None = None
    alt_guidance_scale: _Guidance | None = None
    guidance_phases: _PhaseCount | None = None
    sample_solver: _ShortText = ""
    settings_version: _NonNegativeFinite | None = None
    prompt_enhancer: Literal["", None] = ""
    model_mode: StrictInt | None = None
    custom_settings: StudioMusicCustomSettings | None = None

    # Music UI metadata.  ``_music_description`` is not used as a fallback
    # for the caption, and ``_music_instrumental`` never rewrites lyrics.
    music_description: _Text = Field("", alias="_music_description")
    music_instrumental: StrictBool = Field(False, alias="_music_instrumental")

    # Studio currently serializes TTS bookkeeping for the shared audio tab.
    # It is retained only as inactive metadata; active voice selection fails
    # closed above rather than turning a music command into speech.
    audio_sub_mode: Literal["music"] = Field("music", alias="_audio_sub_mode")
    tts_original_prompt: _Text | None = Field(None, alias="_tts_original_prompt")
    tts_speaker_name1: _Text | None = Field("", alias="_tts_speaker_name1")
    tts_speaker_name2: _Text | None = Field("", alias="_tts_speaker_name2")
    tts_speaker_name3: _Text | None = Field("", alias="_tts_speaker_name3")
    tts_speaker_name4: _Text | None = Field("", alias="_tts_speaker_name4")
    tts_speaker_name5: _Text | None = Field("", alias="_tts_speaker_name5")
    tts_speaker_name6: _Text | None = Field("", alias="_tts_speaker_name6")
    tts_voice_count: _Zero = Field(0, alias="_tts_voice_count")

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
            if not value.strip() or value in {".", ".."} or "/" in value or "\\" in value:
                raise ValueError("activated_loras must contain exact catalog names")
        return values

    @model_validator(mode="after")
    def _check_semantics(self):
        _non_blank(self.prompt, "input.params.prompt")
        # ACE-Step accepts lyrics without a style caption. MiniMax requires
        # one; reject that request here, before resources or task admission.
        if self.model_type in (MUSIC3_LOCAL, YUE2_LOCAL):
            _non_blank(self.alt_prompt, "input.params.alt_prompt")
        _non_blank(self.model_type, "input.params.model_type")
        if self.model_type not in STUDIO_MUSIC_MODEL_TYPES:
            raise ValueError("input.params.model_type is not a registered local music model")
        _check_active_tts_metadata(self)
        return self


class StudioMusicInput(_ClosedModel):
    workspace: _Workspace
    workspace_collection_id: _WorkspaceCollectionId | None = None
    params: StudioMusicParams

    @model_validator(mode="after")
    def _check_collection_id(self):
        if self.workspace_collection_id is not None:
            _non_blank(self.workspace_collection_id, "input.workspace_collection_id")
        return self


class _StudioMusicEnvelope(_ClosedModel):
    version: Literal[SCHEMA_VERSION]
    operation: Literal[OPERATION]
    intent_id: _IntentId
    input: StudioMusicInput

    @model_validator(mode="after")
    def _check_intent(self):
        _non_blank(self.intent_id, "intent_id")
        return self


def _validation_error(exc: ValidationError) -> StudioMusicSpecError:
    details: list[dict[str, Any]] = []
    messages: list[str] = []
    for error in exc.errors(include_input=False):
        location = ".".join(str(part) for part in error.get("loc", ())) or "command"
        message = str(error.get("msg") or "Invalid value")
        details.append({"loc": location, "message": message, "type": error.get("type")})
        messages.append(f"{location}: {message}")
    return StudioMusicSpecError(
        "; ".join(messages) or "Invalid Studio music generation command",
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


def freeze_studio_music_spec(command: Any) -> dict[str, Any]:
    """Validate and detach one Studio music command without side effects."""
    if type(command) is not dict:
        raise StudioMusicSpecError("Studio music generation command must be an object")
    try:
        envelope = _StudioMusicEnvelope.model_validate(command)
    except ValidationError as exc:
        raise _validation_error(exc) from exc

    original = deepcopy(command)
    explicit_params = envelope.input.params.model_dump(
        mode="json", by_alias=True, exclude_unset=True
    )
    effective_params = deepcopy(explicit_params)
    for key, value in STUDIO_MUSIC_DEFAULTS.items():
        effective_params.setdefault(key, deepcopy(value))
    # TTS bookkeeping is metadata only.  When Studio omitted it, retain the
    # exact lyrics literal as the native bookkeeping value without rewriting
    # either prompt field.
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

    return {
        "original": original,
        "effective": effective,
        "fingerprint_version": FINGERPRINT_VERSION,
        "fingerprint": _fingerprint(_canonical_content(effective)),
    }


def studio_music_schema() -> dict[str, Any]:
    """Return the discovery schema for the implemented local music boundary."""
    input_schema = StudioMusicInput.model_json_schema()
    envelope_schema = _StudioMusicEnvelope.model_json_schema()
    return {
        "version": SCHEMA_VERSION,
        "operation": OPERATION,
        "intent_id": envelope_schema["properties"]["intent_id"],
        "input": input_schema,
        "supported_input_fields": list(SUPPORTED_INPUT_FIELDS),
        "music_model_types": sorted(STUDIO_MUSIC_MODEL_TYPES),
        "local_models": sorted(STUDIO_MUSIC_MODEL_TYPES),
        "guide_revision": GUIDE_REVISION,
        "effects": deepcopy(STUDIO_MUSIC_DEFAULTS),
        "inactive": list(INACTIVE_MUSIC_FIELDS),
        "excluded": list(EXCLUDED_MUSIC_FIELDS),
    }


# Names used by the generic operation adapter and by discovery scripts.
StudioMusicGenerationInput = StudioMusicInput
StudioMusicGenerationParams = StudioMusicParams
music_generation_schema_v2 = studio_music_schema


__all__ = [
    "EXCLUDED_MUSIC_FIELDS",
    "FINGERPRINT_VERSION",
    "GUIDE_REVISION",
    "INACTIVE_MUSIC_FIELDS",
    "MUSIC_MODEL_TYPES",
    "OPERATION",
    "SCHEMA_VERSION",
    "STUDIO_MUSIC_OPERATION",
    "STUDIO_MUSIC_DEFAULTS",
    "STUDIO_MUSIC_MODEL_TYPES",
    "STUDIO_MUSIC_SCHEMA_VERSION",
    "SUPPORTED_INPUT_FIELDS",
    "StudioMusicCustomSettings",
    "StudioMusicGenerationInput",
    "StudioMusicGenerationParams",
    "StudioMusicInput",
    "StudioMusicParams",
    "StudioMusicSpecError",
    "freeze_studio_music_spec",
    "music_generation_schema_v2",
    "studio_music_schema",
]
