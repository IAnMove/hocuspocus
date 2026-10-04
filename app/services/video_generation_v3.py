"""Version 3 of ``generation.video`` for typed H3 and LTX-2.3 shots.

Version 2 stays the closed Wan 2.1 Text2Video contract. Version 3 is the
typed surface for frames and driving audio: MiniMax H3 FL2VA, Ref2VA, and
the already wired LTX-2.3 (``ltx2_22B``) catalog. H3 Advanced is a separate
family and is not accepted here.

``validate: true`` builds the internal generate payload and returns before
admission. Nothing in this module loads a checkpoint or enters the GPU queue.
Lengths and resolutions are the lattices and presets the model handlers
already publish. They are not snapped into compliance.
"""

from __future__ import annotations

from collections.abc import Mapping
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

from models.minimax_h3.duration import H3_EXPERIMENTAL_MAX_FRAMES
from models.minimax_h3.minimax_h3_handler import (
    _H3_FRAME_STEP,
    _H3_MAX_FRAMES,
    _H3_MIN_FRAMES,
    _H3_RESOLUTION_PRESETS,
)
from models.minimax_h3.reference_manifest import (
    MINIMAX_H3_MAX_REFERENCE_AUDIOS,
    MINIMAX_H3_MAX_REFERENCE_IMAGES,
    MINIMAX_H3_MAX_REFERENCE_VIDEOS,
    MINIMAX_H3_MAX_REFERENCES,
    validate_reference_manifest,
)
from services.studio_image_spec import _validate_reference
from services.video_generation_spec import VideoGenerationSpecError


SCHEMA_VERSION = 3
FINGERPRINT_VERSION = 3
OPERATION = "generation.video"

# ltx2_handler.query_model_def: frames_minimum 17, frames_steps 8,
# no frames_maximum. sliding_window_defaults are window_min 5,
# window_max 501, window_step 4. 17+8k through that window cap is the
# typed one-pass list. LTX-2 (ltx2_19B) is not this family.
_LTX_MIN_FRAMES = 17
_LTX_FRAME_STEP = 8
_LTX_WINDOW_MIN = 5
_LTX_WINDOW_MAX = 501
_LTX_WINDOW_STEP = 4

# app/wgp.py get_resolution_choices when enable_4k_resolutions is off.
# LTX-2.3 publishes no resolution_presets of its own.
_LTX_RESOLUTIONS = (
    "1920x1088",
    "1088x1920",
    "1920x832",
    "832x1920",
    "1024x1024",
    "1280x720",
    "720x1280",
    "1280x544",
    "544x1280",
    "1104x832",
    "832x1104",
    "960x960",
    "960x544",
    "544x960",
    "832x624",
    "624x832",
    "720x720",
    "832x480",
    "480x832",
    "512x512",
)

FL2VA_MODEL_TYPES = frozenset({
    "minimax_h3",
    "minimax_h3_full",
    "minimax_h3_legacy",
    "minimax_h3_fused_turbo",
})
REF2VA_MODEL_TYPES = frozenset({
    "minimax_h3_ref2va",
    "minimax_h3_ref2va_full",
    "minimax_h3_ref2va_fused_turbo",
})
LTX23_MODEL_TYPES = frozenset({
    "ltx2_22B",
    "ltx2_22B_1_1",
    "ltx2_22B_10eros",
    "ltx2_22B_10eros_v14",
    "ltx2_22B_distilled",
    "ltx2_22B_distilled_1_1",
    "ltx2_22B_distilled_1_1_omninft",
    "ltx2_22B_distilled_fp8",
    "ltx2_22B_distilled_gguf_q4_k_m",
    "ltx2_22B_distilled_gguf_q6_k",
    "ltx2_22B_distilled_gguf_q8_0",
    "ltx2_22B_fp8",
    "ltx2_22B_nvfp4",
    "ltx2_22B_sulphur2_distilled",
})
_FAMILY = {model: "fl2va" for model in FL2VA_MODEL_TYPES}
_FAMILY.update({model: "ref2va" for model in REF2VA_MODEL_TYPES})
_FAMILY.update({model: "ltx2_3" for model in LTX23_MODEL_TYPES})

H3_LENGTHS = list(range(_H3_MIN_FRAMES, _H3_MAX_FRAMES + 1, _H3_FRAME_STEP))
H3_EXTENDED_LENGTHS = list(range(_H3_MIN_FRAMES, H3_EXPERIMENTAL_MAX_FRAMES + 1, _H3_FRAME_STEP))
LTX_VIDEO_LENGTHS = list(range(_LTX_MIN_FRAMES, _LTX_WINDOW_MAX + 1, _LTX_FRAME_STEP))
LTX_WINDOW_LENGTHS = list(range(_LTX_WINDOW_MIN, _LTX_WINDOW_MAX + 1, _LTX_WINDOW_STEP))
_PLACEHOLDER_EXTENSION = {"image": ".png", "video": ".mp4", "audio": ".wav"}
_REFERENCE_KINDS = frozenset(_PLACEHOLDER_EXTENSION)


class VideoGenerationV3Error(VideoGenerationSpecError):
    """Version-3 validation error with a stable command code."""

    def __init__(self, message: str, *, code: str = "invalid_command", details=None):
        super().__init__(message, details=details)
        self.code = code


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=False)


_Workspace = Annotated[
    StrictStr,
    StringConstraints(
        min_length=1,
        max_length=240,
        pattern=r"^(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)$",
    ),
]
_IntentId = Annotated[StrictStr, StringConstraints(min_length=1, max_length=160)]
_Prompt = Annotated[StrictStr, StringConstraints(min_length=1, max_length=200_000)]
_Reference = Annotated[StrictStr, StringConstraints(min_length=1, max_length=8192)]
_Role = Annotated[StrictStr, StringConstraints(max_length=500)]
_Steps = Annotated[StrictInt, Field(ge=1, le=1000)]
_Seed = Annotated[StrictInt, Field(ge=-(2**63), le=2**63 - 1)]
_Frames = Annotated[StrictInt, Field(ge=1, le=10_000)]
_Guidance = Annotated[StrictFloat, Field(ge=0, le=1000, allow_inf_nan=False)]
_ModelType = Literal[
    "minimax_h3",
    "minimax_h3_full",
    "minimax_h3_legacy",
    "minimax_h3_fused_turbo",
    "minimax_h3_ref2va",
    "minimax_h3_ref2va_full",
    "minimax_h3_ref2va_fused_turbo",
    "ltx2_22B",
    "ltx2_22B_1_1",
    "ltx2_22B_10eros",
    "ltx2_22B_10eros_v14",
    "ltx2_22B_distilled",
    "ltx2_22B_distilled_1_1",
    "ltx2_22B_distilled_1_1_omninft",
    "ltx2_22B_distilled_fp8",
    "ltx2_22B_distilled_gguf_q4_k_m",
    "ltx2_22B_distilled_gguf_q6_k",
    "ltx2_22B_distilled_gguf_q8_0",
    "ltx2_22B_fp8",
    "ltx2_22B_nvfp4",
    "ltx2_22B_sulphur2_distilled",
]


def _preset_values(presets: Mapping[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for preset in presets.values():
        for value in (preset.get("values") or {}).values():
            if value not in values:
                values.append(value)
    return tuple(values)


H3_PRESET_RESOLUTIONS = _preset_values(_H3_RESOLUTION_PRESETS)


class H3Reference(_ClosedModel):
    """One Ref2VA reference. ``source`` is an asset id or canonical URL."""

    type: Literal["image", "video", "audio"]
    source: _Reference
    role: _Role | None = None
    image_intent: Literal["identity", "scene", "style", "composition"] | None = None
    video_intent: Literal["character", "motion", "scene"] | None = None
    audio_intent: Literal["voice", "drive", "style"] | None = None
    include_audio: StrictBool | None = None
    remove_background: StrictBool | None = None

    @field_validator("source")
    @classmethod
    def _source(cls, value: str) -> str:
        return _validate_reference(value)


class VideoV3Params(_ClosedModel):
    """Closed parameters for one typed H3 or LTX-2.3 shot."""

    prompt: _Prompt
    model_type: _ModelType
    resolution: StrictStr
    video_length: _Frames
    sliding_window_size: _Frames | None = None
    seed: _Seed = -1
    num_inference_steps: _Steps | None = None
    guidance_scale: _Guidance | None = None
    image_start: _Reference | None = None
    image_end: _Reference | None = None
    audio_prompt_type: Literal["", "A"] = ""
    audio_guide: _Reference | None = None
    references: list[H3Reference] | None = None
    minimax_h3_reference_detail: Literal["match", "max"] | None = None
    minimax_h3_extended_duration: StrictBool = False

    @field_validator("prompt")
    @classmethod
    def _prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("input.params.prompt must contain a non-blank value")
        return value

    @field_validator("image_start", "image_end", "audio_guide")
    @classmethod
    def _media(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_reference(value)


class _VideoV3Input(_ClosedModel):
    workspace: _Workspace
    params: VideoV3Params


class _VideoV3Envelope(_ClosedModel):
    version: Literal[SCHEMA_VERSION]
    operation: Literal[OPERATION]
    intent_id: _IntentId
    # Alias keeps the public JSON key without shadowing BaseModel.validate.
    validate_only: StrictBool = Field(default=False, alias="validate")
    input: _VideoV3Input

    @model_validator(mode="after")
    def _intent(self):
        if not self.intent_id.strip():
            raise ValueError("intent_id must contain a non-blank value")
        return self


def _validation_error(exc: ValidationError) -> VideoGenerationV3Error:
    details: list[dict[str, Any]] = []
    messages: list[str] = []
    for error in exc.errors(include_input=False):
        location = ".".join(str(part) for part in error.get("loc", ())) or "command"
        message = str(error.get("msg") or "Invalid value")
        details.append({"loc": location, "message": message, "type": error.get("type")})
        messages.append(f"{location}: {message}")
    text = "; ".join(messages) or "Invalid generation.video command"
    return VideoGenerationV3Error(text, details=details)


def _parse(command: Any) -> _VideoV3Envelope:
    if type(command) is not dict:
        raise VideoGenerationV3Error("generation.video command must be an object")
    try:
        return _VideoV3Envelope.model_validate(command)
    except ValidationError as exc:
        raise _validation_error(exc) from exc


def _require_choice(field: str, value: Any, allowed: Any, rule: str) -> None:
    if value in allowed:
        return
    shown = ", ".join(str(item) for item in allowed)
    raise VideoGenerationV3Error(
        f"input.params.{field} {value} is not allowed ({rule}); allowed: {shown}",
        code="invalid_selector",
        details=[{"loc": f"input.params.{field}", "allowed": list(allowed), "rule": rule}],
    )


def _require_h3_lengths(params: VideoV3Params) -> None:
    allowed = H3_EXTENDED_LENGTHS if params.minimax_h3_extended_duration else H3_LENGTHS
    _require_choice("video_length", params.video_length, allowed, "124+17k")
    window = params.video_length if params.sliding_window_size is None else params.sliding_window_size
    _require_choice("sliding_window_size", window, allowed, "124+17k")


def _reject_references(params: VideoV3Params, message: str) -> None:
    if params.references or params.minimax_h3_reference_detail is not None:
        raise VideoGenerationV3Error(message, code="invalid_selector")


def _reject_frames(params: VideoV3Params, message: str) -> None:
    if params.image_start or params.image_end:
        raise VideoGenerationV3Error(message, code="invalid_selector")


def _enforce_soundtrack(params: VideoV3Params) -> None:
    if params.audio_prompt_type == "A":
        if not params.audio_guide:
            raise VideoGenerationV3Error(
                "audio mode A requires audio_guide as an asset id or canonical URL",
                code="invalid_selector",
            )
        return
    if params.audio_guide:
        raise VideoGenerationV3Error("audio_guide requires audio mode A", code="invalid_selector")


def _enforce_fl2va(params: VideoV3Params) -> None:
    _reject_references(params, "FL2VA does not accept Ref2VA references")
    if not params.image_start:
        raise VideoGenerationV3Error("FL2VA requires image_start", code="invalid_selector")
    _require_choice("resolution", params.resolution, H3_PRESET_RESOLUTIONS, "H3 resolution preset")
    _require_h3_lengths(params)
    _enforce_soundtrack(params)


def _copy_present(item: H3Reference, payload: dict[str, Any], keys: tuple[str, ...], *, keep_false: bool) -> None:
    for key in keys:
        value = getattr(item, key)
        if keep_false:
            if value is not None:
                payload[key] = value
        elif value:
            payload[key] = value


def _limit_placeholder(item: H3Reference) -> dict[str, Any]:
    payload = {"type": item.type, "path": f"typed-reference{_PLACEHOLDER_EXTENSION[item.type]}"}
    _copy_present(item, payload, ("role", "image_intent", "video_intent", "audio_intent"), keep_false=False)
    _copy_present(item, payload, ("remove_background", "include_audio"), keep_false=True)
    return payload


def _check_reference_limits(references: list[H3Reference]) -> None:
    placeholders = [_limit_placeholder(item) for item in references]
    try:
        validate_reference_manifest(placeholders, require_files=False)
    except ValueError as error:
        raise VideoGenerationV3Error(str(error), code="invalid_reference") from error


def _enforce_ref2va(params: VideoV3Params) -> None:
    _reject_frames(params, "Ref2VA uses image, video, and audio references, not image_start or image_end")
    if params.audio_prompt_type == "A" or params.audio_guide:
        raise VideoGenerationV3Error(
            "Ref2VA audio is a reference, not audio mode A",
            code="invalid_selector",
        )
    if not params.references:
        raise VideoGenerationV3Error(
            "Ref2VA requires at least one image or video reference",
            code="invalid_reference",
        )
    _check_reference_limits(params.references)
    _require_choice("resolution", params.resolution, H3_PRESET_RESOLUTIONS, "H3 resolution preset")
    _require_h3_lengths(params)


def _enforce_ltx(params: VideoV3Params) -> None:
    if params.minimax_h3_extended_duration:
        raise VideoGenerationV3Error(
            "LTX-2.3 does not use minimax_h3_extended_duration",
            code="invalid_selector",
        )
    _reject_references(params, "LTX-2.3 does not accept Ref2VA references")
    if not params.image_start:
        raise VideoGenerationV3Error("LTX-2.3 requires image_start", code="invalid_selector")
    _require_choice("resolution", params.resolution, _LTX_RESOLUTIONS, "LTX-2.3 resolution preset")
    _require_choice("video_length", params.video_length, LTX_VIDEO_LENGTHS, "17+8k")
    window = params.video_length if params.sliding_window_size is None else params.sliding_window_size
    _require_choice("sliding_window_size", window, LTX_WINDOW_LENGTHS, "5+4k through 501")
    _enforce_soundtrack(params)


def _enforce_video_v3(params: VideoV3Params) -> None:
    family = _FAMILY[params.model_type]
    if family == "fl2va":
        _enforce_fl2va(params)
    elif family == "ref2va":
        _enforce_ref2va(params)
    else:
        _enforce_ltx(params)


def _generate_reference(item: H3Reference) -> dict[str, Any]:
    payload = {"type": item.type, "path": item.source}
    _copy_present(item, payload, ("role", "image_intent", "video_intent", "audio_intent"), keep_false=False)
    _copy_present(item, payload, ("remove_background", "include_audio"), keep_false=True)
    return payload


def _put_sampling(payload: dict[str, Any], params: VideoV3Params) -> None:
    if params.num_inference_steps is not None:
        payload["num_inference_steps"] = params.num_inference_steps
    if params.guidance_scale is not None:
        payload["guidance_scale"] = params.guidance_scale


def _assemble_frames(payload: dict[str, Any], params: VideoV3Params) -> None:
    payload["image_start"] = params.image_start
    payload["image_prompt_type"] = "SE" if params.image_end else "S"
    if params.image_end:
        payload["image_end"] = params.image_end


def _assemble_video_v3_payload(params: VideoV3Params) -> dict[str, Any]:
    family = _FAMILY[params.model_type]
    payload = {
        "model_type": params.model_type,
        "prompt": params.prompt,
        "resolution": params.resolution,
        "video_length": params.video_length,
        "sliding_window_size": (
            params.video_length if params.sliding_window_size is None else params.sliding_window_size
        ),
        "seed": params.seed,
        "generation_mode": "video",
        "image_mode": 0,
        "multi_prompts_gen_type": 2,
        "audio_prompt_type": params.audio_prompt_type,
    }
    _put_sampling(payload, params)
    if family == "ref2va":
        payload["minimax_h3_references"] = [_generate_reference(item) for item in params.references or []]
        payload["minimax_h3_reference_detail"] = params.minimax_h3_reference_detail or "match"
    else:
        _assemble_frames(payload, params)
    if family != "ltx2_3" and params.minimax_h3_extended_duration:
        payload["minimax_h3_extended_duration"] = True
    if params.audio_guide:
        payload["audio_guide"] = params.audio_guide
    return payload


def build_video_v3_payload(params: VideoV3Params) -> dict[str, Any]:
    """Return the generate-shaped payload for an already parsed version-3 model."""

    _enforce_video_v3(params)
    return _assemble_video_v3_payload(params)


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


def freeze_video_generation_v3(command: Any) -> dict[str, Any]:
    """Validate one version-3 command and detach its generate payload."""

    envelope = _parse(command)
    payload = build_video_v3_payload(envelope.input.params)
    effective = {
        "version": SCHEMA_VERSION,
        "operation": OPERATION,
        "intent_id": envelope.intent_id,
        "input": {"workspace": envelope.input.workspace, "params": payload},
    }
    return {
        "original": deepcopy(command),
        "effective": effective,
        "fingerprint_version": FINGERPRINT_VERSION,
        "fingerprint": _fingerprint(_canonical_content(effective)),
    }


def video_generation_v3_schema() -> dict[str, Any]:
    """Discovery schema for generation.video version 3."""

    envelope = _VideoV3Envelope.model_json_schema()
    return {
        "version": SCHEMA_VERSION,
        "operation": OPERATION,
        "intent_id": envelope["properties"]["intent_id"],
        "input": _VideoV3Input.model_json_schema(),
        "families": {
            "minimax_h3_fl2va": sorted(FL2VA_MODEL_TYPES),
            "minimax_h3_ref2va": sorted(REF2VA_MODEL_TYPES),
            "ltx2_3": sorted(LTX23_MODEL_TYPES),
        },
        "limits": {
            "reference_images": MINIMAX_H3_MAX_REFERENCE_IMAGES,
            "reference_videos": MINIMAX_H3_MAX_REFERENCE_VIDEOS,
            "reference_audios": MINIMAX_H3_MAX_REFERENCE_AUDIOS,
            "reference_total": MINIMAX_H3_MAX_REFERENCES,
            "h3_lengths": {"rule": "124+17k", "allowed": list(H3_LENGTHS)},
            "h3_extended_lengths": {"rule": "124+17k", "allowed": list(H3_EXTENDED_LENGTHS)},
            "h3_resolutions": list(H3_PRESET_RESOLUTIONS),
            "ltx2_3_video_lengths": {"rule": "17+8k", "allowed": list(LTX_VIDEO_LENGTHS)},
            "ltx2_3_windows": {"rule": "5+4k", "allowed": list(LTX_WINDOW_LENGTHS)},
            "ltx2_3_resolutions": list(_LTX_RESOLUTIONS),
            "audio_prompt_type": ["", "A"],
        },
    }


def _lookup_definition(model_definition: Any, model_type: str) -> dict[str, Any] | None:
    if callable(model_definition):
        definition = model_definition(model_type)
    elif isinstance(model_definition, Mapping):
        definition = model_definition.get(model_type)
    else:
        definition = None
    if isinstance(definition, Mapping):
        return dict(definition)
    return None


def _require_execution(working: dict[str, Any], execution_policy: Any) -> None:
    workspace = working.get("workspace")
    if not isinstance(workspace, str) or not workspace.strip():
        raise ValueError("input.workspace must be an explicit output workspace")
    if not callable(execution_policy):
        raise TypeError("execution_policy must be a workspace policy callback")
    execution_policy(workspace)


def _require_installed_model(working: dict[str, Any], model_definition: Any, model_downloaded: Any) -> None:
    from services.image_generation_commands import command_error

    model_type = working.get("model_type")
    if model_type not in _FAMILY:
        raise ValueError("input.params.model_type is not a typed H3 or LTX-2.3 model")
    if _lookup_definition(model_definition, str(model_type)) is None:
        raise command_error(
            422,
            "unsupported_model",
            "Choose an installed H3 or LTX-2.3 model from the catalog",
        )
    if not callable(model_downloaded) or not model_downloaded(model_type):
        raise command_error(
            409,
            "model_unavailable",
            "Required model files are not installed; install them before submitting",
        )


def _resolve_named(resources: Any, value: Any, kind: str) -> Any:
    resolve = getattr(resources, "_resolve", None)
    if not callable(resolve) or not isinstance(value, str) or not value:
        return value
    path, _workspace = resolve(value, kind)
    return path


def _resolve_audio_guide(prepared: dict[str, Any], resources: Any) -> None:
    if "audio_guide" not in prepared:
        return
    prepared["audio_guide"] = _resolve_named(resources, prepared.get("audio_guide"), "audio")


def _resolve_reference_paths(prepared: dict[str, Any], resources: Any) -> None:
    references = prepared.get("minimax_h3_references")
    if not isinstance(references, list):
        return
    for item in references:
        if not isinstance(item, dict):
            raise ValueError("MiniMax H3 references must be objects")
        kind = item.get("type")
        if kind not in _REFERENCE_KINDS:
            kind = "image"
        item["path"] = _resolve_named(resources, item.get("path"), kind)


def _resolve_typed_media(working: dict[str, Any], resources: Any) -> tuple[dict[str, Any], list]:
    prepared = deepcopy(working)
    media: list = []
    prepare_media = getattr(resources, "prepare_media", None)
    if callable(prepare_media):
        prepared, media = prepare_media(prepared)
        prepared = deepcopy(prepared)
        media = deepcopy(list(media))
    _resolve_audio_guide(prepared, resources)
    _resolve_reference_paths(prepared, resources)
    return prepared, media


def _prepare_typed_video(params, *, model_definition, model_downloaded, resources, execution_policy):
    working = {key: value for key, value in params.items() if not str(key).startswith("_")}
    _require_execution(working, execution_policy)
    _require_installed_model(working, model_definition, model_downloaded)
    return _resolve_typed_media(working, resources)


def prepare_video_generation_v3(
    params,
    *,
    model_definition,
    model_downloaded,
    resources,
    execution_policy,
):
    """Resolve a version-3 payload before admission. Does not enqueue."""

    from services.image_generation_commands import command_error

    try:
        return _prepare_typed_video(
            params,
            model_definition=model_definition,
            model_downloaded=model_downloaded,
            resources=resources,
            execution_policy=execution_policy,
        )
    except VideoGenerationV3Error:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise command_error(422, "invalid_studio_video_input", str(error)) from error


__all__ = [
    "FL2VA_MODEL_TYPES",
    "H3_EXTENDED_LENGTHS",
    "H3_LENGTHS",
    "H3_PRESET_RESOLUTIONS",
    "LTX23_MODEL_TYPES",
    "LTX_VIDEO_LENGTHS",
    "LTX_WINDOW_LENGTHS",
    "REF2VA_MODEL_TYPES",
    "SCHEMA_VERSION",
    "VideoGenerationV3Error",
    "VideoV3Params",
    "build_video_v3_payload",
    "freeze_video_generation_v3",
    "prepare_video_generation_v3",
    "video_generation_v3_schema",
]
