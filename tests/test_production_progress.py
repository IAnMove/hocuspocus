"""production.status progress counts shots and only estimates from measured rates."""
from __future__ import annotations

import json

from services.music_production import status_summary
from services.production_progress import progress_summary


def test_progress_counts_h3_and_scenes_and_leaves_eta_null_without_a_rate():
    state = {
        "stage": "clips",
        "spec": {
            "shots": [{"kind": "h3", "key": "a"}, {"kind": "still", "key": "b"}],
            "fill": [{"kind": "h3", "key": "c"}],
        },
        "clips": {"a": {"file": "a.mp4"}},
        "segments": [["a", 0, 1], ["b", 1, 2]],
        "scenes": {"a": {"file": "a.mp4"}, "b": {}},
    }
    progress = progress_summary(state)
    assert progress == {
        "stage": "clips",
        "clips": {"landed": 1, "total": 2, "eta_s": None},
        "scenes": {"done": 1, "total": 2, "eta_s": None},
    }


def test_eta_uses_this_run_before_history(tmp_path):
    (tmp_path / ".production-timings.json").write_text(json.dumps({
        "n": 2, "clips": {"81": [1, 1]}, "scenes": [1, 1], "images": {}, "seeds": [],
    }))
    state = {
        "spec": {"shots": [{"kind": "h3"}, {"kind": "h3"}, {"kind": "h3"}]},
        "clips": {"a": {}},
        "clip_seconds": {"a": 10, "b": 30},
        "segments": [1, 2, 3],
        "scenes": {"a": {"file": "a.mp4"}},
        "scene_seconds": {"a": 4},
        "timing": {"scenes": 100},
    }
    progress = progress_summary(state, str(tmp_path))
    assert progress["clips"]["eta_s"] == 40
    assert progress["scenes"]["eta_s"] == 8


def test_scene_rate_falls_back_to_the_stage_total_and_then_history(tmp_path):
    measured = {"segments": [1, 2, 3], "scenes": {"a": {"file": "a.mp4"}}, "timing": {"scenes": 9}}
    assert progress_summary(measured)["scenes"]["eta_s"] == 18
    (tmp_path / ".production-timings.json").write_text(json.dumps({
        "n": 2, "clips": {"81": [10, 30]}, "scenes": [10, 30], "images": {}, "seeds": [],
    }))
    bare = {"spec": {"shots": [{"kind": "h3"}, {"kind": "h3"}]}, "clips": {}, "segments": [1, 2, 3]}
    progress = progress_summary(bare, str(tmp_path))
    assert progress["clips"] == {"landed": 0, "total": 2, "eta_s": 40}
    assert progress["scenes"]["eta_s"] == 60
    assert progress_summary({"segments": [], "scenes": {}})["scenes"]["eta_s"] == 0
    assert progress_summary({"clips": {"a": {}, "b": {}}, "spec": {"shots": [{"kind": "h3"}, {"kind": "h3"}]}})["clips"]["eta_s"] == 0


def test_status_summary_includes_progress():
    status = status_summary({"status": "running", "stage": "song"}, "ws")
    assert status["progress"]["stage"] == "song"
    assert status["progress"]["clips"]["eta_s"] == 0
    assert status["progress"]["scenes"]["eta_s"] == 0
