"""Frame-time smoothness: a hold, a hitch, and a speed change, blamed on clip, retime, or export."""
from __future__ import annotations

from pathlib import Path

from services.music_production import Production, status_summary
from services.production_smoothness import assess, note_outputs, read_times


def _steady(count=20, step=1 / 24):
    return [index * step for index in range(count)]


def _production(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.state["clips"] = {"s0": {"file": "s0-clip.mp4"}}
    production.state["scenes"] = {"s0": {"file": "s0-scene.mp4"}}
    production.state["final"] = "final.mp4"
    return production


def test_a_steady_cadence_is_ok_even_when_the_clip_is_slow():
    assert assess(_steady())["verdict"] == "ok"
    assert assess(_steady(step=1 / 12))["verdict"] == "ok"
    assert assess(_steady()[:3])["verdict"] == "unreliable"


def test_a_held_frame_fails_and_a_repeated_timestamp_only_watches():
    times = _steady()
    held = times[:8] + [times[8] + 0.5 + offset for offset in times[:12]]
    report = assess(held)
    assert report["verdict"] == "fail"
    assert report["marks"][0]["kind"] == "duplicate"
    assert report["marks"][0]["seconds"] >= 0.4

    repeated = times[:6] + [times[6], times[6]] + times[6:]
    watched = assess(repeated)
    assert watched["verdict"] == "watch"
    assert watched["marks"][0]["kind"] == "duplicate"


def test_one_dropped_frame_is_a_hitch_and_a_slow_stretch_is_a_speed_change():
    times = _steady()
    hitch = times[:8] + [stamp + (1 / 24) for stamp in times[8:]]
    assert assess(hitch)["verdict"] == "watch"
    assert assess(hitch)["marks"][0]["kind"] == "cadence"

    start = times[5]
    slow = [start + index * (2 / 24) for index in range(1, 8)]
    stretch = times[:6] + slow + [slow[-1] + offset for offset in times[1:8]]
    changed = assess(stretch)
    assert changed["verdict"] == "fail"
    assert changed["marks"][0]["kind"] == "speed"


def test_the_same_jerk_is_blamed_on_the_clip_then_the_retime_then_the_export(tmp_path):
    production = _production(tmp_path)
    steady = _steady()
    held = steady[:8] + [steady[8] + 0.5 + offset for offset in steady[:12]]
    hitch = steady[:8] + [stamp + (1 / 24) for stamp in steady[8:]]
    files = {
        "s0-clip.mp4": held,
        "s0-scene.mp4": held,
        "final.mp4": held,
    }
    production.frame_times = lambda path: files[Path(path).name]
    note_outputs(production, "clip")
    note_outputs(production, "scene")
    note_outputs(production, "final")
    summary = status_summary(production.state, "ws")["smoothness"]
    assert summary["stages"] == {"clip": "fail", "scene": "fail", "final": "fail"}
    assert {row["source"] for row in summary["marks"]} == {"clip"}

    files["s0-clip.mp4"] = steady
    files["s0-scene.mp4"] = hitch
    files["final.mp4"] = hitch
    note_outputs(production, "clip")
    note_outputs(production, "scene")
    note_outputs(production, "final")
    summary = status_summary(production.state, "ws")["smoothness"]
    assert summary["stages"] == {"scene": "watch", "final": "watch"}
    assert {row["source"] for row in summary["marks"]} == {"retime"}

    files["s0-scene.mp4"] = steady
    files["final.mp4"] = held
    note_outputs(production, "scene")
    note_outputs(production, "final")
    summary = status_summary(production.state, "ws")["smoothness"]
    assert summary["stages"] == {"final": "fail"}
    assert summary["marks"][0]["source"] == "export"


def test_a_missing_file_and_an_animatic_add_no_verdict(tmp_path):
    production = _production(tmp_path)
    note_outputs(production, "clip")
    assert production.state["smoothness"]["clip"] == {}
    assert "smoothness" not in status_summary(production.state, "ws")
    assert read_times(tmp_path / "nope.mp4") is None

    production.frame_times = lambda path: _steady()[:8] + [1.0]
    production.state["caption_gate"] = "warn"
    note_outputs(production, "final")
    assert "final" not in production.state["smoothness"]
