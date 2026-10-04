"""A spoken take is measured against its text: transcript, error rate, pitch, pace and silence."""
import asyncio

import numpy as np
import pytest
from fastapi import HTTPException

from services.speech_qa import command_catalog, command_handlers, measure_speech, word_error_rate, words


def test_numbers_accents_and_punctuation_do_not_count_as_errors():
    assert word_error_rate("Tenemos un 97% de éxito.", "tenemos un noventa y siete por ciento de exito", "es") == 0
    assert word_error_rate("We raised $40 million!", "we raised forty million", "en") == 0
    assert words("Self-driving, 2 cars", "en") == ["self", "driving", "two", "cars"]
    assert word_error_rate("one two three four", "one three four five", "en") == 0.5


def _stub_audio(seconds=4.0, lead=0.3, trail=0.2, rate=16000):
    audio = np.zeros(int(seconds * rate), dtype=np.float32)
    audio[int(lead * rate):int((seconds - trail) * rate)] = 0.2
    return audio, rate


def test_a_take_is_measured_and_warned_about_without_blocking():
    clean = measure_speech("take.wav", "This is fine, we have a product.", "English",
                           load=lambda _path: _stub_audio(), transcribe=lambda _audio, code: "This is fine. We have a product.",
                           pitch=lambda _audio, _rate: 120.0, pitch_range=[85, 165])
    assert clean["wer"] == 0 and clean["warnings"] == []
    assert (clean["leadSilence"], clean["trailSilence"], clean["duration"]) == (0.3, 0.2, 4.0)
    assert clean["wordsPerSecond"] == pytest.approx(7 / 3.5, abs=0.01)

    seen = {}
    off = measure_speech("take.wav", "This is fine, we have a product.", "Español de España",
                         load=lambda _path: _stub_audio(lead=1.0), transcribe=lambda _audio, code: seen.setdefault("code", code) and "This is",
                         pitch=lambda _audio, _rate: 230.0, pitch_range=[85, 165])
    assert seen["code"] == "es"
    assert len(off["warnings"]) == 3 and off["wer"] > 0.5
    assert any("230 Hz" in warning for warning in off["warnings"])


def test_the_mcp_tool_reads_workspace_files_only(tmp_path, monkeypatch):
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "take.wav").write_bytes(b"not decoded in this test")
    (tmp_path / "secret.wav").write_bytes(b"x")
    monkeypatch.setattr("services.speech_qa.measure_speech",
                        lambda path, text, language, pitch_range=None: {"path": path, "text": text, "language": language, "range": pitch_range})
    handle = command_handlers(lambda name: str(tmp_path / name))["qa.speech"]
    result = asyncio.run(handle({"version": 1, "input": {"workspace": "ws", "file": "/api/v1/file/take.wav?workspace=ws",
                                                         "text": "Hola.", "language": "es", "pitch_range": [80, 170]}}))
    assert result["result"]["path"].endswith("take.wav") and result["result"]["range"] == [80, 170]
    with pytest.raises(HTTPException) as error:
        asyncio.run(handle({"version": 1, "input": {"workspace": "ws", "file": "../secret.wav", "text": "x"}}))
    assert error.value.status_code == 404
    assert command_catalog()[0]["mutation"] is False
