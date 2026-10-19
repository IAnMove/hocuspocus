"""The production profile a fresh install starts from: the best image model that is already installed.

Until the user saves a profile, the global image model was the MiniMax cloud API, and Qwen Image 2.1 (newer, much better
at following a comic prompt) had to be chosen by hand in Settings. A profile that has never been saved now starts on
local Qwen Image 2.1 Turbo when its weights are installed, or on the base Qwen Image 2.1 when only that is; with neither
installed it stays on the static default, so a small install is not pointed at a model it cannot run. A saved profile is
never touched.

The answer is cached for a short time: the profile is read by every request and "is it installed" walks the checkpoint folders.
"""
from __future__ import annotations

import copy
import time
from typing import Callable

from services.production_image_defaults import DEFAULT_IMAGE_MODEL

PREFERRED_LOCAL_IMAGE_MODEL = DEFAULT_IMAGE_MODEL
# In order: Turbo (the default), then the base model for an install that has only that.
PREFERRED_LOCAL_IMAGE_MODELS = (PREFERRED_LOCAL_IMAGE_MODEL, "qwen_image_21")
_TTL_S = 30.0
_cache: dict[str, float | str | None] = {"at": float("-inf"), "model": None}


def _installed_model(probe: Callable[[str], bool], now: float) -> str | None:
    """The first preferred model that is installed, or None."""
    if now - float(_cache["at"]) >= _TTL_S:
        found = None
        for model in PREFERRED_LOCAL_IMAGE_MODELS:
            try:
                if probe(model):
                    found = model
                    break
            except Exception:  # a probe that cannot run means "not installed", never a broken profile endpoint
                continue
        _cache.update(at=now, model=found)
    return _cache["model"]  # type: ignore[return-value]


def default_profile(static: dict, probe: Callable[[str], bool], *, now: Callable[[], float] = time.monotonic) -> dict:
    """A copy of ``static`` whose image model is local Qwen Image 2.1 Turbo (else the base) when installed."""
    profile = copy.deepcopy(static)
    model = _installed_model(probe, now())
    if model:
        profile["image"] = {"provider": "local", "model": model}
    return profile


def reset_cache() -> None:
    _cache.update(at=float("-inf"), model=None)
