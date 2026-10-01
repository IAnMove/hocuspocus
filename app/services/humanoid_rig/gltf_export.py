"""Write a standard humanoid skin into a GLB. pygltflib stays inside this module.

Video 3D binds the skin with an identity bind matrix and then draws the mesh
with its own world matrix, so each inverse bind is only the inverse of the
bone's world matrix. The mesh stays a sibling of Hips; its vertices, colors,
materials and textures are left as they were.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES, BONE_PARENTS
from services.humanoid_rig.skeleton import world_matrices

FLOAT = 5126
UNSIGNED_SHORT = 5123
ARRAY_BUFFER = 34962
_INDEX_DTYPE = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}


def read_primitives(source: bytes) -> list[dict]:
    """World-space triangles for every triangle primitive, in file order."""
    gltf, blob = _load(source)
    found = []
    for _node, matrix, primitive in _iter_primitives(gltf):
        local = _read_vec3(gltf, blob, primitive.attributes.POSITION)
        world = local @ matrix[:3, :3].T + matrix[:3, 3]
        found.append({"world": world, "indices": _read_indices(gltf, blob, primitive)})
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


def hips_scale(source: bytes) -> float:
    gltf, _blob = _load(source)
    node = gltf.nodes[standard_joint_nodes(gltf)[0]]
    return float((node.scale or [1.0, 1.0, 1.0])[0])


def write_rigged_glb(source: bytes, skeleton: dict, influences: list[tuple[np.ndarray, np.ndarray]], clips: list[dict] | None = None) -> bytes:
    """Return a new GLB. ``source`` is not modified."""
    gltf, blob = _load(source)
    _clear_previous_skin(gltf)
    joints = _append_skeleton(gltf, skeleton)
    primitives = list(_iter_primitives(gltf))
    if len(primitives) != len(influences):
        raise RuntimeError("weight groups do not match the mesh primitives")
    bind = world_matrices(skeleton["bones"])
    skin = _append_skin(gltf, blob, joints, bind)
    for (node_index, _matrix, primitive), (joint_index, weight) in zip(primitives, influences):
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
    gltf.animations = []
    gltf.skins = []
    for node in gltf.nodes or []:
        node.skin = None
    for mesh in gltf.meshes or []:
        for primitive in mesh.primitives or []:
            primitive.attributes.JOINTS_0 = None
            primitive.attributes.WEIGHTS_0 = None


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
    if bone["parent"] is None or not np.allclose(bone["scale"], 1.0):
        node.scale = [float(value) for value in bone["scale"]]
    return node


def _append_skin(gltf, blob, joint_nodes: list[int], bind: list[np.ndarray]) -> int:
    from pygltflib import Skin

    inverse = np.stack([np.linalg.inv(matrix).T for matrix in bind]).astype(np.float32)
    accessor = _append_accessor(gltf, blob, inverse, FLOAT, "MAT4")
    gltf.skins.append(Skin(name="Humanoid", inverseBindMatrices=accessor, skeleton=joint_nodes[0], joints=joint_nodes))
    return len(gltf.skins) - 1


def _bind_primitive(gltf, blob, primitive, joints: np.ndarray, weights: np.ndarray) -> None:
    primitive.attributes.JOINTS_0 = _append_accessor(gltf, blob, joints.astype(np.uint16), UNSIGNED_SHORT, "VEC4", ARRAY_BUFFER)
    primitive.attributes.WEIGHTS_0 = _append_accessor(gltf, blob, weights.astype(np.float32), FLOAT, "VEC4", ARRAY_BUFFER)


def standard_joint_nodes(gltf) -> list[int]:
    by_name = _bone_index(gltf)
    if len(by_name) != len(BONE_NAMES):
        raise ValueError("standard humanoid skeleton not found")
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
            raise ValueError("standard humanoid skeleton not found")


def _require_root(gltf, parent_id: int | None) -> None:
    if parent_id is not None and gltf.nodes[parent_id].name in BONE_BY_NAME:
        raise ValueError("standard humanoid skeleton not found")


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
        gltf.animations.append(animation)


def _add_channel(gltf, blob, animation, times, values, node: int, path: str) -> None:
    from pygltflib import AnimationChannel, AnimationChannelTarget, AnimationSampler

    time_accessor = _append_accessor(gltf, blob, times, FLOAT, "SCALAR", minmax=True)
    value_accessor = _append_accessor(gltf, blob, values, FLOAT, "VEC4" if path == "rotation" else "VEC3")
    animation.samplers.append(AnimationSampler(input=time_accessor, output=value_accessor, interpolation="LINEAR"))
    animation.channels.append(AnimationChannel(
        sampler=len(animation.samplers) - 1,
        target=AnimationChannelTarget(node=node, path=path),
    ))


def _append_accessor(gltf, blob, data: np.ndarray, component_type: int, type_str: str, target: int | None = None, minmax: bool = False) -> int:
    from pygltflib import Accessor, BufferView

    while len(blob) % 4:
        blob.append(0)
    payload = np.ascontiguousarray(data).tobytes()
    view = BufferView(buffer=0, byteOffset=len(blob), byteLength=len(payload))
    if target is not None:
        view.target = target
    blob.extend(payload)
    gltf.bufferViews.append(view)
    components = {"SCALAR": 1, "VEC3": 3, "VEC4": 4, "MAT4": 16}[type_str]
    count = int(data.size // components)
    accessor = Accessor(bufferView=len(gltf.bufferViews) - 1, componentType=component_type, count=count, type=type_str)
    if minmax and count:
        flat = np.ascontiguousarray(data, dtype=np.float64).reshape(count, components)
        accessor.min = [float(value) for value in flat.min(axis=0)]
        accessor.max = [float(value) for value in flat.max(axis=0)]
    gltf.accessors.append(accessor)
    return len(gltf.accessors) - 1


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


def _read_vec3(gltf, blob: bytes, accessor_index: int) -> np.ndarray:
    accessor = gltf.accessors[accessor_index]
    view = gltf.bufferViews[accessor.bufferView]
    offset = (view.byteOffset or 0) + (accessor.byteOffset or 0)
    stride = view.byteStride or 12
    count = accessor.count
    if stride == 12:
        return np.frombuffer(blob, dtype="<f4", count=count * 3, offset=offset).reshape(-1, 3).astype(np.float64)
    raw = np.frombuffer(blob, dtype=np.uint8, count=stride * (count - 1) + 12, offset=offset)
    gather = np.arange(count)[:, None] * stride + np.arange(12)[None, :]
    return raw[gather].copy().view("<f4").reshape(count, 3).astype(np.float64)


def _read_indices(gltf, blob: bytes, primitive):
    if primitive.indices is None:
        return None
    accessor = gltf.accessors[primitive.indices]
    dtype = _INDEX_DTYPE.get(accessor.componentType)
    if dtype is None:
        raise ValueError("triangle indices must be an unsigned integer accessor")
    view = gltf.bufferViews[accessor.bufferView]
    offset = (view.byteOffset or 0) + (accessor.byteOffset or 0)
    values = np.frombuffer(blob, dtype=dtype, count=accessor.count, offset=offset).astype(np.int64)
    if len(values) % 3:
        raise ValueError("triangle index count is not a multiple of 3")
    return values.reshape(-1, 3)
