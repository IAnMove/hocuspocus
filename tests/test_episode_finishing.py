"""A joined episode gets one loudness and subtitles placed where each line is spoken."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from services.episode_finishing import (
    episode_cues,
    finish_episode,
    finishing_note,
    join_offsets,
    measure_loudness,
    scene_beats,
    srt_text,
    vtt_text,
)
from services.mix_concat import build_hold_crossfade_filter, hold_crossfade_offsets, hold_crossfade_output_seconds

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def test_clip_offsets_match_the_dissolve_filter():
    durations = [2.0, 0.3, 4.5, 3.0]
    filter_str, _video, _audio = build_hold_crossfade_filter(durations)
    from_filter = [float(value) for value in re.findall(r"xfade=transition=fade:duration=[0-9.]+:offset=([0-9.]+)", filter_str)]
    assert [round(value, 3) for value in hold_crossfade_offsets(durations)[1:]] == from_filter


def test_the_offsets_follow_the_join_that_was_used():
    durations = [2.0, 3.0, 4.0]
    dissolve, kind = join_offsets(durations, hold_crossfade_output_seconds(durations) + 0.03)
    assert kind == "dissolve" and dissolve == hold_crossfade_offsets(durations)
    cut, kind = join_offsets(durations, 9.02)
    assert (cut, kind) == ([0.0, 2.0, 5.0], "cut")
    assert join_offsets([4.0], 4.0) == ([0.0], "cut")


def test_long_lines_become_two_line_cues_timed_by_length_and_kept_inside_their_shot():
    long_line = ("I'm a large language model, Kevin. Making things up is literally my job, "
                 "and honestly I am very good at it.")
    cues = episode_cues([
        {"offset": 10.0, "duration": 6.0, "beats": [
            {"text": long_line, "start": 0.5, "end": 5.5},
            {"text": "  Past   the   end.  ", "start": 5.0, "end": 9.0},
            {"text": "", "start": 1.0, "end": 2.0},
            {"text": "No timing"},
        ]},
        {"offset": 0.0, "duration": 3.0, "beats": [{"text": "First.", "start": 0.2, "end": 1.0}]},
    ])
    assert [cue["text"] for cue in cues][0] == "First."
    first, second = cues[1], cues[2]
    assert first["start"] == pytest.approx(10.5) and second["end"] == pytest.approx(15.5)
    assert first["end"] == pytest.approx(second["start"])
    for cue in (first, second):
        lines = cue["text"].split("\n")
        assert len(lines) <= 2 and all(len(line) <= 42 for line in lines), cue["text"]
    assert " ".join(" ".join(cue["text"].split("\n")) for cue in (first, second)) == long_line
    assert cues[3] == {"start": pytest.approx(15.0), "end": pytest.approx(16.0), "text": "Past the end."}


def test_srt_and_vtt_use_their_own_timestamp_format():
    cues = [{"start": 3661.5, "end": 3662.25, "text": "Hola.\nAdiós."}]
    assert srt_text(cues) == "1\n01:01:01,500 --> 01:01:02,250\nHola.\nAdiós.\n"
    assert vtt_text(cues) == "WEBVTT\n\n01:01:01.500 --> 01:01:02.250\nHola.\nAdiós.\n"


def test_scene_beats_stay_inside_the_workspace(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "s01.scene.json").write_text(json.dumps({"dialogueBeats": [{"text": "Hi", "start": 0, "end": 1}, "bad"]}))
    (tmp_path / "outside.scene.json").write_text(json.dumps({"dialogueBeats": [{"text": "x", "start": 0, "end": 1}]}))
    assert scene_beats(str(workspace), "s01.scene.json") == [{"text": "Hi", "start": 0, "end": 1}]
    assert scene_beats(str(workspace), "../outside.scene.json") == []
    assert scene_beats(str(workspace), None) == []
    assert scene_beats(str(workspace), "missing.scene.json") == []


def test_the_note_says_what_was_done_and_why_not():
    done = {"loudness": {"applied": True, "before": {"lufs": -19.34}}, "subtitles": {"written": True, "cueCount": 12}}
    assert finishing_note(done) == "Loudness -19.3 → -16 LUFS. 12 subtitle cues."
    skipped = {"loudness": {"applied": False, "reason": "The episode has no audio"},
               "subtitles": {"written": False, "reason": "No approved take has dialogue beats in its scene document"}}
    assert finishing_note(skipped) == ("Loudness unchanged: The episode has no audio. "
                                       "No subtitles: No approved take has dialogue beats in its scene document.")


def _clip(path: Path, duration: float, volume: float) -> None:
    completed = subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=160x120:rate=24",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-af", f"volume={volume}", "-t", f"{duration}", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    ], capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr[-400:]


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe required")
def test_a_joined_episode_is_evened_to_minus_16_lufs_with_subtitles_on_the_joined_timeline(tmp_path):
    from services.core_series_assembly import concatenate_clips

    workspace = tmp_path / "ws"
    workspace.mkdir()
    first, second = workspace / "s01.mp4", workspace / "s02.mp4"
    _clip(first, 3.0, 0.05)
    _clip(second, 4.0, 0.02)
    (workspace / "s02.scene.json").write_text(json.dumps({"dialogueBeats": [
        {"text": "The second shot speaks.", "start": 1.0, "end": 2.5}]}))
    joined = workspace / "episode_series_assembly.mp4"
    assert concatenate_clips([str(first), str(second)], str(joined))

    finished = finish_episode(str(joined), [str(first), str(second)], [None, "s02.scene.json"], workspace_dir=str(workspace))

    subtitles = finished["subtitles"]
    assert subtitles["written"] and subtitles["join"] == "dissolve" and subtitles["cueCount"] == 1
    start = hold_crossfade_offsets([3.0, 4.0])[1] + 1.0
    srt = (workspace / subtitles["srt"]).read_text()
    assert srt.splitlines()[2] == "The second shot speaks."
    stamp = srt.splitlines()[1].split(" --> ")[0]
    hours, minutes, rest = stamp.split(":")
    assert float(rest.replace(",", ".")) == pytest.approx(start, abs=0.1)
    assert (workspace / subtitles["vtt"]).read_text().startswith("WEBVTT")

    loudness = finished["loudness"]
    assert loudness["applied"], loudness
    assert loudness["before"]["lufs"] < -20
    assert loudness["after"]["lufs"] == pytest.approx(-16.0, abs=1.0)
    assert measure_loudness(str(joined), "ffmpeg")["input_i"]
    assert not list(workspace.glob("*loudnorm-tmp*"))
