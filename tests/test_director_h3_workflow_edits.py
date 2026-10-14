import json
from pathlib import Path
from unittest.mock import patch

import pytest

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


def test_saved_h3_prompt_drives_regenerate_without_override(tmp_path: Path):
    """Workspaces Save then Repeat sends no prompt_override; segments must follow."""
    state = _saved_state(tmp_path)
    _write_pipeline(tmp_path, state)
    director_pipeline.update_clip_prompts(
        str(tmp_path),
        "editable",
        0,
        video_prompt="A dragon flies over the castle.",
    )
    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        filename = f"new_{len(submitted)}.mp4"
        (tmp_path / filename).write_bytes(b"new video")
        return [filename]

    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch("app.services.video_editor.probe_media", return_value={"duration": 5.16}), \
            patch("app.services.video_editor.extract_frame",
                  side_effect=lambda _s, destination, _t: Path(destination).write_bytes(b"frame")):
        director_pipeline.rerun_clip_video(str(tmp_path), "editable", 0)

    assert submitted, "H3 regenerate should submit at least one segment"
    assert all("A dragon flies over the castle." in item["prompt"] for item in submitted)
    assert all("Segment 0. Audio: wind." not in item["prompt"] for item in submitted)


THREE_ACTIONS = "She walks to the door. She opens it. She steps outside."


def _saved_clip(tmp_path: Path) -> dict:
    return director_pipeline.load_pipeline_state(str(tmp_path), "editable")["clips"][0]


def test_a_saved_shot_prompt_is_cut_into_one_slice_per_h3_segment(tmp_path: Path):
    """The shot is cut into its segments again; a segment never replays the whole shot."""
    _write_pipeline(tmp_path, _saved_state(tmp_path))

    director_pipeline.update_clip_prompts(str(tmp_path), "editable", 0, video_prompt=THREE_ACTIONS)

    clip = _saved_clip(tmp_path)
    first, second, third = (record["prompt"] for record in clip["h3_segments"])
    assert "Perform only these actions in this segment" in first
    assert "She walks to the door." in first
    assert "She opens it." not in first and "She steps outside." not in first
    for later, own, others in (
        (second, "She opens it.", ("She walks to the door.", "She steps outside.")),
        (third, "She steps outside.", ("She walks to the door.", "She opens it.")),
    ):
        assert "Continue directly from the supplied continuity frame" in later
        assert own in later
        assert not any(other in later for other in others)
    assert all(record["stale"] for record in clip["h3_segments"])
    assert clip["h3_segment_prompts"] == []
    assert clip["video_prompt"] == THREE_ACTIONS
    assert director_pipeline._typed_at_review(
        director_pipeline.load_pipeline_state(str(tmp_path), "editable"), 0, "video_prompt",
    )


def test_an_unchanged_workspace_save_leaves_the_h3_segments_alone(tmp_path: Path):
    state = _saved_state(tmp_path)
    _write_pipeline(tmp_path, state)
    before = _saved_clip(tmp_path)["h3_segments"]

    director_pipeline.update_clip_prompts(
        str(tmp_path), "editable", 0, video_prompt=state["clips"][0]["video_prompt"],
    )

    assert _saved_clip(tmp_path)["h3_segments"] == before
    assert not any(record["stale"] for record in before)


def test_a_saved_shot_prompt_replaces_the_authored_windows_it_was_cut_from(tmp_path: Path):
    """A clip that carries window prompts would otherwise slice the old windows and ignore the save."""
    state = _saved_state(tmp_path)
    state["clips"][0]["window_prompts"] = ["Old window one.", "Old window two.", "Old window three."]
    state["clips"][0]["h3_segment_prompts"] = ["Old a.", "Old b.", "Old c."]
    _write_pipeline(tmp_path, state)

    director_pipeline.update_clip_prompts(str(tmp_path), "editable", 0, video_prompt=THREE_ACTIONS)

    prompts = [record["prompt"] for record in _saved_clip(tmp_path)["h3_segments"]]
    assert not any("Old " in prompt for prompt in prompts)
    assert "She opens it." in prompts[1]


def test_a_workspace_save_leaves_the_segments_of_a_non_h3_production_alone(tmp_path: Path):
    state = _saved_state(tmp_path)
    state["video_model"] = "ltx2_22B_distilled_1_1"
    _write_pipeline(tmp_path, state)
    before = _saved_clip(tmp_path)["h3_segments"]

    director_pipeline.update_clip_prompts(str(tmp_path), "editable", 0, video_prompt=THREE_ACTIONS)

    assert _saved_clip(tmp_path)["h3_segments"] == before
    assert _saved_clip(tmp_path)["video_prompt"] == THREE_ACTIONS


def _resume_h3_render(tmp_path: Path, saved: dict) -> list[dict]:
    """Drive the H3 story render the way a Dashboard resume does: prompts from the saved
    ``clip_plans``, segments from the saved clips (a stale one is not reused)."""
    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        filename = f"resumed_{len(submitted)}.mp4"
        (tmp_path / filename).write_bytes(b"new video")
        return [filename]

    class FakeWgp:
        @staticmethod
        def concatenate_multi_clip_videos(paths, destination, audio_path, audio_start_sec=0.0):
            Path(destination).write_bytes(b"joined")
            return True

    previous = director_pipeline._pipelines
    director_pipeline._pipelines = {
        "editable": {"_h3_segments": [list(clip.get("h3_segments") or []) for clip in saved["clips"]]},
    }
    try:
        with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
                patch.object(director_pipeline, "_save_pipeline_state"), \
                patch.object(director_pipeline, "_wgp", FakeWgp()), \
                patch("app.services.video_editor.probe_media", return_value={"duration": 5.16}), \
                patch("app.services.video_editor.extract_frame",
                      side_effect=lambda _s, destination, _t: Path(destination).write_bytes(b"frame")):
            director_pipeline._run_minimax_h3_story_video(
                "editable", {}, saved["clip_plans"], [{"duration_sec": 15}],
                [saved["clips"][0]["start_image_filename"]],
                {"num_inference_steps": 20, "h3_reference_mode": "first_frame"}, "960x544", str(tmp_path),
            )
    finally:
        director_pipeline._pipelines = previous
    return submitted


@pytest.mark.parametrize("authored", ["h3_segment_prompts", "window_prompts"])
def test_a_resume_after_a_workspace_save_renders_the_saved_text(tmp_path: Path, authored: str):
    """The save marks the shot's segments stale, so a resume renders them again from
    ``clip_plans``. Those must carry the saved text, not the old optimised segment
    prompts or planner windows (which take precedence over ``video_prompt``)."""
    state = _saved_state(tmp_path)
    # Frames on H3's lattice, so an untouched segment would be reused by the resume.
    for record, frames in zip(state["clips"][0]["h3_segments"], director_pipeline._minimax_h3_frame_segments(15, 24)):
        record["frames"] = frames
    old = ["Old a.", "Old b.", "Old c."]
    state["clips"][0][authored] = list(old)
    state["clip_plans"][0][authored] = list(old)
    _write_pipeline(tmp_path, state)

    director_pipeline.update_clip_prompts(str(tmp_path), "editable", 0, video_prompt=THREE_ACTIONS)
    saved = director_pipeline.load_pipeline_state(str(tmp_path), "editable")
    submitted = _resume_h3_render(tmp_path, saved)

    prompts = [item["prompt"] for item in submitted]
    assert len(prompts) == 3
    assert not any("Old " in prompt for prompt in prompts)
    for prompt, own in zip(prompts, THREE_ACTIONS.split(". ")):
        assert own.rstrip(".") in prompt
    assert saved["clip_plans"][0][authored] == [] and saved["clips"][0][authored] == []


def test_a_workspace_save_on_a_legacy_shot_without_segment_records_is_sliced_on_repeat(tmp_path: Path):
    """A production saved before segment records: Repeat groups the outputs into segments and takes their
    prompts from the clip's h3_segment_prompts. After a save they must be the new text's slices, not the
    old optimised ones (edit ignored) nor the whole shot in every segment."""
    outputs = [f"segment_{index}.mp4" for index in range(3)]
    for name in outputs:
        (tmp_path / name).write_bytes(b"video")
    old = ["old a", "old b", "old c"]
    _write_pipeline(tmp_path, {
        "pipeline_id": "legacy",
        "video_model": "minimax_h3",
        "video_params": {"h3_reference_mode": "first_frame"},
        "clips": [{"index": 0, "planned_clip": {"duration_sec": 15}, "seed": 10,
                   "video_prompt": "Old shot.", "h3_segment_prompts": list(old)}],
        "clip_plans": [{"video_prompt": "Old shot.", "h3_segment_prompts": list(old)}],
        "output_files": outputs,
    })

    director_pipeline.update_clip_prompts(str(tmp_path), "legacy", 0, video_prompt=THREE_ACTIONS)

    loaded = director_pipeline.load_pipeline_state(str(tmp_path), "legacy")
    prompts = [record["prompt"] for record in loaded["clips"][0]["h3_segments"]]
    assert len(prompts) == 3
    for prompt, own in zip(prompts, ("She walks to the door.", "She opens it.", "She steps outside.")):
        assert own in prompt
        assert not any(other in prompt for other in THREE_ACTIONS.split(". ") if other.rstrip(".") not in own)
    assert not any(prompt in old for prompt in prompts)


def test_a_workspace_save_cuts_the_same_slices_as_regenerate_with_a_new_shot_prompt(tmp_path: Path):
    """One cut, two doors: Workspaces Save and "regenerate with a new prompt" (replace_shot_prompt)."""
    saved_dir, rerun_dir = tmp_path / "save", tmp_path / "rerun"
    for folder in (saved_dir, rerun_dir):
        folder.mkdir()
        _write_pipeline(folder, _saved_state(folder))

    director_pipeline.update_clip_prompts(str(saved_dir), "editable", 0, video_prompt=THREE_ACTIONS)

    def submit(_params, **_kwargs):
        name = f"rerun_{len(list(rerun_dir.glob('rerun_*.mp4')))}.mp4"
        (rerun_dir / name).write_bytes(b"new video")
        return [name]

    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch("app.services.video_editor.probe_media", return_value={"duration": 5.16}), \
            patch("app.services.video_editor.extract_frame",
                  side_effect=lambda _s, destination, _t: Path(destination).write_bytes(b"frame")):
        director_pipeline.rerun_h3_segment(
            str(rerun_dir), "editable", 0, 0, prompt_override=THREE_ACTIONS, replace_shot_prompt=True,
        )

    assert [record["prompt"] for record in _saved_clip(saved_dir)["h3_segments"]] == [
        record["prompt"] for record in _saved_clip(rerun_dir)["h3_segments"]
    ]


def test_a_workspace_save_marks_stale_only_from_the_first_segment_whose_slice_changed(tmp_path: Path):
    """A segment continues from the one before it, so a changed slice makes it and every later
    segment stale; the segments before it keep their take (rejoin and resume reuse them)."""
    _write_pipeline(tmp_path, _saved_state(tmp_path))
    director_pipeline.update_clip_prompts(str(tmp_path), "editable", 0, video_prompt=THREE_ACTIONS)
    state = director_pipeline.load_pipeline_state(str(tmp_path), "editable")
    for record in state["clips"][0]["h3_segments"]:
        record["stale"] = False  # as after the Repeat that rendered the saved text
    _write_pipeline(tmp_path, state)

    director_pipeline.update_clip_prompts(
        str(tmp_path), "editable", 0, video_prompt="She walks to the door. She opens it. She waves goodbye.",
    )
    assert [record["stale"] for record in _saved_clip(tmp_path)["h3_segments"]] == [False, False, True]

    # A save that leaves every slice as it is (here only the plan's copy differed) marks nothing.
    state = director_pipeline.load_pipeline_state(str(tmp_path), "editable")
    for record in state["clips"][0]["h3_segments"]:
        record["stale"] = False
    state["clip_plans"][0]["video_prompt"] = "An older plan wording."
    _write_pipeline(tmp_path, state)
    director_pipeline.update_clip_prompts(
        str(tmp_path), "editable", 0, video_prompt="She walks to the door. She opens it. She waves goodbye.",
    )
    assert not any(record["stale"] for record in _saved_clip(tmp_path)["h3_segments"])


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
    assert "Same faces and wardrobe throughout" in submitted[0]["prompt"]
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


@pytest.mark.parametrize("direct_video", [False, True])
def test_rerun_h3_segment_can_replace_the_whole_shot_prompt(tmp_path: Path, direct_video):
    state = _saved_state(tmp_path)
    state["video_model"] = "minimax_h3_legacy"
    _write_pipeline(tmp_path, state)
    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        filename = f"new_{len(submitted)}.mp4"
        (tmp_path / filename).write_bytes(b"new video")
        return [filename]

    with patch.object(director_pipeline, "_direct_video_settings", return_value=(direct_video, "")), \
            patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch("app.services.video_editor.probe_media", return_value={"duration": 5.16}), \
            patch("app.services.video_editor.extract_frame",
                  side_effect=lambda _s, destination, _t: Path(destination).write_bytes(b"frame")):
        result = director_pipeline.rerun_h3_segment(
            str(tmp_path),
            "editable",
            0,
            2,
            prompt_override="She stands and looks at the sky.",
            cascade=False,
            replace_shot_prompt=True,
        )

    assert result["filenames"] == ["new_1.mp4"]
    saved = director_pipeline.load_pipeline_state(str(tmp_path), "editable")
    assert saved["clips"][0]["video_prompt"] == "She stands and looks at the sky."


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


@pytest.mark.parametrize("video_model", ["minimax_h3", "minimax_h3_legacy"])
@pytest.mark.parametrize("selected", [None, "shot0_studio.mp4"])
def test_h3_rejoin_rejects_stale_clip_even_when_segments_are_playable(tmp_path: Path, video_model, selected):
    filenames = ("shot0_a.mp4", "shot0_b.mp4", "shot1.mp4")
    for filename in filenames:
        (tmp_path / filename).write_bytes(b"video")
    if selected:
        (tmp_path / selected).write_bytes(b"selected video")
    _write_pipeline(tmp_path, {
        "pipeline_id": "h3-stale-rejoin",
        "created_at": 10.0,
        "status": "completed",
        "pipeline_type": "short_film_story",
        "video_model": video_model,
        "clips": [
            {
                "index": 0,
                "video_filename": "shot0_b.mp4",
                "selected_video_filename": selected,
                "video_stale": True,
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
    checkpoint = Path(director_pipeline._find_pipeline_file(str(tmp_path), "h3-stale-rejoin"))
    before = checkpoint.read_bytes()
    joined = []

    class FakeWgp:
        @staticmethod
        def concatenate_multi_clip_videos(paths, destination, _audio, **_kwargs):
            joined.extend(Path(path).name for path in paths)
            Path(destination).write_bytes(b"joined")
            return True

    with patch.object(director_pipeline, "_wgp", FakeWgp()):
        with pytest.raises(ValueError, match="stale video clip.*1.*before rejoining"):
            director_pipeline.rejoin_clips(str(tmp_path), "h3-stale-rejoin")
    assert joined == []
    assert checkpoint.read_bytes() == before


def test_regenerating_an_h3_segment_draws_and_records_a_new_seed(tmp_path: Path):
    state = _saved_state(tmp_path)
    _write_pipeline(tmp_path, state)
    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        filename = f"retry_{len(submitted)}.mp4"
        (tmp_path / filename).write_bytes(b"new video")
        return [filename]

    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch.object(director_pipeline.secrets, "randbelow", side_effect=[4242, 4343]):
        for _ in range(2):
            director_pipeline.rerun_h3_segment(str(tmp_path), "editable", 0, 0, cascade=False)

    assert [item["seed"] for item in submitted] == [4242, 4343]
    saved = director_pipeline.load_pipeline_state(str(tmp_path), "editable")
    assert saved["clips"][0]["h3_segments"][0]["seed"] == 4343


def test_comic_movies_keep_the_seed_their_pre_pinned():
    state = {"_params_snapshot": {"pipeline_type": "comic_movie"}}
    assert director_pipeline._regenerate_seed(state, 777) == 777
    with patch.object(director_pipeline.secrets, "randbelow", return_value=55):
        assert director_pipeline._regenerate_seed({}, 777) == 55
