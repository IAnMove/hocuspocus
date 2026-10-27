"""Save one round-headed body and rig it on CPU. No routers and no HTTP.

The rig is the same synchronous function the humanoid worker uses. The reply
is the finished GLB, so callers do not poll ``model3d.rig.status``.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from urllib.parse import urlencode

from services.agent_activity import trusted_tool as agent_trusted_tool
from services.asset_manifest import publish_generation_sidecar
from services.blob_builder import PRESETS, BlobTraitsError, _copy, blob_pieces
from services.humanoid_rig.errors import NotHumanoid
from services.humanoid_rig.names import CLIP_IDS
from services.humanoid_rig.rig import rig_humanoid
from services.procedural_3d.compose import compose_glb

MAKE = "model3d.blob.make"
PRESETS_OP = "model3d.blob.presets"
DEFAULT_CLIPS = ("idle", "walk", "talk", "nod", "wave", "shrug", "point", "run")
_INPUT_FIELDS = {"workspace", "name", "traits", "preset", "clips"}
_NESTED = ("colors", "head", "arms", "legs", "hair")
_CLIP_KEYS = ("index", "id", "name", "duration", "loop")


class BlobRigError(Exception):
    """The mesh is not a person. ``reason`` is the rig's own motive, such as ``hands_stuck``."""

    code = "not_humanoid"

    def __init__(self, reason: str) -> None:
        self.reason = str(reason)
        super().__init__(f"not_humanoid: {self.reason}")


def resolve_request(payload: dict) -> tuple[dict, list[str]]:
    """Preset traits overridden by ``traits``, plus the clip ids to bake."""
    if not isinstance(payload, dict):
        raise BlobTraitsError("invalid_traits", "input must be an object")
    extra = set(payload) - _INPUT_FIELDS
    if extra:
        raise BlobTraitsError("unknown_field", "Unknown field: " + ", ".join(sorted(extra)))
    base = _preset(payload.get("preset"))
    traits = payload.get("traits")
    merged = _overlay(base, {} if traits is None else traits)
    return merged, _clips(payload.get("clips"))


def rig_glb(source: bytes, clip_ids: list[str]) -> tuple[bytes, dict]:
    """Rig bytes on CPU. A refusal keeps the rig's reason."""
    try:
        return rig_humanoid(source, list(clip_ids))
    except NotHumanoid as exc:
        raise BlobRigError(exc.reason) from exc


def build_body(traits: dict, clip_ids: list[str], face_fit=None) -> dict:
    """Pieces, both GLBs and the humanoid sidecar. Nothing is written. ``face_fit`` is the face picture's skull box for a loft."""
    built = blob_pieces(traits)
    if built["traits"].get("mesh") == "blocky":
        from services.blob_blocky import blocky_glb
        built.pop("layout", None)
        glb = blocky_glb(built["traits"], "blob")
    elif built["traits"].get("mesh") == "loft":
        from services.blob_loft import loft_glb
        glb = loft_glb(built["traits"], built.pop("layout"), "blob", fit=face_fit)
    else:
        glb = compose_glb(built["pieces"], "blob")
    rigged, sidecar = rig_glb(glb, clip_ids)
    return {**built, "glb": glb, "rigged": rigged, "sidecar": sidecar}


def write_body(folder: Path, workspace: str, name: str, intent: str, body: dict) -> dict:
    """Write the plain GLB, the rigged GLB, the humanoid sidecar and both gallery manifests."""
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")[:48] or "blob"
    stamp = hashlib.sha256(f"{MAKE}:{workspace}:{intent}".encode()).hexdigest()[:16]
    plain_name = f"blob-{stem}-{stamp}.glb"
    rigged_name = f"blob-{stem}-{stamp}-rigged.glb"
    plain, rigged = _store(folder, plain_name, body["glb"]), _store(folder, rigged_name, body["rigged"])
    rigged.with_suffix(".humanoid.json").write_text(json.dumps(body["sidecar"]), encoding="utf-8")
    recipe = {"traits": body["traits"], "faceAnchor": body["faceAnchor"], "pieces": len(body["pieces"])}
    _manifest(plain, workspace, intent, {**recipe, "role": "body"})
    _manifest(rigged, workspace, intent, {**recipe, "role": "rigged", "clips": _public_clips(body["sidecar"])})
    return _result(workspace, name, plain_name, rigged_name, body)


def _preset(name):
    if name is None:
        return {}
    if not isinstance(name, str) or name not in PRESETS:
        raise BlobTraitsError("unknown_preset", f"Unknown preset: {name}")
    return _copy(PRESETS[name])


def _overlay(base: dict, traits: dict) -> dict:
    if not isinstance(traits, dict):
        raise BlobTraitsError("invalid_traits", "traits must be an object")
    merged = _copy(base)
    for key, value in traits.items():
        current = merged.get(key)
        if key in _NESTED and isinstance(current, dict) and isinstance(value, dict):
            merged[key] = {**current, **value}
        else:
            merged[key] = _copy(value)
    return merged


def _one_clip(item, chosen: list[str]) -> None:
    if not isinstance(item, str) or item not in CLIP_IDS:
        raise BlobTraitsError("invalid_clips", f"Unknown clip: {item}")
    if item not in chosen:
        chosen.append(item)


def _clips(value) -> list[str]:
    if value is None:
        return [clip for clip in DEFAULT_CLIPS if clip in CLIP_IDS]
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        raise BlobTraitsError("invalid_clips", "clips must be one to 32 catalog names")
    chosen: list[str] = []
    for item in value:
        _one_clip(item, chosen)
    return chosen


def _store(folder: Path, filename: str, data: bytes) -> Path:
    target = folder / filename
    temporary = folder / f".{filename}-{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(data)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _manifest(path: Path, workspace: str, intent: str, params: dict) -> None:
    publish_generation_sidecar(
        path,
        {"generation_mode": "model3d", "model_type": "blob-body", "command_id": intent, "params": params},
        output_folder=workspace, tool=agent_trusted_tool() or "model3d", actor="user", capability=MAKE,
    )


def _public_clips(sidecar: dict) -> list[dict]:
    return [{key: row[key] for key in _CLIP_KEYS} for row in sidecar["clips"]]


def _result(workspace: str, name: str, plain_name: str, rigged_name: str, body: dict) -> dict:
    def url(filename: str) -> str:
        return f"/api/v1/file/{filename}?{urlencode({'workspace': workspace})}"

    return {
        "file": plain_name, "url": url(plain_name),
        "rigged_file": rigged_name, "rigged_url": url(rigged_name),
        "clips": _public_clips(body["sidecar"]),
        "faceAnchor": body["faceAnchor"], "traits": body["traits"],
        "name": name, "workspace": workspace,
    }
