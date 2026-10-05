"""Layered sets for 2D Series shots: images and looping videos at a depth, behind or in front of the cast.

A location's ``layout2d.layers`` are drawn over its base background (``series_shot_plan.background_for``) in every
2D shot there; a shot's own ``layout2d.layers`` replace them, and ``[]`` turns them off for that shot::

    {"layers": [{"assetId": "asset_columns", "depth": 0.25},
                {"file": "fg-candle.png", "depth": 0.95, "front": true, "x": 12, "y": 70, "scale": 0.5},
                {"file": "fog.webm", "depth": 0.85, "front": true, "opacity": 0.5, "scale": 1.2, "drift": 14}],
     "castDepth": 0.6}

``depth`` 0 is the far plane of the background (it moves least), 1 the nearest; the cast stands at ``castDepth``
(default 0.6; a shot's value overrides its location's). Layers with ``front: true`` are drawn in front of the cast,
the others behind it, farthest first. ``x``/``y`` (%) put the layer's centre on the background, so it stays on its
spot when a tighter framing zooms and pans the background; ``scale`` is a fraction of the frame height (1 fills the
frame with a frame-sized image). The Video 2D compiler (``ui/scripts/seriesShot.ts``) gives every layer, and the base
background, its share of the camera push by depth: far layers grow and move less than the cast, near ones more.
``drift`` (frame pixels per second, negative to the left) slides a layer on its own, for fog or smoke; give it a
``scale`` above 1 so its edge stays out of the frame. A malformed layer is refused, not dropped: a missing pillar
would change the picture.
"""
from __future__ import annotations

from typing import Any

from services.series_shot_extras import _FILE

MAX_LAYERS = 8
CAST_DEPTH = 0.6
VIDEO_SUFFIXES = (".mp4", ".webm", ".mov", ".m4v")
KEYS = ("layers", "castDepth")
# Default depth: just behind the cast's floor plane, or close to the lens in front of it.
_DEPTH = {False: 0.3, True: 0.9}
_LIMITS = (("depth", 0, 1), ("opacity", 0, 1), ("x", -50, 150), ("y", -50, 150), ("scale", 0.05, 4), ("drift", -400, 400))


def _number(value: Any, low: float, high: float) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high else None


def _layout(value: Any) -> dict[str, Any]:
    """The ``layout2d`` of a location or a shot, or an empty one."""
    layout = value.get("layout2d") if isinstance(value, dict) else None
    return layout if isinstance(layout, dict) else {}


def _source(value: dict[str, Any], label: str) -> tuple[str, str]:
    given = [key for key in ("assetId", "file") if value.get(key) is not None]
    if len(given) != 1 or not isinstance(value[given[0]], str) or not value[given[0]].strip():
        raise ValueError(f"{label} needs exactly one of assetId (a series image or video) or file (a workspace file)")
    key, source = given[0], value[given[0]].strip()
    if len(source) > 300 or (key == "file" and not _FILE.match(source)):
        raise ValueError(f"{label}.{key} must be a workspace path or asset id of at most 300 characters")
    return key, source


def layer_entry(value: Any, label: str) -> dict[str, Any]:
    """One layer with its defaults filled in; unknown keys are dropped, a bad value is refused."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object {{assetId | file, depth, front, opacity, x, y, scale, drift}}")
    key, source = _source(value, label)
    if value.get("front") is not None and not isinstance(value["front"], bool):
        raise ValueError(f"{label}.front must be true or false")
    front = value.get("front") is True
    entry: dict[str, Any] = {key: source, "depth": _DEPTH[front], "front": front, "opacity": 1.0, "x": 50.0, "y": 50.0, "scale": 1.0}
    for name, low, high in _LIMITS:
        if value.get(name) is None:
            continue
        number = _number(value[name], low, high)
        if number is None:
            raise ValueError(f"{label}.{name} must be a number from {low:g} to {high:g}")
        entry[name] = number
    if not entry.get("drift"):
        entry.pop("drift", None)
    return entry


def normalize_layers(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of layers")
    if len(value) > MAX_LAYERS:
        raise ValueError(f"{label} has more than {MAX_LAYERS} layers")
    return [layer_entry(item, f"{label}[{index}]") for index, item in enumerate(value)]


def layout_layers(value: dict[str, Any], label: str) -> dict[str, Any]:
    """``layers`` and ``castDepth`` of a ``layout2d``, normalized; a key left out or null stays out. ``label`` prefixes
    the error messages (``locations[2].layout2d``; empty for a script shot)."""
    prefix = f"{label}." if label else ""
    found: dict[str, Any] = {}
    if value.get("layers") is not None:
        found["layers"] = normalize_layers(value["layers"], f"{prefix}layers")
    if value.get("castDepth") is not None:
        depth = _number(value["castDepth"], 0.1, 1)
        if depth is None:
            raise ValueError(f"{prefix}castDepth must be a number from 0.1 to 1")
        found["castDepth"] = depth
    return found


def normalize_location(location: dict[str, Any], label: str) -> dict[str, Any]:
    """Check a location's layers in place. An empty list is dropped, so taking the layers away renders as before."""
    layout = location.get("layout2d")
    if not isinstance(layout, dict) or not any(key in layout for key in KEYS):
        return location
    found = layout_layers(layout, label)
    if not found.get("layers"):
        found.pop("layers", None)
    location["layout2d"] = {key: found.get(key, value) for key, value in layout.items() if key not in KEYS or key in found}
    return location


def shot_layers(location: dict[str, Any] | None, shot: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    """The layers a shot draws (its own list, else its location's) and the depth its cast stands at."""
    own, place = _layout(shot), _layout(location)
    items = own["layers"] if isinstance(own.get("layers"), list) else place.get("layers") or []
    layers = []
    for index, item in enumerate(items[:MAX_LAYERS]):
        try:
            layers.append(layer_entry(item, f"layers[{index}]"))
        except ValueError:
            continue  # saved data is checked on save; a hand-edited file must not stop the render
    depth = next((value for value in (own.get("castDepth"), place.get("castDepth")) if _number(value, 0.1, 1) is not None), CAST_DEPTH)
    return layers, float(depth)


def layer_kind(file: str) -> str:
    return "video" if file.lower().endswith(VIDEO_SUFFIXES) else "image"


def digest_location(location: dict[str, Any] | None, shot: dict[str, Any]) -> dict[str, Any] | None:
    """The location as a shot's render sees it: its layers matter only to a 2D shot that does not bring its own, so
    changing them leaves 3D shots and overriding shots up to date. A location without layers is returned as it is."""
    layout = _layout(location)
    if not any(key in layout for key in KEYS):
        return location
    own, flat = _layout(shot), shot.get("productionMethod") == "animation_2d"
    unseen = {key for key in KEYS if not flat or own.get(key) is not None}
    if not unseen:
        return location
    rest = {key: value for key, value in layout.items() if key not in unseen}
    seen = {key: value for key, value in location.items() if key != "layout2d"}
    return {**seen, "layout2d": rest} if rest else seen
