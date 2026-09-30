"""H3 status performance copied onto timing.shots. Missing fields stay null."""
from __future__ import annotations

from services.music_production import Production
from services.production_timing import StageWatch, note_clip_performance, timing_summary


def test_note_clip_performance_copies_only_keys_that_exist():
    state = {}
    note_clip_performance(state, "a", {"performance": {"s_per_step": 0, "degraded": False, "extra": 9}})
    assert state["clip_perf"]["a"] == {"s_per_step": 0, "degraded": False, "model": None}
    assert "extra" not in state["clip_perf"]["a"]
    note_clip_performance(state, "b", {"status": "completed"})
    assert state["clip_perf"]["b"] == {"s_per_step": None, "degraded": None, "model": None}
    note_clip_performance(state, "c", {"performance": None})
    assert state["clip_perf"]["c"]["model"] is None
    note_clip_performance(state, "d", {"performance": {"model": "minimax_h3_fused_turbo", "s_per_step": None}})
    assert state["clip_perf"]["d"]["s_per_step"] is None
    assert state["clip_perf"]["d"]["model"] == "minimax_h3_fused_turbo"


def test_timing_rows_gain_phase_fields_without_dropping_the_old_ones():
    bare = {"timing": {"shots": [{"key": "a", "seconds": 3, "takes": 1}]}}
    assert timing_summary(bare)["shots"] == [{"key": "a", "seconds": 3, "takes": 1}]
    state = {
        "timing": {"shots": [{"key": "a", "seconds": 3.2, "takes": 2}]},
        "clip_perf": {"a": {"s_per_step": 22.5, "degraded": True, "model": "h3"}},
    }
    row = timing_summary(state)["shots"][0]
    assert row["key"] == "a" and row["seconds"] == 3 and row["takes"] == 2
    assert row["s_per_step"] == 22.5 and row["degraded"] is True and row["model"] == "h3"


def test_the_watch_publishes_phase_fields_from_clip_perf():
    production = type("P", (), {"state": {
        "clip_seconds": {"a": 7.5},
        "clip_takes": {"a": 2},
        "clip_perf": {"a": {"s_per_step": 21.0, "degraded": False, "model": "h3"}},
    }})()
    StageWatch(production, clock=lambda: 0.0).call("clips", lambda: None)
    assert production.state["timing"]["shots"] == [{
        "key": "a", "seconds": 7.5, "takes": 2, "s_per_step": 21.0, "degraded": False, "model": "h3",
    }]


def test_wait_records_a_completed_job_and_skips_a_failed_one(tmp_path):
    def failed(tool, arguments):
        assert tool == "status"
        return {"status": "failed", "performance": {"s_per_step": 99, "degraded": True, "model": "h3"}}

    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=failed)
    assert production.wait({"a": "job"}, poll=0) == {"a": None}
    assert "clip_perf" not in production.state

    def completed(tool, arguments):
        return {"status": "completed", "output_files": ["a.mp4"], "performance": {"s_per_step": 21, "model": "minimax_h3_fused_turbo"}}

    production.mcp = completed
    assert production.wait({"a": "job"}, poll=0) == {"a": "a.mp4"}
    assert production.state["clip_perf"]["a"] == {"s_per_step": 21, "degraded": None, "model": "minimax_h3_fused_turbo"}
