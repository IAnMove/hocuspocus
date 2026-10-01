"""Real PCM normalization, source-clock cues and the workspace boundary."""
import io
import json
import wave

import pytest
from fastapi import HTTPException

from services import speech_file_commands as commands
from services.scene3d_speech import validate_voice_wav


def voice_file(root):
    source = root / "voice.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setparams((2, 2, 44100, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x00" * 2 * 44100 * 2)
    return source


def envelope(**patch):
    return {"version": 1, "input": {"workspace": "song", "file": "voice.wav", "duration": 1, **patch}}


@pytest.mark.parametrize("patch", [
    {"file": "../voice.wav"}, {"file": "/tmp/voice.wav"}, {"file": "..\\voice.wav"},
    {"workspace": "../song"}, {"duration": 91}, {"duration": 0}, {"duration": True},
    {"start": -1}, {"start": float("nan")}, {"duration": float("inf")},
    {"start": 590, "duration": 30}, {"unexpected": True}, {"dialogue": "\x00"},
])
def test_invalid_inputs_never_reach_the_decoder(tmp_path, patch):
    voice_file(tmp_path)
    with pytest.raises(HTTPException) as error:
        commands.freeze_window(envelope(**patch), lambda _: tmp_path)
    assert error.value.detail["code"] == "invalid_command"


@pytest.mark.parametrize("version", [True, 2, "1"])
def test_version_is_exact(tmp_path, version):
    voice_file(tmp_path)
    with pytest.raises(HTTPException):
        commands.freeze_window({**envelope(), "version": version}, lambda _: tmp_path)


def test_symlink_outside_workspace_is_rejected(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    source = voice_file(tmp_path)
    (root / source.name).symlink_to(source)
    with pytest.raises(HTTPException):
        commands.freeze_window(envelope(), lambda _: root)


def test_actual_stereo_wav_is_trimmed_and_normalized(tmp_path):
    source = voice_file(tmp_path)
    pcm = commands._window_wav(source, .5, 1)
    assert validate_voice_wav(pcm) == pytest.approx(1)
    with wave.open(io.BytesIO(pcm)) as audio:
        assert audio.getnchannels() == 1
        assert audio.getframerate() == 16000
        assert audio.getsampwidth() == 2
    assert commands._probe_duration(source) == pytest.approx(2)


def test_cues_use_source_time_and_preserve_real_phonetic_shapes(tmp_path, monkeypatch):
    voice_file(tmp_path)
    window, source, root = commands.freeze_window(envelope(start=1, duration=10, dialogue="Hello", language="en"), lambda _: tmp_path)
    received = []

    def analyze(data, **options):
        received.append((validate_voice_wav(data), options))
        return {"mouthCues": [{"start": .1, "end": .3, "value": "D"}, {"start": .3, "end": 1, "value": "X"}],
                "duration": 1, "recognizer": "pocketSphinx", "analysisSource": "original"}

    monkeypatch.setattr(commands, "analyze_voice", analyze)
    result = commands.analyze_window(window, source, root)
    assert received == [(1, {"dialogue": "Hello", "language": "en"})]
    assert result["duration"] == 1
    assert result["mouthCues"] == [{"start": 1.1, "end": 1.3, "value": "D"}, {"start": 1.3, "end": 2, "value": "X"}]
    assert json.loads((root / result["file"]).read_text())["mouthCues"] == result["mouthCues"]
    assert commands.analyze_window(window, source, root)["file"] == result["file"]


def test_window_after_end_is_rejected(tmp_path):
    voice_file(tmp_path)
    window, source, root = commands.freeze_window(envelope(start=3), lambda _: tmp_path)
    with pytest.raises(commands.SpeechAnalysisError):
        commands.analyze_window(window, source, root)


def test_registered_under_the_existing_audio_boundary(tmp_path):
    from services.song_analysis import command_catalog, command_handlers
    assert any(tool["name"] == commands.OPERATION for tool in command_catalog())
    assert commands.OPERATION in command_handlers(lambda _: tmp_path)
