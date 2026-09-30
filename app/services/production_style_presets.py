"""Named looks expanded from productions that already rendered (app/shared/style_presets.json).

``anime`` is the promo musical style. ``riso-zine`` is the Love the Machine
look without its DHH-specific footer and lip-sync line (those go in the spec).
``omarchy-desktop`` is keyboard-first (native desktop, no on-screen singer).
``neo-noir-realista`` is City of Windows.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from services.production_image_defaults import image_style_defaults

UNKNOWN_PRESET = "unknown_style_preset"
PRESET_IDS = ("anime", "riso-zine", "omarchy-desktop", "neo-noir-realista")
PRESETS: dict[str, dict] = json.loads((Path(__file__).resolve().parents[1] / "shared" / "style_presets.json").read_text(encoding="utf-8"))["entries"]


def expand_style_preset(spec: Any) -> Any:
    """Fill style from a preset. Keys set beside the preset replace those fields."""
    if not isinstance(spec, dict):
        return spec
    style = spec.get("style")
    if not isinstance(style, dict):
        return spec
    base = _preset_fields(style.get("preset")) if "preset" in style else {}
    overlay = {key: value for key, value in style.items() if key != "preset"}
    return {**spec, "style": image_style_defaults({**base, **overlay}, overlay)}


def _preset_fields(name: Any) -> dict:
    if isinstance(name, str) and name in PRESETS:
        return copy.deepcopy(PRESETS[name])
    from services.music_production import ProductionError
    raise ProductionError(UNKNOWN_PRESET, f"unknown style preset {name}")
