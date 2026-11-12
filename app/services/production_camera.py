"""A production shot's named camera move, over the whole shot, on a ``camera`` layer.

``camera`` on a shot names a ``kind: camera`` preset of ``motion_presets.json``. Its numbers describe the camera:
on a ``camera`` layer the renderer (``ui/src/lib/scene2d/evaluate.ts``, ``applyCameraTransform``) moves the view, so
``camera-pan-right`` pans right, ``camera-crane-up`` rises and ``camera-handheld`` shakes. Production used to write
them on the picture layer instead: the picture slid the other way, a preset shorter than the shot froze at its end, a
clip was forced back to a neutral end, and the shake was dropped (the renderer shakes camera layers only). So the
picture layer stays still, a camera layer plays the preset from the first frame to the last, and the picture is
enlarged just enough that the camera, its roll and its shake never show an edge of the picture.

A still also takes ``zoom`` [start, end]: it multiplies the preset's scale. A still with no ``camera`` moves by its
zoom alone (a centred push, 1.0→1.1 by default). Clips (``h3``, ``clip``, ``scene3d``) default to ``camera-locked``:
their generated motion is the move.
"""
from __future__ import annotations

import math
from typing import Any

from services.video2d_edit import Video2dEditError
from services.video2d_preset_catalog import camera_presets

ASPECT = 1920 / 1080                 # production scene documents (production_stage_scenes.scene_document)
STILL_ZOOM = (1.0, 1.1)
CLIP_CAMERA = "camera-locked"
LAYER = "camera"
_SAMPLES = 96
_SHAKE_LIMIT = 8.0                   # evaluate.ts shakenState clamps the amount to [0, 8]
_FOCUS = (10.0, 90.0)                # a focus nearer an edge cannot stay centred without showing that edge


def background_ops(source: str, layer_type: str, duration: float, *, camera: str | None = None,
                   zoom: Any = None, focus: Any = None, skip: float = 0.0) -> list[dict]:
    """The ``scenes.video2d.edit`` operations for a shot's picture (``bg``) and its camera.

    ``skip`` seconds of a video are skipped for the whole scene (lip-sync): the video span is
    ``sceneTimeline.getSceneLayerTiming``'s animation duration, so the picture's animation covers the scene plus the
    skipped head while the camera covers the scene."""
    still = layer_type != "video"
    name, start, end, preset = _path(camera if camera or still else CLIP_CAMERA, zoom if still else None)
    held = _focus(focus) if still else None
    scale = cover_scale(start, end, preset.get("shake"), held)
    pose = {"x": 50, "y": 50, "scale": scale, "rotation": 0}
    picture: dict[str, Any] = {"start": pose, "end": dict(pose), "duration": round(duration + skip, 3)}
    if skip > 0:
        picture["trimStart"] = skip
    patch: dict[str, Any] = {"fill": True, "transform": {"scale": scale}, "animation": picture}
    if held:
        patch["focus"] = held
    motion: dict[str, Any] = {"start": start, "end": end, "duration": round(duration, 3), "curve": preset["curve"]}
    if preset.get("shake"):
        motion["shake"] = dict(preset["shake"])
    return [
        {"op": "add_layer", "id": "bg", "source": source, "type": layer_type},
        {"op": "update_layer", "id": "bg", "patch": patch},
        {"op": "add_layer", "id": LAYER, "type": "camera", "name": name},
        {"op": "update_layer", "id": LAYER, "patch": {"transform": dict(start), "animation": motion}},
    ]


def _path(camera: str | None, zoom: Any) -> tuple[str, dict, dict, dict]:
    """``(layer name, start, end, preset)``: the preset's path with its scale times ``zoom``, or the zoom alone."""
    presets = camera_presets()
    if camera is None:
        z0, z1 = _zoom(zoom, STILL_ZOOM)
        return "zoom", _point(50, 50, z0, 0), _point(50, 50, z1, 0), {"curve": "ease"}
    preset = presets.get(camera)
    if preset is None:          # a resumed spec skips the plan gate (production_quality_gate)
        raise Video2dEditError("unknown_camera", f"camera {camera} is not a kind: camera preset of motion_presets.json")
    z0, z1 = _zoom(zoom, (1.0, 1.0))
    start, end = preset["start"], preset["end"]
    return (camera, _point(start["x"], start["y"], start["scale"] * z0, start.get("rotation", 0)),
            _point(end["x"], end["y"], end["scale"] * z1, end.get("rotation", 0)), preset)


def _zoom(value: Any, fallback: tuple[float, float]) -> tuple[float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 2 and all(
            isinstance(item, (int, float)) and not isinstance(item, bool) and item > 0 for item in value):
        return float(value[0]), float(value[1])
    return fallback


def _point(x: float, y: float, scale: float, rotation: float) -> dict:
    return {"x": round(float(x), 4), "y": round(float(y), 4), "scale": round(float(scale), 4), "rotation": round(float(rotation), 4)}


def _focus(value: Any) -> dict:
    low, high = _FOCUS

    def axis(key: str) -> float:
        raw = value.get(key) if isinstance(value, dict) else None
        return min(high, max(low, float(raw))) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 50

    return {"x": axis("x"), "y": axis("y")}


def cover_scale(start: dict, end: dict, shake: dict | None = None, focus: dict | None = None, aspect: float = ASPECT) -> float:
    """The smallest picture scale (at least 1) that keeps the frame covered along the camera path, with its shake.

    The path is sampled from start to end (every curve stays between them); the shake adds its worst offsets
    (x ± amount, y ± 0.65 amount, roll ± 0.35 amount, as in ``shakenState``)."""
    amount = min(_SHAKE_LIMIT, max(0.0, float((shake or {}).get("amount") or 0)))
    jitters = [(dx, dy, dr) for dx in (-amount, 0, amount) for dy in (-0.65 * amount, 0, 0.65 * amount)
               for dr in (-0.35 * amount, 0, 0.35 * amount)] if amount else [(0.0, 0.0, 0.0)]
    fx, fy = ((focus or {}).get("x", 50) - 50) / 100, ((focus or {}).get("y", 50) - 50) / 100
    needed = 1.0
    for index in range(_SAMPLES + 1):
        u = index / _SAMPLES
        view = {key: start.get(key, 0) + (end.get(key, 0) - start.get(key, 0)) * u for key in ("x", "y", "scale", "rotation")}
        for dx, dy, dr in jitters:
            needed = max(needed, _needed(view["x"] + dx, view["y"] + dy, view["scale"], view["rotation"] + dr, fx, fy, aspect))
    return math.ceil(needed * 1000 - 1e-6) / 1000


def _needed(vx: float, vy: float, vs: float, roll: float, fx: float, fy: float, aspect: float) -> float:
    """Scale a fill picture at 50/50 needs so a camera at (vx, vy, vs, roll) sees only picture.

    Mirrors ``applyCameraTransform`` and ``pinFocus``: the picture's centre goes to ``50 + zoom·R(-roll)(50 - v)``,
    its box is the frame times ``scale·vs`` turned by ``-roll``, and ``focus`` shifts the box by ``(focus - 50)·size``.
    In box units a frame corner at ``a`` (along x) needs ``|a + fx·m| ≤ m/2``."""
    theta = math.radians(roll)
    cos, sin = math.cos(theta), math.sin(theta)
    dx, dy = 50 - vx, 50 - vy
    cx = (50 + (dx * cos + dy / aspect * sin) * vs) / 100 * aspect
    cy = (50 + (-dx * aspect * sin + dy * cos) * vs) / 100
    needed = 0.0
    for px, py in ((0.0, 0.0), (aspect, 0.0), (0.0, 1.0), (aspect, 1.0)):
        ox, oy = px - cx, py - cy
        a = (cos * ox - sin * oy) / (aspect * vs)      # the corner in the picture's own axes (rotated by -roll)
        b = (sin * ox + cos * oy) / vs
        needed = max(needed, _axis(a, fx), _axis(b, fy))
    return needed


def _axis(offset: float, focus: float) -> float:
    return offset / (0.5 - focus) if offset > 0 else -offset / (0.5 + focus)


def unknown_cameras(spec: dict) -> list[dict]:
    """``unknown_camera`` for each shot, fill or shot override whose ``camera`` is not a camera preset id; ``uses``
    pairs each shot with the camera it asked for."""
    known = camera_presets()
    uses: list[dict] = []
    shots = spec.get("shots") if isinstance(spec.get("shots"), list) else []
    fills = spec.get("fill") if isinstance(spec.get("fill"), list) else []
    rows = [(str(shot.get("key")), shot) for shot in shots if isinstance(shot, dict)]
    rows += [(f"fill[{index}]", item) for index, item in enumerate(fills) if isinstance(item, dict)]
    for label, shot in rows:
        overrides = shot.get("overrides") if isinstance(shot.get("overrides"), dict) else {}
        for value in (shot.get("camera"), overrides.get("camera")):
            if value is not None and value not in known:
                uses.append({"shot": label, "camera": str(value)})
    if not uses:
        return []
    return [{"code": "unknown_camera", "shots": [use["shot"] for use in uses], "cameras": sorted({use["camera"] for use in uses}),
             "uses": uses, "hint": "camera is a kind: camera preset of motion_presets.json: " + ", ".join(known)}]


def is_camera(value: Any) -> bool:
    return isinstance(value, str) and value in camera_presets()


__all__ = ["background_ops", "cover_scale", "is_camera", "unknown_cameras"]
