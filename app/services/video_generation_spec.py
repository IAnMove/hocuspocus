"""Closed, provider-free contract for the typed ``generation.video`` command.

This first vertical freezes one Wan 2.1 Text2Video family (``t2v`` and
``t2v_1.3B``) before model lookup, resource inspection or task admission.
``original`` keeps the submitted envelope byte-for-byte. ``effective`` adds
only adapter-owned video sentinels. The fingerprint covers operation,
workspace and native parameters and excludes ``intent_id``.
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
OPERATION = "generation.video"
VIDEO_MODEL_FAMILY = "wan_t2v_2_1"
VIDEO_MODEL_TYPES = frozenset({"t2v", "t2v_1.3B"})
WAN_T2V_ARCHITECTURES = frozenset({"t2v", "t2v_1.3B"})

_MAX_ID_LENGTH = 240
_MAX_INTENT_LENGTH = 160
_MAX_PROMPT_LENGTH = 200_000
_MAX_REFERENCE_LENGTH = 8_192
_MAX_LORA_COUNT = 64
_RESOLUTION = re.compile(r"^([1-9][0-9]{1,4})x([1-9][0-9]{1,4})$")

STUDIO_VIDEO_DEFAULTS: dict[str, Any] = {
    "generation_mode": "video",
    "image_mode": 0,
    "repeat_generation": 1,
    "batch_size": 1,
    "prompt_enhancer": "",
    "activated_loras": [],
    "loras_multipliers": "",
    "negative_prompt": "",
    "seed": -1,
    "video_prompt_type": "",
    "image_prompt_type": "",
    # Keep a literal multi-line prompt as one video. Image/speech/music already
    # pin this; omitting it lets wgp.primary_settings (default 0) split each
    # newline into a separate generation at execute time.
    "multi_prompts_gen_type": 2,
}

SUPPORTED_INPUT_FIELDS = (
    "prompt",
    "negative_prompt",
    "model_type",
    "resolution",
    "video_length",
    "num_inference_steps",
    "guidance_scale",
    "seed",
    "image_mode",
    "generation_mode",
    "repeat_generation",
    "batch_size",
    "activated_loras",
    "loras_multipliers",
    "image_start",
    "image_end",
    "image_refs",
    "video_guide",
    "video_source",
    "video_mask",
    "image_prompt_type",
    "video_prompt_type",
    "prompt_enhancer",
    "flow_shift",
    "sample_solver",
    "guidance_phases",
    "multi_prompts_gen_type",
)

INACTIVE_VIDEO_FIELDS = (
    "generation_mode=video",
    "image_mode=0",
    "repeat_generation=1",
    "batch_size=1",
    "prompt_enhancer=empty",
    "video_prompt_type=empty",
    "image_prompt_type=empty",
    "multi_prompts_gen_type=2",
    "image_end=empty_or_null",
    "video_source=empty_or_null",
    "video_mask=empty_or_null",
)

EXCLUDED_VIDEO_FIELDS = (
    "actor",
    "client",
    "permission",
    "provenance",
    "workspace inside input.params",
    "filesystem paths",
    "remote URLs",
    "free-form provider payloads",
    "speech, music and SFX controls",
    "avatar, recast and model3d controls",
    "Hunyuan, LTX, MiniMax H3 and Wan 2.2 families",
    "download or queue controls",
)


class VideoGenerationSpecError(ImageGenerationSpecError):
    """Validation error for the closed generation.video envelope."""


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
_Reference = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=_MAX_REFERENCE_LENGTH),
]
_Steps = Annotated[StrictInt, Field(ge=1, le=1000)]
_Seed = Annotated[StrictInt, Field(ge=-(2**63), le=2**63 - 1)]
_Count = Annotated[StrictInt, Field(ge=1, le=1)]
_Two = Annotated[StrictInt, Field(ge=2, le=2)]
_Zero = Annotated[StrictInt, Field(ge=0, le=0)]
_Frames = Annotated[StrictInt, Field(ge=5, le=10_000)]
_PhaseCount = Annotated[StrictInt, Field(ge=1, le=3)]
_Guidance = Annotated[StrictFloat, Field(ge=0, le=1000, allow_inf_nan=False)]
_Finite = Annotated[StrictFloat, Field(allow_inf_nan=False)]
_Resolution = Annotated[StrictStr, StringConstraints(min_length=1, max_length=128)]


def _non_blank(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must contain a non-blank value")


def _check_resolution(value: str) -> str:
    match = _RESOLUTION.fullmatch(value)
    if match is None:
        raise ValueError("resolution must be WIDTHxHEIGHT")
    width, height = (int(part) for part in match.groups())
    if any(not 64 <= size <= 4096 or size % 8 for size in (width, height)):
        raise ValueError("resolution sides must be 64..4096 and a multiple of 8")
    return value


def _check_optional_reference(value):
    if value in (None, ""):
        return value
    if isinstance(value, list):
        if any(item not in (None, "") and not isinstance(item, str) for item in value):
            raise ValueError("reference lists must contain strings")
        return [_validate_reference(item) if item not in (None, "") else item for item in value]
    return _validate_reference(value)


class VideoGenerationParams(_ClosedModel):
    """Closed native parameters for one Wan 2.1 Text2Video job."""

    prompt: _Prompt
    negative_prompt: _Text = ""
    model_type: Literal["t2v", "t2v_1.3B"]
    resolution: _Resolution
    video_length: _Frames
    num_inference_steps: _Steps
    guidance_scale: _Guidance
    seed: _Seed = -1
    image_mode: _Zero = 0
    generation_mode: Literal["video"] = "video"
    repeat_generation: _Count = 1
    batch_size: _Count = 1
    multi_prompts_gen_type: _Two = 2
    activated_loras: list[_Identity] = Field(default_factory=list, max_length=_MAX_LORA_COUNT)
    loras_multipliers: _ShortText = ""
    prompt_enhancer: Literal["", None] = ""
    image_prompt_type: Literal["", None] = ""
    video_prompt_type: Literal["", None] = ""
    flow_shift: _Finite | None = None
    sample_solver: _ShortText = ""
    guidance_phases: _PhaseCount = 1

    image_start: _Reference | Literal["", None] | list[StrictStr] = None
    image_end: Literal["", None] | list[StrictStr] = None
    image_refs: list[StrictStr] | None = None
    video_guide: _Reference | Literal["", None] = None
    video_source: Literal["", None] = None
    video_mask: Literal["", None] = None

    @field_validator("resolution")
    @classmethod
    def _resolution(cls, value):
        return _check_resolution(value)

    @field_validator("activated_loras")
    @classmethod
    def _lora_names(cls, values):
        for value in values:
            if not value.strip() or value in {".", ".."} or "/" in value or "\\" in value:
                raise ValueError("activated_loras must contain exact catalog names")
        return values

    @field_validator("image_start", "video_guide")
    @classmethod
    def _active_reference(cls, value):
        return _check_optional_reference(value)

    @field_validator("image_end", "image_refs")
    @classmethod
    def _optional_reference_list(cls, value):
        if value in (None, "", []):
            return value
        if isinstance(value, list) and all(item == "" for item in value):
            return value
        if isinstance(value, list):
            return _check_optional_reference(value)
        raise ValueError("inactive image lists must be empty")

    @model_validator(mode="after")
    def _check_semantics(self):
        _non_blank(self.prompt, "input.params.prompt")
        _non_blank(self.model_type, "input.params.model_type")
        if self.model_type not in VIDEO_MODEL_TYPES:
            raise ValueError("input.params.model_type is not a registered Wan 2.1 Text2Video model")
        return self


class VideoGenerationInput(_ClosedModel):
    workspace: _Workspace
    workspace_collection_id: _WorkspaceCollectionId | None = None
    params: VideoGenerationParams

    @model_validator(mode="after")
    def _check_collection_id(self):
        if self.workspace_collection_id is not None:
            _non_blank(self.workspace_collection_id, "input.workspace_collection_id")
        return self


class _VideoGenerationEnvelope(_ClosedModel):
    version: Literal[SCHEMA_VERSION]
    operation: Literal[OPERATION]
    intent_id: _IntentId
    input: VideoGenerationInput

    @model_validator(mode="after")
    def _check_intent(self):
        _non_blank(self.intent_id, "intent_id")
        return self


def _validation_error(exc: ValidationError) -> VideoGenerationSpecError:
    details: list[dict[str, Any]] = []
    messages: list[str] = []
    for error in exc.errors(include_input=False):
        location = ".".join(str(part) for part in error.get("loc", ())) or "command"
        message = str(error.get("msg") or "Invalid value")
        details.append({"loc": location, "message": message, "type": error.get("type")})
        messages.append(f"{location}: {message}")
    return VideoGenerationSpecError(
        "; ".join(messages) or "Invalid generation.video command",
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


def freeze_video_generation_spec(command: Any) -> dict[str, Any]:
    """Validate and detach one generation.video command without I/O."""
    if type(command) is not dict:
        raise VideoGenerationSpecError("generation.video command must be an object")
    try:
        envelope = _VideoGenerationEnvelope.model_validate(command)
    except ValidationError as exc:
        raise _validation_error(exc) from exc

    original = deepcopy(command)
    explicit_params = envelope.input.params.model_dump(mode="json", exclude_unset=True)
    effective_params = deepcopy(explicit_params)
    for key, value in STUDIO_VIDEO_DEFAULTS.items():
        effective_params.setdefault(key, deepcopy(value))

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


def video_generation_schema() -> dict[str, Any]:
    """Return the executable discovery schema for ``generation.video``."""
    input_schema = VideoGenerationInput.model_json_schema()
    envelope_schema = _VideoGenerationEnvelope.model_json_schema()
    return {
        "version": SCHEMA_VERSION,
        "operation": OPERATION,
        "intent_id": envelope_schema["properties"]["intent_id"],
        "input": input_schema,
        "supported_input_fields": list(SUPPORTED_INPUT_FIELDS),
        "video_model_family": VIDEO_MODEL_FAMILY,
        "video_model_types": sorted(VIDEO_MODEL_TYPES),
        "architectures": sorted(WAN_T2V_ARCHITECTURES),
        "effects": deepcopy(STUDIO_VIDEO_DEFAULTS),
        "inactive": list(INACTIVE_VIDEO_FIELDS),
        "excluded": list(EXCLUDED_VIDEO_FIELDS),
        "limits": {
            "video_length_frames": {"minimum": 5, "maximum": 10000},
            "resolution": "WIDTHxHEIGHT, each 64..4096 and a multiple of 8",
        },
    }


StudioVideoParams = VideoGenerationParams
StudioVideoInput = VideoGenerationInput
freeze_studio_video_spec = freeze_video_generation_spec
studio_video_schema = video_generation_schema


__all__ = [
    "EXCLUDED_VIDEO_FIELDS",
    "FINGERPRINT_VERSION",
    "INACTIVE_VIDEO_FIELDS",
    "OPERATION",
    "SCHEMA_VERSION",
    "STUDIO_VIDEO_DEFAULTS",
    "SUPPORTED_INPUT_FIELDS",
    "VIDEO_MODEL_FAMILY",
    "VIDEO_MODEL_TYPES",
    "WAN_T2V_ARCHITECTURES",
    "StudioVideoInput",
    "StudioVideoParams",
    "VideoGenerationInput",
    "VideoGenerationParams",
    "VideoGenerationSpecError",
    "freeze_studio_video_spec",
    "freeze_video_generation_spec",
    "studio_video_schema",
    "video_generation_schema",
]
