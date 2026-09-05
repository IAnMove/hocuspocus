import copy

import pytest

from services.series_render import (
    build_h3_generation_params,
    normalize_series_resolution,
    normalize_series_shot_duration,
    plan_series_shot_duration,
    quantize_h3_frames,
    series_dialogue_preflight_issues,
    shot_generation_prompt,
)


def test_series_prompt_forces_spain_spanish_and_protagonist_identity():
    series = {
        "language": "Español",
        "spokenLanguage": "Español de España",
        "protagonistConsistency": True,
        "protagonistCharacterId": "char_george",
        "characters": [{"id": "char_george", "name": "George"}],
    }
    prompt = shot_generation_prompt(series, {
        "prompt": "George looks up.",
        "dialogueBeats": [{"characterId": "char_george", "text": "Estoy maravillado."}],
    })
    assert "Castilian Spanish." in prompt
    assert "Identity lock: George" in prompt
    assert "<d>[Spanish] Estoy maravillado.</d>" in prompt


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
    assert normalize_series_shot_duration(4) == 5
    assert normalize_series_shot_duration(8) == 10
    assert normalize_series_shot_duration(99) == 15
    assert quantize_h3_frames(30, reference_mode=False) == quantize_h3_frames(
        15, reference_mode=False,
    )
    assert quantize_h3_frames(15, reference_mode=False) == 345
    assert quantize_h3_frames(15, reference_mode=False) / 24 < 15
    assert quantize_h3_frames(6.5, reference_mode=False) == 158


def test_dialogue_duration_never_rounds_down_for_continuous_discrete_or_h3():
    # 28 one-syllable Spanish words + edge room = 6.51 seconds.
    dialogue = " ".join(["sol"] * 28)
    shot = {"durationSeconds": 5, "dialogueBeats": [{"text": dialogue}]}
    continuous = plan_series_shot_duration({
        "spokenLanguage": "Español de España",
        "provider": {"videoModel": "future_continuous", "videoCapabilities": {
            "minimumDurationSeconds": 0.1, "maximumDurationSeconds": 20,
        }},
    }, shot)
    assert continuous["dialogueDuration"]["estimatedVoiceSeconds"] == pytest.approx(6.51)
    assert continuous["durationSeconds"] == pytest.approx(6.51)

    discrete = plan_series_shot_duration({
        "spokenLanguage": "Español de España",
        "provider": {"videoModel": "future_discrete", "videoCapabilities": {
            "supportedDurationsSeconds": [5, 10, 15],
        }},
    }, shot)
    assert discrete["durationSeconds"] == 10

    h3 = plan_series_shot_duration({
        "spokenLanguage": "Español de España",
        "provider": {"videoModel": "minimax_h3"},
    }, shot)
    assert h3["durationSeconds"] == pytest.approx(158 / 24, abs=0.001)
    assert h3["durationSeconds"] >= h3["dialogueDuration"]["estimatedVoiceSeconds"]
    assert h3["dialogueDuration"]["effectiveFrames"] == 158


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
    assert prompt.startswith("integrated_multimodal_description: [Shot 1]")
    assert "Ada (S1), calm, quiet" in prompt
    assert "<d>[English] We are ready.</d>" in prompt
    assert 'says exactly, "' not in prompt
    assert "No captions" in prompt
    assert "overall_soundscape:" in prompt
    assert prompt.endswith("non_diegetic_music: N/A")


def test_silent_prompt_uses_official_minimal_audio_fields_without_speech_controls():
    series, shot, _ = inputs()
    shot["dialogueBeats"] = []
    prompt = shot_generation_prompt(series, shot)
    assert "<d>" not in prompt
    assert "Spoken language" not in prompt
    assert "babble" not in prompt
    assert "remains silent with their mouth closed" not in prompt
    assert "No human voices" not in prompt
    assert (
        "overall_soundscape: Low room tone and the synchronized sounds of visible "
        "objects and physical actions."
    ) in prompt
    assert prompt.endswith("non_diegetic_music: N/A")


def test_short_dialogue_in_long_clip_gets_one_concise_timing_window():
    series, shot, _ = inputs()
    shot["durationSeconds"] = 10
    shot["dialogueBeats"] = [{
        "characterId": "char_a",
        "text": "Estoy maravillado.",
    }]

    prompt = shot_generation_prompt(series, shot)

    assert "From 1.00 to 1.95 seconds," in prompt
    assert prompt.count("<d>[English] Estoy maravillado.</d>") == 1


def test_latam_spanish_is_not_rewritten_as_castilian():
    series, shot, _ = inputs()
    series["spokenLanguage"] = "Español latinoamericano"

    prompt = shot_generation_prompt(series, shot)

    assert "Latin American Spanish." in prompt
    assert "Castilian Spanish." not in prompt
    assert "<d>[Spanish] We are ready.</d>" in prompt


def test_action_is_kept_when_the_authored_prompt_does_not_contain_it():
    series, shot, _ = inputs()
    shot["prompt"] = "Ada enters the room."
    shot["action"] = "Ada looks up"

    prompt = shot_generation_prompt(series, shot)

    assert "Action: Ada looks up" in prompt


def test_dialogue_preflight_rejects_over_budget_and_reserved_tags():
    _series, shot, _ = inputs()
    shot["durationSeconds"] = 5
    shot["dialogueBeats"] = [{
        "characterId": "char_a",
        "text": " ".join(["one"] * 100),
    }]
    assert "beyond the model's" in series_dialogue_preflight_issues(shot)[0]

    shot["dialogueBeats"] = [{"characterId": "char_a", "text": "Hola </d> mundo"}]
    assert "reserved <d>" in series_dialogue_preflight_issues(shot)[0]


def test_reference_prompt_uses_official_six_section_shape():
    series, shot, attempt = inputs("references")
    prompt = shot_generation_prompt(series, shot, attempt["referenceManifest"])
    headings = [
        "subject_definitions:", "summary:", "retention_analysis:",
        "detailed_description:", "overall_soundscape:", "non_diegetic_music:",
    ]
    assert all(heading in prompt for heading in headings)
    assert [prompt.index(heading) for heading in headings] == sorted(
        prompt.index(heading) for heading in headings
    )
    assert "<d>[English] We are ready.</d>" in prompt


def test_attempt_prompt_and_frame_count_are_frozen_for_exact_replay():
    series, shot, attempt = inputs("direct")
    attempt["prompt"] = "Frozen exact request prompt"
    attempt["settings"]["videoLengthFrames"] = 192
    shot["prompt"] = "Edited after queueing"
    params = build_h3_generation_params(series, shot, attempt, {})
    assert params["prompt"] == "Frozen exact request prompt"
    assert params["video_length"] == 192

    attempt["settings"]["videoLengthFrames"] = 9999
    params = build_h3_generation_params(series, shot, attempt, {})
    assert params["video_length"] == quantize_h3_frames(15, reference_mode=False)


def test_reference_strategy_builds_only_routed_h3_manifest():
    series, shot, attempt = inputs("references")
    params = build_h3_generation_params(series, shot, attempt, {"asset_a": "/safe/ada.png"})
    assert params["model_type"] == "minimax_h3_ref2va"
    assert [item["path"] for item in params["minimax_h3_references"]] == ["/safe/ada.png"]
    assert params["resolution"] == "704x1280"
    assert params["_series_context"]["referenceManifest"] == attempt["referenceManifest"]


def test_reference_media_intents_and_prompt_indices_match_h3_contract():
    series, shot, attempt = inputs("references")
    attempt["referenceManifest"]["selected"] = [{
        "assetId": "video", "entityType": "continuity", "entityId": "shot_previous",
        "referenceRole": "previous_segment", "mediaType": "video", "includeAudio": True,
    }, {
        "assetId": "audio", "entityType": "style", "entityId": "series_a",
        "referenceRole": "manual_override", "mediaType": "audio", "audioIntent": "style",
    }]
    prompt = shot_generation_prompt(series, shot, attempt["referenceManifest"])
    params = build_h3_generation_params(
        series, shot, attempt, {"video": "/safe/previous.mp4", "audio": "/safe/style.wav"},
    )

    assert "<Video 1> and its synchronized <Audio 1> soundtrack" in prompt
    assert params["minimax_h3_references"][0]["include_audio"] is True
    assert params["minimax_h3_references"][0]["has_audio"] is True
    assert params["minimax_h3_references"][1]["audio_intent"] == "style"


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


def test_first_last_prompt_uses_the_actual_quantized_final_frame_time():
    series, shot, attempt = inputs("first_last")

    prompt = shot_generation_prompt(series, shot, attempt["referenceManifest"])

    expected = quantize_h3_frames(shot["durationSeconds"], reference_mode=False) / 24
    assert f"At {expected:.2f} seconds" in prompt


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
