"""world3d.scene.inspect shows the camera, the light and where every object is in metres (boundsM), without rendering."""
import json
import math

import pytest

from services.world3d_scene_layout import MAX_ITEMS
from services.world3d_scenes import inspect_scene
from tests.test_glb_bounds import accessor, mesh, write as write_glb

WORKSPACE = "studio"
SCENE = "w3d-0000000000a1"


def workspace_dir(tmp_path):
    return lambda name: str(tmp_path / name)


def model_glb(tmp_path, name="model.glb", low=(-1, 0, -0.5), high=(1, 2, 0.5)):
    folder = tmp_path / WORKSPACE
    folder.mkdir(exist_ok=True)
    document = {"scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}], "meshes": [mesh(0)], "accessors": [accessor(list(low), list(high))]}
    return write_glb(folder, document, name)


def slot(identifier, source="", **fields):
    return {"id": identifier, "slot": "prop", "position": [0, 0, 0], "rotationY": 0, "scale": 1, "sourceUrl": source,
            "media": "model3d", "clip": None, **fields}


def scene(tmp_path, slots, **document):
    body = {"version": 1, "units": "meters", "up": "y", "templateId": "user-layout", "width": 1280, "height": 720, "fps": 30, "duration": 5,
            "camera": {"family": "fixed", "eye": [0, 1.6, 6], "look": [0, 1, 0], "fov": 45},
            "light": {"kind": "directional", "direction": [-0.4, -1, -0.3], "intensity": 1.2, "color": "#ffffff"},
            "slots": slots, **document}
    folder = tmp_path / WORKSPACE / "world3d-edits"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{SCENE}.json").write_text(json.dumps({"revision": 1, "templateId": "user-layout", "document": body, "warnings": []}), encoding="utf-8")
    return inspect_scene(WORKSPACE, SCENE, workspace_dir(tmp_path))


def item(viewed, identifier):
    return next(row for row in viewed["layout"]["items"] if row["id"] == identifier)


def test_inspect_adds_camera_light_size_and_duration_and_keeps_objects_as_they_were(tmp_path):
    camera = {"family": "orbit", "eye": [0, 2, 8], "look": [0, 1, 0], "fov": 40, "orbitRadius": 8, "orbitTurns": 0.25,
              "framing": {"targetSlot": "hero", "anchor": "head", "from": [0, 1, 5], "to": [0, 1.6, 3], "fovTo": 30, "rollFrom": 0, "rollTo": 3},
              "shake": [{"start": 1, "end": 2, "amplitude": 0.05, "frequency": 12}, {"start": 3, "end": 3.5, "amplitude": 0.09, "frequency": 20, "seed": 4}]}
    viewed = scene(tmp_path, [slot("hero")], camera=camera)
    assert viewed["camera"]["family"] == "orbit" and viewed["camera"]["eye"] == [0, 2, 8] and viewed["camera"]["orbitRadius"] == 8
    assert viewed["camera"]["framing"] == {"targetSlot": "hero", "anchor": "head", "from": [0, 1, 5], "to": [0, 1.6, 3], "fovTo": 30}
    assert viewed["camera"]["shake"] == {"windows": 2, "start": 1, "end": 3.5, "maxAmplitude": 0.09}
    assert viewed["light"]["color"] == "#ffffff" and viewed["duration"] == 5 and viewed["size"] == {"width": 1280, "height": 720, "fps": 30}
    assert viewed["document"]["camera"] == camera, "the document itself is untouched"
    assert [row["id"] for row in viewed["objects"]] == ["hero"] and set(viewed["objects"][0]) >= {"id", "role", "media", "sourceUrl", "marker", "position", "scale"}
    assert "boundsM" not in viewed["objects"][0], "objects stays what patches address; the layout is separate"


def test_a_model_is_measured_after_the_renderers_1_7_m_normalisation(tmp_path):
    model_glb(tmp_path)                                          # 2 x 2 x 1 m native: 2 tall, so 0.85 per native metre
    rows = scene(tmp_path, [slot("tree", "/api/v1/file/model.glb?workspace=studio", position=[3, 0, 1])])["layout"]["items"]
    bounds = rows[0]["boundsM"]
    assert bounds["size"] == pytest.approx([1.7, 1.7, 0.85]) and bounds["bottomY"] == 0
    assert bounds["center"] == pytest.approx([3, 0.85, 1]) and bounds["min"] == pytest.approx([2.15, 0, 0.575]) and bounds["max"] == pytest.approx([3.85, 1.7, 1.425])
    assert "boundsReason" not in rows[0]


def test_scale_position_and_a_quarter_turn_move_the_world_box_not_the_models_own_size(tmp_path):
    model_glb(tmp_path)
    row = item(scene(tmp_path, [slot("tree", "model.glb", position=[1, 0.5, -2], scale=2, rotationY=math.pi / 2)]), "tree")
    assert row["boundsM"]["size"] == pytest.approx([3.4, 3.4, 1.7])            # its own width, height, depth
    assert row["boundsM"]["min"] == pytest.approx([0.15, 0.5, -3.7]) and row["boundsM"]["max"] == pytest.approx([1.85, 3.9, -0.3])
    assert row["boundsM"]["center"] == pytest.approx([1, 2.2, -2])


def test_the_origin_is_not_recentred_and_grounded_puts_the_lowest_point_at_the_position(tmp_path):
    model_glb(tmp_path, "sunk.glb", low=(-1, -1, -1), high=(1, 1, 1))         # origin in the middle: 2 m tall native
    free = item(scene(tmp_path, [slot("a", "sunk.glb", position=[0, 2, 0])]), "a")["boundsM"]
    grounded = item(scene(tmp_path, [slot("a", "sunk.glb", position=[0, 2, 0], grounded=True)]), "a")["boundsM"]
    assert free["bottomY"] == pytest.approx(1.15) and free["center"][1] == pytest.approx(2)
    assert grounded["bottomY"] == pytest.approx(2) and grounded["center"][1] == pytest.approx(2.85)


def test_an_object_that_cannot_be_measured_says_why_and_never_fails_the_inspect(tmp_path):
    model_glb(tmp_path)
    (tmp_path / WORKSPACE / "fake.glb").write_bytes(b"this is text")
    (tmp_path / WORKSPACE / "scene.gltf").write_text("{}")
    slots = [slot("marker"), slot("picture", "pic.png", media="image", surface="cutout"), slot("gone", "/api/v1/file/missing.glb?workspace=studio"),
             slot("upload", "/api/v1/uploads/model.glb"), slot("other", "/api/v1/file/model.glb?workspace=elsewhere"),
             slot("climb", "/api/v1/file/../model.glb?workspace=studio"), slot("remote", "https://example.com/model.glb"),
             slot("gltf", "scene.gltf"), slot("fake", "fake.glb"), slot("blob", "blob:http://x/1"), slot("fine", "model.glb")]
    rows = {row["id"]: row for row in scene(tmp_path, slots)["layout"]["items"]}
    reasons = {key: row.get("boundsReason") for key, row in rows.items()}
    assert reasons == {"marker": "marker", "picture": "not_a_3d_model", "gone": "missing_file", "upload": "outside_workspace",
                       "other": "outside_workspace", "climb": "outside_workspace", "remote": "outside_workspace", "gltf": "not_glb",
                       "fake": "not_glb", "blob": "outside_workspace", "fine": None}
    assert all(rows[key]["boundsM"] is None for key in reasons if key != "fine") and rows["fine"]["boundsM"]["size"][1] == pytest.approx(1.7)


def test_a_flat_model_uses_the_renderers_one_millimetre_floor(tmp_path):
    model_glb(tmp_path, "slab.glb", low=(-5, 0, -5), high=(5, 0, 5))
    bounds = item(scene(tmp_path, [slot("floor", "slab.glb")]), "floor")["boundsM"]
    assert bounds["size"][1] == 0 and bounds["size"][0] == pytest.approx(10 * 1.7 / 0.001)


def test_the_item_list_is_capped_and_says_how_many_were_left_out(tmp_path):
    viewed = scene(tmp_path, [slot(f"p{index}") for index in range(MAX_ITEMS + 5)])
    assert len(viewed["layout"]["items"]) == MAX_ITEMS and viewed["layout"]["omitted"] == 5
    assert "omitted" not in scene(tmp_path, [slot("only")])["layout"]
    assert len(json.dumps(viewed["layout"])) < 14_000


def test_a_scene_without_a_camera_or_light_still_inspects(tmp_path):
    folder = tmp_path / WORKSPACE / "world3d-edits"
    folder.mkdir(parents=True)
    (folder / f"{SCENE}.json").write_text(json.dumps({"revision": 1, "templateId": "x", "document": {"slots": [slot("a", "model.glb")]}}), encoding="utf-8")
    viewed = inspect_scene(WORKSPACE, SCENE, workspace_dir(tmp_path))
    assert viewed["camera"] is None and viewed["light"] is None and viewed["size"] == {} and viewed["layout"]["items"][0]["boundsM"] is None
