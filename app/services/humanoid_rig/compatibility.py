"""Compatibility descriptor. Parsing a rig does not verify a retarget.

``status`` is ``mapped`` or ``needs_review`` (or ``native_playback`` when the
source can play but the body map is incomplete). ``retarget_verified`` stays
false until a caller records destination evidence.
"""

from __future__ import annotations

import numpy as np

from services.humanoid_rig.body_roles import (
    CONTRACT_ID,
    CONTRACT_VERSION,
    LEGACY_CLIP_COUNT,
    PROFILE_EXTERNAL,
    PROFILE_LEGACY,
    PROFILE_MESHY,
    PROFILE_V1,
    STATUS_MAPPED,
    STATUS_NATIVE,
    STATUS_REVIEW,
    STATUS_UNSUPPORTED,
    STATUS_VERIFIED,
    V1_ROOT_NAME,
)
from services.humanoid_rig.clip_inventory import default_motion_index, list_clips
from services.humanoid_rig.gltf_accessors import position_y_bounds, required_extension_issues
from services.humanoid_rig.pose_math import (
    IDENTITY_QUAT,
    in_place_translations,
    local_from_parent,
    preserve_translations,
    resolve_height,
    target_world_quat,
)
from services.humanoid_rig.role_map import map_roles

_REVIEW_PREFIXES = (
    "unsupported_transform",
    "duplicate_role",
    "extra_spine",
    "variable_scale",
)


def describe(document: dict, buffers: list[bytes] | None = None, *, asset_hash: str | None = None, metadata: dict | None = None) -> dict:
    nodes = list(document.get("nodes") or [])
    mapped = map_roles(nodes, metadata)
    extension_reasons = required_extension_issues(document)
    transform_reasons = _transform_reasons(nodes)
    reasons = [*mapped["reasons"], *extension_reasons, *transform_reasons]
    clips = list_clips(document, buffers)
    bounds = position_y_bounds(document)
    low, high = (None, None) if bounds is None else bounds
    height = resolve_height(
        position_min_y=low,
        position_max_y=high,
        node_translation_span=_node_span(nodes),
        wrapper_scale=_wrapper_scale(nodes),
    )
    status, retarget_status = _statuses(document, mapped, reasons)
    return {
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "asset_hash": asset_hash,
        "profile_id": mapped["profile_id"],
        "profile_evidence": mapped["profile_evidence"],
        "status": status,
        "retarget_status": retarget_status,
        "retarget_verified": False,
        "native_playback": _native_ok(document, reasons),
        "roles": _role_view(nodes, mapped["roles"]),
        "missing_required": list(mapped["missing_required"]),
        "reasons": reasons,
        "auxiliaries": mapped["auxiliaries"],
        "clips": clips,
        "default_motion_index": default_motion_index(clips),
        "preservation": preservation_plan(mapped["profile_id"]),
        **height,
    }


def preservation_plan(profile_id: str) -> dict:
    """What the later importer is allowed to do. External skins stay intact."""
    if profile_id in (PROFILE_EXTERNAL, PROFILE_MESHY):
        return {
            "rewrite_skin": False,
            "discard_animations": False,
            "reorder_joints": False,
            "clear_previous_skin": False,
        }
    if profile_id == PROFILE_LEGACY:
        return {
            "silent_migration": False,
            "keep_hips_scale": True,
            "legacy_clip_count": LEGACY_CLIP_COUNT,
        }
    if profile_id == PROFILE_V1:
        return {
            "hips_normalization_scale": 1,
            "non_deforming_root": V1_ROOT_NAME,
            "clear_previous_skin_on_source": False,
        }
    return {"clear_previous_skin": False}


def retarget_world(source_world: dict, source_ref: dict, target_ref: dict) -> dict:
    """World quaternion per role. Source-at-reference yields target-at-reference."""
    return {
        role: target_world_quat(source_world[role], source_ref[role], target_ref[role])
        for role in source_world
    }


def retarget_locals(worlds: dict, parent_of: dict) -> dict:
    locals_out = {}
    for role, world in worlds.items():
        parent = parent_of.get(role)
        parent_world = IDENTITY_QUAT if parent is None else worlds[parent]
        locals_out[role] = local_from_parent(parent_world, world)
    return locals_out


def retarget_root(samples, source_m: float, target_m: float, policy: str = "in_place"):
    """Default root policy on this path is in_place."""
    if policy == "preserve":
        return preserve_translations(samples, source_m, target_m)
    if policy == "in_place":
        return in_place_translations(samples, source_m, target_m)
    raise ValueError("unknown_root_policy")


def record_verification(descriptor: dict, evidence: dict) -> dict:
    """Set retarget_verified only when destination evidence says the checks passed.

    A finished parse is not evidence. The copied descriptor is what changes.
    """
    updated = dict(descriptor)
    ready = bool(evidence.get("destination_id")) and bool(evidence.get("neutral_passed"))
    ready = ready and bool(evidence.get("axis_passed"))
    updated["retarget_verified"] = ready
    updated["status"] = STATUS_VERIFIED if ready else descriptor.get("status")
    updated["verification"] = {
        "destination_id": evidence.get("destination_id"),
        "neutral_passed": bool(evidence.get("neutral_passed")),
        "axis_passed": bool(evidence.get("axis_passed")),
    }
    return updated


def weight_issues(joints, weights, joint_count: int) -> list[str]:
    """Report bad influences. A source with more than four is not truncated here."""
    values = np.asarray(weights, dtype=np.float64)
    indexes = np.asarray(joints)
    issues = []
    if values.size and not np.isfinite(values).all():
        issues.append("non_finite_weight")
    if values.size and (values < -1e-8).any():
        issues.append("negative_weight")
    if indexes.size and (indexes.min() < 0 or indexes.max() >= joint_count):
        issues.append("joint_index_outside_skin")
    if values.ndim == 2 and values.shape[0]:
        drift = float(np.max(np.abs(values.sum(axis=1) - 1.0)))
        if drift > 1e-4:
            issues.append("weight_sum")
    return issues


def _role_view(nodes, roles: dict) -> dict:
    return {
        role: {"node_index": index, "name": nodes[index].get("name") or ""}
        for role, index in roles.items()
    }


def _statuses(document, mapped, reasons) -> tuple[str, str]:
    if "skeleton_cycle" in reasons:
        return STATUS_UNSUPPORTED, STATUS_UNSUPPORTED
    if any(reason.startswith("unsupported_extension") for reason in reasons):
        return STATUS_UNSUPPORTED, STATUS_UNSUPPORTED
    if mapped["missing_required"] or _blocked(reasons):
        retarget = STATUS_REVIEW
        if _native_ok(document, reasons):
            return STATUS_NATIVE, retarget
        return STATUS_REVIEW, retarget
    return STATUS_MAPPED, STATUS_MAPPED


def _blocked(reasons: list[str]) -> bool:
    return any(reason.startswith(_REVIEW_PREFIXES) for reason in reasons)


def _native_ok(document, reasons) -> bool:
    if "skeleton_cycle" in reasons:
        return False
    if any(reason.startswith("unsupported_extension") for reason in reasons):
        return False
    skins = document.get("skins") or []
    return bool(skins)


def _transform_reasons(nodes: list[dict]) -> list[str]:
    reasons = []
    for index, node in enumerate(nodes):
        if "matrix" in node and _matrix_problem(node["matrix"]):
            reasons.append(f"unsupported_transform:{index}")
        elif _scale_problem(node.get("scale")):
            reasons.append(f"unsupported_transform:{index}")
    return reasons


def _matrix_problem(values) -> bool:
    linear = np.asarray(values, dtype=np.float64).reshape(4, 4)[:3, :3]
    columns = [linear[:, axis] for axis in range(3)]
    norms = [float(np.linalg.norm(column)) for column in columns]
    if any(norm < 1e-8 for norm in norms):
        return True
    for left, right in ((0, 1), (0, 2), (1, 2)):
        coupled = abs(float(np.dot(columns[left], columns[right])))
        if coupled > 1e-3 * norms[left] * norms[right]:
            return True
    if float(np.linalg.det(linear)) < 0.0:
        return True
    return max(norms) - min(norms) > 1e-4


def _scale_problem(scale) -> bool:
    if not scale:
        return False
    axes = [float(value) for value in scale]
    if any(axis < 0.0 for axis in axes):
        return True
    return max(axes) - min(axes) > 1e-4


def _wrapper_scale(nodes: list[dict]):
    for node in nodes:
        if (node.get("name") or "") != "Armature":
            continue
        scale = node.get("scale")
        if scale:
            return scale
    return None


def _node_span(nodes: list[dict]) -> float | None:
    ys = []
    for node in nodes:
        translation = node.get("translation")
        if translation and len(translation) >= 2:
            ys.append(float(translation[1]))
    if len(ys) < 2:
        return None
    return max(ys) - min(ys)
