"""Vertex colours that are really normals (game rips) are dropped from an imported GLB; real colours stay."""
import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")

from services.glb_cleanup import clean_glb, colours_are_normals  # noqa: E402


def write_glb(path, normals, colours):
    positions = np.random.default_rng(1).random((len(normals), 3)).astype(np.float32)
    blobs = [positions.tobytes(), normals.astype(np.float32).tobytes(), (colours * 255).astype(np.uint8).tobytes()]
    blob, views = b"", []
    for data in blobs:
        views.append(pygltflib.BufferView(buffer=0, byteOffset=len(blob), byteLength=len(data)))
        blob += data + b"\0" * (-len(data) % 4)
    accessors = [pygltflib.Accessor(bufferView=0, componentType=pygltflib.FLOAT, count=len(normals), type="VEC3",
                                    min=positions.min(0).tolist(), max=positions.max(0).tolist()),
                 pygltflib.Accessor(bufferView=1, componentType=pygltflib.FLOAT, count=len(normals), type="VEC3"),
                 pygltflib.Accessor(bufferView=2, componentType=pygltflib.UNSIGNED_BYTE, normalized=True, count=len(normals), type="VEC3")]
    gltf = pygltflib.GLTF2(scenes=[pygltflib.Scene(nodes=[0])], scene=0, nodes=[pygltflib.Node(mesh=0)], bufferViews=views, accessors=accessors,
                           meshes=[pygltflib.Mesh(primitives=[pygltflib.Primitive(attributes=pygltflib.Attributes(POSITION=0, NORMAL=1, COLOR_0=2))])],
                           buffers=[pygltflib.Buffer(byteLength=len(blob))])
    gltf.set_binary_blob(blob)
    gltf.save_binary(str(path))
    return path


def unit(rows):
    return rows / np.linalg.norm(rows, axis=1, keepdims=True)


def test_vertex_colours_that_follow_the_normals_are_dropped_and_real_paint_is_kept(tmp_path):
    rng = np.random.default_rng(7)
    normals = unit(rng.normal(size=(400, 3)))
    rainbow = write_glb(tmp_path / "ape.glb", normals, (1 - normals) / 2)          # an N64 rip: normals, flipped
    painted = write_glb(tmp_path / "fairy.glb", normals, np.tile([0.9, 0.6, 0.3], (400, 1)) + rng.normal(0, 0.03, (400, 3)).clip(-0.1, 0.1))
    assert colours_are_normals(pygltflib.GLTF2().load(str(rainbow)))
    assert clean_glb(rainbow, tmp_path / "ape.clean.glb")
    cleaned = pygltflib.GLTF2().load(str(tmp_path / "ape.clean.glb"))
    assert cleaned.meshes[0].primitives[0].attributes.COLOR_0 is None and cleaned.meshes[0].primitives[0].attributes.NORMAL == 1
    assert not clean_glb(painted, tmp_path / "fairy.clean.glb") and not (tmp_path / "fairy.clean.glb").exists()
    (tmp_path / "broken.glb").write_bytes(b"not a glb")
    assert not clean_glb(tmp_path / "broken.glb", tmp_path / "broken.clean.glb")
