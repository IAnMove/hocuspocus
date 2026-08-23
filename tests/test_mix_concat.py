from app.services.mix_concat import build_hold_crossfade_filter


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
