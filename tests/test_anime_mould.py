"""The anime mould (``blob_loft``): what must not move, and how the arms follow their bones.

The first half pins what the realistic (PS2) style and the vertical cards depend on: the lofted bytes of a ``style: real``
body and the face anchor of the reference characters. They were taken from the mould before the arm and face work, so an
edit that leaks into the real style or moves a head fails here.
"""
import hashlib

import pytest

from services.anime_make import resolve_traits
from services.blob_builder import blob_pieces
from services.blob_loft import loft_glb

# sha256 of ``loft_glb`` for the real-style body of each gender, from the mould as approved with the PS2 heads
REAL_MOULD = {
    ("man", None, None): "b243b96a898a4907d47f81497104c7ddb3514bec87b38c62eadd16fa586fe1d5",
    ("woman", None, None): "b175b6759c3bb1f75e02b0ae16ac060200a3936a57cd9aa68a70813d2a0cdb90",
    ("boy", None, None): "c676375984108c40916112723f329ecd20db4494a8f4f5fe5efe04ecb974101d",
    ("girl", None, None): "f06a0a714974922036f46a35ba6bf22b131efc64733336bea9b36f132ea1c012",
    ("woman", "bob", 1.7): "df342e29e26a9caccd662c6dda5b66ebe071e312a793301243569f661910f662",
}


def _real(gender, hair, height):
    raw = {"style": "real", "gender": gender, **({"hair_style": hair} if hair else {}), **({"height": height} if height else {})}
    built = blob_pieces(resolve_traits(raw)["body"])
    return hashlib.sha256(loft_glb(built["traits"], built["layout"], "blob")).hexdigest()


@pytest.mark.parametrize("key", list(REAL_MOULD), ids=lambda key: "-".join(str(part) for part in key if part))
def test_real_style_mould_is_byte_identical(key):
    assert _real(*key) == REAL_MOULD[key], "a change to the anime mould reached the realistic style"


# The reference characters of the vertical cards: (height, head kind, outfit, skirt) -> the head centre their framing depends on.
REFERENCE_HEAD = {
    "Ana": ({"height": 1.62, "head": {"width": 0.12, "height": 0.146, "depth": 0.128, "shape": "anime", "kind": "fem"}}, [0.0, 1.50174, 0.0], [0.0972, 0.11826, 0.10368]),
    "Eva": ({"height": 1.66, "head": {"width": 0.12, "height": 0.146, "depth": 0.128, "shape": "anime", "kind": "fem"}}, [0.0, 1.53882, 0.0], [0.0996, 0.12118, 0.10624]),
    "Teo": ({"height": 1.9008, "head": {"width": 0.108, "height": 0.152, "depth": 0.136, "shape": "anime", "kind": "boy"}}, [0.0, 1.7563392, 0.0], [0.1026432, 0.1444608, 0.12925440000000002]),
}


@pytest.mark.parametrize("name", list(REFERENCE_HEAD))
def test_face_anchor_does_not_move(name):
    traits, center, radii = REFERENCE_HEAD[name]
    body = {"family": "anime", "mesh": "loft", "build": "slim", "hands": "mitten", "feet": "shoe", "outfit": "school",
            "hair": {"style": "short", "color": "#2A211C"}, **traits}
    anchor = blob_pieces(body)["faceAnchor"]
    assert anchor["center"] == pytest.approx(center, abs=1e-9)
    assert anchor["radii"] == pytest.approx(radii, abs=1e-9)


# ---- the arms: mesh, joints and weights agree for any height, build, outfit, head and skirt ----

import numpy as np  # noqa: E402

from services.blob_builder import PRESETS, _layout, _normalize  # noqa: E402
from services.humanoid_rig.clips import clip_library, rig_for_skeleton  # noqa: E402
from services.humanoid_rig.comfort import comfort_limits  # noqa: E402
from services.humanoid_rig.gltf_export import read_primitives  # noqa: E402
from services.humanoid_rig.landmarks import detect_landmarks  # noqa: E402
from services.humanoid_rig.names import BONE_NAMES  # noqa: E402
from services.humanoid_rig.rig import _combined  # noqa: E402
from services.humanoid_rig.skeleton import build_skeleton, world_matrices  # noqa: E402
from services.humanoid_rig.weights import compute_weights  # noqa: E402

# (gender, outfit, height, build, skirt, hair, arm thickness): the three reference characters first, then the edges. Hips drop to the hem
# under a skirt, a tall slim body without one was the case whose arms bowed like hoops, and a small round one never did. (A wide-shouldered
# body with long hair over a skirt makes the rig lose the neck notch and take the top of the sleeves for the head: a rig limit, not in this grid.)
ARM_GRID = [
    ("boy", "sport", 1.9008, "slim", None, "short", None), ("girl", "casual", 1.62, "slim", True, "long", None), ("girl", "school", 1.66, "slim", True, "bob", None),
    ("boy", "sport", 1.2, "slim", None, "short", None), ("girl", "sport", 1.2, "round", None, "twin_tails", None), ("man", "school", 1.95, "average", False, "short", None),
    ("man", "casual", 1.82, "average", None, "spiky", None), ("boy", "school", 1.5, "round", False, "bangs", None), ("girl", "casual", 1.95, "slim", False, "ponytail", None),
    ("woman", "school", 1.7, "average", True, "bob", None), ("boy", "casual", 1.35, "slim", True, "short", None), ("girl", "casual", 1.45, "slim", False, "bun", 0.03),
    ("man", "sport", 1.6, "pear", None, "none", 0.05),
]


def _body(gender, outfit, height, build, skirt, hair, thickness):
    body = resolve_traits({"gender": gender, "outfit": outfit, "height": height, "hair_style": hair})["body"]
    body["build"] = build
    if skirt is not None:
        body["accessories"] = [item for item in body["accessories"] if item["kind"] != "skirt"] + ([{"kind": "skirt", "color": "#1B2350"}] if skirt else [])
    if thickness:
        body["arms"] = {"length": 0.44, "thickness": thickness}
    return body


def _rig(body):
    """The mould, rigged on CPU the way ``rig_humanoid`` does, with the idle pose skinned: everything the arm checks read."""
    built = blob_pieces(body)
    positions, indices, _counts = _combined(read_primitives(loft_glb(built["traits"], built["layout"], "blob")))
    found = detect_landmarks(positions, indices)
    skeleton = build_skeleton(found["points"], found["height"], found["y_min"], found["facing"], found["head_region"], found["base"], found["robe"])
    joints, weights = compute_weights(positions, indices, skeleton, found["cloth"])
    limits = comfort_limits(positions, indices, joints, weights, skeleton)
    idle = clip_library(120.0, ["idle"], rig_for_skeleton(skeleton, limits))[0]
    bones = skeleton["bones"]
    rest = world_matrices(bones)
    moved = [dict(bone) for bone in bones]
    moved[0]["translation"] = idle["hips_translation"][0]
    posed_world = world_matrices(moved, {name: rotations[0] for name, rotations in idle["rotations"].items()})
    skin = np.stack([now @ np.linalg.inv(then) for now, then in zip(posed_world, rest)])
    homogeneous = np.c_[positions, np.ones(len(positions))]
    posed = sum(weights[:, k:k + 1] * np.einsum("nij,nj->ni", skin[joints[:, k]], homogeneous)[:, :3] for k in range(4))
    return {"L": built["layout"], "positions": positions, "joints": joints, "weights": weights, "skeleton": skeleton, "found": found,
            "posed": posed, "posed_joints": {bone["name"]: matrix[:3, 3] for bone, matrix in zip(bones, posed_world)}}


def _upper_arm_band(rig, side):
    """Mould vertices on the middle half of the upper arm (rest pose), and the bones the rig gave them."""
    world, L, positions = rig["skeleton"]["world"], rig["L"], rig["positions"]
    shoulder, elbow = world[f"{side}Arm"], world[f"{side}ForeArm"]
    low, high = (shoulder[0] + share * (elbow[0] - shoulder[0]) for share in (0.25, 0.75))
    reach = L["arm_d"] * 0.8
    return ((positions[:, 0] - low) * (positions[:, 0] - high) < 0) & (np.abs(positions[:, 1] - shoulder[1]) < reach) & (np.abs(positions[:, 2]) < reach)


def _arm_share(rig, side, band):
    names = np.array(BONE_NAMES)
    return sum(rig["weights"][band, k] * np.isin(names[rig["joints"][band, k]], [f"{side}Arm", f"{side}ForeArm"]) for k in range(4))


@pytest.mark.parametrize("case", ARM_GRID, ids=lambda case: "-".join(str(part) for part in case if part is not None))
def test_arms_follow_their_bones_and_hang_to_mid_thigh(case):
    rig = _rig(_body(*case))
    L, world = rig["L"], rig["skeleton"]["world"]
    assert not {"arms_steep", "short_arms", "hands_stuck"} & set(rig["found"]["warnings"])
    for side in ("Left", "Right"):
        # The joints sit on the mould's elbow and wrist. The rig puts the shoulder 0.4 to 7 cm inboard of the torso edge (its opening rounds the
        # shoulder corner; a skirt drops the hips to the hem) and the elbow and wrist at 44 % and 76 % of the path from there: measured worst 6.3 % and 2.8 %.
        assert abs(abs(world[f"{side}ForeArm"][0]) - L["elbow_x"]) <= 0.07 * L["arm_len"]
        assert abs(abs(world[f"{side}Hand"][0]) - L["wrist_x"]) <= 0.035 * L["arm_len"]
        # an upper arm weighs on the arm and the forearm, not on the clavicle (that is what bowed the arms)
        share = _arm_share(rig, side, _upper_arm_band(rig, side))
        assert share.mean() >= 0.95 and share.min() >= 0.8   # before the rings: a mean of 0.64 to 0.91; the clavicle keeps a little near the joint
    # idle, left arm: the skinned middle of the upper arm lies on the bone, and the elbow stays near the shoulder-wrist line
    band = _upper_arm_band(rig, "Left")
    shoulder, elbow, wrist = (rig["posed_joints"][f"Left{part}"] for part in ("Arm", "ForeArm", "Hand"))
    bone = elbow - shoulder
    centre = rig["posed"][band].mean(axis=0)
    along = float(np.clip(np.dot(centre - shoulder, bone) / np.dot(bone, bone), 0.0, 1.0))
    assert np.linalg.norm(centre - (shoulder + along * bone)) <= 0.1 * L["arm_d"]
    line = (wrist - shoulder) / np.linalg.norm(wrist - shoulder)
    assert np.linalg.norm((elbow - shoulder) - line * np.dot(elbow - shoulder, line)) <= 0.07 * L["arm_len"]
    # the fingertips of the hanging arm end around mid-thigh, not near the knee
    tip = rig["posed"][:, 1][rig["positions"][:, 0] > L["tip_x"] * 0.97].min()
    assert 0.4 <= (L["leg_top"] - tip) / (L["leg_top"] - L["knee"]) <= 0.62


def test_only_a_lofted_anime_arm_is_shortened():
    """The cap belongs to the lofted anime body that is not realistic: the pieces body and the real style keep 0.42 of the height."""
    pieces = _layout(_normalize({**PRESETS["anime_boy"], "mesh": "pieces"}))
    assert pieces["arm_len"] == pytest.approx(0.42 * pieces["h"])
    loft = _layout(_normalize({**PRESETS["anime_boy"], "mesh": "loft"}))
    assert loft["arm_len"] == pytest.approx(0.385 * loft["h"])
    real = blob_pieces(resolve_traits({"style": "real", "gender": "man"})["body"])["layout"]
    assert real["arm_len"] == pytest.approx(0.42 * real["h"])
