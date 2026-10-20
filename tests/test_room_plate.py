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
    assert means == sorted(means, reverse=True) and means[0] == pytest.approx(120, abs=1) and 60 < means[-1] < 80, "darker with distance, never black"
    checker = Image.fromarray((np.indices((96, 96)).sum(axis=0) // 8 % 2 * 200 + 20).astype(np.uint8)).convert("RGB")
    grain = room_plate_extend.Plate(checker)
    across = np.linspace(0.1, 0.9, 64)
    near = grain.sample(np.full_like(across, -0.02), across)[..., 0].std()
    far = grain.sample(np.full_like(across, -1.0), across)[..., 0].std()
    assert near > 3 * far, "and blurrier"
    assert room_plate_extend.dimming(np.array([0.0]))[0] == 1 and room_plate_extend.dimming(np.array([9.0]))[0] == pytest.approx(1 - room_plate_extend.DARKEN)
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


# ---------------------------------------------------------------- scene3d.room.put and paint with a picture


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    from services import core_workspace
    monkeypatch.setattr(core_workspace, "outputs_root", lambda: tmp_path)
    _plate_picture((1920, 1088)).save(tmp_path / "office.png")
    _plate_picture((800, 544)).save(tmp_path / "other.png")
    _cutout(tmp_path / "column.png")
    return tmp_path


def _put(name="office", room=None, intent=None):
    from services.room_box_commands import PUT, run
    base = {"kind": "room", "prompt": "an office", "walls": {"file": "office.png"}, "stage": OFFICE}
    return run(PUT, {"version": 1, "intent_id": intent or f"i-{name}", "input": {"workspace": "default", "name": name, "room": room or base}})["result"]


def test_put_reads_the_plate_builds_the_glb_and_keeps_what_it_was_made_from(workspace):
    from services import room_store
    result = _put()
    assert result["file"] == "rooms/office.glb" and (workspace / "rooms" / "office.glb").stat().st_size > 1000
    plate = result["room"]["plate"]
    assert plate["back"] == {"file": "office.png", "w": 1920, "h": 1088} and plate["camera"]["lensShift"] == pytest.approx(0.28)
    assert result["surfaces"]["plate"]["source"] == "plate" and result["surfaces"]["plate"]["file"] == "office.png"
    assert "warnings" not in result and result["paint"]["status"] == "not_painted"
    assert _put() == result, "the same intent returns what it returned"
    record = room_store.record_of(workspace, "office")
    assert record["surfaces"]["plate"]["sha"] and room_store.look_of(record) == result["paint"]["look"]
    gltf = pygltflib.GLTF2().load(workspace / "rooms" / "office.glb")
    assert gltf.extensionsUsed == ["KHR_materials_unlit"]


def test_put_without_a_stage_says_the_stage_is_assumed(workspace):
    result = _put("guess", {"kind": "room", "prompt": "an office", "walls": {"file": "office.png"}})
    assert [warning["code"] for warning in result["warnings"]] == ["stage_assumed"] and "stage {horizon" in result["warnings"][0]["message"]
    odd = _put("odd", {"kind": "room", "prompt": "an office", "walls": {"file": "office.png"},
                       "stage": {"horizon": 0.1, "ref": {"baseY": 0.95, "heightPct": 0.3, "heightM": 2.0}}})
    assert [warning["code"] for warning in odd["warnings"]] == ["eye_height"]


@pytest.mark.parametrize("room, message", [
    ({"walls": {"file": "missing.png"}}, "must be a file of this workspace"),
    ({"walls": {"file": "../outside.png"}}, "must be a file of this workspace"),
    ({"walls": {"asset": "https://example.test/a.png"}}, "must be a file of this workspace"),
    ({"walls": {"file": "office.png"}, "size": {"w": 4, "d": 4}}, "size comes from the plate"),
    ({"walls": {"file": "office.png"}, "windows": [{"wall": "back", "x": 0, "y": 1, "w": 1, "h": 1}]}, "windows and ceiling"),
    ({"walls": {"left": {"file": "office.png"}}}, "back wall's picture"),
    ({"walls": {"file": "office.png"}, "stage": {"horizon": 0.9}}, "stage is"),
    ({"walls": {"file": "office.png"}, "props": [{"prompt": "a desk", "on": "floor", "x": 0, "z": 0, "height_m": 1, "image": {"file": "nothing.png"}}]}, "must be a file"),
])
def test_put_names_what_is_wrong_with_a_plate(workspace, room, message):
    from fastapi import HTTPException
    (workspace / "notimage.png").write_text("not a picture")
    with pytest.raises(HTTPException) as error:
        _put(room={"kind": "room", "prompt": "an office", **room})
    assert error.value.status_code == 422 and message in error.value.detail
    with pytest.raises(HTTPException) as unreadable:
        _put(room={"kind": "room", "prompt": "an office", "walls": {"file": "notimage.png"}})
    assert "not an image" in unreadable.value.detail


def test_put_keeps_a_props_cutout_as_the_surface_it_stands_on(workspace):
    result = _put("columns", {"kind": "room", "prompt": "an office", "walls": {"file": "office.png"}, "stage": OFFICE,
                              "props": [{"prompt": "a column", "on": "floor", "x": 0.5, "z": 1.0, "height_m": 2.0, "image": {"file": "column.png"}}]})
    assert result["room"]["props"][0]["image"] == {"file": "column.png", "w": 200, "h": 300}
    material, points, _uv = _part(pygltflib.GLTF2().load(workspace / "rooms" / "columns.glb"), "prop-1")
    assert material.alphaMode == "MASK" and points[:, 1].max() == pytest.approx(2.0)


def test_paint_with_a_picture_replaces_the_plate_at_once_and_changes_the_look(workspace):
    from services.room_box_commands import PAINT, PAINT_STATUS, run
    first = _put()
    painted = run(PAINT, {"version": 1, "intent_id": "p1", "input": {"workspace": "default", "name": "office", "walls": {"file": "other.png"},
                                                                       "stage": {**OFFICE, "horizon": 0.3}}})["result"]
    assert painted["status"] == "completed" and painted["engine"] == "plate" and painted["look"] != first["paint"]["look"]
    assert painted["surfaces"]["plate"]["file"] == "other.png"
    status = run(PAINT_STATUS, {"version": 1, "input": {"workspace": "default", "name": "office"}})["result"]
    assert status["status"] == "completed" and status["look"] == painted["look"]
    from services.room_box_commands import get_room
    room = get_room("default", "office")["room"]
    assert room["plate"]["back"]["w"] == 800 and room["plate"]["stage"]["horizon"] == 0.3 and room["plate"]["camera"]["lensShift"] == pytest.approx(0.2)
    assert room["size"]["w"] / room["size"]["h"] != first["room"]["size"]["w"] / first["room"]["size"]["h"], "the room follows the new plate"
    again = run(PAINT, {"version": 1, "intent_id": "p1", "input": {"workspace": "default", "name": "office", "walls": {"file": "other.png"},
                                                                     "stage": {**OFFICE, "horizon": 0.3}}})["result"]
    assert again == painted


def test_paint_refuses_words_on_a_plate_and_a_picture_on_a_room_with_no_plate(workspace):
    from fastapi import HTTPException
    from services.room_box_commands import PAINT, PUT, run
    _put()
    with pytest.raises(HTTPException) as words:
        run(PAINT, {"version": 1, "intent_id": "p2", "input": {"workspace": "default", "name": "office", "floor": "oak boards"}})
    assert "nothing to paint with words" in words.value.detail
    with pytest.raises(HTTPException) as strange:
        run(PAINT, {"version": 1, "intent_id": "p3", "input": {"workspace": "default", "name": "office", "walls": {"file": "other.png"}, "style": "ink"}})
    assert "unknown style" in strange.value.detail
    run(PUT, {"version": 1, "intent_id": "i9", "input": {"workspace": "default", "name": "plain", "room": {
        "kind": "room", "prompt": "a kitchen", "size": {"w": 4, "d": 5}, "floor": "oak boards", "walls": "warm plaster"}}})
    with pytest.raises(HTTPException) as ordinary:
        run(PAINT, {"version": 1, "intent_id": "p4", "input": {"workspace": "default", "name": "plain", "walls": {"file": "other.png"}}})
    assert "not a plate room" in ordinary.value.detail


# ---------------------------------------------------------------- a Series shot in a plate room


def _series_shot(**extra):
    return {"kind": "3d", "set": "office", "cast": [{"characterId": "ana", "at": "mid"}], **extra}


def test_a_shot_stands_in_the_plate_the_camera_is_the_plates_and_people_stay_in_the_frame(workspace):
    from services.series_room_box import box_camera, dress_shot, place, plate_warnings, shot_problems, spec_of
    from services.series_shot3d import _setup, normalize_scene3d
    result = _put()
    spec = spec_of({"spec": result["room"]})
    plate = spec["plate"]
    camera = box_camera(spec)
    assert camera == {"family": "fixed", "eye": plate["camera"]["eye"], "look": plate["camera"]["look"], "fov": 48.0, "lensShift": pytest.approx(0.28)}
    assert place(spec, "near") == (0.0, room_plate.zones(plate)["near"]) and place(spec, {"x": 0.3, "z": 1}) == (0.3, 1.0)
    root = str(workspace)
    assert shot_problems(_series_shot(), None, root, {}) == []
    below = _series_shot(cast=[{"characterId": "ana", "at": {"x": 0, "z": -1.5}}])
    assert any("below the plate's frame" in item for item in shot_problems(below, None, root, {}))
    outside = _series_shot(cast=[{"characterId": "ana", "at": {"x": 9, "z": 1}}])
    assert any("outside the room floor" in item for item in shot_problems(outside, None, root, {}))
    dressed = dress_shot(_series_shot(), None, root, {})
    assert dressed["roomBox"]["plate"]["camera"]["lensShift"] == pytest.approx(0.28)
    room = next(item for item in dressed["objects"] if item["objectId"] == "room-box")
    assert room["scale"] == round(result["room"]["size"]["h"] / 1.7, 4) and room["grounded"] is False
    setup = _setup("w", None, normalize_scene3d({**dressed, "template": "two-shot"}), [], lambda *_args: RuntimeError("unused"), [])
    assert setup["camera"]["lensShift"] == pytest.approx(0.28) and setup["camera"]["eye"] == plate["camera"]["eye"]
    assert plate_warnings(_series_shot(), None, root) == []


def test_a_shot_that_moves_the_camera_past_the_range_is_warned_and_the_move_is_rendered(workspace):
    from services.series_room_box import box_camera, plate_warnings, spec_of
    from services.series_shot3d import _setup, normalize_scene3d
    spec = spec_of({"spec": _put()["room"]})
    held = _series_shot(scene3d={"camera": {"shift": {"x": 0.3}, "yaw": 10}})
    assert plate_warnings(held, None, str(workspace)) == []
    broken = _series_shot(scene3d={"camera": {"shift": {"x": 0.9}, "yaw": 40}})
    warnings = plate_warnings(broken, None, str(workspace))
    assert warnings[0]["code"] == "camera_breaks_plate" and warnings[0]["moved_m"] == pytest.approx(0.9)
    moved = box_camera(spec, {"shift": {"x": 0.3}, "yaw": 10})
    assert moved["eye"][0] == pytest.approx(0.3) and moved["look"][0] > moved["eye"][0] and moved["lensShift"] == pytest.approx(0.28)
    stored = normalize_scene3d({"template": "two-shot", "camera": {"shift": {"x": 0.3, "bad": 1, "y": "up"}, "yaw": 10, "pitch": 400, "extra": 1}})
    assert stored["camera"] == {"shift": {"x": 0.3}, "yaw": 10.0}
    assert "camera" not in normalize_scene3d({"template": "two-shot", "camera": {"yaw": "left"}})
    setup = _setup("w", None, {**stored, "roomBox": spec, "cast": []}, [], lambda *_args: RuntimeError("unused"), [])
    assert setup["camera"]["eye"][0] == pytest.approx(0.3)


def test_an_ordinary_room_keeps_every_camera_and_zone_it_had():
    from services.series_room_box import box_camera, place
    spec = normalize({"kind": "room", "prompt": "a kitchen", "size": {"w": 4, "d": 5}, "floor": "oak", "walls": "plaster"})
    assert box_camera(spec) == {"family": "fixed", "eye": [0.0, 1.6, -3.35], "look": [0.0, 1.15, 0.75], "fov": 48.0}
    assert box_camera(spec, {"shift": {"x": 3}}) == box_camera(spec) and place(spec, "far") == (0.0, 1.75)
    from services.world3d_scenes import _CAMERA_FIELDS
    assert "lensShift" in _CAMERA_FIELDS


def test_a_scene_patch_keeps_a_lens_shift_and_refuses_a_bad_one(tmp_path):
    import json
    from services.world3d_scenes import World3DSceneError, patch_scene
    workspace_dir = lambda name: str(tmp_path / name)  # noqa: E731
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True)
    document = {"templateId": "anime-impact-frame", "slots": [], "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0]}}
    (folder / "w3d-00000000beef.json").write_text(json.dumps({"revision": 1, "templateId": "anime-impact-frame", "document": document,
                                                                 "warnings": []}), encoding="utf-8")
    viewed = patch_scene("studio", "w3d-00000000beef", workspace_dir, {"camera": {"lensShift": 0.28}}, 1)
    assert viewed["document"]["camera"]["lensShift"] == 0.28 and viewed["document"]["camera"]["fov"] == 40
    for bad in ("high", True, 0.9, -0.6, float("nan")):
        with pytest.raises(World3DSceneError) as error:
            patch_scene("studio", "w3d-00000000beef", workspace_dir, {"camera": {"lensShift": bad}}, 2)
        assert error.value.code == "invalid_camera_lens_shift"


def test_a_scene_patch_sets_the_look_after_a_grade_and_a_plate_shot_asks_for_none(tmp_path):
    import json
    from services.series_shot3d import _setup, normalize_scene3d
    from services.world3d_scenes import World3DSceneError, patch_scene
    workspace_dir = lambda name: str(tmp_path / name)  # noqa: E731
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True)
    document = {"templateId": "anime-impact-frame", "slots": [], "look": {"toneMapping": "aces", "exposure": -0.5},
                "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0]}}
    (folder / "w3d-00000000beef.json").write_text(json.dumps({"revision": 1, "templateId": "anime-impact-frame", "document": document,
                                                                 "warnings": []}), encoding="utf-8")
    viewed = patch_scene("studio", "w3d-00000000beef", workspace_dir, {"grade": "noir", "look": {"toneMapping": "none"}}, 1)
    assert viewed["document"]["look"] == {"toneMapping": "none", "exposure": 0.0} and "look" in viewed["editable"]
    cleared = patch_scene("studio", "w3d-00000000beef", workspace_dir, {"look": None}, 2)
    assert "look" not in cleared["document"]
    for bad in ("none", {"toneMapping": "filmic"}, {"toneMapping": "none", "exposure": 9}, {"toneMapping": "none", "gamma": 1}, {"exposure": 0}):
        with pytest.raises(World3DSceneError) as error:
            patch_scene("studio", "w3d-00000000beef", workspace_dir, {"look": bad}, 3)
        assert error.value.code == "invalid_look"
    plate = {"kind": "room", "prompt": "p", "floor": "f", "walls": "w", "plate": {"back": BACK, "stage": OFFICE}}
    box = {"kind": "room", "prompt": "p", "size": {"w": 4, "d": 5}, "floor": "oak", "walls": "plaster"}
    fail = lambda *_args: RuntimeError("unused")  # noqa: E731
    assert _setup("w", None, {**normalize_scene3d({"template": "two-shot"}), "roomBox": normalize(plate), "cast": []}, [], fail, [])["look"] == {"toneMapping": "none", "exposure": 0}
    assert "look" not in _setup("w", None, {**normalize_scene3d({"template": "two-shot"}), "roomBox": normalize(box), "cast": []}, [], fail, [])


# ---------------------------------------------------------------- the real renderer (opt in: Chromium on the CPU)


@pytest.mark.skipif(not __import__("os").environ.get("HOCUSPOCUS_BROWSER_PROOF"),
                    reason="set HOCUSPOCUS_BROWSER_PROOF=1 to render through the owned World3D renderer in Chromium (SwiftShader, no GPU)")
def test_in_the_real_renderer_the_plate_comes_out_as_itself_and_a_prop_hides_a_person_behind_it(workspace):
    """The directional sprites of #1170 are depth tested; a masked prop of a plate room writes depth: behind it a person is hidden, in front
    of it a person covers it. The same frames show the lens shift and the unlit plate coming out of the app's own renderer."""
    import json
    import subprocess
    out = workspace / "proof"
    out.mkdir()
    plate_image = _plate_picture((1920, 1088))
    plate_image.save(workspace / "office.png")
    _cutout(workspace / "post.png", (200, 400), 0)
    room = {"kind": "room", "prompt": "an office", "walls": {"file": "office.png"}, "stage": OFFICE,
            "props": [{"prompt": "a post", "on": "floor", "x": 0.5, "z": 1.0, "height_m": 1.0, "image": {"file": "post.png"}}]}
    result = _put("proof", room)
    plate, size = result["room"]["plate"], result["room"]["size"]
    frames = [{"name": "none", "figures": []},
              {"name": "behind", "figures": [{"id": "behind", "x": 0.5, "z": 1.3, "heightM": 1.75}]},
              {"name": "front", "figures": [{"id": "front", "x": 0.5, "z": 0.6, "heightM": 1.75}]}]
    (out / "spec.json").write_text(json.dumps({"glb": str(workspace / result["file"]), "width": 1920, "height": 1088, "size": size,
                                               "camera": plate["camera"], "look": "default", "frames": frames}))
    root = Path(__file__).resolve().parents[1]
    run = subprocess.run([str(root / "ui" / "node_modules" / ".bin" / "tsx"), "--tsconfig", "tsconfig.app.json", "scripts/plate-room-proof.ts",
                          "--spec", str(out / "spec.json"), "--out", str(out)], cwd=root / "ui", capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stderr[-1500:] + run.stdout[-500:]
    frame = {name: np.asarray(Image.open(out / f"{name}.png").convert("RGB"), float) for name in ("none", "behind", "front")}
    shown = np.abs(frame["none"] - np.asarray(plate_image, float))
    camera = plate["camera"]
    corners = [_pinhole([0.5 + dx, y, 1.0], camera, 1920 / 1088) for dx in (-0.25, 0.25) for y in (0.0, 1.0)]
    left, right = int(min(c[0] for c in corners) * 1920) + 4, int(max(c[0] for c in corners) * 1920) - 4
    top, bottom = int(min(c[1] for c in corners) * 1088) + 4, int(max(c[1] for c in corners) * 1088) - 4
    # The post is a brown card in front of the plate, so the room-only frame differs from the plate inside it: compare everywhere else.
    others = np.ones(shown.shape[:2], bool)
    others[max(0, top - 6):bottom + 6, max(0, left - 6):right + 6] = False
    assert shown[others].mean() < 0.5 and np.percentile(shown[others], 99) <= 3, \
        "the room, staged as the app stages it, is the plate: lens shift, unlit, no tone mapping"

    def figure(name):
        return np.abs(frame[name] - frame["none"]).max(axis=2) > 12

    behind, front = figure("behind"), figure("front")
    inside = (slice(top, bottom), slice(left, right))
    keep = __import__("os").environ.get("HOCUSPOCUS_PROOF_OUT")
    if keep:
        Path(keep).mkdir(parents=True, exist_ok=True)
        for name in ("none", "behind", "front"):
            (Path(keep) / f"plate-room-{name}.png").write_bytes((out / f"{name}.png").read_bytes())
        print("figure pixels: behind above the post", int(behind[:top - 2].sum()), "over the post", int(behind[inside].sum()), "| front over the post", int(front[inside].sum()))
    assert behind[:top - 2].sum() > 3000, "the head and chest of the person behind the post are seen above it"
    assert behind[inside].sum() == 0, "and not one pixel of that person is painted over the post: the sprite is depth tested against the masked card"
    assert front[inside].sum() > 5000, "the person in front of the post covers it"
    assert front[:top].sum() > 3000
