"""Music-video production: every decision is made by code and tested here without models."""
from __future__ import annotations

import numpy as np
import pytest

from services import lipsync_qa, song_analysis as audio_analysis
from services.music_production import (ProductionError, h3_frames_for, pick_song, segments, shot_windows,
                                       status_summary, validate_spec)
from services.video2d_edit import edit


def test_tempo_grid_finds_132_bpm_not_a_half_or_double():
    beat, sr_hop = 60 / 132, 0.01
    times = np.arange(0, 20, sr_hop)
    onset = np.zeros_like(times)
    for k in range(int((20 - 0.5) / beat) - 1):
        onset[int(round((0.25 + k * beat) / sr_hop))] = 1.0      # kicks on every beat
        onset[int(round((0.25 + (k + 0.5) * beat) / sr_hop))] = 0.35  # weaker off-beats
    bpm, phase = audio_analysis.tempo_grid(onset, times, 20.0, low=60, high=180)
    assert abs(bpm - 132) < 0.3 and abs(phase - 0.25) < 0.02


def test_align_lines_times_written_words_and_fills_gaps():
    heard = [[1.0, 1.3, "Hocus"], [1.3, 1.6, "pocus"], [2.0, 2.4, "move"]]
    lines, recall = audio_analysis.align_lines(["Hocus pocus, make it move"], heard)
    words = lines[0]["words"]
    assert [w["w"] for w in words] == ["Hocus", "pocus,", "make", "it", "move"]
    assert words[0]["t0"] == 1.0 and words[-1]["t1"] == 2.4
    assert 1.6 <= words[2]["t0"] <= 2.0 and recall == 0.6


def test_song_verdicts_and_pick():
    assert audio_analysis.verdict(0.95, 0.001) == "ok"
    assert audio_analysis.verdict(0.6, 0.001) == "retake"
    assert audio_analysis.verdict(0.95, 0.12) == "retake"      # cut mid-phrase
    songs = {"11": {"recall": 0.9, "tail_rms": 0.001}, "22": {"recall": 0.97, "tail_rms": 0.2}, "33": {"recall": 0.7, "tail_rms": 0.0}}
    assert pick_song(songs) == "11"                            # the clearer song is cut off, so it loses


def test_lipsync_lag_and_verdict():
    t = np.arange(120)
    envelope = np.clip(np.sin(t / 3.0), 0, None)
    mouth = np.roll(envelope, 3)                               # mouth 3 frames late
    r0, r, lag = lipsync_qa.best_lag(mouth, envelope)
    assert r > 0.9 and lag == pytest.approx(3 / 24, abs=1e-3) and r0 < r
    assert lipsync_qa.verdict(0.8, r, lag) == "ok"
    assert lipsync_qa.verdict(0.8, 0.2, 0.0) == "retake"
    assert lipsync_qa.verdict(0.3, 0.9, 0.0) == "unreliable"   # face not detected: never a misleading number


def _spec(**extra):
    spec = {"title": "t", "song": {"lyrics": "a\nb", "caption": "pop", "duration": 30, "bpm": 120}, "style": {},
            "shots": [{"key": "intro", "kind": "still", "t0": 0, "still": "k"},
                      {"key": "s0", "kind": "h3", "line": 0, "frame": "f", "action": "a"},
                      {"key": "s1", "kind": "still", "line": 1, "still": "k"}]}
    spec.update(extra)
    return spec


def test_validate_spec_rejects_what_the_run_cannot_do():
    assert validate_spec(_spec())["title"] == "t"
    with pytest.raises(ProductionError):
        validate_spec(_spec(shots=[{"key": "x", "kind": "h3", "frame": "f"}]))
    with pytest.raises(ProductionError):
        validate_spec(_spec(shots=[{"key": "x", "kind": "still"}, {"key": "x", "kind": "still"}]))


def test_windows_segments_and_instrumental_fill():
    score = {"duration": 30.0, "beat": 0.5, "lines": [{"t0": 1.0, "t1": 3.0}, {"t0": 20.0, "t1": 22.0}]}
    windows = shot_windows(_spec(), score)
    assert [(w["key"], w["t0"]) for w in windows] == [("intro", 0.0), ("s0", 0.75), ("s1", 19.75)]
    assert h3_frames_for(windows[1]["t1"] - windows[1]["t0"]) == 124
    fill = [{"kind": "still", "still": "k"}]
    segs = segments(windows, score, lambda key: key == "s0", fill)
    keys = [s["key"] for s, _, _ in segs]
    assert keys[:2] == ["intro", "s0"] and keys[2].startswith("s0_fill") and keys[-1] == "s1"
    assert all(b - a <= 4.0 + 1e-6 for s, a, b in segs if s["key"].startswith("s0_fill"))  # two bars max
    assert segs[-1][2] == 30.0 and all(abs(segs[i][2] - segs[i + 1][1]) < 1e-6 for i in range(len(segs) - 1))


def test_status_summary_is_short():
    state = {"status": "running", "song": {"file": "s.wav"}, "clips": {"a": {"qa": {"verdict": "ok"}}}, "scenes": {"a": {"file": "x.mp4"}},
             "log": [f"line {i}" for i in range(30)], "final": "v.mp4"}
    summary = status_summary(state, "ws")
    assert summary["clips"] == {"a": "ok"} and summary["video"] == "/api/v1/file/v.mp4?workspace=ws" and len(summary["log"]) == 8


def test_video_layer_can_skip_the_head_of_its_clip_for_the_whole_scene():
    doc = {"version": 1, "name": "p", "width": 1920, "height": 1080, "fps": 24, "duration": 4, "layers": [], "texts": []}
    ops = [{"op": "add_layer", "id": "v", "source": "/examples/clip.mp4", "type": "video"},
           {"op": "update_layer", "id": "v", "patch": {"animation": {"trimStart": 0.5, "duration": 4.5}}}]
    layer = edit({"version": 1, "input": {"document": doc, "operations": ops, "full": True}})["result"]["document"]["layers"][0]
    assert layer["animation"]["trimStart"] == 0.5 and layer["animation"]["duration"] == 4.5
    too_long = [ops[0], {"op": "update_layer", "id": "v", "patch": {"animation": {"duration": 4.5}}}]
    with pytest.raises(Exception):
        edit({"version": 1, "input": {"document": doc, "operations": too_long, "full": True}})
