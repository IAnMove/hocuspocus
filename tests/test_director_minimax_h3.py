"""Regression tests for Story Director's MiniMax H3 duration adapter."""

from pathlib import Path
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
