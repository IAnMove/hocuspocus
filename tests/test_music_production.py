"""Music-video production: every decision is made by code and tested here without models."""
from __future__ import annotations

import numpy as np
import pytest

from services import lipsync_qa, song_analysis as audio_analysis
from services.music_production import (Production, ProductionError, failure_reason, h3_frames_for, pick_song, segments,
                                       shot_windows, status_summary, validate_spec)
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


def test_wait_keeps_why_a_job_gave_nothing():
    replies = {"a": [{"status": "running"}, {"status": "completed", "output_files": ["a.mp4"]}],
               "b": [{"status": "failed", "error": "CUDA error:\n out of memory", "oom_info": None}],
               "c": [{"error": {"content": "Job not found"}}] * 5}
    production = Production.__new__(Production)
    production.mcp = lambda tool, arguments: replies[arguments["job_id"]].pop(0)
    names = production.wait({"a": "a", "b": "b", "c": "c", "d": None}, poll=0)
    assert names == {"a": "a.mp4", "b": None, "c": None, "d": None}
    assert production.failures["b"] == "CUDA error: out of memory" and production.failures["d"] == "not admitted"
    assert failure_reason({"status": "failed", "oom_info": {"frames": 192}}) == "out of GPU memory"


def test_failed_takes_keep_their_reason_and_get_new_seeds(tmp_path, monkeypatch):
    (tmp_path / "s.score.json").write_text('{"lines": [], "vocals_file": "v.wav"}')
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.state = {"score": "s.score.json", "frames": {"a": "f.png"}, "log": ["clip a take 1: no output"]}
    production.upload = lambda name: (name, "/u/" + name)
    seeds, outputs = [], iter([None, "a2.mp4"])
    production.clip_job = lambda spec, w, seed, take: seeds.append(seed) or f"job{seed}"

    def wait(jobs):
        production.failures = {"a": "out of GPU memory"}
        return {key: next(outputs) for key in jobs}
    production.wait = wait
    monkeypatch.setattr("services.music_production.lipsync_qa.measure", lambda *a: {"verdict": "ok", "best_r": 0.5})
    window = {"key": "a", "kind": "h3", "i": 0, "t0": 1.0, "t1": 4.0, "sing": True}
    production.clips({"max_takes": 3}, [window], pause=0)
    assert seeds == [7001, 7002]                     # the logged take 1 is not reshot with its old seed
    assert production.state["clips"]["a"]["file"] == "a2.mp4" and production.state["clip_failures"] == {}
    assert "clip a take 2: failed (out of GPU memory)" in production.state["log"][-2]
    summary = status_summary(production.state | {"clip_failures": {"b": "out of GPU memory"}}, "ws")
    assert summary["clips"] == {"b": "failed", "a": "ok"} and summary["failures"] == {"b": "out of GPU memory"}


def test_a_new_clip_reexports_only_its_scene(tmp_path):
    (tmp_path / "s.score.json").write_text('{"duration": 6.0, "beat": 0.5, "lines": []}')
    exported = []

    def mcp(tool, arguments):
        if tool == "scenes.video2d.export":
            exported.append(arguments["input"]["document"]["name"])
            return {"receipt": {"commandId": "c1"}}
        return {"receipt": {"artifacts": [{"name": "new-scene.mp4"}]}}
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.edit = lambda doc, ops: doc
    production.state = {"score": "s.score.json", "clips": {"a": {"file": "new.mp4", "url": "/u/new.mp4"}},
                        "scenes": {"a": {"dur": 3.0, "file": "old-a.mp4", "clip": "old.mp4"}, "b": {"dur": 3.0, "file": "b.mp4", "clip": None}}}
    windows = [{"key": "a", "kind": "h3", "i": 0, "t0": 0.0, "t1": 3.0}, {"key": "b", "kind": "still", "still": "/k.png", "i": 1, "t0": 3.0, "t1": 7.0}]
    production.scenes({"shots": []}, windows)
    assert exported == ["a"] and production.state["scenes"]["a"] == {"intent": "c1", "dur": 3.0, "clip": "new.mp4", "file": "new-scene.mp4"}
