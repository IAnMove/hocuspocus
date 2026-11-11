"""Where a rigged character's joints are at a moment of its clip, in its GLB's own units, read in the app.

A character with the standard humanoid skeleton (``humanoid_rig.names``: ``Hips``, ``LeftUpLeg``, ``LeftLeg``,
``LeftFoot``...; a ``prefix:Hips`` name counts too) is sampled from its glTF animation channels at a clip time and run
through its node tree (``pose_math``), so the contact check of a Video 3D scene judges the pose the renderer draws, not
the bind-pose box. ``held_time`` says which clip and clip time a slot shows at a scene second, by the renderer's own
rules (``clipCues.cueLocalTime`` and ``performanceClipTime``). Nothing here raises; a model that is not a humanoid, or
that cannot be read, is ``None``.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from services.humanoid_rig.gltf_accessors import read_accessor, split_glb
from services.humanoid_rig.pose_math import sample_channel, trs_matrix, world_matrices

LOG = logging.getLogger(__name__)
JOINTS = ("Hips", "Spine2", "Neck", "Head", "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase", "RightUpLeg", "RightLeg",
          "RightFoot", "RightToeBase", "LeftArm", "LeftForeArm", "LeftHand", "RightArm", "RightForeArm", "RightHand")
_REQUIRED = ("Hips", "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot", "Head")
_MARKER = "hocuspocus_humanoid"
_CACHE: dict = {}
_CACHE_LIMIT = 32
_PATHS = {"translation": 0, "rotation": 1, "scale": 2}


@dataclass
class Body:
    document: dict
    buffers: list
    parents: list
    joints: dict             # joint name -> node index
    facing: int              # +1: the character faces +z of its GLB, -1: -z
    floor: float             # native y of the soles at rest
    box_low: float           # native y of the lowest point of the bind pose
    clips: list              # clip names in file order
    cached: dict = field(default_factory=dict)

    def channels(self, clip: int) -> list:
        animation = (self.document.get("animations") or [])[clip]
        found = []
        for channel in animation.get("channels") or []:
            sampler = animation["samplers"][channel["sampler"]]
            target = channel.get("target") or {}
            if target.get("path") in _PATHS and isinstance(target.get("node"), int):
                kind = sampler.get("interpolation") or "LINEAR"
                values = read_accessor(self.document, sampler["output"], self.buffers)
                found.append((target["node"], target["path"], read_accessor(self.document, sampler["input"], self.buffers),
                              values[1::3] if kind == "CUBICSPLINE" else values, kind))     # a spline's keys sit between its tangents
        return found

    def clip_duration(self, clip: int) -> float:
        return max((float(times[-1]) for _node, _path, times, _values, _kind in self._channels(clip) if len(times)), default=0.0)

    def _channels(self, clip: int) -> list:
        if clip not in self.cached:
            self.cached[clip] = self.channels(clip)
        return self.cached[clip]

    def pose(self, clip: int | None = None, seconds: float = 0.0) -> dict:
        """Joint name -> native [x, y, z] at ``seconds`` of clip ``clip`` (None: the rest pose)."""
        nodes = self.document.get("nodes") or []
        trs = [[node.get("translation") or [0.0, 0.0, 0.0], node.get("rotation") or [0.0, 0.0, 0.0, 1.0], node.get("scale") or [1.0, 1.0, 1.0]]
               for node in nodes]
        if clip is not None:
            for node, path, times, values, kind in self._channels(clip):
                trs[node][_PATHS[path]] = sample_channel(times, values, seconds, "STEP" if kind == "STEP" else "LINEAR", channel=path)
        locals_m = [np.asarray(node["matrix"], dtype=np.float64).reshape((4, 4), order="F") if "matrix" in node else trs_matrix(*trs[index])
                    for index, node in enumerate(nodes)]
        worlds = world_matrices(locals_m, self.parents)
        return {name: worlds[index][:3, 3].copy() for name, index in self.joints.items()}


def body_of(path: Path) -> Body | None:
    """The humanoid of a GLB, or None (cached per file version)."""
    try:
        stat = Path(path).stat()
        key = ("body", str(path), stat.st_mtime_ns, stat.st_size)
        if key not in _CACHE:
            if len(_CACHE) >= _CACHE_LIMIT:
                _CACHE.clear()
            _CACHE[key] = _read(Path(path).read_bytes())
        return _CACHE[key]
    except Exception:  # noqa: BLE001 - a model that cannot be read is not a body
        LOG.debug("body_of failed for %s", path, exc_info=True)
        return None


def _read(data: bytes) -> Body | None:
    document, buffers = split_glb(data)
    nodes = document.get("nodes") or []
    joints = _joints(nodes)
    if any(name not in joints for name in _REQUIRED):
        return None
    marker = ((nodes[joints["Hips"]].get("extras") or {}).get(_MARKER) or {})
    body = Body(document, buffers, _parents(nodes), joints, 1, 0.0, _lowest(document),
                [str(item.get("name") or f"Clip {index + 1}") for index, item in enumerate(document.get("animations") or [])])
    body.facing = int(marker.get("facing")) if marker.get("facing") in (1, -1) else _facing(body.pose())
    body.floor = float(marker["floor"]) if isinstance(marker.get("floor"), (int, float)) else body.box_low
    return body


def _joints(nodes: list) -> dict:
    """Joint name -> node index; ``mixamorig:Hips`` counts as ``Hips``."""
    joints: dict = {}
    for index, node in enumerate(nodes):
        name = str(node.get("name") or "").rsplit(":", 1)[-1]
        if name in JOINTS and name not in joints:
            joints[name] = index
    return joints


def _parents(nodes: list) -> list:
    parents: list = [None] * len(nodes)
    for index, node in enumerate(nodes):
        for child in node.get("children") or []:
            if isinstance(child, int) and 0 <= child < len(nodes):
                parents[child] = index
    return parents


def _lowest(document: dict) -> float:
    """The native y of the bind pose's lowest point (the POSITION boxes under their nodes)."""
    from services.procedural_3d.glb_bounds import _mesh_nodes, _primitive_boxes
    lows = [box[0][1] for _i, _n, _w, mesh in _mesh_nodes(document) for box in _primitive_boxes(document, mesh)]
    return min(lows) if lows else 0.0


def _facing(rest: dict) -> int:
    toes = [rest[name] for name in ("LeftToeBase", "RightToeBase") if name in rest]
    if not toes:
        return 1
    ahead = np.mean([toe[2] for toe in toes]) - np.mean([rest["LeftFoot"][2], rest["RightFoot"][2]])
    return 1 if ahead >= 0 else -1


def measures(rest: dict) -> dict:
    """Leg and arm lengths (native) of a rest pose: thigh, shank, leg, arm."""
    def length(a: str, b: str) -> float:
        return float(np.mean([np.linalg.norm(rest[side + b] - rest[side + a]) for side in ("Left", "Right")]))
    thigh, shank = length("UpLeg", "Leg"), length("Leg", "Foot")
    arm = length("Arm", "ForeArm") + length("ForeArm", "Hand") if "LeftArm" in rest and "LeftHand" in rest else thigh + shank
    return {"thigh": thigh, "shank": shank, "leg": thigh + shank, "arm": arm,
            "forearm": length("ForeArm", "Hand") if "LeftForeArm" in rest and "LeftHand" in rest else 0.5 * arm}


def held_time(slot: dict, body: Body, seconds: float) -> tuple[int | None, float, bool]:
    """``(clip index or None, clip seconds, held)`` the slot shows at scene ``seconds``; ``held`` when that clip's clock has stopped."""
    cues = [cue for cue in slot.get("clips") or [] if isinstance(cue, dict) and isinstance(cue.get("clip"), dict)]
    if cues:
        active = [cue for cue in sorted(cues, key=lambda item: float(item.get("start") or 0)) if float(cue.get("start") or 0) <= seconds]
        return _cue_time(active[-1] if active else cues[0], body, seconds)
    index = _clip_index(slot.get("clip"), body)
    if index is None:
        return None, 0.0, False
    return index, *_single_time(slot, body, index, seconds)


def _single_time(slot: dict, body: Body, index: int, seconds: float) -> tuple[float, bool]:
    """The bound clip's time by ``performanceClipTime``: ``clipPlayback`` start and speed, looping unless ``loop: false``."""
    if slot.get("performance") == "idle":
        return 0.0, False
    playback = slot.get("clipPlayback") if isinstance(slot.get("clipPlayback"), dict) else {}
    length = body.clip_duration(index)
    time = float(playback.get("start") or 0) + max(0.0, seconds) * float(playback.get("speed") or 1)
    if playback.get("loop") is False:
        return min(length, time), time >= length
    return (time % length if length > 0 else 0.0), False


def _cue_time(cue: dict, body: Body, seconds: float) -> tuple[int | None, float, bool]:
    index = _clip_index(cue["clip"], body)
    if index is None:
        return None, 0.0, False
    stop = cue.get("duration")
    elapsed = min(max(0.0, seconds - float(cue.get("start") or 0)), float(stop) if isinstance(stop, (int, float)) else math.inf)
    time = float(cue.get("offset") or 0) + elapsed * float(cue.get("speed") or 1)
    length = body.clip_duration(index)
    if length <= 0:
        return index, time, isinstance(stop, (int, float))
    if cue.get("loop") is False:
        return index, min(time, length), isinstance(stop, (int, float)) or time >= length
    return index, time % length, isinstance(stop, (int, float))


def _clip_index(clip, body: Body) -> int | None:
    if not isinstance(clip, dict) or type(clip.get("index")) is not int:
        return None
    index = clip["index"]
    return index if 0 <= index < len(body.clips) and body.clips[index] == clip.get("name") else None
