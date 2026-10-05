"""Shorten the long pauses of a cloned voice's reference before the model hears it.

Qwen3 Base clones a voice by continuing its reference recording. When that
recording waits a long time between sentences, a short target line (two to
four words) often comes back as silence or a single click. Shortening every
pause to about a quarter of a second, and the silence at either end to the
same length, keeps the voice and every spoken word, so the reference
transcript stays valid and the line is spoken.

The shortened copy is a cache entry keyed by the source's bytes and these
settings; the user's file is never changed. A reference without long pauses
is used as it is, and any ffmpeg or analysis failure uses the original file.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Any, Callable

SCHEMA = 1
# The longest silence the model hears: inside the speech and at either end.
MAX_PAUSE_SECONDS = 0.25
# Pauses up to this much longer than the maximum are left alone (no needless copy).
TOLERANCE_SECONDS = 0.05
# Silence is never louder than this, and always this far under the recording's peak,
# so a quiet recording does not lose its quiet speech.
SILENCE_DB = -35.0
BELOW_PEAK_DB = 30.0
# A peak under this is a recording without speech: there is nothing to shorten.
MIN_PEAK_DB = -60.0
# A result shorter than this means the analysis misread the recording.
MIN_RESULT_SECONDS = 1.0
# Silences that start or end within this distance of the file's edges are edge silences.
EDGE_SECONDS = 0.02
MAX_ENTRIES = 128
TIMEOUT_SECONDS = 120

# Native fields that hold a speaker's reference voice, per architecture.
CLONE_REFERENCE_FIELDS: dict[str, tuple[str, ...]] = {
    "qwen3_tts_base": ("audio_guide", "audio_guide2"),
}

_SETTINGS = {
    "schema": SCHEMA, "max_pause": MAX_PAUSE_SECONDS, "tolerance": TOLERANCE_SECONDS,
    "silence_db": SILENCE_DB, "below_peak_db": BELOW_PEAK_DB, "min_peak_db": MIN_PEAK_DB,
}
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_PEAK = re.compile(r"max_volume:\s*(-?(?:inf|[\d.]+))\s*dB")
_SILENCE = re.compile(r"silence_(start|end):\s*(-?[\d.]+(?:e-?\d+)?)")

_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def cache_dir() -> Path:
    override = os.environ.get("VOICE_REFERENCE_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "cache" / "voice-references"


def ffmpeg_binary() -> str | None:
    return os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")


def tighten_clone_references(params: dict[str, Any], *,
                             base_model_type: Callable[[str], str | None] | None = None) -> dict[str, Any]:
    """Point each cloned-voice reference in ``params`` at its shortened copy, in place."""
    model = params.get("model_type")
    try:
        architecture = base_model_type(model) if base_model_type else model
    except Exception:
        architecture = model
    for field in CLONE_REFERENCE_FIELDS.get(architecture or "", ()):
        source = params.get(field)
        if isinstance(source, str) and source:
            params[field] = tightened_reference(source)
    return params


def tightened_reference(source: str) -> str:
    """The reference the model should hear: a cached shortened copy, or ``source`` itself."""
    try:
        key = cache_key(source)
    except OSError:
        return source
    folder = cache_dir()
    derived, keep = folder / f"{key}.wav", folder / f"{key}.keep"
    with _lock_for(key):
        if _fresh(derived):
            return str(derived)
        if _fresh(keep):
            return source
        try:
            return _build(source, folder, derived, keep)
        except Exception as error:  # fail open: the original reference still clones the voice
            print(f"[Voice reference] Using {os.path.basename(source)} as is: {error}")
            return source


def cache_key(source: str) -> str:
    digest = hashlib.sha256()
    with open(source, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    material = {**_SETTINGS, "audio": digest.hexdigest()}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("ascii")).hexdigest()


def silence_threshold(peak_db: float) -> float | None:
    """Level under which audio counts as silence, or None when the recording has no speech."""
    if not peak_db > MIN_PEAK_DB:
        return None
    return min(SILENCE_DB, peak_db - BELOW_PEAK_DB)


def plan_keep(silences: list[tuple[float, float | None]], duration: float) -> list[tuple[float, float | None]] | None:
    """Spans of the source to keep (``None`` end: to the end of the file), or None to keep it whole.

    Each silence longer than the maximum pause (plus tolerance) is shortened to
    that pause: half kept after the speech before it and half before the speech
    after it; at the start only its last part, at the end only its first part.
    """
    cuts = []
    for start, end in silences:
        start, end = max(0.0, start), duration if end is None else min(end, duration)
        if round(end - start, 6) <= MAX_PAUSE_SECONDS + TOLERANCE_SECONDS:
            continue
        if start <= EDGE_SECONDS:
            cuts.append((0.0, end - MAX_PAUSE_SECONDS))
        elif end >= duration - EDGE_SECONDS:
            cuts.append((start + MAX_PAUSE_SECONDS, duration))
        else:
            cuts.append((start + MAX_PAUSE_SECONDS / 2, end - MAX_PAUSE_SECONDS / 2))
    if not cuts:
        return None
    keep: list[tuple[float, float | None]] = []
    cursor = 0.0
    for start, end in sorted(cuts):
        if start > cursor:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration - EDGE_SECONDS:
        keep.append((cursor, None))
    kept = sum((duration if end is None else end) - start for start, end in keep)
    return keep if kept >= MIN_RESULT_SECONDS else None


def parse_duration(log: str) -> float | None:
    match = _DURATION.search(log)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_peak(log: str) -> float | None:
    match = _PEAK.search(log)
    return float(match.group(1)) if match else None


def parse_silences(log: str) -> list[tuple[float, float | None]]:
    """silencedetect's runs; a run still open at the end of the file has no end."""
    silences: list[tuple[float, float | None]] = []
    start = None
    for kind, value in _SILENCE.findall(log):
        if kind == "start":
            start = float(value)
        elif start is not None:
            silences.append((start, float(value)))
            start = None
    if start is not None:
        silences.append((start, None))
    return silences


def keep_filter(keep: list[tuple[float, float | None]]) -> str:
    """An ffmpeg graph that joins the kept spans sample-accurately."""
    count = len(keep)
    parts = [f"[0:a]asplit={count}" + "".join(f"[s{index}]" for index in range(count))]
    for index, (start, end) in enumerate(keep):
        span = f"start={start:.6f}" + ("" if end is None else f":end={end:.6f}")
        parts.append(f"[s{index}]atrim={span},asetpts=PTS-STARTPTS[k{index}]")
    parts.append("".join(f"[k{index}]" for index in range(count)) + f"concat=n={count}:v=0:a=1[out]")
    return ";".join(parts)


def _build(source: str, folder: Path, derived: Path, keep_marker: Path) -> str:
    ffmpeg = ffmpeg_binary()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed")
    level = _ffmpeg_log(ffmpeg, source, "volumedetect")
    duration, peak = parse_duration(level), parse_peak(level)
    if duration is None or peak is None:
        raise RuntimeError("ffmpeg could not measure the recording")
    threshold = silence_threshold(peak)
    keep = None
    if threshold is not None:
        detected = _ffmpeg_log(ffmpeg, source, f"silencedetect=noise={threshold:.1f}dB:d={MAX_PAUSE_SECONDS}")
        keep = plan_keep(parse_silences(detected), duration)
    folder.mkdir(parents=True, exist_ok=True)
    if keep is None:
        _write_atomic(folder, keep_marker, lambda path: Path(path).write_text("original\n", encoding="utf-8"))
        _prune(folder)
        return source

    def render(path: str) -> None:
        subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-y", "-i", source, "-filter_complex", keep_filter(keep),
                        "-map", "[out]", "-c:a", "pcm_s16le", path],
                       check=True, capture_output=True, timeout=TIMEOUT_SECONDS)
        if os.path.getsize(path) <= 44:  # a WAV header without samples
            raise RuntimeError("ffmpeg wrote no audio")

    _write_atomic(folder, derived, render)
    _prune(folder)
    return str(derived)


def _ffmpeg_log(ffmpeg: str, source: str, audio_filter: str) -> str:
    result = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-nostats", "-i", source, "-af", audio_filter,
                             "-f", "null", "-"], capture_output=True, text=True, check=True, timeout=TIMEOUT_SECONDS)
    return result.stderr


def _write_atomic(folder: Path, target: Path, write: Callable[[str], None]) -> None:
    handle, temporary = tempfile.mkstemp(prefix=f".{target.stem}.", suffix=f".tmp{target.suffix}", dir=folder)
    os.close(handle)
    try:
        write(temporary)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _fresh(path: Path) -> bool:
    """True for a usable entry; marks it recently used so pruning keeps it."""
    try:
        if path.stat().st_size <= 0:
            return False
        os.utime(path)
    except OSError:
        return False
    return True


def _prune(folder: Path) -> None:
    entries = []
    for path in folder.glob("*"):
        if path.name.startswith(".") or path.suffix not in (".wav", ".keep"):
            continue
        try:
            entries.append((path.stat().st_mtime, path))
        except OSError:
            continue
    for _mtime, path in sorted(entries)[:-MAX_ENTRIES]:
        try:
            path.unlink()
        except OSError:
            pass


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


__all__ = ["CLONE_REFERENCE_FIELDS", "cache_dir", "plan_keep", "tighten_clone_references", "tightened_reference"]
