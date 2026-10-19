"""A painted plate as the back wall of a metric box room: the numbers, the GLB, the extension and the camera range."""
import io
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

pygltflib = pytest.importorskip("pygltflib")

from services import room_plate, room_plate_extend
from services.room_box import build_room, normalize, prop_point

OFFICE = {"horizon": 0.22, "ref": {"baseY": 0.72, "heightPct": 0.62, "heightM": 2.0}}
SILOS = {"horizon": 0.51, "ref": {"baseY": 0.648, "heightPct": 0.176, "heightM": 2.0}}
BACK = {"file": "plate.png", "w": 1920, "h": 1088}


def _plate_picture(size=(960, 544)):
    """A plate with a sky, a wall band, a door and a floor with board lines, so every edge has something to continue."""
    image = Image.new("RGB", size, (150, 160, 90))
    draw = ImageDraw.Draw(image)
    width, height = size
    draw.rectangle([0, int(height * 0.72), width, height], fill=(96, 52, 30))
    for row in range(int(height * 0.74), height, max(6, height // 40)):
        draw.line([0, row, width, row], fill=(60, 30, 18), width=2)
    draw.rectangle([int(width * 0.40), int(height * 0.10), int(width * 0.58), int(height * 0.72)], fill=(110, 60, 30))
    draw.rectangle([0, 0, width, int(height * 0.04)], fill=(70, 45, 28))
    return image


def _room(stage=OFFICE, **extra):
    entry = {"kind": "room", "prompt": "an office", "floor": "the floor of the plate", "walls": "the walls of the plate",
             "plate": {"back": BACK, "stage": stage}, **extra}
    return normalize(entry)


def _gltf(tmp_path, spec, textures=None):
    target = tmp_path / "room.glb"
    build_room(target, spec, textures or {"plate": {"back": _plate_picture()}})
    return pygltflib.GLTF2().load(target)


def _accessor(gltf, index):
    accessor = gltf.accessors[index]
    view = gltf.bufferViews[accessor.bufferView]
    start = (view.byteOffset or 0) + (accessor.byteOffset or 0)
    width = {"VEC3": 3, "VEC2": 2, "SCALAR": 1}[accessor.type]
    dtype = "<u2" if accessor.type == "SCALAR" else "<f4"
    return np.frombuffer(gltf.binary_blob()[start:start + accessor.count * width * np.dtype(dtype).itemsize], dtype=dtype).reshape(accessor.count, width).copy()


def _part(gltf, name):
    index = next(i for i, material in enumerate(gltf.materials) if material.name == name)
    primitive = gltf.meshes[0].primitives[index]
    return gltf.materials[index], _accessor(gltf, primitive.attributes.POSITION), _accessor(gltf, primitive.attributes.TEXCOORD_0)


def _pinhole(point, camera, aspect):
    """The plate's own camera, written out on its own: a level lens looking along +z whose picture is lifted by ``lensShift``."""
    eye = np.asarray(camera["eye"], float)
    forward = np.asarray(camera["look"], float) - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0.0, 1.0, 0.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    rel = np.asarray(point, float) - eye
    x, y, z = rel @ right, rel @ up, rel @ forward
    focal = 1 / math.tan(math.radians(camera["fov"]) / 2)
    return (x * focal / (aspect * z) + 1) / 2, (1 - y * focal / z) / 2 - camera["lensShift"]


# ---------------------------------------------------------------- the numbers


def test_the_stage_fixes_the_camera_height_the_card_and_the_floor_in_metres():
    spec = _room()
    plate, size = spec["plate"], spec["size"]
    assert spec["door"] is None and spec["windows"] == [] and "ceiling" not in spec
    # The camera is as high as the metres between the reference's foot and the horizon (series_stage.eye_height_m).
    assert plate["metres"]["eye_height"] == pytest.approx((0.72 - 0.22) * 2.0 / 0.62, abs=1e-3)
    assert plate["camera"]["lensShift"] == pytest.approx(0.28) and plate["camera"]["fov"] == 48.0
    # The card stands on the floor at the camera's distance; the room is as deep as that distance and as tall as the card.
    assert size["d"] == pytest.approx(plate["metres"]["distance"]) and plate["camera"]["eye"][2] == pytest.approx(-size["d"] / 2)
    assert size["w"] / size["h"] == pytest.approx(1920 / 1088 * 1 / 0.72, abs=1e-3)
    camera, aspect = plate["camera"], 1920 / 1088
    door_foot = _pinhole([0, 0, size["d"] / 2], camera, aspect)[1]
    door_head = _pinhole([0, 2.0, size["d"] / 2], camera, aspect)[1]
    assert door_foot == pytest.approx(0.72, abs=1e-4)
    assert door_foot - door_head == pytest.approx(0.62, abs=1e-4), "a 2 m door is 62 % of the plate, as the stage says"
    near = plate["visible"]["near_z"]
    assert _pinhole([0, 0, near], camera, aspect)[1] == pytest.approx(1.0, abs=1e-3), "the nearest floor is the bottom row"
    assert room_plate.eye_note(plate["stage"]) is None and "camera 4.50 m" in room_plate.eye_note({**OFFICE, "horizon": 0.0, "ref": {"baseY": 0.9, "heightPct": 0.4, "heightM": 2.0}})


def test_the_farthest_floor_moves_the_card_back():
    plain = _room()["plate"]
    far = _room({**OFFICE, "floorTop": 0.62})["plate"]
    assert far["metres"]["eye_height"] == plain["metres"]["eye_height"] and far["metres"]["distance"] > plain["metres"]["distance"]
    spec = normalize({"kind": "room", "prompt": "p", "floor": "f", "walls": "w", "plate": {"back": BACK, "stage": {**OFFICE, "floorTop": 0.62}}})
    row = _pinhole([0, 0, spec["size"]["d"] / 2], spec["plate"]["camera"], 1920 / 1088)[1]
    assert row == pytest.approx(0.62, abs=1e-4), "the card meets the floor where the stage says the floor ends"


def test_a_plate_with_no_stage_assumes_a_camera_at_eye_height_and_says_so():
    spec = normalize({"kind": "room", "prompt": "p", "floor": "f", "walls": "w", "plate": {"back": BACK}})
    assert spec["plate"]["stage_assumed"] is True and spec["plate"]["metres"]["eye_height"] == pytest.approx(1.6)
    assert normalize(spec) == spec, "a stored room normalises to itself, and stays assumed"
    stated = normalize({**{k: v for k, v in spec.items() if k != "size"}, "plate": {**spec["plate"], "stage": OFFICE, "stage_assumed": False}})
    assert stated["plate"]["stage_assumed"] is False


def test_the_derived_numbers_are_recomputed_not_trusted():
    spec = _room()
    tampered = {**spec, "plate": {**spec["plate"], "camera": {"eye": [9, 9, 9], "look": [0, 0, 0], "fov": 10, "lensShift": 0.0},
                                  "metres": {"eye_height": 9, "distance": 9, "plate_w": 9, "plate_h": 9, "top": 9}}}
    assert normalize(tampered) == spec
    with pytest.raises(ValueError, match="size comes from the plate"):
        normalize({**spec, "size": {"w": 4, "d": 4, "h": 2.6}})


@pytest.mark.parametrize("bad, message", [
    ({"plate": {"left": BACK}}, "plate.back"),
    ({"plate": {"back": {"file": "p.png"}}}, "plate.back is a workspace picture"),
    ({"plate": {"back": BACK, "stage": {"horizon": 0.8, "ref": {"baseY": 0.5, "heightPct": 0.3}}}}, "below the horizon"),
    ({"plate": {"back": BACK, "stage": {"horizon": 0.2}}}, "stage is"),
    ({"plate": {"back": BACK, "fov": 5}}, "fov is a number"),
    ({"plate": {"back": BACK, "range": {"orbit": 3}}}, "range is"),
    ({"plate": {"back": BACK, "stage": {"horizon": 0.4, "ref": {"baseY": 0.5, "heightPct": 0.01, "heightM": 2}}}}, "re-read the horizon"),
    ({"plate": {"back": BACK}, "windows": [{"wall": "back", "x": 0, "y": 1, "w": 1, "h": 1}]}, "windows and ceiling"),
    ({"plate": {"back": BACK}, "props": [{"prompt": "a desk", "on": "floor", "x": 0, "z": 0, "height_m": 1}]}, "needs image"),
    ({"plate": {"back": BACK}, "walls": {"back": {"file": "x.png"}}}, "walls is a picture"),
])
def test_a_bad_plate_names_the_field(bad, message):
    entry = {"kind": "room", "prompt": "p", "floor": "f", "walls": "w", **bad}
    with pytest.raises(ValueError, match=message):
        normalize(entry)


def test_prepare_reads_every_picture_and_gathers_the_plate_options():
    seen = []

    def resolve(ref):
        seen.append(ref)
        return {"file": next(iter(ref.values())), "w": 1920, "h": 1088}

    raw = {"kind": "room", "prompt": "an office", "walls": {"back": {"file": "a.png"}, "left": {"asset": "b.png"}},
           "stage": OFFICE, "fov": 40, "range": {"shift_m": 0.4},
           "props": [{"prompt": "a column", "on": "floor", "x": 0.5, "z": 1, "height_m": 2.0, "image": {"file": "col.png"}}]}
    room = room_plate.prepare(raw, resolve)
    assert room["plate"]["back"]["file"] == "a.png" and room["plate"]["left"]["file"] == "b.png"
    assert room["plate"]["fov"] == 40 and "stage" not in room and room["props"][0]["image"]["file"] == "col.png"
    spec = normalize(room)
    assert spec["plate"]["range"] == {"orbit_deg": 25.0, "shift_m": 0.4} and spec["plate"]["camera"]["fov"] == 40.0
    assert len(seen) == 3
    with pytest.raises(ValueError, match="belongs to a room whose walls is a picture"):
        room_plate.prepare({"kind": "room", "prompt": "p", "walls": "words", "stage": OFFICE}, resolve)
    with pytest.raises(ValueError, match="size comes from the plate"):
        room_plate.prepare({**raw, "size": {"w": 4, "d": 4}}, resolve)
    with pytest.raises(ValueError, match="back wall's picture"):
        room_plate.prepare({**raw, "walls": {"left": {"file": "x.png"}}}, resolve)
    with pytest.raises(ValueError, match="walls is words"):
        room_plate.prepare({**raw, "walls": {"colour": "red"}}, resolve)


# ---------------------------------------------------------------- the GLB


def test_the_glb_is_a_closed_box_in_metres_of_unlit_pictures(tmp_path):
    spec = _room()
    gltf = _gltf(tmp_path, spec)
    size = spec["size"]
    assert [material.name for material in gltf.materials] == ["plate", "floor-plate", "floor", "wall-left", "wall-right", "ceiling"]
    assert gltf.extensionsUsed == ["KHR_materials_unlit"]
    assert all(material.extensions == {"KHR_materials_unlit": {}} and material.doubleSided for material in gltf.materials)
    low, high = np.full(3, np.inf), np.full(3, -np.inf)
    for primitive in gltf.meshes[0].primitives:
        points = _accessor(gltf, primitive.attributes.POSITION)
        low, high = np.minimum(low, points.min(axis=0)), np.maximum(high, points.max(axis=0))
    # fitGltf scales by 1.7 / the box's height and does not recentre it: the floor is y = 0 and the box is size.h tall.
    assert low[1] == pytest.approx(0, abs=1e-6) and high[1] == pytest.approx(size["h"], abs=1e-4)
    assert high[0] == pytest.approx(size["w"] / 2, abs=1e-4) and low[0] == pytest.approx(-size["w"] / 2, abs=1e-4)
    assert low[2] == pytest.approx(-size["d"] / 2, abs=1e-4) and high[2] == pytest.approx(size["d"] / 2, abs=1e-4)
    _material, card, _uv = _part(gltf, "plate")
    assert np.allclose(card[:, 2], size["d"] / 2) and card[:, 1].min() == 0 and card[:, 1].max() == pytest.approx(size["h"], abs=1e-4)
    # The card and the floor strip are one picture, kept once.
    assert len(gltf.images) == 5 and len(gltf.textures) == 5
    assert gltf.materials[0].pbrMetallicRoughness.baseColorTexture.index == gltf.materials[1].pbrMetallicRoughness.baseColorTexture.index
    assert Image.open(io.BytesIO(_image_bytes(gltf, 0))).size == (960, 544)


def _image_bytes(gltf, index):
    view = gltf.bufferViews[gltf.images[index].bufferView]
    start = view.byteOffset or 0
    return gltf.binary_blob()[start:start + view.byteLength]


@pytest.mark.parametrize("stage, fov", [(OFFICE, 48), (SILOS, 48), (OFFICE, 35), ({"horizon": 0.5, "ref": {"baseY": 0.8, "heightPct": 0.5, "heightM": 2.0}}, 60)])
def test_the_card_and_the_floor_strip_are_the_plate_as_its_own_camera_sees_it(tmp_path, stage, fov):
    spec = normalize({"kind": "room", "prompt": "p", "floor": "f", "walls": "w", "plate": {"back": BACK, "stage": stage, "fov": fov}})
    gltf = _gltf(tmp_path, spec)
    camera, aspect = spec["plate"]["camera"], 1920 / 1088
    for name in ("plate", "floor-plate"):
        _material, points, uvs = _part(gltf, name)
        for point, (u, v) in zip(points, uvs):
            seen_u, seen_v = _pinhole(point, camera, aspect)
            assert (seen_u, seen_v) == pytest.approx((u, v), abs=2e-4), (name, point)
    _material, strip, _uv = _part(gltf, "floor-plate")
    assert strip[:, 1].max() == 0 and strip[:, 2].min() == pytest.approx(spec["plate"]["visible"]["near_z"], abs=1e-3)


def test_the_extension_continues_the_plate_and_fades_away_from_it(tmp_path):
    picture = _plate_picture()
    extension = room_plate_extend.Plate(picture)
    inside = extension.sample(np.array([0.3]), np.array([0.5]))[0]
    base = np.asarray(picture.resize(extension.levels.shape[2:0:-1]), float)[int(0.5 * (extension.levels.shape[1] - 1)), int(0.3 * (extension.levels.shape[2] - 1)), :]
    assert np.allclose(inside, base, atol=2)
    edge, mirrored = extension.sample(np.array([-0.001]), np.array([0.4]))[0], extension.sample(np.array([0.001]), np.array([0.4]))[0]
    assert np.abs(edge - mirrored).max() < 8, "the colour at the picture's edge is the picture's"
    flat = room_plate_extend.Plate(Image.new("RGB", (120, 70), (120, 120, 120)))
    means = [flat.sample(np.array([-t]), np.array([0.5]))[0].mean() for t in (0.0, 0.1, 0.4, 1.0, 3.0)]
    assert means == sorted(means, reverse=True) and means[0] == pytest.approx(120, abs=1) and 55 < means[-1] < 65, "darker with distance, never black"
    checker = Image.fromarray((np.indices((96, 96)).sum(axis=0) // 8 % 2 * 200 + 20).astype(np.uint8)).convert("RGB")
    grain = room_plate_extend.Plate(checker)
    across = np.linspace(0.1, 0.9, 64)
    near = grain.sample(np.full_like(across, -0.02), across)[..., 0].std()
    far = grain.sample(np.full_like(across, -1.0), across)[..., 0].std()
    assert near > 3 * far, "and blurrier"
    assert room_plate_extend.dimming(np.array([0.0]))[0] == 1 and room_plate_extend.dimming(np.array([9.0]))[0] == pytest.approx(0.5)
    assert room_plate_extend.fold(np.array([1.25, -0.25, 2.1])).tolist() == pytest.approx([0.75, 0.25, 0.1])


def test_the_ceiling_and_walls_are_not_one_flat_colour(tmp_path):
    gltf = _gltf(tmp_path, _room())
    for index, name in enumerate(("floor", "wall-left", "wall-right", "ceiling")):
        pass
    for name in ("floor", "wall-left", "wall-right", "ceiling"):
        position = next(i for i, material in enumerate(gltf.materials) if material.name == name)
        view = gltf.bufferViews[gltf.images[gltf.textures[gltf.materials[position].pbrMetallicRoughness.baseColorTexture.index].source].bufferView]
        data = np.asarray(Image.open(io.BytesIO(gltf.binary_blob()[(view.byteOffset or 0):(view.byteOffset or 0) + view.byteLength])).convert("RGB"), float)
        assert data.std() > 4 and data.mean() > 20, name


def test_a_picture_for_a_side_wall_replaces_the_extension(tmp_path):
    left = Image.new("RGB", (64, 32), (200, 20, 20))
    gltf = _gltf(tmp_path, _room(), {"plate": {"back": _plate_picture(), "left": left}})
    position = next(i for i, material in enumerate(gltf.materials) if material.name == "wall-left")
    view = gltf.bufferViews[gltf.images[gltf.textures[gltf.materials[position].pbrMetallicRoughness.baseColorTexture.index].source].bufferView]
    shown = Image.open(io.BytesIO(gltf.binary_blob()[(view.byteOffset or 0):(view.byteOffset or 0) + view.byteLength])).convert("RGB")
    assert shown.size == (64, 32) and shown.getpixel((3, 3)) == (200, 20, 20)
    _material, points, _uv = _part(gltf, "wall-left")
    assert np.allclose(points[:, 0], _room()["size"]["w"] / 2), "left is the left of the frame: world +x, as every x in a room"


# ---------------------------------------------------------------- the props that hide a person


def _cutout(path, size=(200, 300), margin=20):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle([margin, margin, size[0] - margin, size[1] - margin], fill=(120, 80, 40, 255))
    image.save(path)
    return image


def test_a_prop_is_a_masked_card_with_real_depth_cropped_to_what_it_draws(tmp_path):
    spec = _room(props=[{"prompt": "a column", "on": "floor", "x": 0.6, "z": 0.9, "y": 0.1, "height_m": 1.8,
                         "image": {"file": "column.png", "w": 200, "h": 300}}])
    gltf = _gltf(tmp_path, spec, {"plate": {"back": _plate_picture()}, "props": [_cutout(tmp_path / "column.png")]})
    material, points, _uv = _part(gltf, "prop-1")
    assert material.alphaMode == "MASK" and material.alphaCutoff == 0.5 and material.extensions == {"KHR_materials_unlit": {}}
    assert np.allclose(points[:, 2], 0.9) and points[:, 2].max() < spec["size"]["d"] / 2, "in front of the card, at its own depth"
    assert points[:, 1].min() == pytest.approx(0.1) and points[:, 1].max() == pytest.approx(1.9)
    # Cropped to the drawn rectangle (161 x 261 pixels): width over height 0.617, centred on x = 0.6.
    assert points[:, 0].max() - points[:, 0].min() == pytest.approx(1.8 * 161 / 261, abs=1e-3)
    assert points[:, 0].mean() == pytest.approx(0.6, abs=1e-3)
    assert prop_point(spec["size"], spec["props"][0]) == (0.6, 0.0, 0.9)
    with pytest.raises(ValueError, match="needs its cut-out"):
        build_room(tmp_path / "bad.glb", spec, {"plate": {"back": _plate_picture()}})
    empty = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    with pytest.raises(ValueError, match="draws nothing"):
        build_room(tmp_path / "empty.glb", spec, {"plate": {"back": _plate_picture()}, "props": [empty]})


def test_a_cutout_in_an_ordinary_room_is_lit_and_masked_too(tmp_path):
    box = {"kind": "room", "prompt": "p", "size": {"w": 4, "d": 5}, "floor": "oak", "walls": "plaster",
           "props": [{"prompt": "a chair", "on": "floor", "x": 0, "z": 0, "height_m": 1.0, "image": {"file": "c.png", "w": 200, "h": 300}}]}
    gltf = _gltf(tmp_path, normalize(box), {"props": [_cutout(tmp_path / "c.png")]})
    material, points, _uv = _part(gltf, "prop-1")
    assert material.alphaMode == "MASK" and not material.extensions and points[:, 1].max() == pytest.approx(1.0)
    flat = normalize({**box, "props": [{k: v for k, v in box["props"][0].items() if k != "image"}]})
    assert _part(_gltf(tmp_path, flat, {}), "prop-1")[0].alphaMode == "BLEND", "a prop with no cut-out stays the placeholder it was"


# ---------------------------------------------------------------- standing and looking


def test_the_zones_are_floor_the_frame_shows():
    plate = _room()["plate"]
    zones = room_plate.zones(plate)
    assert plate["visible"]["near_z"] < zones["near"] < zones["mid"] < zones["far"] < plate["visible"]["far_z"]
    camera, aspect = plate["camera"], 1920 / 1088
    rows = [_pinhole([0, 0, zones[name]], camera, aspect)[1] for name in ("near", "mid", "far")]
    assert 0.72 < rows[2] < rows[1] < rows[0] < 1.0


def test_the_camera_range_says_camera_breaks_plate_only_outside_it():
    plate = _room()["plate"]
    held = room_plate.pose_of(plate, {"x": 0.4, "y": 0, "z": 0}, 20, 5)
    assert room_plate.camera_report(plate, held) == []
    assert room_plate.camera_report(plate, plate["camera"]) == []
    moved = room_plate.pose_of(plate, {"x": 0.9})
    report = room_plate.camera_report(plate, moved)
    assert report[0]["code"] == "camera_breaks_plate" and "0.90 m" in report[0]["message"] and report[0]["moved_m"] == pytest.approx(0.9)
    turned = room_plate.camera_report(plate, room_plate.pose_of(plate, None, 35, 0))
    assert turned[0]["code"] == "camera_breaks_plate" and "35 degrees" in turned[0]["message"]
    assert room_plate.camera_report(plate, {**plate["camera"], "fov": 70})[0]["code"] == "camera_breaks_plate"
    wide = normalize({"kind": "room", "prompt": "p", "floor": "f", "walls": "w", "plate": {"back": BACK, "range": {"shift_m": 1.5, "orbit_deg": 40}}})
    assert room_plate.camera_report(wide["plate"], room_plate.pose_of(wide["plate"], {"x": 0.9}, 35)) == []
