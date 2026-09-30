"""Conservative anatomical loops for an upright, branched UniRig skeleton.

Joint names are not semantic in UniRig. Resolve topology and bind positions;
never call the longest root-to-finger path a humanoid spine. Unsupported
skeletons retain the legacy library with an explicit result warning.
"""
from __future__ import annotations

import numpy as np

SUPPORTED_CLIPS = frozenset({"idle", "walk", "wobble"})


def animation_tempo(value: object = 120) -> float:
    try:
        bpm = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Animation BPM must be between 60 and 180") from exc
    if isinstance(value, bool) or not np.isfinite(bpm) or not 60 <= bpm <= 180:
        raise ValueError("Animation BPM must be between 60 and 180")
    return bpm


def _limb_roles(kind, candidates, chain, positions, hip):
    ordered = sorted(candidates, key=lambda j: positions[chain(j)[-1]][0])
    if not positions[chain(ordered[0])[-1]][0] < positions[hip][0] < positions[chain(ordered[1])[-1]][0]:
        raise ValueError("Expected left and right limb branches")
    result = {}
    for side, branch in zip(("right", "left"), ordered):
        limb = chain(branch)
        if len(limb) < 3:
            raise ValueError("Each limb needs separately articulated upper, lower and end joints")
        if kind == "leg":
            if positions[limb[2]][1] >= positions[hip][1]:
                raise ValueError("Leg joints must descend below the pelvis")
            roles, indices = ("thigh", "knee", "ankle"), limb[:3]
        else:
            roles, indices = ("upper_arm", "elbow", "wrist"), limb[-3:]
        result.update({f"{side}_{role}": index for role, index in zip(roles, indices)})
    return result


def resolve_humanoid(joints: list[int], children: dict[int, list[int]], matrices: dict[int, np.ndarray]) -> dict[str, int]:
    joint_set = set(joints)
    parents = {child: parent for parent, kids in children.items() for child in kids if child in joint_set}
    roots = [joint for joint in joints if parents.get(joint) not in joint_set]
    if len(roots) != 1 or any(j not in matrices for j in joints):
        raise ValueError("A single connected humanoid skin is required")
    positions = {j: matrices[j][:3, 3] for j in joints}
    graph = {j: [c for c in children.get(j, []) if c in joint_set] for j in joints}

    def chain(j: int) -> list[int]:
        result = [j]
        while len(graph[result[-1]]) == 1:
            next_joint = graph[result[-1]][0]
            if next_joint in result:
                raise ValueError("Cyclic skeleton")
            result.append(next_joint)
        return result

    hip_chain = chain(roots[0])
    hip = hip_chain[-1]
    branches = graph[hip]
    if len(branches) != 3:
        raise ValueError("Expected a pelvis with a torso and two legs")
    upward = [j for j in branches if positions[chain(j)[-1]][1] > positions[hip][1]]
    if len(upward) != 1:
        raise ValueError("The skeleton must be upright in Y-up coordinates")
    torso = chain(upward[0])
    chest = torso[-1]
    upper = graph[chest]
    if len(upper) != 3:
        raise ValueError("Expected a chest with neck and two arm branches")
    neck = max(upper, key=lambda j: positions[chain(j)[-1]][1])
    head = chain(neck)[-1]
    if positions[head][1] <= positions[chest][1]:
        raise ValueError("The head must be above the chest")
    rig = {"hips": hip, "spine": torso[0], "chest": chest, "head": head}
    for kind, candidates in (("leg", [j for j in branches if j not in upward]),
                             ("arm", [j for j in upper if j != neck])):
        rig.update(_limb_roles(kind, candidates, chain, positions, hip))
    return rig


def _rotations(bind: list[float], matrix: np.ndarray, world_axis: list[float], angles: np.ndarray) -> np.ndarray:
    # Convert the desired anatomical world axis into each joint's bind space.
    basis = matrix[:3, :3]
    basis = basis / np.linalg.norm(basis, axis=0)
    axis = np.linalg.solve(basis, np.asarray(world_axis, dtype=float))
    axis /= np.linalg.norm(axis)
    delta_xyz = np.sin(angles[:, None] / 2) * axis
    delta_w = np.cos(angles / 2)
    bind = np.asarray(bind, dtype=float)
    xyz = bind[3] * delta_xyz + delta_w[:, None] * bind[:3] + np.cross(bind[:3], delta_xyz)
    w = bind[3] * delta_w - delta_xyz @ bind[:3]
    rotations = np.column_stack((xyz, w))
    return rotations / np.linalg.norm(rotations, axis=1, keepdims=True)


def humanoid_tracks(clip: str, rig: dict[str, int], matrices: dict[int, np.ndarray],
                    rotations: dict[int, list[float]], bpm: float = 120) -> tuple[np.ndarray, list[tuple[int, np.ndarray]]]:
    if clip not in SUPPORTED_CLIPS:
        raise ValueError("Unsupported anatomical clip")
    bpm = animation_tempo(bpm)
    duration = 4.0 if clip == "idle" else 120 / bpm if clip == "walk" else 240 / bpm
    times = np.linspace(0, duration, int(np.ceil(duration * 30)) + 1)
    phase = 2 * np.pi * times / duration
    wave = np.sin(phase)
    tracks: list[tuple[int, np.ndarray]] = []

    def turn(role: str, axis: list[float], angles: np.ndarray) -> None:
        joint = rig[role]
        values = _rotations(rotations[joint], matrices[joint], axis, angles)
        values[-1] = values[0]  # Exact seam, including floating-point rounding.
        tracks.append((joint, values))

    if clip == "idle":
        turn("spine", [0, 1, 0], .015 * wave)
        turn("head", [0, 1, 0], .035 * wave)
        for side, sign in (("left", 1), ("right", -1)):
            turn(f"{side}_upper_arm", [1, 0, 0], sign * .015 * wave)
        return times, tracks

    groove = clip == "wobble"
    turn("hips", [0, 1, 0], (.06 if groove else .025) * wave)
    turn("chest", [0, 1, 0], (-.035 if groove else -.015) * wave)
    for side, sign in (("left", 1), ("right", -1)):
        leg_wave = sign * wave
        flex = np.maximum(0, leg_wave)
        turn(f"{side}_thigh", [1, 0, 0], (.06 if groove else .24) * leg_wave)
        turn(f"{side}_knee", [1, 0, 0], (.12 if groove else .32) * flex)
        turn(f"{side}_ankle", [1, 0, 0], -(.08 if groove else .20) * flex)
        turn(f"{side}_upper_arm", [0, 0, 1] if groove else [1, 0, 0],
             sign * (.10 + .14 * leg_wave) if groove else -.18 * leg_wave)
        turn(f"{side}_elbow", [1, 0, 0], .08 * leg_wave)
        if groove:
            turn(f"{side}_wrist", [0, 1, 0], .12 * leg_wave)
    return times, tracks


def bake_humanoid_clips(gltf, blob, clips, matrices, add_sampler, labels, profile, bpm):
    """Append anatomical clips when supported; report every legacy fallback."""
    from pygltflib import Animation

    summary = {"animation_mode": "body_chain", "articulated_clips": [],
               "humanoid_joints": {}, "animation_warnings": []}
    if profile != "humanoid":
        return set(), summary
    try:
        joints = gltf.skins[0].joints
        if any(gltf.nodes[j].matrix for j in joints):
            raise ValueError("Humanoid animation requires joints with bind TRS")
        rig = resolve_humanoid(joints, {j: n.children or [] for j, n in enumerate(gltf.nodes)}, matrices)
    except ValueError as exc:
        summary["animation_warnings"] = [f"Humanoid mapping unavailable; using body-chain clips: {exc}"]
        return set(), summary
    rotations = {j: gltf.nodes[j].rotation or [0, 0, 0, 1] for j in joints}
    baked = set()
    for clip in clips:
        if clip not in SUPPORTED_CLIPS:
            summary["animation_warnings"].append(f"{labels[clip]} uses the legacy body-chain approximation")
            continue
        times, tracks = humanoid_tracks(clip, rig, matrices, rotations, bpm)
        animation = Animation(name=labels[clip], channels=[], samplers=[])
        for joint, values in tracks:
            add_sampler(gltf, blob, animation, times, values, joint, "rotation")
        gltf.animations.append(animation)
        baked.add(clip)
    summary.update(animation_mode="articulated_humanoid" if baked else "body_chain",
                   articulated_clips=[labels[c] for c in clips if c in baked], humanoid_joints=rig,
                   animation_bpm=bpm)
    return baked, summary
