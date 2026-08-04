import json

from app.services import minimax_music_service


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
    assert metadata["model"] == "music-2.6"
    assert metadata["duration_seconds"] == 91.234
    sent = session.calls[0][1]["json"]
    assert sent["output_format"] == "hex"
    assert sent["audio_setting"]["sample_rate"] == 44100


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
