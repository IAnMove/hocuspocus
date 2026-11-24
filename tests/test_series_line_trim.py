"""The silence trim of a spoken line follows the take's own level, so a quiet voice keeps its last syllable."""
from __future__ import annotations

import shutil
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from services.series_native_render import (
    silence_threshold_db,
    trim_silence,
)

RATE = 44100


def test_threshold_follows_the_peak_inside_its_limits():
    assert silence_threshold_db(None) == -42.0  # unreadable peak: the value it always had
    assert silence_threshold_db(-1.0) == -42.0  # a full-scale voice is trimmed as before
    assert silence_threshold_db(-16.0) == -56.0  # a quiet voice: its tail is 40 dB under its own peak
    assert silence_threshold_db(-45.0) == -70.0  # never under a real noise floor


def _write(path: Path, samples: np.ndarray) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())


def _take(gain_db: float) -> np.ndarray:
    """0.5 s silence, 1 s of voice, a 0.4 s last syllable 30 dB quieter, 0.5 s silence."""
    tone = lambda seconds, db: 10 ** (db / 20) * np.sin(2 * np.pi * 220 * np.arange(int(RATE * seconds)) / RATE)
    quiet = np.zeros(RATE // 2)
    return np.concatenate([quiet, tone(1.0, gain_db), tone(0.4, gain_db - 30), quiet])


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg")
@pytest.mark.parametrize("gain_db", [-3.0, -16.0])
def test_quiet_take_keeps_its_soft_last_syllable(tmp_path, gain_db):
    # At -16 dBFS the last syllable sits at -46: under the fixed -42 dBFS it used to be cut with the silence.
    raw, out = tmp_path / "raw.wav", tmp_path / "line.wav"
    _write(raw, _take(gain_db))
    duration = trim_silence(str(raw), str(out))
    assert 1.4 <= duration <= 1.75  # voice and last syllable stay, the silence around them goes
