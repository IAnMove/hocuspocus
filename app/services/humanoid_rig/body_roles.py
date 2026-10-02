"""Semantic body roles for humanoid compatibility.

VRM 1.0 humanoid names are a map only. This module does not declare a VRM
extension and does not claim that every Mixamo clip will play.
"""

from __future__ import annotations

CONTRACT_ID = "hocuspocus-humanoid-body"
CONTRACT_VERSION = "1.0"

PROFILE_EXTERNAL = "external-native"
PROFILE_V1 = "hocuspocus-body-v1"
PROFILE_LEGACY = "hocuspocus-legacy-body-v0"
PROFILE_MESHY = "meshy-blender-body-reference-v1"
KNOWN_PROFILES = (PROFILE_EXTERNAL, PROFILE_V1, PROFILE_LEGACY, PROFILE_MESHY)

STATUS_NATIVE = "native_playback"
STATUS_MAPPED = "mapped"
STATUS_REVIEW = "needs_review"
STATUS_VERIFIED = "retarget_verified"
STATUS_UNSUPPORTED = "unsupported"

# Fifteen roles the body retarget requires. Exporters add the other nodes.
REQUIRED_RETARGET_ROLES = (
    "hips",
    "spine",
    "head",
    "leftUpperArm",
    "leftLowerArm",
    "leftHand",
    "rightUpperArm",
    "rightLowerArm",
    "rightHand",
    "leftUpperLeg",
    "leftLowerLeg",
    "leftFoot",
    "rightUpperLeg",
    "rightLowerLeg",
    "rightFoot",
)

# role, export name, parent role, required for body retarget.
BODY_BONES = (
    ("hips", "Hips", None, True),
    ("spine", "Spine", "hips", True),
    ("chest", "Spine1", "spine", False),
    ("upperChest", "Spine2", "chest", False),
    ("neck", "Neck", "upperChest", False),
    ("head", "Head", "neck", True),
    ("leftShoulder", "LeftShoulder", "upperChest", False),
    ("leftUpperArm", "LeftArm", "leftShoulder", True),
    ("leftLowerArm", "LeftForeArm", "leftUpperArm", True),
    ("leftHand", "LeftHand", "leftLowerArm", True),
    ("rightShoulder", "RightShoulder", "upperChest", False),
    ("rightUpperArm", "RightArm", "rightShoulder", True),
    ("rightLowerArm", "RightForeArm", "rightUpperArm", True),
    ("rightHand", "RightHand", "rightLowerArm", True),
    ("leftUpperLeg", "LeftUpLeg", "hips", True),
    ("leftLowerLeg", "LeftLeg", "leftUpperLeg", True),
    ("leftFoot", "LeftFoot", "leftLowerLeg", True),
    ("leftToes", "LeftToeBase", "leftFoot", False),
    ("rightUpperLeg", "RightUpLeg", "hips", True),
    ("rightLowerLeg", "RightLeg", "rightUpperLeg", True),
    ("rightFoot", "RightFoot", "rightLowerLeg", True),
    ("rightToes", "RightToeBase", "rightFoot", False),
)

EXPORT_NAME_BY_ROLE = {role: name for role, name, _parent, _required in BODY_BONES}
PARENT_ROLE = {role: parent for role, _name, parent, _required in BODY_BONES}

# Our exporter creates these. An external source may omit them.
AUXILIARY_EXPORT_NODES = ("HeadTop_End", "LeftToe_End", "RightToe_End")

# Nodes after Hips on the measured Meshy/Blender reference, in hierarchy order.
# The file hash does not select this profile.
MESHY_SPINE_CHAIN = ("Spine02", "Spine01", "Spine", "neck", "Head")

SPINE_TORSO_ROLES = ("spine", "chest", "upperChest")
NEUTRAL_POSITION_M = 1e-5
NEUTRAL_RADIANS = 1e-4
CHILD_TRANSLATION_REST_M = 1e-5
CONSTANT_SCALE_EPSILON = 1e-6
LEGACY_CLIP_COUNT = 14
LEGACY_REFERENCE_HEIGHT_M = 1.7
V1_ROOT_NAME = "HocusPocusRoot"

# Humanoid height ratios outside this band are refused. A factor of 100 is the
# double-applied wrapper scale, not a character proportion.
HEIGHT_RATIO_MIN = 0.05
HEIGHT_RATIO_MAX = 20.0

_PREFIXES = ("mixamorig:", "mixamorig_", "Mixamo_", "Armature|")


def strip_joint_prefix(name: str) -> str:
    """Drop a known Mixamo or armature prefix. The remainder is not a role."""
    text = name or ""
    for prefix in _PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def normalized_joint_name(name: str) -> str:
    return strip_joint_prefix(name).lower()
