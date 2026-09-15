"""Provider-free tests for the closed generation.video envelope."""

from copy import deepcopy
import hashlib
import json

import pytest

from services.studio_video_spec import freeze_studio_video_spec, studio_video_schema
from services.video_generation_spec import (
    STUDIO_VIDEO_DEFAULTS,
    VIDEO_MODEL_TYPES,
    VideoGenerationSpecError,
    freeze_video_generation_spec,
    video_generation_schema,
)


def command(intent="video-intent", **params):
    native = {
        "model_type": "t2v_1.3B",
        "prompt": '  A lantern over wet cobblestones.\n"Mañana"  ',
        "resolution": "832x480",
        "video_length": 81,
        "num_inference_steps": 30,
        "guidance_scale": 5.0,
        "seed": 42,
        "negative_prompt": " blur, text ",
    }
    native.update(params)
    return {
        "version": 2,
        "operation": "generation.video",
        "intent_id": intent,
        "input": {"workspace": "video-test", "params": native},
    }


def test_freeze_preserves_literal_prompt_and_detaches_input():
    submitted = command()
    before = deepcopy(submitted)
    frozen = freeze_video_generation_spec(submitted)

    assert submitted == before
    assert frozen["original"] == before
    assert frozen["original"] is not submitted
    assert frozen["original"]["input"]["params"]["prompt"] == before["input"]["params"]["prompt"]
    assert frozen["effective"]["input"]["params"]["prompt"] == before["input"]["params"]["prompt"]
    assert freeze_studio_video_spec(submitted)["fingerprint"] == frozen["fingerprint"]

    submitted["input"]["params"]["prompt"] = "changed"
    assert frozen["original"]["input"]["params"]["prompt"] == before["input"]["params"]["prompt"]


def test_effective_defaults_are_video_selectors_and_omissions_survive():
    submitted = command()
    omitted = (
        "generation_mode", "image_mode", "repeat_generation", "batch_size",
        "prompt_enhancer", "activated_loras", "loras_multipliers", "seed",
        "video_prompt_type", "image_prompt_type", "multi_prompts_gen_type",
    )
    for key in omitted:
        submitted["input"]["params"].pop(key, None)
    frozen = freeze_video_generation_spec(submitted)
    effective = frozen["effective"]["input"]["params"]
    assert "generation_mode" not in submitted["input"]["params"]
    for key in omitted:
        assert effective[key] == STUDIO_VIDEO_DEFAULTS[key]
    assert effective["negative_prompt"] == submitted["input"]["params"]["negative_prompt"]


def test_fingerprint_excludes_intent_and_covers_workspace_and_native_content():
    first = freeze_video_generation_spec(command("one"))
    second = freeze_video_generation_spec(command("two"))
    assert first["fingerprint"] == second["fingerprint"]
    changed = command("three")
    changed["input"]["params"]["prompt"] += " changed"
    assert freeze_video_generation_spec(changed)["fingerprint"] != first["fingerprint"]
    other = command("four")
    other["input"]["workspace"] = "another-workspace"
    assert freeze_video_generation_spec(other)["fingerprint"] != first["fingerprint"]


def test_fingerprint_is_canonical_sha256():
    frozen = freeze_video_generation_spec(command())
    content = {"version": 2, "operation": "generation.video", "input": frozen["effective"]["input"]}
    expected = hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    assert frozen["fingerprint"] == expected
    assert frozen["fingerprint_version"] == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("generation_mode", "image"),
        ("generation_mode", "audio"),
        ("image_mode", 1),
        ("video_length", 1),
        ("video_length", 0),
        ("model_type", "pi_flux2"),
        ("model_type", "t2v_2_2"),
        ("model_type", "minimax_h3"),
        ("prompt_enhancer", "cinematic"),
        ("repeat_generation", 2),
        ("multi_prompts_gen_type", 0),
        ("multi_prompts_gen_type", 3),
    ],
)
def test_closed_video_surface_rejects_other_families_and_modes(field, value):
    with pytest.raises(VideoGenerationSpecError):
        freeze_video_generation_spec(command(**{field: value}))


@pytest.mark.parametrize(
    "value",
    [
        "/etc/passwd",
        "../frame.png",
        "C:\\frame.png",
        "https://example.test/frame.png",
        "/api/v1/file/frame.png",
        "/api/v1/file/../frame.png?workspace=video-test",
        "/api/v1/uploads/frame.png?workspace=other",
    ],
)
def test_image_start_must_be_canonical(value):
    with pytest.raises(VideoGenerationSpecError):
        freeze_video_generation_spec(command(image_start=value))


def test_canonical_image_start_and_collection_are_retained():
    submitted = command()
    submitted["input"]["workspace_collection_id"] = "collection-a"
    submitted["input"]["params"]["image_start"] = "/api/v1/file/frame.png?workspace=source"
    frozen = freeze_video_generation_spec(submitted)
    assert frozen["effective"]["input"]["workspace_collection_id"] == "collection-a"
    assert frozen["effective"]["input"]["params"]["image_start"] == submitted["input"]["params"]["image_start"]


def test_schema_announces_wan_t2v_family_only():
    schema = video_generation_schema()
    assert schema == studio_video_schema()
    assert schema["operation"] == "generation.video"
    assert schema["video_model_family"] == "wan_t2v_2_1"
    assert schema["video_model_types"] == sorted(VIDEO_MODEL_TYPES)
    assert "t2v_2_2" not in schema["video_model_types"]
    assert "minimax_h3" not in schema["video_model_types"]


@pytest.mark.parametrize("invalid", [None, [], "command", 2])
def test_command_must_be_an_object(invalid):
    with pytest.raises(VideoGenerationSpecError):
        freeze_video_generation_spec(invalid)


def test_image_spec_still_rejects_generation_video_operation():
    from services.image_generation_spec import ImageGenerationSpecError, freeze_image_generation_spec

    with pytest.raises(ImageGenerationSpecError, match="operation"):
        freeze_image_generation_spec({
            "version": 1,
            "operation": "generation.video",
            "intent_id": "keep-image-spec",
            "input": {
                "workspace": "workspace-a",
                "model_type": "pi_flux2",
                "prompt": "still an image command",
                "resolution": "512x512",
                "num_inference_steps": 1,
                "seed": -1,
                "guidance_scale": 1.0,
            },
        })
