"""Original synthesizer for the sfxr sound model.

This is an original implementation of the sfxr algorithm by Tomas Pettersson
(DrPetter), MIT license. It is not a copy of the C source.

Waves are square (with duty), saw, sine, and pitched noise. The envelope is
attack, sustain, punch, and decay. Pitch moves by a slide, a delta slide, vibrato,
and one arpeggio jump. A resonant low-pass and high-pass follow, then a phaser.
Noise comes from ``numpy.random.Generator(numpy.random.PCG64(seed))`` so a seed
replays the same samples. The sample rate is 44100 Hz.
"""
from __future__ import annotations

import numpy as np

SR = 44100

_WAVES = ("square", "saw", "sine", "noise")

_DEFAULTS = {
    "wave": "square",
    "duty": 0.5,
    "duty_slide": 0.0,
    "frequency": 440.0,
    "slide": 0.0,
    "delta_slide": 0.0,
    "min_frequency": 40.0,
    "vibrato_depth": 0.0,
    "vibrato_speed": 0.0,
    "arp_ratio": 1.0,
    "arp_time": 0.1,
    "attack": 0.0,
    "sustain": 0.08,
    "punch": 0.0,
    "decay": 0.12,
    "noise": 0.02,
    "lp_freq": 8000.0,
    "lp_resonance": 0.15,
    "lp_slide": 0.0,
    "hp_freq": 40.0,
    "hp_resonance": 0.1,
    "hp_slide": 0.0,
    "phaser_offset": 0.0,
    "phaser_sweep": 0.0,
}


def _preset(**overrides) -> dict:
    params = dict(_DEFAULTS)
    params.update(overrides)
    return params


# Fixed category sounds. ``noise`` is mixed into tonal waves so the seed changes
# every preset; a noise wave uses the pitched-noise oscillator instead.
PRESETS = {
    "pickup": _preset(
        wave="square", duty=0.5, frequency=720.0, slide=0.4,
        arp_ratio=1.498, arp_time=0.07, sustain=0.06, punch=0.45, decay=0.14,
        noise=0.02, lp_freq=6500.0, lp_resonance=0.2, hp_freq=180.0,
    ),
    "laser": _preset(
        wave="saw", duty=0.25, duty_slide=-0.15, frequency=980.0, slide=-4.2,
        delta_slide=-1.4, min_frequency=70.0, vibrato_depth=0.06, vibrato_speed=28.0,
        sustain=0.11, punch=0.25, decay=0.2, noise=0.035,
        lp_freq=5200.0, lp_resonance=0.45, lp_slide=-1.6,
        hp_freq=240.0, hp_resonance=0.2,
        phaser_offset=0.0015, phaser_sweep=-0.004,
    ),
    "explosion": _preset(
        wave="noise", frequency=90.0, slide=-1.8, delta_slide=-0.6, min_frequency=28.0,
        vibrato_depth=0.12, vibrato_speed=9.0, sustain=0.18, punch=0.85, decay=0.7,
        noise=1.0, lp_freq=900.0, lp_resonance=0.55, lp_slide=-1.3,
        hp_freq=35.0, hp_resonance=0.25,
        phaser_offset=0.003, phaser_sweep=0.012,
    ),
    "powerup": _preset(
        wave="square", duty=0.35, frequency=280.0, slide=2.4,
        vibrato_depth=0.04, vibrato_speed=14.0, arp_ratio=1.5, arp_time=0.12,
        sustain=0.22, punch=0.3, decay=0.22, noise=0.02,
        lp_freq=7000.0, lp_resonance=0.25, hp_freq=80.0,
    ),
    "hit": _preset(
        wave="square", duty=0.2, duty_slide=-0.2, frequency=420.0, slide=-6.5,
        min_frequency=50.0, sustain=0.035, punch=0.7, decay=0.1, noise=0.18,
        lp_freq=2800.0, lp_resonance=0.5, hp_freq=120.0, hp_resonance=0.35,
    ),
    "jump": _preset(
        wave="square", duty=0.45, frequency=260.0, slide=3.2,
        sustain=0.09, punch=0.35, decay=0.13, noise=0.02,
        lp_freq=4800.0, lp_resonance=0.2, hp_freq=90.0, hp_resonance=0.2,
    ),
    "blip": _preset(
        wave="sine", frequency=880.0, slide=0.8, sustain=0.03, punch=0.15, decay=0.06,
        noise=0.015, lp_freq=7500.0, hp_freq=200.0, arp_ratio=1.0, arp_time=1.0,
    ),
}


def _resolve(preset) -> dict:
    """A preset by name, or a parameter dict filled in from the defaults."""
    if isinstance(preset, str):
        try:
            params = PRESETS[preset]
        except KeyError as exc:
            raise KeyError(f"unknown sfxr preset {preset!r}") from exc
    elif isinstance(preset, dict):
        params = {**_DEFAULTS, **preset}
    else:
        raise TypeError("preset must be a name or a parameter dict")
    if params["wave"] not in _WAVES:
        raise ValueError(f"unknown sfxr wave {params['wave']!r}; expected one of {', '.join(_WAVES)}")
    return params


def _seed(seed) -> int:
    value = int(seed)
    if value < 0:
        return value % (2**32)
    return value


def _duration_samples(params: dict, sr: int) -> tuple[int, int, int, int]:
    attack = max(0, int(round(float(params["attack"]) * sr)))
    sustain = max(0, int(round(float(params["sustain"]) * sr)))
    decay = max(1, int(round(float(params["decay"]) * sr)))
    total = attack + sustain + decay
    cap = int(sr * 2.95)
    if total <= cap:
        return total, attack, sustain, decay
    scale = cap / float(total)
    attack = int(attack * scale)
    sustain = int(sustain * scale)
    decay = max(1, cap - attack - sustain)
    return attack + sustain + decay, attack, sustain, decay


def _frequency_curve(n: int, sr: int, params: dict) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / float(sr)
    base = max(1.0, float(params["frequency"]))
    curved = base * np.exp(float(params["slide"]) * t + 0.5 * float(params["delta_slide"]) * t * t)
    vibrato = 1.0 + float(params["vibrato_depth"]) * np.sin(
        2.0 * np.pi * float(params["vibrato_speed"]) * t
    )
    jump = np.where(t >= float(params["arp_time"]), float(params["arp_ratio"]), 1.0)
    floor = max(1.0, float(params["min_frequency"]))
    return np.clip(curved * vibrato * jump, floor, sr * 0.45)


def _pitched_noise(travel: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """sfxr's noise wave: 32 random values per oscillator period.

    ``travel`` is the running phase in periods, so ``floor(travel * 32)`` steps
    to the next value 32 times per cycle, like sfxr's 32-entry noise buffer.
    """
    if travel.size == 0:
        return np.zeros(0, dtype=np.float64)
    steps = np.floor(travel * 32.0).astype(np.int64)
    table = rng.uniform(-1.0, 1.0, size=int(steps[-1]) + 1)
    return table[steps]


def _square(phase: np.ndarray, params: dict, sr: int) -> np.ndarray:
    t = np.arange(phase.shape[0], dtype=np.float64) / float(sr)
    width = np.clip(float(params["duty"]) + float(params["duty_slide"]) * t, 0.05, 0.95)
    return np.where(phase < width, 1.0, -1.0)


def _voice(params: dict, travel: np.ndarray, sr: int, white: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    kind = str(params["wave"])
    if kind == "noise":
        return _pitched_noise(travel, rng)
    phase = travel % 1.0
    if kind == "saw":
        shaped = 2.0 * phase - 1.0
    elif kind == "sine":
        shaped = np.sin(2.0 * np.pi * phase)
    else:
        shaped = _square(phase, params, sr)
    return shaped + float(params["noise"]) * white


def _envelope(n: int, attack: int, sustain: int, decay: int, punch: float) -> np.ndarray:
    env = np.zeros(n, dtype=np.float64)
    if attack:
        env[:attack] = np.linspace(0.0, 1.0, attack, endpoint=False)
    if sustain:
        fade = np.linspace(1.0, 0.0, sustain, endpoint=False)
        env[attack : attack + sustain] = 1.0 + punch * fade
    if decay:
        start = attack + sustain
        env[start : start + decay] = np.linspace(1.0, 0.0, decay, endpoint=True)
    return env


def _cutoff_curve(n: int, sr: int, start, slide) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / float(sr)
    freq = float(start) * np.exp(float(slide) * t)
    return np.clip(freq, 40.0, float(sr) / 6.0)


def _damping(resonance) -> float:
    amount = min(1.0, max(0.0, float(resonance)))
    return 0.85 - 0.5 * amount


def _svf_split(signal: np.ndarray, cutoff: np.ndarray, resonance, sr: int):
    """Chamberlin state-variable split. ``q`` stays high enough to stay stable."""
    samples = np.ascontiguousarray(signal, dtype=np.float64).tolist()
    coeffs = (2.0 * np.sin(np.pi * cutoff / float(sr))).tolist()
    q = _damping(resonance)
    low = 0.0
    band = 0.0
    lows = [0.0] * len(samples)
    highs = [0.0] * len(samples)
    for index, sample in enumerate(samples):
        coeff = coeffs[index]
        high = sample - low - q * band
        band += coeff * high
        low += coeff * band
        lows[index] = low
        highs[index] = high
    return np.nan_to_num(np.asarray(lows)), np.nan_to_num(np.asarray(highs))


def _filter_bank(signal: np.ndarray, params: dict, sr: int) -> np.ndarray:
    frames = int(signal.shape[0])
    low, _high = _svf_split(
        signal, _cutoff_curve(frames, sr, params["lp_freq"], params["lp_slide"]), params["lp_resonance"], sr,
    )
    _low, high = _svf_split(
        low, _cutoff_curve(frames, sr, params["hp_freq"], params["hp_slide"]), params["hp_resonance"], sr,
    )
    return high


def _phaser(signal: np.ndarray, sr: int, offset, sweep) -> np.ndarray:
    offset = float(offset)
    sweep = float(sweep)
    if offset == 0.0 and sweep == 0.0:
        return signal
    n = int(signal.shape[0])
    t = np.arange(n, dtype=np.float64) / float(sr)
    delay = np.clip(offset + sweep * t, 0.0, 0.02) * sr
    index = np.arange(n, dtype=np.float64) - delay
    i0 = np.floor(index).astype(np.int64)
    frac = index - i0
    i0 = np.clip(i0, 0, n - 1)
    i1 = np.clip(i0 + 1, 0, n - 1)
    delayed = signal[i0] * (1.0 - frac) + signal[i1] * frac
    return 0.5 * signal + 0.5 * delayed


def _limit(signal: np.ndarray) -> np.ndarray:
    clean = np.nan_to_num(np.asarray(signal, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    clean *= 0.35
    peak = float(np.max(np.abs(clean))) if clean.size else 0.0
    if peak > 1.0:
        clean = clean / peak
    return np.clip(clean, -1.0, 1.0).astype(np.float32)


def generate(preset, seed) -> tuple[np.ndarray, int]:
    """Synthesize ``preset`` (a name or a parameter dict). The same seed repeats."""
    params = _resolve(preset)
    total, attack, sustain, decay = _duration_samples(params, SR)
    # Running phase in periods; the curve is already clipped to 1 Hz .. 0.45 * SR.
    travel = np.cumsum(_frequency_curve(total, SR, params) / float(SR))
    rng = np.random.Generator(np.random.PCG64(_seed(seed)))
    white = rng.uniform(-1.0, 1.0, size=total)
    voice = _voice(params, travel, SR, white, rng)
    shaped = voice * _envelope(total, attack, sustain, decay, float(params["punch"]))
    filtered = _filter_bank(shaped, params, SR)
    phased = _phaser(filtered, SR, params["phaser_offset"], params["phaser_sweep"])
    return _limit(phased), SR
