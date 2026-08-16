from pathlib import Path

from services.minimax_h3_duration import (
    apply_h3_dialogue_duration,
    apply_h3_vocal_timeline,
    count_spoken_syllables,
    estimate_h3_dialogue_seconds,
    extract_h3_dialogue,
    h3_dialogue_split_error,
    inject_h3_vocal_timeline,
    plan_h3_vocal_timeline,
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
    assert "apply_h3_vocal_timeline(frozen_params, duration_model_def)" in job_factory
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


def test_castilian_counter_handles_diphthongs_hiatus_and_silent_u():
    assert count_spoken_syllables(
        "Atención, tripulación, día, ciudad, queso y pingüino.",
        "Castilian Spanish",
    ) == 17


def test_estimate_uses_seconds_per_syllable_plus_authored_pauses():
    estimate = estimate_h3_dialogue_seconds([
        {"language": "Spanish", "text": "Hola, Fry."},
        {"language": "Spanish", "text": "Ya voy!"},
    ])
    assert estimate["word_count"] == 4
    assert estimate["syllable_count"] == 5
    assert estimate["seconds_per_syllable"] == 0.22
    assert estimate["spoken_seconds"] == 1.1
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


def test_longer_dialogue_rounds_up_to_lattice_and_never_cuts_syllables():
    words = " ".join("sol" for _ in range(24)) + "."
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


def test_short_line_gets_bounded_by_silence_for_the_full_h3_minimum():
    params = {
        "prompt": (
            "integrated_multimodal_description: [Shot 1] Ana says "
            "<d>[Spanish] Ya están aquí.</d> "
            "overall_soundscape: Low room tone. "
            "non_diegetic_music: N/A"
        ),
        "video_length": 243,
    }
    apply_h3_dialogue_duration(params, MODEL)
    timeline = apply_h3_vocal_timeline(params, MODEL)

    assert timeline is not None
    assert timeline["duration_seconds"] == 5.167
    assert [item["kind"] for item in timeline["intervals"]] == [
        "silence", "dialogue", "silence",
    ]
    assert timeline["leading_silence_seconds"] >= 0.45
    assert timeline["trailing_silence_seconds"] > 1.0
    assert "the first tagged line is spoken exactly once" in params["prompt"]
    assert "00:05.167" in params["prompt"]
    assert params["prompt"].count("VOCAL TIMELINE LOCK:") == 1


def test_vocal_timeline_reapplication_replaces_old_physical_boundary():
    prompt = (
        "integrated_multimodal_description: [Shot 1] Ana says "
        "<d>[Spanish] Espera.</d> "
        "overall_soundscape: Wind. non_diegetic_music: N/A"
    )
    first, _ = inject_h3_vocal_timeline(prompt, 5.0)
    second, timeline = inject_h3_vocal_timeline(first, 5.167)

    assert second.count("VOCAL TIMELINE LOCK:") == 1
    assert "00:05.167" in second
    assert "00:05.000" not in second
    assert timeline["intervals"][-1]["end_seconds"] == 5.167


def test_multiple_lines_have_separate_windows_and_silent_turn_gap():
    timeline = plan_h3_vocal_timeline([
        {"language": "Spanish", "text": "Ven aquí."},
        {"language": "Spanish", "text": "Ahora voy."},
    ], 5.167)

    kinds = [item["kind"] for item in timeline["intervals"]]
    assert kinds == ["silence", "dialogue", "silence", "dialogue", "silence"]
    assert "the first tagged line" in timeline["text"]
    assert "the second tagged line" in timeline["text"]


def test_visual_only_and_driving_audio_clips_get_non_conflicting_full_timeline():
    silent = plan_h3_vocal_timeline([], 5.167)
    driving = plan_h3_vocal_timeline([], 5.167, mapped_driving_audio=True)

    assert silent["intervals"][0]["kind"] == "silence"
    assert "all characters remain silent" in silent["text"]
    assert driving["intervals"][0]["kind"] == "mapped_audio"
    assert "only from the mapped driving audio" in driving["text"]
    assert "all characters remain silent" not in driving["text"]


def test_unstructured_singing_prompt_is_not_accidentally_silenced():
    params = {
        "prompt": "A woman sings wordlessly while walking through the rain.",
        "video_length": 124,
    }

    assert apply_h3_vocal_timeline(params, MODEL) is None
    assert "VOCAL TIMELINE LOCK" not in params["prompt"]
    assert "remain silent" not in params["prompt"]
