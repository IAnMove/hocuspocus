"""Skinned GLB: rest pose holds, colors survive, and a bad mesh is refused."""
import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pygltflib")

from pygltflib import GLTF2

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.names import BONE_NAMES
from services.humanoid_rig.rig import rig_humanoid
from services.procedural_3d.compose import compose_glb
from services.procedural_3d.glb_inspector import inspect_glb_bytes
from tests.humanoid_bodies import as_glb, body

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
    assert sidecar["confidence"] >= 0.8
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
    arm.rotation = [float(value) for value in rot.axis_angle(np.array([0.0, 0.0, 1.0]), 90.0)]
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


def test_an_a_pose_mesh_rests_exactly_and_carries_its_rig_facts():
    rigged, sidecar = rig_humanoid(as_glb(body("human_a")), ["walk", "wave"], 120)
    report = inspect_glb_bytes(rigged)
    assert report.status == "valid"
    gltf, blob = _loaded(rigged)
    positions, skinned = _skin_rest(gltf, blob, gltf.meshes[0].primitives[0])
    assert float(np.linalg.norm(skinned - positions, axis=1).max()) < 1e-5
    left_arm = next(node for node in gltf.nodes if node.name == "LeftArm")
    assert left_arm.rotation is not None and abs(left_arm.rotation[2]) > 0.2
    hips = next(node for node in gltf.nodes if node.name == "Hips")
    marker = hips.extras["hocuspocus_humanoid"]
    assert marker["version"] == 2 and marker["facing"] == 1
    assert 30.0 <= marker["arm_down"] <= 80.0 and marker["chest_front"] > 0.0
    assert [animation.name for animation in gltf.animations] == ["Walk", "Wave"]
    assert sidecar["pose"] == "a" and [clip["name"] for clip in sidecar["clips"]] == ["Walk", "Wave"]


def test_rigging_a_rigged_model_again_leaves_one_standard_skeleton():
    once, _sidecar = rig_humanoid(as_glb(body("human_t")))
    twice, _sidecar = rig_humanoid(once, ["clap"], 120)
    gltf, _blob = _loaded(twice)
    names = [node.name for node in gltf.nodes]
    assert all(names.count(name) == 1 for name in BONE_NAMES)
    assert sum(1 for name in names if name and name.startswith("previous:")) == len(BONE_NAMES)
    reachable = set()

    def walk(index):
        reachable.add(index)
        for child in gltf.nodes[index].children or []:
            walk(child)

    for root in gltf.scenes[gltf.scene or 0].nodes:
        walk(root)
    assert not any(gltf.nodes[index].name.startswith("previous:") for index in reachable if gltf.nodes[index].name)
    assert len(gltf.skins) == 1 and [animation.name for animation in gltf.animations] == ["Clap"]


def _spec_skinned_rest(gltf, blob):
    """Skin every skinned primitive the way glTF defines it: the mesh node's own transform is ignored."""
    worlds = _joint_worlds(gltf)
    inverse = _inverse_binds(gltf, blob)
    out = []
    for node in gltf.nodes:
        if node.mesh is None or node.skin is None:
            continue
        assert not node.matrix and not node.translation and not node.rotation and not node.scale
        for primitive in gltf.meshes[node.mesh].primitives:
            positions = _vec3(gltf, blob, primitive.attributes.POSITION).astype(np.float64)
            joints = _vec4(gltf, blob, primitive.attributes.JOINTS_0, np.uint16)
            weights = _vec4(gltf, blob, primitive.attributes.WEIGHTS_0, np.float32).astype(np.float64)
            skinned = np.zeros_like(positions)
            for slot in range(4):
                for joint in np.unique(joints[:, slot]):
                    mask = joints[:, slot] == joint
                    matrix = worlds[int(joint)] @ inverse[int(joint)]
                    skinned[mask] += weights[mask, slot:slot + 1] * (positions[mask] @ matrix[:3, :3].T + matrix[:3, 3])
            out.append(skinned)
    return out


@pytest.mark.parametrize("label,matrix", [
    ("centimetres", np.diag([0.01, 0.01, 0.01, 1.0])),
    ("z_up", np.array([[1.0, 0.0, 0.0, 0.2], [0.0, 0.0, 1.0, 0.0], [0.0, -1.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0]])),
])
def test_a_mesh_under_a_transformed_node_is_skinned_in_world_space(label, matrix):
    item = body("human_a")
    rigged, sidecar = rig_humanoid(as_glb(item, node_matrix=matrix), ["wave"], 120)
    assert sidecar["pose"] == "a", label
    gltf, blob = _loaded(rigged)
    skinned = _spec_skinned_rest(gltf, blob)
    assert len(skinned) == 1 and float(np.abs(skinned[0] - np.asarray(item["positions"])).max()) < 1e-4, label
    assert inspect_glb_bytes(rigged).status == "valid"


def test_a_mesh_used_by_two_nodes_gets_its_own_world_space_copy_per_node():
    from services.humanoid_rig.gltf_export import _iter_primitives
    from services.humanoid_rig.gltf_world import world_space_primitives

    item = body("human_t")
    gltf, blob = _loaded(as_glb(item, instances=2))
    blob = bytearray(blob)
    placed = world_space_primitives(gltf, blob, list(_iter_primitives(gltf)))
    assert len(placed) == 2 and placed[0][1] is not placed[1][1]
    assert len(gltf.meshes) == 3 and gltf.nodes[0].mesh is None and gltf.nodes[1].mesh is None
    for copy, (node_index, primitive) in enumerate(placed):
        node = gltf.nodes[node_index]
        assert not node.matrix and node_index in gltf.scenes[0].nodes
        positions = _vec3(gltf, bytes(blob), primitive.attributes.POSITION)
        assert np.allclose(positions, np.asarray(item["positions"]) + np.array([3.0 * copy, 0.0, 0.0]), atol=1e-5)
    with pytest.raises(NotHumanoid):
        rig_humanoid(as_glb(item, instances=2))


def test_compressed_meshes_are_refused_with_a_clear_message():
    with pytest.raises(ValueError, match="compressed meshes are not supported"):
        rig_humanoid(as_glb(body("human_t"), extensions=["KHR_draco_mesh_compression"]))
