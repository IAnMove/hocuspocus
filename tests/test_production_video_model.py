"""spec.video: the H3 model that shoots a production's clips is visible and can be chosen.

Without it nothing changes: the same request, the same seeds and intent ids, no clip shot again.
"""
from __future__ import annotations

import copy
import json

import pytest

from services.music_production import Production, ProductionError, shot_windows, status_summary, validate_spec
from services.production_dry_run import dry_run
from services.production_estimate import H3_MINUTES, estimate_minutes, record_observation
from services.production_video_model import DEFAULT_MODEL, VIDEO_MODELS, resolve_video

LYRICS = "[Verse]\nfirst line here\nsecond line here\n[Chorus]\nsing it back\nonce again\n"


def _raw(**extra) -> dict:
    spec = {"title": "Night Bus", "song": {"lyrics": LYRICS, "caption": "pop", "duration": 30, "bpm": 120, "language": "en"},
            "style": {"image": "painterly", "video": "painterly motion"},
            "cast": [{"id": "singer", "sheet_prompt": "a singer"}],
            "shots": [{"key": "v0", "kind": "h3", "line": 0, "sing": True, "cast": ["singer"], "frame": "a singer", "action": "(S1) sings"},
                      {"key": "s0", "kind": "h3", "line": 1, "cast": ["singer"], "frame": "a street",
                       "action": "The protagonist acts out the scene: Night Bus. Clear movement, slow camera."}]}
    spec.update(extra)
    return spec


def _production(tmp_path, sent: list) -> Production:
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.mcp = lambda tool, arguments: sent.append((tool, arguments)) or {"job_id": "job-1"}
    production.upload = lambda name: (f"/up/{name}", f"/api/v1/uploads/{name}")
    production.score = lambda: {"lines": [], "vocals_file": None}
    production.state = {"song": {"file": "song.wav"}, "frames": {"v0": "v0.png", "s0": "s0.png"}}
    return production


def _no_ffmpeg(monkeypatch) -> list:
    """The audio slice is cut by ffmpeg; validate specs before this (it replaces subprocess.run everywhere)."""
    cut = []
    monkeypatch.setattr("services.production_stage_clips.subprocess.run", lambda args, **_kwargs: cut.append(args))
    return cut


def test_the_default_clip_request_is_byte_identical_to_the_hardwired_one(tmp_path, monkeypatch):
    spec = validate_spec(_raw())
    assert "video" not in spec
    _no_ffmpeg(monkeypatch)
    sent: list = []
    production = _production(tmp_path, sent)
    window = {"key": "v0", "kind": "h3", "i": 0, "t0": 2.0, "t1": 6.0, "sing": True, "action": "(S1) sings"}
    assert production.clip_job(spec, window, 7001, 0) == "job-1"
    tool, arguments = sent[0]
    assert tool == "generate" and arguments["request_id"].startswith("p-v0-7001-")
    assert arguments["params"] == {
        "prompt": ("integrated_multimodal_description: [Shot 1] painterly motion (S1) sings (S1) sings the lead vocal of the mapped "
                   "driving audio, lips, jaw and breath in precise sync with every syllable.\noverall_soundscape: The mapped driving "
                   "audio: the song.\nnon_diegetic_music: N/A"),
        "model_type": "minimax_h3_fused_turbo", "resolution": "1280x704", "seed": 7001, "generation_mode": "video",
        "workspace": "ws", "image_prompt_type": "S", "image_start": "/up/v0.png", "video_length": 124, "sliding_window_size": 124,
        "num_inference_steps": 4, "guidance_scale": 1, "image_mode": 0, "input_video_strength": 1.0, "audio_prompt_type": "A",
        "audio_guide": "/up/p-slice-v0-0.wav"}


def test_a_spec_can_pick_base_h3_and_gets_its_own_steps(tmp_path, monkeypatch):
    assert VIDEO_MODELS == ("minimax_h3", "minimax_h3_full", "minimax_h3_fused_turbo", "minimax_h3_legacy")
    spec = validate_spec(_raw(video={"model": "minimax_h3"}))
    assert resolve_video(spec) == {"model": "minimax_h3", "steps": 20, "source": "spec"}
    assert resolve_video(validate_spec(_raw(video={"model": "minimax_h3", "steps": 12})))["steps"] == 12
    assert resolve_video(validate_spec(_raw(video={"steps": 8}))) == {"model": DEFAULT_MODEL, "steps": 8, "source": "spec"}
    _no_ffmpeg(monkeypatch)
    sent: list = []
    production = _production(tmp_path, sent)
    production.clip_job(spec, {"key": "s0", "kind": "h3", "i": 1, "t0": 4.0, "t1": 8.0, "action": "walks"}, 7011, 0)
    params = sent[0][1]["params"]
    assert (params["model_type"], params["num_inference_steps"]) == ("minimax_h3", 20)


@pytest.mark.parametrize("video, words", [
    ({"model": "ltx2_22B"}, "video.model must be one of minimax_h3, minimax_h3_full, minimax_h3_fused_turbo, minimax_h3_legacy"),
    ({"model": "minimax_h3_ref2va"}, "video.model must be one of"),
    ({"model": "minimax_h3", "lora": "x"}, "spec.video is {model, steps}"),
    ({"steps": 0}, "video.steps for minimax_h3_fused_turbo is a whole number from 4 to 8"),
    ({"steps": 12}, "video.steps for minimax_h3_fused_turbo is a whole number from 4 to 8"),
    ({"model": "minimax_h3", "steps": 60}, "video.steps for minimax_h3 is a whole number from 1 to 50"),
    ({"steps": True}, "video.steps"),
    ("minimax_h3", "spec.video is {model, steps}"),
])
def test_other_video_models_are_refused_with_the_list(video, words):
    with pytest.raises(ProductionError) as error:
        validate_spec(_raw(video=video))
    assert error.value.code == "invalid_spec" and words in str(error.value)


def test_the_mcp_schema_closes_the_video_object():
    from services.music_production import SPEC_SCHEMA
    video = SPEC_SCHEMA["properties"]["video"]
    assert video["additionalProperties"] is False and video["properties"]["model"]["enum"] == list(VIDEO_MODELS)
    assert not any(model.startswith("ltx") for model in video["properties"]["model"]["enum"])
    assert SPEC_SCHEMA["properties"]["section_actions"]["additionalProperties"] is False


def _shoot(tmp_path, monkeypatch, spec: dict, state: dict) -> tuple[Production, list]:
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.state = state
    production.upload = lambda name: (name, "/u/" + name)
    production.score = lambda: {"lines": [], "vocals_file": None}
    asked: list = []
    production.clip_job = lambda spec, window, seed, take: asked.append((window["key"], seed)) or f"job-{window['key']}"
    production.wait = lambda jobs: {key: f"{key}-new.mp4" for key in jobs}
    monkeypatch.setattr("services.production_clip_qa.clip_qa", lambda *args: {"verdict": "ok", "best_r": 0.7})
    windows = [{"key": "v0", "kind": "h3", "i": 0, "t0": 2.0, "t1": 6.0, "sing": True}]
    production.clips(spec, windows, pause=0)
    return production, asked


def _legacy_state() -> dict:
    """A record from before spec.video: its clip says nothing about the model that shot it."""
    return {"frames": {"v0": "f.png"}, "clip_takes": {"v0": 1}, "seed_base": 0,
            "clips": {"v0": {"file": "v0-old.mp4", "qa": {"verdict": "ok", "best_r": 0.6}, "url": "/u/v0-old.mp4"}},
            "takes": {"v0": [{"file": "v0-old.mp4", "take": 1, "verdict": "ok", "r": 0.6, "drive": "mix"}]}}


def test_a_legacy_record_with_no_video_shoots_nothing_again(tmp_path, monkeypatch):
    state = _legacy_state()
    before = copy.deepcopy(state["clips"])
    production, asked = _shoot(tmp_path, monkeypatch, {"max_takes": 3}, state)
    assert asked == [] and production.state["clips"] == before
    assert production.state["video_model"] == {"model": "minimax_h3_fused_turbo", "steps": 4, "source": "default"}


def test_another_model_marks_the_kept_clip_and_shoots_it_again(tmp_path, monkeypatch):
    production, asked = _shoot(tmp_path, monkeypatch, {"max_takes": 3, "video": {"model": "minimax_h3"}}, _legacy_state())
    assert asked == [("v0", 7001)]          # 7000 + 10 * i + takes already recorded, as for any retake
    kept = production.state["clips"]["v0"]
    assert kept["file"] == "v0-new.mp4" and (kept["model"], kept["steps"]) == ("minimax_h3", 20) and "obsolete" not in kept
    assert production.state["takes"]["v0"][-1]["model"] == "minimax_h3"
    assert any("shot with minimax_h3_fused_turbo (4 steps), the spec asks for minimax_h3 (20 steps)" in line for line in production.state["log"])
    again, asked_again = _shoot(tmp_path, monkeypatch, {"max_takes": 3, "video": {"model": "minimax_h3"}}, production.state)
    assert asked_again == [], "a clip the chosen model shot is kept"


def test_going_back_to_the_model_that_shot_a_clip_keeps_it(tmp_path, monkeypatch):
    """A run with another model that shoots nothing (cancelled, every take failed) leaves no mark on the kept clips."""
    state = _legacy_state()
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.state = state
    production.upload = lambda name: (name, "/u/" + name)
    production.score = lambda: {"lines": [], "vocals_file": None}
    production.clip_job = lambda spec, window, seed, take: f"job-{window['key']}"
    production.wait = lambda jobs: {key: None for key in jobs}
    production.failures = {}
    windows = [{"key": "v0", "kind": "h3", "i": 0, "t0": 2.0, "t1": 6.0, "sing": True}]
    production.clips({"max_takes": 2, "video": {"model": "minimax_h3"}}, windows, pause=0)
    assert production.state["clips"]["v0"] == _legacy_state()["clips"]["v0"]
    _again, asked = _shoot(tmp_path, monkeypatch, {"max_takes": 3}, production.state)
    assert asked == [], "the Fused Turbo clip is what the default spec asks for"


def test_the_default_steps_do_not_follow_the_model_file(monkeypatch):
    """A new num_inference_steps in app/defaults must not make every earlier clip look shot with other steps."""
    monkeypatch.setattr("services.production_video_model.model_image_steps", lambda model: 6)
    assert resolve_video({})["steps"] == 4 and resolve_video({"video": {"model": DEFAULT_MODEL}})["steps"] == 4
    assert resolve_video({"video": {"model": "minimax_h3"}})["steps"] == 6


def test_a_locked_shot_keeps_its_take_when_the_model_changes(tmp_path, monkeypatch):
    (tmp_path / "p.review.json").write_text(json.dumps({"shots": {"v0": {"locked": True}}}))
    production, asked = _shoot(tmp_path, monkeypatch, {"max_takes": 3, "video": {"model": "minimax_h3"}}, _legacy_state())
    assert asked == [] and "obsolete" not in production.state["clips"]["v0"]


def test_a_take_adopted_by_hand_keeps_the_model_it_was_shot_with(tmp_path):
    from services.production_shot_edit import adopt_take
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.upload = lambda name: (name, "/u/" + name)
    (tmp_path / "v0-b.mp4").write_bytes(b"mp4")
    production.state = {"takes": {"v0": [{"file": "v0-b.mp4", "take": 2, "verdict": "ok", "r": 0.5, "model": "minimax_h3", "steps": 20}]}}
    adopt_take(production, "v0", "v0-b.mp4")
    assert (production.state["clips"]["v0"]["model"], production.state["clips"]["v0"]["steps"]) == ("minimax_h3", 20)


def test_dry_run_and_status_show_the_model_and_where_it_came_from():
    assert dry_run(_raw())["video_model"] == {"model": "minimax_h3_fused_turbo", "steps": 4, "source": "default"}
    assert dry_run(_raw(video={"model": "minimax_h3_legacy"}))["video_model"] == {"model": "minimax_h3_legacy", "steps": 20, "source": "spec"}
    summary = status_summary({"status": "running", "spec": _raw(video={"model": "minimax_h3"})}, "ws")
    assert summary["video_model"]["model"] == "minimax_h3" and "video" in summary      # "video" stays the finished video's URL
    assert status_summary({"status": "running"}, "ws")["video_model"]["source"] == "default"
    refused = dry_run(_raw(video={"model": "ltx2_22B"}))["video_model"]
    assert refused["error"].startswith("video.model must be one of") and refused["source"] == "spec"
    assert "error" in dry_run(_raw(video={"steps": 20}))["video_model"]
    assert "error" not in dry_run(_raw(video={"model": "minimax_h3", "steps": 20}))["video_model"]


def test_the_estimate_is_per_model_and_keeps_the_default_history(tmp_path):
    raw = _raw()
    assert estimate_minutes(raw, 2) == (2 * 3 + H3_MINUTES * 2 + 1, "defaults")
    assert estimate_minutes(_raw(video={"model": "minimax_h3"}), 2) == (2 * 3 + H3_MINUTES * 5 * 2 + 1, "defaults+model_steps")
    timing = {"shots": [{"key": "v0", "seconds": 120.0}], "song": 60.0}
    record_observation(tmp_path, {"timing": timing, "spec": raw})
    record_observation(tmp_path, {"timing": {"shots": [{"key": "v0", "seconds": 900.0}]}, "video_model": {"model": "minimax_h3", "steps": 20}})
    history = json.loads((tmp_path / ".production-timings.json").read_text())
    assert history["clip_s"] == [120.0] and history["clip_s:minimax_h3:20"] == [900.0]
    assert estimate_minutes(raw, 1, tmp_path) == (1 * 3 + 2 + 1, "history(1)")
    assert estimate_minutes(_raw(video={"model": "minimax_h3"}), 1, tmp_path) == (1 * 3 + 15 + 1, "history(1)")


def test_a_stored_record_resumes_with_the_same_spec_seeds_and_intents(tmp_path):
    """A production saved before these defaults became visible: the expanded spec with the old b-roll texts and
    section_actions. A resume revalidates it to the same spec (so the quality gate does not see a new spec), asks for
    the same frame and clip jobs, and draws no frame again."""
    from services.production_quality_gate import refuse_thin_plan
    from services.production_seeds import window_seed
    from services.production_stage_frames import forget_changed_shots

    raw = _raw(section_actions={"verse": "Night Bus", "chorus": "Listen now"}, max_takes=3)
    stored = validate_spec(copy.deepcopy(raw))
    assert validate_spec(copy.deepcopy(stored)) == stored and "video" not in stored
    assert refuse_thin_plan(validate_spec(copy.deepcopy(stored)), stored) == []
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.state = {"spec": stored, "seed_base": 41, "started": 1.0, "cast": {"singer": "/u/singer.png"}, "log": []}
    score = {"duration": 30.0, "bpm": 120, "beat": 0.5,
             "lines": [{"t0": 2.0 * (i + 1), "t1": 2.0 * (i + 1) + 1.6, "text": f"line {i}"} for i in range(4)]}
    windows = shot_windows(stored, score)
    forget_changed_shots(production, stored, windows)
    sources = copy.deepcopy(production.state["h3_sources"])
    production.state["frames"] = {"v0": "v0.png", "s0": "s0.png"}
    production.state["clips"] = {"v0": {"file": "v0.mp4", "qa": {"verdict": "ok"}}}
    resumed = validate_spec(copy.deepcopy(production.state["spec"]))
    forget_changed_shots(production, resumed, shot_windows(resumed, score))
    assert production.state["h3_sources"] == sources and set(production.state["frames"]) == {"v0", "s0"}
    assert "obsolete" not in production.state["clips"]["v0"]
    assert [window_seed(production, 3, int(window["i"])) for window in windows if window["kind"] == "h3"] == [41 + 3, 41 + 3 + 1009]
    jobs: list = []
    production.mcp = lambda tool, arguments: jobs.append(arguments["intent_id"]) or {}
    production.image("frame-v0", "p", None, "1280x704", 44)
    assert jobs == ["p-frame-v0-44"]
