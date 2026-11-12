"""Is a spoken take clean? Noise floor, signal-to-noise and rumble, measured without listening.

Voices made with Drama ``voicedesign`` come out with a noise floor around -47 to -55 dBFS, 26 to 36 dB
between speech and floor, and sometimes a rumble under 100 Hz ("speaking too close to the microphone").
A clone of a clean VoxCPM2 reference measures a floor near -93 dBFS and 76 dB. The pitch band gate
(``voice_band``) cannot see any of that, so this module measures it.

The numbers come from 50 ms RMS frames of the take:

* ``noiseFloorDb``: the 5th percentile of the frame levels (dBFS). The 10th percentile was tried first and
  called 23 % of clean voices dirty, because a short line has few pauses and its 10th percentile is a quiet
  phoneme; the 5th percentile sits in the pauses and the stable-floor test below covers the rest.
* ``snrDb``: the 90th percentile (speech) minus the floor.
* ``lowEndPct``: share of the energy under 100 Hz; ``bassPct``: the share between 40 and 100 Hz, where a
  hum or a forced-deep voice piles up. Only ``bassPct`` judges (a slow drift under 40 Hz cannot be heard).
* ``clippedPct``: share of samples at full scale. Reported, never judged (no real take clips).

The floor and the SNR are judged only when the clip can show a floor: at least 1.5 s, speech above
-55 dBFS, a stable bottom (10th percentile within 15 dB of the 2nd: at least a tenth of the frames are
pause) and at least 10 dB between the loud and the quiet frames (a flatter signal is a drone, or speech
at a constant level, not a floor). A short line or a line spoken without a pause has none; its verdict is
``inconclusive``, never ``unclean``. The bass check needs no pause.
Nothing here blocks a render: a take that cannot be read has no cleanliness at all.
"""
from __future__ import annotations

from typing import Any

import numpy as np

FRAME_SECONDS = 0.05
FLOOR_PERCENTILE, SPEECH_PERCENTILE = 5, 90
# Shortest clip that has a pause to measure a floor in, and shortest one worth a spectrum.
MIN_FLOOR_SECONDS, MIN_SPECTRUM_SECONDS = 1.5, 0.5
# Speech quieter than this is no speech to compare a floor against.
MIN_SPEECH_DB = -55.0
# A stable floor: the 10th percentile of the frames is not far above the 2nd (a flat pause, not a quiet phoneme).
MAX_FLOOR_SPREAD_DB = 15.0
# Speech always varies by more than this between its loud and its quiet frames; a flatter clip has no floor to find.
MIN_DYNAMIC_DB = 10.0
# The three limits: floor at or under, SNR at or over, bass share under.
MAX_FLOOR_DB, MIN_SNR_DB, MAX_BASS_PCT = -60.0, 45.0, 35.0
BASS_BAND_HZ, LOW_END_HZ = (40.0, 100.0), 100.0
CLIP_LEVEL = 0.985
REMEDY = ("Design the voice reference with VoxCPM2 and clone it with Drama drama3_base; "
          "do not use drama3_voicedesign for final lines.")


def _frame_levels(audio: np.ndarray, rate: int) -> np.ndarray:
    size = max(1, int(FRAME_SECONDS * rate))
    count = len(audio) // size
    if count < 4:
        return np.zeros(0)
    frames = audio[:count * size].reshape(count, size)
    return 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)


def _energy_shares(audio: np.ndarray, rate: int) -> tuple[float, float]:
    """``(under 100 Hz, 40 to 100 Hz)`` as shares of the whole energy, without the DC offset."""
    centered = audio - audio.mean()
    power = np.abs(np.fft.rfft(centered * np.hanning(len(centered)))) ** 2
    total = float(power.sum())
    if total <= 0:
        return 0.0, 0.0
    freqs = np.fft.rfftfreq(len(centered), d=1.0 / rate)
    low = float(power[freqs < LOW_END_HZ].sum() / total)
    bass = float(power[(freqs >= BASS_BAND_HZ[0]) & (freqs < BASS_BAND_HZ[1])].sum() / total)
    return low, bass


def _floor_numbers(audio: np.ndarray, rate: int) -> tuple[float, float, bool]:
    """``(floor dB, speech dB, conclusive)``: the floor can be judged only on a clip that shows one."""
    levels = _frame_levels(audio, rate)
    if not len(levels):
        return -120.0, -120.0, False
    floor, speech = (float(np.percentile(levels, q)) for q in (FLOOR_PERCENTILE, SPEECH_PERCENTILE))
    low, edge = (float(np.percentile(levels, q)) for q in (2, 10))
    stable = edge - low <= MAX_FLOOR_SPREAD_DB and speech - floor >= MIN_DYNAMIC_DB
    return max(floor, -120.0), speech, len(audio) / rate >= MIN_FLOOR_SECONDS and speech >= MIN_SPEECH_DB and stable


def _reasons(floor: float, snr: float, bass_pct: float, conclusive: bool, audible: bool) -> list[str]:
    found = []
    if conclusive and floor > MAX_FLOOR_DB:
        found.append("noise_floor")
    if conclusive and snr < MIN_SNR_DB:
        found.append("snr")
    if audible and bass_pct >= MAX_BASS_PCT:
        found.append("bass")
    return found


def measure_cleanliness(audio: Any, rate: int) -> dict[str, Any] | None:
    """The cleanliness numbers and verdict of a mono signal; None for silence or a clip under half a second."""
    samples = np.nan_to_num(np.asarray(audio, dtype=np.float64).reshape(-1))
    if rate <= 0 or len(samples) < MIN_SPECTRUM_SECONDS * rate or float(np.max(np.abs(samples))) < 1e-6:
        return None
    floor, speech, conclusive = _floor_numbers(samples, rate)
    low, bass = _energy_shares(samples, rate)
    snr = speech - floor
    reasons = _reasons(floor, snr, bass * 100, conclusive, speech >= MIN_SPEECH_DB)
    return {"noiseFloorDb": round(floor, 1), "snrDb": round(snr, 1), "speechDb": round(speech, 1),
            "lowEndPct": round(low * 100, 1), "bassPct": round(bass * 100, 1),
            "clippedPct": round(float(np.mean(np.abs(samples) >= CLIP_LEVEL)) * 100, 3),
            "seconds": round(len(samples) / rate, 2), "floorConclusive": conclusive,
            "verdict": "unclean" if reasons else ("clean" if conclusive else "inconclusive"), "reasons": reasons}


def measure_file(path: str) -> dict[str, Any] | None:
    """``measure_cleanliness`` of an audio file at its own sample rate; None when it cannot be read."""
    try:
        import soundfile as sf
        audio, rate = sf.read(path, dtype="float32", always_2d=True)
        return measure_cleanliness(audio.mean(axis=1), int(rate))
    except Exception:  # an unreadable take is simply unmeasured: the gate never stops a render
        return None


def clean_reason(metrics: Any) -> str | None:
    """Why this take is unclean (the first reason), or None when it is clean, inconclusive or unmeasured."""
    reasons = metrics.get("reasons") if isinstance(metrics, dict) else None
    return str(reasons[0]) if isinstance(reasons, list) and reasons else None


def dirt_score(metrics: Any) -> float:
    """0 for a take that is not unclean; otherwise 1 per reason plus how far past each limit it went."""
    if not clean_reason(metrics):
        return 0.0
    reasons, score = metrics["reasons"], 0.0
    if "noise_floor" in reasons:
        score += 1 + max(0.0, float(metrics.get("noiseFloorDb", 0)) - MAX_FLOOR_DB) / 10
    if "snr" in reasons:
        score += 1 + max(0.0, MIN_SNR_DB - float(metrics.get("snrDb", 0))) / 10
    if "bass" in reasons:
        score += 1 + max(0.0, float(metrics.get("bassPct", 0)) - MAX_BASS_PCT) / MAX_BASS_PCT
    return round(score, 3)


def describe(metrics: dict[str, Any]) -> str:
    """The ``qa.speech`` warning about an unclean take (the Characters voice designer shows it): the numbers, then the remedy."""
    parts = []
    if "noise_floor" in metrics["reasons"]:
        parts.append(f"noise floor {metrics['noiseFloorDb']:.0f} dBFS (limit {MAX_FLOOR_DB:.0f})")
    if "snr" in metrics["reasons"]:
        parts.append(f"{metrics['snrDb']:.0f} dB between speech and floor (at least {MIN_SNR_DB:.0f})")
    if "bass" in metrics["reasons"]:
        parts.append(f"{metrics['bassPct']:.0f}% of the energy between 40 and 100 Hz (under {MAX_BASS_PCT:.0f}%)")
    return f"The take is not clean: {', '.join(parts)}. {REMEDY}"


def unclean_warning(beat_id: str, metrics: dict[str, Any]) -> dict[str, Any]:
    """The ``voice_unclean`` entry of a render item's warnings, with the numbers and the remedy."""
    return {"id": beat_id, "warning": "voice_unclean", "cleanliness": metrics, "remedy": REMEDY}
