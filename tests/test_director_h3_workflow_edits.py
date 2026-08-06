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
        "video_model": "minimax_h3",
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
        def concatenate_multi_clip_videos(paths, destination, audio_path):
            joined.extend(Path(path).name for path in paths)
            assert audio_path is None
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
