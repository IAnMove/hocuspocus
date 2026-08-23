"""CPU-only regression tests for audio-analysis model cleanup."""

import sys
import types

import numpy as np
import pytest

from app.services import audio_analysis


@pytest.fixture(autouse=True)
def _reset_audio_progress():
    audio_analysis.set_progress_callback(None)
    audio_analysis.clear_progress()
    yield
    audio_analysis.set_progress_callback(None)
    audio_analysis.clear_progress()


@pytest.fixture
def analysis_path(tmp_path, monkeypatch):
    """Stub all signal-processing work so these tests never touch a GPU."""
    path = tmp_path / "song.wav"
    path.write_bytes(b"not-real-audio")

    fake_librosa = types.ModuleType("librosa")
    fake_librosa.get_duration = lambda **_kwargs: 8.0
    fake_librosa.get_samplerate = lambda _path: 44_100
    monkeypatch.setitem(sys.modules, "librosa", fake_librosa)
    monkeypatch.setattr(
        audio_analysis,
        "_load_audio",
        lambda _path: (np.zeros(16, dtype=np.float32), 22_050),
    )
    monkeypatch.setattr(
        audio_analysis,
        "_detect_beats",
        lambda _samples, _sample_rate: (
            120.0,
            [audio_analysis.Beat(time=0.0, strength=1.0)],
        ),
    )
    monkeypatch.setattr(
        audio_analysis,
        "_compute_onset_envelope",
        lambda _samples, _sample_rate: [0.5],
    )
    monkeypatch.setattr(
        audio_analysis,
        "_segment_sections",
        lambda _samples, _sample_rate, _beats, _duration: [
            audio_analysis.Section(
                start=0.0,
                end=8.0,
                label="verse",
                energy=0.5,
            )
        ],
    )
    return path


def _record_cleanup(monkeypatch):
    calls = []
    monkeypatch.setattr(
        audio_analysis,
        "unload_diarizer",
        lambda: calls.append("diarizer"),
    )
    monkeypatch.setattr(
        audio_analysis,
        "unload_whisper",
        lambda: calls.append("whisper"),
    )
    return calls


def test_transcription_models_are_unloaded_after_success(
    analysis_path,
    monkeypatch,
):
    calls = _record_cleanup(monkeypatch)
    lyrics = [
        audio_analysis.LyricSegment(
            start=0.0,
            end=1.0,
            text="hello",
            speaker="SPEAKER_00",
        )
    ]
    monkeypatch.setattr(
        audio_analysis,
        "_transcribe",
        lambda *_args, **_kwargs: lyrics,
    )
    monkeypatch.setattr(
        audio_analysis,
        "_diarize",
        lambda _path, segments: segments,
    )

    result = audio_analysis.analyze(
        str(analysis_path),
        transcribe=True,
        extract_vocals_for_transcription=False,
    )

    assert result["lyrics"][0]["text"] == "hello"
    assert calls == ["diarizer", "whisper"]


def test_transcription_error_still_degrades_and_unloads_models(
    analysis_path,
    monkeypatch,
    capsys,
):
    calls = _record_cleanup(monkeypatch)

    def fail_transcription(*_args, **_kwargs):
        raise ValueError("decoder failed")

    monkeypatch.setattr(audio_analysis, "_transcribe", fail_transcription)

    result = audio_analysis.analyze(
        str(analysis_path),
        transcribe=True,
        extract_vocals_for_transcription=False,
    )

    assert result["lyrics"] is None
    assert "continuing without lyrics: decoder failed" in capsys.readouterr().out
    assert calls == ["diarizer", "whisper"]


def test_progress_cancellation_unloads_models_before_propagating(
    analysis_path,
    monkeypatch,
):
    calls = _record_cleanup(monkeypatch)

    class AnalysisCancelled(RuntimeError):
        pass

    cancellation_started = False

    def cancel_from_progress(step, _detail):
        nonlocal cancellation_started
        if step == "transcribing":
            cancellation_started = True
        if cancellation_started:
            raise AnalysisCancelled("Audio analysis cancelled")

    audio_analysis.set_progress_callback(cancel_from_progress)

    with pytest.raises(AnalysisCancelled, match="Audio analysis cancelled"):
        audio_analysis.analyze(
            str(analysis_path),
            transcribe=True,
            extract_vocals_for_transcription=False,
        )

    assert calls == ["diarizer", "whisper"]


def test_one_cleanup_failure_does_not_skip_the_other_or_fail_analysis(
    analysis_path,
    monkeypatch,
    caplog,
):
    whisper_calls = []
    monkeypatch.setattr(audio_analysis, "_transcribe", lambda *_args, **_kwargs: [])

    def fail_diarizer_cleanup():
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(audio_analysis, "unload_diarizer", fail_diarizer_cleanup)
    monkeypatch.setattr(
        audio_analysis,
        "unload_whisper",
        lambda: whisper_calls.append(True),
    )

    result = audio_analysis.analyze(
        str(analysis_path),
        transcribe=True,
        extract_vocals_for_transcription=False,
    )

    assert result["bpm"] == 120.0
    assert whisper_calls == [True]
    assert "Could not fully unload the diarization model" in caplog.text
