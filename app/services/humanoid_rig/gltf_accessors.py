"""glTF accessor reads for the compatibility path.

Honors bufferView byteStride and accessor byteOffset. Sparse accessors and
unknown required extensions are rejected with a reason. The legacy retarget
reader is unchanged and still ignores stride.
"""

from __future__ import annotations

import json
import math
import struct

import numpy as np

_COMPONENT = {
    5120: ("b", 1, True),
    5121: ("B", 1, False),
    5122: ("h", 2, True),
    5123: ("H", 2, False),
    5125: ("I", 4, False),
    5126: ("f", 4, False),
}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942


class AccessorError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def split_glb(data: bytes) -> tuple[dict, list[bytes]]:
    """Return the JSON document and BIN chunks from a GLB 2.0 payload."""
    if len(data) < 12:
        raise AccessorError("glb")
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or version != 2 or length > len(data):
        raise AccessorError("glb")
    offset = 12
    document = None
    buffers: list[bytes] = []
    while offset + 8 <= length:
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        start = offset + 8
        end = start + chunk_length
        if end > length:
            raise AccessorError("glb")
        payload = data[start:end]
        if chunk_type == _JSON_CHUNK and document is None:
            document = json.loads(payload)
        elif chunk_type == _BIN_CHUNK:
            buffers.append(bytes(payload))
        offset = end
    if document is None:
        raise AccessorError("glb")
    return document, buffers


def required_extension_issues(document: dict) -> list[str]:
    required = document.get("extensionsRequired") or []
    return [f"unsupported_extension:{name}" for name in required]


def read_accessor(document: dict, index: int, buffers: list[bytes]) -> np.ndarray:
    accessor = _accessor(document, index)
    if accessor.get("sparse") is not None:
        raise AccessorError("unsupported_sparse_accessor")
    view = _buffer_view(document, accessor.get("bufferView"))
    blob = _buffer_bytes(buffers, view.get("buffer", 0))
    code, comp_size, signed = _component(accessor.get("componentType"))
    width = _WIDTH.get(accessor.get("type"))
    if width is None:
        raise AccessorError("unsupported_accessor_type")
    count = int(accessor.get("count") or 0)
    stride = int(view.get("byteStride") or (width * comp_size))
    if "byteLength" not in view:
        raise AccessorError("bad_buffer_view")
    view_length = int(view["byteLength"])
    acc_off = int(accessor.get("byteOffset") or 0)
    element = width * comp_size
    if count:
        end = acc_off + (count - 1) * stride + element
        if acc_off < 0 or stride < element or end > view_length:
            raise AccessorError("accessor_outside_view")
    start = int(view.get("byteOffset") or 0) + acc_off
    rows = [_row(blob, start + i * stride, code, width, signed, accessor) for i in range(count)]
    array = np.asarray(rows, dtype=np.float64)
    if width == 1:
        return array.reshape(count)
    return array


def accessor_min_max(document: dict, index: int) -> tuple[list[float], list[float]] | None:
    accessor = _accessor(document, index)
    low = accessor.get("min")
    high = accessor.get("max")
    if not isinstance(low, list) or not isinstance(high, list):
        return None
    return [float(v) for v in low], [float(v) for v in high]


def position_y_bounds(document: dict) -> tuple[float, float] | None:
    """Union of POSITION Y bounds. A later primitive can hold the body."""
    low = None
    high = None
    for _mesh_index, primitive in _position_primitives(document, _selected_meshes(document)):
        index = (primitive.get("attributes") or {}).get("POSITION")
        bounds = accessor_min_max(document, index)
        if bounds is None or len(bounds[0]) < 2:
            continue
        low = bounds[0][1] if low is None else min(low, bounds[0][1])
        high = bounds[1][1] if high is None else max(high, bounds[1][1])
    if low is None or high is None:
        return None
    return low, high


def measured_height(document: dict, buffers: list[bytes] | None, nodes: list[dict], parents: list[int | None]) -> dict:
    """Height in metres for the selected character, or an unresolved measurement.

    Raw POSITION is used only when no inverse bind is declared and no mesh node
    supplies a transform. A skinned span is computed once. Wrapper scale is not
    applied a second time.
    """
    if _skin_height_available(document, buffers):
        skinned = _skinned_height(document, buffers or [], nodes, parents)
        if skinned is None:
            return _unresolved()
        return {"height_m": skinned, "height_method": "skinned_bounds_m", "height_unresolved": False}
    if _ibm_declared(document):
        return _unresolved()
    transformed = _node_bounds_height(document, nodes, parents)
    if transformed is not None:
        return {"height_m": transformed, "height_method": "node_bounds_m", "height_unresolved": False}
    raw = position_y_bounds(document)
    if raw is None:
        return {"height_m": None, "height_method": None, "height_unresolved": False}
    return {"height_m": float(raw[1] - raw[0]), "height_method": "position_bounds_m", "height_unresolved": False}


def _accessor(document: dict, index: int) -> dict:
    accessors = document.get("accessors") or []
    if not isinstance(index, int) or index < 0 or index >= len(accessors):
        raise AccessorError("bad_accessor")
    return accessors[index]


def _buffer_view(document: dict, index) -> dict:
    views = document.get("bufferViews") or []
    if not isinstance(index, int) or index < 0 or index >= len(views):
        raise AccessorError("bad_buffer_view")
    return views[index]


def _buffer_bytes(buffers: list[bytes], index: int) -> bytes:
    if index < 0 or index >= len(buffers):
        raise AccessorError("missing_buffer")
    return buffers[index]


def _component(component_type) -> tuple[str, int, bool]:
    found = _COMPONENT.get(component_type)
    if found is None:
        raise AccessorError("unsupported_component_type")
    return found


def _row(blob: bytes, offset: int, code: str, width: int, signed: bool, accessor: dict) -> list[float]:
    need = struct.calcsize("<" + code) * width
    if offset < 0 or offset + need > len(blob):
        raise AccessorError("truncated_accessor")
    raw = struct.unpack_from("<" + code * width, blob, offset)
    if accessor.get("componentType") == 5126:
        if any(not math.isfinite(float(v)) for v in raw):
            raise AccessorError("non_finite_accessor")
        return [float(v) for v in raw]
    return [_normalize(v, code, signed, bool(accessor.get("normalized"))) for v in raw]


def _unresolved() -> dict:
    return {"height_m": None, "height_method": None, "height_unresolved": True}


def _selected_meshes(document: dict) -> set[int] | None:
    chosen = set()
    for node in document.get("nodes") or []:
        if isinstance(node.get("skin"), int) and isinstance(node.get("mesh"), int):
            chosen.add(node["mesh"])
    return chosen or None


def _position_primitives(document: dict, selected: set[int] | None):
    for mesh_index, mesh in enumerate(document.get("meshes") or []):
        if selected is not None and mesh_index not in selected:
            continue
        for primitive in mesh.get("primitives") or []:
            index = (primitive.get("attributes") or {}).get("POSITION")
            if isinstance(index, int):
                yield mesh_index, primitive


def _ibm_declared(document: dict) -> bool:
    for skin in document.get("skins") or []:
        if isinstance(skin.get("inverseBindMatrices"), int):
            return True
    return False


def _skin_height_available(document: dict, buffers: list[bytes] | None) -> bool:
    if not buffers or not _ibm_declared(document):
        return False
    skin = (document.get("skins") or [{}])[0]
    joints = skin.get("joints") or []
    if not joints:
        return False
    for mesh_index, primitive in _position_primitives(document, _selected_meshes(document)):
        attrs = primitive.get("attributes") or {}
        if all(isinstance(attrs.get(key), int) for key in ("JOINTS_0", "WEIGHTS_0")):
            return True
        del mesh_index
    return False


def _skinned_height(document, buffers, nodes, parents) -> float | None:
    from services.humanoid_rig.pose_math import PoseMathError, trs_matrix, world_matrices

    skin = (document.get("skins") or [{}])[0]
    try:
        inverse = read_accessor(document, skin["inverseBindMatrices"], buffers)
        locals_m = [_node_matrix(node, trs_matrix) for node in nodes]
        worlds = world_matrices(locals_m, parents)
    except (AccessorError, PoseMathError, ValueError):
        return None
    ibms = [np.asarray(row, dtype=np.float64).reshape((4, 4), order="F") for row in np.atleast_2d(inverse)]
    joints = skin.get("joints") or []
    ys: list[float] = []
    selected = _selected_meshes(document)
    for mesh_index, primitive in _position_primitives(document, selected):
        attrs = primitive.get("attributes") or {}
        if not all(isinstance(attrs.get(key), int) for key in ("POSITION", "JOINTS_0", "WEIGHTS_0")):
            continue
        try:
            points = read_accessor(document, attrs["POSITION"], buffers)
            joint_index = read_accessor(document, attrs["JOINTS_0"], buffers)
            weights = read_accessor(document, attrs["WEIGHTS_0"], buffers)
        except AccessorError:
            return None
        ys.extend(_skin_y(points, joint_index, weights, joints, worlds, ibms))
        del mesh_index
    if len(ys) < 2:
        return None
    return float(max(ys) - min(ys))


def _skin_y(points, joint_index, weights, skin_joints, worlds, ibms) -> list[float]:
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim == 1:
        pts = pts.reshape(1, -1)
    homo = np.concatenate((pts[:, :3], np.ones((len(pts), 1))), axis=1)
    indexes = np.asarray(joint_index, dtype=np.int64)
    influence = np.asarray(weights, dtype=np.float64)
    if indexes.ndim == 1:
        indexes = indexes.reshape(-1, 1)
        influence = influence.reshape(-1, 1)
    out = np.zeros((len(pts), 4), dtype=np.float64)
    for slot in range(indexes.shape[1]):
        for joint in np.unique(indexes[:, slot]):
            mask = indexes[:, slot] == joint
            joint = int(joint)
            if joint < 0 or joint >= len(skin_joints) or joint >= len(ibms):
                continue
            node = skin_joints[joint]
            if not isinstance(node, int) or isinstance(node, bool) or node < 0 or node >= len(worlds):
                continue
            transformed = homo[mask] @ (worlds[node] @ ibms[joint]).T
            out[mask] += influence[mask, slot][:, None] * transformed
    return out[:, 1].tolist()


def _node_bounds_height(document, nodes, parents) -> float | None:
    from services.humanoid_rig.pose_math import PoseMathError, trs_matrix, world_matrices

    selected = _selected_meshes(document)
    if not any(isinstance(node.get("mesh"), int) and not isinstance(node.get("skin"), int) for node in nodes):
        return None
    try:
        worlds = world_matrices([_node_matrix(node, trs_matrix) for node in nodes], parents)
    except PoseMathError:
        return None
    ys: list[float] = []
    meshes = document.get("meshes") or []
    for node_index, node in enumerate(nodes):
        mesh_index = node.get("mesh")
        if not isinstance(mesh_index, int) or isinstance(node.get("skin"), int):
            continue
        if selected is not None and mesh_index not in selected:
            continue
        if mesh_index < 0 or mesh_index >= len(meshes):
            continue
        for primitive in meshes[mesh_index].get("primitives") or []:
            index = (primitive.get("attributes") or {}).get("POSITION")
            bounds = accessor_min_max(document, index) if isinstance(index, int) else None
            if bounds is None or len(bounds[0]) < 3:
                continue
            ys.extend(_corner_y(worlds[node_index], bounds[0], bounds[1]))
    if len(ys) < 2:
        return None
    return float(max(ys) - min(ys))


def _corner_y(world, low, high) -> list[float]:
    ys = []
    for x in (low[0], high[0]):
        for y in (low[1], high[1]):
            for z in (low[2], high[2]):
                point = world @ np.array([x, y, z, 1.0], dtype=np.float64)
                ys.append(float(point[1]))
    return ys


def _node_matrix(node: dict, trs_matrix) -> np.ndarray:
    if "matrix" in node:
        return np.asarray(node["matrix"], dtype=np.float64).reshape((4, 4), order="F")
    return trs_matrix(
        node.get("translation") or [0.0, 0.0, 0.0],
        node.get("rotation") or [0.0, 0.0, 0.0, 1.0],
        node.get("scale") or [1.0, 1.0, 1.0],
    )


def _normalize(value: int, code: str, signed: bool, normalized: bool) -> float:
    if not normalized:
        return float(value)
    if not signed:
        return float(value) / float((1 << (8 * struct.calcsize("<" + code))) - 1)
    limit = 1 << (8 * struct.calcsize("<" + code) - 1)
    if value == -limit:
        return -1.0
    return max(-1.0, float(value) / float(limit - 1))
