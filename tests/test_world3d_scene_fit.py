"""fit in a world3d.scene.patch binding sizes an object in metres from its GLB bounds (no rendering, no node)."""
import json

import pytest

from services.world3d_scenes import World3DSceneError, inspect_scene, patch_scene
from services.world3d_template_commands import command_catalog
from tests.test_world3d_scene_layout import SCENE, WORKSPACE, model_glb, scene, slot, workspace_dir


def patch(tmp_path, bindings, revision=1):
    return patch_scene(WORKSPACE, SCENE, workspace_dir(tmp_path), {"bindings": bindings}, revision)


def fitted(tmp_path, binding, **slot_fields):
    """A scene with one 2 x 2 x 1 m (x, y, z) GLB object `ship`, then the patch."""
    model_glb(tmp_path, "ship.glb", low=(-1, 0, -0.5), high=(1, 2, 0.5))
    scene(tmp_path, [slot("ship", "ship.glb", **slot_fields)])
    return patch(tmp_path, [{"object_id": "ship", **binding}])


def scale_of(viewed):
    return next(row for row in viewed["layout"]["items"] if row["id"] == "ship")["scale"]


def test_height_needs_no_file_and_is_the_scale_over_1_7(tmp_path):
    scene(tmp_path, [slot("ship")])                                 # a marker: nothing bound yet
    viewed = patch(tmp_path, [{"object_id": "ship", "fit": {"heightM": 3.4}}])
    assert scale_of(viewed) == 2 and viewed["document"]["slots"][0]["scale"] == 2
    assert "fit" not in viewed["document"]["slots"][0], "fit is an instruction, not stored on the object"


def test_height_then_the_bounds_agree_with_the_request(tmp_path):
    viewed = fitted(tmp_path, {"fit": {"heightM": 10}})
    bounds = viewed["layout"]["items"][0]["boundsM"]
    assert bounds["size"][1] == pytest.approx(10) and bounds["size"] == pytest.approx([10, 10, 5])


def test_width_depth_and_longest_read_the_glb(tmp_path):
    for fit, expected in (({"widthM": 6}, [6, 6, 3]), ({"depthM": 6}, [12, 12, 6]), ({"longestM": 8}, [8, 8, 4])):
        model_glb(tmp_path, "ship.glb", low=(-1, 0, -0.5), high=(1, 2, 0.5))
        scene(tmp_path, [slot("ship", "ship.glb")])
        bounds = patch(tmp_path, [{"object_id": "ship", "fit": fit}])["layout"]["items"][0]["boundsM"]
        assert bounds["size"] == pytest.approx(expected, abs=1e-3), fit


def test_a_source_bound_in_the_same_binding_is_measured_and_snake_case_works(tmp_path):
    model_glb(tmp_path, "island.glb", low=(0, 0, 0), high=(40, 4, 20))
    scene(tmp_path, [slot("env")])
    viewed = patch(tmp_path, [{"object_id": "env", "source_url": "/api/v1/file/island.glb?workspace=studio", "fit": {"longest_m": 80}}])
    item = viewed["layout"]["items"][0]
    assert item["boundsM"]["size"] == pytest.approx([80, 8, 40]) and item["boundsM"]["min"] == pytest.approx([0, 0, 0])


def test_native_takes_the_files_size_as_metres_and_warns_when_that_looks_wrong(tmp_path):
    model_glb(tmp_path, "tree.glb", low=(-1, 0, -1), high=(1, 6, 1))
    scene(tmp_path, [slot("tree", "tree.glb")])
    viewed = patch(tmp_path, [{"object_id": "tree", "fit": "native"}])
    assert viewed["layout"]["items"][0]["boundsM"]["size"] == pytest.approx([2, 6, 2]) and viewed["warnings"] == []
    model_glb(tmp_path, "cm.glb", low=(-50, 0, -50), high=(50, 180, 50))
    scene(tmp_path, [slot("tree", "cm.glb")])
    viewed = patch(tmp_path, [{"object_id": "tree", "fit": "native"}])
    assert viewed["layout"]["items"][0]["boundsM"]["size"][1] == pytest.approx(180)
    assert viewed["warnings"] and viewed["warnings"][0].startswith("fit_native_unusual")


def test_fit_keeps_a_set_items_real_height_in_step_like_the_editor(tmp_path):
    viewed = fitted(tmp_path, {"fit": {"heightM": 0.6}}, setItem={"heightM": 1.7})
    assert viewed["document"]["slots"][0]["setItem"]["heightM"] == pytest.approx(0.6)


def test_a_cutout_fits_by_height_from_its_2_m_plane_and_nothing_else(tmp_path):
    scene(tmp_path, [slot("sign", "sign.png", media="image", surface="cutout")])
    assert scale_of_row(patch(tmp_path, [{"object_id": "sign", "fit": {"heightM": 1}}]), "sign") == 0.5
    with pytest.raises(World3DSceneError) as raised:
        patch(tmp_path, [{"object_id": "sign", "fit": {"widthM": 1}}], 2)
    assert raised.value.code == "invalid_fit"


def scale_of_row(viewed, identifier):
    return next(row for row in viewed["layout"]["items"] if row["id"] == identifier)["scale"]


@pytest.mark.parametrize("fit,code", [
    ({"heightM": 2, "widthM": 2}, "invalid_fit"), ({}, "invalid_fit"), ({"colourM": 2}, "invalid_fit"), ("huge", "invalid_fit"), (None, "invalid_fit"),
    (3, "invalid_fit"), ({"heightM": 0}, "invalid_fit"), ({"heightM": -1}, "invalid_fit"), ({"heightM": float("nan")}, "invalid_fit"),
    ({"heightM": float("inf")}, "invalid_fit"), ({"heightM": "2"}, "invalid_fit"), ({"heightM": True}, "invalid_fit"), ({"heightM": 1e9}, "invalid_fit"),
])
def test_a_bad_fit_is_refused_and_writes_nothing(tmp_path, fit, code):
    model_glb(tmp_path, "ship.glb")
    scene(tmp_path, [slot("ship", "ship.glb")])
    before = (tmp_path / WORKSPACE / "world3d-edits" / f"{SCENE}.json").read_text(encoding="utf-8")
    with pytest.raises(World3DSceneError) as raised:
        patch(tmp_path, [{"object_id": "ship", "position": [5, 0, 0], "fit": fit}])
    assert raised.value.code == code
    assert (tmp_path / WORKSPACE / "world3d-edits" / f"{SCENE}.json").read_text(encoding="utf-8") == before
    assert inspect_scene(WORKSPACE, SCENE, workspace_dir(tmp_path))["revision"] == 1


def test_fit_and_scale_in_one_binding_are_refused(tmp_path):
    model_glb(tmp_path, "ship.glb")
    scene(tmp_path, [slot("ship", "ship.glb")])
    with pytest.raises(World3DSceneError) as raised:
        patch(tmp_path, [{"object_id": "ship", "scale": 2, "fit": {"heightM": 2}}])
    assert raised.value.code == "invalid_fit" and "not both" in str(raised.value)


@pytest.mark.parametrize("source,reason", [("", "marker"), ("missing.glb", "missing_file"), ("/api/v1/uploads/ship.glb", "outside_workspace"), ("notes.txt", "not_glb")])
def test_dimensions_other_than_height_need_a_readable_glb(tmp_path, source, reason):
    scene(tmp_path, [slot("ship", source)])
    with pytest.raises(World3DSceneError) as raised:
        patch(tmp_path, [{"object_id": "ship", "fit": {"widthM": 5}}])
    assert raised.value.code == "bounds_unavailable" and reason in str(raised.value) and "heightM" in str(raised.value)
    with pytest.raises(World3DSceneError) as raised:
        patch(tmp_path, [{"object_id": "ship", "fit": "native"}])
    assert raised.value.code == "bounds_unavailable"


def test_a_flat_model_cannot_be_fitted_by_height_but_can_by_width(tmp_path):
    model_glb(tmp_path, "slab.glb", low=(-5, 0, -5), high=(5, 0, 5))
    scene(tmp_path, [slot("floor", "slab.glb")])
    with pytest.raises(World3DSceneError, match="no height"):
        patch(tmp_path, [{"object_id": "floor", "fit": {"heightM": 1}}])
    assert patch(tmp_path, [{"object_id": "floor", "fit": {"widthM": 20}}])["layout"]["items"][0]["boundsM"]["size"][0] == pytest.approx(20)


def test_fit_on_a_screen_or_other_media_is_refused(tmp_path):
    scene(tmp_path, [slot("tv", "clip.mp4", media="screen")])
    with pytest.raises(World3DSceneError) as raised:
        patch(tmp_path, [{"object_id": "tv", "fit": {"heightM": 1}}])
    assert raised.value.code == "invalid_fit"


def test_the_tool_descriptions_document_fit_layout_and_the_1_7_m_rule():
    tools = {item["name"]: item for item in command_catalog()}
    patch_description = json.dumps(tools["world3d.scene.patch"]["inputSchema"]) + tools["world3d.scene.patch"]["description"]
    inspect_description = tools["world3d.scene.inspect"]["description"]
    for word in ("fit:", "heightM", "longestM", "native", "1.7 m x scale"):
        assert word in patch_description, word
    for word in ("layout.items", "boundsM", "boundsReason", "camera", "1.7 m x scale", "rest pose", "Open dialog"):
        assert word in inspect_description, word
