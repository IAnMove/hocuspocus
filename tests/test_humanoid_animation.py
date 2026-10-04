import math
from types import SimpleNamespace

import numpy as np
import pytest

from app.services.hunyuan3d.humanoid_animation import (
    animation_tempo, bake_humanoid_clips, humanoid_tracks, resolve_humanoid, rig_seed,
)


def skeleton():
    # Deliberately generic joint identifiers, with a long hand/finger branch.
    children = {0: [1, 5, 8], 1: [2], 2: [3, 11, 15], 3: [4],
                5: [6], 6: [7], 8: [9], 9: [10],
                11: [12], 12: [13], 13: [14], 14: [19, 20],
                15: [16], 16: [17], 17: [18], 18: [21, 22]}
    positions = [(0, 1, 0), (0, 1.2, 0), (0, 1.5, 0), (0, 1.7, 0), (0, 1.9, 0),
                 (.2, 1, 0), (.2, .6, 0), (.2, .1, 0),
                 (-.2, 1, 0), (-.2, .6, 0), (-.2, .1, 0),
                 (.15, 1.5, 0), (.3, 1.45, 0), (.6, 1.2, 0), (.8, 1, 0),
                 (-.15, 1.5, 0), (-.3, 1.45, 0), (-.6, 1.2, 0), (-.8, 1, 0),
                 (.9, 1, 0), (.9, 1.05, 0), (-.9, 1, 0), (-.9, 1.05, 0)]
    matrices = {}
    for j, position in enumerate(positions):
        matrices[j] = np.eye(4)
        matrices[j][:3, 3] = position
    return list(matrices), children, matrices


def test_anatomy_uses_branches_and_positions_instead_of_longest_finger_chain():
    joints, children, matrices = skeleton()
    rig = resolve_humanoid(joints, children, matrices)
    assert (rig['hips'], rig['spine'], rig['chest'], rig['head']) == (0, 1, 2, 4)
    assert (rig['left_upper_arm'], rig['left_elbow'], rig['left_wrist']) == (12, 13, 14)
    assert (rig['right_upper_arm'], rig['right_elbow'], rig['right_wrist']) == (16, 17, 18)
    assert (rig['left_thigh'], rig['left_knee'], rig['left_ankle']) == (5, 6, 7)
    assert (rig['right_thigh'], rig['right_knee'], rig['right_ankle']) == (8, 9, 10)


@pytest.mark.parametrize('clip', ['idle', 'walk', 'wobble'])
def test_loops_rotate_real_limbs_preserve_unit_quaternions_and_close_seam(clip):
    joints, children, matrices = skeleton()
    rig = resolve_humanoid(joints, children, matrices)
    bind = [0, 0, math.sin(.2), math.cos(.2)]
    rotations = {j: bind for j in joints}
    times, tracks = humanoid_tracks(clip, rig, matrices, rotations)
    assert times[0] == 0
    assert times[-1] == {'idle': 4, 'walk': 1, 'wobble': 2}[clip]
    assert {rig['left_upper_arm'], rig['right_upper_arm']} <= {j for j, _ in tracks}
    for _, values in tracks:
        np.testing.assert_allclose(np.linalg.norm(values, axis=1), 1, atol=1e-12)
        np.testing.assert_array_equal(values[0], values[-1])
    if clip != 'wobble':
        for _, values in tracks:
            np.testing.assert_allclose(values[0], bind, atol=1e-12)
    if clip != 'idle':
        by_joint = dict(tracks)
        assert {rig['left_knee'], rig['right_knee'], rig['left_ankle'], rig['right_ankle']} <= by_joint.keys()
        assert not np.allclose(by_joint[rig['left_knee']], by_joint[rig['right_knee']])


def test_world_axis_is_transformed_to_joint_bind_space():
    joints, children, matrices = skeleton()
    rig = resolve_humanoid(joints, children, matrices)
    j = rig['left_thigh']
    # Bind local X points along world Y, local Y along negative world X.
    matrices[j][:3, :3] = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    _, tracks = humanoid_tracks('walk', rig, matrices, {j: [0, 0, 0, 1] for j in joints})
    values = dict(tracks)[j]
    assert np.max(np.abs(values[:, 0])) < 1e-12
    assert np.max(np.abs(values[:, 1])) > .1


@pytest.mark.parametrize('value', [None, 'invalid', float('nan'), float('inf'), 59, 181, True])
def test_invalid_tempo_is_rejected(value):
    with pytest.raises(ValueError, match='BPM'):
        animation_tempo(value)


def test_groove_follows_requested_tempo():
    joints, children, matrices = skeleton()
    rig = resolve_humanoid(joints, children, matrices)
    times, _ = humanoid_tracks('wobble', rig, matrices, {j: [0, 0, 0, 1] for j in joints}, 128)
    assert times[-1] == 240 / 128


def test_zero_seed_is_preserved_and_default_is_reproducible():
    assert rig_seed(0) == 0
    assert rig_seed() == 12345
    with pytest.raises(ValueError, match='seed'):
        rig_seed(True)
    with pytest.raises(ValueError, match='seed'):
        rig_seed(-1)


def test_single_body_chain_is_not_silently_labelled_a_humanoid():
    with pytest.raises(ValueError, match='pelvis'):
        resolve_humanoid([0, 1, 2], {0: [1], 1: [2]}, {j: np.eye(4) for j in range(3)})


def test_articulated_baking_leaves_mesh_skin_and_texture_data_untouched():
    pytest.importorskip('pygltflib')
    joints, children, matrices = skeleton()
    nodes = [SimpleNamespace(children=children.get(j), rotation=None, matrix=None) for j in joints]
    gltf = SimpleNamespace(nodes=nodes, skins=[SimpleNamespace(joints=joints)], animations=[],
                           meshes=object(), materials=object(), images=object(), textures=object())
    original = (gltf.meshes, gltf.materials, gltf.images, gltf.textures, gltf.skins)
    calls = []

    def sampler(_gltf, _blob, animation, times, values, joint, path):
        calls.append((animation.name, joint, path))

    baked, summary = bake_humanoid_clips(gltf, bytearray(), ['idle', 'walk', 'wobble', 'spin'],
                                         matrices, sampler,
                                         {'idle': 'Idle', 'walk': 'Walk', 'wobble': 'Dance', 'spin': 'Spin'},
                                         'humanoid', 120)
    assert baked == {'idle', 'walk', 'wobble'}
    assert summary['animation_mode'] == 'articulated_humanoid'
    assert summary['articulated_clips'] == ['Idle', 'Walk', 'Dance']
    assert summary['animation_warnings'] == ['Spin uses the legacy body-chain approximation']
    assert all(path == 'rotation' for _, _, path in calls)
    assert (gltf.meshes, gltf.materials, gltf.images, gltf.textures, gltf.skins) == original


def test_unsupported_skeleton_publishes_explicit_fallback_warning():
    pytest.importorskip('pygltflib')
    gltf = SimpleNamespace(skins=[SimpleNamespace(joints=[0])],
                           nodes=[SimpleNamespace(children=[], matrix=None)], animations=[])
    baked, summary = bake_humanoid_clips(gltf, bytearray(), ['idle'], {0: np.eye(4)}, None,
                                         {'idle': 'Idle'}, 'humanoid', 120)
    assert not baked
    assert summary['animation_mode'] == 'body_chain'
    assert 'mapping unavailable' in summary['animation_warnings'][0]
    assert gltf.animations == []
