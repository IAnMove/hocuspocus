"""Clay captures of a humanoid mesh's hands, for judging whether it has a thumb or fingers worth rigging.

python scripts/dev/humanoid_hand_captures.py --out OUT_FOLDER pet=path/to/pet.glb alien=path/to/alien.glb

For each mesh, writes ``OUT/<name>_hands.png``: the body with the rig's arm landmarks, the left arm close up, and the
left hand from the back and edge on. Gray clay only (geometry, not texture), orthographic, painter's order. Also
writes ``OUT/hands.json`` with sizes, triangle counts and how many separate pieces a cut across the hand meets. The mesh
must be an unrigged GLB the humanoid rig accepts; nothing is uploaded or saved anywhere else.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
from services.humanoid_rig.gltf_export import read_primitives
from services.humanoid_rig.landmarks import detect_landmarks

TILE = 420
BACKGROUND = (246, 244, 240)
CLAY = np.array([214.0, 200.0, 186.0])
LIGHT = np.array([0.35, 0.6, 0.72]) / np.linalg.norm([0.35, 0.6, 0.72])
MARKS = {"shoulder": (40, 160, 60), "elbow": (150, 60, 180), "wrist": (30, 110, 200), "hand_tip": (210, 60, 40)}


def load(path: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    """World positions, triangles and the rig's landmarks."""
    positions, faces, offset = [], [], 0
    for item in read_primitives(path.read_bytes()):
        world = np.asarray(item["world"], dtype=np.float64)
        indices = item["indices"]
        if indices is None:
            indices = np.arange(len(world) - len(world) % 3).reshape(-1, 3)
        positions.append(world)
        faces.append(np.asarray(indices, dtype=np.int64).reshape(-1, 3) + offset)
        offset += len(world)
    positions, faces = np.vstack(positions), np.vstack(faces)
    return positions, faces, detect_landmarks(positions, faces)


class View:
    """Orthographic camera: ``right`` and ``up`` span the image, ``extent`` metres fill it."""

    def __init__(self, right, up, center, extent: float, size: int = TILE) -> None:
        self.right = np.asarray(right, dtype=np.float64) / np.linalg.norm(right)
        up = np.asarray(up, dtype=np.float64) - self.right * float(np.dot(up, self.right))
        self.up = up / np.linalg.norm(up)
        self.toward = np.cross(self.right, self.up)
        self.center, self.extent, self.size = np.asarray(center, dtype=np.float64), float(extent), size

    def pixels(self, points: np.ndarray) -> np.ndarray:
        rel = np.asarray(points, dtype=np.float64) - self.center
        scale = self.size / self.extent
        return np.stack([rel @ self.right * scale + self.size / 2, self.size / 2 - rel @ self.up * scale], axis=-1)


def shades(positions: np.ndarray, faces: np.ndarray, view: View) -> np.ndarray:
    """Lambert tone per triangle; back faces darker."""
    tri = positions[faces]
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    light = view.right * LIGHT[0] + view.up * LIGHT[1] + view.toward * LIGHT[2]
    amount = 0.25 + 0.75 * np.abs(normal @ light) * np.where(normal @ view.toward >= 0.0, 1.0, 0.6)
    return (amount[:, None] * CLAY).astype(np.uint8)


def render(positions: np.ndarray, faces: np.ndarray, view: View, marks=()) -> Image.Image:
    image = Image.new("RGB", (view.size, view.size), BACKGROUND)
    draw = ImageDraw.Draw(image)
    flat = view.pixels(positions)
    corners = flat[faces]
    shown = (corners[..., 0].max(1) >= 0) & (corners[..., 0].min(1) < view.size) & (corners[..., 1].max(1) >= 0) & (corners[..., 1].min(1) < view.size)
    tones = shades(positions, faces, view)
    depth = ((positions - view.center) @ view.toward)[faces].mean(1)
    for face in np.argsort(depth):
        if shown[face]:
            tone = tuple(int(c) for c in tones[face])
            draw.polygon([tuple(point) for point in corners[face]], fill=tone, outline=tone)
    for point, colour in marks:
        x, y = view.pixels(point)
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], outline=colour, width=2)
    return image


def welded(positions: np.ndarray) -> np.ndarray:
    """One id per position: UV seams and flat-shaded boxes duplicate vertices."""
    _keys, ids = np.unique(np.round(positions / 1e-5).astype(np.int64), axis=0, return_inverse=True)
    return ids.reshape(-1)


def attached(faces: np.ndarray, positions: np.ndarray, tip: np.ndarray) -> np.ndarray:
    """The faces connected to the vertex nearest ``tip``: the hand without a thigh or the torso beside it."""
    ids = welded(positions)
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, c in ids[faces]:
        for u, v in ((a, b), (b, c)):
            parent[find(int(u))] = find(int(v))
    vertices = np.unique(faces)
    root = find(int(ids[vertices[np.argmin(np.linalg.norm(positions[vertices] - tip, axis=1))]]))
    return faces[np.array([find(int(ids[face[0]])) == root for face in faces], dtype=bool)]


def hand_axes(wrist: np.ndarray, tip: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Along the hand, across it, out of its back, and its length from the landmark wrist."""
    along = tip - wrist
    length = float(np.linalg.norm(along))
    along = along / max(length, 1e-9)
    across = np.cross(along, [0.0, 1.0, 0.0])
    if np.linalg.norm(across) < 0.2:
        across = np.cross(along, [0.0, 0.0, 1.0])
    across /= np.linalg.norm(across)
    return along, across, np.cross(across, along), length


def runs(line: np.ndarray, least: int = 3) -> int:
    """Separate pieces on one pixel line; pieces and gaps under ``least`` pixels do not count."""
    edges = np.flatnonzero(np.diff(np.concatenate(([0], line.astype(np.int8), [0]))))
    spans = list(zip(edges[::2], edges[1::2]))
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start - merged[-1][1] < least:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    return sum(1 for start, end in merged if end - start >= least)


def pieces_along(tile: Image.Image, view: View, wrist: np.ndarray, tip: np.ndarray, slices: int = 10) -> list[int]:
    """Most pieces a cut across the back view meets, per tenth of the hand from the landmark wrist to the tip."""
    mask = np.abs(np.asarray(tile, dtype=np.int16) - BACKGROUND).sum(axis=2) > 6
    start, end = view.pixels(wrist)[0], view.pixels(tip)[0]
    counts = []
    for k in range(slices):
        columns = range(int(start + (end - start) * k / slices), int(start + (end - start) * (k + 1) / slices))
        counts.append(max((runs(mask[:, x]) for x in columns if 0 <= x < mask.shape[1]), default=0))
    return counts


def hand_tiles(positions: np.ndarray, faces: np.ndarray, found: dict, side: str) -> tuple[list[Image.Image], dict]:
    points = {key: np.asarray(value) for key, value in found["points"].items()}
    wrist, tip = points[f"{side}_wrist"], points[f"{side}_hand_tip"]
    along, across, back, length = hand_axes(wrist, tip)
    height = float(found["height"])
    center = wrist + along * 0.5 * length
    extent = max(3.0 * length, 0.2 * height)
    near = np.linalg.norm(positions - center, axis=1) < 0.75 * extent
    hand = attached(faces[near[faces].all(1)], positions, tip)
    arm = View([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], points[f"{side}_elbow"], 0.5 * height)
    arm_marks = [(points[f"{side}_{key}"], colour) for key, colour in MARKS.items()]
    top = View(along, across, center, extent)
    tiles = [render(positions, faces, arm, arm_marks), render(positions, hand, top), render(positions, hand, View(along, back, center, extent))]
    info = {"hand_length_m": round(length, 3), "hand_share_of_height": round(length / height, 3),
            "hand_triangles": len(hand), "pieces_per_tenth": pieces_along(tiles[1], top, wrist, tip)}
    return tiles, info


def capture(name: str, path: Path, out: Path) -> dict:
    positions, faces, found = load(path)
    points = {key: np.asarray(value) for key, value in found["points"].items()}
    low, high = positions.min(0), positions.max(0)
    body = View([1.0, 0.0, 0.0], [0.0, 1.0, 0.0], (low + high) / 2, float((high - low)[:2].max()) * 1.1)
    marks = [(points[f"{side}_{key}"], colour) for side in ("left", "right") for key, colour in MARKS.items()]
    tiles = [render(positions, faces, body, marks)]
    info = {"vertices": len(positions), "triangles": len(faces), "height_m": round(float(found["height"]), 3)}
    for side in ("left", "right"):
        side_tiles, info[side] = hand_tiles(positions, faces, found, side)
        if side == "left":
            tiles += side_tiles
    labels = ["body: shoulder, elbow, wrist, hand tip", "left arm and the rig's landmarks", "left hand, back", "left hand, edge on"]
    sheet = Image.new("RGB", (len(tiles) * (TILE + 10) - 10, TILE + 30), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    for index, (tile, label) in enumerate(zip(tiles, labels)):
        sheet.paste(tile, (index * (TILE + 10), 30))
        draw.text((index * (TILE + 10) + 6, 9), f"{name}: {label}", fill=(20, 20, 20), font=ImageFont.load_default())
    sheet.save(out / f"{name}_hands.png", optimize=True)
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("meshes", nargs="+", help="name=path/to/mesh.glb")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = {}
    for item in args.meshes:
        name, _, path = item.partition("=")
        report[name] = capture(name, Path(path), args.out)
        print(name, json.dumps(report[name]), flush=True)
    (args.out / "hands.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
