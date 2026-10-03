"""Batched xyzw quaternions and 3x3 rotations. Right-handed, Hamilton product.

Every function accepts a single rotation or a stack in the leading axes.
"""

from __future__ import annotations

import numpy as np

IDENTITY = np.array([0.0, 0.0, 0.0, 1.0])


def normalize(quat: np.ndarray) -> np.ndarray:
    quat = np.asarray(quat, dtype=np.float64)
    length = np.linalg.norm(quat, axis=-1, keepdims=True)
    return np.where(length > 1e-12, quat / np.maximum(length, 1e-12), IDENTITY)


def multiply(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lx, ly, lz, lw = np.moveaxis(np.asarray(left, dtype=np.float64), -1, 0)
    rx, ry, rz, rw = np.moveaxis(np.asarray(right, dtype=np.float64), -1, 0)
    return np.stack((
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
        lw * rw - lx * rx - ly * ry - lz * rz,
    ), axis=-1)


def inverse(quat: np.ndarray) -> np.ndarray:
    quat = np.asarray(quat, dtype=np.float64)
    return np.concatenate((-quat[..., :3], quat[..., 3:]), axis=-1)


def axis_angle(axis, degrees) -> np.ndarray:
    """Rotation of ``degrees`` about ``axis``. Broadcasts over ``degrees``."""
    direction = np.asarray(axis, dtype=np.float64)
    direction = direction / np.linalg.norm(direction, axis=-1, keepdims=True)
    half = np.radians(np.asarray(degrees, dtype=np.float64))[..., None] * 0.5
    return np.concatenate((direction * np.sin(half), np.cos(half)), axis=-1)


def euler(x_degrees=0.0, y_degrees=0.0, z_degrees=0.0) -> np.ndarray:
    """Intrinsic X, then Y, then Z: ``qx * qy * qz``."""
    qx = axis_angle([1.0, 0.0, 0.0], x_degrees)
    qy = axis_angle([0.0, 1.0, 0.0], y_degrees)
    qz = axis_angle([0.0, 0.0, 1.0], z_degrees)
    return multiply(multiply(qx, qy), qz)


def to_matrix(quat: np.ndarray) -> np.ndarray:
    x, y, z, w = np.moveaxis(normalize(quat), -1, 0)
    return np.stack((
        np.stack((1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)), axis=-1),
        np.stack((2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)), axis=-1),
        np.stack((2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)), axis=-1),
    ), axis=-2)


def from_matrix(matrix: np.ndarray) -> np.ndarray:
    """Quaternion of a rotation matrix, with w >= 0."""
    m = np.asarray(matrix, dtype=np.float64)
    trace = m[..., 0, 0] + m[..., 1, 1] + m[..., 2, 2]
    candidates = np.stack((
        np.stack((m[..., 2, 1] - m[..., 1, 2], m[..., 0, 2] - m[..., 2, 0], m[..., 1, 0] - m[..., 0, 1], 1.0 + trace), axis=-1),
        np.stack((1.0 + m[..., 0, 0] - m[..., 1, 1] - m[..., 2, 2], m[..., 0, 1] + m[..., 1, 0], m[..., 0, 2] + m[..., 2, 0], m[..., 2, 1] - m[..., 1, 2]), axis=-1),
        np.stack((m[..., 0, 1] + m[..., 1, 0], 1.0 + m[..., 1, 1] - m[..., 0, 0] - m[..., 2, 2], m[..., 1, 2] + m[..., 2, 1], m[..., 0, 2] - m[..., 2, 0]), axis=-1),
        np.stack((m[..., 0, 2] + m[..., 2, 0], m[..., 1, 2] + m[..., 2, 1], 1.0 + m[..., 2, 2] - m[..., 0, 0] - m[..., 1, 1], m[..., 1, 0] - m[..., 0, 1]), axis=-1),
    ), axis=-2)
    pick = np.argmax(np.stack((trace, m[..., 0, 0], m[..., 1, 1], m[..., 2, 2]), axis=-1), axis=-1)
    chosen = np.take_along_axis(candidates, pick[..., None, None], axis=-2)[..., 0, :]
    chosen = normalize(chosen)
    return np.where(chosen[..., 3:] < 0.0, -chosen, chosen)


def rotate(quat: np.ndarray, vector: np.ndarray) -> np.ndarray:
    return np.einsum("...ij,...j->...i", to_matrix(quat), np.asarray(vector, dtype=np.float64))


def align(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Shortest rotation that carries direction ``source`` onto ``target``."""
    a = np.asarray(source, dtype=np.float64) / np.linalg.norm(source)
    b = np.asarray(target, dtype=np.float64) / np.linalg.norm(target)
    dot = float(np.clip(a @ b, -1.0, 1.0))
    if dot > 1.0 - 1e-12:
        return IDENTITY.copy()
    if dot < -1.0 + 1e-12:
        side = np.cross(a, [1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.cross(a, [0.0, 1.0, 0.0])
        return axis_angle(side, 180.0)
    return normalize(np.concatenate((np.cross(a, b), [1.0 + dot])))


def slerp(left: np.ndarray, right: np.ndarray, amount) -> np.ndarray:
    a, b = normalize(left), normalize(right)
    dot = np.sum(a * b, axis=-1, keepdims=True)
    b = np.where(dot < 0.0, -b, b)
    dot = np.abs(dot)
    t = np.asarray(amount, dtype=np.float64)[..., None] if np.ndim(amount) else float(amount)
    theta = np.arccos(np.clip(dot, -1.0, 1.0))
    small = theta < 1e-6
    sin = np.where(small, 1.0, np.sin(theta))
    wa = np.where(small, 1.0 - t, np.sin((1.0 - t) * theta) / sin)
    wb = np.where(small, t, np.sin(t * theta) / sin)
    return normalize(wa * a + wb * b)


def continuous(track: np.ndarray) -> np.ndarray:
    """Flip signs so neighbouring keys take the short way (no slerp spins)."""
    out = np.array(track, dtype=np.float64, copy=True)
    for index in range(1, len(out)):
        if float(out[index] @ out[index - 1]) < 0.0:
            out[index] = -out[index]
    return out
