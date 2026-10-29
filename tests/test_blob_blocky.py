"""Blocky people (voxel, roblox): our own boxes on the humanoid rig, a 64 x 64 picture, a face kit."""
import io
import json
import struct
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from services.anime_make import make_character, resolve_traits
from services.blob_blocky import SIZE, SHAPES, blocky_glb, blocky_parts, blocky_picture
from services.blob_face import face_kit
from services.blob_make import build_body

COLORS = {"skin": "#C8946A", "hair": "#3A2A1C", "top": "#2E6FB4", "bottom": "#2B3A5E", "shoes": "#222222"}


def _spec(kind, **extra):
    return {"blocky": kind, "height": 1.8, "blocky_colors": COLORS, **extra}


@pytest.mark.parametrize("kind", sorted(SHAPES))
def test_both_blocky_bodies_are_people_the_rig_accepts_with_uvs_inside_the_picture(kind):
    parts = {name: (mesh, uvs) for mesh, name, uvs in blocky_parts(_spec(kind))}
    body, uvs = parts["body"]
    assert len(uvs) == len(body.vertices) > 0 and len(parts["face"][0].vertices) == 6
    assert all(0.0 <= u <= 1.0 and 0.0 <= v <= 1.0 for u, v in uvs)
    resolved = resolve_traits({"style": kind, "gender": "boy"})
    built = build_body(resolved["body"], ["idle", "talk"])
    assert built["rigged"][:4] == b"glTF" and abs(built["faceAnchor"]["center"][1] - 1.5) < 0.2 and built["traits"]["mesh"] == "blocky"


def test_the_picture_is_made_from_the_colours_and_a_voxel_one_has_noise_a_roblox_one_has_none():
    voxel = Image.open(io.BytesIO(blocky_picture(_spec("voxel")))).convert("RGB")
    roblox = Image.open(io.BytesIO(blocky_picture(_spec("roblox")))).convert("RGB")
    assert voxel.size == roblox.size == (SIZE, SIZE)
    torso = lambda image: [image.getpixel((x, y)) for x in range(20, 28) for y in range(20, 32)]
    assert len(set(torso(voxel))) > 12, "pixel noise in the cloth"
    assert len(set(torso(roblox))) <= 12, "flat plastic with only a soft gradient"
    assert voxel.getpixel((12, 8))[0] < 100 and voxel.getpixel((12, 13))[0] > 150, "hair above, skin below on the head's front"


def test_make_character_writes_a_rigged_textured_body_and_a_blocky_kit_for_each_style():
    folder = Path(tempfile.mkdtemp())
    for kind in ("voxel", "roblox"):
        made = make_character(folder, "t", f"b-{kind}", f"i-{kind}", {"style": kind, "gender": "boy", "skin": "#C8946A"})
        glb = (folder / made["rigged_file"]).read_bytes()
        document = json.loads(glb[20:20 + struct.unpack_from("<I", glb, 12)[0]])
        names = [m["name"] for m in document["materials"]]
        assert {"body", "face"} <= set(names) and len(document["images"]) == 2
        nearest = 9728 if kind == "voxel" else 9729
        assert all(s["magFilter"] == nearest for s in document["samplers"])
        assert made["faceTraits"]["style"] == "blocky" and made["character"]["style"] == kind and set(made["poses"]) >= {"neutral", "happy", "shout"}


def test_the_blocky_kit_has_the_eleven_poses_the_nine_mouths_and_a_blink_that_differ():
    for kind in ("voxel", "roblox"):
        kit = face_kit({"style": "blocky", "blocky": kind, "skin": "#C8946A", "eyeColor": "#3a6ad8", "hairColor": "#3a2a1c"})
        assert len(kit["poses"]) == 11 and len(kit["mouths"]) == 9 and kit["face"]["fit"] == [0.5, 0.5, 0.5, 0.5]
        bytes_of = lambda image: image.tobytes()
        assert len({bytes_of(image) for image in kit["poses"].values()}) >= 9, "the expressions are distinguishable"
        assert len({bytes_of(image) for image in kit["mouths"].values()}) == 9
        assert bytes_of(kit["blinks"]["neutral"]) != bytes_of(kit["poses"]["neutral"])


def test_a_blocky_body_takes_a_workspace_picture_and_refuses_a_head_picture():
    folder = Path(tempfile.mkdtemp())
    Image.new("RGB", (64, 64), (200, 30, 30)).save(folder / "skin.png")
    made = make_character(folder, "t", "red", "i-red", {"style": "voxel", "texture": "skin.png"})
    assert made["texture_file"] == "skin.png"
    with pytest.raises(Exception):
        resolve_traits({"style": "voxel", "texture": "skin.png", "texture_head": "head.png"})
