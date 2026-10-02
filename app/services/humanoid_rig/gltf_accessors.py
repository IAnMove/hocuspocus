"""glTF accessor reads for the compatibility path.

Honors bufferView byteStride and accessor byteOffset. Sparse accessors and
unknown required extensions are rejected with a reason. The legacy retarget
reader is unchanged and still ignores stride.
"""

from __future__ import annotations

import json
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
    start = int(view.get("byteOffset") or 0) + int(accessor.get("byteOffset") or 0)
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
    """Y bounds of the first POSITION accessor that publishes min and max."""
    for mesh in document.get("meshes") or []:
        for primitive in mesh.get("primitives") or []:
            index = (primitive.get("attributes") or {}).get("POSITION")
            if not isinstance(index, int):
                continue
            bounds = accessor_min_max(document, index)
            if bounds is not None and len(bounds[0]) >= 2:
                return bounds[0][1], bounds[1][1]
    return None


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
        return [float(v) for v in raw]
    return [_normalize(v, code, signed, bool(accessor.get("normalized"))) for v in raw]


def _normalize(value: int, code: str, signed: bool, normalized: bool) -> float:
    if not normalized:
        return float(value)
    if not signed:
        return float(value) / float((1 << (8 * struct.calcsize("<" + code))) - 1)
    limit = 1 << (8 * struct.calcsize("<" + code) - 1)
    if value == -limit:
        return -1.0
    return max(-1.0, float(value) / float(limit - 1))
