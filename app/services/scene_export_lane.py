"""Shared scene2d-render lane. The coordinator freezes the semaphore on first acquire.

Both the scene export and the contact-sheet painter must ask for the same capacity,
or the second caller is stuck with whatever the first one stored.

Each painter is one headless browser plus one encoder, about one and a half
cores. Two painters left a 32-core machine mostly idle during a two-language
episode export, so the default now grows with the core count.
"""
from __future__ import annotations

import os

from services.resource_scheduler import cpu_lane

ENV = "HOCUS_SCENE_EXPORT_CONCURRENCY"
MAX_CAPACITY = 8
CORES_PER_PAINTER = 6
DEFAULT_RANGE = (2, 6)


def scene2d_render_lane():
    """Default one painter per six cores, from 2 to 6. An invalid value, or one outside 1–8, is 1."""
    raw = os.environ.get(ENV)
    return cpu_lane("scene2d-render", capacity=_capacity(raw))


def default_capacity(cores: int | None = None) -> int:
    cores = cores if cores is not None else (os.cpu_count() or 1)
    low, high = DEFAULT_RANGE
    return max(low, min(high, cores // CORES_PER_PAINTER))


def _capacity(raw: str | None) -> int:
    if raw is None or not str(raw).strip():
        return default_capacity()
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 1
    if isinstance(raw, bool) or value < 1 or value > MAX_CAPACITY:
        return 1
    return value
