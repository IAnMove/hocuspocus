"""production.run dry_run checks the spec and does not call MCP or start a run."""
from __future__ import annotations

import asyncio
import sys
import time
import types

from services.music_production import RUN, command_handlers, h3_frames_for
from services.production_dry_run import dry_run


def _spy():
    calls = []

    def mcp(tool, arguments):
        calls.append((tool, arguments))
        raise AssertionError("mcp invoked")

    return mcp, calls


def _spec(**extra):
    spec = {
        "title": "123456789012345",
        "song": {"lyrics": "one uncovered line", "caption": "pop", "duration": 30, "bpm": 120},
        "style": {},
        "shots": [{"key": "card", "kind": "still", "t0": 0, "still": "k"}],
    }
    spec.update(extra)
    return spec


def test_uncovered_line_and_long_title_warn_without_mcp():
    mcp, calls = _spy()
    spec = _spec()
    spec["song"] = {**spec["song"], "caption": "c" * 33}
    spec["shots"][0]["title"] = {"fields": {"caption": "c" * 33}}
    started = time.perf_counter()
    result = dry_run(spec, mcp=mcp)
    assert time.perf_counter() - started < 1
    assert calls == []
    assert result["running"] is False
    assert result["windows"] and result["windows"][0]["key"] == "card"
    assert result["h3_frames"] == 0
    assert result["lines_without_shot"] == [{"index": 0, "text": "one uncovered line"}]
    assert result["long_titles"] == [{"field": "title", "text": "123456789012345", "length": 15}]
    assert any(item["length"] == 33 for item in result["long_captions"])
    assert isinstance(result["minutes"], float) and result["minutes"] > 0
    codes = {item["code"] for item in result["warnings"]}
    assert "line_without_shot" in codes and "title_too_long" in codes and "caption_too_long" in codes


def test_h3_window_frames_and_gap_without_fill():
    mcp, calls = _spy()
    shot = {"key": "s0", "kind": "h3", "line": 0, "frame": "f", "action": "a"}
    result = dry_run(_spec(title="Short", shots=[shot]), mcp=mcp)
    assert calls == []
    window = result["windows"][0]
    assert window["frames"] == h3_frames_for(window["t1"] - window["t0"]) == result["h3_frames"]
    assert result["gaps"] and result["gaps"][0]["key"] == "s0"
    assert "gap_without_fill" in {item["code"] for item in result["warnings"]}
    filled = dry_run(_spec(title="Short", shots=[shot], fill=[{"kind": "still", "still": "k"}]), mcp=mcp)
    assert filled["gaps"] == []


def test_auto_shots_stay_unexpanded_when_the_planner_is_missing(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def blocked(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "services.production_shot_plan":
            raise ImportError("hidden")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "services.production_shot_plan", raising=False)
    monkeypatch.setattr(builtins, "__import__", blocked)
    mcp, calls = _spy()
    result = dry_run(_spec(shots="auto"), mcp=mcp)
    assert calls == []
    assert result["expanded"] is False and result["shots"] == "auto"
    assert result["windows"] == []
    assert any(item["code"] == "shots_auto_unavailable" for item in result["warnings"])


def test_auto_shots_expand_when_the_planner_is_present(monkeypatch):
    module = types.ModuleType("services.production_shot_plan")
    module.plan_shots = lambda spec: {**spec, "shots": [{"key": "a", "kind": "still", "t0": 0, "line": 0, "still": "x"}]}
    monkeypatch.setitem(sys.modules, "services.production_shot_plan", module)
    mcp, calls = _spy()
    result = dry_run(_spec(title="Short", shots="auto"), mcp=mcp)
    assert calls == []
    assert result["expanded"] is True and result["shots"] == "expanded"
    assert result["windows"][0]["key"] == "a"
    assert "line_without_shot" not in {item["code"] for item in result["warnings"]}
    assert "shots_auto_unavailable" not in {item["code"] for item in result["warnings"]}


def test_handler_returns_before_the_thread_and_does_not_call_mcp(monkeypatch):
    def forbid(*_args, **_kwargs):
        raise AssertionError("production.run touched the studio")

    monkeypatch.setattr("services.music_production.loopback_mcp", forbid)
    monkeypatch.setattr("services.music_production.threading.Thread", forbid)
    handlers = command_handlers(forbid, forbid, forbid, forbid)
    started = time.perf_counter()
    result = asyncio.run(handlers[RUN]({
        "version": 1,
        "input": {"workspace": "ws", "production_id": "dry", "dry_run": True, "spec": _spec()},
    }))
    assert time.perf_counter() - started < 1
    report = result["result"]
    codes = {item["code"] for item in report["warnings"]}
    assert result["operation"] == RUN and report["running"] is False
    assert "line_without_shot" in codes and "title_too_long" in codes


def _quality_spec(**extra):
    lyrics = "\n".join(f"line {i}" for i in range(8))
    spec = {"title": "t", "song": {"lyrics": lyrics, "caption": "pop", "duration": 80, "bpm": 120, "seeds": [1, 2, 3]}, "style": {},
            "max_takes": 2, "shots": [{"key": "still0", "kind": "still", "line": 0, "span": 8, "still": "a.png"}], "fill": []}
    spec.update(extra)
    return spec


def test_a_mostly_still_video_is_flagged_before_any_gpu_work():
    report = dry_run(_quality_spec())
    assert report["motion"]["static_ratio"] == 1.0 and report["motion"]["longest_shot"] == "still0"
    codes = {item["code"] for item in report["warnings"]}
    assert {"too_static", "long_shot"} <= codes


def test_a_moving_video_with_retakes_and_seeds_has_no_quality_warnings():
    shots = [{"key": f"c{i}", "kind": "h3", "line": i, "frame": "f", "action": "a"} for i in range(8)]
    report = dry_run(_quality_spec(shots=shots))
    assert report["motion"]["static_ratio"] == 0.0 and report["motion"]["avg_shot_s"] == 10.0
    assert not {"too_static", "single_take", "few_song_seeds", "still_reused"} & {item["code"] for item in report["warnings"]}


def test_single_take_few_seeds_and_a_reused_still_are_named():
    shots = [{"key": f"s{i}", "kind": "still", "line": i, "still": "same.png"} for i in range(3)] + [{"key": "h", "kind": "h3", "line": 3, "span": 5, "frame": "f", "action": "a"}]
    spec = _quality_spec(shots=shots, max_takes=1)
    spec["song"]["seeds"] = [7]
    codes = {item["code"]: item for item in dry_run(spec)["warnings"]}
    assert codes["single_take"] and codes["few_song_seeds"]["seeds"] == 1 and codes["still_reused"]["shots"] == 3


def test_the_bar_follows_the_quality_profile():
    shots = [{"key": f"c{i}", "kind": "h3", "line": i, "frame": "f", "action": "a"} for i in range(4)] + [{"key": "s", "kind": "still", "line": 4, "span": 4, "still": "a.png"}]
    spec = _quality_spec(shots=shots)                                     # 80 s, 4 clips: 3 a minute, half the runtime on a still
    codes = {item["code"] for item in dry_run(spec)["warnings"]}
    assert {"too_static", "few_clips"} <= codes
    draft = {item["code"] for item in dry_run({**spec, "quality": "draft"})["warnings"]}
    assert "too_static" not in draft and "few_clips" not in draft          # a draft may be mostly stills
    assert "too_static" in {item["code"] for item in dry_run({**spec, "quality": "max"})["warnings"]}
