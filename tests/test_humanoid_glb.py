"""Skinned GLB: rest pose holds, colors survive, and a bad mesh is refused."""
import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pygltflib")

from pygltflib import GLTF2

from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.names import BONE_NAMES
from services.humanoid_rig.rig import rig_humanoid
from services.humanoid_rig.skeleton import axis_quaternion
from services.procedural_3d.compose import compose_glb
from services.procedural_3d.glb_inspector import inspect_glb_bytes

ROOT = Path(__file__).parents[1] / "tests" / "fixtures" / "humanoid_rig"


def _pieces(name):
    return json.loads((ROOT / f"{name}.json").read_text())["pieces"]


def _accessor(gltf, blob, index):
    accessor = gltf.accessors[index]
    view = gltf.bufferViews[accessor.bufferView]
    offset = (view.byteOffset or 0) + (accessor.byteOffset or 0)
    return accessor, offset


def _vec3(gltf, blob, index):
    accessor, offset = _accessor(gltf, blob, index)
    count = accessor.count
    return np.frombuffer(blob, dtype="<f4", count=count * 3, offset=offset).reshape(-1, 3).copy()


def _skin_rest(gltf, blob, primitive):
    joints = _vec4(gltf, blob, primitive.attributes.JOINTS_0, np.uint16)
    weights = _vec4(gltf, blob, primitive.attributes.WEIGHTS_0, np.float32).astype(np.float64)
    positions = _vec3(gltf, blob, primitive.attributes.POSITION).astype(np.float64)
    skin = gltf.skins[gltf.nodes[0].skin]
    accessor, offset = _accessor(gltf, blob, skin.inverseBindMatrices)
    raw = np.frombuffer(blob, dtype="<f4", count=accessor.count * 16, offset=offset).reshape(-1, 4, 4)
    inverse = raw.transpose(0, 2, 1).astype(np.float64)
    bind = _joint_worlds(gltf)
    skinned = np.zeros_like(positions)
    for slot in range(4):
        for joint in np.unique(joints[:, slot]):
            mask = joints[:, slot] == joint
            if not np.any(mask):
                continue
            parented = bind[int(joint)] @ inverse[int(joint)]
            local = positions[mask]
            moved = local @ parented[:3, :3].T + parented[:3, 3]
            skinned[mask] += weights[mask, slot:slot + 1] * moved
    return positions, skinned


def _vec4(gltf, blob, index, dtype):
    accessor, offset = _accessor(gltf, blob, index)
    count = accessor.count
    return np.frombuffer(blob, dtype=dtype, count=count * 4, offset=offset).reshape(-1, 4).copy()


def _joint_worlds(gltf) -> list[np.ndarray]:
    ids = list(gltf.skins[0].joints)
    parents = {}
    for index, node in enumerate(gltf.nodes):
        for child in node.children or []:
            parents[child] = index
    worlds: dict[int, np.ndarray] = {}

    def walk(node_id: int) -> np.ndarray:
        if node_id in worlds:
            return worlds[node_id]
        node = gltf.nodes[node_id]
        local = np.eye(4)
        local[:3, :3] = np.diag(node.scale or [1.0, 1.0, 1.0])
        if node.rotation:
            local[:3, :3] = _quat(node.rotation) @ local[:3, :3]
        local[:3, 3] = node.translation or [0.0, 0.0, 0.0]
        parent_id = parents.get(node_id)
        parent = np.eye(4) if parent_id is None else walk(parent_id)
        worlds[node_id] = parent @ local
        return worlds[node_id]

    return [walk(node_id) for node_id in ids]


def _quat(quaternion) -> np.ndarray:
    x, y, z, w = (float(value) for value in quaternion)
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


@pytest.mark.parametrize("name", ("robot", "pet", "a_pose"))
def test_rigged_compose_rests_keeps_colors_and_passes_the_inspector(name):
    source = bytearray(compose_glb(_pieces(name), name))
    original_colors = _vec3(*_loaded(bytes(source)), 2)
    rigged, sidecar = rig_humanoid(source)
    assert bytes(source) == bytes(compose_glb(_pieces(name), name))
    report = inspect_glb_bytes(rigged)
    assert report.status == "valid"
    assert not [issue for issue in report.issues if issue.severity == "error"]
    gltf, blob = _loaded(rigged)
    assert [node.name for node in gltf.nodes if node.name in BONE_NAMES] == list(BONE_NAMES)
    assert all(not name.startswith("mixamorig") for name in BONE_NAMES)
    colors = _vec3(gltf, blob, 2)
    assert np.array_equal(colors, original_colors)
    assert gltf.materials[0].name == "Flat vertex colors"
    positions, skinned = _skin_rest(gltf, blob, gltf.meshes[0].primitives[0])
    assert float(np.linalg.norm(skinned - positions, axis=1).max()) < 1e-5
    assert sidecar["bones"] == list(BONE_NAMES)
    assert sidecar["confidence"] == 1.0
    hips = next(node for node in gltf.nodes if node.name == "Hips")
    assert hips.scale[0] == pytest.approx(sidecar["height"] / 1.7)
    assert _joint_worlds(gltf)[BONE_NAMES.index("LeftHand")][0, 3] > 0


def test_hands_stuck_is_not_rigged_and_one_leg_is_a_different_reason():
    stuck = bytearray(compose_glb(_pieces("hands_stuck"), "hands_stuck"))
    before = bytes(stuck)
    with pytest.raises(NotHumanoid) as caught:
        rig_humanoid(stuck)
    assert caught.value.reason == "hands_stuck"
    assert bytes(stuck) == before
    with pytest.raises(NotHumanoid) as other:
        rig_humanoid(compose_glb(_pieces("one_leg"), "one_leg"))
    assert other.value.reason == "single_leg"


def test_exported_right_arm_rotation_moves_the_hand_only_on_that_side():
    rigged, _sidecar = rig_humanoid(compose_glb(_pieces("robot"), "robot"))
    gltf, blob = _loaded(rigged)
    primitive = gltf.meshes[0].primitives[0]
    positions = _vec3(gltf, blob, primitive.attributes.POSITION).astype(np.float64)
    joints = _vec4(gltf, blob, primitive.attributes.JOINTS_0, np.uint16)
    weights = _vec4(gltf, blob, primitive.attributes.WEIGHTS_0, np.float32).astype(np.float64)
    bind = _joint_worlds(gltf)
    arm = next(node for node in gltf.nodes if node.name == "RightArm")
    arm.rotation = [float(value) for value in axis_quaternion(np.array([0.0, 0.0, 1.0]), 90.0)]
    posed = _joint_worlds(gltf)
    inverse = _inverse_binds(gltf, blob)
    delta = _blend(positions, joints, weights, bind, posed, inverse)
    assert float(delta[positions[:, 0] < -0.95].min()) > 0.2
    left = (positions[:, 0] > 0.02) & (positions[:, 0] < 0.20) & (positions[:, 1] > 0.9)
    assert float(delta[left].max()) < 0.02


def _inverse_binds(gltf, blob):
    accessor, offset = _accessor(gltf, blob, gltf.skins[0].inverseBindMatrices)
    raw = np.frombuffer(blob, dtype="<f4", count=accessor.count * 16, offset=offset).reshape(-1, 4, 4)
    return raw.transpose(0, 2, 1).astype(np.float64)


def _blend(positions, joints, weights, bind, posed, inverse):
    skinned = np.zeros_like(positions)
    for slot in range(4):
        for joint in np.unique(joints[:, slot]):
            mask = joints[:, slot] == joint
            if not np.any(mask):
                continue
            matrix = posed[int(joint)] @ inverse[int(joint)]
            local = positions[mask]
            skinned[mask] += weights[mask, slot:slot + 1] * (local @ matrix[:3, :3].T + matrix[:3, 3])
    return np.linalg.norm(skinned - positions, axis=1)


def _loaded(data: bytes):
    gltf = GLTF2.load_from_bytes(data)
    return gltf, gltf.binary_blob()
