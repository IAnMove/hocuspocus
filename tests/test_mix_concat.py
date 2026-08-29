import shutil
import subprocess
from pathlib import Path

import pytest

from app.services.mix_concat import (
    build_hard_concat_filter,
    build_hold_crossfade_filter,
    hold_crossfade_output_seconds,
    probe_audio_flags,
    probe_has_audio,
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
    assert "probe_audio_flags" in text
    assert "build_hard_concat_filter" in text
    # Hard concat used to probe only valid_paths[0] for audio. The fps
    # probe may still read clip 0; the audio decision must not.
    audio_probe_window = text[
        text.index("Probe every clip") : text.index("use_clip_audio = clips_have_audio")
    ]
    assert "valid_paths[0]" not in audio_probe_window


def test_mixed_audio_keeps_dialogue_when_the_first_clip_is_silent():
    # A video-only bumper followed by H3 dialogue used to drop every audio
    # stream because the join probed only clip 0.
    filter_str, video, audio = build_hold_crossfade_filter(
        [4.0, 5.0, 5.0],
        has_audio=[False, True, True],
    )
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in filter_str
    assert "[1:a]aresample=48000" in filter_str
    assert "[2:a]aresample=48000" in filter_str
    assert "[0:a]" not in filter_str
    assert "acrossfade=d=0.400" in filter_str
    assert video == "vx2"
    assert audio == "ax2"


def test_mixed_audio_does_not_reference_missing_streams_on_later_clips():
    # Dialogue first, then a video-only B-roll: the old graph asked ffmpeg
    # for [1:a] and the whole assembly failed.
    filter_str, _video, audio = build_hold_crossfade_filter(
        [5.0, 3.0],
        has_audio=[True, False],
    )
    assert "[0:a]aresample=48000" in filter_str
    assert "[1:a]" not in filter_str
    assert "anullsrc=" in filter_str
    assert audio == "ax1"


def test_all_silent_clips_stay_video_only_even_if_flags_are_passed():
    filter_str, _video, audio = build_hold_crossfade_filter(
        [2.0, 2.0],
        with_audio=True,
        has_audio=[False, False],
    )
    assert "[0:a]" not in filter_str
    assert "anullsrc=" not in filter_str
    assert audio is None


def test_probe_audio_flags_checks_every_clip(monkeypatch):
    seen: list[str] = []

    def fake_probe(path: str, ffmpeg_bin: str = "ffmpeg") -> bool:
        seen.append(path)
        return path.endswith("talk.mp4")

    monkeypatch.setattr("app.services.mix_concat.probe_has_audio", fake_probe)
    flags = probe_audio_flags(["intro.mp4", "talk.mp4", "broll.mp4"])
    assert seen == ["intro.mp4", "talk.mp4", "broll.mp4"]
    assert flags == [False, True, False]


def test_hard_concat_keeps_dialogue_when_the_first_clip_is_silent():
    filter_str, maps_audio = build_hard_concat_filter(
        3,
        audio_flags=[False, True, True],
        silent_durations=[2.0, 5.0, 5.0],
    )
    assert maps_audio is True
    assert "anullsrc=channel_layout=stereo:sample_rate=48000:d=2.000" in filter_str
    assert "[1:a]aresample=48000" in filter_str
    assert "[2:a]aresample=48000" in filter_str
    assert "[0:a]" not in filter_str
    assert "concat=n=3:v=1:a=1[outv][outa]" in filter_str


def test_hard_concat_does_not_reference_missing_streams_on_later_clips():
    filter_str, maps_audio = build_hard_concat_filter(
        2,
        audio_flags=[True, False],
        silent_durations=[5.0, 3.0],
    )
    assert maps_audio is True
    assert "[0:a]aresample=48000" in filter_str
    assert "[1:a]" not in filter_str
    assert "anullsrc=" in filter_str
    assert ":d=3.000" in filter_str


def test_hard_concat_all_silent_clips_stay_video_only():
    filter_str, maps_audio = build_hard_concat_filter(
        2,
        audio_flags=[False, False],
        silent_durations=[2.0, 2.0],
    )
    assert maps_audio is False
    assert filter_str == "[0:v][1:v]concat=n=2:v=1:a=0[outv]"


def test_hard_concat_all_audio_clips_keep_the_simple_graph():
    filter_str, maps_audio = build_hard_concat_filter(
        2,
        audio_flags=[True, True],
    )
    assert maps_audio is True
    assert filter_str == "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]"


def _write_test_clip(path: Path, *, with_audio: bool, duration: float = 1.0) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s=160x120:d={duration:.3f}",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=f=440:d={duration:.3f}", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", f"{duration:.3f}", str(path)]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr[-400:]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_hard_concat_mixed_audio_ffmpeg_keeps_dialogue(tmp_path):
    silent = tmp_path / "silent.mp4"
    talk = tmp_path / "talk.mp4"
    out = tmp_path / "joined.mp4"
    _write_test_clip(silent, with_audio=False)
    _write_test_clip(talk, with_audio=True)
    flags = probe_audio_flags([str(silent), str(talk)])
    assert flags == [False, True]
    filter_str, maps_audio = build_hard_concat_filter(
        2, audio_flags=flags, silent_durations=[1.0, 1.0],
    )
    assert maps_audio is True
    completed = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(silent), "-i", str(talk),
            "-filter_complex", filter_str,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
            str(out),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr[-600:]
    assert out.is_file() and out.stat().st_size > 0
    assert probe_has_audio(str(out)) is True


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_hard_concat_mixed_audio_ffmpeg_survives_later_silent_clip(tmp_path):
    talk = tmp_path / "talk.mp4"
    silent = tmp_path / "silent.mp4"
    out = tmp_path / "joined.mp4"
    _write_test_clip(talk, with_audio=True)
    _write_test_clip(silent, with_audio=False)
    flags = probe_audio_flags([str(talk), str(silent)])
    assert flags == [True, False]
    filter_str, maps_audio = build_hard_concat_filter(
        2, audio_flags=flags, silent_durations=[1.0, 1.0],
    )
    assert maps_audio is True
    completed = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(talk), "-i", str(silent),
            "-filter_complex", filter_str,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p",
            str(out),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr[-600:]
    assert probe_has_audio(str(out)) is True
