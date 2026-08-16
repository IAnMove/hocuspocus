"""Durable Series Lab library, canon review, and Story Lab import helpers.

The workspace JSON file is the source of truth.  Normalization deliberately
preserves unknown fields so newer clients can round-trip data through an older
Maestro server without silently losing it.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import os
import re
import uuid
from typing import Any


SERIES_LIBRARY_FILENAME = ".series-library-v1.json"
MAX_SERIES_PROJECTS = 100
MAX_SERIES_LIBRARY_BYTES = 100 * 1024 * 1024
MAX_BULK_ATTEMPT_APPROVALS = 500
_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_ASSET_PATH = re.compile(r"^(assets|outputs)/[A-Za-z0-9._/-]+$")

EPISODE_EDITOR_FIELDS = frozenset({
    "seasonId", "number", "title", "premise", "logline",
    "targetDurationSeconds", "outline", "script", "shots",
    "continuityIssues", "proposedCanonDelta",
})
SHOT_EDITOR_FIELDS = frozenset({
    "sceneId", "order", "durationSeconds", "framing", "camera", "action",
    "dialogueBeats", "visibleCharacterIds", "speakingCharacterIds",
    "primarySpeakerId", "locationId", "locationVariantId",
    "wardrobeByCharacterId", "propIds", "emotionalStateByCharacterId",
    "continuityFromShotId", "renderStrategy", "referencePolicy", "prompt",
    "negativePrompt", "audioDirection",
})
SHOT_SERVER_FIELDS = frozenset({"attempts", "approvedAttemptId", "referenceManifest"})


class SeriesConflictError(ValueError):
    """Raised when an optimistic revision no longer matches stored state."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _text(value: Any, fallback: str = "") -> str:
    return value if isinstance(value, str) else fallback


def _id(value: Any, fallback: str = "") -> str:
    result = _text(value, fallback).strip()
    if not result or len(result) > 240 or any(ord(char) < 32 for char in result):
        raise ValueError("Series Lab contains an invalid id")
    return result


def _integer(value: Any, fallback: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return max(minimum, fallback)


def _number(value: Any, fallback: float, minimum: float = 0) -> float:
    try:
        return max(minimum, float(value))
    except (TypeError, ValueError):
        return max(minimum, fallback)


def _objects(value: Any) -> list[dict]:
    return [copy.deepcopy(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _unique_ids(value: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    if not isinstance(value, list):
        return result
    for raw in value:
        if not isinstance(raw, str):
            continue
        item = raw.strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def validate_workspace_id(value: Any) -> str:
    workspace_id = _text(value or "default").strip()
    if workspace_id != "default" and not _WORKSPACE_ID.fullmatch(workspace_id):
        raise ValueError("Invalid Series Lab workspace")
    return workspace_id


def validate_series_asset_uri(value: Any) -> str:
    """Reject data URIs, traversal, absolute paths, and non-HTTPS remotes."""
    uri = _text(value).strip()
    if uri.startswith("https://"):
        return uri
    if not _ASSET_PATH.fullmatch(uri) or ".." in uri.split("/"):
        raise ValueError(
            "Series assets must use a workspace-contained assets/ or outputs/ path, "
            "or an HTTPS URL"
        )
    return uri


def empty_series_library(workspace_id: str = "default") -> dict[str, Any]:
    return {
        "schema": "series-library",
        "version": 1,
        "workspaceId": validate_workspace_id(workspace_id),
        "seriesOrder": [],
        "seriesById": {},
    }


def create_series_project(
    workspace_id: str = "default",
    *,
    title: str = "Untitled series",
) -> dict:
    workspace_id = validate_workspace_id(workspace_id)
    now = _now()
    suffix = uuid.uuid4().hex
    series_id = f"series_{suffix}"
    value = {
        "version": 1, "id": series_id, "revision": 1,
        "title": title.strip() or "Untitled series", "logline": "", "premise": "",
        "format": "episodic", "defaultEpisodeDurationSeconds": 75,
        "language": "Español", "spokenLanguage": "Español de España",
        "protagonistConsistency": False, "protagonistCharacterId": "",
        "genre": "", "tone": "Cinematic", "audience": "General",
        "visualStyle": "", "characterVisualStyle": "", "cameraLanguage": "",
        "allowClipText": False, "sourceMode": "original", "masterUniversePrompt": "",
        "rightsNote": "", "bestEffortLipSyncAcknowledged": False,
        "importSource": {
            "kind": "original", "sourceWorkspaceId": None, "sourceStoryId": None,
            "importedAt": now, "historicalProductionIds": [],
            "migrationNotes": "Created as an original Series Lab project.",
        },
        "canon": {
            "worldSummary": "", "immutableRules": [], "currentFacts": [],
            "forbiddenChanges": [], "themes": [], "longArcs": [], "timeline": [],
            "revision": 1,
            "approval": "draft", "approvedAt": "",
        },
        "characters": [], "relationships": [], "locations": [], "props": [],
        "seasons": [{
            "id": f"season_{suffix}_1", "number": 1, "title": "Season 1",
            "premise": "", "arc": "", "episodeOrder": [],
            "createdAt": now, "updatedAt": now,
        }],
        "episodesById": {}, "assets": {},
        "provider": {
            "useGlobalProfile": True,
            "writingProvider": "minimax", "writingModel": "MiniMax-M3", "writingBaseUrl": "https://api.minimax.io/v1",
            "imageProvider": "minimax", "imageModel": "image-01", "videoModel": "minimax_h3_legacy",
            "videoSettings": {
                "renderStrategy": "auto", "resolution": "540p",
                "orientation": "landscape", "numInferenceSteps": 20,
                "flowShift": 12, "audioShift": 3, "modelProfile": "quality",
            },
            "videoCapabilities": copy.deepcopy(DEFAULT_SERIES_H3_CAPABILITIES),
        },
        "createdAt": now, "updatedAt": now,
    }
    return normalize_series_project(value, series_id, workspace_id)


DEFAULT_SERIES_H3_CAPABILITIES = {
    "model": "minimax_h3_legacy", "family": "minimax_h3_legacy", "version": "runtime-default",
    "limits": {"image": 9, "video": 3, "audio": 3, "total": 12},
    "supportsFirstFrame": True, "supportsFirstLast": True,
    "supportsContinuation": True, "supportsNativeAudio": True,
}


def _normalize_asset(
    value: dict, series_id: str, workspace_id: str, index: int, key: str = ""
) -> dict:
    asset = copy.deepcopy(value)
    asset_id = _id(asset.get("id"), key or f"asset_{series_id}_{index + 1}")
    asset.update({
        "id": asset_id,
        "workspaceId": workspace_id,
        "kind": asset.get("kind") if asset.get("kind") in {
            "image", "audio", "video", "character", "location", "prop", "other"
        } else "other",
        "uri": validate_series_asset_uri(asset.get("uri")),
        "ownerType": asset.get("ownerType") if asset.get("ownerType") in {
            "series", "character", "location", "prop", "episode", "shot", "attempt"
        } else "series",
        "ownerId": _id(asset.get("ownerId"), series_id),
        "isDerivedThumbnail": asset.get("isDerivedThumbnail") is True,
        "metadata": copy.deepcopy(asset.get("metadata"))
        if isinstance(asset.get("metadata"), dict) else {},
    })
    return asset


def _normalize_entity(value: dict, prefix: str, index: int, defaults: dict) -> dict:
    entity = copy.deepcopy(value)
    entity["id"] = _id(entity.get("id"), f"{prefix}_{index + 1}")
    for key, fallback in defaults.items():
        if isinstance(fallback, list):
            entity[key] = (
                _objects(entity.get(key))
                if key in {"wardrobeVariants", "variants"}
                else _unique_ids(entity.get(key))
            )
        elif isinstance(fallback, dict):
            entity[key] = copy.deepcopy(entity.get(key)) if isinstance(entity.get(key), dict) else {}
        elif isinstance(fallback, bool):
            entity[key] = entity.get(key) is True
        elif isinstance(fallback, int):
            entity[key] = _integer(entity.get(key), fallback)
        else:
            entity[key] = _text(entity.get(key), fallback)
    return entity


def _normalize_canon(value: Any) -> dict:
    canon = copy.deepcopy(value) if isinstance(value, dict) else {}
    canon.update({
        "worldSummary": _text(canon.get("worldSummary")),
        "immutableRules": _objects(canon.get("immutableRules")),
        "currentFacts": _objects(canon.get("currentFacts")),
        "forbiddenChanges": _unique_ids(canon.get("forbiddenChanges")),
        "themes": _unique_ids(canon.get("themes")),
        "longArcs": _objects(canon.get("longArcs")),
        "timeline": _objects(canon.get("timeline")),
        "revision": _integer(canon.get("revision"), 1),
        "approval": "approved" if canon.get("approval") == "approved" else "draft",
        "approvedAt": _text(canon.get("approvedAt")),
    })
    return canon


def _normalize_dialogue_beat(value: dict, fallback_id: str) -> dict:
    beat = copy.deepcopy(value)
    beat.update({
        "id": _id(beat.get("id"), fallback_id),
        "characterId": _id(beat.get("characterId"), "character_unknown"),
        "text": _text(beat.get("text")),
        "emotion": _text(beat.get("emotion"), "natural"),
        "delivery": _text(beat.get("delivery"), "natural delivery"),
    })
    return beat


def _normalize_attempt(value: dict, shot_id: str, index: int) -> dict:
    attempt = copy.deepcopy(value)
    seed = attempt.get("seed")
    try:
        seed = int(seed) if seed is not None else None
    except (TypeError, ValueError, OverflowError):
        seed = None
    status = str(attempt.get("status") or "queued")
    if status not in {"queued", "running", "cancelling", "completed", "failed", "cancelled"}:
        status = "failed"
    attempt.update({
        "id": _id(attempt.get("id"), f"{shot_id}_attempt_{index + 1}"),
        "status": status,
        "prompt": _text(attempt.get("prompt")),
        "negativePrompt": _text(attempt.get("negativePrompt")),
        "model": _text(attempt.get("model"), "minimax_h3"),
        "referenceManifest": copy.deepcopy(attempt.get("referenceManifest"))
        if isinstance(attempt.get("referenceManifest"), dict) else {},
        "seed": seed,
        "settings": copy.deepcopy(attempt.get("settings"))
        if isinstance(attempt.get("settings"), dict) else {},
        "startTimeSeconds": _number(attempt.get("startTimeSeconds"), 0, 0),
        "endTimeSeconds": _number(attempt.get("endTimeSeconds"), 0, 0),
        "createdAt": _text(attempt.get("createdAt"), _now()),
        "elapsedMs": _integer(attempt.get("elapsedMs"), 0, 0),
        "outputAssetIds": _unique_ids(attempt.get("outputAssetIds")),
        "retryCount": _integer(attempt.get("retryCount"), 0, 0),
    })
    if attempt.get("reviewDecision") not in {"approved", "rejected"}:
        attempt.pop("reviewDecision", None)
    return attempt


def _normalize_shot(value: dict, index: int) -> dict:
    from .series_render import normalize_series_shot_duration

    shot = copy.deepcopy(value)
    shot_id = _id(shot.get("id"), f"shot_{index + 1}")
    dialogue = [
        _normalize_dialogue_beat(item, f"{shot_id}_dialogue_{dialogue_index + 1}")
        for dialogue_index, item in enumerate(_objects(shot.get("dialogueBeats")))
    ]
    attempts = [
        _normalize_attempt(item, shot_id, attempt_index)
        for attempt_index, item in enumerate(_objects(shot.get("attempts")))
    ]
    shot.update({
        "id": shot_id,
        "sceneId": _id(shot.get("sceneId"), "scene_1"),
        "order": _integer(shot.get("order"), index + 1, 1),
        "durationSeconds": float(normalize_series_shot_duration(shot.get("durationSeconds"))),
        "framing": _text(shot.get("framing")),
        "camera": _text(shot.get("camera")),
        "action": _text(shot.get("action")),
        "dialogueBeats": dialogue,
        "visibleCharacterIds": _unique_ids(shot.get("visibleCharacterIds")),
        "speakingCharacterIds": _unique_ids(shot.get("speakingCharacterIds")),
        "wardrobeByCharacterId": copy.deepcopy(shot.get("wardrobeByCharacterId"))
        if isinstance(shot.get("wardrobeByCharacterId"), dict) else {},
        "propIds": _unique_ids(shot.get("propIds")),
        "emotionalStateByCharacterId": copy.deepcopy(shot.get("emotionalStateByCharacterId"))
        if isinstance(shot.get("emotionalStateByCharacterId"), dict) else {},
        "renderStrategy": shot.get("renderStrategy") if shot.get("renderStrategy") in {
            "auto", "direct", "first_frame", "references", "first_last"
        } else "auto",
        "referencePolicy": copy.deepcopy(shot.get("referencePolicy"))
        if isinstance(shot.get("referencePolicy"), dict) else {
            "mode": "automatic", "manualIncludeAssetIds": [], "manualExcludeAssetIds": []
        },
        "prompt": _text(shot.get("prompt")),
        "negativePrompt": _text(shot.get("negativePrompt")),
        "attempts": attempts,
    })
    policy = shot["referencePolicy"]
    policy["mode"] = "manual" if policy.get("mode") == "manual" else "automatic"
    policy["manualIncludeAssetIds"] = _unique_ids(policy.get("manualIncludeAssetIds"))
    policy["manualExcludeAssetIds"] = _unique_ids(policy.get("manualExcludeAssetIds"))
    return shot


def _normalize_scene(value: dict, episode_id: str, index: int) -> dict:
    scene = copy.deepcopy(value)
    scene_id = _id(scene.get("id"), f"{episode_id}_scene_{index + 1}")
    scene.update({
        "id": scene_id,
        "order": _integer(scene.get("order"), index + 1, 1),
        "locationId": _text(scene.get("locationId")),
        "time": _text(scene.get("time")),
        "participatingCharacterIds": _unique_ids(scene.get("participatingCharacterIds")),
        "purpose": _text(scene.get("purpose")),
        "entryState": _text(scene.get("entryState")),
        "exitState": _text(scene.get("exitState")),
        "beats": _objects(scene.get("beats")),
        "dialogue": [
            _normalize_dialogue_beat(item, f"{scene_id}_dialogue_{dialogue_index + 1}")
            for dialogue_index, item in enumerate(_objects(scene.get("dialogue")))
        ],
    })
    for beat_index, beat in enumerate(scene["beats"]):
        beat["id"] = _id(beat.get("id"), f"{scene_id}_beat_{beat_index + 1}")
        beat["kind"] = "dialogue" if beat.get("kind") == "dialogue" else "action"
        beat["summary"] = _text(beat.get("summary"))
    return scene


def _unique_runtime_id(candidate: str, used: set[str], fallback: str) -> str:
    """Repair legacy copied dialogue IDs without creating unstable random IDs."""
    value = candidate.strip() if isinstance(candidate, str) else ""
    if value and value not in used:
        used.add(value)
        return value
    value = fallback
    suffix = 2
    while value in used:
        value = f"{fallback}_{suffix}"
        suffix += 1
    used.add(value)
    return value


def _normalize_episode(value: dict, key: str, index: int, season_id: str, canon: dict) -> dict:
    now = _now()
    episode = copy.deepcopy(value)
    episode_id = _id(episode.get("id"), key or f"episode_{index + 1}")
    snapshot = copy.deepcopy(episode.get("canonSnapshot")) \
        if isinstance(episode.get("canonSnapshot"), dict) else {}
    snapshot.setdefault("revision", _integer(episode.get("canonRevisionAtCreation"), canon["revision"]))
    snapshot.setdefault("worldSummary", canon["worldSummary"])
    snapshot.setdefault("immutableRules", copy.deepcopy(canon["immutableRules"]))
    snapshot.setdefault("currentFacts", copy.deepcopy(canon["currentFacts"]))
    for state_key in ("characterStates", "relationshipStates", "locationStates", "propStates"):
        snapshot.setdefault(state_key, {})
    script = [
        _normalize_scene(item, episode_id, scene_index)
        for scene_index, item in enumerate(_objects(episode.get("script")))
    ]
    shots = [
        _normalize_shot(item, shot_index)
        for shot_index, item in enumerate(_objects(episode.get("shots")))
    ]
    # Older planner responses sometimes copied IDs when a scene was expanded or
    # repeated. Repair those IDs in document order so the first occurrence keeps
    # its stable identifier and every later occurrence gets an episode-scoped ID.
    # This makes loading old libraries safe while the graph validator below still
    # rejects ambiguous IDs in every other live collection.
    used_runtime_ids: set[str] = set()
    scene_id_remap: dict[str, str] = {}
    for scene_index, scene in enumerate(script):
        original_scene_id = str(scene.get("id") or "")
        scene["id"] = _unique_runtime_id(
            original_scene_id, used_runtime_ids,
            f"{episode_id}_scene_{scene_index + 1}",
        )
        scene_id_remap.setdefault(original_scene_id, scene["id"])
        for beat_index, beat in enumerate(scene.get("beats", [])):
            beat["id"] = _unique_runtime_id(
                str(beat.get("id") or ""), used_runtime_ids,
                f"{scene['id']}_beat_{beat_index + 1}",
            )
        for dialogue_index, beat in enumerate(scene.get("dialogue", [])):
            beat["id"] = _unique_runtime_id(
                str(beat.get("id") or ""), used_runtime_ids,
                f"{scene['id']}_dialogue_{dialogue_index + 1}",
            )

    shot_id_remap: dict[str, str] = {}
    for shot_index, shot in enumerate(shots):
        original_shot_id = str(shot.get("id") or "")
        shot["id"] = _unique_runtime_id(
            original_shot_id, used_runtime_ids,
            f"{episode_id}_shot_{shot_index + 1}",
        )
        shot_id_remap.setdefault(original_shot_id, shot["id"])
        original_scene_id = str(shot.get("sceneId") or "")
        shot["sceneId"] = scene_id_remap.get(original_scene_id, original_scene_id)
        for dialogue_index, beat in enumerate(shot.get("dialogueBeats", [])):
            beat["id"] = _unique_runtime_id(
                str(beat.get("id") or ""), used_runtime_ids,
                f"{shot['id']}_dialogue_{dialogue_index + 1}",
            )
        approved_attempt_id = str(shot.get("approvedAttemptId") or "")
        approved_replacement = ""
        for attempt_index, attempt in enumerate(shot.get("attempts", [])):
            original_attempt_id = str(attempt.get("id") or "")
            attempt["id"] = _unique_runtime_id(
                original_attempt_id, used_runtime_ids,
                f"{shot['id']}_attempt_{attempt_index + 1}",
            )
            if original_attempt_id == approved_attempt_id and not approved_replacement:
                approved_replacement = attempt["id"]
        if approved_attempt_id:
            shot["approvedAttemptId"] = approved_replacement or approved_attempt_id
    for shot in shots:
        continuity_id = str(shot.get("continuityFromShotId") or "")
        if continuity_id:
            shot["continuityFromShotId"] = shot_id_remap.get(continuity_id, continuity_id)
    episode.update({
        "id": episode_id,
        "seasonId": _id(episode.get("seasonId"), season_id),
        "number": _integer(episode.get("number"), index + 1, 1),
        "title": _text(episode.get("title"), f"Episode {index + 1}"),
        "premise": _text(episode.get("premise")),
        "logline": _text(episode.get("logline")),
        "targetDurationSeconds": max(15, min(3600, _integer(episode.get("targetDurationSeconds"), 75, 15))),
        "status": episode.get("status") if episode.get("status") in {
            "draft", "outline", "script", "shot_plan", "rendering", "completed", "archived"
        } else "draft",
        "canonRevisionAtCreation": _integer(
            episode.get("canonRevisionAtCreation"), snapshot["revision"]
        ),
        "canonSnapshot": snapshot,
        "outline": copy.deepcopy(episode.get("outline"))
        if isinstance(episode.get("outline"), dict) else {"beats": []},
        "script": script,
        "shots": shots,
        "proposedCanonDelta": copy.deepcopy(episode.get("proposedCanonDelta"))
        if isinstance(episode.get("proposedCanonDelta"), dict) else {
            "baseRevision": snapshot["revision"], "sourceEpisodeId": episode_id,
            "add": [], "change": [], "retire": [],
        },
        "productionIds": _unique_ids(episode.get("productionIds")),
        "createdAt": _text(episode.get("createdAt"), now),
        "updatedAt": _text(episode.get("updatedAt"), now),
    })
    return episode


def _validate_project_graph_ids(project: dict) -> None:
    """Reject ambiguous IDs and references that would corrupt the live graph."""
    seen: dict[str, str] = {}

    def register(item: dict, path: str) -> None:
        item_id = _id(item.get("id"))
        previous = seen.get(item_id)
        if previous is not None:
            raise ValueError(
                f"Series Lab contains duplicate id {item_id} at {previous} and {path}"
            )
        seen[item_id] = path

    def require_known(value: Any, known: set[str], path: str, kind: str, *, optional: bool = False) -> None:
        item_id = str(value or "").strip()
        if optional and not item_id:
            return
        if item_id not in known:
            raise ValueError(f"{path} references unknown {kind} {item_id or '<empty>'}")

    register(project, "series")
    for collection in ("characters", "relationships", "locations", "props", "seasons"):
        for index, item in enumerate(_objects(project.get(collection))):
            register(item, f"{collection}[{index}]")
            for variants_key in ("wardrobeVariants", "variants"):
                for variant_index, variant in enumerate(_objects(item.get(variants_key))):
                    register(variant, f"{collection}[{index}].{variants_key}[{variant_index}]")
    character_ids = {str(item["id"]) for item in _objects(project.get("characters"))}
    location_ids = {str(item["id"]) for item in _objects(project.get("locations"))}
    prop_ids = {str(item["id"]) for item in _objects(project.get("props"))}
    season_ids = {str(item["id"]) for item in _objects(project.get("seasons"))}
    for index, relationship in enumerate(_objects(project.get("relationships"))):
        require_known(
            relationship.get("fromCharacterId"), character_ids,
            f"relationships[{index}].fromCharacterId", "character",
        )
        require_known(
            relationship.get("toCharacterId"), character_ids,
            f"relationships[{index}].toCharacterId", "character",
        )
    for index, prop in enumerate(_objects(project.get("props"))):
        require_known(
            prop.get("ownerCharacterId"), character_ids,
            f"props[{index}].ownerCharacterId", "character", optional=True,
        )
    canon = project.get("canon") if isinstance(project.get("canon"), dict) else {}
    for collection in ("immutableRules", "currentFacts", "longArcs", "timeline"):
        for index, item in enumerate(_objects(canon.get(collection))):
            register(item, f"canon.{collection}[{index}]")
    for episode_index, episode in enumerate(
        item for item in project.get("episodesById", {}).values() if isinstance(item, dict)
    ):
        register(episode, f"episodes[{episode_index}]")
        require_known(
            episode.get("seasonId"), season_ids,
            f"episodes[{episode_index}].seasonId", "season",
        )
        scene_ids: set[str] = set()
        for scene_index, scene in enumerate(_objects(episode.get("script"))):
            register(scene, f"episodes[{episode_index}].script[{scene_index}]")
            scene_ids.add(str(scene["id"]))
            require_known(
                scene.get("locationId"), location_ids,
                f"episodes[{episode_index}].script[{scene_index}].locationId",
                "location", optional=True,
            )
            for participant_index, character_id in enumerate(scene.get("participatingCharacterIds", [])):
                require_known(
                    character_id, character_ids,
                    f"episodes[{episode_index}].script[{scene_index}].participatingCharacterIds[{participant_index}]",
                    "character",
                )
            for beat_index, beat in enumerate(_objects(scene.get("beats"))):
                register(beat, f"episodes[{episode_index}].script[{scene_index}].beats[{beat_index}]")
            for line_index, line in enumerate(_objects(scene.get("dialogue"))):
                register(line, f"episodes[{episode_index}].script[{scene_index}].dialogue[{line_index}]")
                require_known(
                    line.get("characterId"), character_ids,
                    f"episodes[{episode_index}].script[{scene_index}].dialogue[{line_index}].characterId",
                    "character",
                )
        shot_ids = {
            str(shot.get("id")) for shot in _objects(episode.get("shots"))
            if shot.get("id")
        }
        for shot_index, shot in enumerate(_objects(episode.get("shots"))):
            register(shot, f"episodes[{episode_index}].shots[{shot_index}]")
            if shot.get("sceneId") not in scene_ids:
                raise ValueError(
                    f"Shot {shot.get('id')} uses unknown scene {shot.get('sceneId')}"
                )
            for key in ("visibleCharacterIds", "speakingCharacterIds"):
                for character_index, character_id in enumerate(shot.get(key, [])):
                    require_known(
                        character_id, character_ids,
                        f"episodes[{episode_index}].shots[{shot_index}].{key}[{character_index}]",
                        "character",
                    )
            require_known(
                shot.get("primarySpeakerId"), character_ids,
                f"episodes[{episode_index}].shots[{shot_index}].primarySpeakerId",
                "character", optional=True,
            )
            require_known(
                shot.get("locationId"), location_ids,
                f"episodes[{episode_index}].shots[{shot_index}].locationId",
                "location", optional=True,
            )
            for prop_index, prop_id in enumerate(shot.get("propIds", [])):
                require_known(
                    prop_id, prop_ids,
                    f"episodes[{episode_index}].shots[{shot_index}].propIds[{prop_index}]",
                    "prop",
                )
            for key in ("wardrobeByCharacterId", "emotionalStateByCharacterId"):
                values = shot.get(key) if isinstance(shot.get(key), dict) else {}
                for character_id in values:
                    require_known(
                        character_id, character_ids,
                        f"episodes[{episode_index}].shots[{shot_index}].{key}",
                        "character",
                    )
            require_known(
                shot.get("continuityFromShotId"), shot_ids,
                f"episodes[{episode_index}].shots[{shot_index}].continuityFromShotId",
                "shot", optional=True,
            )
            attempt_ids: set[str] = set()
            for line_index, line in enumerate(_objects(shot.get("dialogueBeats"))):
                register(line, f"episodes[{episode_index}].shots[{shot_index}].dialogue[{line_index}]")
                require_known(
                    line.get("characterId"), character_ids,
                    f"episodes[{episode_index}].shots[{shot_index}].dialogue[{line_index}].characterId",
                    "character",
                )
            for attempt_index, attempt in enumerate(_objects(shot.get("attempts"))):
                register(attempt, f"episodes[{episode_index}].shots[{shot_index}].attempts[{attempt_index}]")
                attempt_ids.add(str(attempt["id"]))
            approved_attempt_id = str(shot.get("approvedAttemptId") or "")
            if approved_attempt_id and approved_attempt_id not in attempt_ids:
                raise ValueError(
                    f"Shot {shot.get('id')} approves unknown attempt {approved_attempt_id}"
                )
    for asset_index, asset in enumerate(
        item for item in project.get("assets", {}).values() if isinstance(item, dict)
    ):
        register(asset, f"assets[{asset_index}]")
    asset_ids = {
        str(asset["id"])
        for asset in project.get("assets", {}).values()
        if isinstance(asset, dict)
    }
    owner_ids = {
        "series": {str(project["id"])},
        "character": character_ids,
        "location": location_ids,
        "prop": prop_ids,
        "episode": {
            str(episode["id"]) for episode in project.get("episodesById", {}).values()
            if isinstance(episode, dict)
        },
        "shot": {
            str(shot["id"])
            for episode in project.get("episodesById", {}).values() if isinstance(episode, dict)
            for shot in _objects(episode.get("shots"))
        },
        "attempt": {
            str(attempt["id"])
            for episode in project.get("episodesById", {}).values() if isinstance(episode, dict)
            for shot in _objects(episode.get("shots"))
            for attempt in _objects(shot.get("attempts"))
        },
    }
    for asset_index, asset in enumerate(
        item for item in project.get("assets", {}).values() if isinstance(item, dict)
    ):
        owner_type = str(asset.get("ownerType") or "series")
        require_known(
            asset.get("ownerId"), owner_ids.get(owner_type, set()),
            f"assets[{asset_index}].ownerId", owner_type,
        )
    for collection in ("characters", "locations", "props"):
        for entity_index, entity in enumerate(_objects(project.get(collection))):
            for reference_index, asset_id in enumerate(entity.get("referenceAssetIds", [])):
                require_known(
                    asset_id, asset_ids,
                    f"{collection}[{entity_index}].referenceAssetIds[{reference_index}]",
                    "asset",
                )
    for episode_index, episode in enumerate(
        item for item in project.get("episodesById", {}).values() if isinstance(item, dict)
    ):
        for shot_index, shot in enumerate(_objects(episode.get("shots"))):
            policy = shot.get("referencePolicy") if isinstance(shot.get("referencePolicy"), dict) else {}
            for key in ("manualIncludeAssetIds", "manualExcludeAssetIds"):
                for reference_index, asset_id in enumerate(policy.get(key, [])):
                    require_known(
                        asset_id, asset_ids,
                        f"episodes[{episode_index}].shots[{shot_index}].referencePolicy.{key}[{reference_index}]",
                        "asset",
                    )
            for attempt_index, attempt in enumerate(_objects(shot.get("attempts"))):
                for output_index, asset_id in enumerate(attempt.get("outputAssetIds", [])):
                    require_known(
                        asset_id, asset_ids,
                        f"episodes[{episode_index}].shots[{shot_index}].attempts[{attempt_index}].outputAssetIds[{output_index}]",
                        "asset",
                    )


def normalize_series_project(value: Any, key: str, workspace_id: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Every Series Lab project must be a JSON object")
    project = copy.deepcopy(value)
    series_id = _id(project.get("id"), key)
    now = _now()
    canon = _normalize_canon(project.get("canon"))

    characters = [
        _normalize_entity(item, "character", index, {
            "name": f"Character {index + 1}", "aliases": [], "role": "",
            "personality": "", "desire": "", "need": "", "flaw": "",
            "longArc": "", "voiceAndDialogue": "", "appearance": "",
            "identityLock": "", "wardrobeVariants": [], "referenceAssetIds": [],
            "currentState": {}, "approval": "draft",
        }) for index, item in enumerate(_objects(project.get("characters")))
    ]
    locations = [
        _normalize_entity(item, "location", index, {
            "name": f"Location {index + 1}", "purpose": "", "description": "",
            "referenceAssetIds": [], "variants": [], "currentState": {}, "approval": "draft",
        }) for index, item in enumerate(_objects(project.get("locations")))
    ]
    props = [
        _normalize_entity(item, "prop", index, {
            "name": f"Prop {index + 1}", "kind": "", "description": "",
            "ownerCharacterId": "", "referenceAssetIds": [], "variants": [],
            "currentState": {}, "approval": "draft",
        }) for index, item in enumerate(_objects(project.get("props")))
    ]
    seasons = [
        _normalize_entity(item, "season", index, {
            "number": index + 1, "title": f"Season {index + 1}", "premise": "",
            "arc": "", "episodeOrder": [], "createdAt": now, "updatedAt": now,
        }) for index, item in enumerate(_objects(project.get("seasons")))
    ]
    if not seasons:
        seasons = [_normalize_entity({}, "season", 0, {
            "number": 1, "title": "Season 1", "premise": "", "arc": "",
            "episodeOrder": [], "createdAt": now, "updatedAt": now,
        })]
    season_ids = {item["id"] for item in seasons}
    default_season_id = seasons[0]["id"]

    episodes: dict[str, dict] = {}
    raw_episodes = project.get("episodesById") if isinstance(project.get("episodesById"), dict) else {}
    for index, (episode_key, raw_episode) in enumerate(raw_episodes.items()):
        if not isinstance(raw_episode, dict):
            continue
        episode = _normalize_episode(raw_episode, str(episode_key), index, default_season_id, canon)
        if episode["seasonId"] not in season_ids:
            episode["seasonId"] = default_season_id
        episodes[episode["id"]] = episode

    # episodeOrder is repaired deterministically: retain valid order, then append
    # every orphaned episode by number/id. No episode is discarded.
    for season in seasons:
        valid = [
            episode_id for episode_id in _unique_ids(season.get("episodeOrder"))
            if episode_id in episodes and episodes[episode_id]["seasonId"] == season["id"]
        ]
        missing = sorted(
            (item for item in episodes.values()
             if item["seasonId"] == season["id"] and item["id"] not in valid),
            key=lambda item: (item["number"], item["id"]),
        )
        season["episodeOrder"] = valid + [item["id"] for item in missing]

    raw_assets = project.get("assets") if isinstance(project.get("assets"), dict) else {}
    assets: dict[str, dict] = {}
    for index, (asset_key, raw_asset) in enumerate(raw_assets.items()):
        if not isinstance(raw_asset, dict):
            continue
        asset = _normalize_asset(raw_asset, series_id, workspace_id, index, str(asset_key))
        assets[asset["id"]] = asset
    provider = copy.deepcopy(project.get("provider")) if isinstance(project.get("provider"), dict) else {}
    video_settings = copy.deepcopy(provider.get("videoSettings")) \
        if isinstance(provider.get("videoSettings"), dict) else {}
    raw_resolution = str(video_settings.get("resolution") or "540p").strip().lower()
    provider_was_present = isinstance(project.get("provider"), dict)
    video_settings.update({
        "renderStrategy": video_settings.get("renderStrategy")
        if video_settings.get("renderStrategy") in {"auto", "direct", "first_frame", "references", "first_last"}
        else "auto",
        "resolution": "768p" if raw_resolution in {
            "768", "768p", "1344x768", "768x1344"
        } else "720p" if raw_resolution in {
            "720", "720p", "1280x720", "1280x704", "720x1280", "704x1280"
        } else "540p" if raw_resolution in {
            "540", "540p", "960x544", "544x960"
        } else "480p",
        "orientation": "portrait" if str(video_settings.get("orientation") or "").lower() in {
            "portrait", "vertical", "9:16"
        } else "landscape",
        "numInferenceSteps": max(1, min(50, _integer(video_settings.get("numInferenceSteps"), 20, 1))),
    })
    provider.update({
        "useGlobalProfile": provider.get("useGlobalProfile") is True
        if provider_was_present else False,
        "writingProvider": _text(provider.get("writingProvider"), "maestro"),
        "writingModel": _text(provider.get("writingModel")),
        "imageProvider": _text(provider.get("imageProvider"), "maestro"),
        "imageModel": _text(provider.get("imageModel")),
        "videoModel": "minimax_h3" if _text(provider.get("videoModel"), "minimax_h3_legacy") == "minimax-h3"
        else _text(provider.get("videoModel"), "minimax_h3_legacy"),
        "videoSettings": video_settings,
    })
    import_source = copy.deepcopy(project.get("importSource")) \
        if isinstance(project.get("importSource"), dict) else {}
    import_source.update({
        "kind": "story_import" if import_source.get("kind") == "story_import" else "original",
        "sourceWorkspaceId": import_source.get("sourceWorkspaceId")
        if isinstance(import_source.get("sourceWorkspaceId"), str) else None,
        "sourceStoryId": import_source.get("sourceStoryId")
        if isinstance(import_source.get("sourceStoryId"), str) else None,
        "importedAt": _text(import_source.get("importedAt"), now),
        "historicalProductionIds": _unique_ids(import_source.get("historicalProductionIds")),
        "migrationNotes": _text(import_source.get("migrationNotes")),
    })
    project.update({
        "version": 1,
        "id": series_id,
        "revision": _integer(project.get("revision"), 1, 1),
        "title": _text(project.get("title"), "Untitled series"),
        "logline": _text(project.get("logline")),
        "premise": _text(project.get("premise")),
        "format": project.get("format") if project.get("format") in {"serial", "episodic", "hybrid"} else "episodic",
        "defaultEpisodeDurationSeconds": max(15, min(3600, _integer(
            project.get("defaultEpisodeDurationSeconds"), 75, 15
        ))),
        "language": _text(project.get("language"), "Español"),
        "spokenLanguage": _text(
            project.get("spokenLanguage"), _text(project.get("language"), "Español de España")
        ),
        "protagonistConsistency": project.get("protagonistConsistency") is True,
        "protagonistCharacterId": (
            _text(project.get("protagonistCharacterId"))
            if any(item.get("id") == project.get("protagonistCharacterId") for item in characters)
            else ""
        ),
        "genre": _text(project.get("genre")),
        "tone": _text(project.get("tone")),
        "audience": _text(project.get("audience"), "General"),
        "visualStyle": _text(project.get("visualStyle")),
        "characterVisualStyle": _text(project.get("characterVisualStyle")),
        "cameraLanguage": _text(project.get("cameraLanguage")),
        "allowClipText": project.get("allowClipText") is True,
        "sourceMode": project.get("sourceMode") if project.get("sourceMode") in {
            "original", "known_universe_experimental", "hybrid"
        } else "original",
        "masterUniversePrompt": _text(project.get("masterUniversePrompt")),
        "rightsNote": _text(project.get("rightsNote")),
        "bestEffortLipSyncAcknowledged": project.get("bestEffortLipSyncAcknowledged") is True,
        "importSource": import_source,
        "canon": canon,
        "characters": characters,
        "relationships": _objects(project.get("relationships")),
        "locations": locations,
        "props": props,
        "seasons": seasons,
        "episodesById": episodes,
        "assets": assets,
        "provider": provider,
        "createdAt": _text(project.get("createdAt"), now),
        "updatedAt": _text(project.get("updatedAt"), now),
    })
    _validate_project_graph_ids(project)
    return project


def normalize_series_library(value: Any, workspace_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Series library must be a JSON object")
    authoritative_workspace = validate_workspace_id(workspace_id or value.get("workspaceId") or "default")
    payload_workspace = validate_workspace_id(value.get("workspaceId") or authoritative_workspace)
    if workspace_id is not None and payload_workspace != authoritative_workspace:
        raise ValueError("Series library workspaceId does not match the requested workspace")
    raw_projects = value.get("seriesById")
    if not isinstance(raw_projects, dict):
        raise ValueError("Series library seriesById must be an object")
    if len(raw_projects) > MAX_SERIES_PROJECTS:
        raise ValueError(f"Series library is limited to {MAX_SERIES_PROJECTS} projects")

    projects: dict[str, dict] = {}
    for key, raw_project in raw_projects.items():
        project = normalize_series_project(raw_project, str(key), authoritative_workspace)
        if project["id"] in projects:
            raise ValueError(f"Series library contains duplicate project id {project['id']}")
        projects[project["id"]] = project
    order = [item for item in _unique_ids(value.get("seriesOrder")) if item in projects]
    order.extend(item for item in projects if item not in order)
    result = copy.deepcopy(value)
    result.update({
        "schema": "series-library",
        "version": 1,
        "workspaceId": authoritative_workspace,
        "seriesOrder": order,
        "seriesById": projects,
    })
    return result


def series_library_path(workspace_dir: str) -> str:
    return os.path.join(workspace_dir, SERIES_LIBRARY_FILENAME)


def read_series_library(workspace_dir: str, workspace_id: str = "default") -> dict[str, Any]:
    path = series_library_path(workspace_dir)
    if not os.path.isfile(path):
        return empty_series_library(workspace_id)
    with open(path, "r", encoding="utf-8") as handle:
        return normalize_series_library(json.load(handle), workspace_id)


def write_series_library(workspace_dir: str, value: Any, workspace_id: str = "default") -> dict[str, Any]:
    library = normalize_series_library(value, workspace_id)
    encoded = json.dumps(library, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_SERIES_LIBRARY_BYTES:
        raise ValueError("Series library is too large to save")
    os.makedirs(workspace_dir, exist_ok=True)
    path = series_library_path(workspace_dir)
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


def create_episode_canon_snapshot(series: dict) -> dict:
    canon = _normalize_canon(series.get("canon"))
    provider = copy.deepcopy(series.get("provider")) if isinstance(series.get("provider"), dict) else {}
    capability = copy.deepcopy(provider.get("videoCapabilities")) \
        if isinstance(provider.get("videoCapabilities"), dict) else {
            "model": _text(provider.get("videoModel"), "minimax_h3").replace("minimax-h3", "minimax_h3"),
            "family": "minimax_h3", "version": "unknown",
            "limits": {"image": 9, "video": 3, "audio": 3, "total": 12},
            "supportsFirstFrame": True, "supportsFirstLast": False,
            "supportsContinuation": True, "supportsNativeAudio": True,
        }
    raw_assets = series.get("assets") if isinstance(series.get("assets"), dict) else {}
    frozen_characters = [
        copy.deepcopy(item) for item in _objects(series.get("characters"))
        if item.get("approval") == "approved"
    ]
    frozen_locations = [
        copy.deepcopy(item) for item in _objects(series.get("locations"))
        if item.get("approval") == "approved"
    ]
    frozen_props = [
        copy.deepcopy(item) for item in _objects(series.get("props"))
        if item.get("approval") == "approved"
    ]
    approved_asset_ids: set[str] = set()
    for entity in [*frozen_characters, *frozen_locations, *frozen_props]:
        approved_asset_ids.update(_unique_ids(entity.get("referenceAssetIds")))
        primary = entity.get("primaryReferenceAssetId")
        if isinstance(primary, str) and primary:
            approved_asset_ids.add(primary)
        for variant in [*_objects(entity.get("wardrobeVariants")), *_objects(entity.get("variants"))]:
            approved_asset_ids.update(_unique_ids(variant.get("referenceAssetIds")))
    approved_assets = sorted(
        asset_id for asset_id in approved_asset_ids
        if isinstance(raw_assets.get(asset_id), dict) and not raw_assets[asset_id].get("isDerivedThumbnail")
    )
    return {
        "revision": canon["revision"],
        "worldSummary": canon["worldSummary"],
        "immutableRules": copy.deepcopy(canon["immutableRules"]),
        "currentFacts": copy.deepcopy(canon["currentFacts"]),
        "characters": frozen_characters,
        "relationships": copy.deepcopy(_objects(series.get("relationships"))),
        "locations": frozen_locations,
        "props": frozen_props,
        "characterStates": {
            item["id"]: copy.deepcopy(item.get("currentState") or {})
            for item in _objects(series.get("characters")) if item.get("id")
        },
        "relationshipStates": {
            item["id"]: _text(item.get("currentState"), _text(item.get("dynamic")))
            for item in _objects(series.get("relationships")) if item.get("id")
        },
        "locationStates": {
            item["id"]: copy.deepcopy(item.get("currentState") or {})
            for item in _objects(series.get("locations")) if item.get("id")
        },
        "propStates": {
            item["id"]: copy.deepcopy(item.get("currentState") or {})
            for item in _objects(series.get("props")) if item.get("id")
        },
        "sourceMode": series.get("sourceMode", "original"),
        "masterUniversePrompt": _text(series.get("masterUniversePrompt")),
        "rightsNote": _text(series.get("rightsNote")),
        "visualStyle": _text(series.get("visualStyle")),
        "characterVisualStyle": _text(series.get("characterVisualStyle")),
        "cameraLanguage": _text(series.get("cameraLanguage")),
        "spokenLanguage": _text(series.get("spokenLanguage"), _text(series.get("language"))),
        "protagonistConsistency": series.get("protagonistConsistency") is True,
        "protagonistCharacterId": _text(series.get("protagonistCharacterId")),
        "allowClipText": series.get("allowClipText") is True,
        "provider": provider,
        "capabilitySnapshot": capability,
        "approvedReferenceAssetIds": approved_assets,
        "assets": {
            asset_id: copy.deepcopy(raw_assets[asset_id]) for asset_id in approved_assets
        },
    }


def series_for_episode_snapshot(series: dict, episode: dict) -> dict:
    """Overlay immutable episode canon onto live storage while retaining new shot outputs."""
    result = copy.deepcopy(series)
    snapshot = episode.get("canonSnapshot") if isinstance(episode.get("canonSnapshot"), dict) else {}
    for key in (
        "sourceMode", "masterUniversePrompt", "rightsNote", "visualStyle",
        "characterVisualStyle", "cameraLanguage", "allowClipText", "provider",
        "characters", "relationships", "locations", "props",
    ):
        if key in snapshot:
            result[key] = copy.deepcopy(snapshot[key])
    frozen_assets = snapshot.get("assets") if isinstance(snapshot.get("assets"), dict) else None
    live_assets = series.get("assets") if isinstance(series.get("assets"), dict) else {}
    if frozen_assets is None:
        approved_ids = set(_unique_ids(snapshot.get("approvedReferenceAssetIds")))
        frozen_assets = {
            asset_id: copy.deepcopy(asset) for asset_id, asset in live_assets.items()
            if asset_id in approved_ids and isinstance(asset, dict)
        }
    assets = copy.deepcopy(frozen_assets)
    episode_attempt_ids = {
        str(attempt.get("id"))
        for shot in _objects(episode.get("shots"))
        for attempt in _objects(shot.get("attempts")) if attempt.get("id")
    }
    episode_shot_ids = {
        str(shot.get("id")) for shot in _objects(episode.get("shots")) if shot.get("id")
    }
    for asset_id, asset in live_assets.items():
        if not isinstance(asset, dict):
            continue
        if (
            asset.get("ownerType") == "shot" and str(asset.get("ownerId")) in episode_shot_ids
        ) or (
            asset.get("ownerType") == "attempt" and str(asset.get("ownerId")) in episode_attempt_ids
        ):
            assets[asset_id] = copy.deepcopy(asset)
    result["assets"] = assets
    result["canon"] = {
        **copy.deepcopy(result.get("canon") or {}),
        "worldSummary": copy.deepcopy(snapshot.get("worldSummary", result.get("canon", {}).get("worldSummary", ""))),
        "immutableRules": copy.deepcopy(snapshot.get("immutableRules", result.get("canon", {}).get("immutableRules", []))),
        "currentFacts": copy.deepcopy(snapshot.get("currentFacts", result.get("canon", {}).get("currentFacts", []))),
        "revision": int(snapshot.get("revision") or episode.get("canonRevisionAtCreation") or 1),
    }
    return result


def create_series_episode(series: dict, season_id: str | None = None, **overrides: Any) -> dict:
    """Create a draft episode with an immutable snapshot of current approved canon."""
    seasons = _objects(series.get("seasons"))
    if not seasons:
        raise ValueError("Create a season before adding an episode")
    season = next((item for item in seasons if item.get("id") == season_id), seasons[0])
    episodes = series.get("episodesById") if isinstance(series.get("episodesById"), dict) else {}
    season_episodes = [
        item for item in episodes.values()
        if isinstance(item, dict) and item.get("seasonId") == season.get("id")
    ]
    now = _now()
    episode_id = _new_uid("episode")
    snapshot = create_episode_canon_snapshot(series)
    episode = {
        "id": episode_id, "seasonId": str(season["id"]),
        "number": max([_integer(item.get("number"), 0) for item in season_episodes] + [0]) + 1,
        "title": f"Episode {len(season_episodes) + 1}", "premise": "", "logline": "",
        "targetDurationSeconds": _integer(series.get("defaultEpisodeDurationSeconds"), 75, 15),
        "status": "draft", "canonRevisionAtCreation": snapshot["revision"],
        "canonSnapshot": snapshot, "outline": {"beats": []}, "script": [], "shots": [],
        "proposedCanonDelta": {
            "baseRevision": snapshot["revision"], "sourceEpisodeId": episode_id,
            "add": [], "change": [], "retire": [],
        },
        "productionIds": [], "createdAt": now, "updatedAt": now,
    }
    for key, value in overrides.items():
        if key not in {"id", "seasonId", "canonRevisionAtCreation", "canonSnapshot", "createdAt"}:
            episode[key] = copy.deepcopy(value)
    return _normalize_episode(
        episode, episode_id, len(season_episodes), str(season["id"]),
        _normalize_canon(series.get("canon")),
    )


def import_story_project(story: dict, workspace_id: str = "default") -> dict:
    """Create a new draft series without mutating its Story Lab source."""
    if not isinstance(story, dict):
        raise ValueError("Story import requires one Story Lab project")
    now = _now()
    suffix = uuid.uuid4().hex
    series_id = f"series_{suffix}"
    story_assets = story.get("assets") if isinstance(story.get("assets"), dict) else {}
    assets: dict[str, dict] = {}
    valid_asset_ids: set[str] = set()
    for asset_key, raw in story_assets.items():
        if not isinstance(raw, dict):
            continue
        source = _text(raw.get("source"))
        # Story sources served by Maestro are normalized into workspace paths.
        if source.startswith("/api/v1/file/"):
            source = f"outputs/{source.rsplit('/', 1)[-1]}"
        elif source.startswith("/api/v1/output/"):
            source = f"outputs/{source.rsplit('/', 1)[-1]}"
        try:
            uri = validate_series_asset_uri(source)
        except ValueError:
            continue
        asset_id = _id(raw.get("id"), str(asset_key))
        valid_asset_ids.add(asset_id)
        assets[asset_id] = {
            "id": asset_id, "workspaceId": workspace_id,
            "kind": "image", "uri": uri, "ownerType": "series", "ownerId": series_id,
            "isDerivedThumbnail": False,
            "metadata": {
                "name": _text(raw.get("name"), asset_id),
                "prompt": _text(raw.get("prompt")), "provider": _text(raw.get("provider")),
                "sourceStoryAssetId": asset_id,
            },
        }
    characters = []
    for index, raw in enumerate(_objects(story.get("characters"))):
        refs = [item for item in _unique_ids(raw.get("referenceAssetIds")) if item in valid_asset_ids]
        primary = raw.get("primaryReferenceAssetId") if raw.get("primaryReferenceAssetId") in refs else None
        characters.append({
            "id": _id(raw.get("id"), f"character_{index + 1}"),
            "name": _text(raw.get("name"), f"Character {index + 1}"),
            "aliases": [], "role": _text(raw.get("role")),
            "personality": _text(raw.get("personality")), "desire": _text(raw.get("desire")),
            "need": _text(raw.get("need")), "flaw": _text(raw.get("flaw")),
            "longArc": _text(raw.get("arc")), "voiceAndDialogue": _text(raw.get("voice")),
            "appearance": _text(raw.get("appearance")),
            "identityLock": _text(raw.get("visualPrompt")),
            "wardrobeVariants": ([{
                "id": f"wardrobe_{index + 1}_default", "label": "Default",
                "description": _text(raw.get("wardrobe")), "referenceAssetIds": refs,
            }] if _text(raw.get("wardrobe")) else []),
            "referenceAssetIds": refs, "primaryReferenceAssetId": primary,
            "currentState": {}, "approval": "draft",
        })
    world = story.get("world") if isinstance(story.get("world"), dict) else {}
    locations = []
    for index, raw in enumerate(_objects(world.get("locations"))):
        refs = [item for item in _unique_ids(raw.get("referenceAssetIds")) if item in valid_asset_ids]
        locations.append({
            "id": _id(raw.get("id"), f"location_{index + 1}"),
            "name": _text(raw.get("name"), f"Location {index + 1}"),
            "purpose": _text(raw.get("purpose")), "description": _text(raw.get("description")),
            "referenceAssetIds": refs, "variants": [], "currentState": {}, "approval": "draft",
        })
    production_ids = [
        str(item.get("id")) for item in _objects(story.get("productions")) if item.get("id")
    ]
    world_rules = [
        {"id": f"rule_{index + 1}", "description": item, "status": "draft"}
        for index, item in enumerate(_unique_ids(world.get("rules")))
    ]
    series = {
        "version": 1, "id": series_id, "revision": 1,
        "title": _text(story.get("title"), "Imported series"),
        "logline": _text(story.get("logline")), "premise": _text(story.get("premise")),
        "format": "episodic",
        "defaultEpisodeDurationSeconds": max(60, min(90, _integer(
            (story.get("creativeBrief") or {}).get("durationSeconds")
            if isinstance(story.get("creativeBrief"), dict) else None, 75
        ))),
        "language": _text(story.get("language"), "Español"),
        "genre": _text(story.get("genre")), "tone": _text(story.get("tone")),
        "audience": _text(story.get("audience"), "General"),
        "visualStyle": _text(story.get("visualStyle")),
        "characterVisualStyle": _text(story.get("characterVisualStyle")),
        "cameraLanguage": "", "allowClipText": story.get("allowClipText") is True,
        "sourceMode": "original", "masterUniversePrompt": "",
        "rightsNote": "Imported from a user-owned Story Lab project; review rights before production.",
        "bestEffortLipSyncAcknowledged": False,
        "importSource": {
            "kind": "story_import", "sourceWorkspaceId": workspace_id,
            "sourceStoryId": _text(story.get("id")) or None, "importedAt": now,
            "historicalProductionIds": production_ids,
            "migrationNotes": "Story content imported as a new Series Lab draft. Source was not modified.",
        },
        "canon": {
            "worldSummary": _text(world.get("summary"), _text(story.get("synopsis"))),
            "immutableRules": world_rules, "currentFacts": [], "forbiddenChanges": [],
            "themes": [_text(story.get("theme"))] if _text(story.get("theme")) else [],
            "longArcs": [], "timeline": [], "revision": 1,
        },
        "characters": characters,
        "relationships": copy.deepcopy(story.get("relationships"))
        if isinstance(story.get("relationships"), list) else [],
        "locations": locations, "props": [],
        "seasons": [{
            "id": f"season_{suffix}_1", "number": 1, "title": "Season 1",
            "premise": _text(story.get("premise")), "arc": "", "episodeOrder": [],
            "createdAt": now, "updatedAt": now,
        }],
        "episodesById": {}, "assets": assets,
        "provider": {
            "useGlobalProfile": bool((story.get("provider") or {}).get("useGlobalProfile"))
            if isinstance(story.get("provider"), dict) else True,
            "writingProvider": _text((story.get("provider") or {}).get("writingProvider"), "maestro")
            if isinstance(story.get("provider"), dict) else "maestro",
            "writingModel": _text((story.get("provider") or {}).get("writingModel"))
            if isinstance(story.get("provider"), dict) else "",
            "writingBaseUrl": _text((story.get("provider") or {}).get("writingBaseUrl"))
            if isinstance(story.get("provider"), dict) else "",
            "imageProvider": _text((story.get("provider") or {}).get("imageProvider"), "maestro")
            if isinstance(story.get("provider"), dict) else "maestro",
            "imageModel": _text((story.get("provider") or {}).get("imageModel"))
            if isinstance(story.get("provider"), dict) else "",
            "videoModel": "minimax_h3_legacy", "videoSettings": {
                "renderStrategy": "auto", "resolution": "540p",
                "orientation": "landscape", "numInferenceSteps": 20,
                "flowShift": 12, "audioShift": 3, "modelProfile": "quality",
            },
        },
        "createdAt": now, "updatedAt": now,
    }
    return normalize_series_project(series, series_id, workspace_id)


def duplicate_series_project(series: dict) -> dict:
    duplicate = copy.deepcopy(series)
    now = _now()
    old_id = _id(duplicate.get("id"))
    new_id = _new_uid("series")
    duplicate.update({
        "id": new_id, "title": f"{_text(duplicate.get('title'), 'Untitled series')} (copy)",
        "revision": 1, "createdAt": now, "updatedAt": now,
    })
    duplicate["episodesById"] = {}
    duplicate_seasons = _objects(duplicate.get("seasons"))
    for season in duplicate_seasons:
        season["episodeOrder"] = []
        season["createdAt"] = now
        season["updatedAt"] = now
    duplicate["seasons"] = duplicate_seasons
    duplicate_assets = copy.deepcopy(duplicate.get("assets")) \
        if isinstance(duplicate.get("assets"), dict) else {}
    for asset in duplicate_assets.values():
        if not isinstance(asset, dict):
            continue
        if asset.get("ownerType") == "series" and asset.get("ownerId") == old_id:
            asset["ownerId"] = new_id
    duplicate["assets"] = duplicate_assets
    duplicate["importSource"] = {
        "kind": "original", "sourceWorkspaceId": None, "sourceStoryId": None,
        "importedAt": now, "historicalProductionIds": [],
        "migrationNotes": f"Duplicated from Series Lab project {old_id}; episodes and attempts were not copied.",
    }
    return duplicate


def _merge_episode_shot_patch(current_shots: Any, incoming_shots: Any) -> list[dict]:
    """Merge editable shot fields while retaining server-owned render history."""
    if not isinstance(incoming_shots, list):
        raise ValueError("Episode shots patch must be an array")
    current = _objects(current_shots)
    current_by_id = {
        str(shot.get("id")): shot for shot in current if isinstance(shot.get("id"), str)
    }
    incoming_by_id: dict[str, dict] = {}
    incoming_order: list[str] = []
    for raw_shot in incoming_shots:
        if not isinstance(raw_shot, dict):
            raise ValueError("Every episode shot patch must be an object")
        shot_id = _id(raw_shot.get("id"))
        if shot_id in incoming_by_id:
            raise ValueError(f"Episode shot patch contains duplicate id {shot_id}")
        incoming_by_id[shot_id] = raw_shot
        incoming_order.append(shot_id)

    def merge_one(shot_id: str, raw_shot: dict) -> dict:
        stored = current_by_id.get(shot_id)
        merged = copy.deepcopy(stored) if stored is not None else {"id": shot_id, "attempts": []}
        for key in SHOT_EDITOR_FIELDS:
            if key in raw_shot:
                merged[key] = copy.deepcopy(raw_shot[key])
        merged["id"] = shot_id
        if stored is not None:
            for key in SHOT_SERVER_FIELDS:
                if key in stored:
                    merged[key] = copy.deepcopy(stored[key])
                else:
                    merged.pop(key, None)
        else:
            merged["attempts"] = []
            merged.pop("approvedAttemptId", None)
            merged.pop("referenceManifest", None)
        return merged

    # A full collection can express ordering. A sparse patch updates shots in
    # place and cannot accidentally delete another shot (or its attempts).
    if set(current_by_id).issubset(incoming_by_id):
        return [merge_one(shot_id, incoming_by_id[shot_id]) for shot_id in incoming_order]
    result: list[dict] = []
    for stored in current:
        shot_id = str(stored.get("id") or "")
        result.append(
            merge_one(shot_id, incoming_by_id[shot_id])
            if shot_id in incoming_by_id else copy.deepcopy(stored)
        )
    result.extend(
        merge_one(shot_id, incoming_by_id[shot_id])
        for shot_id in incoming_order if shot_id not in current_by_id
    )
    return result


def update_series_episode(
    series: dict,
    episode_id: str,
    patch: dict,
    *,
    base_series_revision: Any = None,
    base_episode_updated_at: Any = None,
    updated_at: str | None = None,
) -> dict:
    """Apply an editor patch with optimistic concurrency and runtime ownership."""
    if not isinstance(series, dict) or not isinstance(patch, dict):
        raise ValueError("Series and episode patch are required")
    if base_series_revision is None and base_episode_updated_at is None:
        raise ValueError("baseSeriesRevision or baseEpisodeUpdatedAt is required")

    updated = copy.deepcopy(series)
    episodes = updated.get("episodesById")
    current = episodes.get(episode_id) if isinstance(episodes, dict) else None
    if not isinstance(current, dict):
        raise ValueError("Series episode not found")
    current_revision = _integer(updated.get("revision"), 1, 1)
    if base_series_revision is not None:
        try:
            requested_revision = int(base_series_revision)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("baseSeriesRevision must be an integer") from exc
        if requested_revision != current_revision:
            raise SeriesConflictError(
                f"Series revision changed from {requested_revision} to {current_revision}; reload before saving"
            )
    if (
        base_episode_updated_at is not None
        and str(base_episode_updated_at) != str(current.get("updatedAt") or "")
    ):
        raise SeriesConflictError(
            "Episode changed after it was loaded; reload before saving"
        )
    if patch.get("id") not in {None, "", episode_id}:
        raise ValueError("Episode id does not match the route")

    merged = copy.deepcopy(current)
    for key in EPISODE_EDITOR_FIELDS - {"shots"}:
        if key in patch:
            merged[key] = copy.deepcopy(patch[key])
    if "shots" in patch:
        merged["shots"] = _merge_episode_shot_patch(current.get("shots"), patch["shots"])

    # Every non-editor field remains authoritative, including status,
    # production/assembly assets, immutable canon and all unknown runtime data.
    now = updated_at or _now()
    merged["id"] = episode_id
    merged["updatedAt"] = now
    episodes[episode_id] = merged
    updated["episodesById"] = episodes
    updated["revision"] = current_revision + 1
    updated["updatedAt"] = now
    return updated


def commit_canon_delta(series: dict, episode_id: str, decisions: dict[str, str], base_revision: int) -> dict:
    """Apply only explicitly accepted delta items using optimistic locking."""
    updated = copy.deepcopy(series)
    canon = _normalize_canon(updated.get("canon"))
    if canon["revision"] != int(base_revision):
        raise SeriesConflictError(
            f"Canon revision changed from {base_revision} to {canon['revision']}; reload before committing"
        )
    episodes = updated.get("episodesById") if isinstance(updated.get("episodesById"), dict) else {}
    episode = episodes.get(episode_id)
    if not isinstance(episode, dict):
        raise ValueError("Series episode not found")
    delta = episode.get("proposedCanonDelta") if isinstance(episode.get("proposedCanonDelta"), dict) else {}
    if _integer(delta.get("baseRevision"), -1, -1) != int(base_revision):
        raise SeriesConflictError("Episode canon delta was created from a different canon revision")
    now = _now()
    facts = {item.get("id"): copy.deepcopy(item) for item in canon["currentFacts"] if item.get("id")}
    changed = False
    for group in ("add", "change"):
        items = _objects(delta.get(group))
        for index, item in enumerate(items):
            item_id = _text(item.get("id")).strip()
            decision = decisions.get(item_id, "pending")
            if decision not in {"accepted", "rejected", "pending"}:
                raise ValueError(f"Invalid canon decision for {item_id}")
            item["decision"] = decision
            if decision != "pending":
                item["decidedAt"] = now
            if decision == "accepted":
                facts[item_id] = {
                    **item, "status": "approved", "sourceEpisodeId": episode_id,
                }
                facts[item_id].pop("decision", None)
                facts[item_id].pop("decidedAt", None)
                changed = True
            items[index] = item
        delta[group] = items
    retire_items = _objects(delta.get("retire"))
    for index, item in enumerate(retire_items):
        fact_id = _text(item.get("factId")).strip()
        decision = decisions.get(fact_id, "pending")
        if decision not in {"accepted", "rejected", "pending"}:
            raise ValueError(f"Invalid canon decision for {fact_id}")
        item["decision"] = decision
        if decision != "pending":
            item["decidedAt"] = now
        if decision == "accepted" and fact_id in facts:
            facts[fact_id]["status"] = "retired"
            changed = True
        retire_items[index] = item
    delta["retire"] = retire_items
    episode["proposedCanonDelta"] = delta
    episode["updatedAt"] = now
    episodes[episode_id] = episode
    updated["episodesById"] = episodes
    if changed:
        canon["currentFacts"] = list(facts.values())
        canon["revision"] += 1
    updated["revision"] = _integer(updated.get("revision"), 1, 1) + 1
    updated["canon"] = canon
    updated["updatedAt"] = now
    return updated


def append_shot_render_attempt(
    shot: dict,
    *,
    manifest: dict,
    model: str,
    settings: dict,
    seed: int | None,
    retry_count: int = 0,
    prompt: str | None = None,
) -> tuple[dict, dict]:
    """Append a queued attempt; existing attempts and approved output stay intact."""
    updated = copy.deepcopy(shot)
    now = _now()
    attempt = {
        "id": _new_uid("attempt"), "status": "queued",
        "prompt": prompt if isinstance(prompt, str) else _text(updated.get("prompt")),
        "negativePrompt": _text(updated.get("negativePrompt")), "model": str(model),
        "referenceManifest": copy.deepcopy(manifest), "seed": seed,
        "settings": copy.deepcopy(settings), "startTimeSeconds": 0,
        "endTimeSeconds": float(updated.get("durationSeconds") or 0),
        "createdAt": now, "elapsedMs": 0, "outputAssetIds": [],
        "retryCount": max(0, int(retry_count)),
    }
    attempts = _objects(updated.get("attempts"))
    attempts.append(attempt)
    updated["attempts"] = attempts
    updated["referenceManifest"] = copy.deepcopy(manifest)
    return updated, copy.deepcopy(attempt)


def update_shot_render_attempt(shot: dict, attempt_id: str, **patch: Any) -> dict:
    updated = copy.deepcopy(shot)
    attempts = _objects(updated.get("attempts"))
    index = next((i for i, item in enumerate(attempts) if item.get("id") == attempt_id), None)
    if index is None:
        raise ValueError("Series shot render attempt not found")
    immutable = {"id", "createdAt", "prompt", "negativePrompt", "model", "referenceManifest", "seed", "settings"}
    for key, value in patch.items():
        if key not in immutable:
            attempts[index][key] = copy.deepcopy(value)
    updated["attempts"] = attempts
    return updated


def approve_shot_render_attempt(shot: dict, attempt_id: str) -> dict:
    updated = copy.deepcopy(shot)
    attempt = next((
        item for item in _objects(updated.get("attempts")) if item.get("id") == attempt_id
    ), None)
    if not attempt:
        raise ValueError("Series shot render attempt not found")
    if attempt.get("status") != "completed" or not attempt.get("outputAssetIds"):
        raise ValueError("Only a completed Series shot attempt with output can be approved")
    updated["approvedAttemptId"] = attempt_id
    updated = update_shot_render_attempt(
        updated, attempt_id, reviewDecision="approved", reviewedAt=_now(),
    )
    return updated


def approve_episode_render_attempts(episode: dict, selections: Any) -> dict:
    """Approve a reviewed episode selection atomically on a detached copy."""
    if not isinstance(selections, list) or not selections:
        raise ValueError("Select at least one completed Series shot attempt")
    if len(selections) > MAX_BULK_ATTEMPT_APPROVALS:
        raise ValueError(f"Bulk approval is limited to {MAX_BULK_ATTEMPT_APPROVALS} shots")
    updated = copy.deepcopy(episode)
    shots = _objects(updated.get("shots"))
    shot_indexes = {
        str(shot.get("id")): index for index, shot in enumerate(shots) if shot.get("id")
    }
    selected_shots: set[str] = set()
    for selection in selections:
        if not isinstance(selection, dict):
            raise ValueError("Every bulk approval selection must identify a shot and attempt")
        shot_id = _id(selection.get("shotId"))
        attempt_id = _id(selection.get("attemptId"))
        if shot_id in selected_shots:
            raise ValueError(f"Shot {shot_id} appears more than once in bulk approval")
        selected_shots.add(shot_id)
        shot_index = shot_indexes.get(shot_id)
        if shot_index is None:
            raise ValueError(f"Series shot {shot_id} not found")
        shots[shot_index] = approve_shot_render_attempt(shots[shot_index], attempt_id)
    updated["shots"] = shots
    return updated


def reject_shot_render_attempt(shot: dict, attempt_id: str) -> dict:
    updated = copy.deepcopy(shot)
    attempt = next((
        item for item in _objects(updated.get("attempts")) if item.get("id") == attempt_id
    ), None)
    if not attempt:
        raise ValueError("Series shot render attempt not found")
    updated = update_shot_render_attempt(
        updated, attempt_id, reviewDecision="rejected", reviewedAt=_now(),
    )
    if updated.get("approvedAttemptId") == attempt_id:
        updated.pop("approvedAttemptId", None)
    return updated
