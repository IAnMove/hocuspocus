"""Song candidates stay, and switching marks only the shots whose window moved."""
from __future__ import annotations

import json
from pathlib import Path

from services.music_production import Production
from services.production_song_switch import mark_moved_clips, use_candidate, windows_by_key
from services.production_takes import pending_windows


def _production(tmp_path: Path, state: dict | None = None) -> Production:
    root = tmp_path / "film"
    uploads = tmp_path / "uploads"
    root.mkdir()
    uploads.mkdir()
    if state is not None:
        (root / "show.production.json").write_text(json.dumps(state), encoding="utf-8")
    return Production("film", "show", workspace_dir=lambda _name: str(root), uploads_dir=lambda: str(uploads), mcp=lambda tool, args: _mcp(tool, args))


def _mcp(tool: str, args: dict) -> dict:
    if tool == "generation.music":
        seed = args["input"]["params"]["seed"]
        return {"receipt": {"result": {"job_id": str(seed)}}}
    if tool == "status":
        return {"status": "completed", "output_files": [f"song-{args['job_id']}.wav"]}
    raise AssertionError(tool)


def _spec() -> dict:
    return {
        "title": "Show",
        "song": {"lyrics": "one two", "caption": "one", "duration": 20, "bpm": 120, "seeds": [11, 22]},
        "style": {"lyric_style": {"color": "#111111"}},
        "shots": [
            {"key": "s0", "kind": "h3", "line": 0, "frame": "a face", "action": "sings", "seed": 1},
            {"key": "s1", "kind": "h3", "line": 1, "frame": "a street", "action": "walks", "seed": 2},
        ],
    }


def test_window_move_of_0_3_seconds_keeps_the_clip():
    state = {"clips": {"a": {"file": "a.mp4"}, "b": {"file": "b.mp4"}}}
    obsolete = mark_moved_clips(state, {"a": (0.0, 1.0), "b": (0.0, 1.0)}, {"a": (0.3, 1.3), "b": (0.31, 1.0)})
    assert obsolete == ["b"]
    assert "obsolete" not in state["clips"]["a"]
    assert state["clips"]["b"]["obsolete"] is True


def test_song_keeps_every_candidate(tmp_path: Path, monkeypatch):
    def analyze(path: str, lyrics: str, out_dir: str | None = None) -> dict:
        stem = Path(path).stem
        recall = 0.9 if stem.endswith("11") else 0.4
        return {"recall": recall, "tail_rms": 0.01, "score_file": f"{stem}.score.json"}

    monkeypatch.setattr("services.music_production.audio_analysis.analyze", analyze)
    production = _production(tmp_path)
    production.song(_spec())
    rows = production.state["song_candidates"]
    assert {row["id"] for row in rows} == {"11", "22"}
    assert {row["file"] for row in rows} == {"song-11.wav", "song-22.wav"}
    assert production.state["song"]["file"] == "song-11.wav"
    assert production.state["song"]["recall"] == 0.9


def test_use_candidate_keeps_a_shot_whose_window_barely_moved(tmp_path: Path, monkeypatch):
    score_a = {"duration": 20, "bpm": 120, "beat": 0.5, "recall": 0.9, "lines": [
        {"t0": 1.0, "t1": 3.0, "text": "one"},
        {"t0": 10.0, "t1": 12.0, "text": "two"},
    ]}
    score_b = {"duration": 20, "bpm": 120, "beat": 0.5, "recall": 0.4, "lines": [
        {"t0": 1.1, "t1": 3.1, "text": "one"},
        {"t0": 14.0, "t1": 16.0, "text": "two"},
    ]}
    root = tmp_path / "film"
    spec = _spec()
    state = {
        "spec": spec,
        "song": {"file": "song-11.wav", "recall": 0.9, "tail_rms": 0.01, "score_file": "score-a.json"},
        "score": "score-a.json",
        "song_candidates": [
            {"id": "11", "file": "song-11.wav", "recall": 0.9, "tail_rms": 0.01, "score_file": "score-a.json"},
            {"id": "22", "file": "song-22.wav", "recall": 0.4, "tail_rms": 0.01, "score_file": "score-b.json"},
        ],
        "clips": {"s0": {"file": "s0.mp4"}, "s1": {"file": "s1.mp4"}},
    }
    production = _production(tmp_path, state)
    (root / "score-a.json").write_text(json.dumps(score_a), encoding="utf-8")
    (root / "s0.mp4").write_bytes(b"s0")
    (root / "s1.mp4").write_bytes(b"s1")

    def analyze(path: str, lyrics: str, out_dir: str | None = None) -> dict:
        Path(out_dir or ".").joinpath("score-b.json").write_text(json.dumps(score_b), encoding="utf-8")
        return {"score_file": "score-b.json", "recall": 0.4, "tail_rms": 0.01}

    monkeypatch.setattr("services.music_production.audio_analysis.analyze", analyze)
    before = windows_by_key(spec, score_a)
    after = windows_by_key(spec, score_b)
    assert abs(before["s0"][0] - after["s0"][0]) <= 0.3
    assert abs(before["s0"][1] - after["s0"][1]) <= 0.3
    assert abs(before["s1"][0] - after["s1"][0]) > 0.3
    result = use_candidate(production, spec, "22")
    assert result["song"] == "song-22.wav"
    assert result["obsolete"] == ["s1"]
    assert "s0" in result["kept"]
    assert "obsolete" not in production.state["clips"]["s0"]
    assert production.state["clips"]["s1"]["obsolete"] is True
    assert (root / "s0.mp4").read_bytes() == b"s0"
    assert (root / "s1.mp4").read_bytes() == b"s1"
    windows = [
        {"key": "s0", "kind": "h3", "i": 0, "t0": 0.85, "t1": 3.3},
        {"key": "s1", "kind": "h3", "i": 1, "t0": 13.75, "t1": 16.2},
    ]
    frames = {"frames": {"s0": "f0.png", "s1": "f1.png"}, "clip_takes": {"s0": 4, "s1": 4}}
    pending = pending_windows(windows, {**production.state, **frames}, ())
    assert [row["key"] for row in pending] == ["s1"]
