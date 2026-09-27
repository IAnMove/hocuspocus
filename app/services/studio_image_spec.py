"""Closed, provider-free contract for a complete Studio image submission.

The first shared image command (``image_generation_spec``) intentionally owns a
small text-to-image surface.  Studio, however, has a much larger native
parameter map: image references, LoRAs, model tuning, post-processing and
typed processor settings are all assembled immediately before ``newJob`` in
the browser.  This module freezes that map before model/resource resolution
or queue effects.

The v2 transport envelope is::

    {
        "version": 2,
        "operation": "generation.image",
        "intent_id": "...",
        "input": {
            "workspace": "...",
            "params": { ... strict native image fields ... }
        }
    }

``original`` is a detached copy of the caller envelope.  ``effective`` adds
only deterministic adapter defaults and keeps the native image fields intact.
The content fingerprint covers the effective operation, workspace and params;
the transport intent is deliberately excluded.  Actor/provenance data and
host paths are rejected here because the runtime owns those authorities.

Reference values are exact asset identifiers or canonical local API URLs.  A
URL is syntax-checked here; source workspace containment, file identity and
model/LoRA compatibility are resolved by the resource/model preflight layer.
No model catalog, settings loader, filesystem path or provider is consulted.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import parse_qs, unquote, urlsplit

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


SCHEMA_VERSION = 2
FINGERPRINT_VERSION = 2
OPERATION = "generation.image"

_MAX_ID_LENGTH = 240
_MAX_INTENT_LENGTH = 160
_MAX_PROMPT_LENGTH = 200_000
_MAX_REFERENCE_LENGTH = 8192
_MAX_REFERENCE_COUNT = 64

# These defaults are adapter-owned.  Defaults for an installed model must be
# obtained by the later model preflight, never inferred by this provider-free
# boundary.  In particular, settings_version is retained when explicitly
# supplied but is intentionally not invented here.
STUDIO_IMAGE_DEFAULTS = {
    "generation_mode": "image",
    "image_mode": 1,
    "video_length": 1,
    "multi_prompts_gen_type": 2,
    "repeat_generation": 1,
    "batch_size": 1,
    "prompt_enhancer": "",
    "activated_loras": [],
    "loras_multipliers": "",
    "canonical_image_refs": False,
}

# The native engine accepts many more keys for video, audio, avatars and
# editor jobs.  Fields that have a harmless empty/null image-mode sentinel are
# modelled below as ``INACTIVE_IMAGE_FIELDS`` so a restored Studio snapshot is
# not truncated.  Other mode-specific fields remain rejected explicitly.
INACTIVE_IMAGE_FIELDS = (
    "minimax_h3_turbo_mode",
    "audio_guide",
    "audio_guide2",
    "audio_guide3",
    "audio_guide4",
    "audio_guide5",
    "audio_guide6",
    "audio_source",
    "video_source",
    "video_guide",
    "video_mask",
    "temporal_upsampling",
    "audio_prompt_type",
    "sliding_window_size",
    "sliding_window_overlap",
    "sliding_window_memory_override",
    "sliding_window_discard_last_frames",
    "sliding_window_color_correction_strength",
    "sliding_window_overlap_noise",
    "keep_frames_video_source",
    "keep_frames_video_guide",
    "force_fps",
    "h3_ref_videos",
    "h3_ref_audios",
    "minimax_h3_references",
    "MMAudio_setting",
    "MMAudio_prompt",
    "MMAudio_neg_prompt",
)

INCOMPATIBLE_IMAGE_FIELDS = (
    # Avatar/audio/video controls have no image-mode interpretation.  Their
    # names are listed here so callers get a stable contract error instead of
    # accidentally relying on the generic extra-field message.
    "viggle_audio_mode",
    "preserve_source_style",
    "stage2_steps",
    "per_clip_frames",
    "per_clip_keyframes",
    "perturbation_switch",
    "perturbation_layers",
    "perturbation_start_perc",
    "perturbation_end_perc",
    "stg_scale",
    "keyframe_conditioning_mode",
    "keyframe_inject_mode",
    "h3_audio_shift",
    "h3_audio_prompt",
    "h3_ref_image_size",
    "h3_reference_mode",
    "h3_model_profile",
    "h3_reference_context",
    "h3_window_prompts",
    "h3_window_plan_signature",
    "h3_window_plan",
    "minimax_h3_reference_detail",
    "minimax_h3_text_encoder",
    "minimax_h3_turbo_preset",
    "minimax_h3_planning_style",
    "minimax_h3_audio_policy",
    "minimax_h3_reference_sequence",
    "minimax_h3_semantic_bridge_alpha",
    "minimax_h3_semantic_bridge_magnitude",
    "minimax_h3_multi_window",
    "minimax_h3_window_storyboard",
    "continue_video",
    "voice_reference",
    "voice_clone_enabled",
    "voice_clone_mode",
    "voice_clone_refs",
    "tts_dynaudnorm",
    "tts_comp_threshold",
    "tts_comp_attack",
    "tts_comp_release",
    "tts_comp_makeup",
    "tts_voice_count",
    "duration_seconds",
    "pause_seconds",
    "_audio_sub_mode",
    "_music_description",
    "_music_instrumental",
    "_tts_original_prompt",
    "_tts_speaker_name1",
    "_tts_speaker_name2",
    "sfx_mode",
)

# Fields in this v2 contract are the image subset of the native generate
# signature plus the post-processing/processor knobs that Studio serializes.
# Keep this inventory explicit; adding a field requires a typed declaration and
# a regression test rather than an unvalidated JSON escape hatch.
SUPPORTED_INPUT_FIELDS = (
    "minimax_h3_turbo_mode",
    "workspace",
    "workspace_collection_id",
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
    "batch_size",
    "activated_loras",
    "loras_multipliers",
    "image_start",
    "image_end",
    "image_refs",
    "image_guide",
    "image_mask",
    "video_guide",
    "video_mask",
    "video_source",
    "audio_guide",
    "audio_guide2",
    "audio_guide3",
    "audio_guide4",
    "audio_guide5",
    "audio_guide6",
    "audio_source",
    "MMAudio_setting",
    "MMAudio_prompt",
    "MMAudio_neg_prompt",
    "h3_ref_videos",
    "h3_ref_audios",
    "minimax_h3_references",
    "image_prompt_type",
    "video_prompt_type",
    "frames_positions",
    "canonical_image_refs",
    "multi_prompts_gen_type",
    "image_fit_mode",
    "input_video_strength",
    "denoising_strength",
    "masking_strength",
    "video_guide_outpainting",
    "control_net_weight",
    "control_net_weight2",
    "control_net_weight_alt",
    "motion_amplitude",
    "mask_expand",
    "image_refs_relative_size",
    "remove_background_images_ref",
    "model_mode",
    "temporal_upsampling",
    "audio_prompt_type",
    "sliding_window_size",
    "sliding_window_overlap",
    "sliding_window_memory_override",
    "sliding_window_discard_last_frames",
    "sliding_window_color_correction_strength",
    "sliding_window_overlap_noise",
    "keep_frames_video_source",
    "keep_frames_video_guide",
    "force_fps",
    "flow_shift",
    "sample_solver",
    "embedded_guidance_scale",
    "guidance2_scale",
    "guidance3_scale",
    "switch_threshold",
    "switch_threshold2",
    "guidance_phases",
    "model_switch_phase",
    "alt_guidance_scale",
    "alt_scale",
    "audio_guidance_scale",
    "audio_scale",
    "NAG_scale",
    "NAG_tau",
    "NAG_alpha",
    "RIFLEx_setting",
    "injection_strength",
    "identity_guidance_scale",
    "skip_steps_cache_type",
    "skip_steps_multiplier",
    "skip_steps_start_step_perc",
    "settings_version",
    "prompt_enhancer",
    "spatial_upsampling",
    "film_grain_intensity",
    "film_grain_saturation",
    "progressive_pipeline",
    "single_stage_pipeline",
    "reference_pipeline",
    "progressive_stage1_image_weight",
    "progressive_stage2_steps",
    "progressive_stage2_sigma",
    "progressive_stage3_steps",
    "progressive_stage3_sigma",
    "progressive_stage3_image_weight",
    "override_profile",
    "override_attention",
    "temperature",
    "top_p",
    "top_k",
    "self_refiner_setting",
    "self_refiner_plan",
    "self_refiner_f_uncertainty",
    "self_refiner_certain_percentage",
    "cfg_rescale",
    "modality_scale",
    "use_gradient_estimation",
    "ge_gamma",
    "ge_alpha",
    "outpaint_lora_strength",
    "outpaint_mask_preserve",
    "outpaint_official_stack",
    "custom_settings",
    "wangp_processor_settings",
)


class StudioImageSpecError(ImageGenerationSpecError):
    """Named alias for callers that distinguish the Studio v2 contract."""


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


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
_InactiveText = Literal["", None]
_NonBlankShortText = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=8192),
]
_ReferenceText = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=_MAX_REFERENCE_LENGTH),
]
_OptionalReferenceText = Annotated[
    StrictStr,
    StringConstraints(max_length=_MAX_REFERENCE_LENGTH),
]
_Steps = Annotated[StrictInt, Field(ge=1, le=1000)]
_Seed = Annotated[StrictInt, Field(ge=-(2**63), le=2**63 - 1)]
_Count = Annotated[StrictInt, Field(ge=1, le=100)]
_PhaseCount = Annotated[StrictInt, Field(ge=1, le=16)]
_NonNegativeInt = Annotated[StrictInt, Field(ge=0, le=100_000)]
_Finite = Annotated[StrictFloat, Field(allow_inf_nan=False)]
_Unit = Annotated[StrictFloat, Field(ge=0, le=1, allow_inf_nan=False)]
_Percent = Annotated[StrictFloat, Field(ge=0, le=100, allow_inf_nan=False)]
_ImageSelector = Annotated[StrictInt, Field(ge=1, le=1)]


_ASSET_ID = re.compile(r"^asset(?:[_:-])[A-Za-z0-9][A-Za-z0-9._:-]{0,238}$")
_WORKSPACE_QUERY = re.compile(r"^(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)$")


def _asset_id(value: str) -> bool:
    return bool(_ASSET_ID.fullmatch(value))


def _safe_local_path(path: str) -> bool:
    decoded = unquote(path)
    if not decoded or "\\" in decoded or "\x00" in decoded:
        return False
    parts = decoded.split("/")
    return all(part not in {"", ".", ".."} for part in parts)


def _validate_reference(value: str) -> str:
    """Accept exact asset IDs and canonical local API references only."""
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("reference must be a non-blank string")
    # Asset catalog IDs are opaque identifiers, never filesystem paths.  Keep
    # their spelling exactly as supplied for the original/effective snapshot.
    if _asset_id(value):
        return value
    if "\\" in value or "\x00" in value:
        raise ValueError("reference must be a canonical local asset URL or asset ID")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError("reference must use a canonical local URL")
    _validate_reference_url(parsed)
    return value


def _validate_reference_url(parsed):
    """Check each canonical URL family's path and source-workspace contract."""
    path = parsed.path
    if path.startswith("/api/v1/uploads/"):
        if parsed.query or not _safe_local_path(path[len("/api/v1/uploads/"):]):
            raise ValueError("upload reference must be a canonical local URL")
        return
    if path.startswith("/api/v1/file/"):
        if not _safe_local_path(path[len("/api/v1/file/"):]):
            raise ValueError("file reference must identify a safe local asset")
        query = parse_qs(parsed.query, keep_blank_values=True)
        if set(query) != {"workspace"} or len(query["workspace"]) != 1:
            raise ValueError("file references require one workspace query value")
        if not _WORKSPACE_QUERY.fullmatch(query["workspace"][0]):
            raise ValueError("file reference workspace is invalid")
        return
    if path.startswith("/api/v1/assets/"):
        if parsed.query or not _asset_id(unquote(path[len("/api/v1/assets/"):])):
            raise ValueError("asset URL must identify one exact asset ID")
        return
    raise ValueError("reference must be a canonical local asset URL or asset ID")


def _validate_optional_reference(value: str) -> str:
    # Restore paths use an empty string sentinel when no start/end image was
    # attached.  It is distinct from a user-selected reference and is kept
    # exactly in the frozen native map.
    if value == "":
        return value
    return _validate_reference(value)


# Pydantic does not apply a field validator to an Annotated scalar alias in all
# supported 2.x releases.  A tiny custom type would make JSON schema opaque, so
# the models below use this helper through field validators instead.
ImageReference = _ReferenceText
ImageReferenceList = list[ImageReference]
ImageReferenceOrList = Union[_OptionalReferenceText, ImageReferenceList]


class WangpProcessorSettings(_ClosedModel):
    """Typed settings currently declared by image-capable processors."""

    spatial_upsampler_strength: _Finite | None = None
    spatial_upsampler_face_count: Annotated[StrictInt, Field(ge=0, le=5)] | None = None
    spatial_upsampler_h3_strength: _Unit | None = None
    spatial_upsampler_prompt: _Text | None = None
    spatial_upsampler_reference_images: ImageReferenceList | None = Field(default_factory=list, max_length=_MAX_REFERENCE_COUNT)
    spatial_upsampler_dlss_strength: Annotated[StrictFloat, Field(ge=0, le=2, allow_inf_nan=False)] | None = None

    @field_validator("spatial_upsampler_reference_images")
    @classmethod
    def _check_reference_images(cls, values):
        if values is None:
            return values
        return [_validate_reference(value) for value in values]


class StudioImageCustomSettings(_ClosedModel):
    """Known model-specific image settings, with no untyped JSON map."""

    # SenseNova image generation.
    sensenova_kv_cache: Literal["Disabled", "Enabled"] | None = None
    # HiDream accepts these values internally even though current UI versions
    # do not expose controls for them.  Keeping them typed prevents a model
    # setting from becoming a free-form provider payload.
    noise_scale_start: _Finite | None = None
    noise_scale_end: _Finite | None = None
    noise_clip_std: _Finite | None = None


class StudioImageParams(_ClosedModel):
    """The closed native parameter family for one Studio image job."""

    prompt: _Prompt
    alt_prompt: _Text = ""
    model_type: _Identity
    resolution: _NonBlankShortText
    video_length: _ImageSelector = 1
    num_inference_steps: _Steps
    guidance_scale: _Finite
    seed: _Seed
    image_mode: _ImageSelector = 1
    generation_mode: Literal["image"] = "image"
    negative_prompt: _Text = ""
    repeat_generation: _Count = 1
    batch_size: _Count = 1
    activated_loras: list[_NonBlankShortText] = Field(default_factory=list, max_length=64)
    loras_multipliers: _ShortText = ""

    # Image conditioning.  Resource resolution happens after this snapshot.
    image_start: ImageReferenceOrList | None = None
    image_end: ImageReferenceOrList | None = None
    image_refs: ImageReferenceList | None = Field(default_factory=list, max_length=_MAX_REFERENCE_COUNT)
    image_guide: ImageReferenceOrList | None = None
    image_mask: ImageReferenceOrList | None = None
    image_prompt_type: _ShortText = ""
    video_prompt_type: _ShortText = ""
    frames_positions: _ShortText = ""
    canonical_image_refs: StrictBool = False

    # Image/edit model controls.
    multi_prompts_gen_type: _NonNegativeInt = 2
    image_fit_mode: Literal["", "contain", "source", "crop"] = ""
    input_video_strength: _Finite | None = None
    denoising_strength: _Finite | None = None
    masking_strength: _Finite | None = None
    video_guide_outpainting: _NonBlankShortText = ""
    control_net_weight: _Finite | None = None
    control_net_weight2: _Finite | None = None
    control_net_weight_alt: _Finite | None = None
    motion_amplitude: _Finite | None = None
    mask_expand: _Finite | None = None
    image_refs_relative_size: _Finite | None = None
    remove_background_images_ref: Annotated[StrictInt, Field(ge=0, le=1)] = 0
    model_mode: _NonNegativeInt | None = 0

    # Studio keeps a few video/audio controls in the shared working set even
    # while image mode is active.  Their only valid image-mode values are the
    # inactive sentinels; retaining those values avoids dropping a complete
    # browser snapshot while an active video/audio request fails closed.
    temporal_upsampling: _InactiveText = ""
    audio_prompt_type: _InactiveText = ""
    video_guide: _InactiveText = None
    video_mask: _InactiveText = None
    video_source: _InactiveText = None
    audio_guide: _InactiveText = None
    audio_guide2: _InactiveText = None
    audio_guide3: _InactiveText = None
    audio_guide4: _InactiveText = None
    audio_guide5: _InactiveText = None
    audio_guide6: _InactiveText = None
    audio_source: _InactiveText = None
    MMAudio_setting: Annotated[StrictInt, Field(ge=0, le=0)] | None = None
    MMAudio_prompt: _InactiveText = None
    MMAudio_neg_prompt: _InactiveText = None
    h3_ref_videos: ImageReferenceList | None = None
    h3_ref_audios: ImageReferenceList | None = None
    # H3's full manifest is a separate video command.  Empty lists are
    # retained here because output restore currently seeds them for every
    # generation mode; non-empty references fail closed as an incompatible
    # mode.
    minimax_h3_references: ImageReferenceList | None = None
    minimax_h3_turbo_mode: Annotated[StrictBool, Field(json_schema_extra={"const": False})] | None = None
    sliding_window_size: _NonNegativeInt | None = None
    sliding_window_overlap: _NonNegativeInt | None = None
    sliding_window_memory_override: StrictBool | None = None
    sliding_window_discard_last_frames: _NonNegativeInt | None = None
    sliding_window_color_correction_strength: _Finite | None = None
    sliding_window_overlap_noise: _Finite | None = None
    keep_frames_video_source: _InactiveText = None
    keep_frames_video_guide: _InactiveText = None
    force_fps: _InactiveText = ""

    # Sampling/model controls shared by image families.
    flow_shift: _Finite | None = None
    sample_solver: _ShortText = ""
    embedded_guidance_scale: _Finite | None = None
    guidance2_scale: _Finite | None = None
    guidance3_scale: _Finite | None = None
    switch_threshold: _Finite | None = None
    switch_threshold2: _Finite | None = None
    guidance_phases: _PhaseCount = 1
    model_switch_phase: _PhaseCount = 1
    alt_guidance_scale: _Finite | None = None
    alt_scale: _Finite | None = None
    audio_guidance_scale: _Finite | None = None
    audio_scale: _Finite | None = None
    NAG_scale: _Finite | None = None
    NAG_tau: _Finite | None = None
    NAG_alpha: _Unit | None = None
    RIFLEx_setting: _NonNegativeInt | None = None
    injection_strength: _Finite | None = None
    identity_guidance_scale: _Finite | None = None
    skip_steps_cache_type: Literal["", "first_block"] = ""
    skip_steps_multiplier: _Finite | None = None
    skip_steps_start_step_perc: _Percent | None = None
    settings_version: _Finite | None = None
    prompt_enhancer: _ShortText = ""

    # Post-processing and native staged image options.
    spatial_upsampling: _ShortText = ""
    film_grain_intensity: _Unit | None = None
    film_grain_saturation: _Unit | None = None
    progressive_pipeline: StrictBool = False
    single_stage_pipeline: StrictBool = False
    reference_pipeline: StrictBool = False
    progressive_stage1_image_weight: _Finite | None = None
    progressive_stage2_steps: _NonNegativeInt | None = None
    progressive_stage2_sigma: _Finite | None = None
    progressive_stage3_steps: _NonNegativeInt | None = None
    progressive_stage3_sigma: _Finite | None = None
    progressive_stage3_image_weight: _Finite | None = None
    override_profile: _Finite | None = None
    override_attention: _ShortText | None = None
    temperature: _Finite | None = None
    top_p: _Finite | None = None
    top_k: _NonNegativeInt | None = None
    self_refiner_setting: _NonNegativeInt | None = None
    self_refiner_plan: _Text | None = None
    self_refiner_f_uncertainty: _Finite | None = None
    self_refiner_certain_percentage: _Unit | None = None
    cfg_rescale: _Finite | None = None
    modality_scale: _Finite | None = None
    use_gradient_estimation: StrictBool | None = None
    ge_gamma: _Finite | None = None
    ge_alpha: _Finite | None = None
    outpaint_lora_strength: _Finite | None = None
    outpaint_mask_preserve: StrictBool | None = None
    outpaint_official_stack: StrictBool | None = None
    custom_settings: StudioImageCustomSettings | None = None
    wangp_processor_settings: WangpProcessorSettings | None = None

    @field_validator("override_profile")
    @classmethod
    def _memory_profile(cls, value):
        if value is not None and value not in (-1, 1, 2, 3, 3.5, 4, 4.5, 5):
            raise ValueError("override_profile must be -1 or a supported memory profile (1, 2, 3, 3.5, 4, 4.5, 5)")
        return value

    @field_validator("minimax_h3_turbo_mode")
    @classmethod
    def _inactive_turbo(cls, value):
        if value is True:
            raise ValueError("minimax_h3_turbo_mode must be inactive in image mode")
        return value

    @field_validator("image_refs")
    @classmethod
    def _check_image_refs(cls, values):
        if values is None:
            return values
        return [_validate_reference(value) for value in values]

    @field_validator("h3_ref_videos", "h3_ref_audios", "minimax_h3_references")
    @classmethod
    def _check_inactive_reference_lists(cls, values):
        if values is None:
            return values
        if values:
            raise ValueError("reference lists must be empty in image mode")
        return values

    @field_validator("image_start", "image_end", "image_guide", "image_mask", mode="after")
    @classmethod
    def _check_single_or_many_reference(cls, value):
        if value is None:
            return value
        values = value if isinstance(value, list) else [value]
        return [_validate_optional_reference(item) for item in values] if isinstance(value, list) else _validate_optional_reference(value)

    @field_validator("activated_loras")
    @classmethod
    def _check_lora_names(cls, values):
        for value in values:
            if not value.strip() or "/" in value or "\\" in value or value in {".", ".."}:
                raise ValueError("activated_loras must contain exact catalog names")
        return values

    @field_validator("resolution")
    @classmethod
    def _check_resolution_shape(cls, value):
        match = re.fullmatch(r"([1-9][0-9]{1,4})x([1-9][0-9]{1,4})", value)
        if not match or any(not 64 <= int(part) <= 4096 or int(part) % 8 for part in match.groups()):
            raise ValueError("resolution must be WIDTHxHEIGHT, each 64..4096 and divisible by 8")
        return value

    @model_validator(mode="after")
    def _check_semantics(self):
        for field in ("prompt", "model_type", "resolution"):
            value = getattr(self, field)
            if not value.strip():
                raise ValueError(f"{field} must contain a non-blank value")
        if self.canonical_image_refs and not self.image_refs:
            raise ValueError("canonical_image_refs requires at least one image_refs entry")
        return self


class StudioImageInput(_ClosedModel):
    workspace: _Workspace
    # Optional collection identity is transport provenance, not a native
    # generation parameter.  The collection registry resolves it later.
    workspace_collection_id: _WorkspaceCollectionId | None = None
    params: StudioImageParams

    @model_validator(mode="after")
    def _check_collection_id(self):
        if self.workspace_collection_id is not None and not self.workspace_collection_id.strip():
            raise ValueError("workspace_collection_id must contain a non-blank value")
        return self


class _StudioImageEnvelope(_ClosedModel):
    version: Literal[SCHEMA_VERSION]
    operation: Literal[OPERATION]
    intent_id: _IntentId
    input: StudioImageInput

    @model_validator(mode="after")
    def _check_intent(self):
        if not self.intent_id.strip():
            raise ValueError("intent_id must contain a non-blank value")
        return self


def _validation_error(exc: ValidationError) -> ImageGenerationSpecError:
    details: list[dict[str, Any]] = []
    messages: list[str] = []
    for error in exc.errors(include_input=False):
        location = ".".join(str(part) for part in error.get("loc", ())) or "command"
        message = str(error.get("msg") or "Invalid value")
        details.append({"loc": location, "message": message, "type": error.get("type")})
        messages.append(f"{location}: {message}")
    return StudioImageSpecError(
        "; ".join(messages) or "Invalid Studio image generation command",
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


def freeze_studio_image_spec(command: Any) -> dict[str, Any]:
    """Validate and detach one complete Studio image command.

    This function is pure.  It does not resolve a model, inspect a file,
    mutate a registry, load settings or enqueue work.  ``original`` retains
    caller spelling/omission exactly; ``effective`` is the native projection
    consumed by the later preflight boundary.
    """
    if type(command) is not dict:
        raise StudioImageSpecError("Studio image generation command must be an object")
    try:
        envelope = _StudioImageEnvelope.model_validate(command)
    except ValidationError as exc:
        raise _validation_error(exc) from exc

    original = deepcopy(command)
    explicit_params = envelope.input.params.model_dump(mode="json", exclude_unset=True)
    effective_params = deepcopy(explicit_params)
    for key, value in STUDIO_IMAGE_DEFAULTS.items():
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
    # Keep an explicit collection ID, including an explicit null, while
    # leaving the field absent when the caller omitted it.
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


def studio_image_schema() -> dict[str, Any]:
    """Return the implemented v2 envelope and its explicit image boundary."""
    input_schema = StudioImageInput.model_json_schema()
    envelope_schema = _StudioImageEnvelope.model_json_schema()
    return {
        "version": SCHEMA_VERSION,
        "operation": OPERATION,
        "intent_id": envelope_schema["properties"]["intent_id"],
        "input": input_schema,
        "supported_input_fields": list(SUPPORTED_INPUT_FIELDS),
        "effects": deepcopy(STUDIO_IMAGE_DEFAULTS),
        "inactive": list(INACTIVE_IMAGE_FIELDS),
        "excluded": [
            "actor",
            "client",
            "permission",
            "provenance",
            "workspace inside input.params",
            *INCOMPATIBLE_IMAGE_FIELDS,
            "free-form JSON settings",
            "filesystem paths",
        ],
    }


# Names used by adapters and discovery code in different slices of the shared
# command work.  They are aliases, not additional contracts.
StudioImageGenerationInput = StudioImageInput
StudioImageGenerationParams = StudioImageParams
image_generation_schema_v2 = studio_image_schema


__all__ = [
    "FINGERPRINT_VERSION",
    "INACTIVE_IMAGE_FIELDS",
    "INCOMPATIBLE_IMAGE_FIELDS",
    "ImageGenerationSpecError",
    "ImageReference",
    "OPERATION",
    "SCHEMA_VERSION",
    "STUDIO_IMAGE_DEFAULTS",
    "SUPPORTED_INPUT_FIELDS",
    "StudioImageCustomSettings",
    "StudioImageGenerationInput",
    "StudioImageGenerationParams",
    "StudioImageInput",
    "StudioImageParams",
    "StudioImageSpecError",
    "WangpProcessorSettings",
    "freeze_studio_image_spec",
    "image_generation_schema_v2",
    "studio_image_schema",
]
