"""Read and append glTF accessors in a GLB's single binary buffer (pygltflib objects).

Only plain float positions, normals and tangents are read. Draco, meshopt and
quantized meshes are refused with a clear message instead of being misread.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.errors import InvalidInput

FLOAT = 5126
UNSIGNED_SHORT = 5123
UNSIGNED_INT = 5125
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963
_INDEX_DTYPE = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_PACKED = ("KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization")


def require_plain_geometry(gltf) -> None:
    packed = [name for name in _PACKED if name in (gltf.extensionsRequired or []) or name in (gltf.extensionsUsed or [])]
    if packed:
        raise InvalidInput(f"compressed meshes are not supported ({', '.join(packed)}); export the GLB without compression")


def read_floats(gltf, blob: bytes, accessor_index: int, width: int) -> np.ndarray:
    """``(count, width)`` float64 rows of a float accessor, honouring byteStride."""
    accessor = gltf.accessors[accessor_index]
    if accessor.bufferView is None or accessor.sparse is not None:
        raise InvalidInput("compressed or sparse mesh data is not supported; export the GLB without compression")
    if accessor.componentType != FLOAT:
        raise InvalidInput("quantized mesh data is not supported; export the GLB with float positions")
    view = gltf.bufferViews[accessor.bufferView]
    offset = (view.byteOffset or 0) + (accessor.byteOffset or 0)
    element = width * 4
    stride = view.byteStride or element
    count = int(accessor.count)
    if count == 0:
        return np.zeros((0, width))
    if stride == element:
        return np.frombuffer(blob, dtype="<f4", count=count * width, offset=offset).reshape(-1, width).astype(np.float64)
    raw = np.frombuffer(blob, dtype=np.uint8, count=stride * (count - 1) + element, offset=offset)
    gather = np.arange(count)[:, None] * stride + np.arange(element)[None, :]
    return raw[gather].copy().view("<f4").reshape(count, width).astype(np.float64)


def read_indices(gltf, blob: bytes, primitive) -> np.ndarray | None:
    """``(M, 3)`` triangle indices, or None for a non-indexed primitive."""
    if primitive.indices is None:
        return None
    accessor = gltf.accessors[primitive.indices]
    dtype = _INDEX_DTYPE.get(accessor.componentType)
    if dtype is None:
        raise InvalidInput("triangle indices must be an unsigned integer accessor")
    if accessor.bufferView is None:
        raise InvalidInput("compressed mesh data is not supported; export the GLB without compression")
    view = gltf.bufferViews[accessor.bufferView]
    offset = (view.byteOffset or 0) + (accessor.byteOffset or 0)
    values = np.frombuffer(blob, dtype=dtype, count=accessor.count, offset=offset).astype(np.int64)
    if len(values) % 3:
        raise InvalidInput("triangle index count is not a multiple of 3")
    return values.reshape(-1, 3)


def append_accessor(gltf, blob: bytearray, data: np.ndarray, component_type: int, type_str: str,
                    target: int | None = None, minmax: bool = False) -> int:
    """Append ``data`` to the binary buffer with its own buffer view; return the accessor index."""
    from pygltflib import Accessor, BufferView

    while len(blob) % 4:
        blob.append(0)
    payload = np.ascontiguousarray(data).tobytes()
    view = BufferView(buffer=0, byteOffset=len(blob), byteLength=len(payload))
    if target is not None:
        view.target = target
    blob.extend(payload)
    gltf.bufferViews.append(view)
    components = _WIDTH[type_str]
    count = int(data.size // components)
    accessor = Accessor(bufferView=len(gltf.bufferViews) - 1, componentType=component_type, count=count, type=type_str)
    if minmax and count:
        flat = np.ascontiguousarray(data, dtype=np.float64).reshape(count, components)
        accessor.min = [float(value) for value in flat.min(axis=0)]
        accessor.max = [float(value) for value in flat.max(axis=0)]
    gltf.accessors.append(accessor)
    return len(gltf.accessors) - 1
