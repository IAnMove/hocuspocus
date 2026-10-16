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


def _marked_clip(path: Path, seconds: float) -> None:
    """A gray clip whose sound is one 1 kHz burst 100 ms after its first frame, so a join can be checked for where
    each clip's sound lands."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=gray:s=160x90:r=24:d={seconds}",
           "-f", "lavfi", "-i", f"sine=f=1000:sample_rate=48000:d=0.3,adelay=100|100,apad=whole_dur={seconds}",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", f"{seconds}", str(path)]
    assert subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0


def _burst_errors_ms(joined: Path, starts: list[float]) -> list[int]:
    """How late (ms) each clip's burst sounds against ``start + 0.1`` on the joined sound."""
    import numpy as np

    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(joined), "-map", "0:a", "-ac", "1", "-ar", "48000",
                          "-f", "s16le", "-"], capture_output=True).stdout
    level = np.abs(np.frombuffer(pcm, dtype="<i2").astype(float))
    errors = []
    for start in starts:
        window = level[int(max(0.0, start - 0.05) * 48000):int((start + 0.5) * 48000)]
        hits = np.nonzero(window > 400)[0]
        assert hits.size, f"no burst near {start:.3f}s"
        errors.append(round((max(0.0, start - 0.05) + hits[0] / 48000 - (start + 0.1)) * 1000))
    return errors


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg is required")
@pytest.mark.parametrize("kind", ["fade_black", "dip_white"])
def test_a_fade_places_the_next_sound_on_the_planned_timeline(tmp_path, kind):
    # Sixteen cuts then a fade into a narrated shot, as the 90-shot episode had. The concat that joins a fade took the
    # longer of the pictures (whole frames) and the sound as the length of what came before, so the shot after it
    # sounded up to a frame late: 10 ms here, 50 ms on the real episode, which the sound check refused.
    from services.core_series_assembly import concatenate_clips
    from services.series_transitions import placed_offsets

    lengths = [1.07, 1.33, 2.91, 1.58, 1.21, 0.87, 1.44, 1.12, 0.96, 1.66, 1.05, 1.29, 1.17, 2.4, 1.9, 1.35, 3.02]
    clips = []
    for index, seconds in enumerate(lengths):
        path = tmp_path / f"clip{index:02d}.mp4"
        _marked_clip(path, seconds)
        clips.append(str(path))
    transitions = [None] * (len(clips) - 1) + [{"kind": kind, "seconds": 0.65}]
    out = tmp_path / "joined.mp4"
    assert concatenate_clips(clips, str(out), transitions=transitions) is True
    starts = placed_offsets([probe_duration_seconds(path) for path in clips], transitions)
    errors = _burst_errors_ms(out, starts)
    assert max(abs(value) for value in errors) <= 3, errors


def _fake_probes(monkeypatch, count, *, seconds=2.0, with_audio=True):
    from app.services import mix_concat

    monkeypatch.setattr(mix_concat, "probe_duration_seconds", lambda path, ffmpeg_bin="ffmpeg": seconds)
    monkeypatch.setattr(mix_concat, "probe_audio_flags", lambda paths, ffmpeg_bin="ffmpeg": [with_audio] * len(paths))
    return [__file__] * count


def test_a_long_join_never_gives_one_ffmpeg_graph_more_than_the_block_size(monkeypatch):
    # One graph keeps a decoder and its frames for every clip it joins (75 MB a 1080p clip): 90 shots killed the server.
    from app.services import mix_concat_blocks

    clips = _fake_probes(monkeypatch, 90)
    runs = []
    monkeypatch.setattr(mix_concat_blocks, "_run_ffmpeg_command", lambda cmd, path, **kw: runs.append(cmd) or True)
    assert concat_with_tail_hold_and_crossfade(clips, "joined.mp4") is True
    inputs = [cmd.count("-i") for cmd in runs]
    assert max(inputs) <= 16, inputs
    # 90 clips: six even blocks of 15, then the join of the six.
    assert inputs == [15] * 6 + [6]


def test_blocks_are_even_and_cover_every_clip_once():
    from app.services.mix_concat_blocks import block_slices

    assert block_slices(90) == [(0, 15), (15, 30), (30, 45), (45, 60), (60, 75), (75, 90)]
    assert block_slices(17) == [(0, 9), (9, 17)]
    assert block_slices(16) == [(0, 16)]
    for count in (2, 31, 257, 1000):
        slices = block_slices(count)
        assert slices[0][0] == 0 and slices[-1][1] == count
        assert all(end - start <= 16 and end > start for start, end in slices)
        assert all(a[1] == b[0] for a, b in zip(slices, slices[1:]))


def test_over_the_block_size_the_blocks_are_joined_again_in_blocks(monkeypatch):
    from app.services import mix_concat_blocks

    clips = _fake_probes(monkeypatch, 300)
    runs = []
    monkeypatch.setattr(mix_concat_blocks, "_run_ffmpeg_command", lambda cmd, path, **kw: runs.append(cmd) or True)
    assert concat_with_tail_hold_and_crossfade(clips, "joined.mp4") is True
    assert max(cmd.count("-i") for cmd in runs) <= 16
    assert runs[-1].count("-i") <= 16 and runs[-1][-1].endswith("joined.mp4")


def test_the_block_files_are_removed_and_a_failed_block_stops_the_join(monkeypatch, tmp_path):
    from app.services import mix_concat_blocks

    clips = _fake_probes(monkeypatch, 40)
    calls = []

    def run(cmd, path, **kw):
        calls.append(path)
        return len(calls) < 2

    monkeypatch.setattr(mix_concat_blocks, "_run_ffmpeg_command", run)
    assert concat_with_tail_hold_and_crossfade(clips, str(tmp_path / "joined.mp4")) is False
    assert len(calls) == 2
    assert [item.name for item in tmp_path.iterdir()] == []


def _seam_clip(path: Path, seconds: float, index: int) -> None:
    color = "0x%02x%02x%02x" % ((index * 53) % 256, (index * 97 + 40) % 256, (index * 29 + 120) % 256)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d={seconds}",
           "-f", "lavfi", "-i", f"sine=f=1000:sample_rate=48000:d=0.3,adelay=100|100,apad=whole_dur={seconds}",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", f"{seconds}", str(path)]
    assert subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0


def _psnr_db(first: Path, second: Path) -> float:
    out = subprocess.run(["ffmpeg", "-i", str(first), "-i", str(second), "-lavfi", "psnr", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    value = out.rsplit("average:", 1)[1].split()[0]
    return float("inf") if value == "inf" else float(value)


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg is required")
@pytest.mark.parametrize("transitions_in_play", [False, True])
def test_joining_in_blocks_equals_joining_in_one_pass(tmp_path, monkeypatch, transitions_in_play):
    # 40 uneven clips: three blocks (14, 13, 13), so the seams fall at clips 14 and 27. With transitions, a dissolve
    # and a fade land ON the seams, one dissolve and one dip inside a block: the join must be the single pass's.
    from services import core_series_assembly, mix_concat as join_module
    from services.series_transitions import placed_offsets

    lengths = [0.9 + 0.13 * ((index * 7) % 11) for index in range(40)]
    clips = []
    for index, seconds in enumerate(lengths):
        path = tmp_path / f"clip{index:02d}.mp4"
        _seam_clip(path, round(seconds, 3), index)
        clips.append(str(path))
    transitions = None
    if transitions_in_play:
        transitions = [None] * 40
        transitions[5] = {"kind": "dissolve", "seconds": 0.5}
        transitions[14] = {"kind": "dissolve", "seconds": 0.6}
        transitions[20] = {"kind": "dip_white", "seconds": 0.4}
        transitions[27] = {"kind": "fade_black", "seconds": 0.65}
    one_pass, blocks = tmp_path / "one_pass.mp4", tmp_path / "blocks.mp4"
    monkeypatch.setattr(core_series_assembly, "ASSEMBLY_BLOCK_CLIPS", 10**6)
    monkeypatch.setattr(join_module, "ASSEMBLY_BLOCK_CLIPS", 10**6)
    assert core_series_assembly.concatenate_clips(clips, str(one_pass), transitions=transitions) is True
    monkeypatch.undo()
    assert core_series_assembly.concatenate_clips(clips, str(blocks), transitions=transitions) is True
    assert sorted(item.name for item in tmp_path.iterdir() if item.name.startswith(".")) == []
    # Frames and sound: the same count and length, the sound at the same samples (within one) of the plan.
    assert _decoded_seconds(blocks, "v") == _decoded_seconds(one_pass, "v")
    assert abs(_decoded_seconds(blocks, "a") - _decoded_seconds(one_pass, "a")) < 0.001
    starts = placed_offsets([probe_duration_seconds(path) for path in clips], transitions)
    assert max(abs(value) for value in _burst_errors_ms(one_pass, starts)) <= 3
    assert max(abs(value) for value in _burst_errors_ms(blocks, starts)) <= 3
    # The pictures: the dissolves and holds fall on the same frames, and the extra generation costs nothing visible.
    assert _psnr_db(one_pass, blocks) >= 40


def test_an_ffmpeg_killed_for_lack_of_memory_fails_the_join_with_a_clear_message(monkeypatch, tmp_path):
    # The kernel's OOM killer sends SIGKILL. That was an opaque "ffmpeg could not join" (and a hard-cut retry that
    # needs the same memory); it is now an error that says what happened.
    from app.services import mix_concat
    from app.services.mix_concat import FfmpegOutOfMemory

    killed = SimpleNamespace(returncode=-9, stderr="")
    monkeypatch.setattr(mix_concat.subprocess, "run", lambda *args, **kwargs: killed)
    out = tmp_path / "joined.mp4"
    with pytest.raises(FfmpegOutOfMemory, match="Out of memory while assembling.*joining 2 clips"):
        mix_concat._run_ffmpeg_command(["ffmpeg", "-i", "a.mp4", "-i", "b.mp4", str(out)], str(out))
    refused = SimpleNamespace(returncode=1, stderr="[libx264] Cannot allocate memory")
    monkeypatch.setattr(mix_concat.subprocess, "run", lambda *args, **kwargs: refused)
    with pytest.raises(FfmpegOutOfMemory):
        mix_concat._run_ffmpeg_command(["ffmpeg", "-i", "a.mp4", str(out)], str(out))
    plain = SimpleNamespace(returncode=1, stderr="Invalid data found")
    monkeypatch.setattr(mix_concat.subprocess, "run", lambda *args, **kwargs: plain)
    assert mix_concat._run_ffmpeg_command(["ffmpeg", str(out)], str(out)) is False


def test_the_soft_join_does_not_fall_back_to_a_hard_join_after_an_out_of_memory(monkeypatch, tmp_path):
    from services import core_series_assembly, mix_concat as join_module

    clips = []
    for index in range(2):
        path = tmp_path / f"clip{index}.mp4"
        path.write_bytes(b"x")
        clips.append(str(path))
    hard = []

    def killed(*args, **kwargs):
        raise join_module.FfmpegOutOfMemory("Out of memory while assembling")

    monkeypatch.setattr(core_series_assembly, "concat_with_tail_hold_and_crossfade", killed)
    monkeypatch.setattr(core_series_assembly, "_hard_concat_filter", lambda *args, **kwargs: hard.append(1) or True)
    with pytest.raises(join_module.FfmpegOutOfMemory):
        core_series_assembly.concatenate_clips(clips, str(tmp_path / "joined.mp4"))
    assert hard == []


@pytest.mark.skipif(not __import__("sys").platform.startswith("linux"), reason="oom_score_adj is Linux only")
def test_ffmpeg_children_are_the_oom_killers_preferred_victim():
    import sys

    from app.services.mix_concat import child_process_options

    child = subprocess.run([sys.executable, "-c", "print(open('/proc/self/oom_score_adj').read().strip())"],
                           capture_output=True, text=True, **child_process_options())
    assert child.stdout.strip() == "1000", child.stderr


def _bound_wgp_concatenate():
    """WanGP's own join, lifted out of app/wgp.py (importing that module loads torch)."""
    import ast
    import os
    import sys

    source = Path(__file__).resolve().parents[1].joinpath("app", "wgp.py").read_text(encoding="utf-8")
    node = next(item for item in ast.parse(source).body
                if isinstance(item, ast.FunctionDef) and item.name == "concatenate_multi_clip_videos")
    namespace = {"os": os, "sys": sys}
    exec(compile(ast.Module([node], []), "wgp.py", "exec"), namespace)
    return namespace["concatenate_multi_clip_videos"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg is required")
@pytest.mark.parametrize("driving_song", [False, True])
def test_a_hard_join_in_blocks_keeps_the_single_passes_frames_and_sound(tmp_path, monkeypatch, driving_song):
    # Director / Recast joins are hard cuts (no soft join): twenty clips go in two blocks, and the song, when there is
    # one, is laid once over the joined blocks.
    from services import mix_concat as join_module

    concatenate = _bound_wgp_concatenate()
    clips = []
    for index in range(20):
        path = tmp_path / f"clip{index:02d}.mp4"
        _seam_clip(path, round(0.6 + 0.07 * (index % 6), 3), index)
        clips.append(str(path))
    song = tmp_path / "song.m4a"
    if driving_song:
        assert subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=330:d=20", "-c:a", "aac",
                               str(song)], capture_output=True).returncode == 0
    extra = dict(audio_path=str(song)) if driving_song else dict(pad_audio=True, audio_duration_sec=30.0)
    one_pass, blocks = tmp_path / "one_pass.mp4", tmp_path / "blocks.mp4"
    monkeypatch.setattr(join_module, "ASSEMBLY_BLOCK_CLIPS", 10**6)
    assert concatenate(clips, str(one_pass), **extra) is True
    monkeypatch.undo()
    assert concatenate(clips, str(blocks), **extra) is True
    assert [item.name for item in tmp_path.iterdir() if item.name.startswith(".")] == []
    # Pictures cut with a song are the same frames. With the clips' own sound the concat filter already pads each shot
    # to the longer of its picture and its sound; the block seam can round that once more, by at most one frame.
    seams = 1
    assert abs(_decoded_seconds(blocks, "v") - _decoded_seconds(one_pass, "v")) * 24 <= (0 if driving_song else seams)
    assert abs(_decoded_seconds(blocks, "a") - _decoded_seconds(one_pass, "a")) < 0.025
    if driving_song:
        assert _psnr_db(one_pass, blocks) >= 38


def test_only_what_a_concat_made_is_restamped_before_an_xfade():
    # The extra filter between two xfades made ffmpeg buffer twice the frames (a 15-clip block: 4.9 GB, not 2.7 GB).
    from services.series_transitions import filter_for

    dissolve, fade = {"kind": "dissolve", "seconds": 0.5}, {"kind": "fade_black", "seconds": 0.5}
    graph, _video, _audio = filter_for([2.0] * 5, transitions=[None, dissolve, dissolve, fade, dissolve])
    assert graph.count("settb=AVTB,setpts=PTS-STARTPTS[vb") == 1
    assert "[vx3]settb=AVTB,setpts=PTS-STARTPTS[vb4]" in graph


def test_the_out_of_memory_mapping_needs_no_sigkill_constant(monkeypatch):
    # signal.SIGKILL does not exist on Windows: an ffmpeg that fails there must be an ordinary failure (False), not an AttributeError.
    import signal

    from app.services import mix_concat

    monkeypatch.delattr(signal, "SIGKILL", raising=False)
    assert mix_concat.raise_if_out_of_memory(1, "Invalid data found", ["ffmpeg", "-i", "a.mp4"]) is None
    assert mix_concat.raise_if_out_of_memory(None, None, ["ffmpeg"]) is None
    with pytest.raises(mix_concat.FfmpegOutOfMemory):
        mix_concat.raise_if_out_of_memory(1, "[libx264] Cannot allocate memory", ["ffmpeg", "-i", "a.mp4"])


def test_a_cancelled_join_is_a_cancel_and_never_an_out_of_memory(monkeypatch, tmp_path):
    # A cancel stops ffmpeg (terminate, then kill: a SIGKILL return code): it must come back False, not as the OOM error.
    from app.services import mix_concat

    class Process:
        returncode = None

        def __init__(self, *args, **kwargs):
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls <= 2:
                raise subprocess.TimeoutExpired("ffmpeg", timeout)  # still running; again after terminate()
            self.returncode = -9
            return "", ""

        def terminate(self):
            pass

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(mix_concat.subprocess, "Popen", Process)
    out = tmp_path / "joined.mp4"
    out.write_bytes(b"partial")
    assert mix_concat._run_ffmpeg_command(["ffmpeg", "-i", "a.mp4", str(out)], str(out), abort_callback=lambda: True) is False
    assert not out.exists()


def test_a_printed_whole_frame_duration_is_not_floored_to_the_frame_before():
    """ffprobe prints 26/24 s as 1.083333: the fade trim must keep all 26 frames, and still never round up."""
    from services.series_transitions import _whole_frames

    for frames in (13, 26, 38, 70, 125):
        printed = float(f"{frames / 24:.6f}")
        assert _whole_frames(printed) == pytest.approx(frames / 24, abs=1e-9), frames
    assert _whole_frames(1.0833 + 0.0205) == pytest.approx(26 / 24, abs=1e-9), "half a frame over still floors"
