"""Bind a Character Kit face onto a Video 3D model slot, and the art the cap paints."""
from __future__ import annotations

from typing import Any

from services.blob_face import BlobFaceError
from services.blob_face_place import anchor_radii, head_placement
from services.character_kit_library import read_character_kit_library
from services.flat_rig import STATES, FlatRigError, _workspace_file
from services.world3d_scenes import World3DSceneError, _read, _target, _view, _write

MOUTH_ANCHOR = {"offsetX": 0.0, "offsetY": 0.0, "scale": 0.16, "rotation": 0.0}
EYE_ANCHOR = {"offsetX": 0.0, "offsetY": 0.0, "scale": 1.0, "rotation": 0.0}


def _approved(asset: Any) -> bool:
    return isinstance(asset, dict) and asset.get("reviewState") == "approved" and bool(asset.get("source"))


def _nine(kit: dict) -> dict[str, str]:
    mouths = {}
    missing = []
    for state in STATES:
        item = (kit.get("mouth") or {}).get(state)
        if _approved(item):
            mouths[state] = item["source"]
        else:
            missing.append(state)
    if missing:
        raise World3DSceneError("mouths_not_ready", "The kit needs nine approved mouths: " + ", ".join(missing))
    return mouths


def _pose_art(kit: dict, name: str, asset: dict) -> dict[str, Any]:
    group = (kit.get("anchors") or {}).get(name) or (kit.get("anchors") or {}).get("base") or {}
    entry = {"base": asset["source"], "mouth": dict(group.get("mouth") or MOUTH_ANCHOR),
             "eyes": dict(group.get("eyes") or EYE_ANCHOR)}
    if group.get("blink") is not False:
        blink = group.get("blinkSource") or ((kit.get("eyes") or {}).get("blink") or {}).get("source")
        if isinstance(blink, str) and blink:
            entry["blink"] = blink
    return entry


def face_art(kit: dict) -> dict[str, Any]:
    """What the cap paints: each approved pose, the nine mouths, and the rest mouth. Cues arrive with talk."""
    mouths = _nine(kit)
    poses = {}
    if _approved(kit.get("base")):
        poses["base"] = _pose_art(kit, "base", kit["base"])
    for name, asset in (kit.get("poses") or {}).items():
        if isinstance(name, str) and _approved(asset):
            poses[name] = _pose_art(kit, name, asset)
    if not poses:
        raise World3DSceneError("pose_not_ready", "The kit has no approved pose to paint")
    rest = (kit.get("mouthMapping") or {}).get("rest") if isinstance(kit.get("mouthMapping"), dict) else None
    return {"poses": poses, "mouths": mouths, "rest": rest if rest in mouths else "closed"}


def _names(kit: dict) -> set[str]:
    names = {name for name, asset in (kit.get("poses") or {}).items() if _approved(asset)}
    if _approved(kit.get("base")):
        names.add("base")
    return names


def _pose_name(changes: dict, kit: dict) -> str:
    names = _names(kit)
    pose = changes.get("pose")
    if isinstance(pose, str) and pose in names:
        return pose
    if "neutral" in names:
        return "neutral"
    return "base" if "base" in names else sorted(names)[0]


def _expressions(changes: dict, kit: dict) -> list[dict[str, Any]]:
    raw = changes.get("expressions") or []
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 32:
        raise World3DSceneError("invalid_expression", "expressions must be a list of at most 32")
    names = _names(kit)
    found = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("pose"), str) or item["pose"] not in names:
            raise World3DSceneError("unknown_pose", f"expressions[{index}] needs a pose the kit has")
        start = item.get("start", 0)
        if isinstance(start, bool) or not isinstance(start, (int, float)) or not 0 <= float(start) <= 600:
            raise World3DSceneError("invalid_expression", f"expressions[{index}].start must be seconds from 0 to 600")
        found.append({"start": round(float(start), 3), "pose": item["pose"]})
    return sorted(found, key=lambda item: item["start"])


def _outset(value: Any) -> float:
    if value is None:
        return 1.04
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= float(value) <= 1.2:
        raise World3DSceneError("invalid_face", "size is how far the cap sits outside the head, from 1 to 1.2")
    return round(float(value), 3)


def _explicit(changes: dict) -> dict[str, Any] | None:
    if "center" not in changes and "radii" not in changes:
        return None
    found = anchor_radii({"center": changes.get("center"), "radii": changes.get("radii")})
    if found is None:
        raise World3DSceneError("invalid_face", "center and radii are three metres each; radii must be greater than 0")
    return found


def _placement(changes: dict, slot: dict, workspace: str, folder: str) -> dict[str, Any]:
    explicit = _explicit(changes)
    if explicit:
        return explicit
    raw = changes.get("face_anchor") if isinstance(changes.get("face_anchor"), dict) else slot.get("faceAnchor")
    declared = anchor_radii(raw) if isinstance(raw, dict) else None
    if declared:
        return declared
    source = changes.get("source_url") or slot.get("sourceUrl") or ""
    if not isinstance(source, str) or not source.startswith("/"):
        raise World3DSceneError("head_not_found", "Pass center and radii, face_anchor, or a model file with a Head bone")
    try:
        return head_placement(_workspace_file(source, workspace, folder))
    except (BlobFaceError, FlatRigError) as error:
        raise World3DSceneError(error.code, str(error), error.status) from error


def _carry(art: dict, kept: dict) -> dict:
    previous = kept.get("art") if isinstance(kept.get("art"), dict) else {}
    for key in ("cues", "blinks"):
        if key in previous:
            art[key] = previous[key]
    if previous.get("rest") in art["mouths"]:
        art["rest"] = previous["rest"]
    return art


def _bone(changes: dict, kept: dict) -> str:
    bone = changes.get("bone") or kept.get("bone") or "Head"
    if not isinstance(bone, str) or not bone.strip():
        raise World3DSceneError("invalid_face", "bone must name a bone, usually Head")
    return bone.strip()[:80]


def bind_face(workspace: str, scene_id: str, workspace_dir, changes: dict, base_revision: int) -> dict:
    """Write ``slot.faceDecal`` on a model. The slot stays a model."""
    record = _read(workspace, scene_id, workspace_dir)
    if type(base_revision) is not int or base_revision != record["revision"]:
        raise World3DSceneError("revision_conflict", "The scene changed since this revision. Reload before editing.", 409)
    kit_id = changes.get("kit_id")
    kit = (read_character_kit_library(str(workspace_dir(workspace))).get("kits") or {}).get(kit_id) if isinstance(kit_id, str) else None
    if kit is None:
        raise World3DSceneError("unknown_kit", f"unknown_kit:{kit_id}", 404)
    document = record["document"]
    slot = _target(document.get("slots") or [], changes)
    if slot.get("media") not in (None, "model3d"):
        raise World3DSceneError("not_a_model", f"Object {slot.get('id')} is {slot.get('media')}; a 2D face needs a model")
    slot["media"] = "model3d"
    placement = _placement(changes, slot, workspace, str(workspace_dir(workspace)))
    kept = slot.get("faceDecal") if isinstance(slot.get("faceDecal"), dict) else {}
    art = _carry(face_art(kit), kept)
    slot["faceDecal"] = {"kitId": kit["id"], "pose": _pose_name(changes, kit), "bone": _bone(changes, kept),
                         "center": placement["center"], "radii": placement["radii"], "size": _outset(changes.get("size", kept.get("size"))),
                         "expressions": _expressions(changes, kit), "art": art}
    character = slot.get("character") if isinstance(slot.get("character"), dict) else {}
    slot["character"] = {**character, "id": str(kit.get("id")), "name": str(kit.get("name") or kit.get("id"))[:300]}
    record["revision"] += 1
    record["warnings"] = []
    _write(workspace, scene_id, record, workspace_dir)
    viewed = _view(scene_id, record, workspace, workspace_dir)
    viewed["face"] = {"objectId": slot.get("id"), "kitId": kit["id"], "pose": slot["faceDecal"]["pose"],
                      "center": placement["center"], "radii": placement["radii"], "method": placement.get("method", "given")}
    return viewed
