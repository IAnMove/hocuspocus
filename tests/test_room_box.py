"""Metric box rooms: a GLB in metres, and a CPU frame whose feet and door agree with a numpy pinhole."""
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")

from services.production_models import check_sets
from services.production_room_box import build, picture_jobs
from services.production_rooms import dry_run_images
from services.production_scene3d import resolve_media, validate_scene3d_shot
from services.room_box import build_room, camera_pose, check_box, image_count, is_box_room, normalize, placeholder_room

ROOT = Path(__file__).resolve().parents[1]
MOLD = {"kind": "room", "mold": "despacho", "skin": {"wall_back": {"image": "painted cabinets"}, "floor": {"texture": "parquet"}}}
BOX = {"kind": "room", "prompt": "a small kitchen", "size": {"w": 4, "d": 5}, "floor": "oak boards", "walls": "warm plaster"}


def _read(gltf, accessor):
    blob = gltf.binary_blob()
    acc = gltf.accessors[accessor]
    view = gltf.bufferViews[acc.bufferView]
    start = (view.byteOffset or 0) + (acc.byteOffset or 0)
    if acc.type == "VEC3":
        return np.frombuffer(blob[start:start + acc.count * 12], dtype="<f4").reshape(acc.count, 3).copy()
    return np.frombuffer(blob[start:start + acc.count * 2], dtype="<u2").copy()


def _part(path, name):
    gltf = pygltflib.GLTF2().load(path)
    index = next(i for i, material in enumerate(gltf.materials) if material.name == name)
    primitive = gltf.meshes[0].primitives[index]
    return gltf, gltf.materials[index], _read(gltf, primitive.attributes.POSITION), _read(gltf, primitive.attributes.NORMAL), _read(gltf, primitive.indices)


def test_a_box_is_not_a_mold_and_names_the_bad_field():
    assert is_box_room(BOX) and not is_box_room(MOLD) and not is_box_room({"kind": "room", "mold": "sala", "size": {"w": 4, "d": 5}})
    spec = normalize(BOX)
    assert spec["size"] == {"w": 4, "d": 5, "h": 2.6} and spec["door"] == {"wall": "back", "x": 0, "w": 0.9, "h": 2}
    assert camera_pose(5) == {"eye": [0.0, 1.6, -3.35], "look": [0.0, 1.15, 0.75], "fov": 48.0}
    assert check_box("k", {**BOX, "door": None}) == "sets.k: door: null is not a door; omit it for a 0.9×2.0 door on the back wall"
    assert "open side" in check_box("k", {**BOX, "door": {"wall": "front"}})
    assert "no mold" in check_box("k", MOLD)
    with pytest.raises(ValueError, match="outside the floor"):
        normalize({**BOX, "props": [{"prompt": "a chair", "on": "floor", "x": 9, "z": 0, "height_m": 1}]})


def test_the_glb_is_an_open_box_in_metres_with_a_door_hole(tmp_path):
    target = tmp_path / "room.glb"
    build_room(target, {**BOX, "props": [{"prompt": "a clock", "wall": "back", "x": 1, "height_m": 0.4}]})
    gltf = pygltflib.GLTF2().load(target)
    assert gltf.asset.generator == "hocuspocus room_box"
    assert all(material.doubleSided and material.pbrMetallicRoughness.metallicFactor == 0 for material in gltf.materials)
    _gltf, _material, floor, floor_normals, _indices = _part(target, "floor")
    assert np.allclose(floor[:, 1], 0) and np.all(floor_normals[:, 1] > 0.9)
    _gltf, door_material, door, _normals, _indices = _part(target, "door")
    assert door[:, 1].min() == pytest.approx(0) and door[:, 1].max() == pytest.approx(2)
    assert door[:, 2].mean() == pytest.approx(2.48, abs=0.01)
    assert door_material.alphaMode == "OPAQUE"
    _gltf, wall_material, walls, normals, indices = _part(target, "walls")
    # Side walls meet the back wall at x = ±w/2, so only the interior of the back plane is the back wall.
    back = (np.abs(walls[:, 2] - 2.5) < 0.02) & (np.abs(walls[:, 0]) < 1.9)
    assert back.any() and np.all(normals[back][:, 2] < -0.9)
    assert len(indices) > 18 and wall_material.alphaMode == "OPAQUE"
    _gltf, prop, prop_points, _normals, _indices = _part(target, "prop-1")
    assert prop.alphaMode == "BLEND" and prop_points[:, 1].max() == pytest.approx(0.4)
    bare = tmp_path / "bare.glb"
    placeholder_room(bare, BOX)
    assert bare.stat().st_size > 100


def test_production_keeps_mold_counts_and_does_not_paint_the_place_into_a_texture(tmp_path, monkeypatch):
    assert dry_run_images({}) == {}
    assert dry_run_images({"sets": {"office": MOLD}}) == {"room_skin_images": 2, "room_sets": {"office": 2}}
    counted = dry_run_images({"sets": {"office": MOLD, "kitchen": {**BOX, "ceiling": "white paint", "props": [{"prompt": "a stool", "floor": True, "x": 1, "z": 1, "height_m": 0.5}]}}})
    assert counted["room_skin_images"] == 2 and counted["room_sets"] == {"office": 2}
    assert counted["room_box_images"] == 4 and counted["room_box_sets"]["kitchen"] == 4
    assert image_count({"kind": "room"}) == 0
    check_sets({"sets": {"kitchen": BOX, "office": MOLD}})
    with pytest.raises(ValueError, match="sets.kitchen: door"):
        check_sets({"sets": {"kitchen": {**BOX, "door": {"wall": "open"}}}})

    calls = []

    class Production:
        id = "batch"
        root = tmp_path
        state = {"sets": {"kitchen": {}}}

        def _attempt(self, *_args):
            return 1

        def image(self, *args):
            calls.append(args)
            return f"job-{len(calls)}"

        def log(self, *_args):
            return None

        ws = "w"

    entry = {**BOX, "props": [{"prompt": "a blue jug", "on": "floor", "x": 0.4, "z": 0.2, "height_m": 0.3}]}
    jobs = picture_jobs(Production(), "kitchen", entry, "layered paper collage", ("from-production",))
    assert set(jobs) == {"set:kitchen:floor", "set:kitchen:walls", "set:kitchen:prop-1"}
    prompts = [call[1] for call in calls]
    assert all("a small kitchen" not in prompt and "layered paper" not in prompt for prompt in prompts)
    assert all(call[5] == "from-production" for call in calls)
    assert {call[3] for call in calls} == {"1024x1024", "768x1024"}
    from PIL import Image
    for name in ("floor.png", "walls.png", "prop.png"):
        Image.new("RGB", (32, 32), (20, 40, 60)).save(tmp_path / name)
    record = {"entry": entry, "pictures": {"floor": "floor.png", "walls": "walls.png", "prop-1": "prop.png"}}
    build(Production(), "kitchen", record)
    assert record["file"] == "set-batch-kitchen.glb" and record["roomBox"]["door"]["h"] == 2
    assert (tmp_path / record["file"]).is_file() and "error" not in record
    resolved = resolve_media(
        {"template": "two-shot", "background": "kitchen", "subject": "https://example.test/hero.glb"},
        stills={}, root=tmp_path, workspace="w", sets={"kitchen": {"roomBox": record["roomBox"], "url": record["url"]}},
    )
    assert resolved["background"]["roomBox"]["size"]["d"] == 5 and resolved["background"]["file"] == record["url"]
    validate_scene3d_shot({"scene3d": {"template": "two-shot", "background": {"roomBox": normalize(BOX)}}})
    with pytest.raises(ValueError, match="subject GLB"):
        validate_scene3d_shot({"scene3d": {"template": "two-shot"}})


def _project(point, eye, look, fov, aspect):
    """A pinhole that does not call the TypeScript projector."""
    eye = np.asarray(eye, float)
    forward = np.asarray(look, float) - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, np.array([0.0, 1.0, 0.0]))
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    rel = np.asarray(point, float) - eye
    cam_x, cam_y, cam_z = np.dot(rel, right), np.dot(rel, up), np.dot(rel, forward)
    focal = 1 / np.tan(np.deg2rad(fov) / 2)
    ndc_x = (cam_x * focal) / (aspect * cam_z)
    ndc_y = (cam_y * focal) / cam_z
    return (ndc_x + 1) / 2, 1 - (ndc_y + 1) / 2


def test_feet_land_on_the_floor_the_numpy_pinhole_predicts():
    tsx = ROOT / "ui" / "node_modules" / ".bin" / "tsx"
    raw = subprocess.check_output(
        [str(tsx), "--tsconfig", "tsconfig.app.json", "scripts/room-box-proof.mjs"],
        cwd=ROOT / "ui", text=True,
    )
    data = json.loads(raw)
    aspect = data["width"] / data["height"]
    x, y = _project(data["point"], data["eye"], data["look"], data["fov"], aspect)
    # The foot is the bottom of the quad. The head leans in perspective, so the body's box centre is not the foot.
    half = max(0.22, 1.75 * 0.18)
    edges = [_project([1.2 + side * half, 0, 2.48], data["eye"], data["look"], data["fov"], aspect)[0] * data["width"] for side in (-1, 1)]
    assert abs(y * data["height"] - data["adult"]["maxY"]) <= 2
    assert abs(max(edges) - (data["adult"]["maxX"] + 0.5)) <= 2
    assert data["adult"]["minX"] <= x * data["width"] <= data["adult"]["maxX"]
    assert x < 0.5
    ratio = data["adult"]["height"] / data["door"]["height"]
    assert abs(ratio - 0.875) <= 0.03
    assert data["near"]["height"] > data["adult"]["height"]
    assert data["adult"]["maxY"] < data["near"]["maxY"]
    assert data["below"] in ([196, 164, 112], [148, 108, 68])
    _door_x, door_foot = _project([0, 0, 2.48], data["eye"], data["look"], data["fov"], aspect)
    _door_x, door_head = _project([0, 2, 2.48], data["eye"], data["look"], data["fov"], aspect)
    _adult_x, adult_head = _project([1.2, 1.75, 2.48], data["eye"], data["look"], data["fov"], aspect)
    predicted = abs(door_foot - adult_head) / abs(door_foot - door_head)
    # The camera looks slightly down, so a 1.75 m body beside a 2.0 m door is not exactly 0.875 on screen.
    assert abs(predicted - 0.875) <= 0.03
    assert abs(predicted - ratio) <= 0.01


KITCHEN = {**BOX, "props": [{"prompt": "a chair", "on": "floor", "x": 0, "z": 0, "height_m": 0.9}]}


def test_series_stands_on_the_floor_and_refuses_the_door_and_the_furniture():
    from services.series_room_box import cutout_scale, foreign_room, shot_problems
    from services.series_sets import inherit_shot, script_scene3d
    from services.series_shot3d import _setup, normalize_scene3d
    series = {"rooms": {"kitchen": KITCHEN}, "locations": [{"id": "office", "set3d": {"mold": "despacho"}}]}
    chair = {"kind": "3d", "set": "kitchen", "cast": [{"characterId": "ana", "at": {"x": 0, "z": 0}}]}
    assert any("furniture" in item for item in shot_problems(chair, series, None, {}))
    clear = {"kind": "3d", "set": "kitchen", "cast": [{"characterId": "ana", "at": {"x": 1.2, "z": 1}, "heightM": 1.75}]}
    assert shot_problems(clear, series, None, {}) == []
    outside = {"kind": "3d", "set": "kitchen", "cast": [{"characterId": "ana", "at": {"x": 3, "z": 0}}]}
    assert any("outside the room floor" in item for item in shot_problems(outside, series, None, {}))
    on_door = {"kind": "3d", "set": "kitchen", "cast": [{"characterId": "ana", "at": {"x": 0, "z": 2.4}}]}
    assert any("stands on the door" in item for item in shot_problems(on_door, series, None, {}))
    far = {"kind": "3d", "set": "kitchen", "cast": [{"characterId": "ana", "at": "far"}]}
    assert shot_problems(far, series, None, {}) == []
    missing = {"kind": "3d", "cast": [{"characterId": "ana", "at": {"x": 0, "z": 0}}]}
    assert any("names set" in item for item in shot_problems(missing, series, None, {}))
    assert foreign_room({"kind": "2d", "set": "kitchen"}) == "set is only for a 3d shot"
    assert any("mold room" in item for item in shot_problems(clear, series, None, series["locations"][0]))
    half = {"kind": "3d", "set": "kitchen", "cast": [{"characterId": "ana", "at": {"x": 1}}]}
    assert any("at is" in item for item in shot_problems(half, series, None, {}))
    dressed = script_scene3d(clear, {}, series=series)
    assert dressed["roomBox"]["size"]["h"] == 2.6 and dressed["cast"][0]["at"] == {"x": 1.2, "z": 1}
    room = next(item for item in dressed["objects"] if item["objectId"] == "room-box")
    assert room["scale"] == round(2.6 / 1.7, 4) and room["grounded"] is False
    stored = normalize_scene3d(dressed)
    assert stored["roomBox"]["size"]["d"] == 5 and stored["cast"][0]["heightM"] == 1.75
    setup = _setup("w", None, stored, [], lambda *_args: RuntimeError("unused"), [])
    assert setup["camera"]["eye"] == [0.0, 1.6, -3.35] and setup["camera"]["fov"] == 48.0
    assert setup["bindings"][0]["position"] == [1.2, 0, 1] and setup["bindings"][0]["grounded"] is True
    assert setup["bindings"][1]["grounded"] is False
    assert cutout_scale({}) == {} and cutout_scale({"heightM": 1.75})["scale"] == 1.75 / 2
    boxed = {"productionMethod": "animation_3d", "set": "kitchen", "locationId": "office", "scene3d": dressed}
    assert inherit_shot(series, boxed) is boxed and "roomSet" not in boxed["scene3d"]


def test_room_put_stores_a_placeholder_and_replays_the_same_intent(tmp_path, monkeypatch):
    import asyncio
    from fastapi import HTTPException
    from services import core_workspace
    from services.room_box_commands import GET, PUT, command_handlers, run
    from services.set_commands import command_catalog
    monkeypatch.setattr(core_workspace, "outputs_root", lambda: tmp_path)
    assert command_catalog()[0]["name"] == "scene3d.sets.catalog"
    body = {"version": 1, "intent_id": "room-1", "input": {"workspace": "default", "name": "kitchen", "room": BOX}}
    first = run(PUT, body)
    assert first["result"]["file"] == "rooms/kitchen.glb"
    assert (tmp_path / "rooms" / "kitchen.glb").stat().st_size > 100
    assert run(PUT, body)["result"] == first["result"]
    changed = {**body, "input": {**body["input"], "room": {**BOX, "floor": "stone"}}}
    with pytest.raises(HTTPException) as conflict:
        run(PUT, changed)
    assert conflict.value.status_code == 409
    read = asyncio.run(command_handlers()[GET]({"version": 1, "input": {"workspace": "default", "name": "kitchen"}}))
    assert read["result"]["room"]["door"]["h"] == 2
    with pytest.raises(HTTPException) as bad_name:
        run(PUT, {**body, "intent_id": "room-2", "input": {**body["input"], "name": "../kitchen"}})
    assert bad_name.value.status_code == 422
