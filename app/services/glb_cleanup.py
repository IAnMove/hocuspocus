"""Clean a GLB brought in from elsewhere before a production rigs it.

Game exports often carry vertex normals in the vertex-colour channel: on the N64 a lit model stores its normals
where an unlit one stores colours, and a ripper that writes both as COLOR_0 gives every lit model rainbow tints
(red, green and purple gradients that follow the surface). Such a channel is recognised by how closely it follows
the NORMAL attribute and how saturated it is, and dropped; real vertex colours are kept.

Rips also carry textures decoded with the wrong format: confetti where every texel is a random vivid colour (an
old ape's beard, a fish's fins). A material painted with one loses that texture and shows its vertex colours.

A ripped character may come with a held thing hung under its feet instead of in its hand (a wooden gun, a club):
it reads as a column between the legs and stands the body on the gun's end. For a body that stands on two feet,
a part hanging well below the feet is dropped.

A glow (a fairy's light, a flame, a spark) is often a bright shape painted on black with no alpha channel, meant
to be added to the picture: drawn as it comes, it is a black square with a light inside. Such a material is marked
additive and unlit, and the viewer adds its light instead of painting the square.

A skinned rip may store each part in its own bone's space (every limb piled at the origin) and leave the skeleton
to assemble the body: a viewer shows it whole, but anything reading the vertices (the humanoid rig, the clean-ups
above) sees a heap. Such a model is baked into its rest pose, the parts where the skeleton puts them, and rebound
so its own clips still play unchanged.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np

NORMAL_LIKE = 0.3       # |median cosine| between the colour read as a direction and the normal
SATURATED = 0.4         # mean (max - min) of the colour channels: encoded directions are vivid, paint mostly is not
NOISY = 0.45            # median colour jump between neighbouring texels (summed over RGB, 0..3): garbage ~0.55-1.3, art < 0.35
VIVID = 0.35            # mean texel saturation: the garbage is confetti, while grain, static and stripes are mostly grey
SAMPLE = 256            # texels on a side of the corner of a texture that is measured
FEET = 10               # the lowest tenth of a standing body's vertices are its feet
UNDER_FEET = 0.2        # a part reaching this share of the height below the feet hangs under the floor
APART = 0.75            # skinned vertices spanning less than this share of the rest pose's height are stored in parts
BLACK = 0.03            # a texture whose border is darker than this (mean RGB) is painted on black
GLOW = 0.1              # ... and whose inside is this much brighter than its border glows
CLEANUP = 5             # version of this cleanup, part of a model's fingerprint

_TYPES = {5126: np.float32, 5121: np.uint8, 5123: np.uint16}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _read(gltf, index: int) -> np.ndarray:
    accessor = gltf.accessors[index]
    view = gltf.bufferViews[accessor.bufferView]
    kind, width = _TYPES[accessor.componentType], _WIDTH[accessor.type]
    item = np.dtype(kind).itemsize * width
    stride = view.byteStride or item
    start = view.byteOffset + (accessor.byteOffset or 0)
    raw = np.frombuffer(gltf.binary_blob()[start:start + stride * accessor.count], dtype=np.uint8)
    values = raw.reshape(accessor.count, stride)[:, :item].copy().view(kind).reshape(accessor.count, width).astype(np.float64)
    if kind is not np.float32 and accessor.normalized is not False:
        values /= np.iinfo(kind).max
    return values


def colours_are_normals(gltf) -> bool:
    """True when the vertex colours of the model's primitives read as its normals."""
    cosines, spreads = [], []
    for mesh in gltf.meshes:
        for primitive in mesh.primitives:
            attributes = primitive.attributes
            if attributes.COLOR_0 is None or attributes.NORMAL is None:
                continue
            colour = _read(gltf, attributes.COLOR_0)[:, :3]
            normal = _read(gltf, attributes.NORMAL)
            direction = 2 * colour - 1
            length = np.linalg.norm(direction, axis=1) * np.linalg.norm(normal, axis=1) + 1e-9
            cosines.append((direction * normal).sum(axis=1) / length)
            spreads.append(colour.max(axis=1) - colour.min(axis=1))
    if not cosines:
        return False
    return abs(float(np.median(np.concatenate(cosines)))) > NORMAL_LIKE and float(np.concatenate(spreads).mean()) > SATURATED


def noisy_images(gltf) -> set[int]:
    """Indices of the embedded images that are decoding garbage: every texel a random vivid colour."""
    found = set()
    for index, image in enumerate(gltf.images or []):
        texels = _texels(gltf, image)
        if texels is not None and _is_noise(texels):
            found.add(index)
    return found


def _texels(gltf, image) -> np.ndarray | None:
    from PIL import Image

    if image.bufferView is None:
        return None
    view = gltf.bufferViews[image.bufferView]
    start = view.byteOffset or 0
    try:
        with Image.open(io.BytesIO(gltf.binary_blob()[start:start + view.byteLength])) as picture:
            corner = picture.crop((0, 0, min(picture.width, SAMPLE), min(picture.height, SAMPLE)))   # a big texture is not read whole
            return np.asarray(corner.convert("RGB"), dtype=np.float32) / 255
    except (OSError, ValueError):
        return None


def _is_noise(rgb: np.ndarray) -> bool:
    if min(rgb.shape[:2]) < 2:
        return False
    jump = (np.median(np.abs(np.diff(rgb, axis=0)).sum(axis=2)) + np.median(np.abs(np.diff(rgb, axis=1)).sum(axis=2))) / 2
    top = rgb.max(axis=2)
    saturation = float(np.mean((top - rgb.min(axis=2)) / np.maximum(top, 1e-6)))
    return float(jump) > NOISY and saturation > VIVID


def _drop_noisy_textures(gltf) -> int:
    """Materials painted with a garbage image lose it; the count of materials changed."""
    noisy = noisy_images(gltf)
    if not noisy:
        return 0
    changed = 0
    for material in gltf.materials or []:
        paint = material.pbrMetallicRoughness
        texture = paint.baseColorTexture if paint else None
        if texture is not None and gltf.textures[texture.index].source in noisy:
            paint.baseColorTexture = None
            changed += 1
    return changed


def glow_materials(gltf) -> list[int]:
    """Indices of the materials painted as a glow on black: an opaque texture without alpha whose border is black
    and whose inside is brighter, on a material that does not blend yet."""
    found = []
    for index, material in enumerate(gltf.materials or []):
        paint = material.pbrMetallicRoughness
        texture = paint.baseColorTexture if paint else None
        if texture is None or (material.alphaMode or "OPAQUE") != "OPAQUE":
            continue
        source = gltf.textures[texture.index].source
        if source is None or _has_alpha(gltf, gltf.images[source]):
            continue
        texels = _texels(gltf, gltf.images[source])
        if texels is None or min(texels.shape[:2]) < 4:
            continue
        border = np.concatenate([texels[0], texels[-1], texels[:, 0], texels[:, -1]])
        if float(border.mean()) < BLACK and float(texels.mean()) > float(border.mean()) + GLOW:
            found.append(index)
    return found


def _has_alpha(gltf, image) -> bool:
    from PIL import Image

    if image.bufferView is None:
        return False
    view = gltf.bufferViews[image.bufferView]
    start = view.byteOffset or 0
    try:
        with Image.open(io.BytesIO(gltf.binary_blob()[start:start + view.byteLength])) as picture:
            return picture.mode in ("RGBA", "LA", "PA") or "transparency" in picture.info
    except (OSError, ValueError):
        return False


def _mark_glows(gltf) -> int:
    """Glow materials become additive (``extras.hocusBlend``) and unlit; the count marked."""
    glows = glow_materials(gltf)
    for index in glows:
        material = gltf.materials[index]
        material.extras = {**(material.extras or {}), "hocusBlend": "additive"}
        material.extensions = {**(material.extensions or {}), "KHR_materials_unlit": {}}
    if glows and "KHR_materials_unlit" not in (gltf.extensionsUsed or []):
        gltf.extensionsUsed = [*(gltf.extensionsUsed or []), "KHR_materials_unlit"]
    return len(glows)


def parts_under_feet(gltf) -> list[tuple[int, int]]:
    """``(mesh, primitive)`` of the parts hanging under a standing body's feet: not its largest part, and reaching
    far below the level that its lowest tenth of vertices (the feet) reach."""
    parts = [(mesh, index, _read(gltf, primitive.attributes.POSITION)[:, 1])
             for mesh, item in enumerate(gltf.meshes) for index, primitive in enumerate(item.primitives)
             if primitive.attributes.POSITION is not None]
    if len(parts) < 2:
        return []
    heights = np.concatenate([part[2] for part in parts])
    floor = np.percentile(heights, FEET) - UNDER_FEET * (heights.max() - heights.min())
    body = max(range(len(parts)), key=lambda index: len(parts[index][2]))
    return [(mesh, index) for at, (mesh, index, ys) in enumerate(parts) if at != body and ys.min() < floor]


def _drop_parts_under_feet(gltf) -> int:
    """Parts hanging under the feet leave their meshes; the count of parts dropped."""
    hanging = parts_under_feet(gltf)
    for mesh, index in sorted(hanging, reverse=True):
        del gltf.meshes[mesh].primitives[index]
    return len(hanging)


def _local_matrix(node) -> np.ndarray:
    if node.matrix:
        return np.array(node.matrix, dtype=np.float64).reshape(4, 4).T
    shift = np.array(node.translation or [0.0, 0.0, 0.0], dtype=np.float64)
    x, y, z, w = node.rotation or [0.0, 0.0, 0.0, 1.0]
    scale = np.array(node.scale or [1.0, 1.0, 1.0], dtype=np.float64)
    turn = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    matrix = np.eye(4)
    matrix[:3, :3] = turn * scale
    matrix[:3, 3] = shift
    return matrix


def _node_worlds(gltf) -> list[np.ndarray]:
    """Every node's world matrix in the rest pose (its own transform under its parents')."""
    parents = {child: index for index, node in enumerate(gltf.nodes) for child in (node.children or [])}
    worlds: dict[int, np.ndarray] = {}

    def world(index: int) -> np.ndarray:
        if index not in worlds:
            local = _local_matrix(gltf.nodes[index])
            worlds[index] = (world(parents[index]) @ local) if index in parents else local
        return worlds[index]

    return [world(index) for index in range(len(gltf.nodes))]


def _skin_matrices(gltf, skin, worlds: list[np.ndarray]) -> np.ndarray:
    """Per joint, the matrix that takes a stored vertex to the rest pose: joint world × inverse bind."""
    if skin.inverseBindMatrices is None:
        inverse = np.tile(np.eye(4), (len(skin.joints), 1, 1))
    else:
        inverse = _read(gltf, skin.inverseBindMatrices).reshape(-1, 4, 4).transpose(0, 2, 1)   # column-major in the file
    return np.array([worlds[joint] @ inverse[index] for index, joint in enumerate(skin.joints)])


def _skinned_parts(gltf):
    """``(skin index, primitive)`` for every primitive a skin drives."""
    for node in gltf.nodes:
        if node.mesh is None or node.skin is None:
            continue
        for primitive in gltf.meshes[node.mesh].primitives:
            attributes = primitive.attributes
            if attributes.POSITION is not None and attributes.JOINTS_0 is not None and attributes.WEIGHTS_0 is not None:
                yield node.skin, primitive


def _rest_pose(gltf, primitive, matrices: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """``(stored positions, rest-pose positions, rest-pose normals)`` of a skinned primitive."""
    stored = _read(gltf, primitive.attributes.POSITION)
    joints = _read(gltf, primitive.attributes.JOINTS_0).astype(int)
    weights = _read(gltf, primitive.attributes.WEIGHTS_0)
    weights = weights / np.maximum(weights.sum(axis=1, keepdims=True), 1e-9)
    influence = matrices[joints]                                                      # (vertex, 4, 4, 4)
    moved = np.einsum("nkij,nj->nki", influence, np.c_[stored, np.ones(len(stored))])[:, :, :3]
    rest = (moved * weights[:, :, None]).sum(axis=1)
    normals = None
    if primitive.attributes.NORMAL is not None:
        turn = np.linalg.inv(influence[:, :, :3, :3]).transpose(0, 1, 3, 2)              # inverse transpose per influence
        turned = (np.einsum("nkij,nj->nki", turn, _read(gltf, primitive.attributes.NORMAL)) * weights[:, :, None]).sum(axis=1)
        normals = turned / np.maximum(np.linalg.norm(turned, axis=1, keepdims=True), 1e-9)
    return stored, rest, normals


def parts_stored_apart(gltf) -> bool:
    """True when the skinned vertices as stored span much less height than the body the skeleton assembles."""
    worlds, matrices, stored, rest = _node_worlds(gltf), {}, [], []
    for skin, primitive in _skinned_parts(gltf):
        if skin not in matrices:
            matrices[skin] = _skin_matrices(gltf, gltf.skins[skin], worlds)
        before, after, _ = _rest_pose(gltf, primitive, matrices[skin])
        stored.append(before)
        rest.append(after)
    if not stored:
        return False
    span = np.vstack(rest)[:, 1]
    height = float(span.max() - span.min())
    stored_height = float(np.ptp(np.vstack(stored)[:, 1]))
    return height > 0 and stored_height < APART * height


def bake_rest_pose(gltf) -> int:
    """Store every skinned vertex where the skeleton puts it at rest and rebind the skins there, so the model reads
    assembled and its clips play as before; the count of parts baked."""
    from services.humanoid_rig.gltf_buffers import ARRAY_BUFFER, FLOAT, append_accessor

    worlds, matrices, blob, baked = _node_worlds(gltf), {}, bytearray(gltf.binary_blob()), 0
    for skin, primitive in _skinned_parts(gltf):
        if skin not in matrices:
            matrices[skin] = _skin_matrices(gltf, gltf.skins[skin], worlds)
        _, rest, normals = _rest_pose(gltf, primitive, matrices[skin])
        primitive.attributes.POSITION = append_accessor(gltf, blob, rest.astype(np.float32), FLOAT, "VEC3", ARRAY_BUFFER, minmax=True)
        if normals is not None:
            primitive.attributes.NORMAL = append_accessor(gltf, blob, normals.astype(np.float32), FLOAT, "VEC3", ARRAY_BUFFER)
        baked += 1
    for skin in matrices:
        inverse = np.array([np.linalg.inv(worlds[joint]) for joint in gltf.skins[skin].joints])
        gltf.skins[skin].inverseBindMatrices = append_accessor(gltf, blob, inverse.transpose(0, 2, 1).reshape(-1, 16).astype(np.float32), FLOAT, "MAT4")
    gltf.set_binary_blob(bytes(blob))
    gltf.buffers[0].byteLength = len(blob)
    return baked


def clean_glb(source: str | Path, target: str | Path, *, standing: bool = False) -> list[str]:
    """Write ``target`` with a skinned body that was stored in parts assembled in its rest pose, without vertex
    colours that are really normals, without garbage textures and, for a body that stands on two feet
    (``standing``), without parts hung under them; say what was fixed. Empty (and nothing written) when the model
    is fine or unreadable."""
    import struct

    import pygltflib

    fixes = []
    try:
        gltf = pygltflib.GLTF2().load(str(source))
        if gltf is None:
            return []
        if parts_stored_apart(gltf) and (baked := bake_rest_pose(gltf)):
            fixes.append(f"its {baked} skinned parts were stored apart (each in its bone's space), now assembled in its rest pose")
        if colours_are_normals(gltf):
            for mesh in gltf.meshes:
                for primitive in mesh.primitives:
                    primitive.attributes.COLOR_0 = None
            fixes.append("its vertex colours were normals (rainbow tints)")
        if painted := _drop_noisy_textures(gltf):
            fixes.append(f"{painted} of its materials were painted with decoding noise, now dropped")
        if glows := _mark_glows(gltf):
            fixes.append(f"{glows} of its materials glow on black (a light with no alpha), now added to the picture")
        if standing and (hung := _drop_parts_under_feet(gltf)):
            fixes.append(f"{hung} of its parts hung under its feet (a held thing the rip misplaced), now dropped")
    except (OSError, ValueError, KeyError, IndexError, TypeError, struct.error):
        return []            # not a GLB this can read: the rig service says what is wrong with it
    if fixes:
        gltf.save_binary(str(target))
    return fixes
