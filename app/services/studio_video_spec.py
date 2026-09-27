"""Studio aliases for the closed ``generation.video`` contract.

The freeze/schema authority lives in :mod:`video_generation_spec`. This module
keeps the Studio naming used by speech/music/SFX adapters.
"""

from services.video_generation_spec import (
    EXCLUDED_VIDEO_FIELDS,
    FINGERPRINT_VERSION,
    INACTIVE_VIDEO_FIELDS,
    OPERATION,
    SCHEMA_VERSION,
    STUDIO_VIDEO_DEFAULTS,
    SUPPORTED_INPUT_FIELDS,
    VIDEO_MODEL_FAMILY,
    VIDEO_MODEL_TYPES,
    WAN_T2V_ARCHITECTURES,
    StudioVideoInput,
    StudioVideoParams,
    VideoGenerationInput,
    VideoGenerationParams,
    VideoGenerationSpecError,
    freeze_studio_video_spec,
    freeze_video_generation_spec,
    studio_video_schema,
    video_generation_schema,
)

STUDIO_VIDEO_OPERATION = OPERATION
STUDIO_VIDEO_SCHEMA_VERSION = SCHEMA_VERSION
StudioVideoSpecError = VideoGenerationSpecError
StudioVideoGenerationInput = StudioVideoInput
StudioVideoGenerationParams = StudioVideoParams


__all__ = [
    "EXCLUDED_VIDEO_FIELDS",
    "FINGERPRINT_VERSION",
    "INACTIVE_VIDEO_FIELDS",
    "OPERATION",
    "SCHEMA_VERSION",
    "STUDIO_VIDEO_DEFAULTS",
    "STUDIO_VIDEO_OPERATION",
    "STUDIO_VIDEO_SCHEMA_VERSION",
    "SUPPORTED_INPUT_FIELDS",
    "VIDEO_MODEL_FAMILY",
    "VIDEO_MODEL_TYPES",
    "WAN_T2V_ARCHITECTURES",
    "StudioVideoGenerationInput",
    "StudioVideoGenerationParams",
    "StudioVideoInput",
    "StudioVideoParams",
    "StudioVideoSpecError",
    "VideoGenerationInput",
    "VideoGenerationParams",
    "VideoGenerationSpecError",
    "freeze_studio_video_spec",
    "freeze_video_generation_spec",
    "studio_video_schema",
    "video_generation_schema",
]
