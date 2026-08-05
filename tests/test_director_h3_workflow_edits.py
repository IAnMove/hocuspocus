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
