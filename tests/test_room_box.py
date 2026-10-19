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
from services import room_materials
from services.game_tiles import seam_error
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


def _read_uv(gltf, accessor):
    blob = gltf.binary_blob()
    acc = gltf.accessors[accessor]
    view = gltf.bufferViews[acc.bufferView]
    start = (view.byteOffset or 0) + (acc.byteOffset or 0)
    return np.frombuffer(blob[start:start + acc.count * 8], dtype="<f4").reshape(acc.count, 2).copy()


def _picture_of(gltf, name):
    from io import BytesIO
    from PIL import Image
    index = next(i for i, material in enumerate(gltf.materials) if material.name == name)
    view = gltf.bufferViews[gltf.images[gltf.textures[gltf.materials[index].pbrMetallicRoughness.baseColorTexture.index].source].bufferView]
    start = view.byteOffset or 0
    return np.asarray(Image.open(BytesIO(gltf.binary_blob()[start:start + view.byteLength])).convert("RGB"))


def _spread(picture):
    """How much a picture varies: the largest standard deviation of its three channels."""
    return float(picture.std(axis=(0, 1)).max())


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


def test_every_material_repeats_without_a_seam_and_is_not_flat():
    """Periodic by construction: the wrap is as smooth as any pixel. 2.5 leaves room for a joint that lands on the wrap."""
    assert set(room_materials.MATERIALS) == {"plaster", "concrete", "wood_planks", "parquet", "metal_panels", "riveted_steel",
                                             "tile", "carpet", "brick", "stone", "linoleum"}
    for name in room_materials.MATERIALS:
        first = room_materials.make(name, 3)
        assert first.size == (512, 512) and first.tobytes() == room_materials.make(name, 3).tobytes(), name
        assert first.tobytes() != room_materials.make(name, 4).tobytes(), name
        assert seam_error(first) <= 2.5, (name, seam_error(first))
        assert np.asarray(first).std() > 3, name
        mosaic = np.tile(np.asarray(first), (2, 2, 1))
        edge = np.abs(mosaic[:, 511].astype(int) - mosaic[:, 512]).mean()
        assert edge < 25, (name, edge)
    leaf = room_materials.door_leaf("wood_planks", 1, None, 0.9, 2.0)
    assert leaf.size[1] > leaf.size[0] * 2 and leaf.size[0] == round(0.9 * 512 / 1.2)


def test_a_surface_names_its_material_from_its_words():
    pick = room_materials.pick
    assert pick("floor", "linóleo gastado verde")["material"] == "linoleum"
    assert pick("floor", "linóleo gastado verde")["color"] == "#6c9670"
    walls = pick("walls", "paneles metálicos remachados color crema")
    assert walls["material"] == "riveted_steel" and walls["color"] == "#e8debe" and walls["tile_m"] == 2.4
    assert pick("floor", "oak parquet")["material"] == "parquet" and pick("floor", "oak parquet")["color"] == "#ae804e"
    assert pick("walls", "red brick")["material"] == "brick"
    assert pick("walls", "rugged cliffs")["material"] == "plaster", "'rug' is a word, not the start of 'rugged'"
    assert pick("floor", "")["material"] == "wood_planks" and pick("walls", "")["material"] == "plaster"
    assert pick("walls", "dark green paint")["color"] == room_materials.hex_of((65, 90, 67))
    assert pick("walls", "", "stone hall")["material"] == "stone", "the style decides only when the words name nothing"
    defaults = room_materials.defaults_for({"floor": "oak boards", "walls": "welded steel plates"})
    assert defaults["door"]["material"] == "metal_panels" and defaults["trim"]["material"] == "metal_panels"


def test_no_room_is_flat_and_every_surface_has_its_own_scale(tmp_path):
    spec = {**BOX, "ceiling": "white plaster", "floor": "oak parquet", "walls": "red brick"}
    target = tmp_path / "room.glb"
    build_room(target, spec)
    gltf = pygltflib.GLTF2().load(target)
    for name in ("floor", "walls", "ceiling", "door", "trim"):
        assert _spread(_picture_of(gltf, name)) > 2, name
    index = next(i for i, material in enumerate(gltf.materials) if material.name == "floor")
    floor_u = _read_uv(gltf, gltf.meshes[0].primitives[index].attributes.TEXCOORD_0)[:, 0].max()
    assert floor_u == pytest.approx(4 / 1.2, abs=0.01), "parquet repeats every 1.2 m, not every 3"
    flat = tmp_path / "flat.glb"
    placeholder_room(flat, spec)
    assert _spread(_picture_of(pygltflib.GLTF2().load(flat), "walls")) == 0
    given = tmp_path / "given.glb"
    build_room(given, spec, {"floor": room_materials.make("stone", 1), "tile_m": {"floor": 0.5}})
    given_gltf = pygltflib.GLTF2().load(given)
    given_u = _read_uv(given_gltf, given_gltf.meshes[0].primitives[index].attributes.TEXCOORD_0)[:, 0].max()
    assert given_u == pytest.approx(4 / 0.5, abs=0.01) and _spread(_picture_of(given_gltf, "walls")) > 2


def test_the_door_has_a_frame_raised_panels_and_a_handle(tmp_path):
    target = tmp_path / "room.glb"
    build_room(target, {**BOX, "windows": [{"wall": "left", "x": 0, "y": 1.1, "w": 1.0, "h": 1.0}]})
    gltf = pygltflib.GLTF2().load(target)
    names = [material.name for material in gltf.materials]
    assert {"door", "door-panels", "trim", "handle"} <= set(names)
    _g, _m, leaf, _n, _i = _part(target, "door")
    _g, _m, panels, panel_normals, _i = _part(target, "door-panels")
    _g, _m, trim, trim_normals, _i = _part(target, "trim")
    # The back wall is z = 2.5 and the leaf stands 2 cm into the room; a panel stands 1.2 cm further out.
    assert leaf[:, 2].mean() == pytest.approx(2.48, abs=0.001) and panels[:, 2].min() == pytest.approx(2.468, abs=0.001)
    assert len(panels) == 4 * 5 * 4 and panels[:, 1].min() == pytest.approx(0.18, abs=0.001) and panels[:, 1].max() == pytest.approx(1.88, abs=0.001)
    # The frame: two jambs and a head around the 0.9 x 2.0 hole, standing out of the wall.
    door_trim = trim[(trim[:, 1] > 0.5) & (trim[:, 1] < 2.2) & (np.abs(trim[:, 0]) < 0.6) & (np.abs(trim[:, 2] - 2.5) < 0.05)]
    assert door_trim[:, 1].max() == pytest.approx(2.07, abs=0.001) and door_trim[:, 0].min() == pytest.approx(-0.52, abs=0.001)
    assert trim[:, 1].min() == pytest.approx(0) and trim[:, 1].max() == pytest.approx(2.6, abs=0.001), "skirting up to the cornice"
    assert (trim[:, 0] < -1.9).any() and np.allclose(np.linalg.norm(trim_normals, axis=1), 1, atol=1e-3), "the window has its frame too"
    # Nothing on the back wall faces back into the wall.
    on_back = (trim[:, 2] > 2.4) & (np.abs(trim[:, 0]) < 1.5)
    assert on_back.any() and trim_normals[on_back][:, 2].max() <= 1e-6
    _g, handle_material, handle, _n, _i = _part(target, "handle")
    assert 0.9 < handle[:, 1].min() < handle[:, 1].max() < 1.1 and handle_material.pbrMetallicRoughness.metallicFactor == 0
    # A picture of a whole door (a painted one) has panels of its own, so no geometry is stacked on it.
    painted = tmp_path / "painted.glb"
    build_room(painted, BOX, {"door": room_materials.make("riveted_steel", 2), "door_panels": False})
    assert "door-panels" not in [material.name for material in pygltflib.GLTF2().load(painted).materials]


class _Model:
    """A stand-in for the image model: a picture per job, drawn from the prompt, no GPU. ``fail`` names words that make a job
    fail; ``seamless=False`` draws pictures that do not repeat, and a heal pass hands the same kind back."""

    def __init__(self, root, fail=(), seamless=True):
        self.root, self.fail, self.seamless = root, tuple(fail), seamless
        self.admitted, self.jobs = [], {}

    def __call__(self, name, args):
        if name == "media.options":
            return {"local": {"image": [{"id": "qwen_image_21_turbo"}]}}
        if name == "generation.image":
            self.admitted.append(args)
            job = f"job-{len(self.admitted)}"
            self.jobs[job] = args["input"]
            return {"receipt": {"result": {"job_id": job}}}
        assert name == "jobs.wait", name
        job = args["input"]["job_id"]
        asked = self.jobs[job]
        if any(word in asked["params"]["prompt"] for word in self.fail):
            return {"job_id": job, "status": "failed", "error": {"code": "oom", "message": "out of memory"}}
        file = f"{asked['output_name']}.png"
        self._draw(asked["params"]).save(self.root / file)
        return {"job_id": job, "status": "completed", "output_files": [file]}

    def _draw(self, params):
        from PIL import Image
        width, height = (int(side) for side in params["resolution"].split("x"))
        if self.seamless:
            # A picture that repeats exactly (a 512 px tile laid 2 x 2), so the seam check is nowhere near its limit.
            base = np.asarray(room_materials.make("tile" if "floor" in params["prompt"] else "brick", len(self.admitted)))
            picture = np.tile(base, (height // 512 + 1, width // 512 + 1, 1))[:height, :width]
            return Image.fromarray(np.roll(picture, (height // 2, width // 2), (0, 1)) if "image_guide" in params else picture)
        ramp = np.tile(np.linspace(40, 215, width)[None, :, None], (height, 1, 3))
        noise = np.random.default_rng(len(self.admitted)).integers(-6, 6, (height, width, 3))
        bad = np.clip(ramp + noise, 0, 255).astype(np.uint8)
        # The heal pass gets back a picture that still has its seam (the code rolls it back before it measures).
        return Image.fromarray(np.roll(bad, (height // 2, width // 2), (0, 1)) if "image_guide" in params else bad)


def _stored(tmp_path, monkeypatch, room=None):
    from services import core_workspace
    from services.room_box_commands import PUT, run
    monkeypatch.setattr(core_workspace, "outputs_root", lambda: tmp_path)
    run(PUT, {"version": 1, "intent_id": "room-1", "input": {"workspace": "default", "name": "kitchen", "room": room or BOX}})
    return tmp_path


def _paint(model, root, data, inline=True):
    from services.room_paint import paint
    return paint(model, "default", root, "kitchen", data, inline=inline)


def test_put_gives_every_surface_a_procedural_look_and_a_fingerprint(tmp_path, monkeypatch):
    from services import room_store
    from services.room_box_commands import GET, PUT, run
    root = _stored(tmp_path, monkeypatch, {**BOX, "ceiling": "white plaster"})
    record = room_store.record_of(root, "kitchen")
    assert set(record["surfaces"]) == {"floor", "walls", "ceiling", "door", "trim"}
    assert {entry["source"] for entry in record["surfaces"].values()} == {"procedural"}
    assert record["surfaces"]["floor"]["material"] == "wood_planks" and record["surfaces"]["walls"]["material"] == "plaster"
    assert record["paint"]["status"] == "not_painted" and len(record["paint"]["look"]) == 16
    read = run(GET, {"version": 1, "input": {"workspace": "default", "name": "kitchen"}})["result"]
    assert read["paint"]["look"] == record["paint"]["look"] and read["surfaces"]["door"]["material"] == "wood_planks"
    again = run(PUT, {"version": 1, "intent_id": "room-2", "input": {"workspace": "default", "name": "kitchen", "room": {**BOX, "ceiling": "white plaster"}}})
    assert again["result"]["paint"]["look"] == record["paint"]["look"], "the same room again keeps its look"
    old = json.loads((root / "scene3d-rooms.json").read_text())
    old["rooms"]["kitchen"] = {"spec": record["spec"], "file": "rooms/kitchen.glb"}
    (root / "scene3d-rooms.json").write_text(json.dumps(old))
    assert room_store.surfaces_of(room_store.record_of(root, "kitchen"))["floor"]["source"] == "procedural", "a room put before looks reads as unpainted"
    upgraded = run(PUT, {"version": 1, "intent_id": "room-3", "input": {"workspace": "default", "name": "kitchen", "room": {**BOX, "ceiling": "white plaster"}}})
    assert upgraded["result"]["paint"]["status"] == "not_painted" and "surfaces" in room_store.record_of(root, "kitchen")


def test_paint_asks_the_model_for_each_surface_then_finds_its_own_work(tmp_path, monkeypatch):
    from services import room_store
    root = _stored(tmp_path, monkeypatch)
    before = room_store.record_of(root, "kitchen")["paint"]["look"]
    model = _Model(root)
    words = {"style": "1950s space hangar", "floor": "worn green linoleum", "door": "hangar door with warning stripes", "tile_m": {"floor": 0.6}}
    done = _paint(model, root, words)
    assert done["status"] == "completed" and done["painted"] == ["door", "floor", "trim", "walls"] and done["warnings"] == []
    prompts = {call["input"]["output_name"].split("-")[-2]: call["input"]["params"] for call in model.admitted if "heal" not in call["input"]["output_name"]}
    assert set(prompts) == {"floor", "walls", "door", "trim"}, "no ceiling picture for a room without a ceiling"
    assert "worn green linoleum" in prompts["floor"]["prompt"] and "about 0.6 m." in prompts["floor"]["prompt"]
    assert all("1950s space hangar" in item["prompt"] and "a small kitchen" not in item["prompt"] for item in prompts.values())
    assert prompts["floor"]["resolution"] == "1024x1024" and prompts["door"]["resolution"] == "576x1280"
    assert prompts["floor"]["model_type"] == "qwen_image_21_turbo" and "hangar door with warning stripes" in prompts["door"]["prompt"]
    assert "closed door" in prompts["door"]["prompt"] and "seamless" in prompts["walls"]["prompt"]
    record = room_store.record_of(root, "kitchen")
    assert {key: entry["source"] for key, entry in record["surfaces"].items()} == {"floor": "ai", "walls": "ai", "door": "ai", "trim": "ai"}
    assert record["surfaces"]["floor"]["tile_m"] == 0.6 and record["surfaces"]["walls"]["tile_m"] == 1.5 and (root / "rooms/kitchen/floor.png").is_file()
    assert record["paint"]["look"] != before and record["paint"]["request"] == done["request"]
    gltf = pygltflib.GLTF2().load(root / "rooms/kitchen.glb")
    assert "door-panels" not in [material.name for material in gltf.materials], "a painted door has its own panels"
    index = next(i for i, material in enumerate(gltf.materials) if material.name == "floor")
    assert _read_uv(gltf, gltf.meshes[0].primitives[index].attributes.TEXCOORD_0)[:, 0].max() == pytest.approx(4 / 0.6, abs=0.01)
    asked = len(model.admitted)
    cached = _paint(model, root, words)
    assert cached["cached"] is True and len(model.admitted) == asked, "same room, words and seed: nothing is asked again"
    assert _paint(model, root, {**words, "seed": 9})["request"] != done["request"] and len(model.admitted) > asked


def test_a_model_that_cannot_paint_leaves_the_procedural_look_and_says_so(tmp_path, monkeypatch):
    from services import room_store
    root = _stored(tmp_path, monkeypatch)
    before = room_store.record_of(root, "kitchen")
    glb = (root / "rooms/kitchen.glb").read_bytes()
    partial = _paint(_Model(root, fail=("wall texture",)), root, {})
    assert partial["status"] == "completed" and partial["painted"] == ["door", "floor", "trim"]
    assert [(item["code"], item["surface"]) for item in partial["warnings"]] == [("paint_failed", "walls")]
    assert partial["surfaces"]["walls"]["source"] == "procedural" and partial["surfaces"]["floor"]["source"] == "ai"
    failed = _paint(_Model(root, fail=("texture", "door", "skirting")), root, {"style": "no model today"})
    assert failed["status"] == "failed" and "procedural" in failed["error"] and len(failed["warnings"]) == 4
    assert failed["surfaces"]["floor"]["source"] == "ai", "what was painted before stays"
    fresh = _stored(tmp_path / "fresh", monkeypatch)
    nothing = _paint(_Model(fresh, fail=("a", "e", "i", "o", "u")), fresh, {})
    assert nothing["status"] == "failed" and nothing["look"] == before["paint"]["look"]
    assert (fresh / "rooms/kitchen.glb").read_bytes() == glb, "a failed paint leaves the GLB as it was"
    with pytest.raises(ValueError, match="not reachable"):
        _paint(None, fresh, {})
    with pytest.raises(ValueError, match="no ceiling"):
        _paint(_Model(fresh), fresh, {"ceiling": "tin"})
    with pytest.raises(ValueError, match="unknown paint fields"):
        _paint(_Model(fresh), fresh, {"colour": "red"})
    with pytest.raises(ValueError, match="unknown room"):
        from services.room_paint import paint
        paint(_Model(fresh), "default", fresh, "attic", {})


def test_a_picture_that_does_not_repeat_is_healed_then_blended_and_a_procedural_paint_needs_no_model(tmp_path, monkeypatch):
    from PIL import Image
    from services import room_store
    from services.room_paint import blend_edges
    root = _stored(tmp_path, monkeypatch)
    model = _Model(root, seamless=False)
    done = _paint(model, root, {})
    assert done["status"] == "completed" and done["warnings"] == []
    floor = room_store.record_of(root, "kitchen")["surfaces"]["floor"]
    assert floor["metrics"]["blended"] and floor["metrics"]["healed"] and floor["metrics"]["seam_error"] <= 1.5
    assert any("image_guide" in call["input"]["params"] for call in model.admitted), "the project's own heal pass ran first"
    with Image.open(root / floor["file"]) as saved:
        assert seam_error(saved) <= 1.5
    ramp = Image.fromarray(np.tile(np.linspace(0, 255, 128).astype(np.uint8)[None, :, None], (128, 1, 3)))
    assert seam_error(ramp) > 5 and seam_error(blend_edges(ramp)) < 1.5
    asked = len(model.admitted)
    plain = _paint(None, root, {"engine": "procedural", "walls": "red brick", "floor": "linóleo verde"})
    assert plain["status"] == "completed" and plain["engine"] == "procedural" and len(model.admitted) == asked
    assert plain["surfaces"]["walls"]["material"] == "brick" and plain["surfaces"]["floor"]["material"] == "linoleum"
    assert {entry["source"] for entry in plain["surfaces"].values()} == {"procedural"}, "it undoes a painted look"


def test_the_commands_paint_in_the_background_and_poll(tmp_path, monkeypatch):
    import time
    from fastapi import HTTPException
    from services.mcp_profiles import SERIES_TOOLS
    from services.room_box_commands import PAINT, PAINT_STATUS, command_catalog, command_handlers, run
    from services.set_commands import command_catalog as set_catalog, command_handlers as set_handlers
    root = _stored(tmp_path, monkeypatch)
    model = _Model(root)
    named = {operation["name"]: operation for operation in command_catalog()}
    assert named[PAINT]["mutation"] is True and named[PAINT_STATUS]["mutation"] is False
    assert "intent_id" in named[PAINT]["inputSchema"]["required"] and "engine" in named[PAINT]["inputSchema"]["properties"]["input"]["properties"]
    assert {PAINT, PAINT_STATUS} <= SERIES_TOOLS and {PAINT, PAINT_STATUS} <= {operation["name"] for operation in set_catalog()}
    assert {PAINT, PAINT_STATUS} <= set(set_handlers(model)) and {PAINT, PAINT_STATUS} <= set(command_handlers())
    body = {"version": 1, "intent_id": "paint-1", "input": {"workspace": "default", "name": "kitchen", "floor": "cracked terrazzo"}}
    first = run(PAINT, body, model)["result"]
    assert first["status"] in ("queued", "running", "completed")
    waited = time.time() + 20
    while run(PAINT_STATUS, {"version": 1, "input": {"workspace": "default", "name": "kitchen"}})["result"]["status"] != "completed":
        assert time.time() < waited, "the background job did not finish"
        time.sleep(0.05)
    assert run(PAINT, body, model)["result"] == first, "the same intent returns its first receipt"
    status = run(PAINT_STATUS, {"version": 1, "input": {"workspace": "default", "name": "kitchen"}})["result"]
    assert status["painted"] == ["door", "floor", "trim", "walls"] and status["surfaces"]["floor"]["file"] == "rooms/kitchen/floor.png"
    with pytest.raises(HTTPException) as conflict:
        run(PAINT, {**body, "input": {**body["input"], "floor": "other"}}, model)
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException) as bad:
        run(PAINT, {**body, "intent_id": "paint-2", "input": {**body["input"], "tile_m": {"floor": 99}}}, model)
    assert bad.value.status_code == 422
    with pytest.raises(HTTPException) as lost:
        run(PAINT_STATUS, {"version": 1, "input": {"workspace": "default", "name": "attic"}})
    assert lost.value.status_code == 422
    from services import room_paint
    room_paint._ACTIVE.clear()


def test_repainting_renders_again_only_the_shots_in_that_room(tmp_path, monkeypatch):
    from services.series_take_inputs import render_inputs
    from services.room_box_commands import PUT, run
    root = _stored(tmp_path, monkeypatch)
    run(PUT, {"version": 1, "intent_id": "room-b", "input": {"workspace": "default", "name": "attic", "room": {**BOX, "floor": "bare boards"}}})

    def shot(room):
        objects = [{"objectId": "room-box", "add": True, "media": "model3d", "file": f"rooms/{room}.glb"}] if room else []
        return {"id": f"s-{room}", "productionMethod": "animation_3d", "locationId": "office", "scene3d": {"template": "two-shot", "objects": objects}}

    series = {"characters": [], "locations": [{"id": "office"}]}
    before = {room: render_inputs(series, shot(room), {}, str(root)) for room in ("kitchen", "attic", None)}
    assert len({*before.values()}) == 3
    assert _paint(_Model(root), root, {"style": "tin"})["status"] == "completed"
    after = {room: render_inputs(series, shot(room), {}, str(root)) for room in ("kitchen", "attic", None)}
    assert after["kitchen"] != before["kitchen"], "the room that was painted"
    assert after["attic"] == before["attic"] and after[None] == before[None], "the shots in other rooms, or in none, keep their takes"
    assert render_inputs(series, shot("kitchen"), {}, str(root)) == after["kitchen"]


def test_the_rest_door_paints_through_the_same_operation(tmp_path, monkeypatch):
    """``POST /api/v1/scene3d/rooms/commands`` hands the image model to ``run`` like MCP does."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.set_catalog import create_set_catalog_router
    root = _stored(tmp_path, monkeypatch)
    model = _Model(root)
    api = FastAPI()
    api.include_router(create_set_catalog_router(model))
    client = TestClient(api)
    body = {"operation": "scene3d.room.paint", "version": 1, "intent_id": "rest-1",
            "input": {"workspace": "default", "name": "kitchen", "engine": "procedural", "walls": "red brick"}}
    first = client.post("/api/v1/scene3d/rooms/commands", json=body)
    assert first.status_code == 200 and first.json()["result"]["surfaces"]["walls"]["material"] == "brick"
    asked = client.post("/api/v1/scene3d/rooms/commands", json={**body, "intent_id": "rest-2", "input": {"workspace": "default", "name": "kitchen"}})
    assert asked.status_code == 200 and asked.json()["result"]["status"] in ("queued", "running", "completed")
    assert client.post("/api/v1/scene3d/rooms/commands", json={**body, "operation": "scene3d.room.bake"}).status_code == 422
    from services import room_paint
    import time
    stop = time.time() + 20
    while time.time() < stop and room_paint.status(root, "kitchen")["status"] in ("queued", "running"):
        time.sleep(0.05)
    assert room_paint.status(root, "kitchen")["status"] == "completed" and len(model.admitted) >= 4


def test_a_superseded_paint_does_not_overwrite_the_newer_look(tmp_path, monkeypatch):
    """A second paint of the same room must keep its PNGs when the first job wakes up and writes."""
    import threading
    from services import room_store
    from services.room_paint import paint

    root = _stored(tmp_path, monkeypatch)
    started, release = threading.Event(), threading.Event()

    class Slow(_Model):
        def __call__(self, name, args):
            if name == "generation.image":
                started.set()
                assert release.wait(15)
            return super().__call__(name, args)

        def _draw(self, params):
            # The older request draws other pictures, so a write of its files over the newer look shows in the bytes.
            from PIL import ImageOps
            return ImageOps.invert(super()._draw(params))

    first_done = []

    def run_first():
        first_done.append(paint(Slow(root), "default", root, "kitchen", {"style": "tin hangar"}, inline=True))

    worker = threading.Thread(target=run_first)
    worker.start()
    assert started.wait(5), "the first paint never reached the model"
    later = paint(_Model(root), "default", root, "kitchen", {"style": "oak parlour"}, inline=True)
    assert later["status"] == "completed" and later["style"] == "oak parlour"
    oak = {surface: (root / f"rooms/kitchen/{surface}.png").read_bytes()
           for surface in ("floor", "walls", "door", "trim")}
    oak_look = later["look"]
    release.set()
    worker.join(20)
    assert not worker.is_alive()
    record = room_store.record_of(root, "kitchen")
    assert record["paint"]["look"] == oak_look and record["paint"]["style"] == "oak parlour"
    assert {surface: (root / f"rooms/kitchen/{surface}.png").read_bytes()
            for surface in oak} == oak, "the superseded job must not replace the published pictures"
    assert first_done and first_done[0]["look"] == oak_look
    from services.room_surfaces import file_sha
    for surface, entry in room_store.surfaces_of(record).items():
        if entry.get("source") == "ai":
            assert entry["sha"] == file_sha(root / entry["file"]), f"{surface}: the record names a picture that is no longer on disk"
    leftover = list((root / "rooms" / "kitchen").glob(".paint-*"))
    assert leftover == []
