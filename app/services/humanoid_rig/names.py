"""Shared names for the standard humanoid skeleton and its landmarks."""

from __future__ import annotations

NORMAL_HEIGHT = 1.7

LANDMARK_NAMES = (
    "crotch",
    "neck",
    "head",
    "crown",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "left_ball",
    "right_ball",
    "left_toe",
    "right_toe",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hand_tip",
    "right_hand_tip",
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
    "talk",
    "nod",
    "look_around",
    "bow",
    "point",
    "shrug",
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
    "talk": "Talk",
    "nod": "Nod",
    "look_around": "Look Around",
    "bow": "Bow",
    "point": "Point",
    "shrug": "Shrug",
}

# (category, one-line description) for catalogs and the Rig panel.
CLIP_INFO = {
    "idle": ("Stand", "Relaxed standing loop: breathing, a slow weight shift and a glance."),
    "breathe": ("Stand", "A deep breath that lifts the chest and shoulders."),
    "walk": ("Move", "Walk cycle in place with planted feet, hip sway and arm swing."),
    "run": ("Move", "Run cycle in place with a flight phase and bent arms."),
    "jump": ("Move", "Crouch, take off, land and recover, in place."),
    "wave": ("Gesture", "Right hand raised and waving hello."),
    "cheer": ("Gesture", "Both arms up, pumping on the beat."),
    "dance_bounce": ("Dance", "Knee bounce on every beat with swinging arms."),
    "dance_side": ("Dance", "Side to side sway with a foot lift on each side."),
    "dance_arms": ("Dance", "Disco arms: one up, one down, switching each bar."),
    "clap": ("Gesture", "Hands meet in front of the chest on every beat."),
    "punch": ("Action", "Guard stance and a straight right punch."),
    "sit_down": ("Move", "Sit down on an unseen seat, hold, and stand up."),
    "victory": ("Gesture", "Arms raised in a V with a small bounce."),
    "talk": ("Gesture", "Conversation gestures with both hands and small nods."),
    "nod": ("Gesture", "Two nods yes."),
    "look_around": ("Gesture", "Turns the head and chest left, then right."),
    "bow": ("Gesture", "A polite bow from the hips and back up."),
    "point": ("Gesture", "Points forward with the right arm and holds."),
    "shrug": ("Gesture", "Shoulders up with open palms: I don't know."),
}
