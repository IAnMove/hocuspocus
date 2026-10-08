import shutil
import subprocess
from pathlib import Path

import pytest

from types import SimpleNamespace

from services.generation import bind_wgp, get_wgp
from services.generation import runtime as generation_runtime
from app.services.mix_concat import (
    build_hard_concat_filter,
    build_hold_crossfade_filter,
    concat_with_tail_hold_and_crossfade,
    concatenate_multi_clip_videos,
    driving_soundtrack_bound,
    hold_crossfade_output_seconds,
    probe_audio_flags,
    probe_duration_seconds,
    probe_has_audio,
    should_use_hold_crossfade,
)


def test_concatenate_port_delegates_to_bound_wgp():
    calls = []
    previous = generation_runtime._wgp

    def fake_concat(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    bind_wgp(SimpleNamespace(concatenate_multi_clip_videos=fake_concat))
    try:
        assert get_wgp().concatenate_multi_clip_videos is fake_concat
        assert concatenate_multi_clip_videos(
            ["a.mp4", "b.mp4"],
            "out.mp4",
            "song.wav",
            abort_callback=None,
        ) is True
    finally:
        generation_runtime._wgp = previous
    assert calls == [
        (
            (["a.mp4", "b.mp4"], "out.mp4", "song.wav"),
            {
                "audio_start_sec": 0.0,
                "abort_callback": None,
                "pad_audio": False,
                "audio_duration_sec": None,
            },
        )
    ]


def test_hold_crossfade_filter_covers_every_clip_and_xfade():
    filter_str, video, audio = build_hold_crossfade_filter([5.0, 5.0, 5.0])
    assert (
        "[0:v]settb=AVTB,setpts=PTS-STARTPTS,"
        "tpad=stop_mode=clone:stop_duration=1.500,trim=end=5.500000[v0]"
    ) in filter_str
    assert "apad=whole_dur=5.500000,atrim=end=5.500000[a1]" in filter_str
    assert "xfade=transition=fade:duration=0.400" in filter_str
    assert "acrossfade=d=0.400000" in filter_str
    assert video == "vx2"
    assert audio == "ax2"


def test_hold_crossfade_cuts_every_clip_to_the_length_its_dissolve_is_placed_by():
    # A decoded AAC track runs up to a frame past its container duration and silence comes in whole 1024-sample
    # frames. Chained untrimmed, the sound drifted ~10 ms a join behind the pictures: 2.7 s over a 268-shot episode.
    filter_str, _video, _audio = build_hold_crossfade_filter([2.25, 3.0], has_audio=[True, False])
    assert "trim=end=2.750000[v0]" in filter_str and "trim=end=3.500000[v1]" in filter_str
    assert "[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS," \
        "apad=whole_dur=2.750000,atrim=end=2.750000[a0]" in filter_str
    assert "anullsrc=channel_layout=stereo:sample_rate=48000,atrim=end=3.500000," in filter_str
    assert ":d=" not in filter_str


def test_hold_crossfade_forces_a_common_timebase_before_xfade():
    # Same fps with encoder tbn 1/30 vs 1/15360 used to fail with
    # "First input link main timebase do not match".
    filter_str, _video, _audio = build_hold_crossfade_filter([1.0, 1.0], with_audio=False)
    assert filter_str.count("settb=AVTB,setpts=PTS-STARTPTS") == 2


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
    # External soundtrack used to be mapped as `{n}:a:0` with -shortest, so a
    # song shorter than the concat truncated the video. Always apad first.
    concat_fn = text[
        text.index("def concatenate_multi_clip_videos(")
        : text.index("def _remove_partial_output():")
    ]
    assert 'f"{n}:a:0"' not in concat_fn
    assert "audio_filters.append(\"apad\")" in concat_fn
    assert "atrim=duration={bound:.6f}" in concat_fn
    assert "driving_soundtrack_bound(clip_secs)" in concat_fn
    assert "sum(clip_secs) - audio_start_sec" not in concat_fn
    assert '"-map", "[outa]"' in concat_fn
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
    assert "acrossfade=d=0.400000" in filter_str
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


def _write_timescale_clip(path: Path, *, frames: int, fps: int, timescale: int) -> None:
    completed = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=blue:s=160x120:r={fps}",
            "-frames:v", str(frames),
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-video_track_timescale", str(timescale),
            str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr[-400:]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_hold_crossfade_ffmpeg_accepts_mismatched_encoder_timebases(tmp_path):
    # Two 30fps clips with tbn 1/30 vs 1/15360. Without settb, xfade rejects
    # the graph and Director fell back to a slap-cut.
    first = tmp_path / "tbn30.mp4"
    second = tmp_path / "tbn15360.mp4"
    out = tmp_path / "xfade.mp4"
    _write_timescale_clip(first, frames=30, fps=30, timescale=30)
    _write_timescale_clip(second, frames=30, fps=30, timescale=15360)
    assert concat_with_tail_hold_and_crossfade(
        [str(first), str(second)], str(out),
    ) is True
    assert out.is_file() and out.stat().st_size > 0


def test_driving_soundtrack_bound_covers_the_pictures_not_the_song_offset():
    # Director music_video / rejoin pass audio_start_sec=12.5 (clip 0 start)
    # and pad_audio=False. That offset is atrim=start on the track. The old
    # bound subtracted it from the clip sum, so 10s of film + start=12.5
    # became atrim=duration=2.1 and -shortest discarded the tail.
    assert driving_soundtrack_bound([5.0, 5.0]) == 12.0
    assert driving_soundtrack_bound([2.0, 2.0]) == 6.0
    assert driving_soundtrack_bound([0.0]) == 2.1


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_padded_soundtrack_shortest_keeps_the_concat_video(tmp_path):
    # Director used to map a raw song with -shortest, so 4s of video + 1s of
    # music encoded 1s of pictures. apad + -shortest keeps the video span.
    first = tmp_path / "a.mp4"
    second = tmp_path / "b.mp4"
    song = tmp_path / "song.m4a"
    out = tmp_path / "joined.mp4"
    _write_test_clip(first, with_audio=False, duration=2.0)
    _write_test_clip(second, with_audio=False, duration=2.0)
    completed = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=f=440:d=1", "-c:a", "aac", str(song),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr[-400:]
    completed = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(first), "-i", str(second), "-i", str(song),
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[outv];"
            "[2:a]asetpts=PTS-STARTPTS,apad,atrim=duration=6[outa]",
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            "-pix_fmt", "yuv420p", str(out),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr[-600:]
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
            "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out),
        ],
        capture_output=True, text=True, timeout=30,
    )
    frames = int((probe.stdout or "0").strip() or 0)
    assert frames >= 100, frames


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_mid_song_offset_does_not_truncate_concat_video(tmp_path):
    # Director music_video / rejoin: two 2s clips, song starts at 12.5s,
    # pad_audio=False. Subtracting that offset from the clip sum used to
    # atrim=2.1s; -shortest then kept ~2s of a 4s movie.
    first = tmp_path / "verse.mp4"
    second = tmp_path / "chorus.mp4"
    song = tmp_path / "song.m4a"
    out = tmp_path / "joined.mp4"
    _write_test_clip(first, with_audio=False, duration=2.0)
    _write_test_clip(second, with_audio=False, duration=2.0)
    completed = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=f=440:d=20", "-c:a", "aac", str(song),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr[-400:]
    stale_bound = max(0.1, 4.0 - 12.5) + 2.0
    bound = driving_soundtrack_bound([2.0, 2.0])
    assert bound == 6.0
    assert stale_bound == 2.1
    completed = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(first), "-i", str(second), "-i", str(song),
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[outv];"
            "[2:a]atrim=start=12.5,asetpts=PTS-STARTPTS,apad,"
            f"atrim=duration={bound:.6f}[outa]",
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            "-pix_fmt", "yuv420p", str(out),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr[-600:]
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
            "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out),
        ],
        capture_output=True, text=True, timeout=30,
    )
    frames = int((probe.stdout or "0").strip() or 0)
    assert frames >= 100, frames


def test_ffprobe_is_found_beside_ffmpeg_even_in_a_folder_named_after_ffmpeg():
    """The bug: ``replace("ffmpeg", "ffprobe")`` also rewrote the folder (``/opt/ffmpeg-6/bin/ffmpeg``)."""
    from app.services.mix_concat import ffprobe_for
    assert ffprobe_for("ffmpeg") == "ffprobe"
    assert ffprobe_for("/opt/ffmpeg-6/bin/ffmpeg") == "/opt/ffmpeg-6/bin/ffprobe"
    assert ffprobe_for("C:/tools/ffmpeg/ffmpeg.exe") == "C:/tools/ffmpeg/ffprobe.exe"
    assert ffprobe_for("/usr/bin/ffmpeg7") == "/usr/bin/ffprobe7"


def test_without_a_transition_the_filter_list_matches_the_hold_crossfade():
    import hashlib

    from services.series_transitions import filter_for, output_seconds, placed_offsets

    durations = [2.0, 3.5, 1.25, 4.0]
    flags = [True, False, True, True]
    plain, video, audio = build_hold_crossfade_filter(durations, has_audio=flags)
    same, same_video, same_audio = filter_for(durations, transitions=None, has_audio=flags)
    cuts = [{"kind": "cut", "seconds": 0.4}] * len(durations)
    cut_filter, cut_video, cut_audio = filter_for(durations, transitions=cuts, has_audio=flags)
    digest = hashlib.sha256(plain.encode()).hexdigest()
    assert hashlib.sha256(same.encode()).hexdigest() == digest
    assert hashlib.sha256(cut_filter.encode()).hexdigest() == digest
    assert (video, audio) == (same_video, same_audio) == (cut_video, cut_audio)
    assert output_seconds(durations, None) == hold_crossfade_output_seconds(durations)
    assert output_seconds(durations, cuts) == hold_crossfade_output_seconds(durations)


def test_transition_duration_arithmetic_for_dissolve_and_the_two_fades():
    from services.series_transitions import output_seconds, placed_offsets

    durations = [2.0, 2.0, 2.0, 2.0, 2.0]
    dissolve = [None, {"kind": "dissolve", "seconds": 0.5}, {"kind": "dissolve", "seconds": 0.5},
                {"kind": "dissolve", "seconds": 0.5}, {"kind": "dissolve", "seconds": 0.5}]
    # The episode still ends on the last clip's held frame, as every joined episode does.
    assert output_seconds(durations, dissolve) == pytest.approx(8.5)
    assert placed_offsets(durations, dissolve) == pytest.approx([0.0, 1.5, 3.0, 4.5, 6.0])
    fades = [None, {"kind": "fade_black", "seconds": 1.0}, {"kind": "dip_white", "seconds": 0.2},
             {"kind": "cut"}, {"kind": "fade_black", "seconds": 2.0}]
    # The cut holds shot 3's last frame 0.5 s and dissolves 0.4 s into shot 4; the fades add nothing.
    assert output_seconds(durations, fades) == pytest.approx(10.6)
    assert placed_offsets(durations, fades) == pytest.approx([0.0, 2.0, 4.0, 6.1, 8.1])
    mixed = [None, {"kind": "fade_black", "seconds": 0.5}, {"kind": "dissolve", "seconds": 0.4},
             {"kind": "dip_white", "seconds": 0.3}, {"kind": "cut"}]
    assert output_seconds(durations, mixed) == pytest.approx(10.2)
    # The first shot's transition has nothing to join from, so it does not change the length.
    assert output_seconds(durations, [{"kind": "dissolve", "seconds": 1.0}]) == hold_crossfade_output_seconds(durations)


def test_a_cut_is_the_same_soft_join_beside_a_transition():
    from app.services.mix_concat import hold_crossfade_offsets
    from services.series_transitions import filter_for, output_seconds, placed_offsets, placed_spans

    durations = [2.0, 2.0, 2.0]
    one_dissolve = [None, None, {"kind": "dissolve", "seconds": 0.5}]
    # Shot 2 starts where it starts without transitions; only the dissolve into shot 3 is new.
    assert placed_offsets(durations, one_dissolve)[:2] == pytest.approx(hold_crossfade_offsets(durations)[:2])
    assert placed_offsets(durations, one_dissolve) == pytest.approx([0.0, 2.1, 3.6])
    assert output_seconds(durations, one_dissolve) == pytest.approx(6.1)
    spans = placed_spans(durations, one_dissolve)
    assert [value for span in spans for value in span] == pytest.approx([0.0, 2.5, 2.1, 4.1, 3.6, 6.1])
    graph, _video, _audio = filter_for(durations, transitions=one_dissolve)
    plain, _plain_video, _plain_audio = build_hold_crossfade_filter(durations)
    plain_parts = plain.split(";")
    # The clip before the cut and the join are the freeze-tail dissolve's own pieces.
    for piece in ("[0:v]", "[0:a]"):
        assert next(part for part in plain_parts if part.startswith(piece)) in graph.split(";")
    assert "xfade=transition=fade:duration=0.400:offset=2.100[vx1]" in graph
    assert "[a0][a1]acrossfade=d=0.400000[ax1]" in graph
    # Shot 2 dissolves on its own last frame: no held tail before the dissolve, which starts 0.5 s early.
    assert "[1:v]settb=AVTB,setpts=PTS-STARTPTS,trim=end=2.000000" in graph and "whole_dur=2.000000" in graph
    assert "xfade=transition=fade:duration=0.500:offset=3.600[vx2]" in graph
    # Many cuts with tiny clips: the same arithmetic as mix_concat.
    uneven = [0.3, 1.2, 0.08, 2.5, 0.9]
    with_one = [None, None, None, None, {"kind": "fade_black", "seconds": 0.4}]
    assert placed_offsets(uneven, with_one)[:4] == pytest.approx(hold_crossfade_offsets(uneven)[:4])


def test_an_active_transition_does_not_reuse_the_freeze_tail():
    from services.series_transitions import filter_for

    graph, _video, _audio = filter_for(
        [2.0, 2.0, 2.0],
        transitions=[None, {"kind": "dissolve", "seconds": 0.5}, {"kind": "fade_black", "seconds": 0.4}],
    )
    parts = graph.split(";")
    assert not any(part.startswith(("[0:v]", "[1:v]")) and "tpad=" in part for part in parts)
    # The episode's last clip keeps the held frame every joined episode ends on.
    assert any(part.startswith("[2:v]") and "tpad=" in part for part in parts)
    assert "xfade=transition=fade:duration=0.500" in graph
    assert "acrossfade=d=0.500000" in graph
    assert "fade=t=out" in graph and "color=black" in graph
    white, _video, _audio = filter_for([2.0, 2.0], transitions=[None, {"kind": "dip_white", "seconds": 0.3}])
    assert "color=white" in white and "xfade=" not in white
    assert not any(part.startswith("[0:v]") and "tpad=" in part for part in white.split(";"))


def _decoded_seconds(path: Path, stream: str) -> float:
    """Length of a stream as decoded (frames at 24 fps, or samples at 48 kHz), not as the container states it."""
    if stream == "v":
        out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                              "stream=nb_read_frames", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
        return int(out.stdout.strip()) / 24
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-ac", "1", "-ar", "48000",
                          "-f", "s16le", "-"], capture_output=True).stdout
    return len(pcm) / 2 / 48000


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg is required")
def test_soft_join_keeps_sound_on_the_pictures_over_many_clips(tmp_path):
    # Twelve talking clips of uneven length, as a Series episode has, plus a silent one: the joined sound must end
    # with the pictures. Untrimmed, each AAC tail pushed the sound ~10 ms later per join.
    lengths = [1.07, 1.33, 0.91, 1.58, 1.21, 0.87, 1.44, 1.12, 0.96, 1.66, 1.05, 1.29, 1.17]
    clips = []
    for index, seconds in enumerate(lengths):
        path = tmp_path / f"clip{index:02d}.mp4"
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=gray:s=160x120:r=24:d={seconds}"]
        if index != 6:
            cmd += ["-f", "lavfi", "-i", f"sine=f={300 + 20 * index}:sample_rate=48000:d={seconds}", "-c:a", "aac"]
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-t", f"{seconds}", str(path)]
        assert subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0
        clips.append(str(path))
    out = tmp_path / "joined.mp4"
    assert concat_with_tail_hold_and_crossfade(clips, str(out)) is True
    planned = hold_crossfade_output_seconds([probe_duration_seconds(path) for path in clips])
    video, sound = _decoded_seconds(out, "v"), _decoded_seconds(out, "a")
    # The sound follows the planned timeline to within one AAC frame of the output's own encoder (it ran 71 ms over
    # here before the cut); the pictures to within the 24 fps frames the last dissolve rounds to.
    assert abs(sound - planned) < 0.025, (sound, planned)
    assert abs(video - planned) < 0.1, (video, planned)
