"""Animation files built from our own clips, written the way other tools write them.

``mixamo_like_gltf`` exports a baked clip with ``mixamorig:`` names, bone
frames whose local Y runs along each bone (as Mixamo and Blender do), a Z-up
world facing -Y, and centimetre units under a 0.01 armature. ``cmu_like_bvh``
writes identity rest rotations and ZXY Euler channels. Importing either back
must give the motion we started from.
"""

from __future__ import annotations

import base64
import json

import numpy as np

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.motion import Pose, bake
from services.humanoid_rig.names import BONE_NAMES, BONE_PARENTS
from services.humanoid_rig.clip_recipes import RECIPES

_PARENT = dict(BONE_PARENTS)
_CHILD = {parent: name for name, parent in reversed(BONE_PARENTS) if parent}
# Canonical (left, up, forward) in a Z-up world facing -Y.
Z_UP_FACING_MINUS_Y = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])


def canonical_motion(rig, clip_id: str, bpm: float = 120.0) -> dict:
    """Canonical world rotations, positions and times of one clip on a T-pose rig facing +Z."""
    beats, author = RECIPES[clip_id]
    duration = beats * 60.0 / bpm
    times = np.linspace(0.0, duration, int(np.ceil(duration * 30)) + 1)
    pose = Pose(rig, times / duration)
    author(pose, times / duration)
    local, root = bake(pose)
    positions, worlds = rig.forward(local, root)
    t_pose, _rest = rig.forward(np.broadcast_to(rot.IDENTITY, (1, len(BONE_NAMES), 4)).copy(), rig.root[None])
    return {"times": times, "worlds": worlds, "positions": positions, "t_pose": t_pose[0]}


def mixamo_like_gltf(rig, clip_id: str, frame: np.ndarray = Z_UP_FACING_MINUS_Y, units: float = 100.0) -> dict:
    motion = canonical_motion(rig, clip_id)
    turn = rot.from_matrix(frame)
    rest_pos = (motion["t_pose"] - motion["t_pose"][0]) @ frame.T * units
    rest_frames = [_bone_frame(name, rest_pos, frame) for name in BONE_NAMES]
    worlds = rot.multiply(rot.multiply(turn[None, None], motion["worlds"]), rot.multiply(rot.inverse(turn)[None, None], np.stack(rest_frames)[None]))
    hips = (motion["positions"][:, 0] - motion["t_pose"][0]) @ frame.T * units
    return _document(motion["times"], rest_pos, rest_frames, worlds, hips, units)


def _bone_frame(name: str, rest_pos: np.ndarray, frame: np.ndarray) -> np.ndarray:
    index = BONE_NAMES.index(name)
    child = _CHILD.get(name)
    along = rest_pos[BONE_NAMES.index(child)] - rest_pos[index] if child else frame[:, 1]
    along = along / max(np.linalg.norm(along), 1e-9)
    side = np.cross(frame[:, 2], along)
    side = side if np.linalg.norm(side) > 1e-6 else np.cross(frame[:, 0], along)
    side = side / np.linalg.norm(side)
    return rot.from_matrix(np.stack((side, along, np.cross(side, along)), axis=1))


def _document(times, rest_pos, rest_frames, worlds, hips, units) -> dict:
    nodes = [{"name": "Armature", "scale": [1.0 / units] * 3, "children": [1]}]
    locals_ = np.zeros_like(worlds)
    for index, name in enumerate(BONE_NAMES):
        parent = _PARENT[name]
        parent_world = rest_frames[BONE_NAMES.index(parent)] if parent else rot.IDENTITY
        offset = rest_pos[index] - (rest_pos[BONE_NAMES.index(parent)] if parent else 0.0)
        node = {"name": f"mixamorig:{name}", "translation": rot.rotate(rot.inverse(parent_world), offset).tolist(),
                "rotation": rot.multiply(rot.inverse(parent_world), rest_frames[index]).tolist()}
        children = [BONE_NAMES.index(child) + 1 for child, owner in BONE_PARENTS if owner == name]
        if children:
            node["children"] = children
        nodes.append(node)
        animated_parent = worlds[:, BONE_NAMES.index(parent)] if parent else np.broadcast_to(rot.IDENTITY, worlds[:, 0].shape)
        locals_[:, index] = rot.continuous(rot.multiply(rot.inverse(animated_parent), worlds[:, index]))
    return _pack(nodes, times, locals_, hips + rest_pos[0])


def _pack(nodes, times, locals_, hips) -> dict:
    blobs, accessors, views, channels, samplers = [], [], [], [], []

    def add(array, kind):
        data = np.ascontiguousarray(array, dtype="<f4").tobytes()
        offset = sum(len(item) for item in blobs)
        blobs.append(data)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data)})
        entry = {"bufferView": len(views) - 1, "componentType": 5126, "count": len(array), "type": kind}
        if kind == "SCALAR":
            entry.update(min=[float(array.min())], max=[float(array.max())])
        accessors.append(entry)
        return len(accessors) - 1

    clock = add(times, "SCALAR")
    for index in range(locals_.shape[1]):
        samplers.append({"input": clock, "output": add(locals_[:, index], "VEC4"), "interpolation": "LINEAR"})
        channels.append({"sampler": len(samplers) - 1, "target": {"node": index + 1, "path": "rotation"}})
    samplers.append({"input": clock, "output": add(hips, "VEC3"), "interpolation": "LINEAR"})
    channels.append({"sampler": len(samplers) - 1, "target": {"node": 1, "path": "translation"}})
    blob = b"".join(blobs)
    return {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
        "animations": [{"name": "mixamo.com", "channels": channels, "samplers": samplers}],
        "accessors": accessors, "bufferViews": views,
        "buffers": [{"byteLength": len(blob), "uri": "data:application/octet-stream;base64," + base64.b64encode(blob).decode()}],
    }


def cmu_like_bvh(rig, clip_id: str, units: float = 100.0) -> str:
    """A BVH with identity rests, Y up, facing +Z, centimetres and ZXY channels."""
    motion = canonical_motion(rig, clip_id)
    rest = (motion["t_pose"] - motion["t_pose"][0]) * units
    lines = ["HIERARCHY"]
    _bvh_joint(lines, "Hips", rest, 0)
    worlds = motion["worlds"]
    frames = []
    for frame in range(len(motion["times"])):
        row = list((motion["positions"][frame, 0] - motion["t_pose"][0] + motion["t_pose"][0] * np.array([0, 1, 0])) * units)
        for name in _bvh_order():
            parent = _PARENT[name]
            parent_world = worlds[frame, BONE_NAMES.index(parent)] if parent else rot.IDENTITY
            row += list(_zxy(rot.multiply(rot.inverse(parent_world), worlds[frame, BONE_NAMES.index(name)])))
        frames.append(" ".join(f"{value:.6f}" for value in row))
    lines += ["MOTION", f"Frames: {len(frames)}", f"Frame Time: {motion['times'][1] - motion['times'][0]:.6f}", *frames]
    return "\n".join(lines) + "\n"


def _bvh_order() -> list[str]:
    order = []

    def visit(name):
        order.append(name)
        for child, parent in BONE_PARENTS:
            if parent == name:
                visit(child)

    visit("Hips")
    return order


def _bvh_joint(lines: list[str], name: str, rest: np.ndarray, depth: int) -> None:
    pad = "  " * depth
    parent = _PARENT[name]
    offset = rest[BONE_NAMES.index(name)] - (rest[BONE_NAMES.index(parent)] if parent else 0.0)
    lines.append(f"{pad}{'ROOT' if parent is None else 'JOINT'} {name}")
    lines.append(f"{pad}{{")
    lines.append(f"{pad}  OFFSET {offset[0]:.6f} {offset[1]:.6f} {offset[2]:.6f}")
    channels = "6 Xposition Yposition Zposition Zrotation Xrotation Yrotation" if parent is None else "3 Zrotation Xrotation Yrotation"
    lines.append(f"{pad}  CHANNELS {channels}")
    for child, owner in BONE_PARENTS:
        if owner == name:
            _bvh_joint(lines, child, rest, depth + 1)
    lines.append(f"{pad}}}")


def _zxy(quat: np.ndarray) -> tuple[float, float, float]:
    """Degrees (z, x, y) with R = Rz · Rx · Ry."""
    m = rot.to_matrix(quat)
    x = np.arcsin(np.clip(m[2, 1], -1.0, 1.0))
    z = np.arctan2(-m[0, 1], m[1, 1])
    y = np.arctan2(-m[2, 0], m[2, 2])
    return tuple(float(np.degrees(value)) for value in (z, x, y))


def as_bytes(document: dict) -> bytes:
    return json.dumps(document).encode("utf-8")
