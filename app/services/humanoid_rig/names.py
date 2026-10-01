"""Shared names for the standard humanoid skeleton and its landmarks."""

from __future__ import annotations

NORMAL_HEIGHT = 1.7

LANDMARK_NAMES = (
    "crotch",
    "crown",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_foot",
    "right_foot",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_hand",
    "right_hand",
)

# Parent of each bone. Order is parent-before-child.
BONE_PARENTS = (
    ("Hips", None),
    ("Spine", "Hips"),
    ("Spine1", "Spine"),
    ("Spine2", "Spine1"),
    ("Neck", "Spine2"),
    ("Head", "Neck"),
    ("HeadTop_End", "Head"),
    ("LeftShoulder", "Spine2"),
    ("LeftArm", "LeftShoulder"),
    ("LeftForeArm", "LeftArm"),
    ("LeftHand", "LeftForeArm"),
    ("RightShoulder", "Spine2"),
    ("RightArm", "RightShoulder"),
    ("RightForeArm", "RightArm"),
    ("RightHand", "RightForeArm"),
    ("LeftUpLeg", "Hips"),
    ("LeftLeg", "LeftUpLeg"),
    ("LeftFoot", "LeftLeg"),
    ("LeftToeBase", "LeftFoot"),
    ("LeftToe_End", "LeftToeBase"),
    ("RightUpLeg", "Hips"),
    ("RightLeg", "RightUpLeg"),
    ("RightFoot", "RightLeg"),
    ("RightToeBase", "RightFoot"),
    ("RightToe_End", "RightToeBase"),
)

BONE_NAMES = tuple(name for name, _parent in BONE_PARENTS)
BONE_BY_NAME = {name: index for index, name in enumerate(BONE_NAMES)}

SPINE_BONES = ("Hips", "Spine", "Spine1", "Spine2", "Neck", "Head", "HeadTop_End")
LEFT_ARM_BONES = ("LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand")
RIGHT_ARM_BONES = ("RightShoulder", "RightArm", "RightForeArm", "RightHand")
LEFT_LEG_BONES = ("LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase", "LeftToe_End")
RIGHT_LEG_BONES = ("RightUpLeg", "RightLeg", "RightFoot", "RightToeBase", "RightToe_End")

# Clip ids authored for this skeleton. Display names stay stable for Video 3D.
CLIP_IDS = (
    "idle",
    "breathe",
    "walk",
    "run",
    "jump",
    "wave",
    "cheer",
    "dance_bounce",
    "dance_side",
    "dance_arms",
    "clap",
    "punch",
    "sit_down",
    "victory",
)

CLIP_LABELS = {
    "idle": "Idle",
    "breathe": "Breathe",
    "walk": "Walk",
    "run": "Run",
    "jump": "Jump",
    "wave": "Wave",
    "cheer": "Cheer",
    "dance_bounce": "Dance Bounce",
    "dance_side": "Dance Side",
    "dance_arms": "Dance Arms",
    "clap": "Clap",
    "punch": "Punch",
    "sit_down": "Sit Down",
    "victory": "Victory",
}
