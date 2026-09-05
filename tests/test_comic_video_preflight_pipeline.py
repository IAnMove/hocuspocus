import copy
import json
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from PIL import Image

from app import services as app_services
from app.services import director_pipeline


def test_api_boolean_parser_preserves_explicit_false_strings():
    assert director_pipeline._as_bool("false", default=True) is False
    assert director_pipeline._as_bool("0", default=True) is False
    assert director_pipeline._as_bool("true") is True
    assert director_pipeline._as_bool(None, default=True) is True


def _wgp_stub(save_path, fps=25):
    return SimpleNamespace(
        save_path=str(save_path),
        server_config={"services": {}},
        get_model_def=lambda _model: {"fps": fps},
        get_model_min_frames_and_step=lambda _model: (17, 8, 8),
        get_lora_dir=lambda _model: str(save_path / "missing-loras"),
    )


def _build_preview_pipeline(
    monkeypatch,
    tmp_path,
    pid="comic-pre",
    clip_count=1,
):
    monkeypatch.setattr(
        director_pipeline,
        "_wgp",
        _wgp_stub(tmp_path),
    )
    sources = []
    prepared_images = []
    for index in range(clip_count):
        source = (
            tmp_path
            / f"comic_source_{index + 1:04d}_fixture.png"
        )
        prepared = (
            tmp_path
            / f"comic_panel_{index + 1:04d}_fixture.png"
        )
        Image.new(
            "RGB",
            (96, 64),
            (30 + (index * 20), 80, 140),
        ).save(source)
        shutil.copy2(source, prepared)
        sources.append(source)
        prepared_images.append(prepared)
    params = {
        "pipeline_type": "comic_movie",
        "comic_id": "comic-1",
        "master_seed": 42,
        "video_model": "ltx2_22B_distilled_1_1",
        "video_params": {
            "resolution": "320x192",
            "num_inference_steps": 50,
            "stage2_steps": 3,
            "guidance_scale": 7,
        },
        "video_image_fit": "contain",
        "comic_motion_fidelity": "faithful",
        "provided_clip_image_paths": [
            str(source) for source in sources
        ],
        "comic_shots": [
            {
                "id": f"panel-{index + 1}",
                "panel_id": f"panel-{index + 1}",
                "renderer": "ltx",
                "motion_level": 2,
                "camera_move": "none",
                "fit_mode": "contain",
                "test_selected": index == 0,
            }
            for index in range(clip_count)
        ],
    }
    plans = [
        {
            "shot_id": f"panel-{index + 1}",
            "renderer": "ltx",
            "motion_level": 2,
            "video_prompt": (
                "Nara slowly closes her hand around the seed "
                f"in shot {index + 1}."
            ),
            "metadata": {
                "primary_source_panel_id": f"panel-{index + 1}"
            },
        }
        for index in range(clip_count)
    ]
    timings = [
        {
            "start": index * 2,
            "end": (index + 1) * 2,
            "duration_sec": 2,
        }
        for index in range(clip_count)
    ]
    director_pipeline._pipelines[pid] = {
        "id": pid,
        "status": "preview_ready",
        "phase": "preview_ready",
        "created_at": 1,
        "out_dir": str(tmp_path),
        "workspace": None,
        "params": params,
        "clip_plans": plans,
        "_planned_clips": timings,
        "clip_images": [prepared.name for prepared in prepared_images],
        "_clip_source_images": [source.name for source in sources],
        "_clip_source_sizes": [(96, 64)] * clip_count,
        "_clip_fit_details": [
            {
                "requested_fit_mode": "contain",
                "effective_fit_mode": "contain",
                "needs_reframe": False,
            }
            for _index in range(clip_count)
        ],
        "_clip_keyframes": [[] for _index in range(clip_count)],
        "_clip_video_files": [None] * clip_count,
        "_clip_validations": [None] * clip_count,
        "_preview_revision": 1,
    }
    previews, ends = director_pipeline._build_comic_video_previews(
        pid,
        params,
        plans,
        timings,
        [prepared.name for prepared in prepared_images],
        str(tmp_path),
    )
    fingerprint = params["_comic_preflight_fingerprint"]
    director_pipeline._pipelines[pid].update({
        "preview_clips": previews,
        "_clip_end_images": ends,
        "_comic_preflight_fingerprint": fingerprint,
    })
    return pid, fingerprint, previews


def _editable_clip(preview, **updates):
    clip = {
        "index": preview["index"],
        "order": preview["order"],
        "included": preview["included"],
        "renderer": preview["renderer"],
        "motion_level": preview["motion_level"],
        "camera_move": preview["requested_camera_move"],
        "fit_mode": preview["fit_mode"],
        "duration_seconds": preview["duration_seconds"],
        "test_selected": preview["test_selected"],
        "prompt": preview["prompt"],
    }
    clip.update(updates)
    return clip


def test_shot_seed_follows_stable_id_when_shots_are_reordered():
    params = {
        "master_seed": 1234,
        "comic_shots": [{"id": "a"}, {"id": "b"}],
    }
    plans = [{"shot_id": "a"}, {"shot_id": "b"}]
    first = {
        plan["shot_id"]: director_pipeline._comic_shot_seed(
            params, index, plan
        )
        for index, plan in enumerate(plans)
    }
    reordered_params = {
        "master_seed": 1234,
        "comic_shots": [{"id": "b"}, {"id": "a"}],
    }
    reordered_plans = [{"shot_id": "b"}, {"shot_id": "a"}]
    second = {
        plan["shot_id"]: director_pipeline._comic_shot_seed(
            reordered_params, index, plan
        )
        for index, plan in enumerate(reordered_plans)
    }

    assert first == second
    assert first["a"] != first["b"]


def test_motion_levels_have_observable_renderer_and_prompt_semantics():
    params = {"comic_shots": [{"renderer": "ltx", "motion_level": 0}]}
    assert director_pipeline._comic_effective_renderer(params, 0) == "hold"
    assert "No subject or camera motion" in director_pipeline._comic_motion_prompt(
        "The dust hangs in the air.",
        "faithful",
        False,
        motion_level=0,
    )

    params["comic_shots"][0]["motion_level"] = 1
    params["comic_shots"][0]["camera_move"] = "push-in"
    assert director_pipeline._comic_effective_renderer(params, 0) == "ltx"
    assert director_pipeline._comic_camera_is_locked(params, 0)
    assert "Only subtle supported motion" in director_pipeline._comic_motion_prompt(
        "Nara breathes.",
        "faithful",
        False,
        motion_level=1,
    )
    assert "contained, readable performance" in (
        director_pipeline._comic_motion_prompt(
            "Nara looks toward Kael.",
            "faithful",
            False,
            motion_level=2,
        )
    )
    assert "one clear, readable action" in director_pipeline._comic_motion_prompt(
        "Nara runs to the tree.",
        "faithful",
        False,
        motion_level=3,
    )

    # Deterministic renderers expose one meaningful intensity only.
    assert director_pipeline._comic_motion_level(
        {"comic_shots": [{"renderer": "hold", "motion_level": 3}]},
        0,
    ) == 0
    assert director_pipeline._comic_motion_level(
        {"comic_shots": [{"renderer": "parallax", "motion_level": 3}]},
        0,
    ) == 1


def test_pre_exposes_effective_runtime_renderer_seed_and_per_clip_negatives(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        director_pipeline,
        "_wgp",
        _wgp_stub(tmp_path),
    )
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (64, 64), (20, 40, 60)).save(first)
    Image.new("RGB", (64, 64), (60, 40, 20)).save(second)
    pid = "pre-contract"
    params = {
        "master_seed": 77,
        "video_model": "ltx2_22B_distilled_1_1",
        "video_params": {
            "resolution": "320x192",
            "num_inference_steps": 40,
            "stage2_steps": 9,
            "guidance_scale": 6,
            "negative_prompt": "text artifacts",
        },
        "provided_clip_image_paths": [str(first), str(second)],
        "comic_shots": [
            {
                "id": "one",
                "renderer": "ltx",
                "motion_level": 0,
                "camera_move": "none",
            },
            {
                "id": "two",
                "renderer": "ltx",
                "motion_level": 3,
                "camera_move": "push-in",
            },
        ],
    }
    plans = [
        {
            "shot_id": "one",
            "video_prompt": "Hold the moment.",
            "metadata": {
                "dialogue": "Nara: Keep the lantern covered."
            },
        },
        {"shot_id": "two", "video_prompt": "She lifts the lantern."},
    ]
    timings = [
        {"start": 0, "end": 2, "duration_sec": 2},
        {"start": 2, "end": 4, "duration_sec": 2},
    ]
    director_pipeline._pipelines[pid] = {
        "_clip_source_sizes": [(64, 64), (64, 64)],
        "_clip_source_images": [first.name, second.name],
        "_clip_fit_details": [{}, {}],
        "_preview_revision": 1,
    }
    try:
        previews, _ends = director_pipeline._build_comic_video_previews(
            pid,
            params,
            plans,
            timings,
            [first.name, second.name],
            str(tmp_path),
        )
    finally:
        director_pipeline._pipelines.pop(pid, None)

    assert previews[0]["renderer"] == "ltx"
    assert previews[0]["effective_renderer"] == "hold"
    assert previews[1]["effective_renderer"] == "ltx"
    assert previews[0]["num_inference_steps"] == 8
    assert previews[0]["requested_num_inference_steps"] == 40
    assert previews[0]["stage2_steps"] == 3
    assert previews[0]["requested_stage2_steps"] == 9
    assert previews[0]["guidance_scale"] == 1
    assert previews[0]["seed"] >= 0
    assert previews[0]["seed"] != previews[1]["seed"]
    assert previews[0]["dialogue"] == "Nara: Keep the lantern covered."
    assert previews[1]["dialogue"] == ""
    assert "camera zoom" in previews[0]["negative_prompt"]
    assert "camera zoom" not in previews[1]["negative_prompt"]
    assert params["_effective_video_negative_prompts"] == [
        item["negative_prompt"] for item in previews
    ]


def test_final_pre_test_selection_includes_measured_aspect_mismatch(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        director_pipeline,
        "_wgp",
        _wgp_stub(tmp_path),
    )
    count = 7
    images = []
    for index in range(count):
        path = tmp_path / f"panel-{index}.png"
        Image.new("RGB", (64, 64), (40 + index, 60, 80)).save(path)
        images.append(path.name)
    params = {
        "master_seed": 101,
        "video_model": "ltx2_22B_distilled_1_1",
        "video_params": {"resolution": "320x192"},
        "video_image_fit": "contain",
        "comic_shots": [
            {
                "id": f"panel-{index}",
                "renderer": "ltx",
                "motion_level": 2,
                # Simulate an early planner selection made before capture size
                # and retained-fraction measurements were available.
                "test_selected": index < 6,
            }
            for index in range(count)
        ],
    }
    plans = [
        {
            "shot_id": f"panel-{index}",
            "video_prompt": f"Action {index}.",
            "metadata": {
                "risk_tags": ["action"] if index == 6 else []
            },
        }
        for index in range(count)
    ]
    timings = [
        {
            "start": index,
            "end": index + 1,
            "duration_sec": 1,
        }
        for index in range(count)
    ]
    pid = "final-risk-selection"
    director_pipeline._pipelines[pid] = {
        "_clip_source_sizes": [(64, 64)] * count,
        "_clip_source_images": list(images),
        "_clip_fit_details": [
            {
                "requested_fit_mode": "contain",
                "effective_fit_mode": "contain",
                # Every source is a mismatch. PRE should reserve one slot for
                # the measured fit risk, then still cover semantic risks such
                # as the action shot at the end.
                "retained_fraction": 0.3,
                "needs_reframe": False,
            }
            for index in range(count)
        ],
        "_preview_revision": 1,
    }
    try:
        previews, _ends = director_pipeline._build_comic_video_previews(
            pid,
            params,
            plans,
            timings,
            images,
            str(tmp_path),
        )
        selected = [
            index
            for index, preview in enumerate(previews)
            if preview["test_selected"]
        ]
        assert 6 in selected
        assert len(selected) <= 6
        assert params["comic_shots"][6]["test_selected"] is True
        assert plans[6]["metadata"]["test_selected"] is True
    finally:
        director_pipeline._pipelines.pop(pid, None)


def test_metadata_only_approval_test_review_and_human_acceptance(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, _previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
    )
    try:
        ok, message = director_pipeline.update_comic_preview(
            pid,
            [],
            str(tmp_path),
            expected_fingerprint=fingerprint,
            approve_preview=True,
        )
        assert (ok, message) == (True, "preview_approved")
        parent = director_pipeline._pipelines[pid]
        assert parent["_preview_approved_fingerprint"] == fingerprint
        assert parent["_quality_gate"]["required_test_indices"] == [0]
        assert parent["_quality_gate"]["status"] == "pending"

        child_pid = "quality-child"
        director_pipeline._pipelines[child_pid] = {
            "id": child_pid,
            "out_dir": str(tmp_path),
            "_preview_run_type": "test",
            "_source_preview_pipeline_id": pid,
            "_source_preview_clip_indices": [0],
            "_source_preview_fingerprint": fingerprint,
        }
        director_pipeline._record_comic_preview_quality(
            child_pid,
            [{
                "passed": True,
                "failures": [],
                "warnings": [],
                "metrics": {"frames": 50},
                "renderer": "ltx",
                "video_filename": "quality-clip.mp4",
            }],
        )
        gate = director_pipeline._pipelines[pid]["_quality_gate"]
        assert gate["status"] == "review_required"
        assert gate["results"]["0"]["output_files"] == ["quality-clip.mp4"]

        ok, message = director_pipeline.update_comic_preview(
            pid,
            [],
            str(tmp_path),
            expected_fingerprint=fingerprint,
            accept_quality_test=True,
        )
        assert (ok, message) == (True, "quality_test_accepted")
        assert director_pipeline._pipelines[pid]["_quality_gate"]["status"] == "passed"
    finally:
        director_pipeline._pipelines.pop(pid, None)
        director_pipeline._pipelines.pop("quality-child", None)


def test_approval_and_waiver_roll_back_when_checkpoint_write_fails(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, _previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
        pid="approval-write-failure",
    )
    before = copy.deepcopy(director_pipeline._pipelines[pid])
    monkeypatch.setattr(
        director_pipeline,
        "_save_pipeline_state",
        lambda _pid: False,
    )
    try:
        ok, message = director_pipeline.update_comic_preview(
            pid,
            [],
            str(tmp_path),
            expected_fingerprint=fingerprint,
            approve_preview=True,
            quality_waiver=True,
            waiver_reason="Representative test intentionally skipped.",
        )

        assert ok is False
        assert "rolled back" in message
        state = director_pipeline._pipelines[pid]
        assert state.get("_preview_approved_fingerprint") == before.get(
            "_preview_approved_fingerprint"
        )
        assert state.get("_quality_gate") == before.get("_quality_gate")
    finally:
        director_pipeline._pipelines.pop(pid, None)


def test_quality_acceptance_rolls_back_when_checkpoint_write_fails(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, _previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
        pid="accept-write-failure",
    )
    state = director_pipeline._pipelines[pid]
    state["_preview_approved_fingerprint"] = fingerprint
    state["_quality_gate"] = {
        "status": "review_required",
        "fingerprint": fingerprint,
        "required_test_indices": [0],
        "tested_indices": [0],
        "results": {"0": {"passed": True}},
        "failures": [],
    }
    before_gate = copy.deepcopy(state["_quality_gate"])
    monkeypatch.setattr(
        director_pipeline,
        "_save_pipeline_state",
        lambda _pid: False,
    )
    try:
        ok, message = director_pipeline.update_comic_preview(
            pid,
            [],
            str(tmp_path),
            expected_fingerprint=fingerprint,
            accept_quality_test=True,
        )

        assert ok is False
        assert "rolled back" in message
        assert (
            director_pipeline._pipelines[pid]["_quality_gate"]
            == before_gate
        )
    finally:
        director_pipeline._pipelines.pop(pid, None)


def test_metadata_edit_reuses_lossless_and_prepared_images(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
        pid="metadata-reuse",
    )
    before_pngs = {path.name for path in tmp_path.glob("*.png")}
    before_sources = list(
        director_pipeline._pipelines[pid]["_clip_source_images"]
    )
    before_prepared = list(
        director_pipeline._pipelines[pid]["clip_images"]
    )
    try:
        ok, message = director_pipeline.update_comic_preview(
            pid,
            [
                _editable_clip(
                    previews[0],
                    duration_seconds=3.25,
                )
            ],
            str(tmp_path),
            expected_fingerprint=fingerprint,
        )

        assert (ok, message) == (True, "updated")
        state = director_pipeline._pipelines[pid]
        assert state["_clip_source_images"] == before_sources
        assert state["clip_images"] == before_prepared
        assert {path.name for path in tmp_path.glob("*.png")} == before_pngs
        assert state["_planned_clips"][0]["duration_sec"] == 3.25
        assert "_preflight_prompt_override" not in state["clip_plans"][0]
    finally:
        director_pipeline._pipelines.pop(pid, None)


def test_fit_edit_restages_only_changed_clip_and_reuses_lossless_sources(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
        pid="selective-restage",
        clip_count=2,
    )
    before_sources = list(
        director_pipeline._pipelines[pid]["_clip_source_images"]
    )
    before_prepared = list(
        director_pipeline._pipelines[pid]["clip_images"]
    )
    try:
        ok, message = director_pipeline.update_comic_preview(
            pid,
            [_editable_clip(previews[0], fit_mode="cover")],
            str(tmp_path),
            expected_fingerprint=fingerprint,
        )

        assert (ok, message) == (True, "updated")
        state = director_pipeline._pipelines[pid]
        assert state["_clip_source_images"] == before_sources
        assert state["clip_images"][0] != before_prepared[0]
        assert state["clip_images"][1] == before_prepared[1]
        assert not (tmp_path / before_prepared[0]).exists()
        assert (tmp_path / before_prepared[1]).is_file()
        assert (tmp_path / state["clip_images"][0]).is_file()
        assert len(list(tmp_path.glob("comic_source_*.png"))) == 2
        assert len(list(tmp_path.glob("comic_panel_*.png"))) == 2
    finally:
        director_pipeline._pipelines.pop(pid, None)


def test_failed_preview_staging_rolls_back_state_and_files(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
        pid="atomic-rollback",
    )
    before_state = copy.deepcopy(director_pipeline._pipelines[pid])
    before_pngs = {path.name for path in tmp_path.glob("*.png")}

    def fail_preview_build(*_args, **_kwargs):
        raise RuntimeError("synthetic staging failure")

    monkeypatch.setattr(
        director_pipeline,
        "_build_comic_video_previews",
        fail_preview_build,
    )
    try:
        ok, message = director_pipeline.update_comic_preview(
            pid,
            [_editable_clip(previews[0], fit_mode="cover")],
            str(tmp_path),
            expected_fingerprint=fingerprint,
        )

        assert ok is False
        assert "synthetic staging failure" in message
        assert director_pipeline._pipelines[pid] == before_state
        assert {path.name for path in tmp_path.glob("*.png")} == before_pngs
        assert not any(
            key.startswith(f"{pid}:preview-staging:")
            for key in director_pipeline._pipelines
        )
    finally:
        director_pipeline._pipelines.pop(pid, None)


def test_failed_checkpoint_replace_rolls_back_live_pre_and_keeps_old_files(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
        pid="durable-rollback",
    )
    assert director_pipeline._save_pipeline_state(pid) is True
    checkpoint = tmp_path / f"_director_pipeline_{pid}.json"
    before_checkpoint = checkpoint.read_bytes()
    before_state = copy.deepcopy(director_pipeline._pipelines[pid])
    before_pngs = {path.name for path in tmp_path.glob("*.png")}

    def fail_replace(_source, _destination):
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(director_pipeline.os, "replace", fail_replace)
    try:
        ok, message = director_pipeline.update_comic_preview(
            pid,
            [_editable_clip(previews[0], fit_mode="cover")],
            str(tmp_path),
            expected_fingerprint=fingerprint,
        )

        assert ok is False
        assert "rolled back" in message
        assert director_pipeline._pipelines[pid] == before_state
        assert checkpoint.read_bytes() == before_checkpoint
        assert {path.name for path in tmp_path.glob("*.png")} == before_pngs
    finally:
        director_pipeline._pipelines.pop(pid, None)


def test_only_active_child_statuses_block_pre_edits(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
        pid="child-edit-lock",
    )
    child_pid = "child-edit-lock-run"
    director_pipeline._pipelines[child_pid] = {
        "id": child_pid,
        "status": "running",
        "_source_preview_pipeline_id": pid,
    }
    try:
        ok, message = director_pipeline.update_comic_preview(
            pid,
            [_editable_clip(previews[0], duration_seconds=3)],
            str(tmp_path),
            expected_fingerprint=fingerprint,
        )
        assert ok is False
        assert "using this PRE" in message

        ok, message = director_pipeline.update_comic_preview(
            pid,
            [],
            str(tmp_path),
            expected_fingerprint=fingerprint,
            approve_preview=True,
        )
        assert ok is False
        assert "approving or waiving" in message

        director_pipeline._pipelines[child_pid]["status"] = None
        ok, message = director_pipeline.update_comic_preview(
            pid,
            [_editable_clip(previews[0], duration_seconds=3)],
            str(tmp_path),
            expected_fingerprint=fingerprint,
        )
        assert (ok, message) == (True, "updated")
    finally:
        director_pipeline._pipelines.pop(pid, None)
        director_pipeline._pipelines.pop(child_pid, None)


def test_reordering_keeps_every_pre_shot_array_aligned(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
        pid="aligned-reorder",
        clip_count=3,
    )
    state = director_pipeline._pipelines[pid]
    state["_clip_keyframes"] = [
        [f"keyframe-{index}.png"] for index in range(3)
    ]
    before_sources = list(state["_clip_source_images"])
    before_prepared = list(state["clip_images"])
    try:
        ok, message = director_pipeline.update_comic_preview(
            pid,
            [
                _editable_clip(preview, order=2 - index)
                for index, preview in enumerate(previews)
            ],
            str(tmp_path),
            expected_fingerprint=fingerprint,
        )

        assert (ok, message) == (True, "updated")
        reordered = director_pipeline._pipelines[pid]
        assert [
            shot["id"] for shot in reordered["params"]["comic_shots"]
        ] == ["panel-3", "panel-2", "panel-1"]
        assert [
            plan["shot_id"] for plan in reordered["clip_plans"]
        ] == ["panel-3", "panel-2", "panel-1"]
        assert [
            planned["start"] for planned in reordered["_planned_clips"]
        ] == [0.0, 2.0, 4.0]
        assert reordered["_clip_source_images"] == list(
            reversed(before_sources)
        )
        assert reordered["clip_images"] == list(reversed(before_prepared))
        assert reordered["_clip_keyframes"] == [
            ["keyframe-2.png"],
            ["keyframe-1.png"],
            ["keyframe-0.png"],
        ]
        assert [
            preview["index"] for preview in reordered["preview_clips"]
        ] == [0, 1, 2]
        assert [
            preview["shot_id"] for preview in reordered["preview_clips"]
        ] == ["panel-3", "panel-2", "panel-1"]
    finally:
        director_pipeline._pipelines.pop(pid, None)


def test_preview_generation_reuses_identical_child_and_blocks_competitor(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, _previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
        pid="child-generation-lock",
        clip_count=2,
    )
    parent = director_pipeline._pipelines[pid]
    parent["_preview_approved_fingerprint"] = fingerprint
    parent["_quality_gate"] = {
        "status": "passed",
        "fingerprint": fingerprint,
        "required_test_indices": [0],
        "tested_indices": [0],
        "results": {"0": {"passed": True}},
        "failures": [],
    }
    active_pid = "active-preview-child"
    director_pipeline._pipelines[active_pid] = {
        "id": active_pid,
        "status": "running",
        "_source_preview_pipeline_id": pid,
        "_source_preview_clip_indices": [0],
        "_source_preview_fingerprint": fingerprint,
        "_preview_run_type": "test",
    }
    started_threads = []

    class DummyThread:
        def __init__(self, *args, **kwargs):
            started_threads.append((args, kwargs))

        def start(self):
            return None

    monkeypatch.setattr(director_pipeline.threading, "Thread", DummyThread)
    created_pid = None
    try:
        result = director_pipeline.start_preview_generation(
            pid,
            clip_indices=[0],
            out_dir=str(tmp_path),
            expected_fingerprint=fingerprint,
            run_type="test",
        )
        assert result == (True, "already_running", active_pid)
        assert started_threads == []

        ok, message, child_pid = director_pipeline.start_preview_generation(
            pid,
            clip_indices=[1],
            out_dir=str(tmp_path),
            expected_fingerprint=fingerprint,
            run_type="test",
        )
        assert ok is False
        assert "Another generation" in message
        assert child_pid == active_pid
        assert started_threads == []

        director_pipeline._pipelines[active_pid]["status"] = "completed"
        ok, message, created_pid = director_pipeline.start_preview_generation(
            pid,
            clip_indices=[1],
            out_dir=str(tmp_path),
            expected_fingerprint=fingerprint,
            run_type="test",
        )
        assert (ok, message) == (True, "started")
        assert created_pid != active_pid
        assert len(started_threads) == 1
    finally:
        for key in (pid, active_pid, created_pid):
            if key:
                director_pipeline._pipelines.pop(key, None)


def test_full_preview_generation_cannot_submit_only_a_subset(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, _previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
        pid="full-generation-subset",
        clip_count=2,
    )
    parent = director_pipeline._pipelines[pid]
    parent["_preview_approved_fingerprint"] = fingerprint
    parent["_quality_gate"] = {
        "status": "passed",
        "fingerprint": fingerprint,
        "required_test_indices": [0],
        "tested_indices": [0],
        "results": {"0": {"passed": True}},
        "failures": [],
    }
    try:
        ok, message, child_pid = director_pipeline.start_preview_generation(
            pid,
            clip_indices=[0],
            out_dir=str(tmp_path),
            expected_fingerprint=fingerprint,
            run_type="full",
        )
        assert ok is False
        assert "every enabled shot" in message
        assert child_pid is None
    finally:
        director_pipeline._pipelines.pop(pid, None)


def test_legacy_pre_without_fingerprint_cannot_generate_test_or_full(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, _previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
        pid="legacy-pre",
    )
    parent = director_pipeline._pipelines[pid]
    parent.pop("_comic_preflight_fingerprint", None)
    parent["params"].pop("_comic_preflight_fingerprint", None)
    parent["_preview_approved_fingerprint"] = fingerprint
    try:
        for run_type, indices in (("test", [0]), ("full", None)):
            ok, message, child_pid = (
                director_pipeline.start_preview_generation(
                    pid,
                    clip_indices=indices,
                    out_dir=str(tmp_path),
                    expected_fingerprint=fingerprint,
                    run_type=run_type,
                )
            )
            assert ok is False
            assert "legacy PRE" in message
            assert "Rebuild PRE" in message
            assert child_pid is None
    finally:
        director_pipeline._pipelines.pop(pid, None)


def test_full_generation_reuses_accepted_test_clip_from_same_fingerprint(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, _previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
        pid="reuse-test-clip",
        clip_count=2,
    )
    accepted = tmp_path / "accepted-test-exact.mp4"
    accepted.write_bytes(b"accepted-video-checkpoint")
    parent = director_pipeline._pipelines[pid]
    parent["_preview_approved_fingerprint"] = fingerprint
    parent["_quality_gate"] = {
        "status": "passed",
        "fingerprint": fingerprint,
        "required_test_indices": [0],
        "tested_indices": [0],
        "results": {
            "0": {
                "passed": True,
                "video_filename": accepted.name,
            },
        },
        "failures": [],
    }
    started_threads = []

    class DummyThread:
        def __init__(self, *args, **kwargs):
            started_threads.append((args, kwargs))

        def start(self):
            return None

    monkeypatch.setattr(director_pipeline.threading, "Thread", DummyThread)
    child_pid = None
    try:
        ok, message, child_pid = (
            director_pipeline.start_preview_generation(
                pid,
                out_dir=str(tmp_path),
                expected_fingerprint=fingerprint,
                run_type="full",
            )
        )
        assert (ok, message) == (True, "started")
        assert director_pipeline._pipelines[child_pid][
            "_clip_video_files"
        ] == [accepted.name, None]
        assert len(started_threads) == 1
    finally:
        director_pipeline._pipelines.pop(pid, None)
        if child_pid:
            director_pipeline._pipelines.pop(child_pid, None)


def test_preview_generation_does_not_start_without_durable_child_checkpoint(
    monkeypatch,
    tmp_path,
):
    pid, fingerprint, _previews = _build_preview_pipeline(
        monkeypatch,
        tmp_path,
        pid="child-checkpoint-required",
    )
    parent = director_pipeline._pipelines[pid]
    parent["_preview_approved_fingerprint"] = fingerprint
    parent["_quality_gate"] = {
        "status": "pending",
        "fingerprint": fingerprint,
        "required_test_indices": [0],
        "tested_indices": [],
        "results": {},
        "failures": [],
    }
    started_threads = []

    class DummyThread:
        def __init__(self, *args, **kwargs):
            started_threads.append((args, kwargs))

        def start(self):
            raise AssertionError("GPU thread must not start")

    monkeypatch.setattr(director_pipeline.threading, "Thread", DummyThread)
    monkeypatch.setattr(
        director_pipeline,
        "_save_pipeline_state",
        lambda _pid: False,
    )
    try:
        ok, message, child_pid = (
            director_pipeline.start_preview_generation(
                pid,
                clip_indices=[0],
                out_dir=str(tmp_path),
                expected_fingerprint=fingerprint,
                run_type="test",
            )
        )
        assert ok is False
        assert "no GPU work was started" in message
        assert child_pid is None
        assert started_threads == []
        assert not any(
            state.get("_source_preview_pipeline_id") == pid
            for key, state in director_pipeline._pipelines.items()
            if key != pid
        )
    finally:
        director_pipeline._pipelines.pop(pid, None)


@pytest.mark.parametrize("worker_status", ["queued", "running"])
def test_pipeline_cancel_stays_active_until_worker_settles(
    monkeypatch,
    tmp_path,
    worker_status,
):
    pid = f"cancel-{worker_status}"
    jobs = {}
    worker_ready = threading.Event()
    worker_release = threading.Event()
    waiter_done = threading.Event()
    outcome = {}

    def run_generation(job_id):
        job = jobs[job_id]
        if worker_status == "running":
            job["status"] = "running"
        worker_ready.set()
        worker_release.wait(timeout=5)
        if job.get("_cancel_requested"):
            job["status"] = "cancelled"
            job["message"] = "Cancelled"

    def cancel_generation(job_id):
        job = jobs[job_id]
        job["_cancel_requested"] = True
        if job.get("status") == "queued":
            job["status"] = "cancelled"
            job["message"] = "Cancelled"
        return {"status": job["status"]}

    monkeypatch.setattr(director_pipeline, "_jobs", jobs)
    monkeypatch.setattr(
        director_pipeline,
        "_run_generation",
        run_generation,
    )
    monkeypatch.setattr(
        director_pipeline,
        "_cancel_generation",
        cancel_generation,
    )
    monkeypatch.setattr(
        director_pipeline,
        "_save_pipeline_state",
        lambda _pid: True,
    )
    director_pipeline._pipelines[pid] = {
        "id": pid,
        "status": "running",
        "phase": "generating_video",
        "progress": {"message": "Generating"},
        "out_dir": str(tmp_path),
        "params": {},
    }

    def wait_for_generation():
        try:
            director_pipeline._submit_and_wait(
                {"_director_pipeline_id": pid},
                timeout_s=5,
                out_dir=str(tmp_path),
            )
        except Exception as exc:
            outcome["error"] = exc
        finally:
            waiter_done.set()

    waiter = threading.Thread(target=wait_for_generation)
    waiter.start()
    assert worker_ready.wait(timeout=2)
    try:
        status = director_pipeline.stop_pipeline(pid)
        assert status is True
        assert director_pipeline._pipelines[pid]["status"] == "running"
        assert director_pipeline._pipelines[pid]["phase"] == "cancelling"
        assert director_pipeline._pipelines[pid].get("_completed_at") is None

        worker_release.set()
        waiter.join(timeout=3)
        assert waiter_done.is_set()
        assert "error" not in outcome
        assert director_pipeline._pipelines[pid]["status"] == "cancelled"
        assert "_active_generation_job_id" not in (
            director_pipeline._pipelines[pid]
        )
    finally:
        worker_release.set()
        waiter.join(timeout=3)
        director_pipeline._pipelines.pop(pid, None)


def test_preflight_uses_durable_sources_after_upload_is_removed(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        director_pipeline,
        "_wgp",
        _wgp_stub(tmp_path),
    )
    monkeypatch.setattr(
        director_pipeline,
        "_wait_for_gpu",
        lambda _pid: True,
    )
    monkeypatch.setitem(sys.modules, "services", app_services)
    upload = tmp_path / "temporary-upload.png"
    Image.new("RGB", (96, 64), (20, 90, 150)).save(upload)
    pid = "durable-source-pre"
    params = {
        "pipeline_type": "comic_movie",
        "comic_preflight_only": True,
        "auto_mode": True,
        "master_seed": 99,
        "video_model": "ltx2_22B_distilled_1_1",
        "video_params": {"resolution": "320x192"},
        "video_image_fit": "contain",
        "comic_motion_fidelity": "faithful",
        "provided_clip_image_paths": [str(upload)],
        "comic_shots": [{
            "id": "panel-1",
            "panel_id": "panel-1",
            "renderer": "ltx",
            "motion_level": 2,
            "camera_move": "none",
            "fit_mode": "contain",
            "test_selected": True,
        }],
    }
    plan = {
        "shot_id": "panel-1",
        "renderer": "ltx",
        "motion_level": 2,
        "video_prompt": "Nara closes her hand around the seed.",
        "metadata": {"primary_source_panel_id": "panel-1"},
    }
    director_pipeline._pipelines[pid] = {
        "id": pid,
        "status": "running",
        "phase": "resuming",
        "created_at": 1,
        "out_dir": str(tmp_path),
        "workspace": None,
        "params": params,
        "clip_plans": [plan],
        "_planned_clips": [{"start": 0, "end": 2, "duration_sec": 2}],
        "clip_images": [],
        "_clip_keyframes": [],
        "output_files": [],
    }
    child_pid = None
    try:
        director_pipeline._run_pipeline(pid, resume=True)
        state = director_pipeline._pipelines[pid]
        assert state["status"] == "preview_ready"
        durable_path = state["params"]["provided_clip_image_paths"][0]
        assert durable_path != str(upload)
        assert "comic_source_" in durable_path
        assert (tmp_path / state["_clip_source_images"][0]).is_file()
        fingerprint = state["_comic_preflight_fingerprint"]

        upload.unlink()
        assert director_pipeline._comic_preflight_fingerprint(
            state["params"],
            state["clip_plans"],
            state["_planned_clips"],
            state["clip_images"],
            str(tmp_path),
        ) == fingerprint

        director_pipeline._pipelines.pop(pid)
        ok, message = director_pipeline.resume_pipeline(pid, str(tmp_path))
        assert (ok, message) == (True, "recovered_preview")
        recovered = director_pipeline._pipelines[pid]
        assert recovered["params"]["provided_clip_image_paths"] == [
            durable_path
        ]
        assert director_pipeline._comic_preflight_fingerprint(
            recovered["params"],
            recovered["clip_plans"],
            recovered["_planned_clips"],
            recovered["clip_images"],
            str(tmp_path),
        ) == fingerprint

        ok, message = director_pipeline.update_comic_preview(
            pid,
            [],
            str(tmp_path),
            expected_fingerprint=fingerprint,
            approve_preview=True,
        )
        assert (ok, message) == (True, "preview_approved")

        started_threads = []

        class DummyThread:
            def __init__(self, *args, **kwargs):
                started_threads.append((args, kwargs))

            def start(self):
                return None

        monkeypatch.setattr(
            director_pipeline.threading,
            "Thread",
            DummyThread,
        )
        ok, message, child_pid = (
            director_pipeline.start_preview_generation(
                pid,
                clip_indices=[0],
                out_dir=str(tmp_path),
                expected_fingerprint=fingerprint,
                run_type="test",
            )
        )
        assert (ok, message) == (True, "started")
        assert child_pid
        child_params = director_pipeline._pipelines[child_pid]["params"]
        assert child_params["provided_clip_image_paths"] == [durable_path]
        assert len(started_threads) == 1
    finally:
        director_pipeline._pipelines.pop(pid, None)
        if child_pid:
            director_pipeline._pipelines.pop(child_pid, None)


def test_quality_results_accumulate_and_retry_replaces_same_required_index(
    tmp_path,
):
    pid = "parent"
    fingerprint = "fingerprint"
    director_pipeline._pipelines[pid] = {
        "id": pid,
        "out_dir": str(tmp_path),
        "_comic_preflight_fingerprint": fingerprint,
        "_quality_gate": {
            "status": "pending",
            "fingerprint": fingerprint,
            "required_test_indices": [0, 1],
            "tested_indices": [],
            "results": {},
            "failures": [],
        },
    }

    def record(child_pid, source_index, passed):
        director_pipeline._pipelines[child_pid] = {
            "id": child_pid,
            "out_dir": str(tmp_path),
            "_preview_run_type": "test",
            "_source_preview_pipeline_id": pid,
            "_source_preview_clip_indices": [source_index],
            "_source_preview_fingerprint": fingerprint,
        }
        director_pipeline._record_comic_preview_quality(
            child_pid,
            [{
                "passed": passed,
                "failures": [] if passed else ["scene-replacement"],
                "metrics": {},
            }],
        )

    try:
        record("fail-zero", 0, False)
        gate = director_pipeline._pipelines[pid]["_quality_gate"]
        assert gate["status"] == "failed"
        assert gate["failures"] == ["shot 1: scene-replacement"]
        record("pass-zero", 0, True)
        assert director_pipeline._pipelines[pid]["_quality_gate"]["status"] == "pending"
        record("pass-one", 1, True)
        gate = director_pipeline._pipelines[pid]["_quality_gate"]
        assert gate["status"] == "review_required"
        assert gate["tested_indices"] == [0, 1]
        assert gate["results"]["0"]["passed"] is True
    finally:
        for key in ("parent", "fail-zero", "pass-zero", "pass-one"):
            director_pipeline._pipelines.pop(key, None)


def test_standard_comic_generation_forwards_exact_seed_and_negative_per_clip(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        director_pipeline,
        "_wgp",
        _wgp_stub(tmp_path),
    )
    for name in ("one.png", "two.png"):
        Image.new("RGB", (64, 64), (70, 90, 110)).save(tmp_path / name)
    captured = {}

    def submit(params, **_kwargs):
        captured.update(params)
        return ["one.mp4", "two.mp4"]

    monkeypatch.setattr(director_pipeline, "_submit_and_wait", submit)
    params = {
        "pipeline_type": "comic_movie",
        "_comic_renderer_orchestrated": True,
        "seamless": False,
        "master_seed": 55,
        "video_model": "ltx2_22B_distilled_1_1",
        "video_params": {"resolution": "320x192"},
        "comic_shots": [
            {"id": "one", "renderer": "ltx", "camera_move": "none"},
            {"id": "two", "renderer": "ltx", "camera_move": "push-in"},
        ],
        "_effective_video_negative_prompt": "reference guard",
        "_effective_video_negative_prompts": [
            "reference guard, no camera",
            "reference guard",
        ],
    }
    plans = [
        {"shot_id": "one", "_effective_video_prompt": "first motion"},
        {"shot_id": "two", "_effective_video_prompt": "second motion"},
    ]
    timings = [
        {"start": 0, "end": 1, "duration_sec": 1},
        {"start": 1, "end": 2, "duration_sec": 1},
    ]

    output = director_pipeline._run_video_generation(
        "seed-negative",
        params,
        plans,
        timings,
        ["one.png", "two.png"],
        [[], []],
        str(tmp_path),
        None,
    )

    assert output == ["one.mp4", "two.mp4"]
    assert captured["per_clip_negative_prompts"] == [
        "reference guard, no camera",
        "reference guard",
    ]
    assert captured["per_clip_seeds"] == [
        director_pipeline._comic_shot_seed(params, 0, plans[0]),
        director_pipeline._comic_shot_seed(params, 1, plans[1]),
    ]
    assert captured["num_inference_steps"] == 8
    assert captured["guidance_scale"] == 1


def test_failed_validation_clears_only_failed_checkpoint_for_resume(
    monkeypatch,
    tmp_path,
):
    wgp = _wgp_stub(tmp_path, fps=10)

    def concatenate(_inputs, destination, _audio):
        with open(destination, "wb") as handle:
            handle.write(b"joined")
        return True

    wgp.concatenate_multi_clip_videos = concatenate
    monkeypatch.setattr(director_pipeline, "_wgp", wgp)
    pid = "selective-validation-resume"
    image_names = ["source-one.png", "source-two.png"]
    exact_names = [
        f"comic_{pid}_0001_ltx_exact.mp4",
        f"comic_{pid}_0002_ltx_exact.mp4",
    ]
    for index, name in enumerate(image_names):
        Image.new("RGB", (64, 64), (80 + index * 20, 50, 40)).save(
            tmp_path / name
        )
    for name in exact_names:
        (tmp_path / name).write_bytes(b"diagnostic-video")
    params = {
        "pipeline_type": "comic_movie",
        "video_model": "ltx2_22B_distilled_1_1",
        "video_params": {"resolution": "64x64"},
        "comic_shots": [
            {
                "id": "one",
                "renderer": "ltx",
                "motion_level": 2,
                "camera_move": "none",
            },
            {
                "id": "two",
                "renderer": "ltx",
                "motion_level": 2,
                "camera_move": "none",
            },
        ],
    }
    plans = [
        {"shot_id": "one", "renderer": "ltx", "video_prompt": "First."},
        {"shot_id": "two", "renderer": "ltx", "video_prompt": "Second."},
    ]
    timings = [
        {"start": 0, "end": 1, "duration_sec": 1},
        {"start": 1, "end": 2, "duration_sec": 1},
    ]
    director_pipeline._pipelines[pid] = {
        "id": pid,
        "status": "running",
        "created_at": 1,
        "out_dir": str(tmp_path),
        "params": params,
        "clip_plans": plans,
        "_planned_clips": timings,
        "clip_images": image_names,
        "_clip_video_files": list(exact_names),
        "_clip_validations": [None, None],
    }
    validation_pass = {"value": 0}

    def validate(*_args, **_kwargs):
        call = validation_pass["value"]
        validation_pass["value"] += 1
        # First pass: shot one succeeds, shot two fails. The resumed pass
        # validates both successful files.
        failed = call == 1
        return {
            "passed": not failed,
            "failures": ["identity-drift"] if failed else [],
            "warnings": [],
            "metrics": {},
        }

    regenerated = []

    def regenerate(
        _pid,
        _params,
        selected_plans,
        _selected_timings,
        _selected_images,
        _selected_keyframes,
        **_kwargs,
    ):
        regenerated.extend(plan["shot_id"] for plan in selected_plans)
        files = list(
            director_pipeline._pipelines[pid]["_clip_video_files"]
        )
        files[1] = exact_names[1]
        director_pipeline._pipelines[pid]["_clip_video_files"] = files
        return [exact_names[1]]

    monkeypatch.setattr(
        director_pipeline,
        "_validate_comic_clip",
        validate,
    )
    monkeypatch.setattr(
        director_pipeline,
        "_run_video_generation",
        regenerate,
    )
    try:
        with pytest.raises(RuntimeError, match="shot 2"):
            director_pipeline._run_comic_renderer_pipeline(
                pid,
                params,
                plans,
                timings,
                image_names,
                [[], []],
                str(tmp_path),
                None,
            )

        assert director_pipeline._pipelines[pid]["_clip_video_files"] == [
            exact_names[0],
            None,
        ]
        assert all((tmp_path / name).is_file() for name in exact_names)

        result = director_pipeline._run_comic_renderer_pipeline(
            pid,
            params,
            plans,
            timings,
            image_names,
            [[], []],
            str(tmp_path),
            None,
        )
        assert regenerated == ["two"]
        assert result == [f"comic_{pid}_r1_movie.mp4"]
        assert director_pipeline._pipelines[pid]["_clip_video_files"] == (
            exact_names
        )
    finally:
        director_pipeline._pipelines.pop(pid, None)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe unavailable",
)
@pytest.mark.parametrize("source_has_audio", [False, True])
def test_exact_clip_normalization_preserves_or_adds_audio(
    tmp_path,
    source_has_audio,
):
    source = tmp_path / (
        "source-with-audio.mp4"
        if source_has_audio
        else "source-without-audio.mp4"
    )
    output = tmp_path / "normalized.mp4"
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=64x64:r=10:d=0.7",
    ]
    if source_has_audio:
        command.extend([
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=0.35",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:a",
            "aac",
            "-shortest",
        ])
    command.extend([
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(source),
    ])
    subprocess.run(command, check=True, capture_output=True)

    director_pipeline._normalize_comic_clip_duration(
        str(source),
        str(output),
        duration_seconds=1.2,
        fps=10,
        resolution="64x64",
    )

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name",
            "-of",
            "json",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(probe.stdout)
    streams = payload["streams"]
    assert any(
        stream["codec_type"] == "video" for stream in streams
    )
    assert any(
        stream["codec_type"] == "audio"
        and stream["codec_name"] == "aac"
        for stream in streams
    )
    assert float(payload["format"]["duration"]) == pytest.approx(
        1.2,
        abs=0.06,
    )

    if source_has_audio:
        volume = subprocess.run(
            [
                "ffmpeg",
                "-i",
                str(output),
                "-af",
                "volumedetect",
                "-f",
                "null",
                "-",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert "mean_volume: -91.0 dB" not in volume.stderr


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg unavailable")
def test_dispatcher_renders_motion_zero_as_exact_hold_checkpoint(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        director_pipeline,
        "_wgp",
        _wgp_stub(tmp_path, fps=10),
    )
    pid = "deterministic-hold"
    image = tmp_path / "panel.png"
    Image.new("RGB", (64, 64), (180, 70, 40)).save(image)
    params = {
        "pipeline_type": "comic_movie",
        "video_model": "test-video-model",
        "video_params": {"resolution": "64x64"},
        "comic_shots": [{
            "id": "panel",
            "renderer": "ltx",
            "motion_level": 0,
            "camera_move": "none",
        }],
    }
    plan = {
        "shot_id": "panel",
        "renderer": "ltx",
        "motion_level": 0,
        "video_prompt": "No movement.",
    }
    director_pipeline._pipelines[pid] = {
        "id": pid,
        "created_at": 1,
        "out_dir": str(tmp_path),
        "params": params,
        "clip_plans": [plan],
        "_planned_clips": [{"start": 0, "end": 0.8, "duration_sec": 0.8}],
        "clip_images": [image.name],
        "_clip_source_images": [image.name],
        "_clip_source_sizes": [(64, 64)],
        "_clip_fit_details": [{}],
        "_clip_video_files": [None],
        "_clip_keyframes": [[]],
    }
    try:
        output = director_pipeline._run_comic_renderer_pipeline(
            pid,
            params,
            [plan],
            [{"start": 0, "end": 0.8, "duration_sec": 0.8}],
            [image.name],
            [[]],
            str(tmp_path),
            None,
        )
        validation = director_pipeline._pipelines[pid][
            "_clip_validations"
        ][0]
        assert len(output) == 1
        assert "_hold_exact.mp4" in output[0]
        assert (tmp_path / output[0]).is_file()
        assert validation["passed"] is True
        assert validation["metrics"]["frames"] == 8
        assert validation["metrics"]["width"] == 64
        assert validation["metrics"]["height"] == 64
    finally:
        director_pipeline._pipelines.pop(pid, None)
