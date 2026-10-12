"""Deterministic sfxr presets for game sound effects."""
from __future__ import annotations

import hashlib

import numpy as np
import pytest

from services.game_sfxr import PRESETS, generate


def _digest(samples: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(samples).tobytes()).hexdigest()


def test_same_seed_reproduces_two_presets():
    for name in ("pickup", "explosion"):
        first, rate = generate(name, 99)
        second, again = generate(name, 99)
        assert rate == again == 44100
        assert _digest(first) == _digest(second)


def test_every_preset_is_finite_short_and_seeded():
    assert set(PRESETS) == {"pickup", "laser", "explosion", "powerup", "hit", "jump", "blip"}
    keys = set(PRESETS["blip"])
    for name, params in PRESETS.items():
        assert set(params) == keys
        assert params["wave"] in {"square", "saw", "sine", "noise"}
        first, rate = generate(name, 1)
        second, _rate = generate(name, 2)
        assert rate == 44100
        assert first.dtype == np.float32
        assert np.isfinite(first).all()
        assert float(np.max(np.abs(first))) <= 1.0
        assert first.shape[0] / rate < 3.0
        assert not np.array_equal(first, second)


def test_parameter_dict_fills_in_defaults():
    samples, rate = generate({"wave": "sine", "frequency": 500.0}, 1)
    # Default envelope: no attack, 0.08 s sustain, 0.12 s decay.
    assert samples.shape[0] == round(0.08 * rate) + round(0.12 * rate)
    assert np.isfinite(samples).all()
    assert _digest(samples) == _digest(generate({"wave": "sine", "frequency": 500.0}, 1)[0])


def test_unknown_wave_is_rejected():
    with pytest.raises(ValueError, match="triangle"):
        generate({"wave": "triangle"}, 1)


def test_noise_wave_is_not_a_rumble():
    # sfxr draws 32 noise values per period; one per period put most energy below 100 Hz.
    for seed in (1, 2, 3):
        samples, rate = generate("explosion", seed)
        power = np.abs(np.fft.rfft(samples.astype(np.float64))) ** 2
        freqs = np.fft.rfftfreq(samples.shape[0], 1.0 / rate)
        assert float(power[freqs < 100.0].sum() / power.sum()) < 0.3
