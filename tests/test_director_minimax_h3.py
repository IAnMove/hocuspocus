"""Regression tests for Story Director's MiniMax H3 duration adapter."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services import director_pipeline
from app.services.director.minimax_h3_prompting import is_structured_h3_prompt


def test_h3_duration_segments_stay_on_the_supported_lattice():
    segments = director_pipeline._minimax_h3_frame_segments(45.0)

    assert len(segments) == 9
    assert all(107 <= frames <= 362 for frames in segments)
    assert all(frames % 17 == 5 for frames in segments)
    assert abs(sum(segments) - 45 * 24) <= 17 / 2


def test_director_startup_removes_only_private_audio_scratch(tmp_path: Path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    song = workspace / "song.wav"
    song.write_bytes(b"keep")
    legacy = workspace / "_director_h3_audio_deadbeef_s0_0_abcd1234.wav"
    legacy.write_bytes(b"remove")
    hidden = workspace / ".director-tmp" / "deadbeef" / "slice.wav"
    hidden.parent.mkdir(parents=True)
    hidden.write_bytes(b"remove")

    director_pipeline._cleanup_stale_director_temporary_outputs(str(tmp_path))

    assert song.exists()
    assert not legacy.exists()
    assert not hidden.exists()
    assert not (workspace / ".director-tmp").exists()


def test_h3_long_shot_is_split_without_losing_its_duration():
    segments = director_pipeline._minimax_h3_frame_segments(20.0)

    assert len(segments) == 4
    assert abs(sum(segments) - 20 * 24) <= 17 / 2


def test_h3_segment_prompts_follow_authored_windows():
    plan = {
        "video_prompt": "fallback",
        "window_prompts": [
            {"prompt": "opening"},
            {"prompt": "middle"},
            {"prompt": "ending"},
        ],
    }

    prompts = [
        director_pipeline._minimax_h3_segment_prompt(plan, index, 3)
        for index in range(3)
    ]

    assert all(expected in prompt for expected, prompt in zip(["opening", "middle", "ending"], prompts))
    assert all("overall_soundscape:" in prompt for prompt in prompts)


def test_h3_authored_windows_are_split_instead_of_replayed():
    plan = {
        "window_prompts": [
            {"prompt": "She approaches. She stops. She kneels. She uncovers the sphere."},
            {"prompt": "She lifts it. The map appears. She studies it. She walks away."},
        ],
    }

    prompts = [
        director_pipeline._minimax_h3_segment_prompt(plan, index, 4)
        for index in range(4)
    ]

    assert "She approaches" in prompts[0]
    assert "She approaches" not in prompts[1]
    assert "She lifts it" in prompts[2]
    assert "She lifts it" not in prompts[3]


def test_h3_segment_prompt_renders_director_audio_plan_and_dialogue():
    prompt = director_pipeline._minimax_h3_segment_prompt({
        "video_prompt": "A mechanic shuts the workshop door.",
        "audio_plan": {
            "mode": "dialogue_driven",
            "ambience": "rain on the metal roof",
            "effects": ["door clang", "tools rattling"],
            "vocal_style": "tired whisper",
            "lip_sync_critical": True,
        },
        "dialogue_beats": [{
            "speaker_name": "Mara",
            "spoken_text": "We leave at dawn.",
            "delivery": "quietly",
        }],
    }, 0, 1)

    assert "overall_soundscape:" in prompt
    assert "Mara says <d>[English] We leave at dawn.</d>" in prompt
    soundscape = prompt.split("overall_soundscape:", 1)[1].split("non_diegetic_music:", 1)[0]
    assert "N/A" in soundscape
    assert "rain on the metal roof" not in soundscape
    assert "door clang" not in soundscape
    assert "precise lip sync" not in soundscape
    assert "Vocal delivery:" not in soundscape
    assert "non_diegetic_music: N/A" in prompt


def test_h3_dialogue_is_assigned_once_across_continuation_segments():
    plan = {
        "video_prompt": "She enters. She stops. She looks back. She leaves.",
        "dialogue_beats": [
            {"speaker_name": "Mara", "spoken_text": "Wait for me."},
            {"speaker_name": "Mara", "spoken_text": "Now we go."},
        ],
        "audio_plan": {"mode": "dialogue_driven", "lip_sync_critical": True},
    }

    first = director_pipeline._minimax_h3_segment_prompt(plan, 0, 2)
    second = director_pipeline._minimax_h3_segment_prompt(plan, 1, 2)

    assert "Wait for me." in first
    assert "Wait for me." not in second
    assert "Now we go." not in first
    assert "Now we go." in second


def test_h3_story_renders_each_shot_and_assembles_native_audio(tmp_path: Path):
    start_images = []
    for index in range(2):
        path = tmp_path / f"shot_{index}.png"
        path.write_bytes(b"frame")
        start_images.append(path.name)

    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        name = f"clip_{len(submitted)}.mp4"
        (tmp_path / name).write_bytes(b"video")
        return [name]

    class FakeWgp:
        @staticmethod
        def concatenate_multi_clip_videos(
            paths, destination, audio_path, audio_start_sec=0.0,
        ):
            assert len(paths) == 2
            assert audio_path is None
            assert audio_start_sec == 0.0
            Path(destination).write_bytes(b"assembled")
            return True

    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch.object(director_pipeline, "_save_pipeline_state"), \
            patch.object(director_pipeline, "_wgp", FakeWgp()):
        outputs = director_pipeline._run_minimax_h3_story_video(
            "h3story",
            {},
            [{"video_prompt": "first"}, {"video_prompt": "second"}],
            [{"start": 0, "end": 5}, {"start": 5, "end": 10}],
            start_images,
            {"num_inference_steps": 20},
            "1344x768",
            str(tmp_path),
        )

    assert all(expected in item["prompt"] for expected, item in zip(["first", "second"], submitted))
    assert all("overall_soundscape:" in item["prompt"] for item in submitted)
    assert all(item["model_type"] == "minimax_h3" for item in submitted)
    assert all(item["image_start"].endswith(f"shot_{index}.png") for index, item in enumerate(submitted))
    assert [item["_director_progress_label"] for item in submitted] == [
        "H3 Legacy · clip 1/2",
        "H3 Legacy · clip 2/2",
    ]
    assert outputs == ["clip_1.mp4", "clip_2.mp4", "minimax_h3_h3story_multiclip.mp4"]
    assert (tmp_path / "minimax_h3_h3story_multiclip.mp4").is_file()


def test_h3_direct_video_repeats_master_and_never_sends_images(tmp_path: Path):
    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        name = f"direct_{len(submitted)}.mp4"
        (tmp_path / name).write_bytes(b"video")
        return [name]

    class FakeWgp:
        @staticmethod
        def concatenate_multi_clip_videos(
            paths, destination, audio_path, audio_start_sec=0.0,
        ):
            assert len(paths) == 2
            assert audio_path == "/music/song.wav"
            assert audio_start_sec == 0.0
            Path(destination).write_bytes(b"assembled")
            return True

    params = {
        "pipeline_type": "music_video",
        "audio_path": "/music/song.wav",
        "reference_image_path": "/ignored/portrait.png",
        "character_ref_paths": ["/ignored/character.png"],
        "music_video_treatment": {
            "generation_mode": "direct_video",
            "direct_video_master_prompt": "IMMUTABLE HEAVY METAL WORLD.",
        },
    }
    plan = {
        "scene_goal": "A duel above an alien city",
        "environment": "a rusted bridge under a purple sky",
        "video_prompt": (
            "The armored warrior advances. The creature spreads its wings. "
            "The camera circles once. Both freeze before the strike."
        ),
    }
    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch.object(director_pipeline, "_save_pipeline_state"), \
            patch.object(director_pipeline, "_wgp", FakeWgp()):
        outputs = director_pipeline._run_minimax_h3_story_video(
            "h3direct",
            params,
            [plan],
            [{"duration_sec": 10}],
            [""],
            {
                "num_inference_steps": 20,
                "h3_reference_mode": "references",
                "h3_ref_videos": ["/ignored/motion.mp4"],
                "h3_ref_audios": ["/ignored/voice.wav"],
            },
            "544x960",
            str(tmp_path),
        )

    assert len(submitted) == 2
    assert all("integrated_multimodal_description:" in item["prompt"] for item in submitted)
    assert all("[Shot 1]" in item["prompt"] for item in submitted)
    assert all("Shared visual direction: IMMUTABLE HEAVY METAL WORLD" in item["prompt"] for item in submitted)
    assert all("A duel above an alien city" in item["prompt"] for item in submitted)
    assert all("Scene overview:" not in item["prompt"] for item in submitted)
    assert all("overall_soundscape:" in item["prompt"] for item in submitted)
    assert all(item["prompt"].count("overall_soundscape:") == 1 for item in submitted)
    assert all(
        "overall_soundscape:" not in item["prompt"].split(
            "overall_soundscape:", 1
        )[0]
        for item in submitted
    )
    assert all("overall_soundscape: N/A" in item["prompt"] for item in submitted)
    assert all(
        "Follow the selected song section as the musical and timing anchor" in item["prompt"]
        for item in submitted
    )
    assert all("PORTRAIT COMPOSITION LOCK:" in item["prompt"] for item in submitted)
    assert all("full 544x960 vertical portrait canvas" in item["prompt"] for item in submitted)
    assert all("VISIBLE TEXT LOCK" in item["prompt"] for item in submitted)
    assert all("Picture 1" not in item["prompt"] for item in submitted)
    assert all(is_structured_h3_prompt(item["prompt"], "direct") for item in submitted)
    assert all(item["image_prompt_type"] == "" for item in submitted)
    assert all("image_start" not in item and "image_refs" not in item for item in submitted)
    assert all("h3_ref_videos" not in item and "h3_ref_audios" not in item for item in submitted)
    assert outputs[-1] == "minimax_h3_h3direct_multiclip.mp4"


def test_h3_story_wrapper_releases_runtime_after_failure(tmp_path: Path):
    params = {
        "video_model": "minimax_h3",
        "pipeline_type": "short_film_story",
        "video_params": {"resolution": "960x544"},
    }
    with patch.object(
        director_pipeline,
        "_run_minimax_h3_story_video",
        side_effect=RuntimeError("render failed"),
    ), patch.object(director_pipeline, "_stop_minimax_h3_runtime") as stop_runtime:
        try:
            director_pipeline._run_video_generation(
                "h3failure",
                params,
                [],
                [],
                [],
                out_dir=str(tmp_path),
            )
        except RuntimeError as exc:
            assert str(exc) == "render failed"
        else:  # pragma: no cover - regression assertion
            raise AssertionError("Expected the simulated H3 render failure")

    stop_runtime.assert_called_once()


def test_current_h3_registry_uses_native_bounded_renderer():
    assert not director_pipeline._uses_legacy_h3_renderer(
        "minimax_h3",
        {
            "architecture": "minimax_h3",
            "director_video_strategy": "bounded_start_end",
        },
    )
    assert not director_pipeline._uses_legacy_h3_renderer(
        "minimax_h3_ref2va",
        {
            "architecture": "minimax_h3_ref2va",
            "director_video_strategy": "omni_reference",
        },
    )
    assert director_pipeline._uses_legacy_h3_renderer(
        "minimax_h3_legacy",
        {
            "architecture": "minimax_h3_legacy",
            "director_video_strategy": "bounded_start_end",
        },
    )


def test_registryless_h3_music_video_keeps_legacy_sequential_compatibility(tmp_path: Path):
    params = {
        "video_model": "minimax_h3",
        "pipeline_type": "music_video",
        "video_params": {"resolution": "960x544"},
    }
    with patch.object(
        director_pipeline,
        "_run_minimax_h3_story_video",
        return_value=["clip_1.mp4", "movie.mp4"],
    ) as render, patch.object(director_pipeline, "_stop_minimax_h3_runtime") as stop_runtime:
        outputs = director_pipeline._run_video_generation(
            "h3music",
            params,
            [{"video_prompt": "first"}, {"video_prompt": "second"}],
            [{"start": 0, "end": 5}, {"start": 5, "end": 10}],
            ["first.png", "second.png"],
            out_dir=str(tmp_path),
        )

    assert outputs == ["clip_1.mp4", "movie.mp4"]
    render.assert_called_once()
    stop_runtime.assert_called_once()


def test_incomplete_h3_checkpoint_is_not_treated_as_completed(tmp_path: Path):
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.write_bytes(b"video")
    state = {
        "video_model": "minimax_h3",
        "clips": [
            {
                "planned_clip": {"duration_sec": 5},
                "h3_segments": [{"index": 0, "filename": first.name, "frames": 124}],
            },
            {
                "planned_clip": {"duration_sec": 5},
                "h3_segments": [],
            },
        ],
    }

    assert not director_pipeline._h3_checkpoint_is_complete(state, str(tmp_path))

    second.write_bytes(b"video")
    state["clips"][1]["h3_segments"] = [{"index": 0, "filename": second.name, "frames": 124}]
    assert director_pipeline._h3_checkpoint_is_complete(state, str(tmp_path))


def test_h3_resume_reuses_completed_segments_before_rendering_the_rest(tmp_path: Path):
    first_frame = tmp_path / "first.png"
    second_frame = tmp_path / "second.png"
    existing = tmp_path / "existing.mp4"
    for path in (first_frame, second_frame, existing):
        path.write_bytes(b"video")
    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        output = tmp_path / "new.mp4"
        output.write_bytes(b"video")
        return [output.name]

    class FakeWgp:
        @staticmethod
        def concatenate_multi_clip_videos(
            paths, destination, audio_path, audio_start_sec=0.0,
        ):
            assert [Path(path).name for path in paths] == ["existing.mp4", "new.mp4"]
            assert audio_path is None
            assert audio_start_sec == 0.0
            Path(destination).write_bytes(b"assembled")
            return True

    previous_pipelines = director_pipeline._pipelines
    director_pipeline._pipelines = {
        "h3resume": {
            "_h3_segments": [[{
                "index": 0,
                "filename": existing.name,
                "frames": 124,
                "stale": False,
            }], []],
        },
    }
    try:
        with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
                patch.object(director_pipeline, "_save_pipeline_state"), \
                patch.object(director_pipeline, "_wgp", FakeWgp()):
            outputs = director_pipeline._run_minimax_h3_story_video(
                "h3resume",
                {},
                [{"video_prompt": "first"}, {"video_prompt": "second"}],
                [{"duration_sec": 5}, {"duration_sec": 5}],
                [first_frame.name, second_frame.name],
                {"num_inference_steps": 20},
                "960x544",
                str(tmp_path),
            )
    finally:
        director_pipeline._pipelines = previous_pipelines

    assert len(submitted) == 1
    assert "second" in submitted[0]["prompt"]
    assert outputs == ["existing.mp4", "new.mp4", "minimax_h3_h3resume_multiclip.mp4"]


def test_h3_story_first_frame_mode_does_not_silently_send_omni_refs(tmp_path: Path):
    shot = tmp_path / "shot.png"
    portrait = tmp_path / "portrait.png"
    location = tmp_path / "location.png"
    for path in (shot, portrait, location):
        path.write_bytes(b"frame")

    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        (tmp_path / "clip.mp4").write_bytes(b"video")
        return ["clip.mp4"]

    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch.object(director_pipeline, "_save_pipeline_state"):
        director_pipeline._run_minimax_h3_story_video(
            "h3firstframe",
            {
                "character_ref_paths": [str(portrait)],
                "location_ref_paths": [str(location)],
            },
            [{"video_prompt": "Use the supplied image as the exact first frame. She turns."}],
            [{"start": 0, "end": 5}],
            [shot.name],
            {"num_inference_steps": 20, "h3_reference_mode": "first_frame"},
            "960x544",
            str(tmp_path),
        )

    assert submitted[0]["image_start"] == str(shot)
    assert "image_refs" not in submitted[0]
    assert "at 0.00 seconds" in submitted[0]["prompt"].casefold()


def test_h3_story_routes_director_omni_references_to_ref2va(tmp_path: Path):
    shot = tmp_path / "shot.png"
    portrait = tmp_path / "portrait.png"
    location = tmp_path / "location.png"
    for path in (shot, portrait, location):
        path.write_bytes(b"frame")

    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        (tmp_path / "clip.mp4").write_bytes(b"video")
        return ["clip.mp4"]

    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch.object(director_pipeline, "_save_pipeline_state"):
        outputs = director_pipeline._run_minimax_h3_story_video(
            "h3refs",
            {
                "video_model": "minimax_h3_legacy",
                "reference_image_path": str(portrait),
                "location_ref_paths": [str(location)],
            },
            [{"video_prompt": "keep the references consistent"}],
            [{"start": 0, "end": 5}],
            [shot.name],
            {
                "num_inference_steps": 20,
                "h3_model_profile": "balanced",
                "h3_reference_mode": "references",
                "h3_ref_videos": ["/refs/motion.mp4"],
                "h3_ref_audios": ["/refs/voice.wav"],
            },
            "960x544",
            str(tmp_path),
        )

    assert outputs == ["clip.mp4"]
    assert submitted[0]["image_refs"] == [str(shot), str(portrait), str(location)]
    assert submitted[0]["h3_ref_videos"] == ["/refs/motion.mp4"]
    assert submitted[0]["h3_ref_audios"] == ["/refs/voice.wav"]
    assert submitted[0]["h3_model_profile"] == "balanced"
    assert submitted[0]["model_type"] == "minimax_h3_legacy"
    assert "image_start" not in submitted[0]


def test_h3_single_shot_music_video_restores_uploaded_soundtrack(tmp_path: Path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"frame")
    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        (tmp_path / "clip.mp4").write_bytes(b"video")
        return ["clip.mp4"]

    class FakeWgp:
        @staticmethod
        def concatenate_multi_clip_videos(
            paths, destination, audio_path, audio_start_sec=0.0,
        ):
            assert [Path(path).name for path in paths] == ["clip.mp4"]
            assert audio_path == "/music/song.mp3"
            assert audio_start_sec == 0.0
            Path(destination).write_bytes(b"assembled")
            return True

    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch.object(director_pipeline, "_save_pipeline_state"), \
            patch.object(director_pipeline, "_wgp", FakeWgp()):
        outputs = director_pipeline._run_minimax_h3_story_video(
            "h3singlemusic",
            {
                "video_model": "minimax_h3_legacy",
                "pipeline_type": "music_video",
                "audio_path": "/music/song.mp3",
            },
            [{"video_prompt": "A single continuous performance shot."}],
            [{"start": 0, "end": 5}],
            [shot.name],
            {"num_inference_steps": 20, "h3_reference_mode": "first_frame"},
            "960x544",
            str(tmp_path),
        )

    assert submitted[0]["model_type"] == "minimax_h3_legacy"
    assert outputs == [
        "clip.mp4",
        "minimax_h3_h3singlemusic_multiclip.mp4",
    ]
    sidecar = json.loads(
        (tmp_path / "minimax_h3_h3singlemusic_multiclip.meta.json")
        .read_text(encoding="utf-8")
    )
    assert sidecar["params"]["model_type"] == "minimax_h3_legacy"


def test_h3_legacy_assembly_offsets_source_audio_to_plan_start(tmp_path: Path):
    """Music-video plans that skip an intro must mux from that source time.

    Per-clip H3 drive already slices from audio_origin_sec. The finished
    multiclip used to remux the song from 0:00, so verse lips landed on the
    instrumental intro.
    """
    start_images = []
    for index in range(2):
        path = tmp_path / f"shot_{index}.png"
        path.write_bytes(b"frame")
        start_images.append(path.name)
    song = tmp_path / "song.mp3"
    song.write_bytes(b"audio")
    slice_starts = []
    captured = {}
    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        name = f"clip_{len(submitted)}.mp4"
        (tmp_path / name).write_bytes(b"video")
        return [name]

    def slice_audio(_src, start_sec, _duration, dst):
        slice_starts.append(start_sec)
        Path(dst).write_bytes(b"wav")

    class FakeWgp:
        @staticmethod
        def concatenate_multi_clip_videos(
            paths, destination, audio_path, audio_start_sec=0.0,
        ):
            captured["paths"] = [Path(path).name for path in paths]
            captured["audio_path"] = audio_path
            captured["audio_start_sec"] = audio_start_sec
            Path(destination).write_bytes(b"assembled")
            return True

    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch.object(director_pipeline, "_slice_audio_segment", side_effect=slice_audio), \
            patch.object(director_pipeline, "_save_pipeline_state"), \
            patch.object(director_pipeline, "_wgp", FakeWgp()):
        outputs = director_pipeline._run_minimax_h3_story_video(
            "h3offset",
            {
                "video_model": "minimax_h3_legacy",
                "pipeline_type": "music_video",
                "audio_path": str(song),
            },
            [
                {"video_prompt": "The singer hits the first verse."},
                {"video_prompt": "The chorus lands on the hook."},
            ],
            [
                {"start": 12.5, "end": 17.5, "duration_sec": 5},
                {"start": 17.5, "end": 22.5, "duration_sec": 5},
            ],
            start_images,
            {"num_inference_steps": 20, "h3_reference_mode": "first_frame"},
            "960x544",
            str(tmp_path),
        )

    assert slice_starts[0] == 12.5
    assert captured["audio_path"] == str(song)
    assert captured["audio_start_sec"] == 12.5
    assert outputs[-1] == "minimax_h3_h3offset_multiclip.mp4"


def test_h3_legacy_music_video_slices_each_shot_from_its_timeline_offset(tmp_path: Path):
    """Shot 2+ must be conditioned on the song after prior segments, not clip 0."""
    song = tmp_path / "song.wav"
    song.write_bytes(b"RIFF")
    start_images = []
    for index in range(2):
        path = tmp_path / f"shot_{index}.png"
        path.write_bytes(b"frame")
        start_images.append(path.name)

    submitted = []
    slices = []

    def submit(params, **_kwargs):
        submitted.append(params)
        name = f"clip_{len(submitted)}.mp4"
        (tmp_path / name).write_bytes(b"video")
        return [name]

    def slice_audio(src, start_sec, duration_sec, dst):
        slices.append((src, float(start_sec), float(duration_sec), dst))
        Path(dst).write_bytes(b"slice")

    class FakeWgp:
        @staticmethod
        def concatenate_multi_clip_videos(paths, destination, audio_path, **_kwargs):
            Path(destination).write_bytes(b"assembled")
            return True

    fps = 24
    first_frames = director_pipeline._minimax_h3_frame_segments(5.0, fps)[0]

    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch.object(director_pipeline, "_slice_audio_segment", side_effect=slice_audio), \
            patch.object(director_pipeline, "_save_pipeline_state"), \
            patch.object(director_pipeline, "_wgp", FakeWgp()):
        director_pipeline._run_minimax_h3_story_video(
            "h3offset",
            {
                "video_model": "minimax_h3_legacy",
                "pipeline_type": "music_video",
                "audio_path": str(song),
            },
            [{"video_prompt": "first verse"}, {"video_prompt": "second verse"}],
            [{"start": 2, "end": 7}, {"start": 7, "end": 12}],
            start_images,
            {"num_inference_steps": 20, "h3_reference_mode": "first_frame"},
            "960x544",
            str(tmp_path),
        )

    assert len(slices) == 2
    assert slices[0][0] == str(song)
    assert slices[0][1] == 2.0
    assert slices[1][1] == 2.0 + first_frames / fps
    assert submitted[0]["audio_guide"] == slices[0][3]
    assert submitted[1]["audio_guide"] == slices[1][3]
    assert submitted[0]["audio_prompt_type"] == "A"
    assert submitted[1]["audio_prompt_type"] == "A"
    assert all(
        Path(item[3]).parent.parent.name == ".director-tmp"
        for item in slices
    )
    assert not (tmp_path / ".director-tmp").exists()


def test_h3_legacy_resume_advances_audio_offset_past_reused_segments(tmp_path: Path):
    """Reused shot 1 must still move the song cursor before rendering shot 2."""
    song = tmp_path / "song.wav"
    song.write_bytes(b"RIFF")
    first_frame = tmp_path / "shot_0.png"
    second_frame = tmp_path / "shot_1.png"
    first_frame.write_bytes(b"frame")
    second_frame.write_bytes(b"frame")
    existing = tmp_path / "existing.mp4"
    existing.write_bytes(b"video")

    submitted = []
    slices = []

    def submit(params, **_kwargs):
        submitted.append(params)
        name = f"new_{len(submitted)}.mp4"
        (tmp_path / name).write_bytes(b"video")
        return [name]

    def slice_audio(src, start_sec, duration_sec, dst):
        slices.append(float(start_sec))
        Path(dst).write_bytes(b"slice")

    class FakeWgp:
        @staticmethod
        def concatenate_multi_clip_videos(paths, destination, audio_path, **_kwargs):
            Path(destination).write_bytes(b"assembled")
            return True

    fps = 24
    reused_frames = 124
    previous_pipelines = director_pipeline._pipelines
    director_pipeline._pipelines = {
        "h3resumeaudio": {
            "_h3_segments": [[{
                "index": 0,
                "filename": existing.name,
                "frames": reused_frames,
                "stale": False,
            }], []],
        },
    }
    try:
        with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
                patch.object(director_pipeline, "_slice_audio_segment", side_effect=slice_audio), \
                patch.object(director_pipeline, "_save_pipeline_state"), \
                patch.object(director_pipeline, "_wgp", FakeWgp()):
            director_pipeline._run_minimax_h3_story_video(
                "h3resumeaudio",
                {
                    "video_model": "minimax_h3_legacy",
                    "pipeline_type": "music_video",
                    "audio_path": str(song),
                },
                [{"video_prompt": "first"}, {"video_prompt": "second"}],
                [{"start": 2, "end": 7}, {"start": 7, "end": 12}],
                [first_frame.name, second_frame.name],
                {"num_inference_steps": 20},
                "960x544",
                str(tmp_path),
            )
    finally:
        director_pipeline._pipelines = previous_pipelines

    assert len(submitted) == 1
    assert "second" in submitted[0]["prompt"]
    assert slices == [2.0 + reused_frames / fps]
    assert submitted[0]["audio_guide"]


def test_h3_story_routes_only_the_location_selected_for_the_shot(tmp_path: Path):
    shot = tmp_path / "shot.png"
    character = tmp_path / "character.png"
    locations = [tmp_path / f"location_{index}.png" for index in range(9)]
    for path in [shot, character, *locations]:
        path.write_bytes(b"frame")

    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        (tmp_path / "clip.mp4").write_bytes(b"video")
        return ["clip.mp4"]

    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch.object(director_pipeline, "_save_pipeline_state"):
        outputs = director_pipeline._run_minimax_h3_story_video(
            "h3manyrefs",
            {
                "character_ref_paths": [str(character)],
                "location_ref_paths": [str(path) for path in locations],
                "location_ref_labels": [f"Location {index}" for index in range(9)],
            },
            [{
                "video_prompt": "keep the cast and selected location consistent",
                "metadata": {"location_ref_label": "Location 7"},
            }],
            [{"start": 0, "end": 5}],
            [shot.name],
            {"num_inference_steps": 20, "h3_reference_mode": "references"},
            "960x544",
            str(tmp_path),
        )

    assert outputs == ["clip.mp4"]
    assert submitted[0]["image_refs"] == [
        str(shot),
        str(character),
        str(locations[7]),
    ]


def test_h3_story_legacy_plan_matches_one_location_from_prompt(tmp_path: Path):
    shot = tmp_path / "shot.png"
    desert = tmp_path / "desert.png"
    harbor = tmp_path / "harbor.png"
    for path in (shot, desert, harbor):
        path.write_bytes(b"frame")

    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        (tmp_path / "clip.mp4").write_bytes(b"video")
        return ["clip.mp4"]

    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch.object(director_pipeline, "_save_pipeline_state"):
        director_pipeline._run_minimax_h3_story_video(
            "h3legacy",
            {
                "location_ref_paths": [str(desert), str(harbor)],
                "location_ref_labels": ["Crystal Desert", "Moon Harbor"],
            },
            [{"video_prompt": "A wide view across the silent Crystal Desert."}],
            [{"start": 0, "end": 5}],
            [shot.name],
            {"num_inference_steps": 20, "h3_reference_mode": "references"},
            "960x544",
            str(tmp_path),
        )

    assert submitted[0]["image_refs"] == [str(shot), str(desert)]


def test_h3_unwindowed_story_prompt_is_split_without_repeating_actions():
    plan = {
        "video_prompt": (
            "Use the supplied image as the exact first frame. "
            "Animate the artwork without changing its visual medium. "
            "She walks forward. She stops. She kneels. She uncovers a sphere. "
            "She lifts it. A map appears. She studies it. She walks away."
        ),
    }

    prompts = [
        director_pipeline._minimax_h3_segment_prompt(plan, index, 4)
        for index in range(4)
    ]

    assert all("Perform only these actions" in prompt for prompt in prompts)
    assert "She walks forward" in prompts[0]
    assert "She walks away" in prompts[-1]
    assert "She walks forward" not in prompts[-1]
    assert "do not repeat actions" in prompts[1]


def test_h3_ref2va_prompt_does_not_claim_an_exact_first_frame():
    prompt = director_pipeline._minimax_h3_segment_prompt({
        "video_prompt": "Use the supplied image as the exact first frame. She turns around.",
    }, 0, 1, reference_mode="references")

    assert "exact first frame" not in prompt.casefold()
    assert "Compose one new continuous shot" in prompt


def test_h3_prompt_validator_cannot_rewrite_authored_audio():
    draft = (
        "Use the supplied image as the exact first frame. She opens the door. "
        'Audio: rain; Mara says "We leave at dawn."'
    )
    candidate = (
        "She slowly opens the door with one clear movement. "
        "Audio: loud music and different dialogue."
    )

    validated = director_pipeline._h3_validated_candidate(
        candidate,
        draft,
        "first_frame",
    )

    assert 'Audio: rain; Mara says "We leave at dawn."' in validated
    assert "loud music" not in validated
    assert "exact first frame" in validated.casefold()


def test_h3_story_runs_one_guarded_optimizer_pass_for_exact_segments():
    old_pipelines = director_pipeline._pipelines
    director_pipeline._pipelines = {"h3opt": {"_llm_passes": []}}

    def optimize(**kwargs):
        entries = json.loads(kwargs["prompt"].split("prompts:\n", 1)[1])
        return json.dumps(entries)

    try:
        with patch.object(director_pipeline, "_scoped_writing_llm", return_value={
            "provider": "minimax",
            "model": "MiniMax-M3",
            "base_url": "https://api.minimax.io/v1",
            "api_key": "test-key",
        }), patch("app.services.llm_service.generate_openai_compatible", side_effect=optimize) as generate:
            plans = director_pipeline._optimize_minimax_h3_story_prompts(
                "h3opt",
                {
                    "video_model": "minimax_h3",
                    "video_params": {"h3_reference_mode": "first_frame"},
                },
                [{
                    "video_prompt": (
                        "Use the supplied image as the exact first frame. "
                        "Animate the artwork without changing its visual medium. "
                        "She walks. She stops."
                    ),
                }],
                [{"duration_sec": 5}],
            )
    finally:
        director_pipeline._pipelines = old_pipelines

    generate.assert_called_once()
    assert len(plans[0]["h3_segment_prompts"]) == 1
    assert plans[0]["metadata"]["h3_prompt_validation"] == "optimized"
    assert "overall_soundscape:" in plans[0]["h3_segment_prompts"][0]


def test_legacy_location_matching_handles_spanish_labels_and_english_prompts():
    params = {
        "location_ref_paths": [
            "/refs/crystal-desert.png",
            "/refs/plateau-tree.png",
            "/refs/horizon.png",
        ],
        "location_ref_labels": [
            "Gran Desierto de Cristales",
            "Meseta del Último Árbol",
            "Línea del Horizonte",
        ],
    }

    desert = director_pipeline._director_location_ref_for_plan({
        "image_prompt": "A crystal desert under a turquoise sky.",
        "video_prompt": "She walks across prisms toward the horizon.",
    }, params)
    plateau = director_pipeline._director_location_ref_for_plan({
        "image_prompt": "A dark plateau with cracked earth and dry roots.",
        "video_prompt": "A glowing tree grows beside the robot.",
    }, params)

    assert desert == ("/refs/crystal-desert.png", "Gran Desierto de Cristales")
    assert plateau == ("/refs/plateau-tree.png", "Meseta del Último Árbol")


def test_story_image_generation_routes_only_one_location_per_shot(tmp_path: Path):
    main = tmp_path / "main.png"
    character = tmp_path / "character.png"
    desert = tmp_path / "desert.png"
    harbor = tmp_path / "harbor.png"
    for path in (main, character, desert, harbor):
        path.write_bytes(b"frame")

    submitted = []

    def submit(params, **_kwargs):
        submitted.append(params)
        name = "frame.png"
        (tmp_path / name).write_bytes(b"generated")
        return [name]

    old_pipelines = director_pipeline._pipelines
    director_pipeline._pipelines = {"images": {"status": "running"}}
    try:
        with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
                patch.object(director_pipeline, "_update_pipeline"), \
                patch.object(director_pipeline, "_wgp", SimpleNamespace(save_path=str(tmp_path))):
            images, _ = director_pipeline._run_image_generation(
                "images",
                {
                    "reference_image_path": str(main),
                    "character_ref_paths": [str(character)],
                    "location_ref_paths": [str(desert), str(harbor)],
                    "location_ref_labels": ["Crystal Desert", "Moon Harbor"],
                    "image_model": "flux2_klein_9b",
                    "image_params": {"resolution": "1280x720"},
                },
                [{
                    "image_prompt": "A static frame at the harbor.",
                    "metadata": {"location_ref_label": "Moon Harbor"},
                }],
                out_dir=str(tmp_path),
            )
    finally:
        director_pipeline._pipelines = old_pipelines

    assert images == ["frame.png"]
    assert submitted[0]["image_refs"] == [str(main), str(character), str(harbor)]
