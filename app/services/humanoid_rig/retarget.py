"""Retarget BVH and glTF/GLB animations onto a standard humanoid rig.

Rotations are not copied: each source bone's *world* rotation change from its
own rest pose is carried onto the target's canonical frame, so a Mixamo export
with bone-aligned local axes, a CMU BVH with identity rests, or a rig facing -Z
in centimetres all land the same way. The source's rest pose may be a T or an
A pose: arm and leg directions are re-aligned per bone. The hips move by the
source's displacement scaled to the target's hip height, forward drift is
removed so clips play in place, and feet keep the source's height above the
floor. Unknown bones are reported and skipped; nothing is downloaded.
"""

from __future__ import annotations

import base64
import json
import math

import numpy as np

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.contacts import foot_contacts
from services.humanoid_rig.errors import InvalidInput
from services.humanoid_rig.gltf_accessors import AccessorError, read_accessor, split_glb
from services.humanoid_rig.motion import Pose, Rig, _euler_locals, lowest_contact
from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES, BONE_PARENTS
from services.humanoid_rig.retarget_names import map_source_bones

FPS = 30
MAX_SECONDS = 120.0
MAX_CLIPS = 24
_PARENT = dict(BONE_PARENTS)
_ALIGN_ARMS = ("Arm", "ForeArm")
# The bone whose rest direction sets each part's alignment.
_ALIGNED_BY = {"Arm": "Arm", "ForeArm": "ForeArm", "Hand": "ForeArm", "UpLeg": "UpLeg", "Leg": "Leg", "Foot": "Leg", "ToeBase": "Leg"}
_FEET = ("LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase")


def retarget_file(payload: bytes, kind: str, rig: Rig, label: str = "Imported") -> list[dict]:
    """Every animation in a .bvh, .glb or .gltf file, baked for ``rig``."""
    source = _parse(payload, kind.lower(), label)
    mapping, warnings = map_source_bones(source["names"], source["parents"])
    clips = []
    for animation in source["animations"][:MAX_CLIPS]:
        clip = _retarget(source, animation, mapping, rig)
        clip["warnings"] = warnings + clip["warnings"]
        clips.append(clip)
    if len(source["animations"]) > MAX_CLIPS:
        clips[-1]["warnings"].append(f"only the first {MAX_CLIPS} animations were imported")
    return clips


def _parse(payload: bytes, kind: str, label: str) -> dict:
    if kind == ".bvh":
        from services.humanoid_rig.bvh import parse_bvh

        return parse_bvh(payload.decode("utf-8-sig", errors="replace"), label)
    try:
        if kind == ".glb":
            document, buffers = split_glb(bytes(payload))
        elif kind == ".gltf":
            document = json.loads(payload.decode("utf-8-sig"))
            buffers = _uri_buffers(document)
        else:
            raise InvalidInput("import file must be .bvh, .glb or .gltf")
        return _gltf_source(document, buffers, label)
    except AccessorError as exc:
        raise InvalidInput(f"unreadable animation file: {exc.reason}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, AttributeError) as exc:
        raise InvalidInput("unreadable animation file: not valid glTF") from exc


def _uri_buffers(document: dict) -> list[bytes]:
    found = []
    for entry in document.get("buffers") or []:
        uri = entry.get("uri") if isinstance(entry, dict) else None
        if not isinstance(uri, str) or not uri.startswith("data:") or "base64," not in uri:
            raise InvalidInput("a .gltf import must embed its buffers; export it as .glb instead")
        found.append(base64.b64decode(uri.split("base64,", 1)[1]))
    return found


def _gltf_source(document: dict, buffers: list[bytes], label: str) -> dict:
    nodes = list(document.get("nodes") or [])
    animations = _gltf_animations(document, buffers, len(nodes), label)
    if not animations:
        raise InvalidInput("the file has no animation")
    return {"names": _joint_names(document, nodes), "parents": _gltf_parents(nodes),
            "rest": [_node_trs(node) for node in nodes], "animations": animations}


def _joint_names(document: dict, nodes: list[dict]) -> list[str]:
    """Node names, keeping only skin joints when the file has a skin, so a mesh called "Head" is not a bone."""
    names = [str(node.get("name") or "") if isinstance(node, dict) else "" for node in nodes]
    joints = {index for skin in document.get("skins") or [] if isinstance(skin, dict)
              for index in skin.get("joints") or [] if isinstance(index, int)}
    if not joints:
        return names
    return [name if index in joints else "" for index, name in enumerate(names)]


def _gltf_parents(nodes: list[dict]) -> list[int | None]:
    """First valid parent of every node."""
    parents: list[int | None] = [None] * len(nodes)
    for index, node in enumerate(nodes):
        for child in node.get("children") or []:
            if isinstance(child, int) and 0 <= child < len(nodes) and parents[child] is None and child != index:
                parents[child] = index
    return parents


def _gltf_animations(document: dict, buffers: list[bytes], count: int, label: str) -> list[dict]:
    found = []
    for number, animation in enumerate(document.get("animations") or []):
        tracks = _gltf_tracks(document, animation, buffers, count)
        if tracks:
            name = animation.get("name") or (label if number == 0 else f"{label} {number + 1}")
            found.append({"name": str(name), "tracks": tracks})
    return found


def _node_trs(node: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if node.get("matrix"):
        matrix = np.asarray(node["matrix"], dtype=np.float64).reshape(4, 4).T
        scale = np.linalg.norm(matrix[:3, :3], axis=0)
        return matrix[:3, 3].copy(), rot.from_matrix(matrix[:3, :3] / np.maximum(scale, 1e-12)), scale
    return (
        np.asarray(node.get("translation") or [0.0, 0.0, 0.0], dtype=np.float64),
        rot.normalize(np.asarray(node.get("rotation") or [0.0, 0.0, 0.0, 1.0], dtype=np.float64)),
        np.asarray(node.get("scale") or [1.0, 1.0, 1.0], dtype=np.float64),
    )


def _gltf_tracks(document: dict, animation: dict, buffers: list[bytes], count: int) -> dict:
    samplers = animation.get("samplers") or []
    tracks: dict = {}
    for channel in animation.get("channels") or []:
        target = channel.get("target") or {}
        node, path = target.get("node"), target.get("path")
        sampler_index = channel.get("sampler")
        if path not in ("rotation", "translation") or not isinstance(node, int) or not 0 <= node < count:
            continue
        if not isinstance(sampler_index, int) or not 0 <= sampler_index < len(samplers):
            raise InvalidInput("animation channel points to a missing sampler")
        tracks.setdefault(node, {})[path] = _sampler_track(document, samplers[sampler_index], buffers)
    return tracks


def _sampler_track(document: dict, sampler, buffers: list[bytes]) -> tuple[np.ndarray, np.ndarray, str]:
    """``(times, values per key, interpolation)``; a cubic spline keeps only its key values."""
    if not isinstance(sampler, dict) or not isinstance(sampler.get("input"), int) or not isinstance(sampler.get("output"), int):
        raise InvalidInput("animation sampler is missing its input or output")
    times = np.asarray(read_accessor(document, sampler["input"], buffers), dtype=np.float64).reshape(-1)
    values = np.asarray(read_accessor(document, sampler["output"], buffers), dtype=np.float64)
    interpolation = str(sampler.get("interpolation") or "LINEAR")
    if not len(times) or values.size % (len(times) * (3 if interpolation == "CUBICSPLINE" else 1)):
        raise InvalidInput("animation sampler keys and values do not match")
    if interpolation == "CUBICSPLINE":
        values = values.reshape(len(times), 3, -1)[:, 1]
    return times, values.reshape(len(times), -1), interpolation


def _retarget(source: dict, animation: dict, mapping: dict, rig: Rig) -> dict:
    times, local_t, local_r, warnings = _sample(source, animation)
    world_r, world_p = _source_fk(source, local_t, local_r)
    rest_r, rest_p = _source_fk(source, np.stack([item[0] for item in source["rest"]])[None], np.stack([item[1] for item in source["rest"]])[None])
    frame = _facing_frame(rest_p[0], mapping)
    canonical = _canonical_worlds(mapping, world_r, rest_r[0], rest_p[0], frame)
    local = _canonical_locals(canonical, rig, len(times))
    root = _root_track(mapping, world_p, rest_p[0], frame, rig, warnings)
    positions, worlds = rig.forward(local, root)
    _keep_feet_height(mapping, world_p, rest_p[0], frame, rig, root, positions, worlds)
    positions, worlds = rig.forward(local, root)
    rotations = rig.to_actual(worlds)
    return {
        "name": animation["name"],
        "times": times,
        "duration": float(times[-1] - times[0]) if len(times) > 1 else 0.0,
        "rotations": {name: rotations[:, index] for index, name in enumerate(BONE_NAMES) if not name.endswith("_End")},
        "hips_translation": root,
        "contacts": foot_contacts(rig, times, positions, worlds, loop=False),
        "warnings": warnings,
    }


def _sample(source: dict, animation: dict):
    tracks = animation["tracks"]
    stamps = [values[0] for paths in tracks.values() for values in paths.values() if len(values[0])]
    start = min(float(item[0]) for item in stamps) if stamps else 0.0
    end = max(float(item[-1]) for item in stamps) if stamps else 0.0
    warnings = []
    if end - start > MAX_SECONDS:
        end = start + MAX_SECONDS
        warnings.append(f"clip cut to its first {int(MAX_SECONDS)} seconds")
    count = max(2, int(math.ceil((end - start) * FPS)) + 1)
    times = np.linspace(start, max(end, start + 1.0 / FPS), count)
    rest_t = np.stack([item[0] for item in source["rest"]])
    rest_r = np.stack([item[1] for item in source["rest"]])
    local_t = np.repeat(rest_t[None], count, axis=0)
    local_r = np.repeat(rest_r[None], count, axis=0)
    for node, paths in tracks.items():
        if "rotation" in paths:
            local_r[:, node] = _sample_rotation(*paths["rotation"], times)
        if "translation" in paths:
            local_t[:, node] = _sample_vectors(*paths["translation"], times)
    return times - start, local_t, local_r, warnings


def _sample_rotation(keys: np.ndarray, values: np.ndarray, interpolation: str, times: np.ndarray) -> np.ndarray:
    values = rot.continuous(rot.normalize(values[:, :4]))
    if len(keys) == 1:
        return np.repeat(values[:1], len(times), axis=0)
    index = np.clip(np.searchsorted(keys, times, side="right") - 1, 0, len(keys) - 2)
    span = np.maximum(keys[index + 1] - keys[index], 1e-9)
    amount = np.clip((times - keys[index]) / span, 0.0, 1.0)
    if interpolation == "STEP":
        amount = np.where(amount >= 1.0, 1.0, 0.0)
    return rot.slerp(values[index], values[index + 1], amount)


def _sample_vectors(keys: np.ndarray, values: np.ndarray, interpolation: str, times: np.ndarray) -> np.ndarray:
    if interpolation == "STEP":
        index = np.clip(np.searchsorted(keys, times, side="right") - 1, 0, len(keys) - 1)
        return values[index, :3]
    return np.stack([np.interp(times, keys, values[:, axis]) for axis in range(3)], axis=1)


def _source_fk(source: dict, local_t: np.ndarray, local_r: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """World rotations ``(F, N, 4)`` and positions ``(F, N, 3)`` of every source node."""
    count, nodes = local_r.shape[:2]
    scales = np.stack([item[2] for item in source["rest"]])
    matrices = np.zeros((count, nodes, 4, 4))
    done = np.zeros(nodes, dtype=bool)
    for index in _ordered(source["parents"]):
        local = np.zeros((count, 4, 4))
        local[:, :3, :3] = rot.to_matrix(local_r[:, index]) * scales[index][None, None, :]
        local[:, :3, 3] = local_t[:, index]
        local[:, 3, 3] = 1.0
        parent = source["parents"][index]
        matrices[:, index] = local if parent is None or not done[parent] else matrices[:, parent] @ local
        done[index] = True
    basis = matrices[:, :, :3, :3]
    basis = basis / np.maximum(np.linalg.norm(basis, axis=-2, keepdims=True), 1e-12)
    return rot.from_matrix(basis), matrices[:, :, :3, 3]


def _ordered(parents: list[int | None]) -> list[int]:
    order, seen = [], set()

    def visit(index: int, trail: set[int]) -> None:
        if index in seen or index in trail:
            return
        parent = parents[index]
        if parent is not None:
            visit(parent, trail | {index})
        seen.add(index)
        order.append(index)

    for index in range(len(parents)):
        visit(index, set())
    return order


def _facing_frame(rest: np.ndarray, mapping: dict) -> np.ndarray:
    """Columns: the source's left, up and forward axes in its own world."""
    up = _pick(rest, mapping, ("Head", "Neck", "Spine2", "Spine1", "Spine")) - rest[mapping["Hips"]]
    left = None
    for pair in (("LeftUpLeg", "RightUpLeg"), ("LeftArm", "RightArm"), ("LeftShoulder", "RightShoulder")):
        if pair[0] in mapping and pair[1] in mapping:
            left = rest[mapping[pair[0]]] - rest[mapping[pair[1]]]
            break
    if left is None or float(np.linalg.norm(up)) < 1e-9:
        raise InvalidInput("the animation skeleton needs hips, a head or spine, and a left and right leg or arm")
    up = up / np.linalg.norm(up)
    left = left - up * float(left @ up)
    left = left / max(float(np.linalg.norm(left)), 1e-12)
    return np.stack((left, up, np.cross(left, up)), axis=1)


def _pick(rest: np.ndarray, mapping: dict, names: tuple[str, ...]) -> np.ndarray:
    for name in names:
        if name in mapping:
            return rest[mapping[name]]
    return rest[mapping["Hips"]]


def _canonical_worlds(mapping: dict, world_r: np.ndarray, rest_r: np.ndarray, rest_p: np.ndarray, frame: np.ndarray) -> dict:
    """Facing-free canonical world rotation per mapped bone: F⁻¹·Δworld·F·G."""
    to_canon = rot.from_matrix(frame.T)
    from_canon = rot.inverse(to_canon)
    found = {}
    for name, node in mapping.items():
        delta = rot.multiply(world_r[:, node], rot.inverse(rest_r[node]))
        canonical = rot.multiply(rot.multiply(to_canon, delta), from_canon)
        found[name] = rot.multiply(canonical, _rest_alignment(name, mapping, rest_p, frame))
    return found


def _rest_alignment(name: str, mapping: dict, rest_p: np.ndarray, frame: np.ndarray) -> np.ndarray:
    """Turns the canonical T direction of an arm or leg bone onto the source's rest direction.

    Hands follow their forearm and feet and toes their shin, as in the target's
    canonical frames, so an A-pose source does not bend the wrists or ankles.
    """
    side = "Left" if name.startswith("Left") else "Right" if name.startswith("Right") else None
    part = _ALIGNED_BY.get(name[len(side):] if side else name)
    child = {"Arm": "ForeArm", "ForeArm": "Hand", "UpLeg": "Leg", "Leg": "Foot"}.get(part)
    if side is None or child is None or f"{side}{part}" not in mapping or f"{side}{child}" not in mapping:
        return rot.IDENTITY.copy()
    direction = frame.T @ (rest_p[mapping[f"{side}{child}"]] - rest_p[mapping[f"{side}{part}"]])
    if part in _ALIGN_ARMS:
        canonical = np.array([1.0 if side == "Left" else -1.0, 0.0, 0.0])
    else:
        canonical = np.array([direction[0], direction[1], 0.0])
    if float(np.linalg.norm(canonical)) < 1e-9 or float(np.linalg.norm(direction)) < 1e-9:
        return rot.IDENTITY.copy()
    return rot.align(canonical, direction)


def _canonical_locals(canonical: dict, rig: Rig, count: int) -> np.ndarray:
    """Local canonical rotations; unmapped bones keep the relaxed stance."""
    neutral = _euler_locals(Pose(rig, np.linspace(0.0, 1.0, count)))
    local = np.zeros_like(neutral)
    worlds = np.zeros_like(neutral)
    for index, name in enumerate(BONE_NAMES):
        parent = _PARENT[name]
        parent_world = np.broadcast_to(rot.IDENTITY, (count, 4)) if parent is None else worlds[:, BONE_BY_NAME[parent]]
        if name in canonical and not name.endswith("_End"):
            worlds[:, index] = canonical[name]
            local[:, index] = rot.multiply(rot.inverse(parent_world), canonical[name])
        else:
            local[:, index] = neutral[:, index]
            worlds[:, index] = rot.multiply(parent_world, neutral[:, index])
    return local


def _hip_scale(mapping: dict, rest_p: np.ndarray, frame: np.ndarray, rig: Rig) -> float:
    """Target hip height over source hip height at rest, both measured down to the same joints."""
    low = [name for name in _FEET if name in mapping] or [name for name in mapping if name != "Hips"]
    height = float(frame[:, 1] @ rest_p[mapping["Hips"]]) - min(float(frame[:, 1] @ rest_p[mapping[name]]) for name in low)
    target = float(rig.rest_positions[0][1]) - min(float(rig.rest_positions[rig.index(name)][1]) for name in low)
    return target / height if height > 1e-9 and target > 1e-9 else 1.0


def _root_track(mapping: dict, world_p: np.ndarray, rest_p: np.ndarray, frame: np.ndarray, rig: Rig, warnings: list[str]) -> np.ndarray:
    """Hips displacement from the first frame, scaled, with forward drift removed."""
    hips = mapping["Hips"]
    moved = (world_p[:, hips] - world_p[:1, hips]) @ frame * _hip_scale(mapping, rest_p, frame, rig)
    drift = moved[-1] - moved[0]
    if abs(float(drift[0])) + abs(float(drift[2])) > rig.leg * 0.25:
        warnings.append("root motion removed so the clip plays in place")
    ramp = np.linspace(0.0, 1.0, len(moved))[:, None]
    moved[:, [0, 2]] -= ramp * drift[None, [0, 2]]
    return rig.root[None] + rot.rotate(rig.facing, moved)


def _keep_feet_height(mapping, world_p, rest_p, frame, rig: Rig, root: np.ndarray, positions, worlds) -> None:
    """The target's lowest foot joint follows the source's, scaled; the clip's lowest contact sits on the floor.

    Both sides use the same joints. A source without toe bones is measured at the ankles, which rise
    when a heel lifts, so comparing them with the target's toes would lift the whole body twice.
    """
    names = [name for name in _FEET if name in mapping]
    if not names:
        return
    source = np.min(world_p[:, [mapping[name] for name in names]] @ frame[:, 1], axis=1)
    target = np.min(positions[:, [BONE_BY_NAME[name] for name in names], 1], axis=1)
    shift = (source - float(source.min())) * _hip_scale(mapping, rest_p, frame, rig) - target
    root[:, 1] += shift + rig.floor - float(np.min(lowest_contact(rig, positions, worlds) + shift))
