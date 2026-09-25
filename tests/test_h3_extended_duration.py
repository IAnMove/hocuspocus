"""Experimental 30s H3 pass stays opt-in and does not rewrite catalog defaults."""

from models.minimax_h3.duration import (
    H3_EXPERIMENTAL_MAX_FRAMES,
    apply_h3_duration_override,
    h3_duration_model_def,
)


H3 = {
    "architecture": "minimax_h3",
    "frames_maximum": 345,
    "sliding_window_defaults": {"window_max": 345, "window_min": 124},
}


def test_extended_duration_is_off_by_default():
    original = dict(H3)
    assert h3_duration_model_def(original, {}) is original
    assert original["frames_maximum"] == 345


def test_extended_duration_raises_one_pass_ceiling():
    effective = h3_duration_model_def(H3, {"minimax_h3_extended_duration": True})
    assert effective["frames_maximum"] == H3_EXPERIMENTAL_MAX_FRAMES
    assert effective["sliding_window_defaults"]["window_max"] == H3_EXPERIMENTAL_MAX_FRAMES
    assert H3["frames_maximum"] == 345


def test_extended_duration_skips_audio_and_viggle():
    audio = {**H3, "audio_only": True}
    viggle = {**H3, "minimax_h3_viggle": True}
    flag = {"minimax_h3_extended_duration": True}
    assert h3_duration_model_def(audio, flag) is audio
    assert h3_duration_model_def(viggle, flag) is viggle


def test_apply_marks_memory_override_only_when_enabled():
    inputs = {"minimax_h3_extended_duration": True}
    apply_h3_duration_override(inputs, H3)
    assert inputs["sliding_window_memory_override"] is True
    skipped = {}
    apply_h3_duration_override(skipped, H3)
    assert "sliding_window_memory_override" not in skipped
