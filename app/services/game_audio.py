"""CPU helpers for game loops, jingles, and loudness.

Loop points are sample indices. ``best_loop`` chooses a downbeat pair whose
length is a multiple of four bars, then scores the crossfade windows. Its end
is exclusive like a slice, so a loop of the whole buffer is ``(0, len)``. The
WAV ``smpl`` chunk stores an inclusive end, so the same loop is ``0 .. len-1``
there.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import warnings
from pathlib import Path

import numpy as np
import soundfile as sf

from services.audio_levels import integrated_lufs

# Deterministic files: no random Ogg serial numbers or versioned encoder tags.
_BITEXACT = ["-fflags", "+bitexact", "-flags:a", "+bitexact"]
# ``latency=1`` compensates the lookahead, so samples keep their positions.
_LIMITER = "alimiter=limit=0.95:level=disabled:latency=1"


def to_mono(y):
    """Average channels. A 1-d array stays 1-d."""
    audio = np.asarray(y, dtype=np.float64)
    if audio.ndim == 1:
        return audio
    if audio.ndim != 2:
        raise ValueError("audio must be mono or shaped (frames, channels)")
    return np.mean(audio, axis=1)


def trim_silence(y, sr, threshold_db=-50, keep_ms=10):
    """Drop leading and trailing samples below ``threshold_db``, keeping ``keep_ms``."""
    audio = np.asarray(y, dtype=np.float64)
    mono = to_mono(audio)
    if mono.size == 0:
        return audio.copy()
    threshold = 10.0 ** (float(threshold_db) / 20.0)
    loud = np.flatnonzero(np.abs(mono) >= threshold)
    if loud.size == 0:
        return audio[:0].copy()
    keep = max(0, int(round(float(keep_ms) * int(sr) / 1000.0)))
    start = max(0, int(loud[0]) - keep)
    end = min(int(mono.size), int(loud[-1]) + 1 + keep)
    return audio[start:end].copy()


def _fade_width(n: int, sr: int, ms: float) -> int:
    if ms <= 0 or n <= 0 or sr <= 0:
        return 0
    return min(n, int(round(float(ms) * int(sr) / 1000.0)))


def _ramp(n: int, sr: int, ms: float, *, out: bool) -> np.ndarray:
    width = _fade_width(n, sr, ms)
    if width <= 0:
        return np.ones(0, dtype=np.float64)
    if out:
        return np.linspace(1.0, 0.0, width, endpoint=True)
    return np.linspace(0.0, 1.0, width, endpoint=False)


def _scale(audio: np.ndarray, ramp: np.ndarray, *, at_start: bool) -> None:
    if ramp.size == 0:
        return
    view = (int(ramp.size),) + (1,) * (audio.ndim - 1)
    shaped = ramp.reshape(view)
    if at_start:
        audio[: ramp.size] *= shaped
        return
    audio[-ramp.size :] *= shaped


def fades(y, sr, in_ms=5, out_ms=15):
    """Linear fade in and out. Returns the same rank as ``y``."""
    audio = np.asarray(y, dtype=np.float64).copy()
    n = int(audio.shape[0])
    _scale(audio, _ramp(n, int(sr), in_ms, out=False), at_start=True)
    _scale(audio, _ramp(n, int(sr), out_ms, out=True), at_start=False)
    return audio


def peak_normalize(y, peak_db=-1.0):
    """Scale so the peak is ``peak_db`` dBFS. Silence stays silence."""
    audio = np.asarray(y, dtype=np.float64)
    if audio.size == 0:
        return audio.copy()
    peak = float(np.max(np.abs(audio)))
    if peak <= 0.0:
        return audio.copy()
    target = 10.0 ** (float(peak_db) / 20.0)
    return audio * (target / peak)


def lufs_normalize(path, target):
    """Rewrite ``path`` to ``target`` LUFS via ffmpeg. Returns the gain in dB.

    Like ``audio_levels.level_file`` (0.5 dB tolerance, gain held to +-20 dB,
    peaks limited to 0.95), but the limiter does not shift the audio, a WAV
    ``smpl`` loop chunk is copied onto the new file, and an Ogg keeps its
    ``LOOPSTART``/``LOOPLENGTH`` comments, so loop points stay valid.
    """
    measured = integrated_lufs(str(path))
    if measured is None or abs(float(target) - measured) <= 0.5:
        return 0.0
    gain = max(-20.0, min(20.0, float(target) - measured))
    smpl = _riff_chunk(path, b"smpl")
    if not _apply_gain(path, gain):
        return 0.0
    if smpl is not None:
        _append_chunk(path, smpl)
    return round(gain, 2)


def _positive_mean(values) -> float | None:
    array = np.asarray(list(values), dtype=np.float64)
    if array.size < 2:
        return None
    gaps = np.diff(array)
    gaps = gaps[gaps > 0]
    if gaps.size == 0:
        return None
    return float(np.mean(gaps))


def _mean_bar(beats, downbeats) -> float:
    """Mean downbeat gap, or four mean beats when downbeats are missing."""
    down = _positive_mean(downbeats)
    if down is not None:
        return down
    beat = _positive_mean(beats)
    if beat is None:
        return 0.0
    return beat * 4.0


def _downbeats(downbeats) -> list[int]:
    return sorted({int(item) for item in downbeats})


def _four_bar_gap(bars: float) -> tuple[int, float]:
    """Nearest multiple of four bars, and how far ``bars`` is from it."""
    if bars <= 0.0:
        return 0, 999.0
    lower = int(bars // 4.0) * 4
    if lower < 4:
        return 4, abs(bars - 4.0)
    upper = lower + 4
    if abs(bars - lower) <= abs(bars - upper):
        return lower, abs(bars - lower)
    return upper, abs(bars - upper)


def _chroma(y: np.ndarray, sr: int, hop: int, librosa):
    try:
        return librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)
    except Exception:
        # chroma_cqt rejects some buffers; chroma_stft still scores the seam.
        return librosa.feature.chroma_stft(y=y, sr=sr, hop_length=hop)


def _features(y: np.ndarray, sr: int, librosa):
    hop = 2048
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        chroma = _chroma(y, sr, hop, librosa)
        mfcc = librosa.feature.mfcc(y=y, sr=sr, hop_length=hop, n_mfcc=13)
    return np.asarray(chroma), np.asarray(mfcc), hop


def _frames(feature: np.ndarray, hop: int, start: int, end: int) -> np.ndarray:
    last = int(feature.shape[1])
    if last <= 0:
        return feature[:, :0]
    first = min(last - 1, max(0, int(start) // hop))
    final = min(last, max(first + 1, int(end) // hop))
    return feature[:, first:final]


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    width = min(int(left.shape[1]), int(right.shape[1])) if left.ndim == 2 and right.ndim == 2 else 0
    if width <= 0:
        return 0.0
    first = left[:, :width].ravel()
    second = right[:, :width].ravel()
    denom = float(np.linalg.norm(first) * np.linalg.norm(second))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(first, second) / denom)


def _seam_score(chroma, mfcc, hop, start: int, end: int, xf: int) -> float:
    left = start - xf
    chroma_score = _cosine(_frames(chroma, hop, left, start), _frames(chroma, hop, end - xf, end))
    mfcc_score = _cosine(_frames(mfcc, hop, left, start), _frames(mfcc, hop, end - xf, end))
    score = 0.5 * (chroma_score + mfcc_score)
    if score != score:  # NaN
        return -1.0
    return float(max(-1.0, min(1.0, score)))


def _pair_score(start, end, mean_bar, sr, target_s, chroma, mfcc, hop, xf):
    bars = (end - start) / mean_bar
    multiple, gap = _four_bar_gap(bars)
    score = _seam_score(chroma, mfcc, hop, start, end, xf)
    distance = abs((end - start) / float(sr) - float(target_s))
    return (int(start), int(end), score, distance, gap, multiple)


def _near_target(qualified: list, tolerance_s: float) -> list:
    nearest = min(item[3] for item in qualified)
    return [item for item in qualified if item[3] <= nearest + tolerance_s]


def _closest_bars(scored: list) -> list:
    if not scored:
        return []
    nearest = min(item[4] for item in scored)
    return [item for item in scored if item[4] <= nearest + 1e-6]


def _choose_pair(scored: list, tolerance_s: float):
    """Best seam among four-bar pairs within ``tolerance_s`` of the closest length."""
    qualified = [item for item in scored if item[5] >= 4 and item[4] <= 0.35]
    pool = _near_target(qualified, tolerance_s) if qualified else _closest_bars(scored)
    if not pool:
        return None
    pool.sort(key=lambda item: (-item[2], item[3], item[0]))
    return pool[0]


def _select_loop(downs, n, mean_bar, xf, sr, target_s, chroma, mfcc, hop):
    scored = []
    for index, start in enumerate(downs):
        if start < xf or start >= n:
            continue
        for end in downs[index + 1 :]:
            if end > n or end - start < xf:
                continue
            scored.append(_pair_score(start, end, mean_bar, sr, target_s, chroma, mfcc, hop, xf))
    # Beat trackers jitter downbeats, so lengths within a bar (or 5% of the
    # target) of the closest one count as equally close and the seam decides.
    chosen = _choose_pair(scored, max(mean_bar / sr, 0.05 * target_s))
    if chosen is None:
        return 0, n, 0.0, 0
    return int(chosen[0]), int(chosen[1]), float(chosen[2]), xf


def best_loop(y, sr, beats, downbeats, target_s, xf_bars=1):
    """Return ``(start, end, score, xf)`` for the best downbeat loop near ``target_s``.

    ``beats`` and ``downbeats`` are sample indices. ``end`` is exclusive, so the
    loop is ``y[start:end]`` and its length is ``end - start``. ``xf`` is the
    crossfade in samples (``xf_bars`` mean bars) to pass to ``render_loop``;
    ``start`` keeps at least ``xf`` samples before it so the window exists. The
    score is the average cosine similarity of chroma and MFCCs on
    ``[start-xf, start]`` and ``[end-xf, end]``. Pairs within 0.35 bars of a
    multiple of four bars compete on that score when their length is within
    one bar or 5% of ``target_s`` (the larger) of the closest length. When no
    pair is that close to four bars, the closest four-bar pair that can still
    be scored is returned.
    Without usable downbeats or pairs the whole buffer comes back as
    ``(0, len, 0.0, 0)``: there is no audio outside it to crossfade with.
    """
    mono = to_mono(np.asarray(y, dtype=np.float64))
    mean_bar = _mean_bar(beats, downbeats)
    downs = _downbeats(downbeats)
    if mean_bar <= 1.0 or len(downs) < 2 or mono.size < 2:
        return 0, int(mono.size), 0.0, 0
    import librosa  # only the seam score needs it; the fallback above works without

    xf = max(1, int(round(float(xf_bars) * mean_bar)))
    chroma, mfcc, hop = _features(mono, int(sr), librosa)
    return _select_loop(
        downs, int(mono.size), mean_bar, xf, int(sr), float(target_s), chroma, mfcc, hop,
    )


def _crossfade(outgoing, incoming, ramp):
    if outgoing.ndim > 1:
        ramp = ramp.reshape((ramp.shape[0],) + (1,) * (outgoing.ndim - 1))
    return (1.0 - ramp) * outgoing + ramp * incoming


def render_loop(y, sr, a, b, xf):
    """Return ``y[a:b]`` with a linear crossfade of ``xf`` samples at the seam.

    ``t`` runs from 0 to 1: ``(1 - t) * outgoing + t * incoming``. Linear, not
    equal power: ``best_loop`` picks correlated windows, where equal power adds
    up to 3 dB and clips. When ``a >= xf`` the last ``xf`` samples fade from
    ``y[b-xf:b]`` into the pre-roll ``y[a-xf:a]``, so the wrap lands on ``y[a]``.
    When ``a < xf`` (``a == 0`` included) the first ``xf`` samples fade from the
    post-roll ``y[b:b+xf]`` into ``y[a:a+xf]``, so the wrap from ``y[b-1]`` lands
    on ``y[b]``. With neither window (a whole-buffer loop) the cut is returned
    unfaded. ``sr`` is part of the call so it matches ``best_loop``; the fade is
    in samples.
    """
    if int(sr) <= 0:
        raise ValueError("sample rate must be positive")
    audio = np.asarray(y, dtype=np.float64)
    start = max(0, int(a))
    end = min(int(audio.shape[0]), max(start, int(b)))
    segment = audio[start:end].copy()
    width = int(xf)
    if width <= 0 or segment.shape[0] < width:
        return segment
    ramp = np.linspace(0.0, 1.0, width, endpoint=True)
    if start >= width:
        segment[-width:] = _crossfade(audio[end - width : end], audio[start - width : start], ramp)
    elif end + width <= int(audio.shape[0]):
        segment[:width] = _crossfade(audio[end : end + width], audio[start : start + width], ramp)
    return segment


def _rms_difference_db(head: np.ndarray, tail: np.ndarray) -> float:
    start = float(np.sqrt(np.mean(np.square(head))))
    end = float(np.sqrt(np.mean(np.square(tail))))
    if start <= 1e-12 and end <= 1e-12:
        return 0.0
    if start <= 1e-12:
        return 120.0
    return float(20.0 * np.log10(max(end, 1e-12) / start))


def seam_metrics(loop, sr: int = 44100) -> dict[str, float]:
    """Sample jump at the wrap, and RMS change from the first 50 ms to the last 50 ms.

    ``rms_db`` is negative when the end is quieter than the start.
    """
    mono = to_mono(np.asarray(loop, dtype=np.float64))
    if mono.size == 0:
        return {"sample_jump": 0.0, "rms_db": 0.0}
    window = max(1, int(round(0.050 * max(1, int(sr)))))
    window = min(window, int(mono.size))
    return {
        "sample_jump": abs(float(mono[-1] - mono[0])),
        "rms_db": _rms_difference_db(mono[:window], mono[-window:]),
    }


def _u32(value: int) -> int:
    return max(0, int(value)) & 0xFFFFFFFF


def _smpl_chunk(sr: int, loop_start: int, loop_end: int) -> bytes:
    # WAV loop end is inclusive: a full-buffer loop is 0 .. len-1.
    period = int(round(1_000_000_000 / sr)) if sr > 0 else 0
    payload = struct.pack("<9I", 0, 0, period, 60, 0, 0, 0, 1, 0)
    payload += struct.pack("<6I", 0, 0, _u32(loop_start), _u32(loop_end), 0, 0)
    return b"smpl" + struct.pack("<I", len(payload)) + payload


def _riff_chunk(path, ident: bytes) -> bytes | None:
    """The first ``ident`` chunk of a WAV, header included; ``None`` if absent."""
    blob = Path(path).read_bytes()
    if blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        return None
    pos = 12
    while pos + 8 <= len(blob):
        size = struct.unpack_from("<I", blob, pos + 4)[0]
        if blob[pos : pos + 4] == ident:
            return blob[pos : pos + 8 + size]
        pos += 8 + size + (size & 1)
    return None


def _append_chunk(path, chunk: bytes) -> None:
    blob = Path(path).read_bytes()
    if blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise ValueError("expected a RIFF WAVE file")
    if len(blob) & 1:
        blob += b"\0"  # RIFF chunks start on an even offset.
    blob = blob + chunk
    size = struct.pack("<I", len(blob) - 8)
    Path(path).write_bytes(blob[:4] + size + blob[8:])


def write_wav_loop(path, y, sr, loop_start, loop_end) -> None:
    """Write a WAV and append a RIFF ``smpl`` loop from ``loop_start`` to ``loop_end``."""
    sf.write(path, np.asarray(y, dtype=np.float32), int(sr), subtype="PCM_16")
    _append_chunk(path, _smpl_chunk(int(sr), int(loop_start), int(loop_end)))


def _remove(path: Path) -> None:
    if path.is_file():
        path.unlink()


def _run_ffmpeg(command: list[str], output: Path) -> bool:
    """Run ``command``; remove a partial ``output`` when it fails."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.SubprocessError):
        _remove(output)
        return False
    if result.returncode != 0 or not output.is_file():
        _remove(output)
        return False
    return True


def _apply_gain(path, gain_db: float) -> bool:
    source = Path(path)
    temporary = source.with_name(source.stem + ".level" + source.suffix)
    codec = ["-c:a", "libvorbis"] if source.suffix.lower() == ".ogg" else []
    command = [
        "ffmpeg", "-v", "error", "-y", "-i", str(source),
        "-af", f"volume={gain_db:.2f}dB,{_LIMITER}", *codec, *_BITEXACT, str(temporary),
    ]
    if not _run_ffmpeg(command, temporary):
        return False
    os.replace(temporary, source)
    return True


def _encode_vorbis(path, audio: np.ndarray, sr: int, loop_start: int, loop_length: int) -> bool:
    """Encode once with libvorbis, writing the loop comments as it encodes.

    Tagging libsndfile's Vorbis output with ``-c copy`` changed the decoded
    length for some sizes (88200 frames came back 128 short), so ffmpeg encodes
    from a float WAV instead.
    """
    destination = Path(path)
    source = destination.with_name(destination.stem + ".loop-source.wav")
    # The .ogg suffix makes ffmpeg pick the Ogg muxer, which writes the comments.
    temporary = destination.with_name(destination.stem + ".loop-tag.ogg")
    try:
        sf.write(source, audio, int(sr), subtype="FLOAT")
    except (RuntimeError, OSError, ValueError):
        _remove(source)
        return False
    command = [
        "ffmpeg", "-v", "error", "-y", "-i", str(source), "-c:a", "libvorbis",
        "-metadata", f"LOOPSTART={int(loop_start)}",
        "-metadata", f"LOOPLENGTH={int(loop_length)}",
        *_BITEXACT, str(temporary),
    ]
    encoded = _run_ffmpeg(command, temporary)
    _remove(source)
    if encoded:
        os.replace(temporary, destination)
    return encoded


def _fallback_wav(path, audio: np.ndarray, sr: int, loop_start: int, loop_length: int, warning: str) -> str:
    destination = Path(path)
    if destination.suffix.lower() == ".ogg":
        _remove(destination)
    loop_end = max(int(loop_start), int(loop_start) + int(loop_length) - 1)
    write_wav_loop(destination.with_suffix(".wav"), audio, int(sr), int(loop_start), loop_end)
    return warning


def write_ogg_loop(path, y, sr, loop_start, loop_length):
    """Write an Ogg Vorbis loop, or a WAV with a ``smpl`` loop if ffmpeg cannot encode it.

    Returns ``None`` when the Ogg file carries ``LOOPSTART`` and ``LOOPLENGTH``.
    Returns a warning string when the WAV fallback was written instead.
    """
    audio = np.asarray(y, dtype=np.float32)
    if shutil.which("ffmpeg") is None:
        warning = "ffmpeg unavailable; wrote WAV instead"
    elif not _encode_vorbis(path, audio, int(sr), int(loop_start), int(loop_length)):
        warning = "ffmpeg could not encode the Ogg Vorbis loop; wrote WAV instead"
    else:
        return None
    return _fallback_wav(path, audio, int(sr), int(loop_start), int(loop_length), warning)


def _nearest_cut(downbeats, target: int, limit: int) -> int:
    # A downbeat at 0 would cut an empty jingle.
    points = [int(item) for item in downbeats if 0 < int(item) <= limit]
    if not points:
        return max(0, min(int(target), int(limit)))
    return min(points, key=lambda point: (abs(point - target), point))


def cut_jingle(y, sr, seconds, downbeats, fade_ms=300):
    """Cut on the downbeat nearest ``seconds`` and fade out over ``fade_ms``."""
    audio = np.asarray(y, dtype=np.float64)
    if int(sr) <= 0:
        raise ValueError("sample rate must be positive")
    target = int(round(float(seconds) * int(sr)))
    cut = _nearest_cut(downbeats, target, int(audio.shape[0]))
    clipped = audio[:cut].copy()
    if fade_ms <= 0 or clipped.shape[0] == 0:
        return clipped
    return fades(clipped, int(sr), in_ms=0, out_ms=fade_ms)
