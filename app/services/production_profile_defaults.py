"""The production profile a fresh install starts from: the best image model that is already installed.

Until the user saves a profile, the global image model was the MiniMax cloud API, and Qwen Image 2.1 (newer, much better
at following a comic prompt) had to be chosen by hand in Settings. A profile that has never been saved now starts on
local Qwen Image 2.1 when its weights are installed; with nothing installed it stays on the static default, so a small
install is not pointed at a model it cannot run. A saved profile is never touched.

The answer is cached for a short time: the profile is read by every request and "is it installed" walks the checkpoint folders.
"""
from __future__ import annotations

import copy
import time
from typing import Callable

PREFERRED_LOCAL_IMAGE_MODEL = "qwen_image_21"
_TTL_S = 30.0
_cache: dict[str, float | bool] = {"at": float("-inf"), "installed": False}


def _installed(model: str, probe: Callable[[str], bool], now: float) -> bool:
    if now - float(_cache["at"]) >= _TTL_S:
        try:
            _cache.update(at=now, installed=bool(probe(model)))
        except Exception:  # a probe that cannot run means "not installed", never a broken profile endpoint
            _cache.update(at=now, installed=False)
    return bool(_cache["installed"])


def default_profile(static: dict, probe: Callable[[str], bool], *, now: Callable[[], float] = time.monotonic) -> dict:
    """A copy of ``static`` whose image model is local Qwen Image 2.1 when it is installed."""
    profile = copy.deepcopy(static)
    if _installed(PREFERRED_LOCAL_IMAGE_MODEL, probe, now()):
        profile["image"] = {"provider": "local", "model": PREFERRED_LOCAL_IMAGE_MODEL}
    return profile


def reset_cache() -> None:
    _cache.update(at=float("-inf"), installed=False)
