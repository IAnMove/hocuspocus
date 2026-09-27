"""Provider-free tests for the closed Studio music command."""

from copy import deepcopy
import hashlib
import json

import pytest

from services.studio_music_spec import (
    STUDIO_MUSIC_DEFAULTS,
    SUPPORTED_INPUT_FIELDS,
    StudioMusicSpecError,
    freeze_studio_music_spec,
    studio_music_schema,
)


def music_command(intent="music-intent"):
    return {
        "version": 2,
        "operation": "generation.music",
        "intent_id": intent,
        "input": {
            "workspace": "music-test",
            "workspace_collection_id": "collection-a",
            "params": {
                "model_type": "ace_step_v1_5_xl_sft_lm_4b",
                "prompt": "  [Verse]\nA literal line\n  ",
                "alt_prompt": "  warm acoustic pop\nwith brushed drums  ",
                "_music_description": "  the description remains literal  ",
                "_music_instrumental": False,
                "duration_seconds": 20,
                "seed": 42,
                "num_inference_steps": 8,
                "guidance_scale": 1.0,
                "resolution": "1280x720",
                "generation_mode": "audio",
                "image_mode": 0,
                "video_length": 0,
                "_audio_sub_mode": "music",
            },
        },
    }


def test_freeze_preserves_literal_music_text_and_detaches_input():
    command = music_command()
    command["input"]["params"]["lyrics_language"] = "es-MX"
    before = deepcopy(command)
    frozen = freeze_studio_music_spec(command)

    assert command == before
    assert frozen["original"] == before
    assert frozen["original"] is not command
    assert frozen["original"]["input"]["params"]["prompt"] == before["input"]["params"]["prompt"]
    assert frozen["effective"]["input"]["params"]["prompt"] == before["input"]["params"]["prompt"]
    assert frozen["effective"]["input"]["params"]["alt_prompt"] == before["input"]["params"]["alt_prompt"]
    assert frozen["effective"]["input"]["params"]["_music_description"] == before["input"]["params"]["_music_description"]
    assert frozen["effective"]["input"]["params"]["lyrics_language"] == "es-MX"
    assert frozen["effective"]["input"]["workspace_collection_id"] == "collection-a"

    command["input"]["params"]["prompt"] = "changed"
    assert frozen["original"]["input"]["params"]["prompt"] == before["input"]["params"]["prompt"]


def test_effective_defaults_are_audio_only_and_omitted_bookkeeping_is_literal():
    command = music_command()
    params = command["input"]["params"]
    for key in (
        "generation_mode",
        "_audio_sub_mode",
        "video_length",
        "image_mode",
        "multi_prompts_gen_type",
        "negative_prompt",
        "repeat_generation",
        "batch_size",
        "activated_loras",
        "loras_multipliers",
        "prompt_enhancer",
        "_music_description",
        "_music_instrumental",
    ):
        params.pop(key, None)
    frozen = freeze_studio_music_spec(command)
    effective = frozen["effective"]["input"]["params"]

    for key, value in STUDIO_MUSIC_DEFAULTS.items():
        assert effective[key] == value
    assert effective["_tts_original_prompt"] == params["prompt"]
    assert "_tts_original_prompt" not in params


def test_instrumental_marker_remains_literal_and_is_not_rewritten():
    command = music_command()
    command["input"]["params"].update({"prompt": "  [Instrumental]\n  ", "_music_instrumental": True})

    frozen = freeze_studio_music_spec(command)

    assert frozen["original"]["input"]["params"]["prompt"] == "  [Instrumental]\n  "
    assert frozen["effective"]["input"]["params"]["prompt"] == "  [Instrumental]\n  "
    assert frozen["effective"]["input"]["params"]["_music_instrumental"] is True
    assert frozen["effective"]["input"]["params"]["alt_prompt"] == command["input"]["params"]["alt_prompt"]


def test_empty_or_omitted_alt_prompt_is_admitted():
    blank = music_command()
    blank["input"]["params"]["alt_prompt"] = ""
    frozen_blank = freeze_studio_music_spec(blank)
    assert frozen_blank["effective"]["input"]["params"]["alt_prompt"] == ""

    omitted = music_command()
    omitted["input"]["params"].pop("alt_prompt")
    frozen_omitted = freeze_studio_music_spec(omitted)
    assert "alt_prompt" not in frozen_omitted["original"]["input"]["params"]
    assert frozen_omitted["effective"]["input"]["params"].get("alt_prompt", "") == ""


def test_fingerprint_excludes_intent_but_covers_workspace_collection_and_content():
    first = freeze_studio_music_spec(music_command("first"))
    second = freeze_studio_music_spec(music_command("second"))
    assert first["fingerprint"] == second["fingerprint"]

    changed_collection = music_command("third")
    changed_collection["input"]["workspace_collection_id"] = "collection-b"
    assert freeze_studio_music_spec(changed_collection)["fingerprint"] != first["fingerprint"]

    changed_prompt = music_command("fourth")
    changed_prompt["input"]["params"]["prompt"] += " added"
    assert freeze_studio_music_spec(changed_prompt)["fingerprint"] != first["fingerprint"]


def test_fingerprint_uses_canonical_json_without_transport_identity():
    frozen = freeze_studio_music_spec(music_command())
    content = {
        "version": 2,
        "operation": "generation.music",
        "input": frozen["effective"]["input"],
    }
    expected = hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    assert frozen["fingerprint"] == expected
    assert len(frozen["fingerprint"]) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("generation_mode", "image"),
        ("_audio_sub_mode", "speech"),
        ("image_mode", 1),
        ("video_length", 1),
        ("multi_prompts_gen_type", 1),
        ("_tts_speaker_name1", "Alice"),
        ("_tts_voice_count", 1),
        ("negative_prompt", "avoid drums"),
        ("prompt_enhancer", "rewrite this"),
        ("audio_prompt_type", "N"),
    ],
)
def test_music_rejects_active_other_mode_fields(field, value):
    command = music_command()
    command["input"]["params"][field] = value
    with pytest.raises(StudioMusicSpecError):
        freeze_studio_music_spec(command)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("num_inference_steps", True),
        ("num_inference_steps", 1.0),
        ("seed", 1.5),
        ("guidance_scale", True),
        ("duration_seconds", "20"),
        ("duration_seconds", float("nan")),
        ("_music_instrumental", 1),
        ("_tts_voice_count", True),
        ("custom_settings", {"unknown": 1}),
    ],
)
def test_music_native_scalars_and_nested_fields_are_strict(field, value):
    command = music_command()
    command["input"]["params"][field] = value
    with pytest.raises(StudioMusicSpecError):
        freeze_studio_music_spec(command)


@pytest.mark.parametrize(
    "value",
    [
        "/etc/music.wav",
        "../music.wav",
        "C:\\music.wav",
        "https://example.test/music.wav",
        "/api/v1/file/music.wav",
        "/api/v1/file/../music.wav?workspace=music-test",
        "/api/v1/uploads/music.wav?workspace=other",
    ],
)
def test_music_references_must_be_canonical(value):
    command = music_command()
    command["input"]["params"].update({"audio_prompt_type": "A", "audio_guide": value})
    with pytest.raises(StudioMusicSpecError):
        freeze_studio_music_spec(command)


@pytest.mark.parametrize("value", ["", None, "asset_abc123", "/api/v1/uploads/music.wav"])
def test_music_reference_sentinels_and_asset_urls_are_retained(value):
    command = music_command()
    command["input"]["params"].update({"audio_prompt_type": "", "audio_guide": value})
    frozen = freeze_studio_music_spec(command)
    assert frozen["effective"]["input"]["params"]["audio_guide"] == value


def test_music_models_are_explicit_and_remote_ids_do_not_enter_local_command():
    for model in ("music-3.0", "minimax_music3_gguf", "unknown"):
        command = music_command()
        command["input"]["params"]["model_type"] = model
        with pytest.raises(StudioMusicSpecError):
            freeze_studio_music_spec(command)


def test_schema_is_closed_and_exposes_only_local_models():
    schema = studio_music_schema()
    assert schema["version"] == 2
    assert schema["operation"] == "generation.music"
    params = schema["input"]["$defs"]["StudioMusicParams"]
    assert params["additionalProperties"] is False
    assert "_music_description" in params["properties"]
    assert schema["music_model_types"] == ["ace_step_v1_5_xl_sft_lm_4b", "minimax_music3", "yue2"]
    assert "provenance" in schema["excluded"]


def test_supported_input_fields_identify_every_closed_native_property_once():
    schema = studio_music_schema()
    properties = tuple(schema["input"]["$defs"]["StudioMusicParams"]["properties"])
    supported = tuple(SUPPORTED_INPUT_FIELDS)

    assert set(supported) == set(properties)
    assert len(supported) == len(set(supported))
    assert set(schema["supported_input_fields"]) == set(properties)
    assert "lyrics_language" in properties


@pytest.mark.parametrize("caption", ["", "  ", None])
def test_music3_still_requires_caption_before_admission(caption):
    command = music_command()
    command["input"]["params"]["model_type"] = "minimax_music3"
    if caption is None:
        command["input"]["params"].pop("alt_prompt")
    else:
        command["input"]["params"]["alt_prompt"] = caption
    with pytest.raises(StudioMusicSpecError, match="alt_prompt"):
        freeze_studio_music_spec(command)
