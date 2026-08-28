"""Durable, workspace-scoped Character Kit storage.

Character kits are reusable production assets rather than scene-local browser
state.  This library uses the same atomic compare-and-swap contract as Story
Lab so two browser tabs cannot silently overwrite one another.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from typing import Any


CHARACTER_KIT_LIBRARY_FILENAME = ".character-kit-library-v1.json"
MAX_CHARACTER_KITS = 100
MAX_LIBRARY_BYTES = 20 * 1024 * 1024
_LOCK = threading.RLock()
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_STYLES = {"cutout", "children-illustration", "anime-2d"}
_REVIEW_STATES = {"pending", "approved", "rejected"}
_ALPHA_STATES = {"unknown", "transparent", "opaque"}


class CharacterKitRevisionConflict(ValueError):
    def __init__(self, expected: int, current: int):
        super().__init__(f"Character Kit library revision conflict: expected {expected}, current {current}")
        self.expected = expected
        self.current = current


def empty_character_kit_library() -> dict[str, Any]:
    return {"version": 1, "revision": 0, "activeId": "", "kits": {}}


def _token(value: Any, label: str) -> str:
    token = str(value or "").strip()
    if not _ID.fullmatch(token):
        raise ValueError(f"{label} has an invalid id")
    return token


def _text(value: Any, label: str, maximum: int, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{label} is required")
    if len(text) > maximum or any(ord(char) < 32 for char in text):
        raise ValueError(f"{label} is invalid")
    return text


def _asset(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    source = _text(value.get("source"), f"{label} source", 1200, required=True)
    if source.startswith("blob:"):
        raise ValueError(f"{label} must use a persistent source, not a browser blob URL")
    alpha_status = str(value.get("alphaStatus") or "unknown")
    review_state = str(value.get("reviewState") or "pending")
    if alpha_status not in _ALPHA_STATES:
        raise ValueError(f"{label} has an invalid alpha status")
    if review_state not in _REVIEW_STATES:
        raise ValueError(f"{label} has an invalid review state")
    result = {
        "id": _token(value.get("id"), label),
        "name": _text(value.get("name"), f"{label} name", 240, required=True),
        "source": source,
        "kind": "overlay" if value.get("kind") == "overlay" else "image",
        "alphaStatus": alpha_status,
        "reviewState": review_state,
    }
    for key, maximum in (("prompt", 4000), ("model", 240), ("workspace", 120)):
        text = _text(value.get(key), f"{label} {key}", maximum)
        if text:
            result[key] = text
    return result


def _anchor(value: Any, label: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    result: dict[str, float] = {}
    bounds = {"offsetX": (-200.0, 200.0), "offsetY": (-200.0, 200.0), "scale": (0.001, 20.0), "rotation": (-360.0, 360.0)}
    for key, (minimum, maximum) in bounds.items():
        raw = value.get(key, 1 if key == "scale" else 0)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"{label} {key} must be numeric")
        number = float(raw)
        if not minimum <= number <= maximum:
            raise ValueError(f"{label} {key} is out of range")
        result[key] = number
    return result


def normalize_character_kit(value: Any, fallback_id: str = "") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Character Kit must be a JSON object")
    kit_id = _token(value.get("id") or fallback_id, "Character Kit")
    style = str(value.get("style") or "cutout")
    if style not in _STYLES:
        raise ValueError("Character Kit style is invalid")

    poses_raw = value.get("poses") or {}
    if not isinstance(poses_raw, dict) or len(poses_raw) > 32:
        raise ValueError("Character Kit poses must be an object with at most 32 entries")
    poses = {_token(key, "Pose"): _asset(asset, f"Pose {key}") for key, asset in poses_raw.items()}

    mouth_raw = value.get("mouth") or {}
    if not isinstance(mouth_raw, dict) or any(key not in {"closed", "small", "wide", "round"} for key in mouth_raw):
        raise ValueError("Character Kit mouth states are invalid")
    mouth = {key: _asset(asset, f"Mouth {key}") for key, asset in mouth_raw.items()}

    eyes_raw = value.get("eyes") or {}
    if not isinstance(eyes_raw, dict) or any(key not in {"open", "blink"} for key in eyes_raw):
        raise ValueError("Character Kit eye states are invalid")
    eyes = {key: _asset(asset, f"Eyes {key}") for key, asset in eyes_raw.items()}

    anchors_raw = value.get("anchors") or {}
    if not isinstance(anchors_raw, dict) or len(anchors_raw) > 32:
        raise ValueError("Character Kit anchors must be an object with at most 32 poses")
    anchors: dict[str, dict[str, Any]] = {}
    for raw_pose_id, raw_group in anchors_raw.items():
        pose_id = _token(raw_pose_id, "Anchor pose")
        if not isinstance(raw_group, dict) or "mouth" not in raw_group:
            raise ValueError(f"Anchors for {pose_id} need a mouth anchor")
        group = {"mouth": _anchor(raw_group["mouth"], f"{pose_id} mouth anchor")}
        mouth_states_raw = raw_group.get("mouthStates")
        if mouth_states_raw is not None:
            if not isinstance(mouth_states_raw, dict) or any(key not in {"closed", "small", "wide", "round"} for key in mouth_states_raw):
                raise ValueError(f"Anchors for {pose_id} have invalid mouth states")
            group["mouthStates"] = {
                key: _anchor(anchor, f"{pose_id} mouth {key} anchor")
                for key, anchor in mouth_states_raw.items()
            }
        if raw_group.get("eyes") is not None:
            group["eyes"] = _anchor(raw_group["eyes"], f"{pose_id} eyes anchor")
        anchors[pose_id] = group

    result: dict[str, Any] = {
        "version": 1,
        "id": kit_id,
        "name": _text(value.get("name"), "Character Kit name", 240, required=True),
        "style": style,
        "poses": poses,
        "mouth": mouth,
        "eyes": eyes,
        "anchors": anchors,
        "provenance": value.get("provenance") if isinstance(value.get("provenance"), list) else [],
    }
    if len(result["provenance"]) > 500 or any(not isinstance(item, dict) for item in result["provenance"]):
        raise ValueError("Character Kit provenance must contain at most 500 objects")
    for key in ("identityReference", "base"):
        if value.get(key) is not None:
            result[key] = _asset(value[key], f"Character Kit {key}")
    for key in ("createdAt", "updatedAt"):
        text = _text(value.get(key), f"Character Kit {key}", 80)
        if text:
            result[key] = text
    return result


def normalize_character_kit_library(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("kits"), dict):
        raise ValueError("Character Kit library must contain a kits object")
    if len(value["kits"]) > MAX_CHARACTER_KITS:
        raise ValueError(f"Character Kit library is limited to {MAX_CHARACTER_KITS} kits")
    kits = {kit_id: normalize_character_kit(kit, str(kit_id)) for kit_id, kit in value["kits"].items()}
    if any(kit_id != kit["id"] for kit_id, kit in kits.items()):
        raise ValueError("Character Kit key does not match its id")
    revision = value.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("Character Kit library revision must be a non-negative integer")
    active_id = str(value.get("activeId") or "")
    if active_id not in kits:
        active_id = next(iter(kits), "")
    return {"version": 1, "revision": revision, "activeId": active_id, "kits": kits}


def character_kit_library_path(workspace_dir: str) -> str:
    return os.path.join(workspace_dir, CHARACTER_KIT_LIBRARY_FILENAME)


def read_character_kit_library(workspace_dir: str) -> dict[str, Any]:
    with _LOCK:
        path = character_kit_library_path(workspace_dir)
        if not os.path.isfile(path):
            return empty_character_kit_library()
        with open(path, "r", encoding="utf-8") as handle:
            return normalize_character_kit_library(json.load(handle))


def _revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("baseRevision must be a non-negative integer")
    return value


def write_character_kit_library(workspace_dir: str, value: Any, *, base_revision: int) -> dict[str, Any]:
    expected = _revision(base_revision)
    library = normalize_character_kit_library(value)
    with _LOCK:
        current = read_character_kit_library(workspace_dir)
        if expected != current["revision"]:
            raise CharacterKitRevisionConflict(expected, int(current["revision"]))
        library["revision"] = int(current["revision"]) + 1
        encoded = json.dumps(library, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_LIBRARY_BYTES:
            raise ValueError("Character Kit library is too large to save")
        os.makedirs(workspace_dir, exist_ok=True)
        path = character_kit_library_path(workspace_dir)
        temporary = f"{path}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                if os.path.isfile(temporary):
                    os.remove(temporary)
            except OSError:
                pass
        return library


def patch_character_kit(workspace_dir: str, kit_id: str, kit: Any, *, base_revision: int, make_active: bool = True) -> dict[str, Any]:
    token = _token(kit_id, "Character Kit")
    candidate = normalize_character_kit(kit, token)
    if candidate["id"] != token:
        raise ValueError("Character Kit id does not match the request path")
    with _LOCK:
        current = read_character_kit_library(workspace_dir)
        expected = _revision(base_revision)
        if expected != current["revision"]:
            raise CharacterKitRevisionConflict(expected, int(current["revision"]))
        next_library = {**current, "kits": {**current["kits"], token: candidate}}
        if make_active or not current.get("activeId"):
            next_library["activeId"] = token
        return write_character_kit_library(workspace_dir, next_library, base_revision=expected)


def delete_character_kit(workspace_dir: str, kit_id: str, *, base_revision: int) -> dict[str, Any]:
    token = _token(kit_id, "Character Kit")
    with _LOCK:
        current = read_character_kit_library(workspace_dir)
        expected = _revision(base_revision)
        if expected != current["revision"]:
            raise CharacterKitRevisionConflict(expected, int(current["revision"]))
        if token not in current["kits"]:
            raise KeyError(token)
        kits = dict(current["kits"])
        del kits[token]
        next_library = {**current, "kits": kits, "activeId": current["activeId"] if current.get("activeId") in kits else next(iter(kits), "")}
        return write_character_kit_library(workspace_dir, next_library, base_revision=expected)
