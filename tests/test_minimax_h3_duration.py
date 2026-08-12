from pathlib import Path

from services.minimax_h3_duration import (
    apply_h3_dialogue_duration,
    estimate_h3_dialogue_seconds,
    extract_h3_dialogue,
    h3_dialogue_split_error,
)


MODEL = {
    "fps": 24,
    "frames_minimum": 124,
    "frames_maximum": 345,
    "frame_alignment_modulus": 17,
    "frame_alignment_remainder": 5,
}


def test_every_h3_job_crosses_the_mandatory_duration_gate():
    launch = (Path(__file__).parents[1] / "app" / "launch.py").read_text(encoding="utf-8")
    job_factory = launch[launch.index("def _new_generation_job("):]
    job_factory = job_factory[:job_factory.index("def _register_manual_generation_job(")]
    assert "apply_h3_dialogue_duration(frozen_params, duration_model_def)" in job_factory
    assert "raise ValueError(h3_dialogue_split_error(contract))" in job_factory
    assert launch.count("apply_h3_dialogue_duration(") >= 2


def test_extracts_only_authored_speech_and_preserves_exact_payload():
    prompt = (
        'A sign reads "CAFÉ". Ana (S1) says '
        '<d>[Spanish] ¿Dónde está la semilla?</d>'
    )
    assert extract_h3_dialogue(prompt) == [
        {"language": "Spanish", "text": "¿Dónde está la semilla?"},
    ]
    assert extract_h3_dialogue('A sign reads "CAFÉ".') == []


def test_plain_says_quote_is_supported_for_uncompiled_manual_prompts():
    assert extract_h3_dialogue('Ana dice: "Llegamos a tiempo."') == [
        {"language": "", "text": "Llegamos a tiempo."},
    ]


def test_estimate_counts_words_punctuation_speaker_gap_and_edges():
    estimate = estimate_h3_dialogue_seconds([
        {"text": "Hola, Fry."},
        {"text": "Ya voy!"},
    ])
    assert estimate["word_count"] == 4
    assert estimate["segment_count"] == 2
    assert estimate["estimated_seconds"] > estimate["spoken_seconds"]


def test_short_dialogue_forces_h3_minimum_instead_of_user_ten_seconds():
    params = {
        "prompt": "Ana (S1): <d>[Spanish] Estoy maravillada.</d>",
        "video_length": 243,
    }
    contract = apply_h3_dialogue_duration(params, MODEL)
    assert contract is not None
    assert params["video_length"] == 124
    assert params["duration_seconds"] == 5.167
    assert contract["minimum_limited"] is True
    assert contract["requested_frames_before"] == 243


def test_longer_dialogue_rounds_up_to_lattice_and_never_cuts_words():
    words = " ".join(f"palabra{index}" for index in range(20)) + "."
    params = {"prompt": f"<d>[Spanish] {words}</d>", "video_length": 124}
    contract = apply_h3_dialogue_duration(params, MODEL)
    assert contract is not None
    assert params["video_length"] >= contract["estimated_seconds"] * 24
    assert params["video_length"] % 17 == 5
    assert params["video_length"] > 124


def test_dialogue_over_model_limit_is_marked_for_split_not_silently_fit():
    words = " ".join(f"palabra{index}" for index in range(90)) + "."
    params = {"prompt": f"<d>[Spanish] {words}</d>", "video_length": 124}
    contract = apply_h3_dialogue_duration(params, MODEL)
    assert contract is not None
    assert contract["requires_split"] is True
    assert params["video_length"] == MODEL["frames_maximum"]
    assert "Split the dialogue across multiple clips" in h3_dialogue_split_error(contract)


def test_duration_application_is_idempotent_at_the_common_job_boundary():
    params = {
        "prompt": "<d>[Spanish] Esta duración se calcula una sola vez.</d>",
        "video_length": 243,
    }
    first = apply_h3_dialogue_duration(params, MODEL)
    second = apply_h3_dialogue_duration(params, MODEL)
    assert second == first
    assert second["requested_frames_before"] == 243


def test_visual_only_prompt_keeps_authored_duration_unchanged():
    params = {"prompt": "A machine starts.", "video_length": 243}
    assert apply_h3_dialogue_duration(params, MODEL) is None
    assert params["video_length"] == 243
