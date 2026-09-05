import base64
import json

import pytest

from app.services import minimax_music_service
from app.services import resource_scheduler


class FakeResponse:
    ok = True
    status_code = 200

    def json(self):
        return {
            "data": {"audio": b"ID3-test-audio".hex(), "status": 2},
            "extra_info": {"music_duration": 91234},
            "trace_id": "trace-1",
            "base_resp": {"status_code": 0, "status_msg": "success"},
        }


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse()


def test_generates_three_persistent_candidates(tmp_path):
    session = FakeSession()
    results = minimax_music_service.generate_candidates(
        api_key="secret",
        prompt="cinematic dream pop, emotional female vocal",
        lyrics="[Verse]\nWe cross the night\n[Chorus]\nBring us home",
        count=3,
        output_dir=str(tmp_path),
        session=session,
    )

    assert len(results) == 3
    assert len(session.calls) == 3
    assert all((tmp_path / item["filename"]).read_bytes() == b"ID3-test-audio" for item in results)
    metadata = json.loads((tmp_path / f"{results[0]['filename']}.json").read_text())
    assert metadata["model"] == "music-3.0"
    assert metadata["duration_seconds"] == 91.234
    sent = session.calls[0][1]["json"]
    assert sent["output_format"] == "hex"
    assert sent["audio_setting"]["sample_rate"] == 44100


def test_correlates_candidate_outputs_with_canonical_task_ids(tmp_path):
    results = minimax_music_service.generate_candidates(
        api_key="secret",
        prompt="cinematic dream pop",
        lyrics="[Verse]\nWe cross the night",
        count=1,
        output_dir=str(tmp_path),
        session=FakeSession(),
        task_id="task-minimax-music-candidate-1",
        root_task_id="task-minimax-music-root",
    )

    result = results[0]
    metadata = json.loads((tmp_path / f"{result['filename']}.json").read_text())
    assert result["task_id"] == "task-minimax-music-candidate-1"
    assert result["root_task_id"] == "task-minimax-music-root"
    assert metadata["task_id"] == result["task_id"]
    assert metadata["root_task_id"] == result["root_task_id"]


def test_cancelled_resource_wait_never_calls_minimax(tmp_path):
    session = FakeSession()

    with pytest.raises(resource_scheduler.ResourceAcquireCancelled):
        minimax_music_service.generate_candidates(
            api_key="secret",
            prompt="cinematic dream pop",
            lyrics="[Verse]\nWe cross the night",
            count=1,
            output_dir=str(tmp_path),
            session=session,
            task_id="task-minimax-music-cancelled",
            cancelled=lambda: True,
        )

    assert session.calls == []
    assert list(tmp_path.iterdir()) == []


def test_cover_sends_reference_audio_and_optional_rewritten_lyrics(tmp_path):
    reference = tmp_path / "reference.mp3"
    reference.write_bytes(b"ID3-reference")
    session = FakeSession()

    results = minimax_music_service.generate_candidates(
        api_key="secret",
        prompt="cinematic synth pop cover",
        lyrics="[Verse]\nA completely new story",
        count=1,
        output_dir=str(tmp_path / "output"),
        model="music-cover",
        reference_audio_path=str(reference),
        session=session,
    )

    sent = session.calls[0][1]["json"]
    assert sent["model"] == "music-cover"
    assert base64.b64decode(sent["audio_base64"]) == b"ID3-reference"
    assert sent["lyrics"] == "[Verse]\nA completely new story"
    assert "is_instrumental" not in sent
    metadata = json.loads((tmp_path / "output" / f"{results[0]['filename']}.json").read_text())
    assert metadata["mode"] == "cover"
    assert metadata["reference_audio_name"] == "reference.mp3"


def test_rejects_unknown_model(tmp_path):
    try:
        minimax_music_service.generate_candidates(
            api_key="secret", prompt="pop", lyrics="words", count=1,
            output_dir=str(tmp_path), model="music-9.9",
        )
    except minimax_music_service.MiniMaxMusicError as error:
        assert error.status_code == 400
        assert "Unsupported" in str(error)
    else:
        raise AssertionError("unknown model should fail")


def test_requires_key_and_vocal_lyrics(tmp_path):
    try:
        minimax_music_service.generate_candidates(
            api_key="", prompt="pop", lyrics="words", count=1, output_dir=str(tmp_path)
        )
    except minimax_music_service.MiniMaxMusicError as error:
        assert error.status_code == 400
    else:
        raise AssertionError("missing key should fail")

    try:
        minimax_music_service.generate_candidates(
            api_key="secret", prompt="pop", lyrics="", count=1, output_dir=str(tmp_path)
        )
    except minimax_music_service.MiniMaxMusicError as error:
        assert "Lyrics" in str(error)
    else:
        raise AssertionError("missing lyrics should fail")
