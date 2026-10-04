"""BVH reader for the retargeter: hierarchy, rest offsets and per-frame channels.

Euler channels are intrinsic in the order they are listed: the first is
applied first, each next one on the right (Hamilton product, xyzw). Position
channels replace the joint offset for that frame.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig import rotation as rot
from services.humanoid_rig.errors import InvalidInput

_AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}


def parse_bvh(text: str, label: str = "Imported") -> dict:
    """Return the retargeter's source dict: names, parents, rest and one animation."""
    tokens = text.replace("{", " { ").replace("}", " } ").split()
    reader = _Reader(tokens)
    reader.expect("HIERARCHY")
    joints: list[dict] = []
    reader.joint(joints, None)
    frames, frame_time, values = reader.motion()
    stride = sum(len(joint["channels"]) for joint in joints)
    if frames < 1 or values.size != frames * stride:
        raise InvalidInput("BVH motion data does not match its channels")
    table = values.reshape(frames, stride)
    times = np.arange(frames, dtype=np.float64) * frame_time
    return {
        "names": [joint["name"] for joint in joints],
        "parents": [joint["parent"] for joint in joints],
        "rest": [(joint["offset"].copy(), rot.IDENTITY.copy(), np.ones(3)) for joint in joints],
        "animations": [{"name": label, "tracks": _tracks(joints, table, times)}],
    }


def _tracks(joints: list[dict], table: np.ndarray, times: np.ndarray) -> dict:
    tracks = {}
    column = 0
    for index, joint in enumerate(joints):
        channels = joint["channels"]
        block = table[:, column:column + len(channels)]
        column += len(channels)
        if not channels:
            continue
        entry = {}
        quats = np.broadcast_to(rot.IDENTITY, (len(times), 4)).copy()
        position = np.broadcast_to(joint["offset"], (len(times), 3)).copy()
        moved = False
        for offset, channel in enumerate(channels):
            kind, axis = channel[1:], channel[0]
            if kind == "rotation":
                quats = rot.multiply(quats, rot.axis_angle(_AXES[axis], block[:, offset]))
            else:
                position[:, "XYZ".index(axis)] = block[:, offset]
                moved = True
        if any(channel.endswith("rotation") for channel in channels):
            entry["rotation"] = (times, quats, "LINEAR")
        if moved:
            entry["translation"] = (times, position, "LINEAR")
        tracks[index] = entry
    return tracks


class _Reader:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.index = 0

    def take(self) -> str:
        if self.index >= len(self.tokens):
            raise InvalidInput("BVH file ends too early")
        self.index += 1
        return self.tokens[self.index - 1]

    def peek(self) -> str:
        return self.tokens[self.index] if self.index < len(self.tokens) else ""

    def expect(self, word: str) -> None:
        if self.take() != word:
            raise InvalidInput(f"BVH: expected {word}")

    def joint(self, joints: list[dict], parent: int | None) -> None:
        kind = self.take()
        if kind == "End":
            self.expect("Site")
            self._end_site()
            return
        if kind not in ("ROOT", "JOINT"):
            raise InvalidInput(f"BVH: unexpected {kind}")
        entry = {"name": self.take(), "parent": parent, "offset": np.zeros(3), "channels": []}
        joints.append(entry)
        index = len(joints) - 1
        self.expect("{")
        while self.peek() not in ("}", ""):
            self._joint_field(joints, entry, index)
        self.expect("}")

    def _joint_field(self, joints: list[dict], entry: dict, index: int) -> None:
        word = self.peek()
        if word == "OFFSET":
            self.take()
            entry["offset"] = np.array([float(self.take()) for _ in range(3)])
        elif word == "CHANNELS":
            self.take()
            entry["channels"] = [self._channel(self.take()) for _ in range(int(self.take()))]
        elif word in ("JOINT", "End"):
            self.joint(joints, index)
        else:
            raise InvalidInput(f"BVH: unexpected {word}")

    def _channel(self, name: str) -> str:
        if len(name) != 9 or name[0] not in "XYZ" or name[1:] not in ("rotation", "position"):
            raise InvalidInput(f"BVH: unknown channel {name}")
        return name

    def _end_site(self) -> None:
        self.expect("{")
        while self.peek() not in ("}", ""):
            self.take()
        self.expect("}")

    def motion(self) -> tuple[int, float, np.ndarray]:
        self.expect("MOTION")
        self.expect("Frames:")
        frames = int(self.take())
        self.expect("Frame")
        self.expect("Time:")
        frame_time = float(self.take())
        if frame_time <= 0.0:
            raise InvalidInput("BVH frame time must be positive")
        rest = self.tokens[self.index:]
        return frames, frame_time, np.asarray([float(item) for item in rest], dtype=np.float64)
