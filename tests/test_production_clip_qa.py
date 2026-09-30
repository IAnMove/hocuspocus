"""Unsung clips are retaken when the picture is frozen, blinking, or no longer itself."""
from __future__ import annotations

import numpy as np

from services.music_production import Production
from services.production_clip_qa import assess, clip_qa


def _still(color, count=8):
    frame = np.full((32, 48, 3), color, np.uint8)
    return [frame.copy() for _ in range(count)]


def _travel():
    frames = []
    for step in range(12):
        image = np.full((32, 48, 3), 90, np.uint8)
        left = 2 + step * 3
        image[12:20, left:left + 8] = (230, 230, 230)
        frames.append(image)
    return frames


def _blink():
    rng = np.random.default_rng(0)
    base = rng.integers(0, 256, size=(32, 48, 3), dtype=np.uint8)
    return [base if step % 2 == 0 else 255 - base for step in range(8)]


def _wash():
    frames = []
    for step in range(8):
        image = np.full((32, 48, 3), 100, np.uint8)
        image[:, :, 2] = np.clip(100 + step * 22, 0, 255)
        frames.append(image)
    return frames


def _center_swap():
    frames = []
    for step in range(8):
        image = np.full((32, 48, 3), 110, np.uint8)
        if step < 4:
            image[8:24, 8:24] = (20, 20, 220)
            image[8:24, 24:40] = (220, 20, 20)
        else:
            image[8:24, 8:40] = (120, 20, 120)
        frames.append(image)
    return frames


def test_a_frozen_clip_asks_for_another_take_and_a_moving_one_passes():
    frozen = assess(_still(0))
    moving = assess(_travel())
    assert frozen["verdict"] == "retake" and "static" in frozen["reasons"]
    assert frozen["best_r"] is not None and frozen["best_r"] < 1
    assert moving["verdict"] == "ok" and moving["reasons"] == []
    assert moving["motion_mean"] > frozen["motion_mean"]


def test_blink_color_wash_and_center_change_are_named():
    blink = assess(_blink())
    wash = assess(_wash())
    swapped = assess(_center_swap())
    assert "flicker" in blink["reasons"]
    assert "color_drift" in wash["reasons"] and "static" not in wash["reasons"]
    assert "identity" in swapped["reasons"]
    assert assess(_still(40)[:2])["reasons"] == ["unreadable"] and assess(_still(40)[:2])["best_r"] is None


def test_a_sung_shot_still_uses_lip_sync_and_an_unsung_one_uses_the_picture(monkeypatch):
    seen = {}

    def measure(clip, audio, offset=0.0, span=None):
        seen["span"] = span
        return {"verdict": "retake", "best_r": 0.2}

    monkeypatch.setattr("services.lipsync_qa.measure", measure)
    assert clip_qa("a.mp4", True, "v.wav", 10.0, 14.0)["best_r"] == 0.2
    assert seen["span"] == [10.0, 14.0]
    assert clip_qa("a.mp4", True, None, 0.0, 4.0) == {"verdict": "ok"}
    monkeypatch.setattr("services.production_clip_qa.measure_clip", lambda _path: {"verdict": "retake", "best_r": 0.1, "reasons": ["static"]})
    assert clip_qa("a.mp4", False, "v.wav", 0.0, 4.0)["reasons"] == ["static"]


def test_an_unsung_clip_spends_another_seed_until_the_picture_is_ok(tmp_path, monkeypatch):
    answers = iter([
        {"verdict": "retake", "best_r": 0.2, "reasons": ["static"]},
        {"verdict": "ok", "best_r": 0.9, "reasons": []},
    ])
    monkeypatch.setattr("services.production_clip_qa.measure_clip", lambda _path: next(answers))
    monkeypatch.setattr("services.lipsync_qa.measure", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("lipsync")))
    (tmp_path / "s.score.json").write_text('{"lines": [], "vocals_file": "v.wav"}', encoding="utf-8")
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.state = {"score": "s.score.json", "frames": {"a": "f.png"}, "log": []}
    production.upload = lambda name: (name, "/u/" + name)
    seeds = []
    production.clip_job = lambda spec, window, seed, take: seeds.append(seed) or f"job-{seed}"
    files = iter(["t1.mp4", "t2.mp4"])
    production.wait = lambda jobs: {key: next(files) for key in jobs}
    window = {"key": "a", "kind": "h3", "i": 0, "t0": 0.0, "t1": 4.0}
    production.clips({"max_takes": 3}, [window], pause=0)
    assert seeds == [7000, 7001]
    assert production.state["clip_takes"]["a"] == 2
    assert production.state["clips"]["a"]["qa"]["verdict"] == "ok"
    assert production.state["clips"]["a"]["file"] == "t2.mp4"


def test_a_worse_second_picture_stops_instead_of_spending_the_budget(tmp_path, monkeypatch):
    answers = iter([
        {"verdict": "retake", "best_r": 0.4, "reasons": ["static"]},
        {"verdict": "retake", "best_r": 0.1, "reasons": ["static"]},
    ])
    monkeypatch.setattr("services.production_clip_qa.measure_clip", lambda _path: next(answers))
    (tmp_path / "s.score.json").write_text('{"lines": []}', encoding="utf-8")
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.state = {"score": "s.score.json", "frames": {"a": "f.png"}, "log": []}
    production.upload = lambda name: (name, "/u/" + name)
    calls = []
    production.clip_job = lambda spec, window, seed, take: calls.append(seed) or "job"
    files = iter(["t1.mp4", "t2.mp4", "t3.mp4"])
    production.wait = lambda jobs: {key: next(files) for key in jobs}
    production.clips({"max_takes": 3}, [{"key": "a", "kind": "h3", "i": 0, "t0": 0.0, "t1": 4.0}], pause=0)
    assert calls == [7000, 7001]
    assert production.state["clips"]["a"]["file"] == "t1.mp4"
    assert production.state["discarded"] == ["t2.mp4"]
