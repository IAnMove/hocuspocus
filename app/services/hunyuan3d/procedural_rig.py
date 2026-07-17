"""Procedural rigging for Maestro's generated GLB meshes.

Adds a crude-but-robust skeleton, linear-blend skinning weights and a small
library of looping animation clips to an existing GLB, editing the file
surgically with pygltflib so materials and extensions (including the PBR
path's KHR_materials_*) survive byte-for-byte.

The skeleton is a single spine chain along the mesh's dominant axis plus a
synthetic root node. Whole-object clips (spin/bounce/breathe) target the
root, so they read correctly on any shape; sway-style clips bend the spine.
"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
from pygltflib import (
    GLTF2,
    Accessor,
    Animation,
    AnimationChannel,
    AnimationChannelTarget,
    AnimationSampler,
    BufferView,
    Node,
    Skin,
)

FLOAT = 5126
UNSIGNED_SHORT = 5123
ARRAY_BUFFER = 34962

MAX_VERTICES = 2_000_000
MAX_INFLUENCES = 4
AXIS_MODES = {"auto", "x", "y", "z"}
RIG_PROFILES = {"prop", "vehicle", "humanoid", "quadruped", "flying", "serpentine"}

# Clip ids exposed through the API; the label becomes the glTF animation name
# that viewers (model-viewer, Blender) display.
CLIPS: dict[str, str] = {
    "idle": "Idle Sway",
    "breathe": "Breathe",
    "hover": "Hover",
    "alert": "Alert Look",
    "walk": "Walk Cycle",
    "run": "Run Cycle",
    "strafe": "Strafe Loop",
    "jump": "Jump",
    "attack": "Attack Lunge",
    "hit": "Hit Reaction",
    "roll": "Combat Roll",
    "charge": "Charge Up",
    "victory": "Victory Jump",
    "bounce": "Bounce",
    "spin": "Turntable Spin",
    "wobble": "Wobble Dance",
}

ProgressFn = Callable[[str, float, str], None]


def _quat_z(angle: float) -> list[float]:
    return [0.0, 0.0, math.sin(angle / 2.0), math.cos(angle / 2.0)]


def _quat_axis(axis: list[float] | np.ndarray, angle: float) -> list[float]:
    direction = np.asarray(axis, dtype=np.float64)
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-9:
        return [0.0, 0.0, 0.0, 1.0]
    direction /= norm
    sine = math.sin(angle / 2.0)
    return [float(direction[0] * sine), float(direction[1] * sine), float(direction[2] * sine), math.cos(angle / 2.0)]


def _quat_x(angle: float) -> list[float]:
    return [math.sin(angle / 2.0), 0.0, 0.0, math.cos(angle / 2.0)]


def _quat_y(angle: float) -> list[float]:
    return [0.0, math.sin(angle / 2.0), 0.0, math.cos(angle / 2.0)]


def _quat_mul(a: list[float], b: list[float]) -> list[float]:
    """Hamilton product a⊗b for [x, y, z, w] quaternions."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ]


def _quat_to_matrix(q: list[float]) -> np.ndarray:
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], dtype=np.float64)


def _node_local_matrix(node: Node) -> np.ndarray:
    if node.matrix:
        # glTF stores matrices column-major.
        return np.array(node.matrix, dtype=np.float64).reshape(4, 4).T
    matrix = np.eye(4)
    if node.scale:
        matrix[:3, :3] = np.diag(node.scale)
    if node.rotation:
        matrix[:3, :3] = _quat_to_matrix(node.rotation) @ matrix[:3, :3]
    if node.translation:
        matrix[:3, 3] = node.translation
    return matrix


def _global_matrices(gltf: GLTF2) -> dict[int, np.ndarray]:
    """Global transform per node index, walking the active scene."""
    result: dict[int, np.ndarray] = {}
    scene_index = gltf.scene or 0
    if not gltf.scenes:
        return result

    def walk(index: int, parent: np.ndarray) -> None:
        node = gltf.nodes[index]
        matrix = parent @ _node_local_matrix(node)
        result[index] = matrix
        for child in node.children or []:
            walk(child, matrix)

    for root in gltf.scenes[scene_index].nodes or []:
        walk(root, np.eye(4))
    return result


def _read_vec3_accessor(gltf: GLTF2, blob: bytes, accessor_index: int) -> np.ndarray:
    accessor = gltf.accessors[accessor_index]
    if accessor.componentType != FLOAT or accessor.type != "VEC3":
        raise ValueError("POSITION accessor must be float32 VEC3")
    view = gltf.bufferViews[accessor.bufferView]
    offset = (view.byteOffset or 0) + (accessor.byteOffset or 0)
    stride = view.byteStride or 12
    if stride == 12:
        return np.frombuffer(blob, dtype="<f4", count=accessor.count * 3, offset=offset).reshape(-1, 3)
    needed = stride * (accessor.count - 1) + 12
    raw = np.frombuffer(blob, dtype=np.uint8, count=needed, offset=offset)
    gather = np.arange(accessor.count)[:, None] * stride + np.arange(12)[None, :]
    return raw[gather].copy().view("<f4").reshape(accessor.count, 3)


def _append_accessor(
    gltf: GLTF2,
    blob: bytearray,
    data: np.ndarray,
    component_type: int,
    type_str: str,
    *,
    target: int | None = None,
    minmax: bool = False,
) -> int:
    while len(blob) % 4:
        blob.append(0)
    payload = np.ascontiguousarray(data).tobytes()
    view = BufferView(buffer=0, byteOffset=len(blob), byteLength=len(payload))
    if target is not None:
        view.target = target
    blob.extend(payload)
    gltf.bufferViews.append(view)
    components = {"SCALAR": 1, "VEC3": 3, "VEC4": 4, "MAT4": 16}[type_str]
    count = data.size // components
    accessor = Accessor(
        bufferView=len(gltf.bufferViews) - 1,
        componentType=component_type,
        count=count,
        type=type_str,
    )
    if minmax:
        flat = data.reshape(count, components)
        accessor.min = [float(value) for value in flat.min(axis=0)]
        accessor.max = [float(value) for value in flat.max(axis=0)]
    gltf.accessors.append(accessor)
    return len(gltf.accessors) - 1


def _principal_axis(world_verts: np.ndarray) -> np.ndarray:
    """Return a stable dominant PCA direction for elongated meshes."""
    centered = world_verts - world_verts.mean(axis=0)
    sample = centered[:: max(1, len(centered) // 50_000)]
    _, vectors = np.linalg.eigh(np.cov(sample.T))
    axis = vectors[:, -1]
    dominant_component = int(np.argmax(np.abs(axis)))
    if axis[dominant_component] < 0:
        axis = -axis
    return axis


def _perpendicular_sway_axis(chain_axis: list[float] | np.ndarray) -> np.ndarray:
    """Keep bending perpendicular to the chain instead of twisting along it."""
    direction = np.asarray(chain_axis, dtype=np.float64)
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-9:
        return np.array([0.0, 0.0, 1.0])
    direction /= norm
    for preferred in (np.array([0.0, 0.0, 1.0]), np.array([1.0, 0.0, 0.0])):
        projected = preferred - direction * float(preferred @ direction)
        projected_norm = float(np.linalg.norm(projected))
        if projected_norm > 1e-6:
            return projected / projected_norm
    return np.array([0.0, 1.0, 0.0])


def _subtree_has_content(gltf: GLTF2, index: int) -> bool:
    node = gltf.nodes[index]
    if node.mesh is not None or node.camera is not None:
        return True
    return any(_subtree_has_content(gltf, child) for child in node.children or [])


def strip_existing_rig(gltf: GLTF2) -> bool:
    """Remove a previous rig (skins, weights, clips, skeleton roots) in place.

    Re-rigging always applies to the base geometry: without this, a second
    pass would layer new skins over stale JOINTS_0/WEIGHTS_0 data and
    duplicate clip names. Orphaned accessor bytes are left in the buffer
    (compacting would mean rewriting every bufferView), which is an accepted
    size cost for the uncommon re-rig path.
    """
    changed = False
    if gltf.animations:
        gltf.animations = []
        changed = True
    if gltf.skins:
        gltf.skins = []
        changed = True
    for node in gltf.nodes:
        if node.skin is not None:
            node.skin = None
            changed = True
    for mesh in gltf.meshes:
        for primitive in mesh.primitives:
            for attribute in ("JOINTS_0", "WEIGHTS_0", "JOINTS_1", "WEIGHTS_1"):
                if getattr(primitive.attributes, attribute, None) is not None:
                    setattr(primitive.attributes, attribute, None)
                    changed = True
    # Drop pure-skeleton scene roots (Rig_Root chains, imported armatures):
    # they render nothing but would otherwise accumulate across re-rigs.
    for scene in gltf.scenes or []:
        if not scene.nodes:
            continue
        kept = [index for index in scene.nodes if _subtree_has_content(gltf, index)]
        if kept != scene.nodes:
            scene.nodes = kept
            changed = True
    return changed


def strip_rig_to_file(source: str, destination: str) -> bool:
    """Write a rig-free copy of `source`; returns whether anything was removed."""
    gltf = GLTF2().load_binary(source)
    changed = strip_existing_rig(gltf)
    if changed:
        gltf.save_binary(destination)
    return changed


def _profile_bin_edges(low: float, high: float, count: int, rig_profile: str) -> np.ndarray:
    """Profile-aware spacing for the same honest single-chain skeleton."""
    normalized = np.linspace(0.0, 1.0, count + 1)
    if rig_profile == "humanoid":
        # Slightly denser toward the base/hips of an upright character.
        normalized = np.power(normalized, 1.18)
    elif rig_profile == "quadruped":
        # Extra articulation toward both ends (head/tail) of a long body.
        normalized = 0.5 - 0.5 * np.cos(math.pi * normalized)
    elif rig_profile == "flying":
        # Keep a little more control toward the leading end of a light rig.
        normalized = np.power(normalized, 0.88)
    return low + (high - low) * normalized


def _build_skeleton(
    world_verts: np.ndarray,
    spine_joints: int,
    axis_mode: str = "auto",
    rig_profile: str = "prop",
) -> dict[str, Any]:
    mins = world_verts.min(axis=0)
    maxs = world_verts.max(axis=0)
    extents = maxs - mins
    if axis_mode != "auto":
        axis = np.eye(3, dtype=np.float64)[{"x": 0, "y": 1, "z": 2}[axis_mode]]
    else:
        # Humanoids strongly prefer glTF's natural Y-up body axis. Creature,
        # flying and serpentine profiles deliberately follow their dominant
        # shape direction so horizontally oriented assets do not stand up.
        upright_threshold = 0.45 if rig_profile == "humanoid" else 0.6
        prefers_upright = rig_profile in {"prop", "humanoid"}
        if prefers_upright and extents[1] >= upright_threshold * float(extents.max()):
            axis = np.array([0.0, 1.0, 0.0])
        else:
            axis = _principal_axis(world_verts)

    projection = world_verts @ axis
    low, high = float(projection.min()), float(projection.max())
    edges = _profile_bin_edges(low, high, spine_joints, rig_profile)
    joints: list[np.ndarray | None] = []
    for i in range(spine_joints):
        mask = (projection >= edges[i]) & (projection <= edges[i + 1])
        bin_center = (edges[i] + edges[i + 1]) / 2.0
        if not mask.any():
            joints.append(None)
            continue
        centroid = world_verts[mask].mean(axis=0)
        centroid = centroid + (bin_center - float(centroid @ axis)) * axis
        joints.append(centroid)

    # Interpolate through empty bins (thin necks, floaters).
    known = [i for i, joint in enumerate(joints) if joint is not None]
    if not known:
        raise ValueError("Mesh has no usable geometry for a skeleton")
    for i, joint in enumerate(joints):
        if joint is not None:
            continue
        before = max((k for k in known if k < i), default=known[0])
        after = min((k for k in known if k > i), default=known[-1])
        if before == after:
            joints[i] = joints[before]
        else:
            t = (i - before) / (after - before)
            joints[i] = joints[before] * (1 - t) + joints[after] * t
    joint_positions = np.array([joint for joint in joints], dtype=np.float64)

    root = joint_positions[0] - (float(joint_positions[0] @ axis) - low) * axis
    return {
        "axis": axis,
        "joints": joint_positions,
        "root": root,
        "height": high - low,
        "diagonal": float(np.linalg.norm(extents)),
    }


def _compute_weights(world_verts: np.ndarray, skeleton: dict[str, Any], weight_falloff: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    joints = skeleton["joints"]
    axis = skeleton["axis"]
    count = len(joints)
    # Bone j runs from joint j to the next joint (the last one extends to the
    # top of the mesh) so weights spread smoothly along the chain.
    tip = joints[-1] + axis * max(skeleton["height"] / max(count, 1), 1e-6)
    ends = np.vstack([joints[1:], tip[None, :]])
    epsilon = max(1e-3 * skeleton["diagonal"], 1e-8)

    distances = np.empty((len(world_verts), count), dtype=np.float64)
    for j in range(count):
        start, end = joints[j], ends[j]
        segment = end - start
        length_sq = float(segment @ segment)
        if length_sq < 1e-12:
            distances[:, j] = np.linalg.norm(world_verts - start, axis=1)
            continue
        t = np.clip(((world_verts - start) @ segment) / length_sq, 0.0, 1.0)
        closest = start[None, :] + t[:, None] * segment[None, :]
        distances[:, j] = np.linalg.norm(world_verts - closest, axis=1)

    raw = 1.0 / (np.power(distances, weight_falloff) + epsilon**weight_falloff)
    influences = min(MAX_INFLUENCES, count)
    order = np.argsort(-raw, axis=1)[:, :influences]
    top = np.take_along_axis(raw, order, axis=1)
    top = top / top.sum(axis=1, keepdims=True)

    joints_out = np.zeros((len(world_verts), 4), dtype=np.uint16)
    weights_out = np.zeros((len(world_verts), 4), dtype=np.float32)
    joints_out[:, :influences] = order.astype(np.uint16)
    weights_out[:, :influences] = top.astype(np.float32)
    return joints_out, weights_out


def _add_sampler(
    gltf: GLTF2,
    blob: bytearray,
    animation: Animation,
    times: np.ndarray,
    values: np.ndarray,
    node_index: int,
    path: str,
) -> None:
    input_accessor = _append_accessor(gltf, blob, times.astype(np.float32), FLOAT, "SCALAR", minmax=True)
    type_str = "VEC4" if path == "rotation" else "VEC3"
    output_accessor = _append_accessor(gltf, blob, values.astype(np.float32), FLOAT, type_str)
    animation.samplers.append(AnimationSampler(input=input_accessor, output=output_accessor, interpolation="LINEAR"))
    animation.channels.append(AnimationChannel(
        sampler=len(animation.samplers) - 1,
        target=AnimationChannelTarget(node=node_index, path=path),
    ))


def _build_clip(
    gltf: GLTF2,
    blob: bytearray,
    clip_id: str,
    target: dict[str, Any],
) -> None:
    """Bake one clip onto a rig described by `target`:

    - root_index / chain_indices: node indices (root + a joint chain).
    - root_translation / root_rotation / root_scale: the root's bind TRS —
      channel values compose with these so non-identity binds (UniRig
      skeletons) keep their pose.
    - chain_rotations: bind rotation per chain node.
    - height: characteristic size used to scale motion amplitudes.
    """
    animation = Animation(name=CLIPS[clip_id], channels=[], samplers=[])
    height = max(float(target["height"]), 1e-6)
    root_index = target["root_index"]
    chain = target["chain_indices"]
    root_translation = np.asarray(target["root_translation"], dtype=np.float64)
    root_rotation = target.get("root_rotation") or [0.0, 0.0, 0.0, 1.0]
    root_scale = np.asarray(target.get("root_scale") or [1.0, 1.0, 1.0], dtype=np.float64)
    chain_rotations = target.get("chain_rotations") or [[0.0, 0.0, 0.0, 1.0]] * len(chain)
    sway_axis = target.get("sway_axis")
    if sway_axis is None:
        sway_axis = [0.0, 0.0, 1.0]
    count = len(chain)

    def timeline(duration: float, per_second: int = 12) -> np.ndarray:
        samples = max(2, int(duration * per_second) + 1)
        return np.linspace(0.0, duration, samples)

    def chain_sway(times: np.ndarray, period: float, base_deg: float, tip_deg: float, phase_step: float) -> None:
        for i, node_index in enumerate(chain):
            amplitude = math.radians(base_deg + (tip_deg - base_deg) * (i / max(count - 1, 1)))
            phase = i * phase_step
            bind = chain_rotations[i]
            # Local-space delta: rotate within the bone's own frame.
            quats = np.array([
                _quat_mul(bind, _quat_axis(sway_axis, amplitude * math.sin(2 * math.pi * t / period + phase)))
                for t in times
            ])
            _add_sampler(gltf, blob, animation, times, quats, node_index, "rotation")

    def root_yaw(times: np.ndarray, angles: list[float]) -> np.ndarray:
        # Parent-space delta: spins stay upright even when the root's bind
        # rotation tilts the skeleton.
        return np.array([_quat_mul(_quat_y(angle), root_rotation) for angle in angles])

    def root_euler(
        times: np.ndarray,
        x_angles: np.ndarray | None = None,
        y_angles: np.ndarray | None = None,
        z_angles: np.ndarray | None = None,
    ) -> np.ndarray:
        """Compose parent-space Euler deltas with a non-identity bind pose."""
        zeros = np.zeros(len(times), dtype=np.float64)
        xs = zeros if x_angles is None else x_angles
        ys = zeros if y_angles is None else y_angles
        zs = zeros if z_angles is None else z_angles
        result = []
        for x_angle, y_angle, z_angle in zip(xs, ys, zs):
            delta = _quat_mul(_quat_y(float(y_angle)), _quat_x(float(x_angle)))
            delta = _quat_mul(delta, _quat_z(float(z_angle)))
            result.append(_quat_mul(delta, root_rotation))
        return np.asarray(result)

    if clip_id == "idle":
        times = timeline(3.0)
        chain_sway(times, period=3.0, base_deg=4.0, tip_deg=10.0, phase_step=0.5)
    elif clip_id == "breathe":
        times = timeline(2.5)
        wave = 0.03 * np.sin(2 * math.pi * times / 2.5)
        scales = np.stack([1.0 + wave, 1.0 - 0.66 * wave, 1.0 + wave], axis=1) * root_scale[None, :]
        _add_sampler(gltf, blob, animation, times, scales, root_index, "scale")
    elif clip_id == "hover":
        duration = 3.0
        times = timeline(duration, per_second=18)
        phase = 2 * math.pi * times / duration
        translations = np.tile(root_translation, (len(times), 1))
        translations[:, 1] += 0.045 * height * np.sin(phase)
        _add_sampler(gltf, blob, animation, times, translations, root_index, "translation")
        tilts = math.radians(3.0) * np.sin(phase + math.pi / 2)
        _add_sampler(gltf, blob, animation, times, root_euler(times, z_angles=tilts), root_index, "rotation")
        chain_sway(times, period=duration, base_deg=2.0, tip_deg=6.0, phase_step=0.35)
    elif clip_id == "alert":
        duration = 2.4
        times = timeline(duration, per_second=18)
        phase = 2 * math.pi * times / duration
        yaw = np.radians(12.0) * np.sin(phase)
        lean = np.radians(3.0) * (1 - np.cos(phase)) * .5
        _add_sampler(gltf, blob, animation, times, root_euler(times, x_angles=lean, y_angles=yaw), root_index, "rotation")
        chain_sway(times, period=duration, base_deg=2.0, tip_deg=8.0, phase_step=.25)
    elif clip_id == "walk":
        duration = 1.0
        times = timeline(duration, per_second=24)
        phase = 2 * math.pi * times / duration
        translations = np.tile(root_translation, (len(times), 1))
        translations[:, 1] += .024 * height * (.5 - .5 * np.cos(phase * 2))
        _add_sampler(gltf, blob, animation, times, translations, root_index, "translation")
        yaw = np.radians(3.5) * np.sin(phase)
        _add_sampler(gltf, blob, animation, times, root_euler(times, y_angles=yaw), root_index, "rotation")
        chain_sway(times, period=duration, base_deg=7.0, tip_deg=14.0, phase_step=.65)
    elif clip_id == "run":
        duration = .64
        times = timeline(duration, per_second=30)
        phase = 2 * math.pi * times / duration
        lift = .052 * height * np.abs(np.sin(phase))
        translations = np.tile(root_translation, (len(times), 1))
        translations[:, 1] += lift
        _add_sampler(gltf, blob, animation, times, translations, root_index, "translation")
        normalized = lift / max(float(lift.max()), 1e-9)
        scales = np.stack([1.035 - .035 * normalized, .94 + .06 * normalized, 1.035 - .035 * normalized], axis=1) * root_scale[None, :]
        _add_sampler(gltf, blob, animation, times, scales, root_index, "scale")
        yaw = np.radians(5.0) * np.sin(phase)
        _add_sampler(gltf, blob, animation, times, root_euler(times, y_angles=yaw), root_index, "rotation")
        chain_sway(times, period=duration, base_deg=11.0, tip_deg=20.0, phase_step=.75)
    elif clip_id == "strafe":
        duration = 1.2
        times = timeline(duration, per_second=24)
        phase = 2 * math.pi * times / duration
        translations = np.tile(root_translation, (len(times), 1))
        translations[:, 0] += .075 * height * np.sin(phase)
        translations[:, 1] += .018 * height * (.5 - .5 * np.cos(phase * 2))
        _add_sampler(gltf, blob, animation, times, translations, root_index, "translation")
        lean = np.radians(-9.0) * np.sin(phase)
        _add_sampler(gltf, blob, animation, times, root_euler(times, z_angles=lean), root_index, "rotation")
        chain_sway(times, period=duration, base_deg=5.0, tip_deg=11.0, phase_step=.45)
    elif clip_id == "jump":
        duration = 1.25
        times = timeline(duration, per_second=30)
        normalized = times / duration
        airborne = np.sin(math.pi * normalized) ** 1.25
        translations = np.tile(root_translation, (len(times), 1))
        translations[:, 1] += .22 * height * airborne
        _add_sampler(gltf, blob, animation, times, translations, root_index, "translation")
        scales = np.stack([1.0 - .045 * airborne, 1.0 + .09 * airborne, 1.0 - .045 * airborne], axis=1) * root_scale[None, :]
        _add_sampler(gltf, blob, animation, times, scales, root_index, "scale")
        pitch = np.radians(-5.0) * np.sin(math.pi * normalized)
        _add_sampler(gltf, blob, animation, times, root_euler(times, x_angles=pitch), root_index, "rotation")
        chain_sway(times, period=duration, base_deg=2.0, tip_deg=8.0, phase_step=.2)
    elif clip_id == "attack":
        duration = .8
        times = timeline(duration, per_second=30)
        normalized = times / duration
        strike = np.sin(math.pi * normalized) ** 2
        translations = np.tile(root_translation, (len(times), 1))
        translations[:, 2] -= .12 * height * strike
        translations[:, 1] += .025 * height * strike
        _add_sampler(gltf, blob, animation, times, translations, root_index, "translation")
        yaw = np.radians(24.0) * np.sin(math.pi * normalized) * np.sin(2 * math.pi * normalized)
        pitch = np.radians(-12.0) * strike
        _add_sampler(gltf, blob, animation, times, root_euler(times, x_angles=pitch, y_angles=yaw), root_index, "rotation")
        chain_sway(times, period=duration, base_deg=8.0, tip_deg=18.0, phase_step=.25)
    elif clip_id == "hit":
        duration = .7
        times = timeline(duration, per_second=30)
        normalized = times / duration
        recoil = np.sin(math.pi * normalized)
        translations = np.tile(root_translation, (len(times), 1))
        translations[:, 0] += .065 * height * recoil
        translations[:, 1] -= .025 * height * recoil
        _add_sampler(gltf, blob, animation, times, translations, root_index, "translation")
        tilt = np.radians(-17.0) * recoil
        _add_sampler(gltf, blob, animation, times, root_euler(times, z_angles=tilt), root_index, "rotation")
        chain_sway(times, period=duration, base_deg=-4.0, tip_deg=-12.0, phase_step=.15)
    elif clip_id == "roll":
        duration = 1.0
        steps = 13
        times = np.linspace(0.0, duration, steps)
        normalized = times / duration
        pitch = 2 * math.pi * normalized
        translations = np.tile(root_translation, (len(times), 1))
        translations[:, 1] += .09 * height * np.sin(math.pi * normalized)
        _add_sampler(gltf, blob, animation, times, translations, root_index, "translation")
        _add_sampler(gltf, blob, animation, times, root_euler(times, x_angles=pitch), root_index, "rotation")
    elif clip_id == "charge":
        duration = 1.6
        times = timeline(duration, per_second=24)
        normalized = times / duration
        pulse = np.sin(2 * math.pi * normalized * 3) * np.sin(math.pi * normalized)
        scales = np.stack([1.0 + .055 * pulse, 1.0 + .08 * pulse, 1.0 + .055 * pulse], axis=1) * root_scale[None, :]
        _add_sampler(gltf, blob, animation, times, scales, root_index, "scale")
        yaw = np.radians(4.0) * pulse
        _add_sampler(gltf, blob, animation, times, root_euler(times, y_angles=yaw), root_index, "rotation")
        chain_sway(times, period=duration / 3, base_deg=2.0, tip_deg=7.0, phase_step=.3)
    elif clip_id == "victory":
        duration = 2.0
        steps = 25
        times = np.linspace(0.0, duration, steps)
        normalized = times / duration
        lift = .13 * height * np.sin(math.pi * normalized) ** 2
        translations = np.tile(root_translation, (len(times), 1))
        translations[:, 1] += lift
        _add_sampler(gltf, blob, animation, times, translations, root_index, "translation")
        yaw = 2 * math.pi * normalized
        _add_sampler(gltf, blob, animation, times, root_euler(times, y_angles=yaw), root_index, "rotation")
        chain_sway(times, period=duration, base_deg=4.0, tip_deg=13.0, phase_step=.4)
    elif clip_id == "bounce":
        times = timeline(1.0, per_second=24)
        lift = 0.10 * height * np.abs(np.sin(math.pi * times / 1.0 * 2.0))
        translations = np.tile(root_translation, (len(times), 1))
        translations[:, 1] += lift
        normalized = lift / lift.max() if lift.max() > 0 else lift
        scales = np.stack([1.04 - 0.04 * normalized, 0.92 + 0.08 * normalized, 1.04 - 0.04 * normalized], axis=1) * root_scale[None, :]
        _add_sampler(gltf, blob, animation, times, translations, root_index, "translation")
        _add_sampler(gltf, blob, animation, times, scales, root_index, "scale")
    elif clip_id == "spin":
        # Quaternion keys every 45° so LINEAR slerp never takes a shortcut.
        steps = 9
        times = np.linspace(0.0, 4.0, steps)
        quats = root_yaw(times, [2 * math.pi * i / (steps - 1) for i in range(steps)])
        _add_sampler(gltf, blob, animation, times, quats, root_index, "rotation")
    elif clip_id == "wobble":
        times = timeline(2.0)
        yaw = root_yaw(times, [math.radians(20.0) * math.sin(2 * math.pi * t / 2.0) for t in times])
        _add_sampler(gltf, blob, animation, times, yaw, root_index, "rotation")
        lift = 0.03 * height * np.abs(np.sin(2 * math.pi * times / 2.0))
        translations = np.tile(root_translation, (len(times), 1))
        translations[:, 1] += lift
        _add_sampler(gltf, blob, animation, times, translations, root_index, "translation")
        chain_sway(times, period=2.0, base_deg=6.0, tip_deg=6.0, phase_step=0.6)
    else:
        raise ValueError(f"Unknown animation clip: {clip_id}")

    gltf.animations.append(animation)


def rig_glb(
    source: str,
    destination: str,
    clip_ids: list[str],
    spine_joints: int = 5,
    axis_mode: str = "auto",
    weight_falloff: float = 2.0,
    progress: ProgressFn | None = None,
    rig_profile: str = "prop",
) -> dict[str, Any]:
    """Rig `source` (a GLB) into `destination` with skeleton + clips.

    Returns a summary dict with the clip names and joint count.
    """
    emit = progress or (lambda phase, value, message: None)
    for clip_id in clip_ids:
        if clip_id not in CLIPS:
            raise ValueError(f"Unknown animation clip: {clip_id}")
    if not clip_ids:
        raise ValueError("Select at least one animation")
    rig_profile = str(rig_profile).strip().lower()
    if rig_profile not in RIG_PROFILES:
        raise ValueError(f"Unknown rig profile: {rig_profile}")
    spine_joints = max(2, min(9, int(spine_joints)))
    axis_mode = str(axis_mode).lower()
    if axis_mode not in AXIS_MODES:
        raise ValueError(f"Unknown skeleton axis: {axis_mode}")
    weight_falloff = max(1.0, min(6.0, float(weight_falloff)))

    emit("loading", 0.1, "Reading GLB")
    gltf = GLTF2().load_binary(source)
    blob = bytearray(gltf.binary_blob())

    # Re-rigging always starts from the base geometry.
    stripped_previous = strip_existing_rig(gltf)
    if stripped_previous:
        emit("loading", 0.18, "Removed the previous rig; re-rigging the base mesh")

    globals_by_node = _global_matrices(gltf)
    mesh_nodes = [index for index, node in enumerate(gltf.nodes) if node.mesh is not None and index in globals_by_node]
    if not mesh_nodes:
        raise ValueError("GLB contains no renderable mesh nodes")

    # Decode every primitive's positions in node-local and world space.
    emit("skeleton", 0.3, "Building skeleton")
    per_node: list[dict[str, Any]] = []
    all_world: list[np.ndarray] = []
    for node_index in mesh_nodes:
        node_global = globals_by_node[node_index]
        mesh = gltf.meshes[gltf.nodes[node_index].mesh]
        primitives = []
        for primitive in mesh.primitives:
            position_index = getattr(primitive.attributes, "POSITION", None)
            if position_index is None:
                continue
            local = _read_vec3_accessor(gltf, bytes(blob), position_index).astype(np.float64)
            world = local @ node_global[:3, :3].T + node_global[:3, 3]
            primitives.append({"primitive": primitive, "world": world})
            all_world.append(world)
        if primitives:
            per_node.append({"node": node_index, "global": node_global, "primitives": primitives})
    if not all_world:
        raise ValueError("GLB has no vertex positions to rig")
    combined = np.vstack(all_world)
    if len(combined) > MAX_VERTICES:
        raise ValueError(f"Mesh too large to rig ({len(combined):,} vertices, limit {MAX_VERTICES:,})")

    skeleton = _build_skeleton(combined, spine_joints, axis_mode, rig_profile)

    # Skeleton nodes: Rig_Root -> Spine_0 -> ... -> Spine_{n-1}.
    root_translation = skeleton["root"]
    node_base = len(gltf.nodes)
    root_index = node_base
    spine_indices = list(range(node_base + 1, node_base + 1 + spine_joints))
    gltf.nodes.append(Node(name="Rig_Root", translation=[float(v) for v in root_translation], children=[spine_indices[0]]))
    previous_world = root_translation
    for i, joint_world in enumerate(skeleton["joints"]):
        local = joint_world - previous_world
        children = [spine_indices[i + 1]] if i + 1 < spine_joints else []
        gltf.nodes.append(Node(name=f"Spine_{i}", translation=[float(v) for v in local], children=children or None))
        previous_world = joint_world
    scene = gltf.scenes[gltf.scene or 0]
    scene.nodes = (scene.nodes or []) + [root_index]

    emit("skinning", 0.55, "Computing skin weights")
    for entry in per_node:
        node_global = entry["global"]
        # One skin per mesh node: the spec ignores a skinned node's own
        # transform, so bake it into the inverse bind matrices instead.
        inverse_binds = np.empty((spine_joints, 4, 4), dtype=np.float32)
        for j, joint_world in enumerate(skeleton["joints"]):
            inverse = np.eye(4)
            inverse[:3, 3] = -joint_world
            inverse_binds[j] = (inverse @ node_global).T  # column-major
        ibm_accessor = _append_accessor(gltf, blob, inverse_binds, FLOAT, "MAT4")
        gltf.skins.append(Skin(
            inverseBindMatrices=ibm_accessor,
            skeleton=root_index,
            joints=spine_indices,
            name=f"MaestroRig_{entry['node']}",
        ))
        gltf.nodes[entry["node"]].skin = len(gltf.skins) - 1

        for item in entry["primitives"]:
            joints_data, weights_data = _compute_weights(item["world"], skeleton, weight_falloff)
            joints_accessor = _append_accessor(gltf, blob, joints_data, UNSIGNED_SHORT, "VEC4", target=ARRAY_BUFFER)
            weights_accessor = _append_accessor(gltf, blob, weights_data, FLOAT, "VEC4", target=ARRAY_BUFFER)
            item["primitive"].attributes.JOINTS_0 = joints_accessor
            item["primitive"].attributes.WEIGHTS_0 = weights_accessor

    emit("animating", 0.8, "Baking animation clips")
    clip_target = {
        "root_index": root_index,
        "chain_indices": spine_indices,
        "root_translation": [float(v) for v in root_translation],
        "height": skeleton["height"],
        "sway_axis": [float(value) for value in _perpendicular_sway_axis(skeleton["axis"])],
    }
    for clip_id in clip_ids:
        _build_clip(gltf, blob, clip_id, clip_target)

    emit("export", 0.95, "Writing rigged GLB")
    gltf.set_binary_blob(bytes(blob))
    gltf.buffers[0].byteLength = len(blob)
    gltf.save_binary(destination)
    return {
        "animations": [CLIPS[clip_id] for clip_id in clip_ids],
        "joints": spine_joints,
        "vertices": int(len(combined)),
        "mesh_nodes": len(per_node),
        "rig_profile": rig_profile,
        "axis_mode": axis_mode,
        "weight_falloff": weight_falloff,
        "resolved_axis": [float(value) for value in skeleton["axis"]],
        "replaced_previous_rig": stripped_previous,
    }


def bake_clips_onto_existing_rig(
    source: str,
    destination: str,
    clip_ids: list[str],
    progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Add Maestro's clip library to a GLB that already has a skin.

    Used after UniRig merges its predicted skeleton+weights: the root joint
    receives the whole-object clips and the longest root→leaf joint chain
    plays the sway-style clips. Channel values compose with each joint's
    bind TRS so the predicted pose is preserved.
    """
    emit = progress or (lambda phase, value, message: None)
    for clip_id in clip_ids:
        if clip_id not in CLIPS:
            raise ValueError(f"Unknown animation clip: {clip_id}")
    if not clip_ids:
        raise ValueError("Select at least one animation")

    emit("animating", 0.86, "Baking animation clips onto the AI skeleton")
    gltf = GLTF2().load_binary(source)
    blob = bytearray(gltf.binary_blob())
    if not gltf.skins or not gltf.skins[0].joints:
        raise ValueError("The merged model has no skin — cannot animate")
    joints = list(gltf.skins[0].joints)
    joint_set = set(joints)

    parent_of: dict[int, int] = {}
    for index, node in enumerate(gltf.nodes):
        for child in node.children or []:
            parent_of[child] = index
    roots = [j for j in joints if parent_of.get(j) not in joint_set]
    root_index = roots[0] if roots else joints[0]

    # Longest root→leaf path through joint children = the "spine".
    def longest_chain(index: int) -> list[int]:
        children = [c for c in (gltf.nodes[index].children or []) if c in joint_set]
        best: list[int] = []
        for child in children:
            candidate = longest_chain(child)
            if len(candidate) > len(best):
                best = candidate
        return [index] + best

    chain = longest_chain(root_index)

    globals_by_node = _global_matrices(gltf)
    joint_positions = np.array([
        globals_by_node[j][:3, 3] for j in joints if j in globals_by_node
    ]) if any(j in globals_by_node for j in joints) else np.zeros((1, 3))
    extents = joint_positions.max(axis=0) - joint_positions.min(axis=0)
    height = float(max(extents.max(), 1e-6))

    root_node = gltf.nodes[root_index]
    target = {
        "root_index": root_index,
        "chain_indices": chain,
        "root_translation": list(root_node.translation or [0.0, 0.0, 0.0]),
        "root_rotation": list(root_node.rotation or [0.0, 0.0, 0.0, 1.0]),
        "root_scale": list(root_node.scale or [1.0, 1.0, 1.0]),
        "chain_rotations": [list(gltf.nodes[j].rotation or [0.0, 0.0, 0.0, 1.0]) for j in chain],
        "height": height,
    }
    for clip_id in clip_ids:
        _build_clip(gltf, blob, clip_id, target)

    emit("export", 0.95, "Writing animated GLB")
    gltf.set_binary_blob(bytes(blob))
    gltf.buffers[0].byteLength = len(blob)
    gltf.save_binary(destination)
    return {
        "animations": [CLIPS[clip_id] for clip_id in clip_ids],
        "joints": len(joints),
        "chain_length": len(chain),
    }
