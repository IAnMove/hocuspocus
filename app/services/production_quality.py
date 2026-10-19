"""Quality profiles for a production: how much the run spends to make the result good.

``spec.quality`` is ``draft``, ``standard`` or ``max``. It fills what the spec left out (max_takes), picks how many
song candidates a run makes, and it sets the bar ``dry_run`` measures the plan against (how much of the runtime may be a still image, how many
clips a minute). No profile means ``standard``'s bar and the spec exactly as written.
"""
from __future__ import annotations

from typing import Any

PROFILES: dict[str, dict[str, Any]] = {
    "draft": {"seeds": 1, "max_takes": 1, "static": 0.6, "clips_per_minute": 2},
    "standard": {"seeds": 3, "max_takes": 2, "static": 0.35, "clips_per_minute": 5},
    "max": {"seeds": 4, "max_takes": 3, "static": 0.15, "clips_per_minute": 7},
}
DEFAULT = "standard"
SEED_BASE = 101


def profile_of(spec: Any) -> dict[str, Any]:
    quality = spec.get("quality") if isinstance(spec, dict) else None
    return PROFILES.get(quality) or PROFILES[DEFAULT]


def song_seed_offsets(spec: Any) -> list[int]:
    """Default song seeds, as offsets from the production's own base; ``song.seeds`` is used as written."""
    if isinstance(spec, dict) and spec.get("quality") in PROFILES:
        return [SEED_BASE * (index + 1) + index for index in range(PROFILES[spec["quality"]]["seeds"])]
    return [11, 22, 33]


def expand_quality(spec: Any) -> Any:
    """Fill the takes a profile implies; what the spec set itself is kept."""
    if not isinstance(spec, dict) or "quality" not in spec:
        return spec
    quality = spec["quality"]
    if quality not in PROFILES:
        from services.music_production import ProductionError
        raise ProductionError("invalid_spec", f"quality must be one of {', '.join(PROFILES)}")
    profile = PROFILES[quality]
    filled = dict(spec)
    filled.setdefault("max_takes", profile["max_takes"])
    return filled
