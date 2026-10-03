"""Write a standard humanoid skin into a GLB. pygltflib stays inside this module.

Each inverse bind matrix is the inverse of the bone's rest world matrix. The
skeleton is a new scene root next to the mesh. Meshes under a transformed node
are baked into world space first (see ``gltf_world``); otherwise vertices,
colors, materials and textures are left as they were. A skeleton from an earlier
rig is renamed and detached, so the new one is the only standard skeleton in the
file. The Hips node carries ``extras.hocuspocus_humanoid`` with the facts later
clips need.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.errors import InvalidInput
from services.humanoid_rig.gltf_buffers import (
    ARRAY_BUFFER,
    FLOAT,
    UNSIGNED_SHORT,
    append_accessor,
    read_floats,
    read_indices,
    require_plain_geometry,
)
from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES, BONE_PARENTS
from services.humanoid_rig.skeleton import world_matrices

MARKER = "hocuspocus_humanoid"
# Each animation's foot landings, ``[{t, foot, strength}]`` (see ``contacts``), so footsteps can follow it.
CONTACTS = "hocuspocus_contacts"


def read_primitives(source: bytes) -> list[dict]:
    """World-space triangles for every triangle primitive, in file order."""
    gltf, blob = _load(source)
    require_plain_geometry(gltf)
    found = []
    for _node, matrix, primitive in _iter_primitives(gltf):
        local = read_floats(gltf, blob, primitive.attributes.POSITION, 3)
        world = local @ matrix[:3, :3].T + matrix[:3, 3]
        found.append({"world": world, "indices": read_indices(gltf, blob, primitive)})
    return found


def append_animation_clips(source: bytes, clips: list[dict]) -> tuple[bytes, int]:
    """Add clips to a GLB that already has the standard skeleton."""
    gltf, blob = _load(source)
    joints = standard_joint_nodes(gltf)
    if gltf.animations is None:
        gltf.animations = []
    start = len(gltf.animations)
    _append_clips(gltf, blob, joints, clips)
    return _save(gltf, blob), start


def read_rig(source: bytes) -> dict:
    """Bones, Hips marker and floor height of a GLB with the standard skeleton."""
    gltf, blob = _load(source)
    joints = standard_joint_nodes(gltf)
    bones = []
    for (name, parent), node_index in zip(BONE_PARENTS, joints):
        node = gltf.nodes[node_index]
        if node.matrix:
            raise InvalidInput("standard humanoid skeleton uses matrices; re-rig the model")
        bones.append({
            "name": name,
            "parent": parent,
            "translation": np.asarray(node.translation or [0.0, 0.0, 0.0], dtype=np.float64),
            "rotation": np.asarray(node.rotation or [0.0, 0.0, 0.0, 1.0], dtype=np.float64),
            "scale": np.asarray(node.scale or [1.0, 1.0, 1.0], dtype=np.float64),
        })
    marker = dict((gltf.nodes[joints[0]].extras or {}).get(MARKER) or {})
    floor = marker.get("floor")
    if floor is None:
        floor = min((float(item["world"][:, 1].min()) for item in _primitives_of(gltf, blob)), default=0.0)
    return {"bones": bones, "marker": marker, "floor": float(floor)}


def _primitives_of(gltf, blob) -> list[dict]:
    found = []
    for _node, matrix, primitive in _iter_primitives(gltf):
        local = read_floats(gltf, blob, primitive.attributes.POSITION, 3)
        found.append({"world": local @ matrix[:3, :3].T + matrix[:3, 3]})
    return found


def write_rigged_glb(source: bytes, skeleton: dict, influences: list[tuple[np.ndarray, np.ndarray]], clips: list[dict] | None = None, marker: dict | None = None) -> bytes:
    """Return a new GLB. ``source`` is not modified."""
    from services.humanoid_rig.gltf_world import world_space_primitives

    gltf, blob = _load(source)
    require_plain_geometry(gltf)
    _clear_previous_skin(gltf)
    targets = world_space_primitives(gltf, blob, list(_iter_primitives(gltf)))
    if len(targets) != len(influences):
        raise RuntimeError("weight groups do not match the mesh primitives")
    joints = _append_skeleton(gltf, skeleton)
    if marker:
        gltf.nodes[joints[0]].extras = {MARKER: dict(marker)}
    skin = _append_skin(gltf, blob, joints, world_matrices(skeleton["bones"]))
    for (node_index, primitive), (joint_index, weight) in zip(targets, influences):
        gltf.nodes[node_index].skin = skin
        _bind_primitive(gltf, blob, primitive, joint_index, weight)
    if clips:
        _append_clips(gltf, blob, joints, clips)
    return _save(gltf, blob)


def _load(source: bytes):
    from pygltflib import GLTF2

    gltf = GLTF2.load_from_bytes(bytes(source))
    return gltf, bytearray(gltf.binary_blob() or b"")


def _save(gltf, blob: bytearray) -> bytes:
    while len(blob) % 4:
        blob.append(0)
    gltf.set_binary_blob(bytes(blob))
    gltf.buffers[0].byteLength = len(blob)
    return b"".join(gltf.save_to_bytes())


def _clear_previous_skin(gltf) -> None:
    old = {joint for skin in gltf.skins or [] for joint in skin.joints or []}
    old |= set(_bone_index(gltf).values())
    _detach(gltf, old)
    gltf.animations = []
    gltf.skins = []
    for node in gltf.nodes or []:
        node.skin = None
    for mesh in gltf.meshes or []:
        for primitive in mesh.primitives or []:
            primitive.attributes.JOINTS_0 = None
            primitive.attributes.WEIGHTS_0 = None


def _detach(gltf, joints: set[int]) -> None:
    """Rename old joints; unhook the ones whose subtree holds no mesh."""
    for index in joints:
        node = gltf.nodes[index]
        node.name = f"previous:{node.name or index}"
    _unhook(gltf, {index for index in joints if not _holds_mesh(gltf, index)})


def _unhook(gltf, loose: set[int]) -> None:
    for scene in gltf.scenes or []:
        scene.nodes = [index for index in scene.nodes or [] if index not in loose]
    for node in gltf.nodes or []:
        if node.children:
            node.children = [index for index in node.children if index not in loose] or None


def _holds_mesh(gltf, index: int, seen: set[int] | None = None) -> bool:
    seen = set() if seen is None else seen
    if index in seen:
        return False
    seen.add(index)
    node = gltf.nodes[index]
    return node.mesh is not None or any(_holds_mesh(gltf, child, seen) for child in node.children or [])


def _append_skeleton(gltf, skeleton: dict) -> list[int]:
    base = len(gltf.nodes)
    for bone in skeleton["bones"]:
        gltf.nodes.append(_bone_node(bone))
    for index, bone in enumerate(skeleton["bones"]):
        parent = bone["parent"]
        if parent is None:
            continue
        parent_node = gltf.nodes[base + BONE_BY_NAME[parent]]
        parent_node.children = list(parent_node.children or []) + [base + index]
    scene = gltf.scenes[gltf.scene or 0]
    scene.nodes = list(scene.nodes or []) + [base]
    return list(range(base, base + len(skeleton["bones"])))


def _bone_node(bone: dict):
    from pygltflib import Node

    node = Node(name=bone["name"], translation=[float(value) for value in bone["translation"]])
    rotation = np.asarray(bone["rotation"], dtype=np.float64)
    if not np.allclose(rotation, [0.0, 0.0, 0.0, 1.0], atol=1e-9):
        node.rotation = [float(value) for value in rotation / np.linalg.norm(rotation)]
    if bone["parent"] is None or not np.allclose(bone["scale"], 1.0):
        node.scale = [float(value) for value in bone["scale"]]
    return node


def _append_skin(gltf, blob, joint_nodes: list[int], bind: list[np.ndarray]) -> int:
    from pygltflib import Skin

    inverse = np.stack([np.linalg.inv(matrix).T for matrix in bind]).astype(np.float32)
    accessor = append_accessor(gltf, blob, inverse, FLOAT, "MAT4")
    gltf.skins.append(Skin(name="Humanoid", inverseBindMatrices=accessor, skeleton=joint_nodes[0], joints=joint_nodes))
    return len(gltf.skins) - 1


def _bind_primitive(gltf, blob, primitive, joints: np.ndarray, weights: np.ndarray) -> None:
    primitive.attributes.JOINTS_0 = append_accessor(gltf, blob, joints.astype(np.uint16), UNSIGNED_SHORT, "VEC4", ARRAY_BUFFER)
    primitive.attributes.WEIGHTS_0 = append_accessor(gltf, blob, weights.astype(np.float32), FLOAT, "VEC4", ARRAY_BUFFER)


def standard_joint_nodes(gltf) -> list[int]:
    by_name = _bone_index(gltf)
    if len(by_name) != len(BONE_NAMES):
        raise InvalidInput("standard humanoid skeleton not found")
    _require_parents(gltf, by_name, _parent_index(gltf))
    return [by_name[name] for name in BONE_NAMES]


def _bone_index(gltf) -> dict[str, int]:
    found = {}
    for index, node in enumerate(gltf.nodes or []):
        if node.name in BONE_BY_NAME and node.name not in found:
            found[node.name] = index
    return found


def _parent_index(gltf) -> dict[int, int]:
    found = {}
    for index, node in enumerate(gltf.nodes or []):
        for child in node.children or []:
            found[child] = index
    return found


def _require_parents(gltf, by_name: dict[str, int], parents: dict[int, int]) -> None:
    for name, parent in BONE_PARENTS:
        parent_id = parents.get(by_name[name])
        if parent is None:
            _require_root(gltf, parent_id)
            continue
        if parent_id is None or gltf.nodes[parent_id].name != parent:
            raise InvalidInput("standard humanoid skeleton not found")


def _require_root(gltf, parent_id: int | None) -> None:
    if parent_id is not None and gltf.nodes[parent_id].name in BONE_BY_NAME:
        raise InvalidInput("standard humanoid skeleton not found")


def _append_clips(gltf, blob, joint_nodes: list[int], clips: list[dict]) -> None:
    from pygltflib import Animation

    for clip in clips:
        animation = Animation(name=str(clip["name"]))
        times = np.asarray(clip["times"], dtype=np.float32)
        for bone, values in clip["rotations"].items():
            if bone not in BONE_BY_NAME:
                continue
            node = joint_nodes[BONE_BY_NAME[bone]]
            _add_channel(gltf, blob, animation, times, np.asarray(values, dtype=np.float32), node, "rotation")
        translation = clip.get("hips_translation")
        if translation is not None:
            _add_channel(gltf, blob, animation, times, np.asarray(translation, dtype=np.float32), joint_nodes[0], "translation")
        if "contacts" in clip:
            animation.extras = {CONTACTS: [dict(item) for item in clip["contacts"]]}
        gltf.animations.append(animation)


def _add_channel(gltf, blob, animation, times, values, node: int, path: str) -> None:
    from pygltflib import AnimationChannel, AnimationChannelTarget, AnimationSampler

    time_accessor = append_accessor(gltf, blob, times, FLOAT, "SCALAR", minmax=True)
    value_accessor = append_accessor(gltf, blob, values, FLOAT, "VEC4" if path == "rotation" else "VEC3")
    animation.samplers.append(AnimationSampler(input=time_accessor, output=value_accessor, interpolation="LINEAR"))
    animation.channels.append(AnimationChannel(
        sampler=len(animation.samplers) - 1,
        target=AnimationChannelTarget(node=node, path=path),
    ))


def _iter_primitives(gltf):
    globals_by_node = _global_matrices(gltf)
    for node_index, node in enumerate(gltf.nodes or []):
        if node.mesh is None or node_index not in globals_by_node:
            continue
        for primitive in gltf.meshes[node.mesh].primitives or []:
            mode = primitive.mode
            position = getattr(primitive.attributes, "POSITION", None)
            if position is None or mode not in (None, 4):
                continue
            yield node_index, globals_by_node[node_index], primitive


def _global_matrices(gltf) -> dict[int, np.ndarray]:
    found: dict[int, np.ndarray] = {}
    if not gltf.scenes:
        return found

    def walk(index: int, parent: np.ndarray) -> None:
        matrix = parent @ _node_matrix(gltf.nodes[index])
        found[index] = matrix
        for child in gltf.nodes[index].children or []:
            walk(child, matrix)

    scene = gltf.scenes[gltf.scene or 0]
    for root in scene.nodes or []:
        walk(root, np.eye(4))
    return found


def _node_matrix(node) -> np.ndarray:
    if node.matrix:
        return np.array(node.matrix, dtype=np.float64).reshape(4, 4).T
    matrix = np.eye(4)
    if node.scale:
        matrix[:3, :3] = np.diag(node.scale)
    if node.rotation:
        matrix[:3, :3] = _quat_matrix(node.rotation) @ matrix[:3, :3]
    if node.translation:
        matrix[:3, 3] = node.translation
    return matrix


def _quat_matrix(quaternion) -> np.ndarray:
    x, y, z, w = (float(value) for value in quaternion)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
