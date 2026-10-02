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
    parents: list[int | None] = [None] * len(nodes)
    for index, node in enumerate(nodes):
        for child in node.get("children") or []:
            if isinstance(child, int) and 0 <= child < len(nodes):
                parents[child] = index
    return parents


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
    if _legacy_hips_scale(nodes, roles):
        return PROFILE_LEGACY, "hips_scale"
    return PROFILE_EXTERNAL, "unversioned"


def _meshy_chain(nodes, chain, roles) -> bool:
    if "leftUpperArm" not in roles or "rightUpperArm" not in roles:
        return False
    names = tuple(nodes[index].get("name") or "" for index in chain[1:])
    return names == MESHY_SPINE_CHAIN


def _legacy_hips_scale(nodes, roles) -> bool:
    hips = roles.get("hips")
    if hips is None:
        return False
    scale = nodes[hips].get("scale") or [1.0, 1.0, 1.0]
    return any(abs(float(axis) - 1.0) > 1e-6 for axis in scale)


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
