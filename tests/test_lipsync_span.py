"""Lip-sync is scored on the sung span, not the whole H3 clip."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import lipsync_qa
from services.music_production import Production, shot_windows

ANTHEM = Path("/mnt/extras/hocuspocus-worktrees/claude-pop/app/outputs/omarchy-anthem-20260928")
PRODUCTION = "love-your-computer-20260928.production.json"


def test_span_under_1_5s_is_unreliable_and_does_not_open_the_clip(monkeypatch):
    import cv2

    def opened(*_args, **_kwargs):
        raise AssertionError("opened")

    monkeypatch.setattr(cv2, "VideoCapture", opened)
    short = lipsync_qa.measure("clip.mp4", "audio.wav", 0.0, [0.0, 1.499])
    assert short["verdict"] == "unreliable"
    assert short["reason"] == "sung_span_short"
    assert short["verdict"] != "retake"
    with pytest.raises(AssertionError, match="opened"):
        lipsync_qa.measure("clip.mp4", "audio.wav", 0.0, [0.0, 1.5])


def test_catalog_scores_an_optional_sung_span():
    operation = lipsync_qa.command_catalog()[0]
    props = operation["inputSchema"]["properties"]["input"]["properties"]
    assert props["span"]["maxItems"] == 2
    assert "span" not in operation["inputSchema"]["properties"]["input"]["required"]
    assert lipsync_qa._optional_span({"span": [1, 4.5]}) == [1.0, 4.5]
    assert lipsync_qa._optional_span({}) is None


def test_judge_take_passes_the_shot_window(tmp_path, monkeypatch):
    seen = {}

    def measure(clip, audio, offset=0.0, span=None):
        seen["offset"] = offset
        seen["span"] = span
        return {"verdict": "retake", "best_r": 0.1}

    monkeypatch.setattr("services.music_production.lipsync_qa.measure", measure)
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.upload = lambda name: (name, "/u/" + name)
    production.state = {}
    window = {"key": "a", "t0": 10.0, "t1": 14.0, "sing": True}
    assert production.judge_take(window, "a.mp4", 1, "v.wav") is False
    assert seen["offset"] == 10.0 and seen["span"] == [10.0, 14.0]


def test_short_sung_span_does_not_burn_another_take(tmp_path):
    (tmp_path / "s.score.json").write_text('{"vocals_file": "v.wav", "lines": []}')
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.state = {"score": "s.score.json", "frames": {"a": "f.png"}, "log": []}
    production.upload = lambda name: (name, "/u/" + name)
    seeds = []
    production.clip_job = lambda spec, w, seed, take: seeds.append(seed) or "job"
    production.wait = lambda jobs: {key: "a.mp4" for key in jobs}
    window = {"key": "a", "kind": "h3", "i": 1, "t0": 8.0, "t1": 9.2, "sing": True}
    production.clips({"max_takes": 3}, [window], pause=0)
    assert seeds == [7010]
    assert production.state["clips"]["a"]["qa"]["verdict"] == "unreliable"
    assert production.state.get("clip_failures", {}) == {}
    assert "retake" not in production.state["log"][-1]


def _final_chorus_takes(prod: dict, index: int) -> list[Path]:
    n = int((prod.get("clip_takes") or {}).get("final_chorus") or 0)
    found: list[Path] = []
    for take in range(n):
        found.extend(sorted(ANTHEM.glob(f"*seed{7000 + index * 10 + take}_*.mp4")))
    return found


def test_final_chorus_sung_span_correlates_above_the_whole_clip():
    """Local acceptance. CI skips when the anthem outputs are not on disk."""
    if not ANTHEM.is_dir():
        pytest.skip("omarchy-anthem outputs are local only")
    pytest.importorskip("librosa")
    pose = Path(__file__).resolve().parents[1] / "app" / "ckpts" / "pose" / "yolox_l.onnx"
    if not pose.is_file():
        pytest.skip("pose weights are local only")
    prod = json.loads((ANTHEM / PRODUCTION).read_text())
    score = json.loads((ANTHEM / prod["score"]).read_text())
    window = next(item for item in shot_windows(prod["spec"], score) if item["key"] == "final_chorus")
    vocals = ANTHEM / score["vocals_file"]
    takes = _final_chorus_takes(prod, int(window["i"]))
    assert takes, "final_chorus takes are missing"
    span = [window["t0"], window["t1"]]
    for clip in takes:
        whole = lipsync_qa.measure(str(clip), str(vocals), window["t0"])
        sung = lipsync_qa.measure(str(clip), str(vocals), window["t0"], span)
        print(f"LIPSYNC {clip.name} span={sung.get('best_r')} whole={whole.get('best_r')} window={span} "
              f"sung_verdict={sung.get('verdict')} whole_verdict={whole.get('verdict')}", flush=True)
        assert sung["best_r"] > whole["best_r"]
