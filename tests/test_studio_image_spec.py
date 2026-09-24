"""Pure contract tests for the complete Studio image command (v2)."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from services.studio_image_spec import (
    FINGERPRINT_VERSION,
    INCOMPATIBLE_IMAGE_FIELDS,
    OPERATION,
    SCHEMA_VERSION,
    StudioImageSpecError,
    freeze_studio_image_spec,
    studio_image_schema,
)
from services.image_generation_spec import ImageGenerationSpecError


def command(*, intent_id="studio-image-1", **param_overrides):
    params = {
        "prompt": '  Keep this literal: "mañana"\nline two  ',
        "model_type": "pi_flux2",
        "resolution": "512x512",
        "num_inference_steps": 4,
        "guidance_scale": 1.0,
        "seed": -1,
    }
    params.update(param_overrides)
    return {
        "version": 2,
        "operation": OPERATION,
        "intent_id": intent_id,
        "input": {"workspace": "workspace_with_underscores", "params": params},
    }


@pytest.mark.parametrize("profile", [-1, 1, 2, 3, 3.5, 4, 4.5, 5, None])
def test_native_numeric_memory_profiles_are_preserved(profile):
    frozen = freeze_studio_image_spec(command(override_profile=profile))
    assert frozen["original"]["input"]["params"]["override_profile"] == profile


@pytest.mark.parametrize("profile", [True, False, "-1", "4.5", 0, 6, 3.2])
def test_invalid_memory_profiles_are_rejected(profile):
    with pytest.raises(StudioImageSpecError, match="override_profile"):
        freeze_studio_image_spec(command(override_profile=profile))


def test_v2_error_keeps_v1_error_compatibility_for_shared_adapters():
    assert issubclass(StudioImageSpecError, ImageGenerationSpecError)


def test_intercepted_native_ui_payload_keeps_all_image_fields_after_envelope_adaptation():
    native = json.loads((Path(__file__).parent / "fixtures/studio_image_native_request.json").read_text())
    workspace = native.pop("workspace")
    attribution = native.pop("provenance")
    request = {"version": 2, "operation": OPERATION, "intent_id": attribution["command"]["command_id"],
               "input": {"workspace": workspace, "params": native}}
    frozen = freeze_studio_image_spec(request)
    assert frozen["original"]["input"]["params"] == native
    effective = frozen["effective"]["input"]["params"]
    assert all(effective[key] == value for key, value in native.items())


@pytest.mark.parametrize("value", [True, 0, 1, "false", "", [], {}])
def test_restored_h3_flag_only_accepts_inactive_boolean_or_null(value):
    with pytest.raises(StudioImageSpecError):
        freeze_studio_image_spec(command(minimax_h3_turbo_mode=value))


def test_freezes_full_envelope_without_effects_or_mutations():
    request = command()
    before = deepcopy(request)

    frozen = freeze_studio_image_spec(request)

    assert request == before
    assert frozen["original"] == before
    assert frozen["original"] is not request
    assert frozen["original"]["input"] is not request["input"]
    assert frozen["original"]["input"]["params"] is not request["input"]["params"]
    assert frozen["effective"]["version"] == SCHEMA_VERSION
    assert frozen["effective"]["operation"] == OPERATION
    assert frozen["effective"]["intent_id"] == request["intent_id"]
    assert frozen["effective"]["input"]["workspace"] == request["input"]["workspace"]
    assert frozen["effective"]["input"]["params"]["prompt"] == request["input"]["params"]["prompt"]
    assert frozen["effective"]["input"]["params"]["generation_mode"] == "image"
    assert frozen["effective"]["input"]["params"]["image_mode"] == 1
    assert frozen["effective"]["input"]["params"]["video_length"] == 1
    assert frozen["effective"]["input"]["params"]["multi_prompts_gen_type"] == 2
    assert frozen["effective"]["input"]["params"]["repeat_generation"] == 1
    assert frozen["effective"]["input"]["params"]["batch_size"] == 1
    assert frozen["effective"]["input"]["params"]["prompt_enhancer"] == ""
    assert frozen["effective"]["input"]["params"]["activated_loras"] == []
    assert frozen["effective"]["input"]["params"]["loras_multipliers"] == ""
    assert frozen["effective"]["input"]["params"]["canonical_image_refs"] is False

    request["input"]["params"]["prompt"] = "changed after validation"
    assert frozen["original"]["input"]["params"]["prompt"] == before["input"]["params"]["prompt"]
    assert frozen["effective"]["input"]["params"]["prompt"] == before["input"]["params"]["prompt"]


def test_explicit_native_and_advanced_fields_are_retained_verbatim():
    params = {
        "alt_prompt": "style and composition cues",
        "negative_prompt": " avoid blur  ",
        "generation_mode": "image",
        "image_mode": 1,
        "video_length": 1,
        "repeat_generation": 2,
        "batch_size": 3,
        "activated_loras": ["style-a.safetensors", "character.sft"],
        "loras_multipliers": "1;0.5 0.25",
        "image_refs": ["asset_ref_01", "/api/v1/uploads/reference.png"],
        "image_start": "/api/v1/file/start.png?workspace=default",
        "image_end": ["asset_end_01"],
        "image_guide": "/api/v1/uploads/guide.png",
        "image_mask": "/api/v1/file/mask.png?workspace=workspace_with_underscores",
        "image_prompt_type": "KI",
        "video_prompt_type": "I",
        "frames_positions": "0,12",
        "canonical_image_refs": True,
        "multi_prompts_gen_type": 2,
        "image_fit_mode": "contain",
        "input_video_strength": 0.75,
        "denoising_strength": 0.8,
        "masking_strength": 0.9,
        "video_guide_outpainting": "2",
        "control_net_weight": 0.5,
        "control_net_weight2": 0.25,
        "control_net_weight_alt": 0.125,
        "motion_amplitude": 1.1,
        "mask_expand": 16,
        "image_refs_relative_size": 80,
        "remove_background_images_ref": 0,
        "model_mode": 2,
        "flow_shift": 3,
        "sample_solver": "default",
        "embedded_guidance_scale": 1.2,
        "guidance2_scale": 1.3,
        "guidance3_scale": 1.4,
        "switch_threshold": 0.8,
        "switch_threshold2": 0.75,
        "guidance_phases": 1,
        "model_switch_phase": 1,
        "alt_guidance_scale": 1.5,
        "alt_scale": 0.25,
        "audio_guidance_scale": 0.0,
        "audio_scale": 0.0,
        "injection_strength": 0.7,
        "identity_guidance_scale": 3.0,
        "skip_steps_cache_type": "first_block",
        "skip_steps_multiplier": 0.08,
        "skip_steps_start_step_perc": 25,
        "settings_version": 2.52,
        "prompt_enhancer": "",
        "spatial_upsampling": "lanczos2",
        "film_grain_intensity": 0.2,
        "film_grain_saturation": 0.6,
        "progressive_pipeline": True,
        "single_stage_pipeline": False,
        "reference_pipeline": False,
        "progressive_stage1_image_weight": 0.7,
        "progressive_stage2_steps": 5,
        "progressive_stage2_sigma": 0.85,
        "progressive_stage3_steps": 3,
        "progressive_stage3_sigma": 0.85,
        "progressive_stage3_image_weight": 0.7,
        "custom_settings": {"sensenova_kv_cache": "Enabled", "noise_clip_std": 2.5},
        "wangp_processor_settings": {
            "spatial_upsampler_strength": 0.5,
            "spatial_upsampler_face_count": 0,
            "spatial_upsampler_h3_strength": 0.75,
            "spatial_upsampler_prompt": "restore face detail",
            "spatial_upsampler_reference_images": ["asset_face_01"],
            "spatial_upsampler_dlss_strength": 1.0,
        },
    }

    frozen = freeze_studio_image_spec(command(**params))
    effective = frozen["effective"]["input"]["params"]
    for key, value in params.items():
        assert effective[key] == value, key


def test_omitted_optional_fields_stay_omitted_in_original_and_defaults_are_effective():
    request = command()
    frozen = freeze_studio_image_spec(request)
    original_params = frozen["original"]["input"]["params"]
    effective_params = frozen["effective"]["input"]["params"]

    for field in ("generation_mode", "image_mode", "video_length", "activated_loras", "loras_multipliers", "canonical_image_refs"):
        assert field not in original_params
        assert field in effective_params
    assert "settings_version" not in original_params
    assert "settings_version" not in effective_params


def test_optional_collection_identity_is_preserved_outside_native_params():
    request = command()
    request["input"]["workspace_collection_id"] = "collection-nightwatch"

    frozen = freeze_studio_image_spec(request)

    assert frozen["original"]["input"]["workspace_collection_id"] == "collection-nightwatch"
    assert frozen["effective"]["input"]["workspace_collection_id"] == "collection-nightwatch"
    assert "workspace_collection_id" not in frozen["effective"]["input"]["params"]

    request["input"]["workspace_collection_id"] = "changed-after-freeze"
    assert frozen["effective"]["input"]["workspace_collection_id"] == "collection-nightwatch"

    explicit_null = command()
    explicit_null["input"]["workspace_collection_id"] = None
    null_frozen = freeze_studio_image_spec(explicit_null)
    assert "workspace_collection_id" in null_frozen["effective"]["input"]
    assert null_frozen["effective"]["input"]["workspace_collection_id"] is None

    for value in ("", " \n\t", True, 1, [], {}):
        invalid = command()
        invalid["input"]["workspace_collection_id"] = value
        with pytest.raises(StudioImageSpecError, match="workspace_collection_id"):
            freeze_studio_image_spec(invalid)


@pytest.mark.parametrize("field,value", [
    ("generation_mode", "video"),
    ("image_mode", 0),
    ("image_mode", 2),
    ("video_length", 0),
    ("video_length", 2),
])
def test_image_selectors_cannot_smuggle_another_mode(field, value):
    with pytest.raises(StudioImageSpecError, match=field):
        freeze_studio_image_spec(command(**{field: value}))


@pytest.mark.parametrize("field", ["workspace", "prompt", "model_type", "resolution"])
def test_required_text_fields_reject_blank_and_non_text_values(field):
    for value in ("", " \n\t", None, True, 1, [], {}):
        overrides = {field: value}
        if field == "workspace":
            request = command()
            request["input"]["workspace"] = value
        else:
            request = command(**overrides)
        with pytest.raises(StudioImageSpecError, match=field):
            freeze_studio_image_spec(request)


@pytest.mark.parametrize("field", ["num_inference_steps", "seed"])
@pytest.mark.parametrize("bad", [None, True, False, 1.0, "1", [], {}])
def test_integer_fields_reject_coercion(field, bad):
    with pytest.raises(StudioImageSpecError, match=field):
        freeze_studio_image_spec(command(**{field: bad}))


@pytest.mark.parametrize("field", [
    "guidance_scale", "flow_shift", "denoising_strength", "masking_strength",
    "film_grain_intensity", "film_grain_saturation", "skip_steps_multiplier",
])
@pytest.mark.parametrize("bad", [True, False, "1.0", [], {}, float("nan"), float("inf")])
def test_numeric_fields_reject_non_finite_or_coercible_values(field, bad):
    with pytest.raises(StudioImageSpecError, match=field):
        freeze_studio_image_spec(command(**{field: bad}))


@pytest.mark.parametrize("reference", [
    "/api/v1/uploads/reference.png",
    "/api/v1/file/reference.png?workspace=default",
    "/api/v1/assets/asset_reference_1",
    "asset_reference_1",
])
def test_references_accept_only_canonical_local_forms(reference):
    frozen = freeze_studio_image_spec(command(image_refs=[reference], canonical_image_refs=True))
    assert frozen["effective"]["input"]["params"]["image_refs"] == [reference]


@pytest.mark.parametrize("reference", [
    "reference.png",
    "/tmp/reference.png",
    "C:\\reference.png",
    "../reference.png",
    "/api/v1/file/../reference.png?workspace=default",
    "/api/v1/file/reference.png",
    "/api/v1/file/reference.png?workspace=default&workspace=other",
    "/api/v1/uploads/reference.png?workspace=default",
    "https://example.invalid/reference.png",
    "/api/v1/assets/not-an-asset-id",
])
def test_references_reject_basenames_host_paths_and_ambiguous_urls(reference):
    with pytest.raises(StudioImageSpecError, match="reference|workspace|asset"):
        freeze_studio_image_spec(command(image_refs=[reference]))


def test_canonical_refs_requires_a_nonempty_reference_list():
    with pytest.raises(StudioImageSpecError, match="canonical_image_refs"):
        freeze_studio_image_spec(command(canonical_image_refs=True))


@pytest.mark.parametrize("extra", [
    {"actor": "wizard"},
    {"client": "mcp"},
    {"provenance": {"actor": "wizard"}},
    {"workspace": "default"},
    {"unknown_native_field": 1},
])
def test_extra_params_and_authority_fields_are_rejected(extra):
    request = command()
    request["input"]["params"].update(extra)
    with pytest.raises(StudioImageSpecError, match="extra|Extra|workspace|unknown"):
        freeze_studio_image_spec(request)


@pytest.mark.parametrize("extra", [
    {"actor": "wizard"},
    {"client": "mcp"},
    {"provenance": {"source": "browser"}},
])
def test_extra_envelope_and_input_fields_are_rejected(extra):
    request = command()
    request.update(extra)
    with pytest.raises(StudioImageSpecError, match="extra|Extra|actor|client|provenance"):
        freeze_studio_image_spec(request)

    request = command()
    request["input"].update(extra)
    with pytest.raises(StudioImageSpecError, match="extra|Extra|actor|client|provenance"):
        freeze_studio_image_spec(request)


@pytest.mark.parametrize("field", ["prompt", "model_type", "resolution"])
def test_explicit_null_is_rejected_for_required_fields(field):
    with pytest.raises(StudioImageSpecError, match=field):
        freeze_studio_image_spec(command(**{field: None}))


def test_known_nullable_native_fields_are_preserved_instead_of_dropped():
    request = command(
        image_refs=None,
        image_start=None,
        image_end=None,
        image_guide=None,
        image_mask=None,
        custom_settings=None,
        wangp_processor_settings=None,
        flow_shift=None,
        model_mode=None,
    )
    frozen = freeze_studio_image_spec(request)
    effective = frozen["effective"]["input"]["params"]
    for field in (
        "image_refs", "image_start", "image_end", "image_guide", "image_mask",
        "custom_settings", "wangp_processor_settings", "flow_shift", "model_mode",
    ):
        assert field in effective
        assert effective[field] is None


def test_nested_settings_are_typed_and_closed():
    with pytest.raises(StudioImageSpecError, match="custom_settings"):
        freeze_studio_image_spec(command(custom_settings={"future_setting": 1}))
    with pytest.raises(StudioImageSpecError, match="wangp_processor_settings"):
        freeze_studio_image_spec(command(wangp_processor_settings={"future_setting": 1}))
    with pytest.raises(StudioImageSpecError, match="spatial_upsampler_face_count"):
        freeze_studio_image_spec(command(wangp_processor_settings={"spatial_upsampler_face_count": 1.5}))
    with pytest.raises(StudioImageSpecError, match="sensenova_kv_cache"):
        freeze_studio_image_spec(command(custom_settings={"sensenova_kv_cache": True}))


def test_lora_names_are_exact_catalog_names_without_paths():
    frozen = freeze_studio_image_spec(command(activated_loras=["style.safetensors"]))
    assert frozen["effective"]["input"]["params"]["activated_loras"] == ["style.safetensors"]
    for value in ("../style.safetensors", "/tmp/style.safetensors", "", " "):
        with pytest.raises(StudioImageSpecError, match="activated_loras"):
            freeze_studio_image_spec(command(activated_loras=[value]))


def test_fingerprint_excludes_intent_but_covers_workspace_and_every_effective_param():
    first = freeze_studio_image_spec(command(intent_id="one", settings_version=2.52))
    second = freeze_studio_image_spec(command(intent_id="two", settings_version=2.52))
    changed = freeze_studio_image_spec(command(intent_id="three", settings_version=2.53))

    assert first["fingerprint_version"] == FINGERPRINT_VERSION == 2
    assert first["fingerprint"] == second["fingerprint"]
    assert first["fingerprint"] != changed["fingerprint"]
    assert len(first["fingerprint"]) == 64
    content = {
        "version": 2,
        "operation": OPERATION,
        "input": first["effective"]["input"],
    }
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert encoded

    other_workspace = command()
    other_workspace["input"]["workspace"] = "another_workspace"
    assert first["fingerprint"] != freeze_studio_image_spec(other_workspace)["fingerprint"]

    collection = command(intent_id="one")
    collection["input"]["workspace_collection_id"] = "collection-a"
    other_collection = command(intent_id="two")
    other_collection["input"]["workspace_collection_id"] = "collection-b"
    assert freeze_studio_image_spec(collection)["fingerprint"] != freeze_studio_image_spec(other_collection)["fingerprint"]


def test_schema_is_closed_and_documents_incompatible_native_families():
    schema = studio_image_schema()
    assert schema["version"] == 2
    assert schema["operation"] == OPERATION
    assert schema["input"]["additionalProperties"] is False
    params_schema = schema["input"]["$defs"]["StudioImageParams"]
    assert params_schema["additionalProperties"] is False
    assert set(schema["supported_input_fields"]) == set(params_schema["properties"]) | {"workspace", "workspace_collection_id"}
    assert "settings_version" in schema["supported_input_fields"]
    assert "generation_mode" in schema["supported_input_fields"]
    assert "canonical_image_refs" in schema["supported_input_fields"]
    assert "video_source" in schema["inactive"]
    assert "audio_guide" in schema["inactive"]
    assert set(INCOMPATIBLE_IMAGE_FIELDS).issubset(schema["excluded"])
    assert schema["effects"]["generation_mode"] == "image"
    assert schema["effects"]["image_mode"] == 1
    assert schema["effects"]["video_length"] == 1


def test_invalid_envelope_shapes_are_reported_as_contract_errors():
    for value in (None, [], "text", 2, True):
        with pytest.raises(StudioImageSpecError):
            freeze_studio_image_spec(value)
    for field, value in (("version", 1), ("operation", "generation.video"), ("intent_id", ""), ("input", None)):
        request = command()
        request[field] = value
        with pytest.raises(StudioImageSpecError, match=field):
            freeze_studio_image_spec(request)


def test_restored_mode_inactive_sentinels_are_retained_but_nonempty_values_fail():
    frozen = freeze_studio_image_spec(command(
        minimax_h3_turbo_mode=False,
        image_start="",
        image_end="",
        image_guide="",
        image_mask="",
        audio_guide="",
        audio_guide2=None,
        video_guide="",
        video_mask=None,
        video_source="",
        temporal_upsampling="",
        audio_prompt_type="",
        force_fps="",
        sliding_window_size=129,
        sliding_window_overlap=9,
        sliding_window_memory_override=False,
        sliding_window_discard_last_frames=0,
        h3_ref_videos=[],
        h3_ref_audios=None,
        minimax_h3_references=[],
        MMAudio_setting=0,
        MMAudio_prompt="",
        MMAudio_neg_prompt=None,
    ))
    effective = frozen["effective"]["input"]["params"]
    assert effective["minimax_h3_turbo_mode"] is False
    assert effective["audio_guide"] == ""
    assert effective["image_start"] == ""
    assert effective["image_end"] == ""
    assert effective["image_guide"] == ""
    assert effective["image_mask"] == ""
    assert effective["audio_guide2"] is None
    assert effective["sliding_window_size"] == 129
    assert effective["sliding_window_overlap"] == 9
    assert effective["h3_ref_videos"] == []
    assert effective["MMAudio_setting"] == 0
    for field, value in (
        ("MMAudio_setting", 1),
        ("audio_guide", "/api/v1/uploads/voice.wav"),
        ("video_guide", "/api/v1/uploads/guide.mp4"),
        ("video_source", "/api/v1/uploads/source.mp4"),
        ("temporal_upsampling", "dlssg*2"),
        ("audio_prompt_type", "A"),
        ("keep_frames_video_source", "0,12"),
        ("force_fps", "control"),
    ):
        with pytest.raises(StudioImageSpecError, match=field):
            freeze_studio_image_spec(command(**{field: value}))

    for field in ("h3_ref_videos", "h3_ref_audios", "minimax_h3_references"):
        with pytest.raises(StudioImageSpecError, match=field):
            freeze_studio_image_spec(command(**{field: ["/api/v1/uploads/reference.png"]}))


@pytest.mark.parametrize("field", [
    "h3_ref_image_size", "h3_reference_mode", "h3_model_profile", "stage2_steps",
    "perturbation_switch", "stg_scale", "keyframe_conditioning_mode",
    "h3_window_plan", "preserve_source_style",
    "duration_seconds", "voice_reference",
])
def test_active_non_image_native_fields_are_explicitly_rejected(field):
    with pytest.raises(StudioImageSpecError, match=field):
        freeze_studio_image_spec(command(**{field: 1}))
