"""Diorama set pieces: a house block wearing its facade, a tiled ground slab, a facade freed of its backdrop."""
import numpy as np
import pygltflib
import pytest
from PIL import Image, ImageDraw

from services.diorama_set import DEPTH, build_ground, build_house, trim_border


def facade(path, size=(300, 400), margin=0, backdrop=(236, 236, 236), base=None):
    """A terracotta facade with a window, on a grey or white backdrop ``margin`` px wide (and a pavement band)."""
    picture = Image.new("RGB", size, backdrop)
    draw = ImageDraw.Draw(picture)
    draw.rectangle((margin, margin, size[0] - margin - 1, size[1] - 1), fill=(200, 110, 60))
    draw.rectangle((size[0] // 3, size[1] // 3, size[0] // 2, size[1] // 2), fill=(40, 60, 120))
    if base:
        draw.rectangle((0, size[1] - base, size[0], size[1]), fill=(120, 110, 100))
    picture.save(path)
    return path


def attribute(gltf, index, width):
    accessor = gltf.accessors[index]
    view = gltf.bufferViews[accessor.bufferView]
    data = gltf.binary_blob()[view.byteOffset:view.byteOffset + view.byteLength]
    return np.frombuffer(data, dtype=np.float32).reshape(-1, width)


def bounds(path):
    gltf = pygltflib.GLTF2().load(str(path))
    position = attribute(gltf, gltf.meshes[0].primitives[0].attributes.POSITION, 3)
    return gltf, position.min(axis=0).tolist(), position.max(axis=0).tolist()


def test_a_house_is_a_box_as_wide_as_its_trimmed_facade_standing_on_its_front_edge(tmp_path):
    size = build_house(tmp_path / "house.glb", facade(tmp_path / "f.png", margin=30), 8)
    assert size == {"width": round(8 * 240 / 370, 3), "height": 8.0}
    gltf, low, high = bounds(tmp_path / "house.glb")
    assert low == pytest.approx([-size["width"] / 2, 0, -DEPTH]) and high == pytest.approx([size["width"] / 2, 8, 0])
    assert gltf.accessors[gltf.meshes[0].primitives[0].indices].count == 30, "front, two sides, back and roof"
    assert gltf.images[0].mimeType == "image/png" and gltf.samplers[0].wrapS == pygltflib.CLAMP_TO_EDGE


def test_a_facade_that_fills_its_picture_is_kept_whole_and_a_backdrop_is_cropped(tmp_path):
    full = Image.open(facade(tmp_path / "full.png"))
    assert trim_border(full).size == full.size
    framed = trim_border(Image.open(facade(tmp_path / "framed.png", margin=24, base=20)))
    assert framed.size == (300 - 48, 400 - 24), "the pavement band across the bottom is part of the facade"
    tinted = Image.open(facade(tmp_path / "tinted.png", margin=24, backdrop=(30, 120, 200)))
    assert trim_border(tinted).size == tinted.size, "only a grey or white backdrop is taken for a studio backdrop"


def test_the_ground_is_a_slab_with_its_top_at_zero_repeating_its_picture(tmp_path):
    Image.new("RGB", (64, 64), (180, 90, 50)).save(tmp_path / "tiles.png")
    assert build_ground(tmp_path / "ground.glb", tmp_path / "tiles.png", size=30, tile=3) == {"size": 30, "height": 0.2}
    gltf, low, high = bounds(tmp_path / "ground.glb")
    assert low == pytest.approx([-15, -0.2, -15]) and high == pytest.approx([15, 0, 15])
    uv = attribute(gltf, gltf.meshes[0].primitives[0].attributes.TEXCOORD_0, 2)
    assert uv[:4].max() == pytest.approx(10), "the top repeats the picture every 3 m"
    assert gltf.samplers[0].wrapS == pygltflib.REPEAT
