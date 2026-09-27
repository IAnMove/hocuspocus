"""Reuse isolation and lip-cue analysis without downloading models."""
from __future__ import annotations

import io
import json
import os
import subprocess
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from services import scene3d_speech as speech
from services import vocal_isolation as vocals
from services.scene3d_speech import SpeechAnalysisError, SpeechAnalysisUnavailable
from services.speech_analysis_cache import (
    analysis_material,
    isolation_material,
    material_key,
    remember,
    reset_runtime_state,
)


@pytest.fixture(autouse=True)
def _cache_env(tmp_path, monkeypatch):
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


def _copy_worker(calls):
    def run(args, **kwargs):
        calls.append(args)
        Path(args[3]).write_bytes(Path(args[2]).read_bytes())
        return SimpleNamespace(returncode=0)
    return run


def test_three_shots_of_the_same_segment_isolate_once(monkeypatch):
    monkeypatch.setattr(vocals, "isolation_capability", lambda: {"available": True, "reason": "ready"})
    calls = []
    monkeypatch.setattr(vocals.subprocess, "run", _copy_worker(calls))
    source = wav(1)
    results = [vocals.isolate_voice(source) for _ in range(3)]
    assert len(calls) == 1
    assert results == [source, source, source]


def test_simultaneous_shots_share_one_worker(monkeypatch):
    monkeypatch.setattr(vocals, "isolation_capability", lambda: {"available": True, "reason": "ready"})
    calls = []
    entered = threading.Event()
    release = threading.Event()

    def run(args, **kwargs):
        calls.append(args)
        entered.set()
        assert release.wait(2)
        Path(args[3]).write_bytes(Path(args[2]).read_bytes())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(vocals.subprocess, "run", run)
    source = wav(1)
    results, errors = [None] * 3, [None] * 3

    def shot(index):
        try:
            results[index] = vocals.isolate_voice(source)
        except Exception as error:
            errors[index] = error

    threads = [threading.Thread(target=shot, args=(i,)) for i in range(3)]
    for thread in threads:
        thread.start()
    assert entered.wait(2)
    time.sleep(0.05)
    release.set()
    for thread in threads:
        thread.join(2)
    assert errors == [None, None, None]
    assert results == [source, source, source]
    assert len(calls) == 1


def test_analysis_reuses_isolation_and_keeps_cue_times(monkeypatch):
    monkeypatch.setattr(vocals, "isolation_capability", lambda: {"available": True, "reason": "ready"})
    monkeypatch.setattr(speech, "rhubarb_executable", lambda: "/configured/rhubarb")
    isolations, analyses = [], []

    def run(args, **_kwargs):
        if "-o" in args:
            analyses.append(args)
            Path(args[args.index("-o") + 1]).write_text(
                json.dumps({"mouthCues": [{"start": 0, "end": 1, "value": "D"}]}))
            return SimpleNamespace(returncode=0)
        isolations.append(args)
        Path(args[3]).write_bytes(Path(args[2]).read_bytes())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    source = wav(1)
    first = speech.analyze_voice(source, isolate_vocals=True)
    second = speech.analyze_voice(source, isolate_vocals=True)
    third = speech.analyze_voice(source, isolate_vocals=True)
    assert first == second == third
    assert first["mouthCues"][0] == {"start": 0, "end": 1, "value": "D"}
    assert first["duration"] == 1
    assert first["analysisSource"] == "isolated-vocals"
    assert len(isolations) == 1
    assert len(analyses) == 1


def test_different_audio_model_or_params_miss_cache(monkeypatch):
    monkeypatch.setattr(vocals, "isolation_capability", lambda: {"available": True, "reason": "ready"})
    calls = []
    monkeypatch.setattr(vocals.subprocess, "run", _copy_worker(calls))
    vocals.isolate_voice(wav(1))
    vocals.isolate_voice(wav(2))
    monkeypatch.setattr(vocals, "MODEL_NAME", "other-roformer")
    vocals.isolate_voice(wav(1))
    monkeypatch.setattr(vocals, "ISOLATION_PARAMS", {**vocals.ISOLATION_PARAMS, "overlap": 4})
    vocals.isolate_voice(wav(1))
    assert len(calls) == 4


def test_distinct_windows_are_not_concatenated(monkeypatch):
    monkeypatch.setattr(vocals, "isolation_capability", lambda: {"available": True, "reason": "ready"})
    calls = []
    monkeypatch.setattr(vocals.subprocess, "run", _copy_worker(calls))
    vocals.isolate_voice(wav(1))
    vocals.isolate_voice(wav(2))
    merged = isolation_material(wav(3), 3.0, vocals.isolation_key_material())
    key = material_key(merged)
    root = Path(os.environ["SPEECH_ANALYSIS_CACHE_DIR"])
    assert not (root / key[:2] / f"{key}.wav").exists()
    assert len(calls) == 2


def test_failure_does_not_publish_a_partial_entry(monkeypatch, tmp_path):
    monkeypatch.setattr(vocals, "isolation_capability", lambda: {"available": True, "reason": "ready"})

    def run(args, **kwargs):
        Path(args[3]).write_bytes(b"partial")
        raise subprocess.TimeoutExpired(args, 900)

    monkeypatch.setattr(vocals.subprocess, "run", run)
    with pytest.raises(SpeechAnalysisUnavailable, match="15 minutes"):
        vocals.isolate_voice(wav())
    root = Path(os.environ["SPEECH_ANALYSIS_CACHE_DIR"])
    assert list(root.rglob("*.wav")) == []
    assert list(root.rglob("*.tmp")) == []
    assert remember({"k": "direct"}, lambda: b"ok", ".bin", root=tmp_path / "direct") == b"ok"


def test_failed_replace_does_not_leave_an_entry(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("disk")
    monkeypatch.setattr(os, "replace", boom)
    material = {"kind": "isolation", "n": 1}
    assert remember(material, lambda: b"payload", ".bin", root=tmp_path) == b"payload"
    key = material_key(material)
    assert not (tmp_path / key[:2] / f"{key}.bin").exists()
    assert list(tmp_path.rglob("*.tmp")) == []


def test_abandoned_waiter_does_not_drop_shared_result(tmp_path):
    started = threading.Event()
    release = threading.Event()
    material = {"kind": "shared", "n": 1}

    def compute():
        started.set()
        assert release.wait(2)
        return b"shared"

    first, second = [], []

    def client(bucket):
        bucket.append(remember(material, compute, ".bin", root=tmp_path))

    dropped = threading.Thread(target=lambda: client(first), daemon=True)
    kept = threading.Thread(target=lambda: client(second))
    dropped.start()
    assert started.wait(2)
    kept.start()
    time.sleep(0.05)
    release.set()
    kept.join(2)
    assert second == [b"shared"]
    key = material_key(material)
    assert (tmp_path / key[:2] / f"{key}.bin").read_bytes() == b"shared"


def test_eviction_skips_a_result_another_consumer_still_needs(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEECH_ANALYSIS_CACHE_MAX_ENTRIES", "1")
    remember({"k": "old"}, lambda: b"old", ".bin", root=tmp_path)
    hold, inside = threading.Event(), threading.Event()

    def compute():
        inside.set()
        assert hold.wait(2)
        return b"live"

    live = []
    thread = threading.Thread(target=lambda: live.append(remember({"k": "live"}, compute, ".bin", root=tmp_path)))
    thread.start()
    assert inside.wait(2)
    remember({"k": "new"}, lambda: b"new", ".bin", root=tmp_path)
    hold.set()
    thread.join(2)
    assert live == [b"live"]
    live_key = material_key({"k": "live"})
    assert (tmp_path / live_key[:2] / f"{live_key}.bin").read_bytes() == b"live"


def test_missing_optional_model_gives_a_reason_without_download(monkeypatch, tmp_path):
    monkeypatch.setattr(vocals, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(vocals.subprocess, "run", lambda *a, **k: pytest.fail("Must not start inference or download"))
    capability = vocals.isolation_capability()
    assert capability["available"] is False
    assert capability["downloads"] is False
    assert capability["reason"] == "optional_model_missing"
    with pytest.raises(SpeechAnalysisUnavailable, match="already be installed"):
        vocals.isolate_voice(wav())
    assert list(Path(os.environ["SPEECH_ANALYSIS_CACHE_DIR"]).rglob("*")) == []


def test_ninety_second_cap_is_unchanged():
    with pytest.raises(SpeechAnalysisError, match="90 seconds"):
        vocals.isolate_voice(wav(91))
    with pytest.raises(SpeechAnalysisError, match="90 seconds"):
        speech.analyze_voice(wav(91))


def test_analysis_key_includes_segment_and_isolation_model():
    model = vocals.isolation_key_material()
    original = analysis_material(wav(1), 1.0, True, "/rhubarb", {"recognizer": "phonetic"}, model)
    shifted = analysis_material(wav(2), 2.0, True, "/rhubarb", {"recognizer": "phonetic"}, model)
    plain = analysis_material(wav(1), 1.0, False, "/rhubarb", {"recognizer": "phonetic"})
    other_model = analysis_material(wav(1), 1.0, True, "/rhubarb", {"recognizer": "phonetic"}, {**model, "model": "other"})
    assert original["segment"]["start"] == 0.0
    assert material_key(original) != material_key(shifted)
    assert material_key(original) != material_key(plain)
    assert material_key(original) != material_key(other_model)
