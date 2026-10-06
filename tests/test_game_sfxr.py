"""Deterministic sfxr presets for game sound effects."""
from __future__ import annotations

import hashlib

import numpy as np

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
