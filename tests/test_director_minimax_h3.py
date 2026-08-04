"""Regression tests for Story Director's MiniMax H3 duration adapter."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services import director_pipeline


def test_h3_duration_segments_stay_on_the_supported_lattice():
    segments = director_pipeline._minimax_h3_frame_segments(45.0)

    assert len(segments) == 3
    assert all(107 <= frames <= 362 for frames in segments)
    assert all(frames % 17 == 5 for frames in segments)
    assert abs(sum(segments) - 45 * 24) <= 17 / 2


def test_h3_long_shot_is_split_without_losing_its_duration():
    segments = director_pipeline._minimax_h3_frame_segments(20.0)

    assert len(segments) == 2
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

    assert [prompt.splitlines()[0] for prompt in prompts] == ["opening", "middle", "ending"]
    assert all("Audio:" in prompt for prompt in prompts)


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

    assert "Audio:" in prompt
    assert "rain on the metal roof" in prompt
    assert "door clang" in prompt
    assert 'Mara says "We leave at dawn."' in prompt
    assert "precise lip sync" in prompt


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
        def concatenate_multi_clip_videos(paths, destination, audio_path):
            assert len(paths) == 2
            assert audio_path is None
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

    assert [item["prompt"].splitlines()[0] for item in submitted] == ["first", "second"]
    assert all("Audio:" in item["prompt"] for item in submitted)
    assert all(item["model_type"] == "minimax_h3" for item in submitted)
    assert all(item["image_start"].endswith(f"shot_{index}.png") for index, item in enumerate(submitted))
    assert outputs == ["clip_1.mp4", "clip_2.mp4", "minimax_h3_h3story_multiclip.mp4"]
    assert (tmp_path / "minimax_h3_h3story_multiclip.mp4").is_file()


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
                "reference_image_path": str(portrait),
                "location_ref_paths": [str(location)],
            },
            [{"video_prompt": "keep the references consistent"}],
            [{"start": 0, "end": 5}],
            [shot.name],
            {
                "num_inference_steps": 20,
                "h3_model_profile": "balanced",
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
    assert "image_start" not in submitted[0]


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
            {"num_inference_steps": 20},
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
            {"num_inference_steps": 20},
            "960x544",
            str(tmp_path),
        )

    assert submitted[0]["image_refs"] == [str(shot), str(desert)]


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
