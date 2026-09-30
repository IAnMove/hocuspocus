"""Retarget BVH and glTF clips onto the standard humanoid skeleton.

Rotations are preserved. Only the Hips translation is scaled by
``target_height / source_height``. BVH Euler channels are intrinsic: the
first rotation channel is applied first, each subsequent channel on the right
(Hamilton product, xyzw).

When ``source_height`` is omitted, BVH uses the rest-pose world-Y span,
including End Site offsets and with identity rest rotations. glTF uses the
same span over recognized bone nodes (parent translation chain, identity
rotations). If that glTF span is not positive and the Hips node translation Y
is non-zero, the fallback height is twice that Y value.
"""

from __future__ import annotations

import base64
import json
import math
import struct
from dataclasses import dataclass

import numpy as np

from services.humanoid_rig.names import BONE_BY_NAME, BONE_NAMES

_PREFIXES = ("mixamorig:", "mixamorig_", "Mixamo_")
_CHANNEL_MAP = {
    "Xposition": ("pos", 0),
    "Yposition": ("pos", 1),
    "Zposition": ("pos", 2),
    "Xrotation": ("rot", 0),
    "Yrotation": ("rot", 1),
    "Zrotation": ("rot", 2),
}
_AXES = (
    np.array([1.0, 0.0, 0.0]),
    np.array([0.0, 1.0, 0.0]),
    np.array([0.0, 0.0, 1.0]),
)
_FLOAT = 5126
_TYPE_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
_GLB_MAGIC = 0x46546C67
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
_SPAN_EPSILON = 1e-6


@dataclass
class _Joint:
    name: str
    offset: np.ndarray
    channels: list[tuple[str, int]]
    children: list[_Joint]
    end_site: bool


class _Cursor:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.index = 0

    def peek(self) -> str:
        if self.index >= len(self.tokens):
            return ""
        return self.tokens[self.index]

    def take(self) -> str:
        token = self.peek()
        if not token:
            raise ValueError("unexpected end of bvh")
        self.index += 1
        return token

    def rest(self) -> list[str]:
        remaining = self.tokens[self.index:]
        self.index = len(self.tokens)
        return remaining


def retarget_bvh(
    text: str,
    target_height: float,
    source_height: float | None = None,
) -> dict:
    """Retarget one BVH clip. Missing bones are skipped, not fatal."""
    target = _require_positive(target_height, "target_height")
    root, frames, frame_time, values = _load_bvh(text)
    ordered = _flatten(root)
    recognized, warnings = _classify(ordered)
    if not recognized:
        raise ValueError("no recognized bones")
    height = _resolve_source_height(source_height, _rest_points(root))
    table = _motion_table(values, frames, _stride(ordered))
    times = _frame_times(frames, frame_time)
    scale = target / height
    rotations = _bvh_rotations(ordered, table)
    hips = _bvh_hips(ordered, table, scale, frames)
    return _result(times, rotations, hips, warnings)


def retarget_gltf(
    document: dict,
    target_height: float,
    source_height: float | None = None,
    buffers: list[bytes] | None = None,
) -> dict:
    """Retarget ``animations[0]`` from a glTF JSON document.

    Buffer bytes come from ``buffers`` (index-aligned) or from a
    ``data:`` base64 URI. Any other buffer URI raises ``ValueError``.
    The omitted-``source_height`` fallback is twice the Hips translation Y
    when bone nodes have no positive world-Y span.
    """
    target = _require_positive(target_height, "target_height")
    if not isinstance(document, dict):
        raise ValueError("gltf document")
    nodes = list(document.get("nodes") or [])
    tracks, warnings = _gltf_tracks(document, nodes, buffers)
    height = _gltf_height(source_height, nodes)
    times = _timeline(tracks)
    scale = target / height
    rotations = _rotation_map(tracks, times)
    hips = _gltf_hips(tracks, nodes, times, scale)
    return _result(times, rotations, hips, warnings)


def retarget_glb(
    data: bytes,
    target_height: float,
    source_height: float | None = None,
) -> dict:
    """Split a GLB (JSON chunk + BIN chunk) and retarget it."""
    document, binary = _glb_parts(data)
    buffers = [binary] if binary is not None else []
    return retarget_gltf(document, target_height, source_height, buffers)


def _require_positive(value: float, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(label) from exc
    if not math.isfinite(number) or number <= 0.0:
        raise ValueError(label)
    return number


def _result(times, rotations, hips, warnings) -> dict:
    ordered = _stable_bones(rotations)
    duration = 0.0
    if len(times):
        duration = float(times[-1] - times[0])
    packed = {name: rotations[name] for name in ordered}
    return {
        "times": np.asarray(times, dtype=np.float64),
        "duration": duration,
        "rotations": packed,
        "hips_translation": np.asarray(hips, dtype=np.float64),
        "warnings": list(warnings),
        "bones": ordered,
    }


def _stable_bones(rotations: dict) -> tuple[str, ...]:
    return tuple(name for name in BONE_NAMES if name in rotations)


def _strip_prefix(name: str) -> str:
    for prefix in _PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _canonical_bone(name: str) -> str | None:
    if not name:
        return None
    stripped = _strip_prefix(name)
    if stripped in BONE_BY_NAME:
        return stripped
    return None


def _warn_name(warnings: list[str], name: str) -> None:
    if not name:
        return
    text = f"unrecognized joint {name}"
    if text not in warnings:
        warnings.append(text)


def _span_y(points) -> float:
    if not points:
        return 0.0
    ys = [float(point[1]) for point in points]
    return max(ys) - min(ys)


def _load_bvh(text: str):
    if not isinstance(text, str):
        raise ValueError("bvh text")
    cursor = _Cursor(_tokenize(text))
    _expect(cursor, "HIERARCHY")
    root = _parse_joint(cursor)
    return (root, *_parse_motion(cursor))


def _tokenize(text: str) -> list[str]:
    spaced = text.replace("{", " { ").replace("}", " } ")
    return spaced.split()


def _expect(cursor: _Cursor, token: str) -> None:
    found = cursor.take()
    if found != token:
        raise ValueError(f"expected {token}")


def _parse_joint(cursor: _Cursor) -> _Joint:
    kind = cursor.take()
    name, end_site = _joint_identity(cursor, kind)
    _expect(cursor, "{")
    joint = _Joint(name, np.zeros(3), [], [], end_site)
    _fill_joint(cursor, joint)
    _expect(cursor, "}")
    return joint


def _joint_identity(cursor: _Cursor, kind: str) -> tuple[str, bool]:
    if kind == "End":
        _expect(cursor, "Site")
        return "End Site", True
    if kind not in ("ROOT", "JOINT"):
        raise ValueError("bad joint")
    return cursor.take(), False


def _fill_joint(cursor: _Cursor, joint: _Joint) -> None:
    while cursor.peek() not in ("}", ""):
        _apply_joint_token(cursor, joint)


def _apply_joint_token(cursor: _Cursor, joint: _Joint) -> None:
    word = cursor.peek()
    if word == "OFFSET":
        cursor.take()
        joint.offset = _read_vec3(cursor)
        return
    if word == "CHANNELS":
        cursor.take()
        joint.channels = _read_channels(cursor)
        return
    if word in ("JOINT", "ROOT", "End"):
        joint.children.append(_parse_joint(cursor))
        return
    raise ValueError(f"bad bvh token {word}")


def _read_vec3(cursor: _Cursor) -> np.ndarray:
    return np.array([float(cursor.take()) for _ in range(3)], dtype=np.float64)


def _read_channels(cursor: _Cursor) -> list[tuple[str, int]]:
    count = int(cursor.take())
    if count < 0:
        raise ValueError("bad channels")
    return [_channel_spec(cursor.take()) for _ in range(count)]


def _channel_spec(name: str) -> tuple[str, int]:
    spec = _CHANNEL_MAP.get(name)
    if spec is None:
        raise ValueError(f"unknown channel {name}")
    return spec


def _parse_motion(cursor: _Cursor):
    _expect(cursor, "MOTION")
    _expect(cursor, "Frames:")
    frames = int(cursor.take())
    _expect(cursor, "Frame")
    _expect(cursor, "Time:")
    frame_time = float(cursor.take())
    if frames < 0 or frame_time <= 0.0:
        raise ValueError("bad motion")
    values = [float(token) for token in cursor.rest()]
    return frames, frame_time, np.asarray(values, dtype=np.float64)


def _flatten(root: _Joint) -> list[_Joint]:
    ordered: list[_Joint] = []
    _walk_joints(root, ordered)
    return ordered


def _walk_joints(joint: _Joint, ordered: list[_Joint]) -> None:
    ordered.append(joint)
    for child in joint.children:
        _walk_joints(child, ordered)


def _rest_points(root: _Joint) -> list[np.ndarray]:
    points: list[np.ndarray] = []
    _walk_rest(root, np.zeros(3), points)
    return points


def _walk_rest(joint: _Joint, parent: np.ndarray, points: list[np.ndarray]) -> None:
    world = parent + joint.offset
    points.append(world)
    for child in joint.children:
        _walk_rest(child, world, points)


def _classify(ordered: list[_Joint]):
    recognized = []
    warnings: list[str] = []
    for joint in ordered:
        if joint.end_site:
            continue
        bone = _canonical_bone(joint.name)
        if bone is None:
            _warn_name(warnings, joint.name)
            continue
        recognized.append(bone)
    return recognized, warnings


def _resolve_source_height(given, points) -> float:
    if given is not None:
        return _require_positive(given, "source_height")
    span = _span_y(points)
    if span < _SPAN_EPSILON:
        raise ValueError("source height")
    return span


def _stride(ordered: list[_Joint]) -> int:
    return sum(len(joint.channels) for joint in ordered)


def _motion_table(values: np.ndarray, frames: int, stride: int) -> np.ndarray:
    if int(values.size) != frames * stride:
        raise ValueError("motion length")
    if frames == 0:
        return np.zeros((0, stride), dtype=np.float64)
    return np.asarray(values, dtype=np.float64).reshape(frames, stride)


def _frame_times(frames: int, frame_time: float) -> np.ndarray:
    return np.arange(frames, dtype=np.float64) * float(frame_time)


def _bvh_rotations(ordered: list[_Joint], table: np.ndarray) -> dict:
    rotations = {}
    cursor = 0
    for joint in ordered:
        width = len(joint.channels)
        block = _channel_block(table, cursor, width)
        cursor += width
        _store_bvh_rotation(rotations, joint, block)
    return rotations


def _channel_block(table: np.ndarray, cursor: int, width: int) -> np.ndarray:
    if table.size == 0:
        return np.zeros((0, width), dtype=np.float64)
    return table[:, cursor:cursor + width]


def _store_bvh_rotation(rotations: dict, joint: _Joint, block: np.ndarray) -> None:
    if joint.end_site:
        return
    bone = _canonical_bone(joint.name)
    if bone is None or bone in rotations:
        return
    if not _has_rotation(joint.channels):
        return
    rotations[bone] = _euler_block(joint.channels, block)


def _has_rotation(channels) -> bool:
    for kind, _axis in channels:
        if kind == "rot":
            return True
    return False


def _euler_block(channels, block: np.ndarray) -> np.ndarray:
    rows = [_euler_frame(channels, row) for row in block]
    if not rows:
        return np.zeros((0, 4), dtype=np.float64)
    return np.stack(rows, axis=0)


def _euler_frame(channels, row) -> np.ndarray:
    quat = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)
    for (kind, axis), value in zip(channels, row):
        if kind != "rot":
            continue
        quat = _mul_quat(quat, _axis_quat(axis, float(value)))
    return quat


def _axis_quat(axis: int, degrees: float) -> np.ndarray:
    half = math.radians(degrees) * 0.5
    vector = _AXES[axis]
    scale = math.sin(half)
    return np.array(
        [vector[0] * scale, vector[1] * scale, vector[2] * scale, math.cos(half)],
        dtype=np.float64,
    )


def _mul_quat(left, right) -> np.ndarray:
    lx, ly, lz, lw = (float(item) for item in left)
    rx, ry, rz, rw = (float(item) for item in right)
    return np.array(
        [
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
            lw * rw - lx * rx - ly * ry - lz * rz,
        ],
        dtype=np.float64,
    )


def _bvh_hips(ordered, table, scale: float, frames: int) -> np.ndarray:
    cursor = 0
    for joint in ordered:
        width = len(joint.channels)
        if _canonical_bone(joint.name) == "Hips":
            return _hips_rows(joint, _channel_block(table, cursor, width), scale)
        cursor += width
    return np.zeros((frames, 3), dtype=np.float64)


def _hips_rows(joint: _Joint, block: np.ndarray, scale: float) -> np.ndarray:
    rows = []
    for row in block:
        local = joint.offset + _position_channels(joint.channels, row)
        rows.append(local * scale)
    if not rows:
        return np.zeros((0, 3), dtype=np.float64)
    return np.stack(rows, axis=0)


def _position_channels(channels, row) -> np.ndarray:
    position = np.zeros(3, dtype=np.float64)
    for (kind, axis), value in zip(channels, row):
        if kind == "pos":
            position[axis] = float(value)
    return position


def _gltf_tracks(document, nodes, buffers):
    warnings = _node_warnings(nodes)
    animation = _first_animation(document)
    tracks: dict = {}
    for channel in animation.get("channels") or []:
        _take_channel(document, nodes, animation, channel, buffers, tracks, warnings)
    if not _has_recognized(nodes, tracks):
        raise ValueError("no recognized bones")
    return tracks, warnings


def _first_animation(document: dict) -> dict:
    clips = document.get("animations") or []
    if not clips or not isinstance(clips[0], dict):
        raise ValueError("missing animation")
    return clips[0]


def _node_warnings(nodes) -> list[str]:
    warnings: list[str] = []
    for node in nodes:
        name = node.get("name") or ""
        if not name:
            continue
        if _canonical_bone(name) is None:
            _warn_name(warnings, name)
    return warnings


def _take_channel(document, nodes, animation, channel, buffers, tracks, warnings) -> None:
    path = (channel.get("target") or {}).get("path")
    if path not in ("rotation", "translation"):
        return
    bone, name = _channel_bone(nodes, channel)
    if bone is None:
        _warn_name(warnings, name)
        return
    times, values = _channel_samples(document, animation, channel, buffers, path)
    tracks.setdefault(bone, {})[path] = (times, values)


def _channel_bone(nodes, channel):
    index = (channel.get("target") or {}).get("node")
    if not isinstance(index, int) or index < 0 or index >= len(nodes):
        raise ValueError("bad channel")
    name = nodes[index].get("name") or ""
    return _canonical_bone(name), name


def _channel_samples(document, animation, channel, buffers, path):
    samplers = animation.get("samplers") or []
    sampler_index = channel.get("sampler")
    if not isinstance(sampler_index, int) or not 0 <= sampler_index < len(samplers):
        raise ValueError("bad sampler")
    sampler = samplers[sampler_index]
    if sampler.get("interpolation", "LINEAR") != "LINEAR":
        raise ValueError("unsupported interpolation")
    times = _accessor_array(document, sampler["input"], buffers)
    values = _accessor_array(document, sampler["output"], buffers)
    _check_width(path, values)
    return _sort_keys(times, values)


def _check_width(path: str, values) -> None:
    array = np.asarray(values)
    if array.ndim != 2 or array.shape[1] != _vector_width(path):
        raise ValueError("sampler shape")


def _vector_width(path: str) -> int:
    if path == "rotation":
        return 4
    return 3


def _sort_keys(times, values):
    ordered_times = np.asarray(times, dtype=np.float64).reshape(-1)
    ordered_values = np.asarray(values, dtype=np.float64)
    if ordered_values.shape[0] != ordered_times.shape[0]:
        raise ValueError("sampler length")
    order = np.argsort(ordered_times, kind="mergesort")
    return _dedupe_keys(ordered_times[order], ordered_values[order])


def _dedupe_keys(times, values):
    count = len(times)
    if count == 0:
        return times, values
    keep = np.ones(count, dtype=bool)
    keep[:-1] = times[1:] != times[:-1]
    return times[keep], values[keep]


def _has_recognized(nodes, tracks) -> bool:
    if tracks:
        return True
    for node in nodes:
        if _canonical_bone(node.get("name") or ""):
            return True
    return False


def _gltf_height(source_height, nodes) -> float:
    if source_height is not None:
        return _require_positive(source_height, "source_height")
    hips_y = float(_node_translation_by_bone(nodes, "Hips")[1])
    return _source_height_from_points(_bone_points(nodes), hips_y)


def _source_height_from_points(points, hips_y: float) -> float:
    """Bone-node world-Y span, else twice the Hips node translation Y."""
    span = _span_y(points)
    if span > _SPAN_EPSILON:
        return span
    if abs(hips_y) > _SPAN_EPSILON:
        return abs(hips_y) * 2.0
    raise ValueError("source height")


def _bone_points(nodes) -> list[np.ndarray]:
    points: list[np.ndarray] = []
    if not nodes:
        return points
    seen: set[int] = set()
    for root in _root_indices(nodes):
        _walk_points(nodes, root, np.zeros(3), points, seen)
    return points


def _root_indices(nodes) -> list[int]:
    children = set()
    for node in nodes:
        for child in node.get("children") or []:
            children.add(child)
    return [index for index in range(len(nodes)) if index not in children]


def _walk_points(nodes, index, parent, points, seen) -> None:
    if index in seen or not isinstance(index, int):
        return
    if index < 0 or index >= len(nodes):
        return
    seen.add(index)
    world = parent + _local_translation(nodes[index])
    if _canonical_bone(nodes[index].get("name") or ""):
        points.append(world)
    for child in nodes[index].get("children") or []:
        _walk_points(nodes, child, world, points, seen)


def _local_translation(node) -> np.ndarray:
    raw = node.get("translation")
    if not raw:
        return np.zeros(3, dtype=np.float64)
    return np.asarray(raw, dtype=np.float64)


def _node_translation_by_bone(nodes, bone: str) -> np.ndarray:
    for node in nodes:
        if _canonical_bone(node.get("name") or "") == bone:
            return _local_translation(node)
    return np.zeros(3, dtype=np.float64)


def _timeline(tracks: dict) -> np.ndarray:
    pieces = []
    for paths in tracks.values():
        for times, _values in paths.values():
            if len(times):
                pieces.append(np.asarray(times, dtype=np.float64))
    if not pieces:
        return np.zeros(1, dtype=np.float64)
    return np.unique(np.concatenate(pieces))


def _rotation_map(tracks: dict, times: np.ndarray) -> dict:
    rotations = {}
    for bone, paths in tracks.items():
        pair = paths.get("rotation")
        if pair is None:
            continue
        rotations[bone] = _sample_rotations(pair[0], pair[1], times)
    return rotations


def _sample_rotations(times_in, values, times_out) -> np.ndarray:
    out = np.empty((len(times_out), 4), dtype=np.float64)
    for index, moment in enumerate(times_out):
        out[index] = _rotation_at(times_in, values, float(moment))
    return out


def _rotation_at(times_in, values, moment: float) -> np.ndarray:
    if len(times_in) == 0:
        return np.array([0.0, 0.0, 0.0, 1.0])
    if moment <= float(times_in[0]) or moment >= float(times_in[-1]):
        return _endpoint_quat(times_in, values, moment)
    upper = int(np.searchsorted(times_in, moment, side="right"))
    return _blend_rotation(times_in, values, upper - 1, moment)


def _endpoint_quat(times_in, values, moment: float) -> np.ndarray:
    if moment <= float(times_in[0]):
        return np.asarray(values[0], dtype=np.float64)
    return np.asarray(values[-1], dtype=np.float64)


def _blend_rotation(times_in, values, lower: int, moment: float) -> np.ndarray:
    start = float(times_in[lower])
    end = float(times_in[lower + 1])
    span = end - start
    if span <= 1e-12:
        return np.asarray(values[lower], dtype=np.float64)
    alpha = (moment - start) / span
    return _slerp(values[lower], values[lower + 1], alpha)


def _slerp(start, end, alpha: float) -> np.ndarray:
    left = np.asarray(start, dtype=np.float64)
    right = np.asarray(end, dtype=np.float64)
    dot = float(np.dot(left, right))
    if dot < 0.0:
        right = -right
        dot = -dot
    if dot > 0.9995:
        return _normalize(left + alpha * (right - left))
    theta = math.acos(min(1.0, dot))
    scale = math.sin(theta)
    w0 = math.sin((1.0 - alpha) * theta) / scale
    w1 = math.sin(alpha * theta) / scale
    return w0 * left + w1 * right


def _normalize(quat: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(quat))
    if length <= 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0])
    return quat / length


def _gltf_hips(tracks, nodes, times, scale: float) -> np.ndarray:
    pair = tracks.get("Hips", {}).get("translation")
    if pair is None:
        local = _node_translation_by_bone(nodes, "Hips")
        return np.tile(local * scale, (len(times), 1))
    return _sample_translation(pair[0], pair[1], times) * scale


def _sample_translation(times_in, values, times_out) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim == 1:
        array = array.reshape(-1, 1)
    if len(times_in) == 0:
        return np.zeros((len(times_out), array.shape[1]), dtype=np.float64)
    return _lerp_columns(times_in, array, times_out)


def _lerp_columns(times_in, values, times_out) -> np.ndarray:
    width = values.shape[1]
    out = np.empty((len(times_out), width), dtype=np.float64)
    for column in range(width):
        out[:, column] = np.interp(times_out, times_in, values[:, column])
    return out


def _accessor_array(document, index, buffers) -> np.ndarray:
    accessor = _accessor_entry(document, index)
    if int(accessor.get("componentType", 0)) != _FLOAT:
        raise ValueError("unsupported accessor")
    width = _TYPE_WIDTH.get(accessor.get("type"))
    if width is None:
        raise ValueError("unsupported accessor")
    blob, start = _accessor_span(document, accessor, buffers)
    return _floats_at(blob, start, int(accessor["count"]), width)


def _accessor_entry(document, index) -> dict:
    entries = document.get("accessors") or []
    if not isinstance(index, int) or index < 0 or index >= len(entries):
        raise ValueError("missing accessor")
    entry = entries[index]
    if not isinstance(entry, dict):
        raise ValueError("missing accessor")
    return entry


def _accessor_span(document, accessor, buffers):
    view_index = accessor.get("bufferView")
    views = document.get("bufferViews") or []
    if not isinstance(view_index, int) or view_index < 0 or view_index >= len(views):
        raise ValueError("missing buffer view")
    view = views[view_index]
    if not isinstance(view, dict):
        raise ValueError("missing buffer view")
    blob = _resolve_buffer(document, int(view.get("buffer", 0)), buffers)
    start = int(view.get("byteOffset") or 0) + int(accessor.get("byteOffset") or 0)
    return blob, start


def _resolve_buffer(document, buffer_index: int, buffers) -> bytes:
    provided = _provided_buffer(buffers, buffer_index)
    if provided is not None:
        return provided
    return _buffer_from_uri(_buffer_entry(document, buffer_index))


def _provided_buffer(buffers, index: int):
    if not buffers or index < 0 or index >= len(buffers):
        return None
    return buffers[index]


def _buffer_entry(document, index: int) -> dict:
    entries = document.get("buffers") or []
    if index < 0 or index >= len(entries) or not isinstance(entries[index], dict):
        raise ValueError("missing buffer")
    return entries[index]


def _buffer_from_uri(entry: dict) -> bytes:
    uri = entry.get("uri")
    if not isinstance(uri, str):
        raise ValueError("missing buffer")
    if uri.startswith("data:"):
        return _data_uri_bytes(uri)
    raise ValueError("external uri")


def _data_uri_bytes(uri: str) -> bytes:
    marker = "base64,"
    at = uri.find(marker)
    if at < 0:
        raise ValueError("data uri")
    payload = uri[at + len(marker):]
    try:
        return base64.b64decode(payload, validate=False)
    except ValueError as exc:
        raise ValueError("data uri") from exc


def _floats_at(blob, start: int, count: int, width: int) -> np.ndarray:
    if count < 0 or start < 0:
        raise ValueError("truncated accessor")
    nbytes = count * width * 4
    raw = bytes(blob[start:start + nbytes])
    if len(raw) != nbytes:
        raise ValueError("truncated accessor")
    data = np.frombuffer(raw, dtype="<f4").astype(np.float64)
    if width == 1:
        return data
    return data.reshape(count, width)


def _glb_parts(data: bytes):
    try:
        return _read_glb_chunks(_glb_header(data))
    except json.JSONDecodeError as exc:
        raise ValueError("glb") from exc


def _glb_header(data: bytes) -> bytes:
    if not isinstance(data, (bytes, bytearray)) or len(data) < 12:
        raise ValueError("glb")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != _GLB_MAGIC or version != 2 or length < 12 or length > len(data):
        raise ValueError("glb")
    return bytes(data[:length])


def _read_glb_chunks(data: bytes):
    offset = 12
    document = None
    binary = None
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        start = offset + 8
        end = start + chunk_length
        if end > len(data):
            raise ValueError("glb")
        payload = data[start:end]
        document, binary = _take_glb_chunk(chunk_type, payload, document, binary)
        offset = end
    if document is None:
        raise ValueError("glb")
    return document, binary


def _take_glb_chunk(chunk_type, payload, document, binary):
    if chunk_type == _JSON_CHUNK and document is None:
        return json.loads(payload), binary
    if chunk_type == _BIN_CHUNK and binary is None:
        return document, bytes(payload)
    return document, binary
