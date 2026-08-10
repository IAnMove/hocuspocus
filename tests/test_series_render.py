import copy

import pytest

from services.series_render import (
    build_h3_generation_params,
    normalize_series_resolution,
    quantize_h3_frames,
    shot_generation_prompt,
)


def inputs(strategy="references"):
    series = {
        "id": "series_a", "sourceMode": "original", "visualStyle": "cinematic",
        "characterVisualStyle": "natural faces", "allowClipText": False,
        "characters": [{"id": "char_a", "name": "Ada"}],
    }
    shot = {
        "id": "shot_a", "durationSeconds": 8, "prompt": "Ada enters", "action": "Ada looks up",
        "framing": "close-up", "camera": "slow push", "negativePrompt": "",
        "dialogueBeats": [{
            "characterId": "char_a", "text": "We are ready.", "emotion": "calm", "delivery": "quiet",
        }],
    }
    manifest = {
        "strategy": strategy,
        "selected": [{
            "assetId": "asset_a", "entityType": "character", "entityId": "char_a",
            "referenceRole": "composed_start_frame" if strategy in {"first_frame", "first_last"} else "primary_speaker_identity", "mediaType": "image",
        }],
    }
    if strategy == "first_last":
        manifest["selected"].append({
            "assetId": "asset_b", "entityType": "continuity", "entityId": "shot_a",
            "referenceRole": "composed_end_frame", "mediaType": "image",
        })
    attempt = {
        "id": "attempt_a", "model": "minimax-h3", "negativePrompt": "artifacts", "seed": 42,
        "referenceManifest": manifest,
        "settings": {"resolution": "720p", "orientation": "portrait", "numInferenceSteps": 20},
    }
    return series, shot, attempt


def test_resolution_and_h3_frame_lattice():
    assert normalize_series_resolution("720p", "portrait") == ("704x1280", "portrait")
    assert normalize_series_resolution("480", "landscape") == ("864x480", "landscape")
    assert (quantize_h3_frames(8, reference_mode=True) - 5) % 17 == 0
    assert quantize_h3_frames(30, reference_mode=True) <= 345


def test_legacy_resolution_tiers_are_distinct_and_idempotent():
    expected = {
        "480p": "864x480",
        "540p": "960x544",
        "720p": "1280x704",
        "768p": "1344x768",
    }
    for preset, canvas in expected.items():
        normalized = normalize_series_resolution(
            preset, "landscape", "minimax_h3_legacy",
        )
        assert normalized == (canvas, "landscape")
        assert normalize_series_resolution(
            canvas, "landscape", "minimax_h3_legacy",
        ) == normalized


def test_prompt_preserves_exact_dialogue_and_text_policy():
    series, shot, _ = inputs()
    prompt = shot_generation_prompt(series, shot)
    assert 'Ada says exactly, "We are ready."' in prompt
    assert "calm emotion" in prompt
    assert "No captions" in prompt


def test_attempt_prompt_and_frame_count_are_frozen_for_exact_replay():
    series, shot, attempt = inputs("direct")
    attempt["prompt"] = "Frozen exact request prompt"
    attempt["settings"]["videoLengthFrames"] = 192
    shot["prompt"] = "Edited after queueing"
    params = build_h3_generation_params(series, shot, attempt, {})
    assert params["prompt"] == "Frozen exact request prompt"
    assert params["video_length"] == 192


def test_reference_strategy_builds_only_routed_h3_manifest():
    series, shot, attempt = inputs("references")
    params = build_h3_generation_params(series, shot, attempt, {"asset_a": "/safe/ada.png"})
    assert params["model_type"] == "minimax_h3_ref2va"
    assert [item["path"] for item in params["minimax_h3_references"]] == ["/safe/ada.png"]
    assert params["resolution"] == "704x1280"
    assert params["_series_context"]["referenceManifest"] == attempt["referenceManifest"]


def test_direct_strategy_has_no_accidental_references():
    series, shot, attempt = inputs("direct")
    params = build_h3_generation_params(series, shot, attempt, {"asset_a": "/safe/ada.png"})
    assert params["model_type"] == "minimax_h3"
    assert "minimax_h3_references" not in params
    assert "image_start" not in params


def test_first_frame_requires_and_uses_one_routed_image():
    series, shot, attempt = inputs("first_frame")
    params = build_h3_generation_params(series, shot, attempt, {"asset_a": "/safe/ada.png"})
    assert params["image_start"] == "/safe/ada.png"
    assert params["image_prompt_type"] == "S"
    missing = copy.deepcopy(attempt)
    with pytest.raises(ValueError, match="exact start image"):
        build_h3_generation_params(series, shot, missing, {})


def test_first_last_uses_exact_start_and_end_frames():
    series, shot, attempt = inputs("first_last")
    params = build_h3_generation_params(
        series, shot, attempt, {"asset_a": "/safe/start.png", "asset_b": "/safe/end.png"},
    )
    assert params["image_start"] == "/safe/start.png"
    assert params["image_end"] == "/safe/end.png"
    assert params["image_prompt_type"] == "SE"


def test_ref2va_never_runs_with_empty_reference_set():
    series, shot, attempt = inputs("references")
    with pytest.raises(ValueError, match="cannot start"):
        build_h3_generation_params(series, shot, attempt, {})


def test_legacy_reference_strategy_uses_legacy_media_inputs_and_fixed_recipe():
    series, shot, attempt = inputs("references")
    attempt["model"] = "minimax_h3_legacy"
    attempt["settings"].update({
        "resolution": "720p", "numInferenceSteps": 8,
        "flowShift": 7, "audioShift": 1,
    })

    params = build_h3_generation_params(
        series, shot, attempt, {"asset_a": "/safe/ada.png"},
    )

    assert params["model_type"] == "minimax_h3_legacy"
    assert params["h3_reference_mode"] == "references"
    assert params["image_refs"] == ["/safe/ada.png"]
    assert "minimax_h3_references" not in params
    assert params["resolution"] == "704x1280"
    assert params["video_length"] >= 124
    assert params["num_inference_steps"] == 20
    assert params["flow_shift"] == 12.0
    assert params["h3_audio_shift"] == 3.0
