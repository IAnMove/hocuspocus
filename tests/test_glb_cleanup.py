"""Vertex colours that are really normals and textures that are decoding noise (game rips) are dropped from an imported
GLB; real colours and real textures stay."""
import io

import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")

from services.glb_cleanup import clean_glb, colours_are_normals, noisy_images  # noqa: E402


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


def png(texels):
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray((texels * 255).astype(np.uint8)).save(buffer, format="PNG")
    return buffer.getvalue()


def write_textured_glb(path, pictures):
    """One triangle per picture, each with its own material and texture."""
    triangle = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
    blobs = [triangle.tobytes()] + [png(picture) for picture in pictures]
    blob, views = b"", []
    for data in blobs:
        views.append(pygltflib.BufferView(buffer=0, byteOffset=len(blob), byteLength=len(data)))
        blob += data + b"\0" * (-len(data) % 4)
    count = len(pictures)
    gltf = pygltflib.GLTF2(
        scenes=[pygltflib.Scene(nodes=[0])], scene=0, nodes=[pygltflib.Node(mesh=0)], bufferViews=views,
        accessors=[pygltflib.Accessor(bufferView=0, componentType=pygltflib.FLOAT, count=3, type="VEC3", min=[0, 0, 0], max=[1, 1, 0])],
        images=[pygltflib.Image(bufferView=1 + index, mimeType="image/png") for index in range(count)],
        textures=[pygltflib.Texture(source=index) for index in range(count)],
        materials=[pygltflib.Material(pbrMetallicRoughness=pygltflib.PbrMetallicRoughness(baseColorTexture=pygltflib.TextureInfo(index=index)))
                   for index in range(count)],
        meshes=[pygltflib.Mesh(primitives=[pygltflib.Primitive(attributes=pygltflib.Attributes(POSITION=0), material=index)
                                           for index in range(count)])],
        buffers=[pygltflib.Buffer(byteLength=len(blob))])
    gltf.set_binary_blob(blob)
    gltf.save_binary(str(path))
    return path


def test_a_texture_decoded_into_confetti_is_dropped_and_real_art_stays(tmp_path):
    rng = np.random.default_rng(3)
    confetti = rng.random((16, 32, 3))                                          # a beard read with the wrong format
    stripes = np.zeros((16, 32, 3)); stripes[:, ::2] = [0.9, 0.85, 0.8]         # hard-edged stripes, mostly grey
    static = np.repeat(rng.random((16, 32, 1)), 3, axis=2)                      # a TV's snow: noisy but grey
    fur = 0.5 + 0.05 * rng.random((16, 32, 3)) * np.array([1.0, 0.6, 0.3])      # gentle grain on brown
    model = write_textured_glb(tmp_path / "ape.glb", [confetti, stripes, static, fur])
    assert noisy_images(pygltflib.GLTF2().load(str(model))) == {0}
    assert clean_glb(model, tmp_path / "ape.clean.glb") == ["1 of its materials were painted with decoding noise, now dropped"]
    paints = [material.pbrMetallicRoughness.baseColorTexture for material in pygltflib.GLTF2().load(str(tmp_path / "ape.clean.glb")).materials]
    assert paints[0] is None and [paint.index for paint in paints[1:]] == [1, 2, 3]
    fine = write_textured_glb(tmp_path / "fur.glb", [fur, stripes])
    assert clean_glb(fine, tmp_path / "fur.clean.glb") == [] and not (tmp_path / "fur.clean.glb").exists()
