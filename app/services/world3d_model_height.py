"""The real height a model recorded when it was made, so a scene can draw it at that height without guessing.

A character made by ``model3d.blob.make`` or ``model3d.anime.make`` writes its recipe in its gallery sidecar
(``<file>.meta.json``, ``params.traits.height``, metres); an import may record ``params.heightM``. A ``world3d.scene.patch``
binding that binds such a GLB without ``height``, ``fit`` or ``scale`` draws it at that height, and inspect shows it as
``layout.items[].recordedHeightM``. Any other GLB keeps the old rule (1.7 m x scale).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from services.asset_manifest import sidecar_path

_RANGE = (0.2, 6.0)
_CACHE: dict = {}


def recorded_height(path: Path | None) -> float | None:
    """The height in metres the model's sidecar records, or None."""
    if path is None:
        return None
    meta = sidecar_path(path)
    try:
        stat = meta.stat()
    except OSError:
        return None
    key = (str(meta), stat.st_mtime_ns, stat.st_size)
    if key not in _CACHE:
        if len(_CACHE) > 256:
            _CACHE.clear()
        _CACHE[key] = _read(meta)
    return _CACHE[key]


def _read(meta: Path) -> float | None:
    try:
        params = json.loads(meta.read_text(encoding="utf-8")).get("params") or {}
    except (OSError, ValueError, AttributeError):
        return None
    traits = params.get("traits") if isinstance(params.get("traits"), dict) else {}
    for value in (traits.get("height"), params.get("heightM")):
        if type(value) in (int, float) and math.isfinite(value) and _RANGE[0] <= value <= _RANGE[1]:
            return float(value)
    return None
