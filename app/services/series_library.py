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

from .language_intent import normalize_language_intent


SERIES_LIBRARY_FILENAME = ".series-library-v1.json"
MAX_SERIES_PROJECTS = 100
MAX_SERIES_LIBRARY_BYTES = 100 * 1024 * 1024
MAX_BULK_ATTEMPT_APPROVALS = 500
_WORKSPACE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_ASSET_PATH = re.compile(r"^(assets|outputs)/[A-Za-z0-9._/-]+$")

EPISODE_EDITOR_FIELDS = frozenset({
    "seasonId", "number", "title", "premise", "logline",
    "targetDurationSeconds", "outline", "script", "shots",
    "continuityIssues", "proposedCanonDelta", "languageVersions", "score", "videoBudget",
    "kitPins",
})
SHOT_EDITOR_FIELDS = frozenset({
    "sceneId", "order", "durationSeconds", "framing", "camera", "action",
    "dialogueBeats", "visibleCharacterIds", "speakingCharacterIds",
    "primarySpeakerId", "locationId", "locationVariantId",
    "wardrobeByCharacterId", "propIds", "emotionalStateByCharacterId",
    "continuityFromShotId", "renderStrategy", "productionMethod", "referencePolicy", "prompt",
    "negativePrompt", "audioDirection", "sourceDialogueIds", "dialogueOrigin", "layout2d", "scene3d", "foley", "video",
    "transitionIn",
})
SHOT_SERVER_FIELDS = frozenset({"attempts", "approvedAttemptId", "referenceManifest"})
# A take is a render of what the audience sees and hears; when these change under a shot id, its takes are stale.
SHOT_CONTENT_FIELDS = frozenset({
    "dialogueBeats", "visibleCharacterIds", "locationId", "locationVariantId", "productionMethod",
    "framing", "camera", "layout2d", "scene3d", "wardrobeByCharacterId", "propIds", "video",
})
SERIES_CANON_INPUT_FIELDS = (
    "title", "premise", "logline", "format", "language", "spokenLanguage",
    "protagonistConsistency", "protagonistCharacterId", "genre", "tone", "audience",
    "visualStyle", "characterVisualStyle", "cameraLanguage", "sourceMode",
    "masterUniversePrompt", "characters", "relationships", "locations", "props",
)


class SeriesConflictError(ValueError):
    """Raised when an optimistic revision no longer matches stored state."""


class EpisodeNumberTaken(ValueError):
    """The series already has an episode with this number."""

    def __init__(self, number: int, holder_id: str) -> None:
        self.number = number
        self.holder_id = holder_id
        self.code = "episode_number_taken"
        super().__init__(f"Episode number {number} is already used by {holder_id}")


def require_episode_number(value: Any) -> int:
    """An explicit episode number: a real integer of 1 or more (a bool is not an integer)."""
    if type(value) is not int or value < 1:
        raise ValueError("Episode number must be an integer of 1 or more")
    return value


def episode_number_holder(episodes: Any, number: int, season_id: Any, except_id: str | None = None) -> str | None:
    """Id of the episode of season ``season_id`` that already uses ``number``, except ``except_id``.

    Numbers are per season (``create_series_episode`` counts them that way): season 2 has its own episode 1."""
    if not isinstance(episodes, dict):
        return None
    for episode_id, episode in episodes.items():
        if str(episode_id) == except_id or not isinstance(episode, dict) or episode.get("seasonId") != season_id:
            continue
        if episode.get("number") == number:
            return str(episode.get("id") or episode_id)
    return None


def assign_episode_number(series: dict, requested: int | None) -> int:
    """The next number, or ``requested`` when that integer is free in the season a new episode goes to (the first)."""
    episodes = series.get("episodesById") if isinstance(series.get("episodesById"), dict) else {}
    if requested is None:
        return max([item.get("number") or 0 for item in episodes.values() if isinstance(item, dict)] + [0]) + 1
    number = require_episode_number(requested)
    seasons = _objects(series.get("seasons"))
    holder = episode_number_holder(episodes, number, seasons[0].get("id") if seasons else None)
    if holder:
        raise EpisodeNumberTaken(number, holder)
    return number


def _guard_episode_number(episodes: Any, season_id: Any, patch: dict, episode_id: str | None = None) -> None:
    """Refuse an explicit number another episode of the season holds. Omitting it leaves the caller to assign one.

    Re-sending the episode's own number in its own season is not a change: the editor sends the whole episode on
    every save, and older episodes may already share a number."""
    if "number" not in patch:
        return
    current = episodes.get(episode_id) if episode_id and isinstance(episodes, dict) else None
    if isinstance(current, dict) and type(patch["number"]) is int and patch["number"] == current.get("number") \
            and season_id == current.get("seasonId"):
        return
    number = require_episode_number(patch["number"])
    holder = episode_number_holder(episodes, number, season_id, except_id=episode_id)
    if holder:
        raise EpisodeNumberTaken(number, holder)


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


# Per-entity fields that stage production (2D homes, prop anchors, 3D plates) rather than describe the world.
STAGING_FIELDS = frozenset({"layout2d"})


def _canon_input(series: dict, key: str) -> Any:
    value = series.get(key)
    if key in {"characters", "locations", "props"} and isinstance(value, list):
        return [{k: v for k, v in item.items() if k not in STAGING_FIELDS} if isinstance(item, dict) else item for item in value]
    return value


def series_canon_inputs_changed(current: dict, updated: dict) -> bool:
    """Compare durable production inputs without coupling canon to chat language."""
    current_canon = copy.deepcopy(current.get("canon") or {})
    updated_canon = copy.deepcopy(updated.get("canon") or {})
    for value in (current_canon, updated_canon):
        value.pop("approval", None)
        value.pop("approvedAt", None)
    if current_canon != updated_canon:
        return True
    if any(_canon_input(current, key) != _canon_input(updated, key) for key in SERIES_CANON_INPUT_FIELDS):
        return True
    current_intent = normalize_language_intent(current.get("languageIntent"))
    updated_intent = normalize_language_intent(updated.get("languageIntent"))
    current_intent.pop("conversationLanguage", None)
    updated_intent.pop("conversationLanguage", None)
    return current_intent != updated_intent


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
        "languageIntent": normalize_language_intent(
            None, content_language="Español", spoken_language="Español de España"
        ),
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
            "writingProvider": "maestro", "writingModel": "", "writingBaseUrl": "",
            "imageProvider": "maestro", "imageModel": "", "videoModel": "minimax_h3_legacy",
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
    # The room this one line is heard in (series_voice_rooms.line_rooms); null clears it, an unknown one is refused.
    if beat.get("voiceRoom") is None:
        beat.pop("voiceRoom", None)
    else:
        from services.series_voice_rooms import check_room
        check_room(beat["voiceRoom"], "dialogueBeats.voiceRoom")
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
    # How the server render made it for a staged review (series_review): a cheap preview or the final take.
    if attempt.get("reviewStage") not in {"preview", "final"}:
        attempt.pop("reviewStage", None)
    return attempt


def _normalize_shot(value: dict, index: int, allowed: list[str] | None = None) -> dict:
    from .series_render import normalize_series_shot_duration
    from .series_production import PRODUCTION_METHODS

    shot = copy.deepcopy(value)
    method = shot.get("productionMethod") or (allowed[0] if allowed else "generated_video")
    if method not in PRODUCTION_METHODS:
        raise ValueError("Unsupported Series shot production method")
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
        "productionMethod": method,
        "durationSeconds": float(normalize_series_shot_duration(shot.get("durationSeconds"))) if method == "generated_video"
        else min(600, _number(shot.get("durationSeconds"), 5, .1)),
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
    from .series_shot_plan import normalize_layout2d
    layout = normalize_layout2d(shot.get("layout2d"))
    if layout:
        shot["layout2d"] = layout
    else:
        shot.pop("layout2d", None)
    from .series_shot3d import normalize_scene3d
    scene3d = normalize_scene3d(shot.get("scene3d"))
    if scene3d:
        shot["scene3d"] = scene3d
    else:
        shot.pop("scene3d", None)
    from .series_shot_foley import normalize_foley
    foley = normalize_foley(shot.get("foley"))
    if foley:
        shot["foley"] = foley
    else:
        shot.pop("foley", None)
    from .series_transitions import normalize_transition
    if "transitionIn" in shot:
        transition = normalize_transition(shot.get("transitionIn"))
        if transition:
            shot["transitionIn"] = transition
        else:
            shot.pop("transitionIn", None)
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


def _normalize_episode(value: dict, key: str, index: int, season_id: str, canon: dict,
                       allowed: list[str] | None = None) -> dict:
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
        _normalize_shot(item, shot_index, allowed)
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
    # The episode's music, laid by the assembly (series_score): cues over runs of these shots, never overlapping.
    from .series_score import normalize_score
    score = normalize_score(episode.get("score"), shots)
    if score:
        episode["score"] = score
    else:
        episode.pop("score", None)
    # The staged review (series_review): mode, per-shot decisions on the current content, notes.
    from .series_review import normalize_episode_review
    normalize_episode_review(episode)
    from .series_kit_pins import normalize_kit_pins
    pins = normalize_kit_pins(episode.get("kitPins"))
    if pins:
        episode["kitPins"] = pins
    else:
        episode.pop("kitPins", None)
    from .series_shot_dialogue import annotate_episode_shot_dialogue
    return annotate_episode_shot_dialogue(episode)


def _normalize_episode_languages(episode: dict, project: dict) -> None:
    """Language versions of an episode (series_language_versions); empty ones are dropped."""
    from .series_language_versions import normalize_language_versions
    from .series_shot_plan import language_key
    versions = normalize_language_versions(episode.get("languageVersions"), episode.get("shots") or [], language_key(project))
    if versions:
        episode["languageVersions"] = versions
    else:
        episode.pop("languageVersions", None)


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


def series_put_payload(current: dict, sent: dict) -> dict:
    """The project a ``PUT /api/v1/series/{id}`` stores: what was sent, and the current value of every top-level field
    that was not. An agent that sent only ``allowedProductionMethods`` emptied the episodes, characters, locations
    and assets of a finished series. To clear a field, send it empty. Each episode keeps its stored review."""
    from .series_review import keep_stored_review
    payload = {**copy.deepcopy(current), **copy.deepcopy(sent)}
    keep_stored_review(current, payload)
    return payload


def normalize_series_project(value: Any, key: str, workspace_id: str) -> dict:
    from services.series_ambience import check_sound_design
    from services.series_layers import normalize_location
    from services.series_production import normalize_production_methods
    from services.series_voice_rooms import check_voice_rooms
    if not isinstance(value, dict):
        raise ValueError("Every Series Lab project must be a JSON object")
    check_sound_design(value.get("soundDesign"))
    check_voice_rooms(value.get("soundDesign"))
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
        normalize_location(_normalize_entity(item, "location", index, {
            "name": f"Location {index + 1}", "purpose": "", "description": "",
            "referenceAssetIds": [], "variants": [], "currentState": {}, "approval": "draft",
        }), f"locations[{index}].layout2d") for index, item in enumerate(_objects(project.get("locations")))
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
    allowed = normalize_production_methods(project.get("allowedProductionMethods"))

    episodes: dict[str, dict] = {}
    raw_episodes = project.get("episodesById") if isinstance(project.get("episodesById"), dict) else {}
    for index, (episode_key, raw_episode) in enumerate(raw_episodes.items()):
        if not isinstance(raw_episode, dict):
            continue
        episode = _normalize_episode(raw_episode, str(episode_key), index, default_season_id, canon, allowed)
        _normalize_episode_languages(episode, project)
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
        "allowedProductionMethods": allowed,
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
        "languageIntent": normalize_language_intent(
            project.get("languageIntent"),
            content_language=_text(project.get("language"), "Español"),
            spoken_language=_text(
                project.get("spokenLanguage"), _text(project.get("language"), "Español de España")
            ),
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
    synchronize_series_project_durations(project)
    _validate_project_graph_ids(project)
    return project


def synchronize_series_project_durations(
    series: dict,
    episode: dict | None = None,
) -> dict:
    """Recalculate every editable dialogue shot from the series provider contract."""
    from .series_render import apply_series_shot_duration

    episodes = [episode] if isinstance(episode, dict) else [
        item for item in (
            series.get("episodesById", {}).values()
            if isinstance(series.get("episodesById"), dict) else []
        )
        if isinstance(item, dict)
    ]
    for current_episode in episodes:
        for shot in (
            current_episode.get("shots", [])
            if isinstance(current_episode.get("shots"), list) else []
        ):
            if isinstance(shot, dict):
                apply_series_shot_duration(series, shot)
    return series


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
    from .series_canon_snapshot import create_snapshot
    return create_snapshot(series, normalize_canon=_normalize_canon, objects=_objects, text=_text, unique_ids=_unique_ids)


def series_for_episode_snapshot(series: dict, episode: dict) -> dict:
    from .series_canon_snapshot import overlay_snapshot
    return overlay_snapshot(series, episode, objects=_objects, unique_ids=_unique_ids)


def create_series_episode(series: dict, season_id: str | None = None, **overrides: Any) -> dict:
    """Create a draft episode with an immutable snapshot of current approved canon."""
    seasons = _objects(series.get("seasons"))
    if not seasons:
        raise ValueError("Create a season before adding an episode")
    season = next((item for item in seasons if item.get("id") == season_id), seasons[0])
    episodes = series.get("episodesById") if isinstance(series.get("episodesById"), dict) else {}
    _guard_episode_number(episodes, season.get("id"), overrides)
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
    from services.series_production import normalize_production_methods
    return _normalize_episode(
        episode, episode_id, len(season_episodes), str(season["id"]),
        _normalize_canon(series.get("canon")),
        normalize_production_methods(series.get("allowedProductionMethods")),
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
            **({"voiceProfile": {"characterKitRef": copy.deepcopy(raw["characterKitRef"])}} if isinstance(raw.get("characterKitRef"), dict) else {}),
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
        # Episodes and their attempt graph are intentionally omitted. Keep the
        # media reusable without leaving owners that no longer exist in the copy.
        if asset.get("ownerType") in {"episode", "shot", "attempt"}:
            asset["ownerType"] = "series"
            asset["ownerId"] = new_id
        elif asset.get("ownerType") == "series" and asset.get("ownerId") == old_id:
            asset["ownerId"] = new_id
    duplicate["assets"] = duplicate_assets
    duplicate["importSource"] = {
        "kind": "original", "sourceWorkspaceId": None, "sourceStoryId": None,
        "importedAt": now, "historicalProductionIds": [],
        "migrationNotes": f"Duplicated from Series Lab project {old_id}; episodes and attempts were not copied.",
    }
    return duplicate


def _approved_take_seconds(shot: dict) -> float | None:
    """Length of the shot's approved take when it was imported (animation, 3D, imported video), else None."""
    approved = shot.get("approvedAttemptId")
    attempt = next((item for item in _objects(shot.get("attempts")) if item.get("id") == approved), None) if approved else None
    seconds = ((attempt or {}).get("settings") or {}).get("sourceDurationSeconds")
    return float(seconds) if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds > 0 else None


def _beat_content(beats: Any) -> list[tuple[str, str]]:
    return [(str(beat.get("characterId") or ""), str(beat.get("text") or "").strip())
            for beat in beats if isinstance(beat, dict)] if isinstance(beats, list) else []


# A generated or imported take gets these at the cut (services/series_take_sound.py): changing them keeps the take.
CUT_APPLIED_LAYOUT = frozenset({"sfx", "music", "clipAudio", "clipVolume", "clipFit"})
VIDEO_TAKE_METHODS = frozenset({"generated_video", "imported_video"})


def _take_layout(shot: dict) -> Any:
    layout = shot.get("layout2d")
    if shot.get("productionMethod") not in VIDEO_TAKE_METHODS or not isinstance(layout, dict):
        return layout
    return {key: value for key, value in layout.items() if key not in CUT_APPLIED_LAYOUT} or None


def same_shot_content(stored: dict, incoming: dict) -> bool:
    """True when the incoming shot shows and says what the stored one does (its takes still fit)."""
    for key in SHOT_CONTENT_FIELDS:
        if key not in incoming and key not in stored:
            continue
        before, after = stored.get(key), incoming.get(key)
        if key == "layout2d":
            before, after = _take_layout(stored), _take_layout(incoming)
        if key == "dialogueBeats":
            if _beat_content(before) != _beat_content(after):
                return False
        elif (before or None) != (after or None):
            return False
    return True


def _merge_episode_shot_patch(current_shots: Any, incoming_shots: Any, *, replace: bool = False) -> list[dict]:
    """Merge editable shot fields while retaining server-owned render history.

    With ``replace`` the incoming list is the whole episode: shots it does not
    name are removed, and a shot whose content changed starts without takes
    (a rewritten script must not inherit takes that show other lines).
    """
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
        if replace and stored is not None and not same_shot_content(stored, raw_shot):
            stored = None
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
            take_seconds = _approved_take_seconds(stored)
            if take_seconds is not None and "durationSeconds" in stored:
                # An imported or server-rendered take sets the shot's length; re-sending the shot must not reset it.
                merged["durationSeconds"] = stored["durationSeconds"]
        else:
            merged["attempts"] = []
            merged.pop("approvedAttemptId", None)
            merged.pop("referenceManifest", None)
        return merged

    # A full collection can express ordering. A sparse patch updates shots in
    # place and cannot accidentally delete another shot (or its attempts).
    if replace or set(current_by_id).issubset(incoming_by_id):
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


def _keep_dropped_take_files(series: dict, episode_id: str, before: Any, after: Any) -> None:
    """A rewrite that drops shots or takes (``replaceShots``) leaves the files they owned: those assets go to the
    episode, so they stay listed and the project still validates (an asset owned by a removed take failed it)."""
    def owners(shots: Any) -> tuple[set[str], set[str]]:
        shots = _objects(shots)
        return ({str(shot.get("id")) for shot in shots},
                {str(attempt.get("id")) for shot in shots for attempt in _objects(shot.get("attempts"))})
    shots_before, attempts_before = owners(before)
    shots_after, attempts_after = owners(after)
    dropped = {"shot": shots_before - shots_after, "attempt": attempts_before - attempts_after}
    for asset in (series.get("assets") or {}).values():
        if isinstance(asset, dict) and str(asset.get("ownerId")) in dropped.get(str(asset.get("ownerType")), ()):
            asset["ownerType"], asset["ownerId"] = "episode", episode_id


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
    _guard_episode_number(episodes, patch.get("seasonId") or current.get("seasonId"), patch, episode_id)
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
        merged["shots"] = _merge_episode_shot_patch(current.get("shots"), patch["shots"], replace=patch.get("replaceShots") is True)
        _keep_dropped_take_files(updated, episode_id, current.get("shots"), merged["shots"])
    if "score" in patch:
        # A cue just written must name shots the episode has; one left behind by a rewrite is only skipped at assembly.
        from .series_score import normalize_score
        normalize_score(merged.get("score"), merged.get("shots"), strict=True, kept=_objects(current.get("score")))

    from .series_shot_dialogue import annotate_episode_shot_dialogue, sync_episode_shot_dialogue
    if patch.get("syncShotDialogueFromScript") is True:
        merged = sync_episode_shot_dialogue(
            merged, include_conflicts=patch.get("syncManualDialogueConflicts") is True,
        )
    annotate_episode_shot_dialogue(merged)

    synchronize_series_project_durations(updated, merged)

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


# Who decided on a take (``approvedBy`` / ``reviewedBy``): a person in Series Lab, an MCP agent, Ask to the Wizard,
# or the server's own render approving what it made (``approve: true``, ``series.episode.produce``).
REVIEWERS = ("user", "agent", "wizard", "server")


def _reviewer(value: Any) -> str:
    return value if value in REVIEWERS else "user"


def approve_shot_render_attempt(shot: dict, attempt_id: str, approved_by: str = "user") -> dict:
    updated = copy.deepcopy(shot)
    attempt = next((
        item for item in _objects(updated.get("attempts")) if item.get("id") == attempt_id
    ), None)
    if not attempt:
        raise ValueError("Series shot render attempt not found")
    if attempt.get("status") != "completed" or not attempt.get("outputAssetIds"):
        raise ValueError("Only a completed Series shot attempt with output can be approved")
    updated["approvedAttemptId"] = attempt_id
    now, reviewer = _now(), _reviewer(approved_by)
    updated = update_shot_render_attempt(
        updated, attempt_id, reviewDecision="approved", reviewedAt=now, reviewedBy=reviewer,
        approvedBy=reviewer, approvedAt=now,
    )
    return updated


def approve_episode_render_attempts(episode: dict, selections: Any, approved_by: str = "user") -> dict:
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
        shots[shot_index] = approve_shot_render_attempt(shots[shot_index], attempt_id, approved_by)
    updated["shots"] = shots
    return updated


def reject_shot_render_attempt(shot: dict, attempt_id: str, rejected_by: str = "user") -> dict:
    updated = copy.deepcopy(shot)
    attempt = next((
        item for item in _objects(updated.get("attempts")) if item.get("id") == attempt_id
    ), None)
    if not attempt:
        raise ValueError("Series shot render attempt not found")
    updated = update_shot_render_attempt(
        updated, attempt_id, reviewDecision="rejected", reviewedAt=_now(), reviewedBy=_reviewer(rejected_by),
    )
    if updated.get("approvedAttemptId") == attempt_id:
        updated.pop("approvedAttemptId", None)
    return updated
