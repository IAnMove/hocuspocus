"""The triangles of a furniture GLB, read in the app: where its flat tops are and whether a point is inside it.

A box per mesh node is too coarse for furniture. A one-mesh chair's box holds the space above its seat and a one-mesh
table's box holds the leg room under its top (``cc0-table.glb`` and the Kenney furniture are one node each), so a person
seated correctly would be "inside" them. This module reads the real triangles (POSITION and indices of every mesh node
of the default scene, under its node transform, in the GLB's own units, rest pose) and answers two questions:

- ``flat_tops``: the upward faces grouped by height, with their area and footprint, so a seat or a table top is found
  from the mesh itself;
- ``inside``: how deep a point is inside the solid (a ray cast along +y counts the crossings; the depth is the nearest
  face along the six axis directions) and which part (mesh node, ``glb_parts`` numbering) that face belongs to.

Models with more than ``MAX_TRIANGLES`` triangles or skinned meshes are not read (a whole environment, a character).
Results are cached per file until it changes. Nothing here raises: an unreadable file is ``None``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from services.humanoid_rig.gltf_accessors import read_accessor, split_glb
from services.procedural_3d.glb_bounds import _mesh_nodes

LOG = logging.getLogger(__name__)
MAX_TRIANGLES = 60_000
MAX_BYTES = 32 * 1024 * 1024
UP = 0.9                  # a face whose normal is within ~25 degrees of +y is a top
BIN = 0.01                # tops within this height (model units) are one surface
_CACHE: dict = {}
_CACHE_LIMIT = 64
_DIRECTIONS = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], dtype=np.float64)
_JITTER = np.array([1.37e-5, 2.11e-5, 0.73e-5])


@dataclass
class Mesh:
    triangles: np.ndarray        # (N, 3, 3) in the GLB's units
    parts: np.ndarray            # (N,) the part (mesh node) of each triangle, numbered as glb_parts
    names: list                  # part index -> node name or None
    low: np.ndarray
    high: np.ndarray


def mesh_of(path: Path) -> Mesh | None:
    """The triangles of a GLB, or None when it cannot or should not be read (cached per file version)."""
    try:
        stat = Path(path).stat()
        if stat.st_size > MAX_BYTES:
            return None
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        if key not in _CACHE:
            if len(_CACHE) >= _CACHE_LIMIT:
                _CACHE.clear()
            _CACHE[key] = _read(Path(path).read_bytes())
        return _CACHE[key]
    except Exception:  # noqa: BLE001 - an unreadable model is just not analysed
        LOG.debug("mesh_of failed for %s", path, exc_info=True)
        return None


def _read(data: bytes) -> Mesh | None:
    document, buffers = split_glb(data)
    chunks, owners, names = [], [], []
    for part, (_index, node, world, mesh_index) in enumerate(_mesh_nodes(document)):
        if "skin" in node:
            return None
        names.append(node.get("name") if isinstance(node.get("name"), str) else None)
        matrix = np.asarray(world, dtype=np.float64)
        for primitive in (document.get("meshes") or [])[mesh_index].get("primitives") or []:
            triangles = _triangles(document, buffers, primitive)
            if triangles is None:
                continue
            chunks.append(triangles @ matrix[:3, :3].T + matrix[:3, 3])
            owners.append(np.full(len(triangles), part, dtype=np.int32))
            if sum(len(chunk) for chunk in chunks) > MAX_TRIANGLES:
                return None
    if not chunks:
        return None
    triangles = np.concatenate(chunks)
    points = triangles.reshape(-1, 3)
    return Mesh(triangles, np.concatenate(owners), names, points.min(axis=0), points.max(axis=0))


def _triangles(document: dict, buffers: list[bytes], primitive: dict) -> np.ndarray | None:
    if primitive.get("mode", 4) != 4 or not isinstance((primitive.get("attributes") or {}).get("POSITION"), int):
        return None
    positions = _floats(document, buffers, primitive["attributes"]["POSITION"])
    index = primitive.get("indices")
    order = _indices(document, buffers, index) if isinstance(index, int) else np.arange(len(positions))
    order = order[: len(order) - len(order) % 3]
    return positions[order].reshape(-1, 3, 3)


def _view(document: dict, accessor: dict) -> tuple[dict, int]:
    view = document["bufferViews"][accessor["bufferView"]]
    return view, int(view.get("byteOffset") or 0) + int(accessor.get("byteOffset") or 0)


def _floats(document: dict, buffers: list[bytes], index: int) -> np.ndarray:
    accessor = document["accessors"][index]
    view, start = _view(document, accessor) if "bufferView" in accessor else ({}, 0)
    if accessor.get("componentType") != 5126 or accessor.get("type") != "VEC3" or view.get("byteStride") not in (None, 12) or accessor.get("sparse"):
        return read_accessor(document, index, buffers)
    count = int(accessor["count"])
    return np.frombuffer(buffers[view.get("buffer", 0)], dtype="<f4", count=count * 3, offset=start).reshape(count, 3).astype(np.float64)


def _indices(document: dict, buffers: list[bytes], index: int) -> np.ndarray:
    accessor = document["accessors"][index]
    kinds = {5121: "<u1", 5123: "<u2", 5125: "<u4"}
    if accessor.get("componentType") not in kinds or accessor.get("sparse") or "bufferView" not in accessor:
        return read_accessor(document, index, buffers).astype(np.int64)
    view, start = _view(document, accessor)
    data = np.frombuffer(buffers[view.get("buffer", 0)], dtype=kinds[accessor["componentType"]], count=int(accessor["count"]), offset=start)
    return data.astype(np.int64)


# ------------------------------------------------------------------------------------------------------------------ tops

def flat_tops(mesh: Mesh, parts: set[int] | None = None) -> list[dict]:
    """Horizontal upward surfaces, highest first: ``{y, area, low [x, z], high [x, z], parts}`` in model units."""
    triangles, owners = mesh.triangles, mesh.parts
    if parts is not None:
        keep = np.isin(owners, sorted(parts))
        triangles, owners = triangles[keep], owners[keep]
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    length = np.linalg.norm(cross, axis=1)
    up = (length > 1e-12) & (cross[:, 1] > UP * np.maximum(length, 1e-12))
    if not up.any():
        return []
    heights = triangles[up][:, :, 1].mean(axis=1)
    return _grouped(triangles[up], owners[up], heights, 0.5 * length[up])


def _grouped(triangles: np.ndarray, owners: np.ndarray, heights: np.ndarray, areas: np.ndarray) -> list[dict]:
    order = np.argsort(-heights)
    groups: list[list[int]] = []
    for index in order:
        if groups and heights[groups[-1][0]] - heights[index] <= BIN:
            groups[-1].append(int(index))
        else:
            groups.append([int(index)])
    surfaces = []
    for members in groups:
        corners = triangles[members].reshape(-1, 3)
        surfaces.append({"y": float(np.average(heights[members], weights=areas[members] + 1e-12)), "area": float(areas[members].sum()),
                         "low": [float(corners[:, 0].min()), float(corners[:, 2].min())],
                         "high": [float(corners[:, 0].max()), float(corners[:, 2].max())],
                         "parts": sorted({int(item) for item in owners[members]})})
    return surfaces


# ---------------------------------------------------------------------------------------------------------------- inside

def inside(mesh: Mesh, points) -> tuple[np.ndarray, np.ndarray]:
    """``(depth, part)`` per point: how deep it is inside the solid (0 outside) and the part of the nearest face (-1 outside)."""
    depth, part, _exits = inside_exits(mesh, points)
    return depth, part


def inside_exits(mesh: Mesh, points) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``inside`` plus, per point, the axis direction of the nearest way out (a unit vector; zero outside)."""
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    depth = np.zeros(len(points))
    part = np.full(len(points), -1, dtype=np.int32)
    exits = np.zeros((len(points), 3))
    for row, point in enumerate(points):
        if np.any(point < mesh.low) or np.any(point > mesh.high):
            continue
        origin = point + _JITTER                  # off the grid, so a ray never runs exactly along a shared edge
        hits = [_hits(mesh, origin, direction) for direction in _DIRECTIONS]
        # Each part is its own closed solid (overlapping boxes stay solid): odd crossings above the point mean inside it.
        counts = np.bincount(hits[2][1], minlength=len(mesh.names))
        holders = np.flatnonzero(counts % 2 == 1)
        if not len(holders):
            continue
        nearest = [(distances[mask].min(), owners[mask][distances[mask].argmin()], axis) for axis, (distances, owners) in enumerate(hits)
                   for mask in [np.isin(owners, holders)] if mask.any()]
        if nearest:
            depth[row], part[row], axis = min(nearest, key=lambda item: item[0])
            exits[row] = _DIRECTIONS[axis]
    return depth, part, exits


def passes_through(mesh: Mesh, start, end) -> np.ndarray:
    """The parts the segment from ``start`` to ``end`` passes right through: it crosses two opposite faces of the part
    (in one side of a table top and out of the other, across a leg). Cutting a corner (in by the top, out by the front)
    is a graze, not a pass."""
    start, end = np.asarray(start, dtype=np.float64) + _JITTER, np.asarray(end, dtype=np.float64) + _JITTER
    length = float(np.linalg.norm(end - start))
    if length < 1e-9 or np.any(np.maximum(start, end) < mesh.low) or np.any(np.minimum(start, end) > mesh.high):
        return np.zeros(0, dtype=np.int32)
    distances, owners, faces = _hits(mesh, start, (end - start) / length, faces=True)
    keep = distances < length
    owners, faces = owners[keep], faces[keep]
    if len(faces) < 2:
        return np.zeros(0, dtype=np.int32)
    triangles = mesh.triangles[faces]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    opposite = (normals @ normals.T < -0.9) & (owners[:, None] == owners[None, :])
    return np.unique(owners[opposite.any(axis=1)])


def _hits(mesh: Mesh, origin: np.ndarray, direction: np.ndarray, faces: bool = False):
    """Distances along ``direction`` at which the ray from ``origin`` crosses a triangle (Moller-Trumbore), their parts,
    and with ``faces`` the triangle indices."""
    a, b, c = mesh.triangles[:, 0], mesh.triangles[:, 1], mesh.triangles[:, 2]
    edge1, edge2 = b - a, c - a
    pvec = np.cross(direction, edge2)
    det = np.einsum("ij,ij->i", edge1, pvec)
    usable = np.abs(det) > 1e-12
    inverse = np.where(usable, 1.0 / np.where(usable, det, 1.0), 0.0)
    tvec = origin - a
    u = np.einsum("ij,ij->i", tvec, pvec) * inverse
    qvec = np.cross(tvec, edge1)
    v = (qvec @ direction) * inverse
    t = np.einsum("ij,ij->i", edge2, qvec) * inverse
    crossing = usable & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-9)
    if faces:
        return t[crossing], mesh.parts[crossing], np.flatnonzero(crossing)
    return t[crossing], mesh.parts[crossing]
