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
        # The joints sit on the mould's elbow and wrist. The rig puts the shoulder 0.4 to 3.7 cm inboard of the torso edge (its opening rounds the
        # shoulder corner; a skirt drops the hips to the hem) and the elbow and wrist at 44 % and 76 % of the path from there: measured worst 3.6 % and 1.7 %.
        assert abs(abs(world[f"{side}ForeArm"][0]) - L["elbow_x"]) <= 0.045 * L["arm_len"]
        assert abs(abs(world[f"{side}Hand"][0]) - L["wrist_x"]) <= 0.025 * L["arm_len"]
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


# ---- shoulders, neck, hands, chin, hair and face of the anime mould (the real style keeps its own: see the byte test above) ----

from services.blob_hair import hair_mesh  # noqa: E402
from services.blob_loft import arm_line, loft_parts, neck_width, shoulder_top, skull_point  # noqa: E402


def _anime(gender="boy", hair="short", **extra):
    raw = {"gender": gender, "hair_style": hair, **extra}
    return blob_pieces(resolve_traits(raw)["body"])


def test_neck_is_shorter_and_slimmer_but_the_head_and_the_arms_stay_where_they_were():
    for gender, kind_share in (("girl", 0.37), ("boy", 0.41), ("man", 0.50)):
        built = _anime(gender)
        L = built["layout"]
        old_close = L["head_y"] - L["sy"] / 2 - 0.035 * L["h"]
        assert shoulder_top(L) == pytest.approx(old_close + 0.009 * L["h"])
        assert arm_line(L) == pytest.approx(old_close - 0.03 * L["h"])   # the arms hang from the line they always did
        assert neck_width(L) <= L["sx"] * kind_share + 1e-9
        assert built["faceAnchor"]["center"][1] == pytest.approx(L["head_y"])
    real = blob_pieces(resolve_traits({"style": "real", "gender": "man"})["body"])["layout"]
    assert shoulder_top(real) == pytest.approx(real["head_y"] - real["sy"] / 2 - 0.022 * real["h"])   # the real style closes where it did


def test_chin_is_round_not_a_point_and_only_the_anime_mould_has_it():
    for gender in ("girl", "boy"):   # the man's measured chin is already a flat plate: it keeps its own
        L = _anime(gender)["layout"]
        real = {**L, "real": True}
        low = lambda layout: max(abs(skull_point(layout, yaw, -84.0)[0]) for yaw in range(0, 360, 15))
        assert low(L) > 1.25 * low(real), gender   # the chin plate is wider than the measured V's tip
        # above the chin the skull is the measured one, to the digit
        assert skull_point(L, 40.0, -20.0) == skull_point(real, 40.0, -20.0)
        assert skull_point(L, 40.0, 30.0) == skull_point(real, 40.0, 30.0)


@pytest.mark.parametrize("style", ["short", "bangs", "bob", "long", "twin_tails", "ponytail", "spiky", "bun"])
def test_hair_leaves_the_face_clear_below_the_brows_and_in_front_of_the_cheeks(style):
    """No lock hangs over the eyes or across the face: everything of the hair that is in the face plane (in front, inside the cheeks) lies at or
    above the equator of the head. The brows are 4 degrees under it and the eyes 15. A bob used to start its ring in front of the face on one side."""
    L = _anime("girl", style)["layout"]
    hair = hair_mesh(L, {"style": style, "color": "#2A211C"})
    rx, rz = L["sx"] / 2, L["sz"] / 2
    in_front = [(x, y, z) for x, y, z in hair.vertices if z > 0.5 * rz and abs(x) < 0.5 * rx]
    assert in_front, style
    assert min(y for _x, y, _z in in_front) >= L["head_y"] - 0.01 * L["sy"]


def test_the_hand_is_a_relaxed_palm_wider_than_it_is_thick():
    """Palm down in the T pose: the lowered arm turns it to the thigh. The old paddle was thicker than wide and showed its flat face to the camera."""
    def hand_extent(layout_traits):
        built = blob_pieces(layout_traits)
        L = built["layout"]
        body = loft_parts(built["traits"], L)[0][0]
        pts = [(x, y, z) for x, y, z in body.vertices if x > L["wrist_x"] + 0.01 and abs(y - L["shoulder_y"]) < L["arm_d"] and abs(z) < L["arm_d"]]
        return max(p[1] for p in pts) - min(p[1] for p in pts), max(p[2] for p in pts) - min(p[2] for p in pts)
    thick, wide = hand_extent(resolve_traits({"gender": "boy"})["body"])
    assert wide > 1.5 * thick
    old_thick, old_wide = hand_extent(resolve_traits({"style": "real", "gender": "man"})["body"])
    assert old_thick > old_wide


def test_the_drawn_anime_face_is_larger_and_the_painted_and_real_faces_keep_theirs():
    from services.blob_face import face_kit, face_traits
    from services.blob_face_anime_head import DIMS

    assert resolve_traits({"gender": "girl"})["face"]["detail"] == 2
    assert "detail" not in resolve_traits({"gender": "man", "style": "real"})["face"]
    assert "detail" not in resolve_traits({"face_style": "cute"})["face"]
    assert "detail" not in resolve_traits({"face_source": "qwen", "face_image": "painted.png"})["face"]   # the painted kit keeps the face as it was
    assert "detail" not in face_traits({"style": "anime_head"})   # no key, so no id derived from the traits of any other style changes
    assert "detail" not in face_traits({"style": "blob"}) and "detail" not in face_traits({})
    assert DIMS[2][1] > 1.1 * DIMS[1][1] and DIMS[2][2] > 1.1 * DIMS[1][2]
    wide = {}
    for detail in (1, 2):
        kit = face_kit({"style": "anime_head", "detail": detail})
        box = kit["mouths"]["closed"].getbbox()
        wide[detail] = box[2] - box[0]
    assert wide[2] > 1.25 * wide[1]
