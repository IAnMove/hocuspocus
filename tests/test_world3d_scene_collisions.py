"""A moving Video 3D object that passes through another is reported (layout.collisions and a collision warning), without rendering."""
import math
import os
import random
from pathlib import Path

import pytest

from services.world3d_scene_bounds import normalisation, placed_bounds, slot_native_bounds
from services.world3d_scene_collisions import Body, _frame, _ground_like, _kept, _place, scene_collisions
from services.world3d_scenes import inspect_scene
from tests.test_glb_bounds import accessor, mesh, write
from tests.test_world3d_scene_layout import SCENE, WORKSPACE, scene, slot, workspace_dir

TOWN = "/api/v1/file/town.glb?workspace=studio"
WALKER = "/api/v1/file/walker.glb?workspace=studio"


def glb(tmp_path, name, boxes):
    """A GLB with one mesh node per ``(low, high)`` box; every box is 1.7 m tall, so the renderer's factor is 1."""
    folder = tmp_path / WORKSPACE
    folder.mkdir(exist_ok=True)
    document = {"scene": 0, "scenes": [{"nodes": list(range(len(boxes)))}],
                "nodes": [{"mesh": index, "name": f"part {index}"} for index in range(len(boxes))],
                "meshes": [mesh(index) for index in range(len(boxes))], "accessors": [accessor(list(low), list(high)) for low, high in boxes]}
    return write(folder, document, name)


def village(tmp_path):
    """A 40 m ground slab (the lowest part, 0.2 m thick), a 4 x 1.7 x 4 m house at the origin and a roof slab on a tall tower."""
    glb(tmp_path, "town.glb", [((-20, -0.2, -20), (20, 0, 20)), ((-2, 0, -2), (2, 1.7, 2)), ((8, 0, -1), (10, 1.7, 1))])


def walker(tmp_path):
    glb(tmp_path, "walker.glb", [((-0.5, 0, -0.5), (0.5, 1.7, 0.5))])


def world(tmp_path, *objects, **document):
    village(tmp_path)
    walker(tmp_path)
    return scene(tmp_path, [slot("town", TOWN, grounded=True), *objects], **document)


def passer(identifier="walker", to=(0, 0, -10), at=(0, 0, 10), **fields):
    return slot(identifier, WALKER, position=list(at), grounded=True, motion={"to": list(to), "easing": "linear", **fields.pop("motion", {})}, **fields)


def test_a_walker_crossing_the_house_is_reported_with_part_time_depth_and_place(tmp_path):
    viewed = world(tmp_path, passer())                       # z = 10 - 4t over the 5 s of the scene; the house spans z -2..2
    (hit,) = viewed["layout"]["collisions"]
    assert (hit["a"], hit["b"], hit["part"], hit["partName"]) == ("walker", "town", 1, "part 1")
    assert hit["from_s"] == pytest.approx(1.9, abs=0.1) and hit["to_s"] == pytest.approx(3.1, abs=0.1)
    assert hit["depth_m"] == pytest.approx(1.0, abs=0.01) and hit["at"] == pytest.approx([0, 0.85, 0], abs=0.15)
    assert any(line.startswith("collision: walker passes through town (part 1 \"part 1\") at ") and "near [0.0," in line for line in viewed["warnings"])


def test_a_walker_beside_the_house_and_over_the_ground_slab_hits_nothing(tmp_path):
    viewed = world(tmp_path, passer(at=(5, 0, 10), to=(5, 0, -10)), passer("sunk", at=(-6, -0.1, 10), to=(-6, -0.1, -10)))
    assert viewed["layout"]["collisions"] == [] and not [line for line in viewed["warnings"] if line.startswith("collision")]


def test_the_ground_is_flat_wide_and_low_in_its_model_and_a_roof_is_not():
    box = {"min": [-20, -0.2, -20], "size": [40, 10, 40]}
    assert _ground_like({"min": [-20, -0.2, -20], "max": [20, 0, 20]}, box)
    assert _ground_like({"min": [-1, 0.2, -10], "max": [1, 0.35, 10]}, box), "a cobbled lane"
    assert not _ground_like({"min": [-20, 8, -20], "max": [20, 8.2, 20]}, box), "a flat roof high up is an obstacle"
    assert not _ground_like({"min": [-2, 0, -2], "max": [2, 3, 2]}, box), "a house is not flat"


def test_a_move_is_checked_only_while_it_runs(tmp_path):
    viewed = world(tmp_path, passer(motion={"start": 2.5}))       # waits at z=10 until 2.5 s, then 7.5 m/s... crosses z 2.5..-2.5 later
    (hit,) = viewed["layout"]["collisions"]
    start = 2.5 + (10 - 2.5) / 20 * 2.5
    assert hit["from_s"] == pytest.approx(start, abs=0.1) and hit["to_s"] == pytest.approx(2.5 + (10 + 2.5) / 20 * 2.5, abs=0.1)
    waiting = world(tmp_path, passer(at=(0, 0, 0), to=(0, 0, -10), motion={"start": 1, "end": 4}))
    assert waiting["layout"]["collisions"], "it starts inside the house: the first samples are inside it"
    assert world(tmp_path, passer(at=(0, 0, 6), to=(0, 0, 3), motion={"start": 1, "end": 4}))["layout"]["collisions"] == []


def test_two_objects_that_stand_still_are_never_compared(tmp_path):
    viewed = world(tmp_path, slot("guest", WALKER, position=[0, 0, 0], grounded=True))
    assert viewed["layout"]["collisions"] == [] and viewed["warnings"] == []


def test_collide_false_a_held_object_and_an_object_that_has_not_appeared_are_left_out(tmp_path):
    assert world(tmp_path, passer(collide=False))["layout"]["collisions"] == []
    assert world(tmp_path, passer(hold={"carrier": "town", "hand": "left"}))["layout"]["collisions"] == []
    late = world(tmp_path, passer(appearance={"start": 3.5, "duration": 0.5, "color": "#ffffff"}))
    assert late["layout"]["collisions"] == [], "it appears after it has left the house (z -2.5 at 3.1 s)"
    early = world(tmp_path, passer(appearance={"start": 2.5, "duration": 0.5, "color": "#ffffff"}))
    assert early["layout"]["collisions"][0]["from_s"] >= 2.5


def test_two_movers_are_compared_once_and_the_faster_one_that_crosses_is_found(tmp_path):
    viewed = world(tmp_path, passer("a", at=(10, 0, 5), to=(-10, 0, 5)), passer("b", at=(0, 0, 10), to=(0, 0, 0)))
    pairs = {(row["a"], row["b"]) for row in viewed["layout"]["collisions"]}
    assert ("a", "b") in pairs and ("b", "a") not in pairs


def test_a_fixed_camera_inside_a_part_warns_and_other_cameras_and_outside_eyes_do_not(tmp_path):
    inside = world(tmp_path, camera={"family": "fixed", "eye": [0.5, 1.0, 0.5], "look": [0, 1, -5], "fov": 45})
    assert any(line.startswith("camera_inside_geometry:") and "town" in line and "part 1" in line for line in inside["warnings"])
    assert not [line for line in world(tmp_path, camera={"family": "fixed", "eye": [0, 1.0, 6], "look": [0, 1, 0], "fov": 45})["warnings"] if "camera_inside" in line]
    orbit = world(tmp_path, camera={"family": "orbit", "eye": [0.5, 1.0, 0.5], "look": [0, 1, 0], "fov": 45})
    assert not [line for line in orbit["warnings"] if "camera_inside" in line]


def test_the_deepest_passages_of_a_pair_are_listed_and_the_rest_counted_in_the_warnings(tmp_path):
    glb(tmp_path, "town.glb", [((x * 3 - 40, 0, -1), (x * 3 - 39, 1.7, 1)) for x in range(20)])      # twenty posts in a row
    walker(tmp_path)
    viewed = scene(tmp_path, [slot("town", TOWN, grounded=True), passer(at=(-45, 0, 0), to=(25, 0, 0))])
    assert len(viewed["layout"]["collisions"]) == 4 and viewed["layout"]["collisionsOmitted"] == 16
    lines = [line for line in viewed["warnings"] if line.startswith("collision")]
    assert len(lines) == 5 and lines[-1] == "collision: 16 more passages (0 listed in layout.collisions, 16 beyond its cap)"


def test_the_whole_list_is_capped_at_twelve():
    runs = [{"a": f"m{index // 4}", "b": "town", "part": index, "from": float(index), "to": index + 0.5, "depth": 1 + index / 100, "at": [0, 0, 0]}
            for index in range(20)]
    shown, left = _kept(runs)
    assert len(shown) == 12 and left == 8 and [row["from_s"] for row in shown] == sorted(row["from_s"] for row in shown)


def test_an_unreadable_model_or_a_marker_means_no_collisions_and_never_a_failed_inspect(tmp_path):
    (tmp_path / WORKSPACE).mkdir(exist_ok=True)
    (tmp_path / WORKSPACE / "town.glb").write_bytes(b"nope")
    viewed = scene(tmp_path, [slot("town", TOWN), slot("marker"), passer()])
    assert viewed["layout"]["collisions"] == []


def test_the_placement_matches_the_layout_boxes_the_renderer_maths_of_placed_bounds(tmp_path):
    glb(tmp_path, "thing.glb", [((-1, -0.5, -2), (3, 1.7, 1))])
    random.seed(4)
    for _ in range(25):
        item = slot("thing", "/api/v1/file/thing.glb?workspace=studio", position=[random.uniform(-5, 5) for _ in range(3)], scale=random.uniform(0.3, 3),
                    rotationY=random.uniform(-4, 4), grounded=random.random() < 0.5)
        box = slot_native_bounds(item, WORKSPACE, workspace_dir(tmp_path))
        body = Body(item, box, [], normalisation(box) * item["scale"], False)
        low, high = _place(box["min"], box["max"], _frame(body, item["position"], item["rotationY"]))
        expected = placed_bounds(box, item)
        assert low == pytest.approx(expected["min"], abs=1e-3) and high == pytest.approx(expected["max"], abs=1e-3)


FILM = os.environ.get("WORLD3D_FILM_GLB_DIR")


@pytest.mark.skipif(not FILM or not (Path(FILM) / "mts8JE.glb").is_file(), reason="the film's GLBs are not here (set WORLD3D_FILM_GLB_DIR)")
def test_the_films_biplane_crosses_the_village_and_the_samurai_walks_its_street(tmp_path):
    folder = tmp_path / WORKSPACE
    folder.mkdir(exist_ok=True)
    for source, name in (("mts8JE", "village"), ("sJHume", "biplane"), ("LS6EBs", "samurai")):
        (folder / f"{name}.glb").write_bytes((Path(FILM) / f"{source}.glb").read_bytes())
    url = lambda name: f"/api/v1/file/{name}.glb?workspace=studio"       # noqa: E731
    # fit longestM 30 / 2.0 / height 1.6 (scales as the film's patches computed them from the GLBs)
    village_scale = 30 / (1.7 / 16.89 * 60)
    biplane_scale = 2.0 / (1.7 / 0.97 * 1.87)
    plane = slot("avioneta", url("biplane"), position=[-1.5, 2.0, 7], scale=biplane_scale, grounded=True,
                 motion={"to": [1.2, 2.6, -16], "faceTravel": True, "easing": "linear"})
    hero = slot("samurai", url("samurai"), position=[0.3, 0, 8.6], scale=1.6 / 1.7, grounded=True,
                motion={"to": [0.3, 0, -3], "faceTravel": True, "easing": "smooth"})
    town = slot("village", url("village"), scale=village_scale, grounded=True)
    flown = scene(tmp_path, [town, plane], duration=3)
    assert any(row["b"] == "village" and "House" in (row.get("partName") or "") or "tower" in (row.get("partName") or "") for row in flown["layout"]["collisions"])
    walked = scene(tmp_path, [town, hero], duration=5)
    assert walked["layout"]["collisions"] == []


def test_inspect_carries_the_collisions_too(tmp_path):
    world(tmp_path, passer())
    again = inspect_scene(WORKSPACE, SCENE, workspace_dir(tmp_path))
    assert again["layout"]["collisions"] and any(line.startswith("collision:") for line in again["warnings"])
    assert scene_collisions(again["document"], None, None) == {"collisions": [], "omitted": 0, "warnings": []}
    assert math.isfinite(again["layout"]["collisions"][0]["depth_m"])
