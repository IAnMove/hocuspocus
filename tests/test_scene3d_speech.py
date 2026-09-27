import io
import json
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.character_kit_face import create_character_kit_face_router
from services import scene3d_speech as speech
from services.speech_analysis_cache import reset_runtime_state


@pytest.fixture(autouse=True)
def _speech_analysis_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEECH_ANALYSIS_CACHE_DIR", str(tmp_path / "speech-cache"))
    reset_runtime_state()
    yield
    reset_runtime_state()


def wav(seconds=1, rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\0\0" * int(seconds * rate))
    return output.getvalue()


def test_reject_invalid_long_and_truncated_wav():
    assert speech.validate_voice_wav(wav()) == 1
    for data in [b"not wav", wav(rate=8000), wav(seconds=91), wav()[:-20], b"x" * (speech.MAX_BYTES + 1)]:
        with pytest.raises(speech.SpeechAnalysisError):
            speech.validate_voice_wav(data)


def test_missing_rhubarb_is_actionable(monkeypatch):
    monkeypatch.setattr(speech, "rhubarb_executable", lambda: None)
    with pytest.raises(speech.SpeechAnalysisUnavailable, match="RHUBARB_EXECUTABLE"):
        speech.analyze_voice(wav())


def test_local_process_has_bounds_and_no_shell(monkeypatch, tmp_path):
    monkeypatch.setattr(speech, "rhubarb_executable", lambda: "/configured/rhubarb")
    monkeypatch.setattr(speech.tempfile, "mkdtemp", lambda **kwargs: str(tmp_path))

    def run(args, **kwargs):
        assert kwargs["shell"] is False and kwargs["timeout"] == 90
        assert args[args.index("-r") + 1] == "phonetic"
        Path(args[args.index("-o") + 1]).write_text(json.dumps({"mouthCues": [{"start": 0, "end": 1, "value": "D"}]}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(speech.subprocess, "run", run)
    assert speech.analyze_voice(wav())["mouthCues"][0]["value"] == "D"
    assert (tmp_path / "voice.wav").exists()


def test_router_mounted_under_existing_character_boundary(monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(create_character_kit_face_router(workspace_dir=lambda _: str(tmp_path), uploads_root=lambda: str(tmp_path)))
    client = TestClient(app)
    path = "/api/v1/character-kits/speech/analyze"
    assert client.post(path, content=wav()).status_code == 415
    assert client.post(path, content=b"bad", headers={"content-type": "audio/wav"}).status_code == 400
    monkeypatch.setattr(speech, "rhubarb_executable", lambda: None)
    assert client.post(path, content=wav(), headers={"content-type": "audio/wav"}).status_code == 503
    assert client.post(path, content=b"x" * (speech.MAX_BYTES + 1), headers={"content-type": "audio/wav"}).status_code == 413
