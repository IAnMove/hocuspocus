"""Loop cutting, WAV sampler loops, and loudness for game audio."""
from __future__ import annotations

import shutil
import struct
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from services.audio_levels import integrated_lufs
from services.game_audio import (
    best_loop,
    cut_jingle,
    fades,
    lufs_normalize,
    peak_normalize,
    render_loop,
    seam_metrics,
    to_mono,
    trim_silence,
    write_ogg_loop,
    write_wav_loop,
)


def _bar_chords(sr=22050, bars=8, bpm=120.0):
    """A steady bed plus a chord that changes every bar. Downbeats are sample indices."""
    bar_samples = int(round(4.0 * 60.0 / bpm * sr))
    total = bar_samples * bars
    t = np.arange(total, dtype=np.float64) / sr
    signal = 0.22 * np.sin(2.0 * np.pi * 90.0 * t)
    chords = (
        (262.0, 330.0, 392.0),
        (349.0, 440.0, 523.0),
        (196.0, 247.0, 294.0),
        (220.0, 277.0, 330.0),
    )
    fade = int(0.015 * sr)
    for bar in range(bars):
        start = bar * bar_samples
        end = start + bar_samples
        tone = sum(np.sin(2.0 * np.pi * freq * t[start:end]) for freq in chords[bar % 4])
        tone = np.asarray(tone, dtype=np.float64) * 0.04
        ramp = np.ones(tone.shape[0], dtype=np.float64)
        ramp[:fade] = np.linspace(0.0, 1.0, fade, endpoint=False)
        ramp[-fade:] = np.linspace(1.0, 0.0, fade, endpoint=True)
        signal[start:end] += tone * ramp
    downbeats = [bar * bar_samples for bar in range(bars + 1)]
    beat = bar_samples / 4.0
    beats = [int(round(index * beat)) for index in range(bars * 4 + 1)]
    return signal, sr, beats, downbeats


def test_trim_silence_drops_leading_silence():
    sr = 16000
    lead = int(0.5 * sr)
    tail = int(0.25 * sr)
    tone_n = sr
    tone = 0.25 * np.sin(2.0 * np.pi * 440.0 * np.arange(tone_n) / sr + np.pi / 2)
    y = np.concatenate([np.zeros(lead), tone, np.zeros(tail)])
    out = trim_silence(y, sr, threshold_db=-50, keep_ms=10)
    keep = int(round(10 * sr / 1000.0))
    assert abs((y.shape[0] - out.shape[0]) - (lead + tail - 2 * keep)) <= 2
    assert np.max(np.abs(out)) > 0.2
    stereo = trim_silence(np.column_stack([y, y * 0.5]), sr)
    assert stereo.ndim == 2 and stereo.shape[0] == out.shape[0]


def test_best_loop_picks_four_bar_spans_and_a_small_seam():
    pytest.importorskip("librosa")
    y, sr, beats, downbeats = _bar_chords()
    target_s = 8.0
    start, end, score = best_loop(y, sr, beats, downbeats, target_s, xf_beats=1)
    mean_bar = float(np.mean(np.diff(downbeats)))
    span = (end - start) / mean_bar
    multiple = int(round(span / 4.0)) * 4
    assert multiple >= 4 and abs(span - multiple) <= 0.35, (start, end, span, score)
    assert start >= int(mean_bar) - 1
    xf = max(1, int(round(mean_bar)))
    loop = render_loop(y, sr, start, end, xf)
    metrics = seam_metrics(loop, sr)
    assert metrics["sample_jump"] < 0.02
    assert abs(metrics["rms_db"]) < 1.5


def _smpl_loop_length(path: Path) -> int:
    blob = path.read_bytes()
    assert blob[:4] == b"RIFF" and blob[8:12] == b"WAVE"
    pos = 12
    body = None
    while pos + 8 <= len(blob):
        ident = blob[pos : pos + 4]
        size = struct.unpack_from("<I", blob, pos + 4)[0]
        payload = blob[pos + 8 : pos + 8 + size]
        if ident == b"smpl":
            body = payload
            break
        pos += 8 + size + (size & 1)
    assert body is not None and len(body) >= 52
    start, end = struct.unpack_from("<II", body, 44)
    return int(end - start)


def test_wav_smpl_records_loop_length(tmp_path):
    sr = 8000
    y = np.linspace(-0.2, 0.2, sr, dtype=np.float32)
    path = tmp_path / "loop.wav"
    write_wav_loop(path, y, sr, 100, 5000)
    assert _smpl_loop_length(path) == 5000 - 100
    write_wav_loop(path, y, sr, 0, len(y) - 1)
    assert _smpl_loop_length(path) == len(y) - 1


def test_lufs_normalize_targets_minus_sixteen(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg cannot measure")
    sr = 44100
    t = np.arange(int(sr * 2.5)) / sr
    tone = (0.05 * np.sin(2.0 * np.pi * 440.0 * t)).astype(np.float32)
    path = tmp_path / "tone.wav"
    sf.write(path, tone, sr)
    before = integrated_lufs(str(path))
    if before is None:
        pytest.skip("ffmpeg cannot measure")
    gain = lufs_normalize(str(path), -16.0)
    after = integrated_lufs(str(path))
    if after is None:
        pytest.skip("ffmpeg cannot measure")
    assert isinstance(gain, float)
    assert abs(after + 16.0) <= 1.0


def test_peak_fade_and_jingle():
    silent = peak_normalize(np.zeros(16))
    assert np.all(silent == 0.0)
    peaked = peak_normalize(np.array([0.0, 0.5, -1.0]), peak_db=-1.0)
    target = 10.0 ** (-1.0 / 20.0)
    assert abs(float(np.max(np.abs(peaked))) - target) < 1e-9
    faded = fades(np.ones(1000), 1000, in_ms=10, out_ms=20)
    assert faded[0] == 0.0 and abs(float(faded[-1])) < 1e-9
    assert to_mono(np.ones(8)).ndim == 1
    stereo = to_mono(np.column_stack([np.ones(8), np.full(8, 3.0)]))
    assert stereo.shape == (8,) and abs(float(stereo[0]) - 2.0) < 1e-9
    sr = 1000
    cut = cut_jingle(np.ones(2000), sr, 1.2, [0, 500, 1000, 1500], fade_ms=100)
    assert cut.shape[0] == 1000
    assert abs(float(cut[-1])) < 1e-9
    assert float(cut[0]) == 1.0


def test_ogg_loop_tags_or_falls_back_to_wav(tmp_path):
    sr = 8000
    y = (0.2 * np.sin(2.0 * np.pi * 440.0 * np.arange(sr) / sr)).astype(np.float32)
    path = tmp_path / "loop.ogg"
    warning = write_ogg_loop(path, y, sr, 0, len(y))
    if warning:
        assert (tmp_path / "loop.wav").is_file()
        assert "WAV" in warning
        return
    assert path.is_file()
    if shutil.which("ffprobe") is None:
        return
    import subprocess
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format_tags:stream_tags",
            "-of", "default=nw=1", str(path),
        ],
        capture_output=True, text=True, check=False, timeout=30,
    )
    tags = (result.stdout or "").upper()
    assert "LOOPSTART=0" in tags
    assert f"LOOPLENGTH={len(y)}" in tags
