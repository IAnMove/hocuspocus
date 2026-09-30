"""Deterministic compose humanoids used by the standard rig."""
import hashlib
import json
from pathlib import Path

import pytest

from services.procedural_3d.compose import compose_glb

ROOT = Path(__file__).parents[1] / "tests" / "fixtures" / "humanoid_rig"
NAMES = ("robot", "pet", "a_pose", "hands_stuck", "one_leg")


def load(name):
    return json.loads((ROOT / f"{name}.json").read_text())


def test_fixture_set_is_small_and_complete():
    assert [path.stem for path in sorted(ROOT.glob("*.json"))] == sorted(NAMES)
    for name in NAMES:
        assert (ROOT / f"{name}.json").stat().st_size < 200_000


@pytest.mark.parametrize("name", NAMES)
def test_fixtures_regenerate_byte_identical(name):
    fixture = load(name)
    first = compose_glb(fixture["pieces"], name)
    second = compose_glb(fixture["pieces"], name)
    assert first == second
    assert hashlib.sha256(first).hexdigest() == fixture["sha256"]


def test_pet_head_is_one_third_of_height_and_a_pose_is_35_degrees():
    pet = load("pet")
    head = next(piece for piece in pet["pieces"] if piece["scale"][1] == 0.4)
    assert head["scale"][1] / 1.2 == pytest.approx(1 / 3)
    pose = load("a_pose")
    angles = [piece["rotation"][2] for piece in pose["pieces"] if "rotation" in piece]
    assert min(abs(angle) for angle in angles) == pytest.approx(35 * 3.141592653589793 / 180)
