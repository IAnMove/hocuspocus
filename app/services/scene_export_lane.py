"""Shared scene2d-render lane. The coordinator freezes the semaphore on first acquire.

Both the scene export and the contact-sheet painter must ask for the same capacity,
or the second caller is stuck with whatever the first one stored.
"""
from __future__ import annotations

import os

from services.resource_scheduler import cpu_lane

ENV = "HOCUS_SCENE_EXPORT_CONCURRENCY"


def scene2d_render_lane():
    """Default two painters. A missing value is 2. An invalid value, or one outside 1–4, is 1."""
    raw = os.environ.get(ENV)
    return cpu_lane("scene2d-render", capacity=_capacity(raw))


def _capacity(raw: str | None) -> int:
    if raw is None or not str(raw).strip():
        return 2
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 1
    if isinstance(raw, bool) or value < 1 or value > 4:
        return 1
    return value
