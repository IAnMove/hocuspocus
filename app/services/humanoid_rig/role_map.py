"""Map joints to body roles from the hierarchy, not from name similarity.

``Spine`` on the measured reference is upperChest because it sits third
between Hips and Head. The same walk assigns a Mixamo Spine/Spine1/Spine2
chain by order. Names do not select a profile version.
"""

from __future__ import annotations

from services.humanoid_rig.body_roles import (
    AUXILIARY_EXPORT_NODES,
    KNOWN_PROFILES,
    MESHY_SPINE_CHAIN,
    PARENT_ROLE,
    PROFILE_EXTERNAL,
    PROFILE_LEGACY,
    PROFILE_MESHY,
    REQUIRED_RETARGET_ROLES,
    SPINE_TORSO_ROLES,
    normalized_joint_name,
)
from services.humanoid_rig.names import BONE_PARENTS

_LIMB_BY_NAME = {
    "leftshoulder": "leftShoulder",
    "leftarm": "leftUpperArm",
    "leftforearm": "leftLowerArm",
    "lefthand": "leftHand",
    "leftupleg": "leftUpperLeg",
    "leftleg": "leftLowerLeg",
    "leftfoot": "leftFoot",
    "lefttoebase": "leftToes",
    "rightshoulder": "rightShoulder",
    "rightarm": "rightUpperArm",
    "rightforearm": "rightLowerArm",
    "righthand": "rightHand",
    "rightupleg": "rightUpperLeg",
    "rightleg": "rightLowerLeg",
    "rightfoot": "rightFoot",
    "righttoebase": "rightToes",
}

# Present on some sources. They are not required body roles.
_AUXILIARY_NAMES = {
    "head_end": "HeadTop_End",
    "headtop_end": "HeadTop_End",
    "headfront": None,
    "lefttoe_end": "LeftToe_End",
    "righttoe_end": "RightToe_End",
}


def node_parents(nodes: list[dict]) -> list[int | None]:
    """First valid parent wins. A second parent is reported, not overwritten."""
    parents: list[int | None] = [None] * len(nodes)
    claimed: set[int] = set()
    for index, node in enumerate(nodes):
        for child in _child_indexes(node, index, len(nodes)):
            if child in claimed:
                continue
            claimed.add(child)
            parents[child] = index
    return parents


def graph_reasons(nodes: list[dict]) -> list[str]:
    reasons: list[str] = []
    claimed: dict[int, int] = {}
    for index, node in enumerate(nodes):
        children = node.get("children") or []
        if not isinstance(children, list):
            reasons.append(f"invalid_child:{index}")
            continue
        for child in children:
            if isinstance(child, bool) or not isinstance(child, int) or child < 0 or child >= len(nodes) or child == index:
                reasons.append(f"invalid_child:{index}")
                continue
            if child in claimed and claimed[child] != index:
                reasons.append(f"multiple_parents:{child}")
                continue
            claimed[child] = index
    return reasons


def _child_indexes(node: dict, parent_index: int, count: int) -> list[int]:
    children = node.get("children") or []
    if not isinstance(children, list):
        return []
    valid = []
    for child in children:
        if isinstance(child, bool) or not isinstance(child, int):
            continue
        if child < 0 or child >= count or child == parent_index or child in valid:
            continue
        valid.append(child)
    return valid


def has_cycle(parents: list[int | None]) -> bool:
    for start in range(len(parents)):
        seen: set[int] = set()
        node: int | None = start
        while node is not None:
            if node in seen:
                return True
            seen.add(node)
            node = parents[node]
    return False


def is_ancestor(parents: list[int | None], node: int, ancestor: int) -> bool:
    cursor: int | None = parents[node]
    seen: set[int] = set()
    while cursor is not None and cursor not in seen:
        if cursor == ancestor:
            return True
        seen.add(cursor)
        cursor = parents[cursor]
    return False


def map_roles(nodes: list[dict], metadata: dict | None = None) -> dict:
    """Return the role map, profile, and review reasons. Never verifies retarget."""
    parents = node_parents(nodes)
    reasons: list[str] = []
    if has_cycle(parents):
        reasons.append("skeleton_cycle")
    hips = _unique_named(nodes, "hips")
    head = _head_under(nodes, parents, hips)
    if hips is None:
        reasons.append("missing_hips")
    if head is None and hips is not None:
        reasons.append("missing_head")
    chain = _chain(parents, hips, head)
    spine_roles, spine_reasons = _assign_spine(nodes, chain)
    reasons.extend(spine_reasons)
    roles = dict(spine_roles)
    if hips is not None:
        _put(roles, "hips", hips, reasons)
    auxiliaries, limb_reasons = _map_limbs(nodes, parents, set(chain), roles)
    reasons.extend(limb_reasons)
    reasons.extend(graph_reasons(nodes))
    reasons.extend(_semantic_parents(nodes, parents, roles))
    missing = [role for role in REQUIRED_RETARGET_ROLES if role not in roles]
    profile_id, evidence = classify_profile(nodes, parents, chain, roles, metadata)
    return {
        "roles": roles,
        "auxiliaries": auxiliaries,
        "parents": parents,
        "missing_required": missing,
        "reasons": reasons,
        "profile_id": profile_id,
        "profile_evidence": evidence,
        "parent_role": {role: PARENT_ROLE[role] for role in roles},
        "auxiliary_export_optional": list(AUXILIARY_EXPORT_NODES),
    }


def classify_profile(nodes, parents, chain, roles, metadata: dict | None) -> tuple[str, str]:
    """Metadata wins. Otherwise structure. Names alone are not a version."""
    meta = (metadata or {}).get("profile_id")
    if meta in KNOWN_PROFILES:
        return meta, "metadata"
    if _meshy_chain(nodes, chain, roles):
        return PROFILE_MESHY, "hierarchy"
    if _legacy_export(nodes, parents):
        return PROFILE_LEGACY, "export_structure"
    return PROFILE_EXTERNAL, "unversioned"


def _meshy_chain(nodes, chain, roles) -> bool:
    if "leftUpperArm" not in roles or "rightUpperArm" not in roles:
        return False
    names = tuple(nodes[index].get("name") or "" for index in chain[1:])
    return names == MESHY_SPINE_CHAIN


def _legacy_export(nodes, parents) -> bool:
    """v0 is the saved export: full hierarchy, identity rests, hips scale only."""
    indexes = {}
    for index, node in enumerate(nodes):
        name = node.get("name") or ""
        if name in indexes:
            return False
        indexes[name] = index
    if any(name not in indexes for name, _parent in BONE_PARENTS):
        return False
    for name, parent_name in BONE_PARENTS:
        index = indexes[name]
        if not _identity_rotation(nodes[index].get("rotation")):
            return False
        if not _legacy_scale(name, nodes[index].get("scale")):
            return False
        parent = parents[index]
        if parent_name is None:
            if parent is not None and not _armature_wrapper(nodes[parent]):
                return False
            continue
        if parent is None or (nodes[parent].get("name") or "") != parent_name:
            return False
    return True


def _legacy_scale(name: str, scale) -> bool:
    axes = [1.0, 1.0, 1.0] if not scale else [float(value) for value in scale]
    if len(axes) != 3 or any(not _finite(axis) or axis <= 0.0 for axis in axes):
        return False
    if name == "Hips":
        return abs(axes[0] - axes[1]) <= 1e-6 and abs(axes[0] - axes[2]) <= 1e-6 and abs(axes[0] - 1.0) > 1e-6
    return all(abs(axis - 1.0) <= 1e-6 for axis in axes)


def _identity_rotation(rotation) -> bool:
    if not rotation:
        return True
    quat = [float(value) for value in rotation]
    if len(quat) != 4 or any(not _finite(value) for value in quat):
        return False
    return abs(quat[0]) <= 1e-6 and abs(quat[1]) <= 1e-6 and abs(quat[2]) <= 1e-6 and abs(abs(quat[3]) - 1.0) <= 1e-6


def _armature_wrapper(node: dict) -> bool:
    return (node.get("name") or "") in ("Armature", "HocusPocusRoot")


def _finite(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def _semantic_parents(nodes, parents, roles: dict) -> list[str]:
    """Each role must descend from the nearest mapped body parent, same side."""
    role_of = {index: role for role, index in roles.items()}
    reasons = []
    for role, index in roles.items():
        expected = _nearest_mapped_parent(role, roles)
        if expected is None:
            continue
        ancestor = roles[expected]
        if is_ancestor(parents, index, ancestor):
            continue
        observed = _observed_parent(nodes, parents, index, role_of)
        reasons.append(f"semantic_parent:{role}:expected={expected}:observed={observed}")
    return reasons


def _nearest_mapped_parent(role: str, roles: dict) -> str | None:
    cursor = PARENT_ROLE.get(role)
    seen: set[str] = set()
    while cursor and cursor not in seen:
        if cursor in roles:
            return cursor
        seen.add(cursor)
        cursor = PARENT_ROLE.get(cursor)
    return None


def _observed_parent(nodes, parents, index: int, role_of: dict) -> str:
    parent = parents[index]
    if parent is None:
        return "root"
    if parent in role_of:
        return role_of[parent]
    return nodes[parent].get("name") or "unmapped"


def _assign_spine(nodes, chain) -> tuple[dict, list[str]]:
    """Fill spine, chest, upperChest from the hips side, then neck and head."""
    if len(chain) < 2:
        return {}, []
    roles: dict[str, int] = {}
    reasons: list[str] = []
    body = list(chain[1:-1])
    _put(roles, "head", chain[-1], reasons)
    if body and _is_neck(nodes[body[-1]]):
        _put(roles, "neck", body[-1], reasons)
        body = body[:-1]
    for role, index in zip(SPINE_TORSO_ROLES, body):
        _put(roles, role, index, reasons)
    if len(body) > len(SPINE_TORSO_ROLES):
        reasons.append("extra_spine_nodes")
    return roles, reasons


def _map_limbs(nodes, parents, spine_ids: set[int], roles: dict) -> tuple[dict, list[str]]:
    auxiliaries: dict[str, dict] = {}
    reasons: list[str] = []
    for index, node in enumerate(nodes):
        if index in spine_ids:
            continue
        key = normalized_joint_name(node.get("name") or "")
        if key in _AUXILIARY_NAMES:
            auxiliaries[node.get("name") or key] = {
                "node_index": index,
                "export_name": _AUXILIARY_NAMES[key],
                "required": False,
            }
            continue
        role = _LIMB_BY_NAME.get(key)
        if role is None:
            continue
        _put(roles, role, index, reasons)
        parent = parents[index]
        if parent is not None and not is_ancestor(parents, index, parent):
            reasons.append(f"parent_not_ancestor:{role}")
    return auxiliaries, reasons


def _put(roles: dict, role: str, index: int, reasons: list[str]) -> None:
    previous = roles.get(role)
    if previous is not None and previous != index:
        reasons.append(f"duplicate_role:{role}")
        return
    roles[role] = index


def _unique_named(nodes, key: str) -> int | None:
    found = [index for index, node in enumerate(nodes) if normalized_joint_name(node.get("name") or "") == key]
    if len(found) != 1:
        return None
    return found[0]


def _head_under(nodes, parents, hips: int | None) -> int | None:
    if hips is None:
        return None
    found = []
    for index, node in enumerate(nodes):
        if normalized_joint_name(node.get("name") or "") != "head":
            continue
        if index == hips or is_ancestor(parents, index, hips):
            found.append(index)
    if len(found) != 1:
        return None
    return found[0]


def _chain(parents, hips: int | None, head: int | None) -> list[int]:
    if hips is None or head is None:
        return []
    chain = []
    node: int | None = head
    seen: set[int] = set()
    while node is not None and node not in seen:
        chain.append(node)
        if node == hips:
            chain.reverse()
            return chain
        seen.add(node)
        node = parents[node]
    return []


def _is_neck(node: dict) -> bool:
    return normalized_joint_name(node.get("name") or "") == "neck"
