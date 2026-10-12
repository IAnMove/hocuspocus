"""Foot landings recorded per humanoid clip, for footsteps that follow the animation."""
import numpy as np
import pytest

pytest.importorskip("pygltflib")

from pygltflib import GLTF2

from services.humanoid_rig.animate import animate_humanoid
from services.humanoid_rig.clip_recipes import RECIPES
from services.humanoid_rig.clips import FPS, clip_library, default_rig
from services.humanoid_rig.motion import Pose
from services.humanoid_rig.retarget import retarget_file
from services.humanoid_rig.rig import rig_humanoid
from tests.humanoid_bodies import as_glb, body
from tests.humanoid_sources import as_bytes, cmu_like_bvh, mixamo_like_gltf


def _planted_starts(rig, clip):
    """Frames where the recipe puts each foot back on the floor (its lift returns to zero)."""
    times = clip["times"]
    pose = Pose(rig, times / clip["duration"])
    RECIPES[clip["id"]][1](pose, times / clip["duration"])
    starts = {}
    for side, foot in (("Left", "left"), ("Right", "right")):
        up = pose.feet[side]["offset"][:-1, 1]
        starts[foot] = [i for i in range(len(up)) if up[i] <= 1e-9 < up[i - 1]]
    return starts


def _cyclic_frames(a: float, b: float, duration: float) -> float:
    gap = abs(a - b) % duration
    return min(gap, duration - gap) * FPS


def test_walk_lands_where_the_recipe_plants_each_foot_and_alternates():
    rig = default_rig()
    clip = clip_library(120.0, ["walk"], rig)[0]
    contacts = clip["contacts"]
    assert [item["foot"] for item in contacts] == ["right", "left"]
    starts = _planted_starts(rig, clip)
    for item in contacts:
        planted = [clip["times"][index] for index in starts[item["foot"]]]
        assert min(_cyclic_frames(item["t"], t, clip["duration"]) for t in planted) <= 1.0, item
    assert all(0.05 <= item["strength"] <= 1.0 for item in contacts)


@pytest.mark.parametrize("clip_id", ["idle", "breathe", "wave", "clap", "talk", "dance_bounce"])
def test_clips_that_keep_both_feet_down_have_no_landings(clip_id):
    assert clip_library(120.0, [clip_id], default_rig())[0]["contacts"] == []


def test_a_jump_lands_on_both_feet_harder_than_a_step():
    rig = default_rig()
    walk, jump = clip_library(120.0, ["walk", "jump"], rig)
    assert [item["foot"] for item in jump["contacts"]] == ["left", "right"]
    assert jump["contacts"][0]["t"] == jump["contacts"][1]["t"]
    assert jump["contacts"][0]["strength"] > max(item["strength"] for item in walk["contacts"])


def test_contacts_follow_the_tempo():
    rig = default_rig()
    slow, fast = (clip_library(bpm, ["walk"], rig)[0] for bpm in (60.0, 120.0))
    assert [item["t"] for item in slow["contacts"]] == pytest.approx([2 * item["t"] for item in fast["contacts"]], abs=1.5 / FPS)


@pytest.mark.parametrize("kind,payload", [
    (".gltf", lambda rig: as_bytes(mixamo_like_gltf(rig, "walk"))),
    (".bvh", lambda rig: cmu_like_bvh(rig, "walk").encode()),
])
def test_an_imported_walk_lands_on_alternating_feet(kind, payload):
    rig = default_rig()
    clip = retarget_file(payload(rig), kind, rig, "walk")[0]
    feet = [item["foot"] for item in clip["contacts"]]
    assert len(feet) >= 2 and all(a != b for a, b in zip(feet, feet[1:]))
    assert np.all(np.diff([item["t"] for item in clip["contacts"]]) > 0)


def test_contacts_are_stored_on_each_animation_of_the_glb():
    rigged, sidecar = rig_humanoid(as_glb(body("pet")), ["walk", "idle"])
    animations = GLTF2.load_from_bytes(rigged).animations
    # pygltflib drops empty lists when it saves, so a clip without landings has no key.
    assert [(animation.extras or {}).get("hocuspocus_contacts", []) for animation in animations] == [clip["contacts"] for clip in sidecar["clips"]]
    assert sidecar["clips"][1]["contacts"] == []
    data, listed, _warnings = animate_humanoid(rigged, ["jump"], 120)
    stored = GLTF2.load_from_bytes(data).animations
    assert stored[0].extras["hocuspocus_contacts"] == sidecar["clips"][0]["contacts"]
    assert stored[2].extras["hocuspocus_contacts"] == listed[0]["contacts"]
