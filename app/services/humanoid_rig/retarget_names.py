"""Map the joints of an imported animation onto the standard humanoid bones.

Names are split into words (``mixamorig:LeftUpLeg``, ``upperarm_l``,
``J_Bip_L_UpperArm``, ``lShldr``, ``thigh.L``) and matched by side and part,
so Mixamo, VRM/VRoid, Unreal, Blender metarigs, Daz and CMU BVH all map. The
spine is read from the hierarchy between the hips and the neck, not from
names, because rigs disagree on what ``Spine`` means.
"""

from __future__ import annotations

import re

from services.humanoid_rig.errors import InvalidInput

_LIMBS = {
    "shoulder": "Shoulder", "clavicle": "Shoulder", "collar": "Shoulder",
    "arm": "Arm", "upperarm": "Arm", "uparm": "Arm", "shldr": "Arm",
    "forearm": "ForeArm", "lowerarm": "ForeArm", "elbow": "ForeArm",
    "hand": "Hand", "wrist": "Hand",
    "upleg": "UpLeg", "upperleg": "UpLeg", "thigh": "UpLeg", "femur": "UpLeg",
    "leg": "Leg", "lowerleg": "Leg", "shin": "Leg", "calf": "Leg", "knee": "Leg",
    "foot": "Foot", "ankle": "Foot",
    "toebase": "ToeBase", "toe": "ToeBase", "toes": "ToeBase", "ball": "ToeBase",
}
_CENTER = {"hips": "Hips", "hip": "Hips", "pelvis": "Hips", "head": "Head", "neck": "Neck", "neck01": "Neck", "neck1": "Neck",
           "necklower": "Neck"}
# Rig prefixes (``Bip01``, ``Character1_``, ``Armature|``) and Daz's ``Bend`` suffix say nothing about the part.
_NOISE = {"j", "bip", "bip01", "def", "mch", "org", "jnt", "mixamorig", "c", "cc", "base", "character", "armature", "bend"}
_LEFT, _RIGHT = {"l", "left"}, {"r", "right"}
_SPINE = ("Spine", "Spine1", "Spine2")
_SPINE_NAMES = {"spine": "Spine", "lowerback": "Spine", "abdomen": "Spine", "spine1": "Spine1", "chest": "Spine1",
                "spine2": "Spine2", "upperchest": "Spine2"}


def words(name: str) -> list[str]:
    """Lowercase words of a joint name, without namespace or rig prefixes."""
    bare = re.split(r"[:|]", name)[-1]
    found = []
    for chunk in re.split(r"[\s_.\-]+", bare):
        found += re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", chunk)
    kept, after_noise = [], True
    for item in (token.lower() for token in found):
        if item in _NOISE or (item.isdigit() and after_noise):
            after_noise = True  # the number of a prefix, as in Bip01 or Character1
            continue
        kept.append(item)
        after_noise = False
    return kept


def bone_for(name: str) -> str | None:
    """Standard bone for one joint name, or None."""
    parts = words(name)
    side = "Left" if any(item in _LEFT for item in parts) else "Right" if any(item in _RIGHT for item in parts) else None
    core = "".join(item for item in parts if item not in _LEFT and item not in _RIGHT)
    if side:
        limb = _LIMBS.get(core) or _LIMBS.get(re.sub(r"\d+$", "", core))  # Bip01 L Toe0
        return f"{side}{limb}" if limb else None
    return _CENTER.get(core)


def map_source_bones(names: list[str], parents: list[int | None]) -> tuple[dict, list[str]]:
    """``({bone: node index}, warnings)``. Raises ``ValueError`` when no humanoid is found."""
    mapping = _by_name(names, parents)
    _fallback_hips(mapping, parents)
    if not _spine_chain(mapping, parents):
        _spine_by_name(mapping, names, parents)
    _require(mapping)
    return mapping, _mapping_warnings(mapping, names, parents)


def _by_name(names: list[str], parents: list[int | None]) -> dict[str, int]:
    """Limbs, hips, neck and head by name; the shallowest joint wins a duplicate."""
    mapping: dict[str, int] = {}
    for index, name in enumerate(names):
        bone = bone_for(name)
        if not bone or bone in _SPINE:
            continue
        if bone not in mapping or _depth(parents, index) < _depth(parents, mapping[bone]):
            mapping[bone] = index
    return mapping


def _mapping_warnings(mapping: dict, names: list[str], parents: list[int | None]) -> list[str]:
    used = set(mapping.values())
    skipped = sum(1 for index, name in enumerate(names)
                  if name and index not in used and not _is_tip(name) and _under(parents, index, mapping["Hips"]))
    warnings = [f"{skipped} joints were not used (fingers, props or extra bones)"] if skipped else []
    missing = [bone for bone in ("LeftShoulder", "RightShoulder", "Neck", "LeftToeBase", "RightToeBase") if bone not in mapping]
    if missing:
        warnings.append("not in the file, kept at rest: " + ", ".join(missing))
    return warnings


def _is_tip(name: str) -> bool:
    """End markers such as HeadTop_End or a BVH nub carry no motion."""
    return bool({"end", "nub", "site", "tip"} & set(words(name)))


def _depth(parents: list[int | None], index: int) -> int:
    depth, seen = 0, set()
    while parents[index] is not None and index not in seen:
        seen.add(index)
        index = parents[index]
        depth += 1
    return depth


def _ancestors(parents: list[int | None], index: int) -> list[int]:
    chain, seen = [], set()
    while index is not None and index not in seen:
        seen.add(index)
        chain.append(index)
        index = parents[index]
    return chain


def _under(parents: list[int | None], index: int, root: int) -> bool:
    return root in _ancestors(parents, index)


def _fallback_hips(mapping: dict, parents: list[int | None]) -> None:
    """No hips by name: the closest common ancestor of both thighs."""
    if "Hips" in mapping or "LeftUpLeg" not in mapping or "RightUpLeg" not in mapping:
        return
    right = set(_ancestors(parents, mapping["RightUpLeg"]))
    for index in _ancestors(parents, mapping["LeftUpLeg"])[1:]:
        if index in right:
            mapping["Hips"] = index
            return


def _spine_chain(mapping: dict, parents: list[int | None]) -> bool:
    """Spine bones in order between the hips and the neck (or head)."""
    top = mapping.get("Neck", mapping.get("Head"))
    if "Hips" not in mapping or top is None:
        return False
    path = _ancestors(parents, top)
    if mapping["Hips"] not in path:
        return False
    between = list(reversed(path[1:path.index(mapping["Hips"])]))
    if "Neck" not in mapping and between:
        mapping["Neck"] = between.pop()
    if len(between) > 3:
        between = [between[0], between[len(between) // 2], between[-1]]
    for bone, index in zip(_SPINE if len(between) != 2 else ("Spine", "Spine2"), between):
        mapping[bone] = index
    return True


def _spine_by_name(mapping: dict, names: list[str], parents: list[int | None]) -> None:
    """Without a neck or head, take spine bones by name under the hips."""
    for index, name in enumerate(names):
        bone = _SPINE_NAMES.get("".join(words(name)))
        if bone and bone not in mapping and ("Hips" not in mapping or _under(parents, index, mapping["Hips"])):
            mapping[bone] = index


def _require(mapping: dict) -> None:
    legs = "LeftUpLeg" in mapping and "RightUpLeg" in mapping
    arms = "LeftArm" in mapping and "RightArm" in mapping
    if "Hips" not in mapping or not (legs or arms) or not ({"Head", "Neck", "Spine"} & set(mapping)):
        raise InvalidInput("no humanoid skeleton found in the animation: it needs hips, a spine or head, and both legs or arms")
