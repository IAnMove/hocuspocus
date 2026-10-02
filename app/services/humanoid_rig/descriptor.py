"""Persist a rig descriptor beside an asset.

The file is ``{asset_path}.rig-descriptor.json``. It stores the describe()
payload plus identity fields. A saved file is not native playback and is not
a retarget certificate.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path

from services.humanoid_rig.body_roles import (
    PARENT_ROLE,
    STATUS_MAPPED,
    STATUS_REVIEW,
    STATUS_UNSUPPORTED,
    STATUS_VERIFIED,
    normalized_joint_name,
)
from services.humanoid_rig.compatibility import describe
from services.humanoid_rig.role_map import _semantic_parents, node_parents

# Bump when role assignment or cache identity changes meaning.
ALGORITHM_VERSION = "1"
RIG_DESCRIPTOR_SUFFIX = ".rig-descriptor.json"


def rig_descriptor_path(asset_path: str | os.PathLike) -> Path:
    """Sidecar path. The asset suffix is kept; this is not ``.humanoid.json``."""
    return Path(f"{asset_path}{RIG_DESCRIPTOR_SUFFIX}")


def build_descriptor(document: dict, buffers: list[bytes] | None = None, *, asset_hash: str | None = None, metadata: dict | None = None, skin_index: int | None = None, options: dict | None = None, reference_pose: str | None = None, clip_selection: int | None = None, destination_id: str | None = None) -> dict:
    """describe() payload plus skin, parents, options, and algorithm version."""
    described = describe(document, buffers, asset_hash=asset_hash, metadata=metadata)
    nodes = list(document.get("nodes") or [])
    payload = copy.deepcopy(described)
    payload.update(_identity_fields(
        document, nodes, described, skin_index, options, reference_pose, clip_selection, destination_id,
    ))
    return payload


def save_descriptor(descriptor: dict, asset_path: str | os.PathLike) -> Path:
    """Atomically replace ``{asset_path}.rig-descriptor.json``."""
    path = rig_descriptor_path(asset_path)
    directory = path.parent
    if not directory.exists():
        raise FileNotFoundError(str(directory))
    temporary = directory / f".{path.name}.{uuid.uuid4().hex}.tmp"
    _replace_json(temporary, path, descriptor)
    return path


def load_descriptor(asset_path: str | os.PathLike) -> dict:
    """Return the stored file. Stale identity is not rejected here."""
    path = rig_descriptor_path(asset_path)
    with path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("rig_descriptor_not_object")
    return loaded


def apply_role_overrides(descriptor: dict, nodes: list[dict], overrides) -> dict:
    """Assign roles to node indexes. A bad map stays in needs_review.

    Duplicate names are not identity. The node index is the assignment.
    """
    updated = copy.deepcopy(descriptor)
    state = _override_state(updated, nodes)
    for role, index in _assignment_rows(overrides):
        _apply_one(state, nodes, role, index)
    _finish_overrides(updated, state, descriptor, nodes)
    return updated


def assign_destination(descriptor: dict, destination_id: str) -> dict:
    return _assign_value(descriptor, "destination_id", destination_id)


def assign_reference_pose(descriptor: dict, reference: str) -> dict:
    return _assign_value(descriptor, "reference_pose", reference)


def assign_clip_selection(descriptor: dict, clip_index: int) -> dict:
    return _assign_value(descriptor, "clip_selection", clip_index)


def assign_options(descriptor: dict, options: dict) -> dict:
    return _assign_value(descriptor, "options", canonical_options(options))


def cache_identity(descriptor: dict) -> dict:
    """Asset hash, skin, contract, algorithm, and canonical options.

    Profile id and destination id are not part of this identity.
    """
    return {
        "asset_hash": descriptor.get("asset_hash"),
        "skin_index": descriptor.get("skin_index"),
        "contract_version": descriptor.get("contract_version"),
        "algorithm_version": descriptor.get("algorithm_version"),
        "options": canonical_options(descriptor.get("options")),
    }


def analysis_reusable(stored: dict, current: dict) -> bool:
    """False when the stored analysis must not be reused.

    A different asset hash or profile id is stale even if the file loaded.
    """
    if not isinstance(stored, dict) or not isinstance(current, dict):
        return False
    if stored.get("profile_id") != current.get("profile_id"):
        return False
    return cache_identity(stored) == cache_identity(current)


def verification_applies(descriptor: dict, destination_id: str) -> bool:
    """A certificate for destination A is not evidence for destination B."""
    if descriptor.get("retarget_verified") is not True:
        return False
    verification = descriptor.get("verification")
    if not isinstance(verification, dict):
        return False
    if verification.get("destination_id") != destination_id:
        return False
    selected = descriptor.get("destination_id")
    if isinstance(selected, str) and selected != destination_id:
        return False
    return True


def canonical_options(options) -> dict:
    if not isinstance(options, dict):
        return {}
    return _canonical_mapping(options)


def _identity_fields(document, nodes, described, skin_index, options, reference_pose, clip_selection, destination_id) -> dict:
    reasons = list(described.get("reasons") or [])
    return {
        "skin_index": _selected_skin(document, skin_index),
        "parent_indexes": node_parents(nodes),
        "role_nodes": _indexes_from_roles(described.get("roles") or {}),
        "options": canonical_options(options),
        "algorithm_version": ALGORITHM_VERSION,
        "role_overrides": {},
        "reference_pose": reference_pose,
        "clip_selection": clip_selection,
        "destination_id": destination_id,
        "structured_reasons": [_structure_reason(reason) for reason in reasons],
        "verification": None,
        "native_playback": False,
        "retarget_verified": False,
    }


def _selected_skin(document: dict, selected) -> int | None:
    skins = document.get("skins") or []
    count = len(skins) if isinstance(skins, list) else 0
    if _valid_skin(selected, count):
        return selected
    if selected is None and count:
        return 0
    return None


def _valid_skin(selected, count: int) -> bool:
    if isinstance(selected, bool) or not isinstance(selected, int):
        return False
    return 0 <= selected < count


def _override_state(descriptor: dict, nodes: list[dict]) -> dict:
    roles = _role_indexes(descriptor)
    return {
        "roles": roles,
        "parents": _parents_for(descriptor, nodes),
        "reasons": list(descriptor.get("reasons") or []),
        "structured": list(descriptor.get("structured_reasons") or []),
        "claimed": _claimed(roles),
        "seen": {},
        "applied": dict(descriptor.get("role_overrides") or {}),
        "blocked": False,
    }


def _apply_one(state: dict, nodes: list[dict], role, index) -> None:
    text = _validate_assignment(role, index, nodes, state["claimed"], state["seen"])
    if text:
        _block(state, text)
        return
    _bind_role(state["roles"], state["claimed"], state["seen"], state["applied"], role, index)
    side = _crossed_side(role, index, nodes)
    if side:
        _block(state, side)


def _finish_overrides(updated: dict, state: dict, original: dict, nodes: list[dict]) -> None:
    for text in _semantic_parents(nodes, state["parents"], state["roles"]):
        if text not in state["reasons"]:
            _block(state, text)
    _write_roles(updated, nodes, state["roles"])
    updated["role_overrides"] = state["applied"]
    updated["reasons"] = state["reasons"]
    updated["structured_reasons"] = state["structured"]
    updated["parent_indexes"] = state["parents"]
    changed = state["applied"] != (original.get("role_overrides") or {})
    if state["blocked"] or changed:
        _mark_override(updated, state["blocked"])


def _validate_assignment(role, index, nodes, claimed, seen) -> str | None:
    unknown = _unknown_text(role)
    if unknown:
        return unknown
    invalid = _index_text(role, index, len(nodes))
    if invalid:
        return invalid
    return _duplicate_text(role, index, claimed, seen)


def _unknown_text(role) -> str | None:
    if isinstance(role, str) and role in PARENT_ROLE:
        return None
    label = role if isinstance(role, str) and role else "invalid"
    return f"unknown_role:{label}"


def _index_text(role: str, index, count: int) -> str | None:
    if isinstance(index, bool) or not isinstance(index, int):
        return f"invalid_override:{role}"
    if index < 0 or index >= count:
        return f"invalid_override:{role}"
    return None


def _duplicate_text(role, index, claimed, seen) -> str | None:
    previous = seen.get(role)
    if previous is not None and previous != index:
        return f"duplicate_role:{role}"
    owner = claimed.get(index)
    if owner is not None and owner != role:
        return f"duplicate_role:{role}"
    return None


def _bind_role(roles, claimed, seen, applied, role, index) -> None:
    old = roles.get(role)
    if old is not None and claimed.get(old) == role and old != index:
        claimed.pop(old, None)
    roles[role] = index
    claimed[index] = role
    seen[role] = index
    applied[role] = index


def _block(state: dict, text: str) -> None:
    state["blocked"] = True
    _remember(state["reasons"], state["structured"], text)


def _crossed_side(role: str, index: int, nodes: list[dict]) -> str | None:
    """A left role cannot use a node whose name is only the other side."""
    role_side = _role_side(role)
    name_side = _name_side(nodes[index].get("name") or "")
    if role_side and name_side and role_side != name_side:
        return f"crossed_side:role={role}:node_index={index}:name_side={name_side}"
    return None


def _role_side(role: str) -> str | None:
    if role.startswith("left"):
        return "left"
    if role.startswith("right"):
        return "right"
    return None


def _name_side(name: str) -> str | None:
    key = normalized_joint_name(name)
    left = "left" in key
    right = "right" in key
    if left and not right:
        return "left"
    if right and not left:
        return "right"
    return None


def _remember(reasons: list, structured: list, text: str) -> None:
    if text not in reasons:
        reasons.append(text)
    item = _structure_reason(text)
    if item not in structured:
        structured.append(item)


def _structure_reason(text: str) -> dict:
    rendered = str(text)
    code, _separator, _detail = rendered.partition(":")
    return {"code": code, "detail": rendered}


def _write_roles(descriptor: dict, nodes: list[dict], roles: dict) -> None:
    view = {}
    indexes = {}
    for role, index in roles.items():
        view[role] = {"node_index": index, "name": _node_name(nodes, index)}
        indexes[role] = index
    descriptor["roles"] = view
    descriptor["role_nodes"] = indexes


def _node_name(nodes: list[dict], index) -> str:
    if isinstance(index, bool) or not isinstance(index, int):
        return ""
    if index < 0 or index >= len(nodes):
        return ""
    return nodes[index].get("name") or ""


def _role_indexes(descriptor: dict) -> dict:
    stored = descriptor.get("role_nodes")
    if isinstance(stored, dict):
        return _plain_indexes(stored)
    return _indexes_from_roles(descriptor.get("roles") or {})


def _plain_indexes(stored: dict) -> dict:
    found = {}
    for role, index in stored.items():
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        found[role] = index
    return found


def _indexes_from_roles(roles: dict) -> dict:
    found = {}
    for role, info in roles.items():
        index = info.get("node_index") if isinstance(info, dict) else None
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        found[role] = index
    return found


def _parents_for(descriptor: dict, nodes: list[dict]) -> list:
    stored = descriptor.get("parent_indexes")
    if isinstance(stored, list) and len(stored) == len(nodes):
        return [None if item is None else int(item) for item in stored]
    return node_parents(nodes)


def _claimed(roles: dict) -> dict:
    return {index: role for role, index in roles.items()}


def _assignment_rows(overrides) -> list[tuple]:
    if isinstance(overrides, dict):
        return list(overrides.items())
    rows = []
    for item in overrides or []:
        rows.append(_assignment_item(item))
    return rows


def _assignment_item(item) -> tuple:
    if isinstance(item, dict):
        return item.get("role"), item.get("node_index")
    return item[0], item[1]


def _assign_value(descriptor: dict, field: str, value) -> dict:
    updated = copy.deepcopy(descriptor)
    if updated.get(field) == value:
        return updated
    updated[field] = value
    return _clear_verification(updated)


def _mark_override(descriptor: dict, blocked: bool) -> None:
    _clear_verification(descriptor)
    if not blocked:
        return
    if descriptor.get("status") == STATUS_UNSUPPORTED:
        descriptor["retarget_status"] = STATUS_UNSUPPORTED
        return
    descriptor["status"] = STATUS_REVIEW
    descriptor["retarget_status"] = STATUS_REVIEW


def _clear_verification(descriptor: dict) -> dict:
    descriptor["retarget_verified"] = False
    descriptor["verification"] = None
    if descriptor.get("status") == STATUS_VERIFIED:
        descriptor["status"] = _mapped_fallback(descriptor)
    return descriptor


def _mapped_fallback(descriptor: dict) -> str:
    status = descriptor.get("retarget_status")
    if status in (STATUS_MAPPED, STATUS_REVIEW, STATUS_UNSUPPORTED):
        return status
    return STATUS_MAPPED


def _replace_json(temporary: Path, path: Path, descriptor: dict) -> None:
    payload = json.dumps(descriptor, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    try:
        _write_text(temporary, payload + "\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_text(path: Path, payload: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _canonical_mapping(mapping: dict) -> dict:
    ordered = sorted(mapping, key=str)
    return {str(key): _canonical_value(mapping[key]) for key in ordered}


def _canonical_value(value):
    if isinstance(value, dict):
        return _canonical_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, str)):
        return value
    return str(value)
