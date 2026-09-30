"""History medians replace dry-run minutes only when a timings file exists."""
from __future__ import annotations

import json

from services.production_dry_run import dry_run
from services.production_estimate import estimate, record_completed


def _spec():
    return {
        "title": "t",
        "song": {"lyrics": "a", "caption": "c", "duration": 30, "bpm": 120, "seeds": [1]},
        "style": {},
        "shots": [{"key": "s", "kind": "h3", "t0": 0, "t1": 4, "frame": "f", "action": "a"}],
    }


def test_dry_run_minutes_stay_on_constants_without_history(tmp_path):
    spec = _spec()
    alone = dry_run(spec)
    placed = dry_run(spec, workspace=str(tmp_path))
    assert alone["estimate_source"] == "defaults"
    assert placed["estimate_source"] == "defaults"
    assert placed["minutes"] == alone["minutes"] == 8.0


def test_dry_run_replaces_minutes_from_history(tmp_path):
    spec = _spec()
    before = dry_run(spec, workspace=str(tmp_path))
    frames = before["windows"][0]["frames"]
    scenes = len(before["windows"])
    (tmp_path / ".production-timings.json").write_text(json.dumps({
        "version": 1, "n": 4, "clips": {str(frames): [600]}, "scenes": [60], "images": {}, "seeds": [120],
    }))
    after = dry_run(spec, workspace=str(tmp_path))
    assert after["minutes"] == round((120 + 600 + 60 * scenes) / 60, 1)
    assert after["estimate_source"] == "history(4)"
    assert after["minutes"] != before["minutes"]


def test_estimate_multiplies_medians_and_skips_a_missing_clip_bucket(tmp_path):
    spec = {"song": {"seeds": [1, 2]}, "style": {}, "shots": []}
    windows = [{"key": "a", "kind": "h3", "frames": 81}, {"key": "b", "kind": "still"}]
    (tmp_path / ".production-timings.json").write_text(json.dumps({
        "n": 4,
        "clips": {"81": [120, 180]},
        "scenes": [30, 50],
        "images": {"1280x704:4": [10, 30]},
        "seeds": [60, 120],
    }))
    judged = estimate(spec, tmp_path, windows)
    assert judged["estimate_source"] == "history(4)"
    assert judged["seconds"] == 430
    assert judged["minutes"] == 7.2
    missing = estimate(spec, tmp_path, [{"kind": "h3", "frames": 100}, {"kind": "still"}])
    assert missing["minutes"] == 9.3
    assert missing["seconds"] == 560


def test_empty_history_matches_the_dry_run_constants(tmp_path):
    spec = {"song": {"seeds": [1, 2]}, "style": {}, "shots": [{"kind": "h3", "key": "a"}]}
    windows = [{"kind": "h3", "frames": 81}, {"kind": "still"}]
    (tmp_path / ".production-timings.json").write_text(json.dumps(
        {"n": 2, "clips": {}, "scenes": [], "images": {}, "seeds": []}
    ))
    judged = estimate(spec, tmp_path, windows)
    assert judged["minutes"] == 10.0
    assert judged["estimate_source"] == "history(2)"


def test_a_corrupt_timings_file_stays_on_defaults(tmp_path):
    (tmp_path / ".production-timings.json").write_text("{")
    judged = estimate({"song": {"seeds": [1]}}, tmp_path)
    assert judged["estimate_source"] == "defaults"
    assert judged["minutes"] == 3.0


def test_record_completed_stores_split_samples(tmp_path):
    state = {
        "status": "completed",
        "spec": {
            "song": {"seeds": [1, 2]},
            "style": {"resolution": "1280x704"},
            "shots": [{"key": "a", "kind": "h3", "frames": 81}],
        },
        "clip_seconds": {"a": 100},
        "frames": {"a": "f.png"},
        "timing": {"song": 180, "frames": 20, "scenes": 40},
        "scenes": {"a": {"file": "a.mp4"}, "b": {"file": "b.mp4"}},
    }
    record_completed(tmp_path, {**state, "status": "running"})
    assert not (tmp_path / ".production-timings.json").exists()
    record_completed(tmp_path, state)
    data = json.loads((tmp_path / ".production-timings.json").read_text())
    assert data["n"] == 1
    assert data["clips"]["81"] == [100.0]
    assert data["seeds"] == [90.0, 90.0]
    assert data["scenes"] == [20.0, 20.0]
    assert data["images"]["1280x704:4"] == [20.0]
    filed = {**state, "spec": {**state["spec"], "song": {"file": "s.wav", "seeds": [1, 2]}}}
    record_completed(tmp_path, filed)
    again = json.loads((tmp_path / ".production-timings.json").read_text())
    assert again["n"] == 2
    assert again["seeds"] == [90.0, 90.0]
    qwen = {
        **state,
        "spec": {**state["spec"], "style": {"image_model": "qwen_image_21"}, "song": {"file": "s.wav"}},
        "image_seconds": None,
        "timing": {"frames": 40},
        "frames": {"a": "f.png"},
    }
    record_completed(tmp_path, qwen)
    stored = json.loads((tmp_path / ".production-timings.json").read_text())
    assert stored["images"]["1280x704:40"] == [40.0]
