import json
from pathlib import Path
from unittest.mock import patch

from app.services import director_pipeline


def _write_pipeline(tmp_path: Path, state: dict) -> Path:
    path = tmp_path / f"_director_pipeline_{state['pipeline_id']}.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def _saved_state(tmp_path: Path) -> dict:
    portrait = tmp_path / "portrait.png"
    start = tmp_path / "start.png"
    portrait.write_bytes(b"portrait")
    start.write_bytes(b"start")
    segments = []
    outputs = []
    for index in range(3):
        filename = f"old_{index}.mp4"
        (tmp_path / filename).write_bytes(b"video")
        outputs.append(filename)
        segments.append({
            "index": index,
            "filename": filename,
            "prompt": f"Segment {index}. Audio: wind.",
            "frames": 124,
            "seed": 900 + index,
            "reference_mode": "first_frame" if index == 0 else "references",
            "stale": False,
        })
    return {
        "pipeline_id": "editable",
        "created_at": 100.0,
        "status": "completed",
        "video_model": "minimax_h3",
        "video_params": {
            "resolution": "960x544",
            "h3_reference_mode": "first_frame",
        },
        "character_ref_paths": [str(portrait)],
        "clips": [{
            "index": 0,
            "start_image_filename": start.name,
            "video_prompt": "A woman walks, crouches and looks up.",
            "planned_clip": {"duration_sec": 15},
            "h3_segments": segments,
        }],
        "clip_plans": [{"video_prompt": "A woman walks, crouches and looks up."}],
        "output_files": outputs,
        "workspace": "default",
        "_params_snapshot": {
            "master_seed": 900,
            "character_ref_paths": [str(portrait)],
        },
    }


def test_legacy_h3_outputs_are_grouped_back_into_editable_segments(tmp_path: Path):
    outputs = [f"segment_{index}.mp4" for index in range(4)]
    for name in outputs:
        (tmp_path / name).write_bytes(b"video")
    (tmp_path / "minimax_h3_legacy_multiclip.mp4").write_bytes(b"joined")
    state = {
        "pipeline_id": "legacy",
        "video_model": "minimax_h3_legacy",
        "video_params": {"h3_reference_mode": "first_frame"},
        "clips": [
            {"index": 0, "planned_clip": {"duration_sec": 10}, "seed": 10, "h3_segment_prompts": ["a", "b"]},
            {"index": 1, "planned_clip": {"duration_sec": 10}, "seed": 20, "h3_segment_prompts": ["c", "d"]},
        ],
        "output_files": [*outputs, "minimax_h3_legacy_multiclip.mp4"],
    }
    _write_pipeline(tmp_path, state)

    loaded = director_pipeline.load_pipeline_state(str(tmp_path), "legacy")

    assert [segment["filename"] for segment in loaded["clips"][0]["h3_segments"]] == outputs[:2]
    assert [segment["filename"] for segment in loaded["clips"][1]["h3_segments"]] == outputs[2:]


def test_malformed_legacy_h3_multiclip_output_is_not_reused_as_a_shot(tmp_path: Path):
    """The old generic multi-clip payload made one H3 video, not one per shot."""
    bad_output = tmp_path / "minimax_h3_old.mp4"
    bad_output.write_bytes(b"video")
    bad_output.with_suffix(".meta.json").write_text(json.dumps({
        "params": {
            "multi_prompts_gen_type": 3,
            "prompt": "first shot\n---CLIP_BOUNDARY---\nsecond shot",
            "image_start": ["first.png", "second.png"],
        },
    }), encoding="utf-8")
    state = {
        "pipeline_id": "badlegacy",
        "video_model": "minimax_h3",
        "video_params": {"h3_reference_mode": "first_frame"},
        "clips": [
            {"index": 0, "planned_clip": {"duration_sec": 5}},
            {"index": 1, "planned_clip": {"duration_sec": 5}},
        ],
        "output_files": [bad_output.name],
    }
    _write_pipeline(tmp_path, state)

    loaded = director_pipeline.load_pipeline_state(str(tmp_path), "badlegacy")

    assert [clip["h3_segments"] for clip in loaded["clips"]] == [[], []]


def test_rerun_h3_video_initializes_a_missing_saved_shot(tmp_path: Path):
    start = tmp_path / "start.png"
    start.write_bytes(b"image")
    state = {
        "pipeline_id": "emptyshot",
        "video_model": "minimax_h3",
        "video_params": {"resolution": "960x544", "h3_reference_mode": "first_frame"},
        "clips": [{
            "index": 0,
            "start_image_filename": start.name,
            "video_prompt": "A scientist turns toward camera.",
            "planned_clip": {"duration_sec": 5},
            "h3_segments": [],
        }],
        "clip_plans": [{"video_prompt": "A scientist turns toward camera."}],
        "output_files": [],
        "workspace": "default",
        "_params_snapshot": {"master_seed": 33},
    }
    _write_pipeline(tmp_path, state)

    with patch.object(director_pipeline, "rerun_h3_segment", return_value={"filename": "new.mp4"}) as rerun:
        result = director_pipeline.rerun_clip_video(str(tmp_path), "emptyshot", 0)

    assert result == {"filename": "new.mp4"}
    rerun.assert_called_once()
    saved = director_pipeline.load_pipeline_state(str(tmp_path), "emptyshot")
    assert len(saved["clips"][0]["h3_segments"]) == 1
    assert saved["clips"][0]["h3_segments"][0]["stale"] is True


def test_rerun_h3_segment_cascades_and_rejoin_uses_current_versions(tmp_path: Path):
    state = _saved_state(tmp_path)
    state["video_model"] = "minimax_h3_legacy"
    _write_pipeline(tmp_path, state)
    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        filename = f"new_{len(submitted)}.mp4"
        (tmp_path / filename).write_bytes(b"new video")
        return [filename]

    def extract(_source, destination, _time):
        Path(destination).write_bytes(b"continuity")

    joined = []

    class FakeWgp:
        @staticmethod
        def concatenate_multi_clip_videos(
            paths,
            destination,
            audio_path,
            audio_start_sec=0.0,
        ):
            joined.extend(Path(path).name for path in paths)
            assert audio_path is None
            assert audio_start_sec == 0.0
            Path(destination).write_bytes(b"joined")
            return True

    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch("app.services.video_editor.probe_media", return_value={"duration": 5.16}), \
            patch("app.services.video_editor.extract_frame", side_effect=extract), \
            patch.object(director_pipeline, "_wgp", FakeWgp()):
        result = director_pipeline.rerun_h3_segment(
            str(tmp_path),
            "editable",
            0,
            1,
            prompt_override="She crouches while keeping the same face. Audio: wind.",
            cascade=True,
        )
        rejoined = director_pipeline.rejoin_clips(str(tmp_path), "editable")

    assert result["filenames"] == ["new_1.mp4", "new_2.mp4"]
    assert len(submitted) == 2
    assert all(item["model_type"] == "minimax_h3_legacy" for item in submitted)
    assert submitted[0]["h3_reference_mode"] == "references"
    assert submitted[0]["image_refs"][1].endswith("portrait.png")
    assert "IDENTITY CONTINUITY LOCK" in submitted[0]["prompt"]
    saved = director_pipeline.load_pipeline_state(str(tmp_path), "editable")
    assert [item["filename"] for item in saved["clips"][0]["h3_segments"]] == [
        "old_0.mp4", "new_1.mp4", "new_2.mp4",
    ]
    assert not any(item["stale"] for item in saved["clips"][0]["h3_segments"])
    assert joined == ["old_0.mp4", "new_1.mp4", "new_2.mp4"]
    assert rejoined["filename"].startswith("minimax_h3_editable_rejoin_")
    assert saved["assembly_time_sec"] >= 0
    assert saved["assembly_count"] == 1
    assert saved["assembled_at"] >= saved["created_at"]
    assert saved["total_time_sec"] == round(saved["assembled_at"] - saved["created_at"], 2)
    assert rejoined["assembly_time_sec"] == saved["assembly_time_sec"]
    assert rejoined["total_time_sec"] == saved["total_time_sec"]
    rejoin_sidecar = json.loads(
        (tmp_path / Path(rejoined["filename"]).with_suffix(".meta.json")).read_text(
            encoding="utf-8",
        )
    )
    assert rejoin_sidecar["generation_time"] == saved["total_time_sec"]
    assert rejoin_sidecar["generation_timings"]["assembly_time_sec"] == saved["assembly_time_sec"]


def test_clip_history_is_recovered_selected_and_used_by_rejoin(tmp_path: Path):
    for filename in ("clip_0_original.mp4", "clip_0_rerun.mp4", "clip_1.mp4"):
        (tmp_path / filename).write_bytes(b"video")
    for filename, clip_index, created_at, prompt in (
        ("clip_0_original.mp4", 0, 100.0, "Original prompt"),
        ("clip_0_rerun.mp4", 0, 200.0, "Edited prompt"),
        ("clip_1.mp4", 1, 110.0, "Second prompt"),
    ):
        legacy_sidecar = filename == "clip_0_original.mp4"
        (tmp_path / filename.replace(".mp4", ".meta.json")).write_text(
            json.dumps({
                "director_pipeline_id": "history",
                **({} if legacy_sidecar else {"director_clip_index": clip_index}),
                "output_filename": filename,
                "created_at": created_at,
                "params": {
                    "_director_pipeline_id": "history",
                    **({
                        "_director_progress_label": "H3 Legacy · clip 1/2",
                    } if legacy_sidecar else {}),
                    "model_type": "test_video",
                    "prompt": prompt,
                    "seed": clip_index + int(created_at),
                    "resolution": "720x1280",
                    "video_length": 81,
                },
            }),
            encoding="utf-8",
        )
    _write_pipeline(tmp_path, {
        "pipeline_id": "history",
        "created_at": 50.0,
        "status": "completed",
        "pipeline_type": "short_film_story",
        "video_model": "test_video",
        "shot_image_policy": "prompt_only",
        "video_params": {"resolution": "720x1280"},
        "clips": [
            {
                "index": 0,
                "video_filename": "clip_0_rerun.mp4",
                "video_prompt": "Edited prompt",
                "video_stale": False,
            },
            {
                "index": 1,
                "video_filename": "clip_1.mp4",
                "video_prompt": "Second prompt",
                "video_stale": False,
            },
        ],
        "output_files": [
            "clip_0_original.mp4", "clip_0_rerun.mp4", "clip_1.mp4",
        ],
        "workspace": "default",
    })

    loaded = director_pipeline.load_pipeline_state(str(tmp_path), "history")
    assert [
        attempt["filename"] for attempt in loaded["clips"][0]["video_attempts"]
    ] == ["clip_0_original.mp4", "clip_0_rerun.mp4"]

    selected = director_pipeline.select_clip_video_attempt(
        str(tmp_path), "history", 0, "clip_0_original.mp4",
    )
    assert selected["filename"] == "clip_0_original.mp4"

    joined = []

    class FakeWgp:
        @staticmethod
        def concatenate_multi_clip_videos(paths, destination, _audio, **_kwargs):
            joined.extend(Path(path).name for path in paths)
            Path(destination).write_bytes(b"joined")
            return True

    with patch.object(director_pipeline, "_wgp", FakeWgp()):
        director_pipeline.rejoin_clips(str(tmp_path), "history")

    assert joined == ["clip_0_original.mp4", "clip_1.mp4"]
    saved = director_pipeline.load_pipeline_state(str(tmp_path), "history")
    assert saved["clips"][0]["selected_video_filename"] == "clip_0_original.mp4"
    assert saved["clips"][0]["video_filename"] == "clip_0_original.mp4"


def test_explicit_whole_clip_selection_ignores_old_h3_segments(tmp_path: Path):
    filenames = ("shot0_a.mp4", "shot0_b.mp4", "shot0_studio.mp4", "shot1.mp4")
    for filename in filenames:
        (tmp_path / filename).write_bytes(b"video")
    _write_pipeline(tmp_path, {
        "pipeline_id": "h3-selection",
        "created_at": 10.0,
        "status": "completed",
        "pipeline_type": "short_film_story",
        "video_model": "minimax_h3_legacy",
        "clips": [
            {
                "index": 0,
                "video_filename": "shot0_b.mp4",
                "video_prompt": "Whole shot zero",
                "h3_segments": [
                    {"index": 0, "filename": "shot0_a.mp4", "stale": False},
                    {"index": 1, "filename": "shot0_b.mp4", "stale": False},
                ],
            },
            {
                "index": 1,
                "video_filename": "shot1.mp4",
                "video_prompt": "Whole shot one",
                "h3_segments": [
                    {"index": 0, "filename": "shot1.mp4", "stale": False},
                ],
            },
        ],
        "output_files": list(filenames),
        "workspace": "default",
    })
    director_pipeline.select_clip_video_attempt(
        str(tmp_path), "h3-selection", 0, "shot0_studio.mp4",
    )
    joined = []

    class FakeWgp:
        @staticmethod
        def concatenate_multi_clip_videos(paths, destination, _audio, **_kwargs):
            joined.extend(Path(path).name for path in paths)
            Path(destination).write_bytes(b"joined")
            return True

    with patch.object(director_pipeline, "_wgp", FakeWgp()):
        director_pipeline.rejoin_clips(str(tmp_path), "h3-selection")

    assert joined == ["shot0_studio.mp4", "shot1.mp4"]
