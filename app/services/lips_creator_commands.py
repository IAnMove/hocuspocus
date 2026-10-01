"""Shared Lips Creator operations for HTTP, MCP and Ask to the Wizard.

Image jobs remain owned by generation.image. Planning never starts a job;
clients generate sequentially and capture each completed image as a candidate.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import threading
import uuid

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from services.character_kit_library import (
    LIPS_CREATOR_LIBRARY_FILENAME, CharacterKitRevisionConflict,
    read_character_kit_library, patch_character_kit, delete_character_kit,
)
from services.mcp_intent import check_intent_id, intent_digest, load_intent, store_intent, IntentConflict

_LOCK = threading.RLock()
_OPTIONS = {"library_filename": LIPS_CREATOR_LIBRARY_FILENAME}
_STATES = {
    "closed": "relaxed closed lips at rest", "small": "a narrow horizontal mouth for I",
    "wide": "an open tall mouth for A, visible dark mouth interior", "round": "rounded open lips for O",
    "pressed": "lips pressed firmly together for M, B and P", "medium": "a moderately open horizontally broad mouth for E",
    "pucker": "small tightly pursed round lips for U", "bite": "upper teeth touching the lower lip for F",
    "tongue": "slightly open lips with the tongue touching the upper teeth for L",
}
_SOUNDS = {"rest": "closed", "M": "pressed", "A": "wide", "E": "medium", "I": "small", "O": "round", "U": "pucker", "F": "bite", "L": "tongue"}
_STRING = {"type": "string", "minLength": 1, "maxLength": 240}
_ID = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$"}
_REV = {"type": "integer", "minimum": 0}
_STATES_SCHEMA = {"type": "array", "minItems": 1, "maxItems": 9, "uniqueItems": True, "items": {"enum": list(_STATES)}}
_CHANGE_FIELDS = {"name", "style", "lookNotes", "base", "mouthGenerationMode", "mouthPrompts", "mouthMapping", "anchors"}
# Input schema and handler validation use this single operation table.
_OPERATIONS = {
    "lips.list": (False, "List saved mouth collections and their revision in one workspace.", {}, []),
    "lips.create": (True, "Create a mouth collection from a description or saved reference, without generating images.",
                    {"name": _STRING, "pack_id": _ID, "description": {"type": "string", "maxLength": 1500}, "style": {"enum": ["cutout", "children-illustration", "anime-2d"]}, "reference": {"type": "object"}}, ["name"]),
    "lips.update": (True, "Edit collection settings, per-mouth prompts, anchors or sound assignments. Uses an exact base_revision.",
                    {"pack_id": _ID, "base_revision": _REV, "changes": {"type": "object", "additionalProperties": False, "properties": {key: {} for key in sorted(_CHANGE_FIELDS)}}}, ["pack_id", "base_revision", "changes"]),
    "lips.generation.plan": (False, "Plan missing mouths or specific states to regenerate. Run generation.image one at a time, wait for terminal status, then lips.capture each output. Generated mouths remain pending until explicitly reviewed with lips.accept. This operation never starts a job.",
                             {"pack_id": _ID, "states": _STATES_SCHEMA}, ["pack_id"]),
    "lips.capture": (True, "Save one generated or uploaded persistent image as a pending mouth candidate; preserves the approved mouth for comparison. Never marks an output approved.",
                     {"pack_id": _ID, "base_revision": _REV, "state": {"enum": list(_STATES)}, "asset": {"type": "object"}}, ["pack_id", "base_revision", "state", "asset"]),
    "lips.accept": (True, "Explicitly approve reviewed transparent mouth candidates for the specified states. Opaque images need background cleanup first.",
                    {"pack_id": _ID, "base_revision": _REV, "states": _STATES_SCHEMA}, ["pack_id", "base_revision", "states"]),
    "lips.apply": (True, "Apply an approved collection and its sound mapping to an exact character ID. Preserves identity, voice and existing placement unless the collection has the exact same reference. base_revision is the CHARACTER library revision, not the Lips library revision. Place and save the character before lip-sync video production.",
                   {"pack_id": _ID, "character_id": _ID, "base_revision": _REV, "pose_id": _ID}, ["pack_id", "character_id", "base_revision"]),
    "lips.delete": (True, "Delete a collection by exact ID and revision. Already linked characters keep their copied mouths.",
                    {"pack_id": _ID, "base_revision": _REV}, ["pack_id", "base_revision"]),
    "lips.receipt": (False, "Recover the stored result of a Lips mutation after a lost response or restart. Reuse the original intent_id for transport retries.",
                     {"operation": {"enum": ["lips.create", "lips.update", "lips.capture", "lips.accept", "lips.apply", "lips.delete"]}, "intent_id": _STRING}, ["operation", "intent_id"]),
}


def command_catalog():
    result = []
    for name, (mutation, description, properties, required) in _OPERATIONS.items():
        envelope = {"version": {"type": "integer", "const": 1}, "input": {"type": "object", "additionalProperties": False,
                    "properties": {"workspace": _ID, **properties}, "required": ["workspace", *required]}}
        keys = ["version", "input"]
        if mutation:
            envelope["intent_id"] = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$"}
            keys.append("intent_id")
        result.append({"name": name, "version": 1, "domain": "characters", "mutation": mutation,
                       "receipt_tool": "lips.receipt", "destructive": name == "lips.delete",
                       "description": description, "inputSchema": {"type": "object", "additionalProperties": False, "properties": envelope, "required": keys}})
    return result


def _states(data):
    states = data.get("states")
    if not isinstance(states, list) or not 1 <= len(states) <= 9 or any(not isinstance(state, str) or state not in _STATES for state in states) or len(set(states)) != len(states):
        raise ValueError("Use one to nine distinct mouth states")
    return states


def _pack(library, pack_id):
    if pack_id not in library["kits"]:
        raise HTTPException(404, detail="Mouth collection not found")
    return deepcopy(library["kits"][pack_id])


def _prompt(pack, state, reference):
    appearance = "Use the reference for the exact lip shape, color, material and drawing style." if reference else "Create the lip shape, color, material and drawing style entirely from the description."
    return f"Create exactly ONE isolated front-facing mouth sprite: {_STATES[state]}. {pack.get('lookNotes') or 'Clean hand-drawn cartoon lips, simple shapes and clear silhouette'}. {pack.get('mouthPrompts', {}).get(state, '')}. {appearance} Preserve identical proportions, centered placement and lighting across all mouth states. Mouth and necessary teeth or tongue ONLY, tightly cropped, transparent background, no face, head, eyes, body, text, grid or multiple mouths."


def _persistent_source(value, message):
    source = value.get("source") if isinstance(value, dict) else None
    if not isinstance(source, str) or not source.strip() or source.lower().startswith(("blob:", "data:")):
        raise ValueError(message)
    return source


def _create(data, library, root):
    pack_id = data.get("pack_id") or f"lips-{uuid.uuid4().hex[:16]}"
    if pack_id in library["kits"]:
        raise HTTPException(409, detail="A collection with that ID already exists")
    timestamp = datetime.now(timezone.utc).isoformat()
    kit = {"version": 1, "id": pack_id, "name": data["name"], "style": data.get("style", "cutout"),
           "lookNotes": data.get("description", ""), "poses": {}, "mouth": {}, "eyes": {}, "anchors": {},
           "mouthMapping": {}, "mouthPrompts": {}, "mouthGenerationMode": "reference" if data.get("reference") else "description",
           "provenance": [{"method": "lips-creator"}], "createdAt": timestamp, "updatedAt": timestamp}
    if data.get("reference"):
        _persistent_source(data["reference"], "Choose a saved persistent reference image")
        kit["base"] = data["reference"]
    saved = patch_character_kit(str(root), pack_id, kit, base_revision=library["revision"], **_OPTIONS)
    return {"pack_id": pack_id, "library": saved}


def _missing_states(pack):
    return [state for state in _STATES if _state_needs_generation(pack, state)]


def _state_needs_generation(pack, state):
    if pack.get("mouthCandidates", {}).get(state):
        return False
    current = pack["mouth"].get(state)
    return not current or current["reviewState"] == "rejected"


def _generation_reference(pack):
    fallback = "reference" if pack.get("base") else "description"
    mode = pack.get("mouthGenerationMode", fallback)
    if mode != "reference":
        return None
    return pack.get("base", {}).get("source")


def _plan(data, pack, library):
    states = _states(data) if "states" in data else _missing_states(pack)
    reference = _generation_reference(pack)
    if pack.get("mouthGenerationMode") == "reference" and not reference:
        raise ValueError("Choose a saved reference or description mode before generating")
    if any(len(_prompt(pack, state, bool(reference))) > 4000 for state in states):
        raise ValueError("Shorten the collection description or per-mouth prompt before generating")
    return {"pack_id": pack["id"], "base_revision": library["revision"], "requests": _plan_requests(pack, states, reference),
            "workflow": "Select an installed image model; submit generation.image sequentially, wait for completion, lips.capture each output with the latest Lips revision, then review and lips.accept. Pass the reference through generation.image v2 image_refs when present. On an uncertain job status, recover generation.receipt before submitting another job."}


def _plan_requests(pack, states, reference):
    hint = "qwen_image_edit" if reference else "qwen_image_21"
    return [{"state": state, "prompt": _prompt(pack, state, bool(reference)), "reference": reference,
             "resolution": "1024x1024", "model_hint": hint,
             "negative_prompt": "face, head, eyes, body, multiple mouths, sprite sheet, text, watermark, checkerboard, background, skin rectangle"}
            for state in states]


def _update(data, pack):
    changes = data["changes"]
    if not isinstance(changes, dict) or set(changes) - _CHANGE_FIELDS:
        raise ValueError("Use only collection settings, prompts, mappings or anchors in changes")
    pack.update(changes)


def _capture(data, pack):
    state = data["state"]
    if state not in _STATES or not isinstance(data["asset"], dict):
        raise ValueError("Use an exact mouth state and persistent image asset")
    source = _persistent_source(data["asset"], "Capture a saved persistent image source")
    pack.setdefault("mouthCandidates", {})[state] = {**data["asset"], "kind": "overlay", "reviewState": "pending"}
    pack["provenance"].append({"method": "lips-creator-capture", "state": state, "source": source})


def _accept_state(pack, state):
    asset = pack.get("mouthCandidates", {}).get(state) or pack["mouth"].get(state)
    if not asset or asset.get("reviewState") == "rejected":
        raise ValueError(f"There is no candidate to approve for {state}")
    if asset.get("alphaStatus") != "transparent" and not asset.get("facePatch"):
        raise ValueError(f"Remove the background before accepting {state}")
    pack["mouth"][state] = {**asset, "reviewState": "approved"}
    pack.get("mouthCandidates", {}).pop(state, None)
    pack["provenance"].append({"method": "lips-creator-accept", "state": state, "source": asset["source"]})


def _accept(data, pack):
    for state in _states(data):
        _accept_state(pack, state)


def _missing_approved_sounds(pack):
    missing = []
    for sound, default in _SOUNDS.items():
        state = pack.get("mouthMapping", {}).get(sound, default)
        if pack["mouth"].get(state, {}).get("reviewState") != "approved":
            missing.append(sound)
    return missing


def _copy_approved_mouths(pack, character, pose_id, pose):
    for state, asset in pack["mouth"].items():
        if asset["reviewState"] != "approved":
            continue
        _require_pose_patch(asset.get("facePatch"), pose_id, pose)
        character["mouth"][state] = asset


def _require_pose_patch(patch, pose_id, pose):
    if patch and (patch["poseId"] != pose_id or patch["poseSource"] != pose["source"]):
        raise ValueError("This facial patch belongs to another pose; prepare it for the target pose")


def _apply(data, pack, root):
    missing = _missing_approved_sounds(pack)
    if missing:
        raise ValueError(f"Approve a mouth for every sound before linking: {', '.join(missing)}")
    characters = read_character_kit_library(str(root))
    character_id = data["character_id"]
    if character_id not in characters["kits"]:
        raise HTTPException(404, detail="Character not found")
    character = deepcopy(characters["kits"][character_id])
    pose_id = data.get("pose_id", "base")
    pose = character.get("base") if pose_id == "base" else character["poses"].get(pose_id)
    if not pose:
        raise ValueError("Choose a character with a saved pose image")
    _copy_approved_mouths(pack, character, pose_id, pose)
    character["mouthMapping"] = pack.get("mouthMapping", {})
    if pack.get("base", {}).get("source") == pose["source"] and pack["anchors"].get("base"):
        character["anchors"][pose_id] = pack["anchors"]["base"]
    character.pop("restPose", None)
    character["provenance"].append({"method": "lips-creator-link", "packId": pack["id"], "packUpdatedAt": pack.get("updatedAt")})
    return character


def _save_pack(name, data, pack, root, options):
    pack["updatedAt"] = datetime.now(timezone.utc).isoformat()
    saved = patch_character_kit(str(root), pack["id"], pack, base_revision=data["base_revision"], **options)
    body = {"pack_id": data["pack_id"], "library": saved}
    if name == "lips.apply":
        body["character_id"] = pack["id"]
    return body


def _effect(name, data, root):
    library = read_character_kit_library(str(root), **_OPTIONS)
    if name == "lips.list":
        return {"library": library}
    if name == "lips.create":
        return _create(data, library, root)
    pack = _pack(library, data["pack_id"])
    if name == "lips.generation.plan":
        return _plan(data, pack, library)
    if name == "lips.delete":
        deleted = delete_character_kit(str(root), pack["id"], base_revision=data["base_revision"], **_OPTIONS)
        return {"pack_id": pack["id"], "library": deleted}
    if name == "lips.apply":
        pack = _apply(data, pack, root)
        return _save_pack(name, data, pack, root, {})
    if name == "lips.update":
        _update(data, pack)
    elif name == "lips.capture":
        _capture(data, pack)
    elif name == "lips.accept":
        _accept(data, pack)
    return _save_pack(name, data, pack, root, _OPTIONS)


def _require_operation(name, arguments):
    if name not in _OPERATIONS:
        raise ValueError("Unknown Lips Creator operation")
    mutation, _, properties, required = _OPERATIONS[name]
    expected = {"version", "input", *(["intent_id"] if mutation else [])}
    version = arguments.get("version") if isinstance(arguments, dict) else None
    if not isinstance(arguments, dict) or set(arguments) != expected or type(version) is not int or version != 1:
        raise ValueError("Use version 1, input, and intent_id for mutations")
    data = arguments["input"]
    allowed = {"workspace", *properties}
    if not isinstance(data, dict) or set(data) - allowed or any(key not in data for key in ["workspace", *required]):
        raise ValueError(f"Use input fields: workspace, {', '.join(required)}")
    return mutation, properties, data


def _check_schema_value(key, schema, value):
    if schema.get("type") == "string" and not _valid_string(value, schema):
        raise ValueError(f"Use a valid {key}")
    if schema.get("type") == "object" and not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"Use a valid {key}")


def _valid_string(value, schema):
    if not isinstance(value, str) or len(value) > schema.get("maxLength", 4000):
        return False
    return not schema.get("minLength", 0) or bool(value.strip())


def _check_ids(data):
    for key in ("workspace", "pack_id", "character_id", "pose_id"):
        if key in data and not _exact_id(data[key]):
            raise ValueError(f"Use an exact valid {key}")
    if "base_revision" in data and not _revision(data["base_revision"]):
        raise ValueError("base_revision must be a non-negative integer")


def _exact_id(value):
    return isinstance(value, str) and re.fullmatch(_ID["pattern"], value) is not None


def _revision(value):
    return type(value) is int and value >= 0


def _receipt(data, root):
    operation = data["operation"]
    intent = check_intent_id(data["intent_id"])
    if operation not in _OPERATIONS or not _OPERATIONS[operation][0]:
        raise ValueError("Choose a Lips mutation operation")
    path = root / ".mcp-intents" / operation / f"{intent}.json"
    if not path.is_file():
        raise HTTPException(404, detail="Lips receipt not found")
    return json.loads(path.read_text(encoding="utf-8"))["result"]


def _completed(name, result, replayed=False):
    body = {"version": 1, "operation": name, "status": "completed", "result": result}
    if replayed:
        body["replayed"] = True
    return body


def _mutate(name, arguments, data, root):
    intent = check_intent_id(arguments["intent_id"])
    digest = intent_digest(data)
    with _LOCK:
        prior = load_intent(root, name, intent, digest)
        if prior is not None:
            return _completed(name, prior, replayed=True)
        result = _effect(name, data, root)
        store_intent(root, name, intent, digest, result)
    return _completed(name, result)


def execute_command(name, arguments, workspace_dir):
    try:
        mutation, properties, data = _require_operation(name, arguments)
        for key, schema in properties.items():
            if key in data:
                _check_schema_value(key, schema, data[key])
        _check_ids(data)
        root = Path(workspace_dir(data["workspace"]))
        if name == "lips.receipt":
            return _completed(name, _receipt(data, root))
        if mutation:
            return _mutate(name, arguments, data, root)
        return _completed(name, _effect(name, data, root))
    except (CharacterKitRevisionConflict, IntentConflict) as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


def command_handlers(workspace_dir):
    def handler(name):
        async def run(arguments):
            return await run_in_threadpool(execute_command, name, arguments, workspace_dir)
        return run
    return {name: handler(name) for name in _OPERATIONS}
