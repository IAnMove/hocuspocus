"""Loop cutting, WAV sampler loops, and loudness for game audio."""
from __future__ import annotations

import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from services import game_audio
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
    start, end, score, xf = best_loop(y, sr, beats, downbeats, target_s, xf_bars=1)
    mean_bar = float(np.mean(np.diff(downbeats)))
    span = (end - start) / mean_bar
    multiple = int(round(span / 4.0)) * 4
    assert multiple >= 4 and abs(span - multiple) <= 0.35, (start, end, span, score)
    assert xf == round(mean_bar)
    assert start >= xf
    loop = render_loop(y, sr, start, end, xf)
    metrics = seam_metrics(loop, sr)
    assert metrics["sample_jump"] < 0.02
    assert abs(metrics["rms_db"]) < 1.5


def test_best_loop_lets_the_seam_decide_near_the_target():
    pytest.importorskip("librosa")
    y, sr, beats, downbeats = _bar_chords()
    bar = downbeats[1]
    jitter = round(0.2 * bar)
    # A late downbeat makes a pair whose length matches the target exactly but
    # whose seam lands a fifth of a bar into the next chord.
    downbeats = list(downbeats)
    downbeats[5] += jitter
    start, end, score, _xf = best_loop(y, sr, beats, downbeats, (4 * bar + jitter) / sr)
    assert end - start == 4 * bar, (start, end, score)
    assert start % bar == 0


def test_best_loop_fallback_end_is_exclusive():
    pytest.importorskip("librosa")
    y = np.linspace(-0.5, 0.5, 1000)
    assert best_loop(y, 1000, [], [], 0.5) == (0, len(y), 0.0, 0)


def test_render_loop_linear_crossfade_keeps_the_peak():
    sr = 8000
    y = 0.8 * np.sin(2.0 * np.pi * 100.0 * np.arange(sr) / sr)
    # 80-sample period: both windows hold the same audio, the case best_loop picks.
    loop = render_loop(y, sr, 800, 4800, 400)
    assert loop.shape[0] == 4000
    assert float(np.max(np.abs(loop))) <= float(np.max(np.abs(y))) + 1e-9
    stereo = render_loop(np.column_stack([y, y]), sr, 800, 4800, 400)
    assert np.allclose(stereo[:, 0], loop)


def test_render_loop_at_zero_fades_in_from_the_post_roll():
    sr = 1000
    y = np.arange(2000, dtype=np.float64)
    loop = render_loop(y, sr, 0, 1200, 100)
    assert loop.shape[0] == 1200
    assert loop[0] == y[1200]  # the wrap from y[1199] continues into y[1200]
    assert loop[99] == y[99]
    assert np.array_equal(loop[100:], y[100:1200])
    whole = render_loop(y, sr, 0, len(y), 100)
    assert np.array_equal(whole, y)


def _smpl_loop(path: Path) -> tuple[int, int]:
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
    return int(start), int(end)


def _smpl_loop_length(path: Path) -> int:
    start, end = _smpl_loop(path)
    return end - start


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


def test_lufs_normalize_keeps_loop_points_and_timing(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg cannot measure")
    sr = 44100
    t = np.arange(int(sr * 2.5)) / sr
    tone = 0.03 * np.sin(2.0 * np.pi * 440.0 * t)
    tone[2000] = 0.1
    path = tmp_path / "loop.wav"
    write_wav_loop(path, tone, sr, 100, 5000)
    gain = lufs_normalize(str(path), -16.0)
    if gain == 0.0:
        pytest.skip("ffmpeg cannot measure")
    out, rate = sf.read(path)
    assert rate == sr and out.shape[0] == tone.shape[0]
    assert int(np.argmax(np.abs(out))) == 2000
    assert _smpl_loop(path) == (100, 5000)


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


def test_cut_jingle_never_cuts_at_zero():
    cut = cut_jingle(np.ones(2000), 1000, 0.1, [0, 1000, 1500], fade_ms=100)
    assert cut.shape[0] == 1000


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


def _vorbis_tags(path: Path) -> dict[str, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format_tags:stream_tags",
            "-of", "default=nw=1", str(path),
        ],
        capture_output=True, text=True, check=False, timeout=30,
    )
    tags = {}
    for line in (result.stdout or "").splitlines():
        key, _sep, value = line.partition("=")
        if key.upper() in {"TAG:LOOPSTART", "TAG:LOOPLENGTH"}:
            tags[key.upper()[4:]] = int(value)
    return tags


def test_ogg_loop_keeps_the_exact_length(tmp_path):
    if shutil.which("ffprobe") is None:
        pytest.skip("ffprobe unavailable")
    sr = 44100
    y = (0.2 * np.sin(2.0 * np.pi * 440.0 * np.arange(88200) / sr)).astype(np.float32)
    path = tmp_path / "loop.ogg"
    if write_ogg_loop(path, y, sr, 0, len(y)):
        pytest.skip("ffmpeg cannot encode Vorbis")
    frames = sf.info(str(path)).frames
    assert frames == len(y)
    tags = _vorbis_tags(path)
    assert tags == {"LOOPSTART": 0, "LOOPLENGTH": len(y)}
    assert tags["LOOPSTART"] + tags["LOOPLENGTH"] <= frames
    first = path.read_bytes()
    write_ogg_loop(path, y, sr, 0, len(y))
    assert path.read_bytes() == first


def test_ogg_fallback_wav_keeps_the_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(game_audio.shutil, "which", lambda _name: None)
    sr = 8000
    y = np.linspace(-0.2, 0.2, sr, dtype=np.float32)
    warning = write_ogg_loop(tmp_path / "loop.ogg", y, sr, 100, 4000)
    assert warning and "WAV" in warning
    assert _smpl_loop(tmp_path / "loop.wav") == (100, 4099)
