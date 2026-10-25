"""Where a Video 3D model object really is, in metres: the size its GLB gets from the renderer, at its position.

The renderer draws a model object like this (ui/src/features/scene3d/gpu.ts ``fitGltf``): the loaded scene is scaled
about its own origin by ``1.7 / (bounding-box height)`` times the object's ``scale``, then moved to ``position`` and
turned ``rotationY`` about y. So a model is always ``1.7 m x scale`` tall, whatever its length, and a whole-environment
GLB is a 1.7 m object until ``scale`` says otherwise. A ``grounded`` object is then lowered or lifted so the lowest point
of the model sits at ``position[1]`` (``groundLoadedSlot``). Nothing re-centres the model, so x and z stay wherever the
GLB put its origin.

The model's own box comes from ``glb_bounds`` (rest pose, JSON chunk only). An image cutout is a plane
``CUTOUT_HEIGHT`` tall times its scale (``imageCutoutMesh``).
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from urllib.parse import urlsplit

from services.kernel.paths import safe_join
from services.media_refs import parse_media_ref
from services.procedural_3d.glb_bounds import glb_bounds
from services.procedural_3d.glb_parts import glb_parts

MODEL_HEIGHT = 1.7       # fitGltf: a model object is this tall at scale 1
CUTOUT_HEIGHT = 2.0      # imageCutoutMesh: an image cutout plane is this tall at scale 1
_MIN_HEIGHT = 0.001      # fitGltf: Math.max(size.y, 0.001)
_FILE_PREFIX = "/api/v1/file/"
_CACHE: dict = {}
_CACHE_LIMIT = 256


def _workspace_file(name: str, workspace: str, workspace_dir):
    """The path inside the workspace, or ``(None, "missing_file")`` when the workspace itself cannot be opened."""
    try:
        return safe_join(str(workspace_dir(workspace)), *[part for part in name.split("/") if part]), None
    except Exception:  # noqa: BLE001 - an unknown workspace is a missing file here, never a failed inspect
        return None, "missing_file"


def resolve_workspace_glb(url, workspace: str, workspace_dir) -> tuple[Path | None, str | None]:
    """The workspace file a slot's ``sourceUrl`` names, or ``(None, reason)``. Uploads, example media, other
    workspaces, remote URLs and anything that climbs out of the workspace folder are not resolved."""
    text = str(url or "").strip()
    if not text:
        return None, "marker"
    if urlsplit(text).scheme or text.startswith("//"):
        return None, "outside_workspace"
    name, scoped = parse_media_ref(text, None)
    if scoped and scoped != workspace:
        return None, "outside_workspace"
    if name.startswith(_FILE_PREFIX):
        name = name[len(_FILE_PREFIX):]
    elif name.startswith("/") or "\x00" in name:
        return None, "outside_workspace"
    if not name.lower().endswith(".glb"):
        return None, "not_glb"
    path, failed = _workspace_file(name, workspace, workspace_dir)
    if failed:
        return None, failed
    if path is None:
        return None, "outside_workspace"
    return (Path(path), None) if os.path.isfile(path) else (None, "missing_file")


def native_bounds(path: Path) -> dict:
    """``glb_bounds`` of a file, remembered until the file changes (an inspect reads each model's header once)."""
    try:
        stat = path.stat()
    except OSError:
        return glb_bounds(path)
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _CACHE:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[key] = glb_bounds(path)
    return _CACHE[key]


def native_parts(path: Path) -> dict:
    """``glb_parts`` of a file, remembered until the file changes (the same cache and key as ``native_bounds``)."""
    try:
        stat = path.stat()
    except OSError:
        return glb_parts(path)
    key = ("parts", str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _CACHE:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[key] = glb_parts(path)
    return _CACHE[key]


def slot_native_parts(slot: dict, workspace: str, workspace_dir) -> dict:
    """The mesh-node boxes of the GLB a model slot points at: ``glb_parts`` (``ok: False`` and a ``reason`` when unreadable)."""
    path, reason = resolve_workspace_glb(slot.get("sourceUrl"), workspace, workspace_dir)
    if path is None:
        return {"ok": False, "parts": [], "omitted": 0, "reason": reason}
    return native_parts(path)


def slot_native_bounds(slot: dict, workspace: str, workspace_dir) -> dict:
    """The box of the GLB a model slot points at: ``glb_bounds`` plus ``reason`` when the file cannot be measured."""
    path, reason = resolve_workspace_glb(slot.get("sourceUrl"), workspace, workspace_dir)
    if path is None:
        return {"ok": False, "reason": reason}
    return native_bounds(path)


def normalisation(box: dict) -> float:
    """The factor the renderer applies to a model at scale 1: ``1.7 / bbox height`` (the height never below 1 mm)."""
    return MODEL_HEIGHT / max(box["size"][1], _MIN_HEIGHT)


def placed_bounds(box: dict, slot: dict) -> dict:
    """The model's size and place in the scene. ``size`` is its own width, height and depth in metres (x, y, z of the
    GLB, before ``rotationY``). ``min``, ``max`` and ``center`` are world coordinates after position and ``rotationY``;
    ``bottomY`` is the lowest point. ``grounded`` puts that point at ``position[1]``."""
    scale = float(slot.get("scale") or 1)
    factor = normalisation(box) * scale
    px, py, pz = (float(v) for v in (slot.get("position") or [0, 0, 0]))
    angle = float(slot.get("rotationY") or 0)
    cos, sin = math.cos(angle), math.sin(angle)
    low = [value * factor for value in box["min"]]
    high = [value * factor for value in box["max"]]
    lift = py - low[1] if slot.get("grounded") else py
    xs, zs = [], []
    for x in (low[0], high[0]):
        for z in (low[2], high[2]):
            xs.append(px + x * cos + z * sin)      # three.js rotation.y: x' = x cos + z sin, z' = -x sin + z cos
            zs.append(pz - x * sin + z * cos)
    world_low, world_high = [min(xs), low[1] + lift, min(zs)], [max(xs), high[1] + lift, max(zs)]
    return {"size": _round(high[axis] - low[axis] for axis in range(3)),
            "center": _round((world_low[axis] + world_high[axis]) / 2 for axis in range(3)),
            "bottomY": round(world_low[1], 4), "min": _round(world_low), "max": _round(world_high)}


def _round(values) -> list[float]:
    return [round(float(value), 4) for value in values]
