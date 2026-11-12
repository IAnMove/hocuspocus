"""beside on a bed means what a person means: head, foot, and left and right as for someone lying in it, by the head end
where a bedside table stands; a nightstand with no side goes there. Other objects and sides keep the box-side meaning."""
import json

import pytest

pytest.importorskip("pygltflib")

from services.world3d_scenes import inspect_scene
from tests.test_world3d_scene_layout import SCENE, WORKSPACE, item, workspace_dir
from tests.test_world3d_scene_rest import patch, slot_of, stage  # noqa: F401 - stage is a fixture

BED = {"object_id": "bed", "add": True, "furniture": {"kind": "bed"}}       # 2.0 m along x, 1.4 m deep, head at -x


def box(viewed, identifier):
    bounds = item(viewed, identifier)["boundsM"]
    return bounds["min"], bounds["max"]


def test_a_nightstand_with_no_side_stands_by_the_head_end_on_the_beds_right(stage):
    viewed = patch(stage, [BED, {"object_id": "lamp_table", "add": True, "furniture": {"kind": "nightstand"}, "beside": {"object": "bed"}}])
    (bx0, _by0, bz0), (_bx1, _by1, bz1) = box(viewed, "bed")
    (nx0, _ny0, nz0), (nx1, _ny1, _nz1) = box(viewed, "lamp_table")
    assert nx0 == pytest.approx(bx0, abs=0.01), "its head-ward edge lines up with the headboard end"
    assert nz0 == pytest.approx(bz1, abs=0.01), "beside the long side someone lying in it has on the right: the bed's front"
    assert nx1 < 0, "at the head half, not the foot"
    assert "side" not in slot_of(viewed, "lamp_table")["beside"]


def test_head_foot_left_right_and_offset_toward_the_foot(stage):
    patch(stage, [BED, {"object_id": "stand", "add": True, "furniture": {"kind": "nightstand"}}])
    (bx0, _y, bz0), (bx1, _y1, bz1) = box(inspect_scene(WORKSPACE, SCENE, workspace_dir(stage)), "bed")
    foot = patch(stage, [{"object_id": "stand", "beside": {"object": "bed", "side": "foot"}}])
    (fx0, _fy, fz0), (_fx1, _fy1, fz1) = box(foot, "stand")
    assert fx0 == pytest.approx(bx1, abs=0.01) and (fz0 + fz1) / 2 == pytest.approx((bz0 + bz1) / 2, abs=0.01), "past the foot, centred"
    head = patch(stage, [{"object_id": "stand", "beside": {"object": "bed", "side": "head", "gap": 0.05}}])
    assert box(head, "stand")[1][0] == pytest.approx(bx0 - 0.05, abs=0.01)
    left = patch(stage, [{"object_id": "stand", "beside": {"object": "bed", "side": "left", "offset": 0.3}}])
    (lx0, _ly, _lz0), (_lx1, _ly1, lz1) = box(left, "stand")
    assert lz1 == pytest.approx(bz0, abs=0.01), "the left of someone lying in it is the bed's back"
    assert lx0 == pytest.approx(bx0 + 0.3, abs=0.01), "offset slides toward the foot"


def test_bed_sides_turn_with_the_bed(stage):
    viewed = patch(stage, [{**BED, "rotationY": 1.5707963}, {"object_id": "stand", "add": True, "furniture": {"kind": "nightstand"},
                                                              "beside": {"object": "bed", "side": "right"}}])
    # A quarter turn takes the GLB's +z (the bed's front) to scene +x and its -x (the head) to scene +z.
    (_bx0, _by, _bz0), (bx1, _by1, bz1) = box(viewed, "bed")
    (nx0, _ny, _nz0), (_nx1, _ny1, nz1) = box(viewed, "stand")
    assert nx0 == pytest.approx(bx1, abs=0.01), "on the bed's front, now scene +x"
    assert nz1 == pytest.approx(bz1, abs=0.01), "lined up with the head end, now at scene +z"


def test_head_on_something_that_is_not_a_bed_warns_and_other_sides_keep_their_meaning(stage):
    viewed = patch(stage, [{"object_id": "table", "add": True, "furniture": {"kind": "table"}},
                           {"object_id": "stool", "add": True, "furniture": {"kind": "stool"}, "beside": {"object": "table", "side": "head"}}])
    assert any(line.startswith("beside_unresolved: stool beside table: side 'head'") for line in viewed["warnings"])
    right = patch(stage, [{"object_id": "stool", "beside": {"object": "table", "side": "right"}}])
    assert box(right, "stool")[0][0] == pytest.approx(box(right, "table")[1][0], abs=0.01), "a table's right is still its +x side"
    chair = patch(stage, [BED, {"object_id": "chair", "add": True, "furniture": {"kind": "chair"}, "beside": {"object": "bed"}}])
    (cx0, _cy, cz0), (cx1, _cy1, _cz1) = box(chair, "chair")
    assert (cx0 + cx1) / 2 == pytest.approx(0.0, abs=0.01) and cz0 == pytest.approx(box(chair, "bed")[1][2], abs=0.01), \
        "a chair with no side stands in front of the bed's middle, as before"


def test_a_stage_beds_head_is_toward_the_back_wall(stage):
    path = stage / WORKSPACE / "world3d-edits" / f"{SCENE}.json"
    record = json.loads(path.read_text())
    record["document"]["room"] = {"mold": {"id": "dormitorio", "blocks": [{"id": "bed", "kind": "bed", "box": [0, 0, -1.3, 1.7, 0.55, 2.2]}]}}
    path.write_text(json.dumps(record))
    viewed = patch(stage, [{"object_id": "stand", "add": True, "furniture": {"kind": "nightstand"}, "beside": {"object": "bed"}}])
    (nx0, _ny, nz0), (nx1, _ny1, _nz1) = box(viewed, "stand")
    assert nz0 == pytest.approx(-1.3 - 1.1, abs=0.01), "lined up with the head end against the back wall (-z)"
    assert nx1 == pytest.approx(-0.85, abs=0.01), "on the right of someone lying with the head at the back wall: scene -x"
