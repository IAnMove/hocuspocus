"""Phase close: long wait, ETA, estimate, usage seconds, review, resolution. No GPU."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.music_production import STATUS, Production, ProductionError, command_handlers
from services.production_close import close_run, note_resume
from services.production_enhance import enhance_clips
from services.production_estimate import EXTRA_MINUTES_PER_CLIP, estimate_minutes
from services.production_perf import remember_performance
from services.production_progress import progress_summary
from services.production_publication import OPERATION, publication_handlers
from services.production_resolution import check_resolution, clip_resolution, crop_plan, frame_resolution
from services.production_shot_redo import redo, undo
from services.production_shot_request import RequestError, request_shot, resolve_plan, validate_plan
from services.production_shot_review import (
    ReviewError, apply_artistic, assert_publishable, assert_retake_unlocked, is_locked, load_review,
    record_decision, unlocked_windows,
)
from services.production_timing import timing_summary
from services.production_usage import usage_summary
from services.production_wait import normalize_until, wait_for_status
from services.scene_export_lane import ENV, scene2d_render_lane

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "agents" / "VIDEO_PRODUCTION_RUNBOOK.md"
BOARD = ROOT / "docs" / "development" / "PRODUCTION_WORK_BOARD.md"


def _production(tmp_path: Path) -> Production:
    return Production("ws", "p", workspace_dir=lambda _name: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=lambda _tool, _arguments: {})


def _handlers(tmp_path: Path):
    return command_handlers(lambda _name: str(tmp_path), lambda: str(tmp_path), lambda: "http://127.0.0.1", lambda: "token")


def test_until_rejects_unknown_values_and_accepts_the_three_modes():
    assert normalize_until(None) == "change"
    assert normalize_until("") == "change"
    assert normalize_until("done") == "done"
    with pytest.raises(HTTPException) as caught:
        normalize_until("later")
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "invalid_command"


def test_done_returns_immediately_and_stage_waits_for_the_stage_name(tmp_path):
    path = tmp_path / "song.production.json"
    path.write_text(json.dumps({"status": "completed", "stage": "montage"}))

    async def boom(_seconds: float) -> None:
        raise AssertionError("slept")

    done = asyncio.run(wait_for_status(path, 30, until="done", clock=lambda: 0.0, sleep=boom))
    assert done["status"] == "completed"
    assert done["waited_s"] == 0
    assert asyncio.run(_stage_flip(path)) == ("frames", 2)


async def _stage_flip(path: Path) -> tuple[str, int]:
    clock = {"t": 0.0}
    path.write_text(json.dumps({"status": "running", "stage": "song"}))

    async def sleep(seconds: float) -> None:
        clock["t"] += seconds
        if clock["t"] >= 2:
            path.write_text(json.dumps({"status": "running", "stage": "frames"}))

    state = await wait_for_status(path, 10, until="stage", clock=lambda: clock["t"], sleep=sleep, poll_s=1)
    return state["stage"], state["waited_s"]


def test_change_ignores_a_stage_only_flip(tmp_path):
    path = tmp_path / "song.production.json"
    clock = {"t": 0.0}
    path.write_text(json.dumps({"status": "running", "stage": "song"}))

    async def sleep(seconds: float) -> None:
        clock["t"] += seconds
        if clock["t"] >= 1:
            path.write_text(json.dumps({"status": "running", "stage": "frames"}))

    state = asyncio.run(wait_for_status(path, 3, until="change", clock=lambda: clock["t"], sleep=sleep, poll_s=1))
    assert state["status"] == "running"
    assert state["stage"] == "frames"
    assert state["waited_s"] == 3


def test_status_surfaces_waited_s_and_rejects_a_bad_until(tmp_path):
    (tmp_path / "clip.production.json").write_text(json.dumps({"status": "running"}))
    handlers = _handlers(tmp_path)
    body = {"version": 1, "input": {"workspace": "ws", "production_id": "clip", "wait_s": 0, "until": "change"}}
    result = asyncio.run(handlers[STATUS](body))
    assert result["result"]["waited_s"] == 0
    assert "waited_s" not in json.loads((tmp_path / "clip.production.json").read_text())
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers[STATUS]({"version": 1, "input": {"workspace": "ws", "production_id": "clip", "until": "later"}}))
    assert caught.value.detail["code"] == "invalid_command"


def test_progress_eta_is_null_without_samples_and_a_median_when_it_has_them(tmp_path):
    waiting = {"spec": {"shots": [{"kind": "h3", "key": "a"}]}, "clips": {}, "segments": [{}], "scenes": {}}
    assert progress_summary(waiting)["clips"] == {"landed": 0, "total": 1, "eta_s": None}
    assert progress_summary(waiting)["scenes"]["eta_s"] is None
    assert progress_summary({})["clips"]["eta_s"] == 0
    running = {
        "stage": "clips",
        "spec": {"shots": [{"kind": "h3", "key": "a"}, {"kind": "h3", "key": "b"}]},
        "clips": {"a": {"file": "a.mp4"}},
        "segments": [{}, {}],
        "scenes": {"a": {"file": "s.mp4"}},
        "timing": {"shots": [{"seconds": 10}, {"seconds": 30}]},
    }
    assert progress_summary(running)["clips"]["eta_s"] == 30
    assert progress_summary(running)["scenes"]["eta_s"] is None
    (tmp_path / ".production-timings.json").write_text(json.dumps({"scene_s": [8]}))
    assert progress_summary(running, str(tmp_path))["scenes"]["eta_s"] == 8
    running["clips"]["b"] = {"file": "b.mp4"}
    assert progress_summary(running)["clips"]["eta_s"] == 0


def test_estimate_uses_defaults_then_history_and_labels_the_enhance_default(tmp_path):
    assert estimate_minutes({"song": {}}, 2) == (17.0, "defaults")
    assert estimate_minutes({"song": {"file": "song.wav"}}, 2) == (11.0, "defaults")
    (tmp_path / ".production-timings.json").write_text(json.dumps({"clip_s": [120, 180]}))
    minutes, source = estimate_minutes({"song": {}}, 2, tmp_path)
    assert source == "history(2)"
    assert minutes == 13.0
    enhanced, labeled = estimate_minutes({"song": {}, "enhance": {"method": "flashvsr", "scale": 2}}, 2, tmp_path)
    assert labeled == "history(2)+default_enhance"
    assert enhanced == minutes + EXTRA_MINUTES_PER_CLIP * 2
    plain, plain_source = estimate_minutes({"song": {}, "enhance": {"method": "rife"}}, 2)
    assert plain_source == "defaults"
    assert plain == 19.0


def test_dry_run_hook_reports_source_and_horizontal_crop_for_1280x704():
    from services.production_dry_run import _crop, _minutes
    assert _minutes({"song": {"file": "a.wav"}}, 1, None) == (6.0, "defaults")
    plan = _crop({})
    assert plan == {"source": "1280x704", "target": "1920x1080", "fit": "fill", "crop": "horizontal"}
    assert _crop({"resolution": {"clips": "1024x576"}})["crop"] == "none"


def test_resolution_allow_list_and_memory_step_down():
    assert check_resolution({"resolution": {"frames": "1024x1536", "clips": "1152x640"}, "enhance": {"method": "rife"}})["enhance"]["method"] == "rife"
    with pytest.raises(ProductionError) as bad_frame:
        check_resolution({"resolution": {"frames": "999x999"}})
    assert bad_frame.value.code == "invalid_spec"
    with pytest.raises(ProductionError):
        check_resolution({"enhance": {"method": "flashvsr", "scale": 3}})
    assert frame_resolution({}, 0, "") == "1280x704"
    assert frame_resolution({}, 1, "out of GPU memory") == "1152x640"
    assert frame_resolution({"resolution": {"frames": "1024x1536"}}, 0, "") == "1024x1536"
    assert clip_resolution({}) == "1280x704"
    assert crop_plan({"resolution": {"clips": "1024x576"}})["crop"] == "none"


def test_usage_seconds_come_from_timing_and_takes():
    state = {
        "timing": {"song": 10, "frames": 2.4, "clips": 3, "scenes": 4, "montage": 1, "package": 1},
        "clip_seconds": {"a": 10, "b": 4},
        "clip_takes": {"a": 2, "b": 1},
        "kept_clips": ["a", "b"],
        "runs": [{"retake": ["a"]}],
    }
    usage = usage_summary(state)
    assert usage["gpu_seconds"] == 15
    assert usage["cpu_seconds"] == 6
    assert usage["retry_seconds"] == 5
    assert usage["reused_seconds"] == 4


def test_a_second_log_inside_five_seconds_waits_and_a_clip_still_writes(tmp_path, monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr("services.production_state._clock", lambda: now["t"])
    production = _production(tmp_path)
    production.log("one")
    production.log("two")
    disk = json.loads((tmp_path / "p.production.json").read_text())
    assert disk["log"] == ["one"]
    assert production.state["log"] == ["one", "two"]
    production.state["clips"] = {"a": {"file": "a.mp4"}}
    production.save()
    disk = json.loads((tmp_path / "p.production.json").read_text())
    assert disk["clips"]["a"]["file"] == "a.mp4"
    assert disk["log"] == ["one", "two"]
    now["t"] += 5
    production.log("three")
    disk = json.loads((tmp_path / "p.production.json").read_text())
    assert disk["log"] == ["one", "two", "three"]


def test_close_run_stores_the_run_and_history_only_when_completed(tmp_path):
    production = _production(tmp_path)
    production.state.update(status="running", clips={"a": {"file": "a.mp4"}, "b": {}}, timing={"song": 60, "shots": [{"seconds": 12}], "scenes": 4}, scenes={"a": {"file": "s.mp4"}})
    note_resume(production)
    assert production.state["kept_clips"] == ["a"]
    close_run(production, ("a",))
    assert production.state["runs"][-1]["retake"] == ["a"]
    assert not (tmp_path / ".production-timings.json").exists()
    production.state["status"] = "completed"
    close_run(production, ())
    body = json.loads((tmp_path / ".production-timings.json").read_text())
    assert body["clip_s"] == [12.0]
    assert body["seed_min"] == [1.0]


def test_enhance_is_planned_until_an_upscaler_is_injected_and_rife_only_recommends():
    logs: list[str] = []

    class Recorder:
        def __init__(self):
            self.state = {"clips": {"a": {"file": "a.mp4"}}}
            self.upscaler = None

        def log(self, line: str) -> None:
            logs.append(line)

    production = Recorder()
    enhance_clips(production, {})
    assert logs == []
    enhance_clips(production, {"enhance": {"method": "flashvsr", "scale": 4}})
    assert logs == ["enhance planned, not run"]
    calls: list[tuple] = []
    production.upscaler = lambda file, method, scale: calls.append((file, method, scale))
    enhance_clips(production, {"enhance": {"method": "flashvsr", "scale": 4}})
    assert calls == [("a.mp4", "flashvsr2", 4)]
    assert production.state["enhance"]["ran"] is True
    enhance_clips(production, {"enhance": {"method": "rife"}})
    assert "rife_recommended" not in production.state
    production.state["smoothness"] = {"clip": {"a": {"verdict": "fail"}}}
    enhance_clips(production, {"enhance": {"method": "rife"}})
    assert production.state["rife_recommended"] is True


def test_clip_performance_is_omitted_until_the_job_sends_it():
    state: dict = {}
    remember_performance(state, "a", {"status": "completed"})
    assert "clip_perf" not in state
    remember_performance(state, "a", {"performance": {}})
    assert state["clip_perf"]["a"] == {"s_per_step": None, "degraded": None, "model": None}
    bare = timing_summary({"timing": {"shots": [{"key": "a", "seconds": 1, "takes": 1}]}})
    assert bare["shots"][0] == {"key": "a", "seconds": 1, "takes": 1}
    published = timing_summary({"timing": {"shots": [{"key": "a", "seconds": 1, "takes": 1}]}, "clip_perf": state["clip_perf"]})
    assert published["shots"][0]["s_per_step"] is None
    assert published["shots"][0]["model"] is None


def test_artistic_overlay_never_uses_ok(tmp_path):
    summary = {"review": {"artistic": {"verdict": "pending"}}}
    apply_artistic(summary, tmp_path, "p")
    assert summary["review"]["artistic"]["verdict"] == "pending"
    assert "source" not in summary["review"]["artistic"]
    record_decision(tmp_path, "p", "s0", status="approved")
    apply_artistic(summary, tmp_path, "p")
    assert summary["review"]["artistic"]["verdict"] == "approved"
    assert summary["review"]["artistic"]["source"] == "human"
    record_decision(tmp_path, "p", "s1", status="changes_requested")
    apply_artistic(summary, tmp_path, "p")
    assert summary["review"]["artistic"]["verdict"] == "changes_requested"
    assert summary["review"]["artistic"]["verdict"] != "ok"
    with pytest.raises(ReviewError) as caught:
        record_decision(tmp_path, "p", "s0", status="ok")
    assert caught.value.code == "invalid_review"


def test_locked_shots_are_skipped_and_an_explicit_retake_is_refused(tmp_path):
    production = _production(tmp_path)
    record_decision(tmp_path, "p", "s0", locked=True)
    windows = [{"key": "s0"}, {"key": "s1"}]
    assert is_locked(production, "s0") is True
    assert is_locked(production, "s1") is False
    assert unlocked_windows(production, windows) == [{"key": "s1"}]
    with pytest.raises(ProductionError) as caught:
        unlocked_windows(production, windows, ("s0",))
    assert caught.value.code == "shot_locked"


def test_run_refuses_a_locked_retake_before_changing_status(tmp_path):
    production = _production(tmp_path)
    production.state.update(status="completed", spec={"shots": [{"key": "s0"}]}, final="v.mp4")
    production.save()
    record_decision(tmp_path, "p", "s0", locked=True)
    with pytest.raises(ProductionError) as caught:
        production.run(production.state["spec"], retake=("s0",))
    assert caught.value.code == "shot_locked"
    disk = json.loads((tmp_path / "p.production.json").read_text())
    assert disk["status"] == "completed"
    assert disk.get("final") == "v.mp4"
    assert_retake_unlocked(production, ())
    with pytest.raises(ProductionError):
        assert_retake_unlocked(production, ("s0",))


def test_publish_requires_every_shot_when_the_spec_lists_them(tmp_path):
    assert_publishable(tmp_path, "p", {"spec": {"title": "Night"}})
    state = {"spec": {"shots": [{"key": "s0"}, {"key": "s1"}]}}
    with pytest.raises(ValueError, match="review_required: s0, s1"):
        assert_publishable(tmp_path, "p", state)
    record_decision(tmp_path, "p", "s0", status="approved")
    with pytest.raises(ValueError, match="review_required: s1"):
        assert_publishable(tmp_path, "p", state)
    record_decision(tmp_path, "p", "s1", status="approved")
    assert_publishable(tmp_path, "p", state)


def test_publish_handler_maps_review_required(monkeypatch):
    def boom(*_args, **_kwargs):
        raise ValueError("review_required: s0")

    monkeypatch.setattr("services.production_publication.publish_production", boom)
    handlers = publication_handlers(lambda _name: "/tmp")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers[OPERATION]({"version": 1, "input": {"workspace": "ws", "production_id": "clip"}}))
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "review_incomplete"


def test_shot_plan_rejects_unknown_ops_extra_fields_and_paths():
    plan = {"summary": "shorter title", "changes": [{"op": "note", "text": "shorter"}]}
    assert validate_plan(plan)["summary"] == "shorter title"
    assert resolve_plan({"plan": plan})["changes"][0]["op"] == "note"
    with pytest.raises(RequestError) as missing:
        resolve_plan({"instruction": "make it shorter"})
    assert missing.value.code == "llm_unavailable"
    with pytest.raises(RequestError) as unknown:
        validate_plan({"summary": "x", "changes": [{"op": "explode"}]})
    assert unknown.value.code == "invalid_plan"
    with pytest.raises(RequestError):
        validate_plan({"summary": "x", "changes": [{"op": "note", "text": "a", "camera": "wide"}]})
    with pytest.raises(RequestError):
        validate_plan({"summary": "look at ../secret", "changes": []})


def test_redo_uses_injected_shooters_and_undo_restores_without_deleting(tmp_path):
    kept = tmp_path / "c.mp4"
    kept.write_bytes(b"clip")
    calls: list[tuple] = []
    production = _production(tmp_path)
    production.state = {
        "frames": {"s0": "f.png"},
        "clips": {"s0": {"file": str(kept)}},
        "scenes": {"s0": {"file": "s.mp4"}},
        "spec": {"shots": [{"key": "s0", "camera": "wide"}]},
    }
    production._attempt = lambda bucket, key: calls.append(("attempt", bucket, key))
    spec = production.state["spec"]

    def shoot_frame(_production, _spec, key, prompt):
        calls.append(("frame", key, prompt))
        _production.state.setdefault("frames", {})[key] = "new.png"

    def shoot_clip(_production, _spec, key, action):
        calls.append(("clip", key, action))
        _production.state.setdefault("clips", {})[key] = {"file": "new.mp4"}

    def export_scene(_production, _spec, key):
        calls.append(("scene", key))

    redo(production, spec, "s0", "frame", frame_prompt="closer", shoot_frame=shoot_frame, shoot_clip=shoot_clip, export_scene=export_scene)
    assert ("frame", "s0", "closer") in calls
    assert ("attempt", "frame_attempts", "s0") in calls
    assert production.state["frames"]["s0"] == "new.png"
    history = load_review(tmp_path, "p")["shots"]["s0"]["history"]
    assert history[0]["snapshot"]["frame"] == "f.png"
    undo(production, spec, "s0", history[0]["id"], export_scene=export_scene)
    assert production.state["frames"]["s0"] == "f.png"
    assert calls[-1] == ("scene", "s0")
    assert kept.exists()
    with pytest.raises(ProductionError) as caught:
        redo(production, spec, "s0", "audio", shoot_frame=shoot_frame, shoot_clip=shoot_clip, export_scene=export_scene)
    assert caught.value.code == "invalid_redo"


def test_redo_of_a_locked_shot_does_not_drop_the_frame(tmp_path):
    """frames() skips locked keys, so popping before the shoot would save a hole."""
    calls: list[tuple] = []
    production = _production(tmp_path)
    production.state = {
        "frames": {"s0": "f.png"},
        "clips": {"s0": {"file": "c.mp4"}},
        "scenes": {"s0": {"file": "s.mp4"}},
        "spec": {"shots": [{"key": "s0", "kind": "h3"}]},
    }
    record_decision(tmp_path, "p", "s0", locked=True)
    spec = production.state["spec"]

    def shoot_frame(_production, _spec, key, prompt):
        calls.append(("frame", key, prompt))

    def shoot_clip(_production, _spec, key, action):
        calls.append(("clip", key, action))

    def export_scene(_production, _spec, key):
        calls.append(("scene", key))

    with pytest.raises(ProductionError) as caught:
        redo(production, spec, "s0", "frame", frame_prompt="closer", shoot_frame=shoot_frame, shoot_clip=shoot_clip, export_scene=export_scene)
    assert caught.value.code == "shot_locked"
    assert production.state["frames"]["s0"] == "f.png"
    assert production.state["clips"]["s0"]["file"] == "c.mp4"
    assert calls == []
    with pytest.raises(ProductionError) as clip_caught:
        redo(production, spec, "s0", "clip", shoot_frame=shoot_frame, shoot_clip=shoot_clip, export_scene=export_scene)
    assert clip_caught.value.code == "shot_locked"
    assert production.state["clips"]["s0"]["file"] == "c.mp4"
    assert calls == []


def test_undo_of_a_locked_shot_does_not_restore(tmp_path):
    """Review Mode still showed Undo after lock; restoring would replace the approved cut."""
    production = _production(tmp_path)
    production.state = {
        "frames": {"s0": "new.png"},
        "clips": {"s0": {"file": "new.mp4"}},
        "scenes": {"s0": {"file": "new-s.mp4"}},
        "spec": {"shots": [{"key": "s0", "camera": "wide"}]},
    }
    record_decision(tmp_path, "p", "s0", locked=True, snapshot={
        "frame": "old.png",
        "clip": {"file": "old.mp4"},
        "scene": {"file": "old-s.mp4"},
        "shot": {"key": "s0", "camera": "close"},
    })
    history = load_review(tmp_path, "p")["shots"]["s0"]["history"]
    calls: list[str] = []

    def export_scene(_production, _spec, _key):
        calls.append("export")

    with pytest.raises(ProductionError) as caught:
        undo(production, production.state["spec"], "s0", history[0]["id"], export_scene=export_scene)
    assert caught.value.code == "shot_locked"
    assert production.state["frames"]["s0"] == "new.png"
    assert production.state["clips"]["s0"]["file"] == "new.mp4"
    assert production.state["scenes"]["s0"]["file"] == "new-s.mp4"
    assert production.state["spec"]["shots"][0]["camera"] == "wide"
    assert calls == []


def test_failed_clip_redo_keeps_the_previous_take(tmp_path):
    """clips() can finish without a file. The next scenes() would then hold the start frame."""
    production = _production(tmp_path)
    production.state = {
        "frames": {"s0": "f.png"},
        "clips": {"s0": {"file": "keep.mp4", "qa": {"verdict": "ok", "best_r": 0.4}}},
        "scenes": {"s0": {"file": "s.mp4", "clip": "keep.mp4"}},
        "spec": {"shots": [{"key": "s0", "kind": "h3"}]},
    }
    spec = production.state["spec"]

    def shoot_clip(_production, _spec, key, _action):
        assert key not in _production.state.get("clips", {})

    with pytest.raises(ProductionError) as caught:
        redo(production, spec, "s0", "clip", shoot_frame=lambda *_args: None, shoot_clip=shoot_clip, export_scene=lambda *_args: None)
    assert caught.value.code == "redo_failed"
    assert production.state["clips"]["s0"]["file"] == "keep.mp4"
    assert production.state["scenes"]["s0"]["file"] == "s.mp4"


def test_raising_frame_redo_keeps_the_previous_frame(tmp_path):
    production = _production(tmp_path)
    production.state = {
        "frames": {"s0": "f.png"},
        "clips": {"s0": {"file": "c.mp4"}},
        "scenes": {"s0": {"file": "s.mp4"}},
        "spec": {"shots": [{"key": "s0", "kind": "h3"}]},
    }
    production._attempt = lambda bucket, key: None
    spec = production.state["spec"]

    def shoot_frame(_production, _spec, _key, _prompt):
        raise ProductionError("frames_incomplete", "no start frame for s0")

    with pytest.raises(ProductionError) as caught:
        redo(production, spec, "s0", "frame", frame_prompt="closer", shoot_frame=shoot_frame, shoot_clip=lambda *_args: None, export_scene=lambda *_args: None)
    assert caught.value.code == "frames_incomplete"
    assert production.state["frames"]["s0"] == "f.png"
    assert production.state["clips"]["s0"]["file"] == "c.mp4"


def test_apply_uses_the_previewed_plan_without_asking_again(tmp_path):
    production = _production(tmp_path)
    spec = {"shots": [{"key": "s0", "kind": "h3", "frame": "a face", "action": "sings"}]}
    production.state = {"frames": {"s0": "old-frame.png"}, "clips": {}, "spec": spec}
    calls: list[str] = []
    inner = production.mcp

    def counting(tool, arguments):
        calls.append(tool)
        return inner(tool, arguments)

    production.mcp = counting
    asked: list[str] = []

    def note(_instruction):
        asked.append("preview")
        return {"summary": "note only", "changes": [{"op": "note", "text": "keep the take"}]}

    preview = request_shot(production, spec, "s0", "keep it", apply=False, generate=note)
    assert preview["applied"] is False
    assert preview["plan"]["changes"][0]["op"] == "note"

    def hostile(_instruction):
        asked.append("apply")
        return {"summary": "wipe", "changes": [{"op": "redo", "from": "frame", "frame_prompt": "wipe the face"}]}

    applied = request_shot(production, spec, "s0", "keep it", apply=True, generate=hostile, plan=preview["plan"])
    assert applied["applied"] is True
    assert asked == ["preview"]
    assert spec["shots"][0]["frame"] == "a face"
    assert production.state["frames"]["s0"] == "old-frame.png"
    notes = json.loads((tmp_path / "p.review.json").read_text(encoding="utf-8"))["shots"]["s0"]["notes"]
    assert notes == "keep the take"
    assert "generation.image" not in calls
    assert "clip_job" not in calls


def test_scene_export_lane_defaults_to_two_and_rejects_out_of_range(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert scene2d_render_lane().capacity == 2
    monkeypatch.setenv(ENV, "")
    assert scene2d_render_lane().capacity == 2
    monkeypatch.setenv(ENV, "nope")
    assert scene2d_render_lane().capacity == 1
    monkeypatch.setenv(ENV, "5")
    assert scene2d_render_lane().capacity == 1
    monkeypatch.setenv(ENV, "3")
    assert scene2d_render_lane().capacity == 3


def test_runbook_and_board_record_the_phase_close():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "Poll `production.status` with `wait_s` 300 instead of many short polls." in text
    section = text.split("## Phase close 2026-09-30", 1)[1]
    for token in ("1200", "gpu_seconds", "face_consistent", "labeled default", "not measured", "HOCUS_SCENE_EXPORT_CONCURRENCY"):
        assert token in section
    review = text.split("## production.review", 1)[1].split("\n## ", 1)[0]
    assert "must not invent yes or no" in review
    board = BOARD.read_text(encoding="utf-8")
    assert "Cierre 2026-09-30" in board
    assert "#661" in board and "#672" in board
