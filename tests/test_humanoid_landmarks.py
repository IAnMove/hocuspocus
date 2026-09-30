"""Landmark error against the construction values of the compose humanoids."""
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.landmarks import detect_landmarks
from services.humanoid_rig.names import LANDMARK_NAMES
from services.procedural_3d.compose import compose_glb
from services.procedural_3d.glb_container import parse_glb_container

ROOT = Path(__file__).parents[1] / "tests" / "fixtures" / "humanoid_rig"
VALID = ("robot", "pet", "a_pose")


def load(name):
    return json.loads((ROOT / f"{name}.json").read_text())


def positions_of(data):
    container = parse_glb_container(data, max_chunks=2, max_json_bytes=200_000)
    document = json.loads(container.json_bytes)
    view = document["bufferViews"][0]
    accessor = document["accessors"][0]
    count = accessor["count"]
    offset = view.get("byteOffset", 0)
    values = struct.unpack_from(f"<{count * 3}f", container.bin_bytes, offset)
    return np.asarray(values, dtype=np.float64).reshape(-1, 3)


def mesh(name):
    fixture = load(name)
    return fixture, positions_of(compose_glb(fixture["pieces"], name))


@pytest.mark.parametrize("name", VALID)
def test_landmarks_match_construction_within_four_percent(name):
    fixture, cloud = mesh(name)
    found = detect_landmarks(cloud)
    height = found["height"]
    assert found["confidence"] == 1.0
    assert list(found["points"]) == list(LANDMARK_NAMES)
    for landmark, target in fixture["landmarks"].items():
        error = np.linalg.norm(np.asarray(found["points"][landmark]) - np.asarray(target))
        assert error / height < 0.04, landmark


def test_detection_is_deterministic_and_index_buffer_matches():
    _fixture, cloud = mesh("robot")
    assert detect_landmarks(cloud)["points"] == detect_landmarks(cloud.copy())["points"]
    indices = np.arange(len(cloud), dtype=np.int64).reshape(-1, 3)
    assert detect_landmarks(cloud, indices)["points"] == detect_landmarks(cloud)["points"]


@pytest.mark.parametrize("name", ("hands_stuck", "one_leg"))
def test_invalid_humanoids_fail_with_their_own_reason(name):
    fixture, cloud = mesh(name)
    with pytest.raises(NotHumanoid) as caught:
        detect_landmarks(cloud)
    assert caught.value.code == "not_humanoid"
    assert caught.value.reason == fixture["reason"]
    assert str(caught.value).startswith("not_humanoid:")


def test_stuck_hands_and_one_leg_are_different_reasons():
    reasons = []
    for name in ("hands_stuck", "one_leg"):
        _fixture, cloud = mesh(name)
        with pytest.raises(NotHumanoid) as caught:
            detect_landmarks(cloud)
        reasons.append(caught.value.reason)
    assert reasons == ["hands_stuck", "single_leg"]


def test_degenerate_mesh_is_rejected():
    with pytest.raises(NotHumanoid) as caught:
        detect_landmarks(np.zeros((3, 3)))
    assert caught.value.reason == "degenerate"
