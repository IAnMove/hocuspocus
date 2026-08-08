from pathlib import Path
from unittest.mock import patch

from app.services import director_pipeline


def test_h3_internal_continuations_use_character_refs_and_stable_seeds(tmp_path: Path):
    shot = tmp_path / "shot.png"
    portrait = tmp_path / "portrait.png"
    shot.write_bytes(b"shot")
    portrait.write_bytes(b"portrait")
    submitted: list[dict] = []

    def submit(params, **_kwargs):
        submitted.append(params)
        output = tmp_path / f"segment_{len(submitted)}.mp4"
        output.write_bytes(b"video")
        return [output.name]

    class FakeWgp:
        @staticmethod
        def concatenate_multi_clip_videos(paths, destination, audio_path):
            assert len(paths) == 2
            assert audio_path is None
            Path(destination).write_bytes(b"joined")
            return True

    with patch.object(director_pipeline, "_submit_and_wait", side_effect=submit), \
            patch.object(director_pipeline, "_save_pipeline_state"), \
            patch("app.services.video_editor.probe_media", return_value={"duration": 5.16}), \
            patch("app.services.video_editor.extract_frame", side_effect=lambda _src, dst, _at: Path(dst).write_bytes(b"continuity")), \
            patch.object(director_pipeline, "_wgp", FakeWgp()):
        director_pipeline._run_minimax_h3_story_video(
            "identitysafe",
            {
                "master_seed": 1200,
                "character_ref_paths": [str(portrait)],
            },
            [{"video_prompt": "She walks. She crouches. Her face becomes visible."}],
            [{"duration_sec": 10}],
            [shot.name],
            {"h3_reference_mode": "first_frame"},
            "960x544",
            str(tmp_path),
        )

    assert len(submitted) == 2
    assert submitted[0]["h3_reference_mode"] == "first_frame"
    assert submitted[0]["image_start"] == str(shot)
    assert "image_refs" not in submitted[0]
    assert submitted[1]["h3_reference_mode"] == "references"
    assert submitted[1]["image_refs"][1:] == [str(portrait)]
    assert submitted[0]["seed"] == submitted[1]["seed"] - 1
    assert submitted[0]["seed"] >= 0
    assert all("IDENTITY CONTINUITY LOCK" in item["prompt"] for item in submitted)
    assert "exact first frame" not in submitted[1]["prompt"].casefold()


def test_h3_identity_contract_stays_before_native_audio_clause():
    prompt = director_pipeline._h3_apply_identity_contract(
        "She turns toward camera.\nAudio: quiet wind."
    )

    assert prompt.index("IDENTITY CONTINUITY LOCK") < prompt.index("Audio:")
    assert prompt.endswith("Audio: quiet wind.")
