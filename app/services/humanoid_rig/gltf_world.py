"""Put every mesh the skin drives into world space, hung from the scene root.

glTF ignores the transform of a skinned mesh's node, while three.js applies it
once at bind time. A centimetre export with a 0.01 scale, a Z-up armature or a
mesh used by two nodes would then read differently in each viewer. Baking the
node's world matrix into the vertices, and moving the mesh to a new root node
without a transform, makes every reading agree. The old node keeps its own
transform and children; only its mesh moves.
"""

from __future__ import annotations

import copy
from collections import Counter

import numpy as np

from services.humanoid_rig.gltf_buffers import (
    ARRAY_BUFFER,
    ELEMENT_ARRAY_BUFFER,
    FLOAT,
    UNSIGNED_INT,
    append_accessor,
    read_floats,
    read_indices,
)


def world_space_primitives(gltf, blob: bytearray, pairs: list) -> list[tuple[int, object]]:
    """``(node index, primitive)`` for each ``(node, world matrix, primitive)``, in order, after baking."""
    users = Counter(gltf.nodes[node_index].mesh for node_index in {pair[0] for pair in pairs})
    moved: dict[int, tuple[int, dict]] = {}
    found = []
    for node_index, matrix, primitive in pairs:
        if node_index not in moved:
            shared = users[gltf.nodes[node_index].mesh] > 1
            moved[node_index] = _rehome(gltf, blob, node_index, matrix, shared)
        new_index, mapping = moved[node_index]
        found.append((new_index, mapping[id(primitive)]))
    return found


def _rehome(gltf, blob: bytearray, node_index: int, matrix: np.ndarray, shared: bool) -> tuple[int, dict]:
    from pygltflib import Node

    node = gltf.nodes[node_index]
    mesh = gltf.meshes[node.mesh]
    if not shared and np.allclose(matrix, np.eye(4), atol=1e-9):
        return node_index, {id(primitive): primitive for primitive in mesh.primitives}
    clone = copy.deepcopy(mesh)
    gltf.meshes.append(clone)
    mapping = {}
    for old, new in zip(mesh.primitives, clone.primitives):
        _bake(gltf, blob, new, matrix)
        mapping[id(old)] = new
    gltf.nodes.append(Node(name=node.name, mesh=len(gltf.meshes) - 1))
    node.mesh = None
    scene = gltf.scenes[gltf.scene or 0]
    scene.nodes = list(scene.nodes or []) + [len(gltf.nodes) - 1]
    return len(gltf.nodes) - 1, mapping


def _bake(gltf, blob: bytearray, primitive, matrix: np.ndarray) -> None:
    linear, shift = matrix[:3, :3], matrix[:3, 3]
    normal_matrix = np.linalg.inv(linear).T
    attributes = primitive.attributes
    positions = read_floats(gltf, blob, attributes.POSITION, 3) @ linear.T + shift
    attributes.POSITION = append_accessor(gltf, blob, positions.astype(np.float32), FLOAT, "VEC3", ARRAY_BUFFER, minmax=True)
    if attributes.NORMAL is not None:
        normals = _unit(read_floats(gltf, blob, attributes.NORMAL, 3) @ normal_matrix.T)
        attributes.NORMAL = append_accessor(gltf, blob, normals.astype(np.float32), FLOAT, "VEC3", ARRAY_BUFFER)
    if attributes.TANGENT is not None:
        tangents = read_floats(gltf, blob, attributes.TANGENT, 4)
        tangents[:, :3] = _unit(tangents[:, :3] @ linear.T)
        tangents[:, 3] *= np.sign(np.linalg.det(linear)) or 1.0
        attributes.TANGENT = append_accessor(gltf, blob, tangents.astype(np.float32), FLOAT, "VEC4", ARRAY_BUFFER)
    _bake_targets(gltf, blob, primitive, linear, normal_matrix)
    if np.linalg.det(linear) < 0.0:
        _flip_winding(gltf, blob, primitive, len(positions))


def _bake_targets(gltf, blob: bytearray, primitive, linear: np.ndarray, normal_matrix: np.ndarray) -> None:
    """Morph target deltas turn with the mesh but do not move."""
    for target in primitive.targets or []:
        for name, transform in (("POSITION", linear), ("NORMAL", normal_matrix)):
            index = target.get(name) if isinstance(target, dict) else getattr(target, name, None)
            if index is None:
                continue
            moved = read_floats(gltf, blob, index, 3) @ transform.T
            baked = append_accessor(gltf, blob, moved.astype(np.float32), FLOAT, "VEC3", ARRAY_BUFFER, minmax=name == "POSITION")
            if isinstance(target, dict):
                target[name] = baked
            else:
                setattr(target, name, baked)


def _flip_winding(gltf, blob: bytearray, primitive, count: int) -> None:
    """A mirroring matrix turns faces inside out; swap two corners of every triangle."""
    faces = read_indices(gltf, blob, primitive)
    if faces is None:
        faces = np.arange(count - count % 3, dtype=np.int64).reshape(-1, 3)
    flipped = faces[:, [0, 2, 1]].astype(np.uint32).reshape(-1)
    primitive.indices = append_accessor(gltf, blob, flipped, UNSIGNED_INT, "SCALAR", ELEMENT_ARRAY_BUFFER)


def _unit(rows: np.ndarray) -> np.ndarray:
    return rows / np.maximum(np.linalg.norm(rows, axis=1, keepdims=True), 1e-12)
