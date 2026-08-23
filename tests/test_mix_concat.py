from pathlib import Path

from app.services.mix_concat import (
    build_hold_crossfade_filter,
    hold_crossfade_output_seconds,
    should_use_hold_crossfade,
)


def test_hold_crossfade_filter_covers_every_clip_and_xfade():
    filter_str, video, audio = build_hold_crossfade_filter([5.0, 5.0, 5.0])
    assert "[0:v]tpad=stop_mode=clone:stop_duration=0.500[v0]" in filter_str
    assert "[1:a]apad=pad_dur=0.500[a1]" in filter_str
    assert "xfade=transition=fade:duration=0.400" in filter_str
    assert "acrossfade=d=0.400" in filter_str
    assert video == "vx2"
    assert audio == "ax2"


def test_video_only_filter_omits_audio_pads():
    filter_str, video, audio = build_hold_crossfade_filter(
        [6.0, 6.0],
        with_audio=False,
    )
    assert "[0:a]" not in filter_str
    assert audio is None
    assert video == "vx1"


def test_hold_crossfade_makes_the_timeline_longer_than_the_source_clips():
    # Two 5s clips become more than 10s: each freeze tail is 0.5s and the
    # 0.4s dissolve overlaps the pad, leaving +0.6s of extra time.
    assert hold_crossfade_output_seconds([5.0, 5.0]) == 10.6


def test_soft_join_is_skipped_for_length_locked_recast_style_assembly():
    # Recast / Repaint / Outpaint pass the expected duration so a later
    # frame-count check can reject drift. Soft joins would fail that job.
    assert should_use_hold_crossfade(4, audio_duration_sec=8.333) is False
    assert should_use_hold_crossfade(4, pad_audio=True) is False
    assert should_use_hold_crossfade(3, has_driving_audio=True) is False
    assert should_use_hold_crossfade(1) is False
    assert should_use_hold_crossfade(3) is True


def test_concatenate_gates_soft_join_on_the_duration_lock():
    source = Path(__file__).resolve().parents[1] / "app" / "wgp.py"
    text = source.read_text(encoding="utf-8")
    assert "should_use_hold_crossfade" in text
    assert "audio_duration_sec=audio_duration_sec" in text
    assert "abort_callback=abort_callback" in text
