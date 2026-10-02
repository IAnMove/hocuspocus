"""Comic-film addendum: panels, canvas, PRE recovery, ffmpeg, and acceptance."""

from __future__ import annotations

import json

import pytest

from services import director_pipeline
from services.director_comic_film import (
    repeat_locked_sources,
    resolve_comic_output_resolution,
)
from services.director_video_strategy import (
    adapt_bounded_timeline,
    build_director_video_execution_profile,
)
from services.job_lifecycle import positional_clip_outputs


H3_DEF = {
    "architecture": "minimax_h3",
    "model_type": "minimax_h3_fl2va",
    "fps": 24,
    "frames_minimum": 124,
    "frames_maximum": 345,
    "frames_steps": 17,
    "resolutions": [
        ("960x544 (16:9)", "960x544"),
        ("1280x704 (16:9 720p)", "1280x704"),
    ],
    "resolution_presets": {
        "540p": {"values": {"16:9": "960x544"}},
        "720p": {"values": {"16:9": "1280x704"}},
    },
}


def _panel(index: int, seconds: float) -> tuple[dict, dict]:
    plan = {"video_prompt": f"panel {index}", "image_prompt": ""}
    planned = {
        "start": index * seconds,
        "end": (index + 1) * seconds,
        "duration_sec": seconds,
        "section_label": f"1.{index + 1}",
    }
    return plan, planned


def test_h3_short_comic_panels_stay_one_shot_each():
    plans = []
    timings = []
    for index in range(30):
        plan, planned = _panel(index, 3.5)
        plans.append(plan)
        timings.append(planned)
    bounds = dict(
        fps=24,
        minimum_frames=124,
        maximum_frames=345,
        frame_step=17,
    )

    merged_plans, _merged_timings = adapt_bounded_timeline(
        plans, timings, **bounds,
    )
    kept_plans, kept_timings = adapt_bounded_timeline(
        plans, timings, preserve_source_units=True, **bounds,
    )

    assert len(merged_plans) == 15
    assert len(kept_plans) == 30
    assert len(kept_timings) == 30
    assert all(item["duration_frames"] >= 124 for item in kept_timings)
    images = [f"panel-{index}.png" for index in range(30)]
    assert repeat_locked_sources(images, kept_plans) == images


def test_a_split_locked_panel_repeats_its_image():
    plan, planned = _panel(0, 20.0)
    plans, timings = adapt_bounded_timeline(
        [plan],
        [planned],
        fps=24,
        minimum_frames=124,
        maximum_frames=124,
        frame_step=17,
        preserve_source_units=True,
    )
    assert len(plans) > 1
    aligned = repeat_locked_sources(["only-panel.png"], plans)
    assert aligned == ["only-panel.png"] * len(plans)
    assert len(aligned) == len(timings)


def test_comic_movie_never_returns_prompt_only_policy():
    fresh = {
        "pipeline_type": "comic_movie",
        "shot_image_guidance": "prompt_only",
        "_director_shot_image_policy": "prompt_only",
    }
    saved = {
        "pipeline_type": "comic_movie",
        "shot_image_policy": "prompt_only",
        "generation_mode": "direct_video",
        "_params_snapshot": {
            "pipeline_type": "comic_movie",
            "_director_shot_image_policy": "prompt_only",
        },
    }

    assert director_pipeline._resolve_fresh_shot_image_policy(fresh) == "generate"
    assert director_pipeline._director_effective_shot_image_policy(fresh) == "generate"
    assert director_pipeline._saved_pipeline_shot_image_policy(saved) == "generate"
    assert director_pipeline._director_effective_shot_image_policy({
        "pipeline_type": "music_video",
        "_director_shot_image_policy": "prompt_only",
    }) == "prompt_only"


def test_resume_of_a_comic_pre_keeps_panel_images(tmp_path):
    pipeline_id = "comic-policy"
    fingerprint = "fingerprint-panels"
    (tmp_path / f"_director_pipeline_{pipeline_id}.json").write_text(
        json.dumps({
            "pipeline_id": pipeline_id,
            "status": "preview_ready",
            "pipeline_type": "comic_movie",
            "shot_image_policy": "prompt_only",
            "generation_mode": "direct_video",
            "preview_fingerprint": fingerprint,
            "preview_approved_fingerprint": fingerprint,
            "preview_clips": [{"index": 0, "prompt": "kept"}],
            "clips": [{
                "index": 0,
                "planned_clip": {"start": 0, "end": 3.5},
                "image_prompt": "",
                "video_prompt": "kept",
                "start_image_filename": "comic_panel_0001.png",
            }],
            "_params_snapshot": {
                "pipeline_type": "comic_movie",
                "comic_preflight_only": True,
                "_director_shot_image_policy": "prompt_only",
            },
        }),
        encoding="utf-8",
    )
    try:
        ok, message = director_pipeline.resume_pipeline(pipeline_id, str(tmp_path))
        recovered = director_pipeline.get_pipeline(pipeline_id)
        assert (ok, message) == (True, "recovered_preview")
        assert recovered["params"]["_director_shot_image_policy"] == "generate"
        assert pipeline_id not in director_pipeline._pipeline_threads
    finally:
        director_pipeline._pipelines.pop(pipeline_id, None)


def test_saved_preview_status_stays_preview_ready(tmp_path):
    pipeline_id = "comic-pre-disk"
    fingerprint = "fingerprint-disk"
    (tmp_path / f"_director_pipeline_{pipeline_id}.json").write_text(
        json.dumps({
            "pipeline_id": pipeline_id,
            "status": "preview_ready",
            "pipeline_type": "comic_movie",
            "preview_fingerprint": fingerprint,
            "preview_approved_fingerprint": fingerprint,
            "quality_gate": {
                "status": "pending",
                "fingerprint": fingerprint,
                "required_test_indices": [0],
                "tested_indices": [],
                "results": {},
                "failures": [],
            },
            "preview_clips": [{"index": 0, "prompt": "frozen"}],
            "clips": [{
                "index": 0,
                "planned_clip": {"start": 0, "end": 3.5},
                "image_prompt": "",
                "video_prompt": "frozen",
                "start_image_filename": "comic_panel_0001.png",
            }],
            "_params_snapshot": {
                "pipeline_type": "comic_movie",
                "comic_preflight_only": True,
            },
        }),
        encoding="utf-8",
    )
    director_pipeline._pipelines.pop(pipeline_id, None)
    try:
        status = director_pipeline.get_pipeline_status(pipeline_id, str(tmp_path))
        assert status["status"] == "preview_ready"
        assert status["phase"] == "preview_ready"
        assert "live worker" not in str(status.get("error") or "")
        assert status["_preview_approved_fingerprint"] == fingerprint
        assert status["_comic_preflight_fingerprint"] == fingerprint
        assert pipeline_id not in director_pipeline._pipeline_threads
    finally:
        director_pipeline._pipelines.pop(pipeline_id, None)


def test_positional_clip_outputs_reads_indexed_filenames():
    assert positional_clip_outputs({"1": "b.mp4", "0": "a.mp4"}) == [
        "a.mp4",
        "b.mp4",
    ]
    assert positional_clip_outputs({"0": "a.mp4", "2": "c.mp4"}) == [
        "a.mp4",
        None,
        "c.mp4",
    ]
    assert positional_clip_outputs(["a.mp4", None]) == ["a.mp4", None]
    assert positional_clip_outputs({"shot": "a.mp4"}) == []


def test_ffmpeg_failure_shows_the_tail_and_keeps_the_log(monkeypatch):
    banner = "ffmpeg version 6\nconfiguration: --enable-foo\n" * 80
    stderr = banner + "Is a directory\n"
    seen = {}

    class _Result:
        returncode = 1
        stdout = "stdout-banner\n"

        def __init__(self):
            self.stderr = stderr

    def _run(command, **_kwargs):
        seen["command"] = list(command)
        return _Result()

    monkeypatch.setattr(director_pipeline.subprocess, "run", _run)
    with pytest.raises(director_pipeline.ComicFfmpegError) as caught:
        director_pipeline._run_comic_ffmpeg(["ffmpeg", "-i", "in"], "Comic hold render")

    message = str(caught.value)
    assert message.rstrip().endswith("Is a directory")
    assert caught.value.ffmpeg_stderr == stderr
    assert len(caught.value.ffmpeg_stderr) > len(message)
    update = director_pipeline._pipeline_failure_update(caught.value, None)
    assert update["ffmpeg_stderr"] == stderr
    assert update["error"].rstrip().endswith("Is a directory")

    captured = []

    def _boom(command, label):
        captured.append(list(command))
        raise director_pipeline.ComicFfmpegError(label, "Is a directory", "")

    monkeypatch.setattr(director_pipeline, "_run_comic_ffmpeg", _boom)
    with pytest.raises(director_pipeline.ComicFfmpegError):
        director_pipeline._render_deterministic_comic_clip(
            "panel.png",
            "out.mp4",
            "hold",
            1.0,
            24,
            "1280x704",
        )
    assert captured[0][:3] == ["ffmpeg", "-hide_banner", "-loglevel"] or (
        "-hide_banner" in captured[0] and "error" in captured[0]
    )
    assert "-hide_banner" in captured[0]
    assert captured[0][captured[0].index("-loglevel") + 1] == "error"


def test_offered_720p_canvas_beats_the_h3_540p_default():
    requested = resolve_comic_output_resolution(
        {"resolution": "1280x704"},
        {"normalized_resolution": "960x544", "is_minimax_h3": True},
        H3_DEF,
    )
    assert requested == "1280x704"

    profile = build_director_video_execution_profile(
        "minimax_h3_fl2va",
        H3_DEF,
        {"resolution": "960x544"},
        {"gpu_vram_gb": 24},
        resolution_preset="720p",
        aspect_ratio="16:9",
    )
    assert profile["normalized_resolution"] == "1280x704"
    assert profile["requested_resolution"] == "1280x704"


def test_comic_output_resolution_uses_the_offered_canvas(monkeypatch):
    class _Wgp:
        @staticmethod
        def get_model_def(_model):
            return dict(H3_DEF)

    monkeypatch.setattr(director_pipeline, "_wgp", _Wgp())
    params = {
        "video_model": "minimax_h3_fl2va",
        "video_params": {"resolution": "1280x704"},
        "_director_video_execution_profile": {
            "normalized_resolution": "960x544",
            "is_minimax_h3": True,
            "model_type": "minimax_h3_fl2va",
        },
    }
    assert director_pipeline._comic_output_resolution(params) == "1280x704"


def test_visual_acceptance_records_who_requested_it(monkeypatch, tmp_path):
    pid = "accept-who"
    fingerprint = "fingerprint-accept"
    note = (
        "I reviewed this exact generated clip and accept its visual quality."
    )
    director_pipeline._pipelines[pid] = {
        "id": pid,
        "status": "preview_ready",
        "out_dir": str(tmp_path),
        "params": {
            "pipeline_type": "comic_movie",
            "_comic_preflight_fingerprint": fingerprint,
        },
        "clip_plans": [{"video_prompt": "kept"}],
        "_planned_clips": [{"start": 0, "end": 3.5}],
        "clip_images": ["comic_panel_0001.png"],
        "preview_clips": [{"index": 0, "included": True}],
        "_comic_preflight_fingerprint": fingerprint,
        "_preview_approved_fingerprint": fingerprint,
        "_quality_gate": {
            "status": "review_required",
            "fingerprint": fingerprint,
            "required_test_indices": [0],
            "tested_indices": [0],
            "results": {"0": {"passed": True}},
            "failures": [],
        },
    }
    monkeypatch.setattr(
        director_pipeline,
        "_comic_preflight_fingerprint",
        lambda *_args, **_kwargs: fingerprint,
    )
    monkeypatch.setattr(director_pipeline, "_save_pipeline_state", lambda _pid: True)
    try:
        rejected, message = director_pipeline.update_comic_preview(
            pid,
            [],
            str(tmp_path),
            expected_fingerprint=fingerprint,
            accept_quality_test=True,
        )
        assert rejected is False
        assert "who requested" in message

        ok, message = director_pipeline.update_comic_preview(
            pid,
            [],
            str(tmp_path),
            expected_fingerprint=fingerprint,
            accept_quality_test=True,
            accepted_via="ui",
            accepted_by="Ada Lovelace",
            acceptance_note=note,
        )
        assert (ok, message) == (True, "quality_test_accepted")
        gate = director_pipeline._pipelines[pid]["_quality_gate"]
        assert gate["status"] == "passed"
        assert gate["accepted_via"] == "ui"
        assert gate["accepted_by"] == "Ada Lovelace"
        assert gate["acceptance_note"] == note
        assert gate["accepted_at"]
    finally:
        director_pipeline._pipelines.pop(pid, None)
