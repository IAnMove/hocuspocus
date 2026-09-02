"""Structured prompts, schemas, and merge rules for Series Lab planning jobs."""

from __future__ import annotations

import copy
import json
import math
import re
import uuid
from typing import Any


ALL_PLANNING_STAGES = ["outline", "script", "shots", "canon_validation", "canon_delta"]

SERIES_SHOT_DURATIONS = (5, 10, 15)
SERIES_SHOT_IDEAL_SECONDS = 10
SERIES_SHOT_MAX_ITEMS = 720


def _planning_uid(prefix: str) -> str:
    """Create a server-owned, globally unique Series planning identifier."""
    return f"{prefix}_{uuid.uuid4().hex}"


def series_shot_count_profile(episode: dict | None = None) -> dict[str, int | float]:
    """Return duration-aware shot bounds using only 5/10/15-second clips."""
    raw_target = (episode or {}).get("targetDurationSeconds", 75)
    try:
        target = max(5.0, min(3600.0, float(raw_target or 75)))
    except (TypeError, ValueError):
        target = 75.0
    minimum = max(1, math.ceil(target / max(SERIES_SHOT_DURATIONS)))
    maximum = min(
        SERIES_SHOT_MAX_ITEMS,
        max(minimum, math.ceil(target / min(SERIES_SHOT_DURATIONS))),
    )
    ideal = max(
        minimum,
        min(maximum, int(math.floor(target / SERIES_SHOT_IDEAL_SECONDS + 0.5))),
    )
    return {
        "target": target,
        "minimum": minimum,
        "ideal": ideal,
        "maximum": maximum,
    }


def planning_output_token_budget(stage: str, episode: dict | None = None) -> int:
    """Scale long-form shot JSON without inflating small planning stages."""
    if stage == "shots":
        ideal = int(series_shot_count_profile(episode)["ideal"])
        return min(64000, max(9000, 2000 + ideal * 600))
    if stage == "script":
        return 6000
    return 2400


def planning_stages(scope: str) -> list[str]:
    if scope == "outline":
        return ["outline"]
    if scope == "script":
        return ["outline", "script"]
    if scope in {"complete", "all"}:
        return list(ALL_PLANNING_STAGES)
    if scope in ALL_PLANNING_STAGES:
        return [scope]
    raise ValueError("Unsupported Series Lab planning scope")


def _string() -> dict:
    return {"type": "string"}


def _string_array(max_items: int = 24) -> dict:
    return {"type": "array", "items": _string(), "maxItems": max_items}


def planning_schema(stage: str, episode: dict | None = None) -> dict:
    string = _string()
    dialogue = {
        "type": "object",
        "properties": {
            "id": string, "characterId": string, "text": string,
            "emotion": string, "delivery": string,
        },
        "required": ["id", "characterId", "text", "emotion", "delivery"],
        "additionalProperties": False,
    }
    if stage == "outline":
        return {
            "type": "object",
            "properties": {"outline": {
                "type": "object",
                "properties": {"beats": _string_array(12)},
                "required": ["beats"], "additionalProperties": False,
            }},
            "required": ["outline"], "additionalProperties": False,
        }
    if stage == "script":
        scene_beat = {
            "type": "object",
            "properties": {"id": string, "kind": {"enum": ["action", "dialogue"]}, "summary": string},
            "required": ["id", "kind", "summary"], "additionalProperties": False,
        }
        scene = {
            "type": "object",
            "properties": {
                "id": string, "order": {"type": "integer"}, "locationId": string,
                "locationVariantId": string, "time": string,
                "participatingCharacterIds": _string_array(4), "purpose": string,
                "entryState": string, "exitState": string,
                "beats": {"type": "array", "items": scene_beat, "maxItems": 16},
                "dialogue": {"type": "array", "items": dialogue, "maxItems": 16},
            },
            "required": [
                "id", "order", "locationId", "locationVariantId", "time",
                "participatingCharacterIds", "purpose", "entryState", "exitState",
                "beats", "dialogue",
            ],
            "additionalProperties": False,
        }
        return {
            "type": "object", "properties": {"script": {
                "type": "array", "items": scene, "minItems": 1, "maxItems": 8,
            }}, "required": ["script"], "additionalProperties": False,
        }
    if stage == "shots":
        profile = series_shot_count_profile(episode)
        shot = {
            "type": "object",
            "properties": {
                "id": string, "sceneId": string, "order": {"type": "integer"},
                "durationSeconds": {
                    "type": "number", "minimum": 0.1, "maximum": 60,
                    "description": (
                        "Visual pacing hint only. Dialogue duration is recalculated "
                        "from syllables and rounded upward to model capabilities."
                    ),
                },
                "framing": string, "camera": string,
                "action": string,
                "dialogueBeats": {"type": "array", "items": dialogue, "maxItems": 4},
                "visibleCharacterIds": _string_array(4), "speakingCharacterIds": _string_array(1),
                "primarySpeakerId": string, "locationId": string, "locationVariantId": string,
                "wardrobeByCharacterId": {"type": "object"}, "propIds": _string_array(6),
                "emotionalStateByCharacterId": {"type": "object"},
                "continuityFromShotId": string,
                "renderStrategy": {"enum": ["auto", "direct", "first_frame", "references", "first_last"]},
                "prompt": string, "negativePrompt": string,
            },
            "required": [
                "id", "sceneId", "order", "durationSeconds", "framing", "camera", "action",
                "dialogueBeats", "visibleCharacterIds", "speakingCharacterIds", "primarySpeakerId",
                "locationId", "locationVariantId", "wardrobeByCharacterId", "propIds",
                "emotionalStateByCharacterId", "continuityFromShotId", "renderStrategy",
                "prompt", "negativePrompt",
            ],
            "additionalProperties": False,
        }
        return {
            "type": "object", "properties": {"shots": {
                "type": "array", "items": shot,
                "minItems": int(profile["minimum"]),
                "maxItems": int(profile["maximum"]),
            }}, "required": ["shots"], "additionalProperties": False,
        }
    if stage == "canon_validation":
        issue = {
            "type": "object",
            "properties": {
                "id": string,
                "kind": {"enum": [
                    "contradiction", "unsupported_knowledge", "missing_required_entity",
                    "wardrobe_state", "relationship", "timeline",
                ]},
                "severity": {"enum": ["warning", "error"]},
                "message": string, "sceneId": string, "shotId": string,
            },
            "required": ["id", "kind", "severity", "message", "sceneId", "shotId"],
            "additionalProperties": False,
        }
        return {
            "type": "object", "properties": {"issues": {
                "type": "array", "items": issue, "maxItems": 30,
            }}, "required": ["issues"], "additionalProperties": False,
        }
    if stage == "canon_delta":
        fact = {
            "type": "object",
            "properties": {"id": string, "description": string},
            "required": ["id", "description"], "additionalProperties": False,
        }
        retire = {
            "type": "object", "properties": {"factId": string},
            "required": ["factId"], "additionalProperties": False,
        }
        return {
            "type": "object", "properties": {
                "add": {"type": "array", "items": fact, "maxItems": 12},
                "change": {"type": "array", "items": fact, "maxItems": 12},
                "retire": {"type": "array", "items": retire, "maxItems": 12},
            },
            "required": ["add", "change", "retire"], "additionalProperties": False,
        }
    raise ValueError("Unsupported Series Lab planning stage")


def canon_preparation_schema() -> dict:
    """Bounded MVP schema for a reviewable Series canon proposal."""
    string = _string()
    variant = {
        "type": "object",
        "properties": {"id": string, "label": string, "description": string},
        "required": ["id", "label", "description"], "additionalProperties": False,
    }
    character = {
        "type": "object",
        "properties": {
            "id": string, "name": string, "role": string, "personality": string,
            "desire": string, "need": string, "flaw": string, "longArc": string,
            "voiceAndDialogue": string, "appearance": string, "identityLock": string,
            "wardrobeVariants": {"type": "array", "items": variant, "maxItems": 4},
        },
        "required": [
            "id", "name", "role", "personality", "desire", "need", "flaw",
            "longArc", "voiceAndDialogue", "appearance", "identityLock", "wardrobeVariants",
        ],
        "additionalProperties": False,
    }
    location = {
        "type": "object",
        "properties": {
            "id": string, "name": string, "purpose": string, "description": string,
            "variants": {"type": "array", "items": variant, "maxItems": 4},
        },
        "required": ["id", "name", "purpose", "description", "variants"],
        "additionalProperties": False,
    }
    relationship = {
        "type": "object",
        "properties": {
            "id": string, "fromCharacterId": string, "toCharacterId": string,
            "label": string, "dynamic": string, "evolution": string,
        },
        "required": ["id", "fromCharacterId", "toCharacterId", "label", "dynamic", "evolution"],
        "additionalProperties": False,
    }
    fact = {
        "type": "object", "properties": {"id": string, "description": string},
        "required": ["id", "description"], "additionalProperties": False,
    }
    arc = {
        "type": "object",
        "properties": {"id": string, "title": string, "description": string},
        "required": ["id", "title", "description"], "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "canon": {
                "type": "object",
                "properties": {
                    "worldSummary": string,
                    "immutableRules": {"type": "array", "items": fact, "maxItems": 12},
                    "forbiddenChanges": _string_array(12), "themes": _string_array(8),
                    "longArcs": {"type": "array", "items": arc, "maxItems": 6},
                },
                "required": ["worldSummary", "immutableRules", "forbiddenChanges", "themes", "longArcs"],
                "additionalProperties": False,
            },
            "characters": {"type": "array", "items": character, "minItems": 1, "maxItems": 2},
            "relationships": {"type": "array", "items": relationship, "maxItems": 4},
            "locations": {"type": "array", "items": location, "minItems": 1, "maxItems": 2},
        },
        "required": ["canon", "characters", "relationships", "locations"],
        "additionalProperties": False,
    }


def canon_preparation_prompt(series: dict, instruction: str = "") -> tuple[str, str]:
    context = {
        key: series.get(key) for key in (
            "title", "premise", "logline", "format", "language", "genre", "tone",
            "audience", "visualStyle", "characterVisualStyle", "cameraLanguage",
            "sourceMode", "masterUniversePrompt", "rightsNote", "canon", "characters",
            "relationships", "locations", "props",
        )
    }
    system = (
        "You are the Series Lab canon architect. Return exactly one JSON object matching the schema. "
        "Create a compact production-ready MVP bible with at most two principal characters and two locations. "
        "Keep supplied entity IDs when refining an existing entity. Use new stable ASCII IDs for new entities. "
        "IdentityLock and location descriptions must be concrete visual prompts, not narrative summaries. "
        "Do not claim legal rights, create copyrighted-franchise defaults, or create episode events."
    )
    prompt = (
        "Prepare a compact persistent series canon that can support short or long episodes. "
        "Include immutable rules, visual identity locks, named wardrobe/location variants, relationships and long arcs.\n"
        f"USER DIRECTION: {instruction.strip() or 'Use the saved setup and improve any existing draft canon.'}\n\n"
        f"SAVED SETUP AND DRAFT CANON:\n{json.dumps(_bounded(context), ensure_ascii=False)}"
    )
    return prompt, system


def normalize_canon_preparation(result: Any, series: dict) -> dict:
    if not isinstance(result, dict):
        raise ValueError("Series canon preparation response is not an object")
    canon = result.get("canon")
    characters = result.get("characters")
    relationships = result.get("relationships")
    locations = result.get("locations")
    if not isinstance(canon, dict) or not isinstance(characters, list) or not isinstance(locations, list):
        raise ValueError("Series canon preparation response is incomplete")
    if not 1 <= len(characters) <= 2 or not 1 <= len(locations) <= 2:
        raise ValueError("Series canon MVP requires one or two principal characters and locations")

    def stable_id(value: Any, prefix: str, index: int) -> str:
        raw = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("_")
        return (raw or f"{prefix}_{index + 1}")[:120]

    normalized_characters = []
    character_ids: set[str] = set()
    for index, raw in enumerate(characters):
        if not isinstance(raw, dict):
            raise ValueError("Series canon contains an invalid character")
        character_id = stable_id(raw.get("id"), "character", index)
        if character_id in character_ids:
            character_id = f"character_{index + 1}"
        character_ids.add(character_id)
        variants = []
        for variant_index, variant in enumerate(raw.get("wardrobeVariants", [])[:4]):
            if isinstance(variant, dict):
                variants.append({
                    "id": stable_id(variant.get("id"), f"wardrobe_{character_id}", variant_index),
                    "label": str(variant.get("label") or f"Variant {variant_index + 1}")[:200],
                    "description": str(variant.get("description") or "")[:2000],
                    "referenceAssetIds": [],
                })
        normalized_characters.append({
            "id": character_id, "name": str(raw.get("name") or f"Character {index + 1}")[:200],
            "aliases": [],
            **{key: str(raw.get(key) or "")[:3000] for key in (
                "role", "personality", "desire", "need", "flaw", "longArc",
                "voiceAndDialogue", "appearance", "identityLock",
            )},
            "wardrobeVariants": variants, "referenceAssetIds": [], "currentState": {},
            "approval": "draft",
        })
    normalized_locations = []
    location_ids: set[str] = set()
    for index, raw in enumerate(locations):
        if not isinstance(raw, dict):
            raise ValueError("Series canon contains an invalid location")
        location_id = stable_id(raw.get("id"), "location", index)
        if location_id in location_ids:
            location_id = f"location_{index + 1}"
        location_ids.add(location_id)
        variants = []
        for variant_index, variant in enumerate(raw.get("variants", [])[:4]):
            if isinstance(variant, dict):
                variants.append({
                    "id": stable_id(variant.get("id"), f"variant_{location_id}", variant_index),
                    "label": str(variant.get("label") or f"Variant {variant_index + 1}")[:200],
                    "description": str(variant.get("description") or "")[:2000],
                    "referenceAssetIds": [],
                })
        normalized_locations.append({
            "id": location_id, "name": str(raw.get("name") or f"Location {index + 1}")[:200],
            "purpose": str(raw.get("purpose") or "")[:2000],
            "description": str(raw.get("description") or "")[:3000],
            "referenceAssetIds": [], "variants": variants, "currentState": {}, "approval": "draft",
        })
    normalized_relationships = []
    for index, raw in enumerate(relationships if isinstance(relationships, list) else []):
        if not isinstance(raw, dict):
            continue
        from_id = str(raw.get("fromCharacterId") or "")
        to_id = str(raw.get("toCharacterId") or "")
        if from_id not in character_ids or to_id not in character_ids or from_id == to_id:
            raise ValueError("Series relationship references an unknown character ID")
        normalized_relationships.append({
            "id": stable_id(raw.get("id"), "relationship", index),
            "fromCharacterId": from_id, "toCharacterId": to_id,
            "label": str(raw.get("label") or "")[:500],
            "dynamic": str(raw.get("dynamic") or "")[:2000],
            "evolution": str(raw.get("evolution") or "")[:2000],
        })
    normalized_canon = {
        "worldSummary": str(canon.get("worldSummary") or "")[:6000],
        "immutableRules": [
            {"id": stable_id(item.get("id"), "rule", index),
             "description": str(item.get("description") or "")[:2000], "status": "draft"}
            for index, item in enumerate(canon.get("immutableRules", [])[:12]) if isinstance(item, dict)
        ],
        "currentFacts": copy.deepcopy(series.get("canon", {}).get("currentFacts") or []),
        "forbiddenChanges": [str(item)[:1000] for item in canon.get("forbiddenChanges", [])[:12]],
        "themes": [str(item)[:500] for item in canon.get("themes", [])[:8]],
        "longArcs": [
            {"id": stable_id(item.get("id"), "arc", index),
             "title": str(item.get("title") or "")[:500],
             "description": str(item.get("description") or "")[:3000], "status": "planned"}
            for index, item in enumerate(canon.get("longArcs", [])[:6]) if isinstance(item, dict)
        ],
        "timeline": copy.deepcopy(series.get("canon", {}).get("timeline") or []),
        "revision": int(series.get("canon", {}).get("revision") or 1),
    }
    return {
        "canon": normalized_canon, "characters": normalized_characters,
        "relationships": normalized_relationships, "locations": normalized_locations,
    }


def known_series_bootstrap_schema() -> dict:
    """Rich but bounded schema for turning one known-series request into an editable bible."""
    string = _string()
    variant = {
        "type": "object",
        "properties": {"id": string, "label": string, "description": string},
        "required": ["id", "label", "description"], "additionalProperties": False,
    }
    character = {
        "type": "object",
        "properties": {
            "id": string, "name": string, "aliases": _string_array(8),
            "role": string, "personality": string, "desire": string, "need": string,
            "flaw": string, "longArc": string, "voiceAndDialogue": string,
            "appearance": string, "identityLock": string,
            "wardrobeVariants": {"type": "array", "items": variant, "maxItems": 4},
        },
        "required": [
            "id", "name", "aliases", "role", "personality", "desire", "need", "flaw",
            "longArc", "voiceAndDialogue", "appearance", "identityLock", "wardrobeVariants",
        ],
        "additionalProperties": False,
    }
    location = {
        "type": "object",
        "properties": {
            "id": string, "name": string, "purpose": string, "description": string,
            "variants": {"type": "array", "items": variant, "maxItems": 4},
        },
        "required": ["id", "name", "purpose", "description", "variants"],
        "additionalProperties": False,
    }
    prop = {
        "type": "object",
        "properties": {
            "id": string, "name": string, "kind": string, "description": string,
            "ownerCharacterId": string,
            "variants": {"type": "array", "items": variant, "maxItems": 4},
        },
        "required": ["id", "name", "kind", "description", "ownerCharacterId", "variants"],
        "additionalProperties": False,
    }
    relationship = {
        "type": "object",
        "properties": {
            "id": string, "fromCharacterId": string, "toCharacterId": string,
            "label": string, "dynamic": string, "evolution": string,
        },
        "required": ["id", "fromCharacterId", "toCharacterId", "label", "dynamic", "evolution"],
        "additionalProperties": False,
    }
    fact = {
        "type": "object", "properties": {"id": string, "description": string},
        "required": ["id", "description"], "additionalProperties": False,
    }
    timeline_fact = {
        "type": "object",
        "properties": {"id": string, "description": string, "occurredAt": string},
        "required": ["id", "description", "occurredAt"], "additionalProperties": False,
    }
    arc = {
        "type": "object",
        "properties": {"id": string, "title": string, "description": string},
        "required": ["id", "title", "description"], "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "setup": {
                "type": "object",
                "properties": {
                    "title": string, "premise": string, "logline": string,
                    "format": {"enum": ["serial", "episodic", "hybrid"]},
                    "defaultEpisodeDurationSeconds": {"type": "integer", "minimum": 15, "maximum": 3600},
                    "language": string, "genre": string, "tone": string, "audience": string,
                    "visualStyle": string, "characterVisualStyle": string, "cameraLanguage": string,
                    "masterUniversePrompt": string, "rightsNote": string,
                },
                "required": [
                    "title", "premise", "logline", "format", "defaultEpisodeDurationSeconds",
                    "language", "genre", "tone", "audience", "visualStyle",
                    "characterVisualStyle", "cameraLanguage", "masterUniversePrompt", "rightsNote",
                ],
                "additionalProperties": False,
            },
            "canon": {
                "type": "object",
                "properties": {
                    "worldSummary": string,
                    "immutableRules": {"type": "array", "items": fact, "maxItems": 20},
                    "currentFacts": {"type": "array", "items": fact, "maxItems": 24},
                    "forbiddenChanges": _string_array(20), "themes": _string_array(12),
                    "longArcs": {"type": "array", "items": arc, "maxItems": 12},
                    "timeline": {"type": "array", "items": timeline_fact, "maxItems": 24},
                },
                "required": [
                    "worldSummary", "immutableRules", "currentFacts", "forbiddenChanges",
                    "themes", "longArcs", "timeline",
                ],
                "additionalProperties": False,
            },
            "characters": {"type": "array", "items": character, "minItems": 1, "maxItems": 12},
            "relationships": {"type": "array", "items": relationship, "maxItems": 24},
            "locations": {"type": "array", "items": location, "minItems": 1, "maxItems": 12},
            "props": {"type": "array", "items": prop, "maxItems": 12},
        },
        "required": ["setup", "canon", "characters", "relationships", "locations", "props"],
        "additionalProperties": False,
    }


def known_series_bootstrap_prompt(series: dict, request: str) -> tuple[str, str]:
    """Prompt a general LLM to draft known public canon without pretending it researched the web."""
    existing = {
        key: series.get(key) for key in (
            "title", "language", "defaultEpisodeDurationSeconds", "premise", "visualStyle",
            "masterUniversePrompt", "rightsNote", "characters", "locations", "props",
        )
    }
    system = (
        "You are the Series Lab known-series bible architect. Return exactly one JSON object matching the schema. "
        "Use your general knowledge of the real TV series, film universe, or franchise named by the user. "
        "This is NOT live web research: include only facts you are reasonably confident are established, keep proper "
        "names exact, and omit uncertain trivia rather than fabricating it. Cover the main and genuinely recurring cast, "
        "recognizable recurring locations, important relationship dynamics, recurring props when useful, world rules, "
        "and broad chronology needed for continuity. Do not reproduce scripts, episode dialogue, catchphrases, or detailed "
        "copyrighted episode plots. Do not invent a new episode or future canon. Character voice guidance must describe "
        "rhythm, attitude, and conversational function without quoting dialogue or imitating a living performer's voice. "
        "Visual identity locks must describe the established fictional character, wardrobe silhouette, era, and continuity; "
        "never instruct face-cloning of a performer. Mark the work as an unofficial editable draft and never claim rights. "
        "Write descriptive prose in the user's requested language while preserving canonical proper nouns."
    )
    prompt = (
        "Build and configure a reusable Series Lab project from this single request:\n"
        f"USER REQUEST: {request.strip()}\n\n"
        "The setup must be useful for writing new, original fan-created episode ideas consistent with the known premise, "
        "but this response itself must contain no new episode story. The masterUniversePrompt should be a concise reusable "
        "continuity instruction naming the source series and the traits that must stay stable. Default to an episodic format "
        "and a practical short-form episode duration unless the request clearly asks otherwise. All facts are drafts for "
        "human verification before canon approval.\n\n"
        f"CURRENT PROJECT PREFERENCES (retain only when useful):\n{json.dumps(_bounded(existing), ensure_ascii=False)}"
    )
    return prompt, system


def normalize_known_series_bootstrap(result: Any, series: dict) -> dict:
    """Normalize a known-series draft into the full editable SeriesProject entity shapes."""
    if not isinstance(result, dict):
        raise ValueError("Known-series bootstrap response is not an object")
    setup = result.get("setup")
    canon = result.get("canon")
    characters = result.get("characters")
    locations = result.get("locations")
    if not isinstance(setup, dict) or not isinstance(canon, dict):
        raise ValueError("Known-series bootstrap response is missing setup or canon")
    if not isinstance(characters, list) or not 1 <= len(characters) <= 12:
        raise ValueError("Known-series bootstrap requires between one and twelve recurring characters")
    if not isinstance(locations, list) or not 1 <= len(locations) <= 12:
        raise ValueError("Known-series bootstrap requires between one and twelve recurring locations")

    def stable_id(value: Any, prefix: str, index: int) -> str:
        raw = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("_")
        return (raw or f"{prefix}_{index + 1}")[:120]

    def text(value: Any, limit: int = 3000) -> str:
        return str(value or "").strip()[:limit]

    def variants(raw_variants: Any, prefix: str) -> list[dict]:
        values = []
        for index, raw in enumerate(raw_variants[:4] if isinstance(raw_variants, list) else []):
            if isinstance(raw, dict):
                values.append({
                    "id": stable_id(raw.get("id"), f"{prefix}_variant", index),
                    "label": text(raw.get("label") or f"Variant {index + 1}", 200),
                    "description": text(raw.get("description"), 2000),
                    "referenceAssetIds": [],
                })
        return values

    normalized_characters: list[dict] = []
    character_ids: set[str] = set()
    character_lookup: dict[str, str] = {}
    for index, raw in enumerate(characters[:12]):
        if not isinstance(raw, dict):
            raise ValueError("Known-series bootstrap contains an invalid character")
        character_id = stable_id(raw.get("id"), "character", index)
        if character_id in character_ids:
            character_id = f"character_{index + 1}"
        character_ids.add(character_id)
        aliases = [text(item, 200) for item in raw.get("aliases", [])[:8] if text(item, 200)] \
            if isinstance(raw.get("aliases"), list) else []
        name = text(raw.get("name") or f"Character {index + 1}", 200)
        for candidate in [raw.get("id"), name, *aliases]:
            token = re.sub(r"[^a-z0-9]+", "", str(candidate or "").casefold())
            if token:
                character_lookup.setdefault(token, character_id)
        normalized_characters.append({
            "id": character_id, "name": name, "aliases": aliases,
            **{key: text(raw.get(key)) for key in (
                "role", "personality", "desire", "need", "flaw", "longArc",
                "voiceAndDialogue", "appearance", "identityLock",
            )},
            "wardrobeVariants": variants(raw.get("wardrobeVariants"), f"wardrobe_{character_id}"),
            "referenceAssetIds": [], "currentState": {}, "approval": "draft",
        })

    def resolve_character(value: Any) -> str:
        raw = str(value or "").strip()
        if raw in character_ids:
            return raw
        token = re.sub(r"[^a-z0-9]+", "", raw.casefold())
        return character_lookup.get(token, "")

    normalized_locations = []
    location_ids: set[str] = set()
    for index, raw in enumerate(locations[:12]):
        if not isinstance(raw, dict):
            raise ValueError("Known-series bootstrap contains an invalid location")
        location_id = stable_id(raw.get("id"), "location", index)
        if location_id in location_ids:
            location_id = f"location_{index + 1}"
        location_ids.add(location_id)
        normalized_locations.append({
            "id": location_id, "name": text(raw.get("name") or f"Location {index + 1}", 200),
            "purpose": text(raw.get("purpose"), 2000), "description": text(raw.get("description")),
            "referenceAssetIds": [], "variants": variants(raw.get("variants"), f"location_{location_id}"),
            "currentState": {}, "approval": "draft",
        })

    normalized_relationships = []
    for index, raw in enumerate(result.get("relationships", [])[:24] if isinstance(result.get("relationships"), list) else []):
        if not isinstance(raw, dict):
            continue
        from_id = resolve_character(raw.get("fromCharacterId"))
        to_id = resolve_character(raw.get("toCharacterId"))
        if not from_id or not to_id or from_id == to_id:
            continue
        normalized_relationships.append({
            "id": stable_id(raw.get("id"), "relationship", index),
            "fromCharacterId": from_id, "toCharacterId": to_id,
            "label": text(raw.get("label"), 500), "dynamic": text(raw.get("dynamic"), 2000),
            "evolution": text(raw.get("evolution"), 2000),
        })

    normalized_props = []
    for index, raw in enumerate(result.get("props", [])[:12] if isinstance(result.get("props"), list) else []):
        if not isinstance(raw, dict):
            continue
        prop_id = stable_id(raw.get("id"), "prop", index)
        normalized_props.append({
            "id": prop_id, "name": text(raw.get("name") or f"Prop {index + 1}", 200),
            "kind": text(raw.get("kind"), 300), "description": text(raw.get("description")),
            "ownerCharacterId": resolve_character(raw.get("ownerCharacterId")),
            "referenceAssetIds": [], "variants": variants(raw.get("variants"), f"prop_{prop_id}"),
            "currentState": {}, "approval": "draft",
        })

    def facts(values: Any, prefix: str, limit: int, timeline: bool = False) -> list[dict]:
        normalized = []
        for index, raw in enumerate(values[:limit] if isinstance(values, list) else []):
            if not isinstance(raw, dict):
                continue
            item = {
                "id": stable_id(raw.get("id"), prefix, index),
                "description": text(raw.get("description"), 2000), "status": "draft",
            }
            if timeline:
                item["occurredAt"] = text(raw.get("occurredAt") or "Established series chronology", 500)
            normalized.append(item)
        return normalized

    format_value = setup.get("format") if setup.get("format") in {"serial", "episodic", "hybrid"} else "episodic"
    try:
        duration = max(15, min(3600, int(setup.get("defaultEpisodeDurationSeconds") or 75)))
    except (TypeError, ValueError):
        duration = 75
    normalized_canon = {
        "worldSummary": text(canon.get("worldSummary"), 6000),
        "immutableRules": facts(canon.get("immutableRules"), "rule", 20),
        "currentFacts": facts(canon.get("currentFacts"), "fact", 24),
        "forbiddenChanges": [text(item, 1000) for item in canon.get("forbiddenChanges", [])[:20] if text(item, 1000)],
        "themes": [text(item, 500) for item in canon.get("themes", [])[:12] if text(item, 500)],
        "longArcs": [
            {
                "id": stable_id(item.get("id"), "arc", index), "title": text(item.get("title"), 500),
                "description": text(item.get("description")), "status": "planned",
            }
            for index, item in enumerate(canon.get("longArcs", [])[:12]) if isinstance(item, dict)
        ],
        "timeline": facts(canon.get("timeline"), "timeline", 24, timeline=True),
        "revision": int(series.get("canon", {}).get("revision") or 1),
    }
    fallback_rights = (
        "Borrador no oficial basado en una obra de terceros. Verifica los derechos necesarios antes de publicar o monetizar."
    )
    return {
        "title": text(setup.get("title") or series.get("title") or "Untitled series", 300),
        "premise": text(setup.get("premise"), 6000), "logline": text(setup.get("logline"), 2000),
        "format": format_value, "defaultEpisodeDurationSeconds": duration,
        "language": text(setup.get("language") or series.get("language") or "Español", 200),
        "genre": text(setup.get("genre"), 500), "tone": text(setup.get("tone"), 1000),
        "audience": text(setup.get("audience") or "General", 500),
        "visualStyle": text(setup.get("visualStyle"), 4000),
        "characterVisualStyle": text(setup.get("characterVisualStyle"), 4000),
        "cameraLanguage": text(setup.get("cameraLanguage"), 4000),
        "sourceMode": "known_universe_experimental",
        "masterUniversePrompt": text(setup.get("masterUniversePrompt"), 6000),
        "rightsNote": text(setup.get("rightsNote") or fallback_rights, 2000),
        "canon": normalized_canon, "characters": normalized_characters,
        "relationships": normalized_relationships, "locations": normalized_locations,
        "props": normalized_props,
    }


def merge_series_canon_proposal(
    series: dict, proposal: dict, *, bootstrap_known_series: bool = False,
) -> dict:
    """Pure merge used by durable jobs; never drops assets, episodes, or matched references."""
    merged_series = copy.deepcopy(series)
    if bootstrap_known_series:
        for key in (
            "title", "premise", "logline", "format", "defaultEpisodeDurationSeconds",
            "language", "genre", "tone", "audience", "visualStyle",
            "characterVisualStyle", "cameraLanguage", "sourceMode",
            "masterUniversePrompt", "rightsNote",
        ):
            if key in proposal:
                merged_series[key] = copy.deepcopy(proposal[key])
    collection_names = ["characters", "locations"]
    if bootstrap_known_series:
        collection_names.append("props")
    for collection_name in collection_names:
        existing = {
            str(item.get("id")): item for item in merged_series.get(collection_name, [])
            if isinstance(item, dict) and item.get("id")
        }
        merged_items = []
        for item in proposal.get(collection_name, []):
            if not isinstance(item, dict):
                continue
            previous = existing.get(str(item.get("id"))) or {}
            merged_item = copy.deepcopy(item)
            for key in (
                "referenceAssetIds", "primaryReferenceAssetId", "voiceProfile", "currentState",
            ):
                if key in previous:
                    merged_item[key] = copy.deepcopy(previous[key])
            merged_item["approval"] = "draft"
            merged_items.append(merged_item)
        merged_series[collection_name] = merged_items
    merged_series["relationships"] = copy.deepcopy(proposal.get("relationships") or [])
    proposed_canon = copy.deepcopy(proposal.get("canon") or {})
    if not bootstrap_known_series:
        proposed_canon["currentFacts"] = copy.deepcopy(merged_series.get("canon", {}).get("currentFacts") or [])
        proposed_canon["timeline"] = copy.deepcopy(merged_series.get("canon", {}).get("timeline") or [])
    proposed_canon["revision"] = int(merged_series.get("canon", {}).get("revision") or 1)
    proposed_canon["approval"] = "draft"
    proposed_canon["approvedAt"] = ""
    merged_series["canon"] = proposed_canon
    return merged_series


def _bounded(value: Any, depth: int = 0) -> Any:
    if depth > 7:
        return None
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, list):
        return [_bounded(item, depth + 1) for item in value[:40]]
    if isinstance(value, dict):
        return {
            str(key): _bounded(item, depth + 1) for key, item in value.items()
            if key not in {"assets", "attempts", "referenceManifest", "productions", "productionIds"}
        }
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def planning_prompt(stage: str, series: dict, episode: dict, instruction: str = "") -> tuple[str, str]:
    shot_profile = series_shot_count_profile(episode)
    script_scene_ids = [
        str(item.get("id")) for item in episode.get("script", [])
        if isinstance(item, dict) and item.get("id")
    ]
    canon_snapshot = episode.get("canonSnapshot") if isinstance(episode.get("canonSnapshot"), dict) else {}
    context = {
        "series": {
            key: series.get(key) for key in (
                "title", "logline", "premise", "format", "language", "spokenLanguage", "languageIntent", "genre", "tone",
                "audience", "visualStyle", "characterVisualStyle", "cameraLanguage",
                "allowClipText", "sourceMode", "masterUniversePrompt",
            )
        },
        "canonSnapshot": canon_snapshot,
        "characters": series.get("characters", []),
        "relationships": series.get("relationships", []),
        "locations": series.get("locations", []),
        "props": series.get("props", []),
        "season": next((
            item for item in series.get("seasons", []) if item.get("id") == episode.get("seasonId")
        ), {}),
        "priorEpisodeSummaries": series.get("priorEpisodeSummaries", []),
        "episode": episode,
    }
    system = (
        "You are the Series Lab planning engine. Return exactly one JSON object matching the schema. "
        "CanonSnapshot is immutable evidence, never rewrite it. Use entity IDs exactly as supplied. "
        "Every speaking character must also be visible. Never invent a reference asset or entity ID. "
        "Each shot may contain dialogue from only one character; split every speaker change into a separate shot. "
        "Write short dialogue suitable for best-effort native lip sync. "
        "Write all generation-facing visual shot fields (prompt, action, framing, camera, and negativePrompt) "
        "in English. Keep only dialogueBeats.text in the series spokenLanguage, with natural regional wording. "
        "Never put quoted dialogue or instructions to speak in prompt or action; dialogueBeats is the sole speech source. "
        "For shots, speakingCharacterIds must be exactly the unique characterId values used by dialogueBeats; "
        "never copy every visible character into speakingCharacterIds. If a scene needs three people to speak, "
        "cover them across separate single-speaker shots in conversational order. "
        "Do not mutate canon; canon changes are proposals for later human review."
    )
    requirements = {
        "outline": "Create a compact episode outline with 4–8 causal beats.",
        "script": (
            "Create complete editable scenes. Every dialogue line must name a supplied characterId and include "
            "emotion and delivery. Use only supplied location/character IDs."
        ),
        "shots": (
            f"Create about {int(shot_profile['ideal'])} shots (valid range "
            f"{int(shot_profile['minimum'])}–{int(shot_profile['maximum'])}) for the "
            f"{float(shot_profile['target']):g}-second target. For silent coverage, use a 5, 10, "
            "or 15 second pacing hint; dialogue clips are recalculated by syllable count and model capabilities: "
            "prefer 10 seconds, use 5 when the visible action or spoken line comfortably fits, and never exceed "
            "15 seconds. Add shots to cover runtime; never make a clip longer to fill the episode. "
            "Set every sceneId by copying one exact ID from episode.script; never rename or describe a scene. "
            f"The only valid scene IDs are {json.dumps(script_scene_ids, ensure_ascii=False)}. "
            "Assign visibleCharacterIds, "
            "speakingCharacterIds, location/variant, wardrobe and props by ID. Keep renderStrategy auto unless "
            "a clear explicit strategy is essential. Prompts describe only the shot; do not claim loose portraits "
            "are exact first frames. Describe visible action rather than saying that a character talks, asks, replies, "
            "sings, mutters, or shouts; put every spoken word only in dialogueBeats.text."
        ),
        "canon_validation": (
            "Report structured contradictions or continuity risks. Do not rewrite the episode and return an empty "
            "issues array when no evidence-backed issue exists."
        ),
        "canon_delta": (
            "Propose only facts genuinely established by this episode. Do not approve them. Use existing fact IDs "
            "for change/retire and stable new IDs for additions."
        ),
    }[stage]
    prompt = (
        f"STAGE: {stage}\n{requirements}\n"
        f"USER EPISODE INSTRUCTION: {instruction.strip() or 'Use the saved episode premise and constraints.'}\n\n"
        f"AUTHORITATIVE CONTEXT:\n{json.dumps(_bounded(context), ensure_ascii=False)}"
    )
    return prompt, system


def _token(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def _resolver(items: list[dict]) -> tuple[set[str], dict[str, str]]:
    ids = {str(item.get("id")) for item in items if item.get("id")}
    lookup: dict[str, str] = {}
    for item in items:
        entity_id = str(item.get("id") or "")
        for alias in [entity_id, item.get("name"), *(item.get("aliases") or [])]:
            if alias:
                lookup.setdefault(_token(alias), entity_id)
    return ids, lookup


def _resolve(value: Any, valid_ids: set[str], lookup: dict[str, str]) -> str:
    result = str(value or "").strip()
    return result if result in valid_ids else lookup.get(_token(result), result)


def _split_dialogue_speaker_turns(
    shots: list[Any],
    character_ids: set[str],
    character_lookup: dict[str, str],
    character_names: dict[str, str],
) -> list[Any]:
    """Split provider-combined conversations into ordered single-speaker clips."""
    expanded: list[Any] = []
    for raw in shots:
        if not isinstance(raw, dict):
            expanded.append(raw)
            continue
        dialogue = raw.get("dialogueBeats") if isinstance(raw.get("dialogueBeats"), list) else []
        groups: list[tuple[str, list[Any]]] = []
        for beat in dialogue:
            if not isinstance(beat, dict):
                # Keep malformed data in place so the authoritative validator
                # below returns its precise error instead of silently dropping it.
                speaker = ""
            else:
                speaker = _resolve(beat.get("characterId"), character_ids, character_lookup)
            if groups and groups[-1][0] == speaker:
                groups[-1][1].append(beat)
            else:
                groups.append((speaker, [beat]))
        distinct = {speaker for speaker, _beats in groups if speaker}
        if len(distinct) <= 1:
            expanded.append(raw)
            continue

        base_id = str(raw.get("id") or f"shot_{len(expanded) + 1}").strip()
        previous_id = str(raw.get("continuityFromShotId") or "")
        for group_index, (speaker, beats) in enumerate(groups, start=1):
            clone = copy.deepcopy(raw)
            clone_id = base_id if group_index == 1 else f"{base_id}_turn_{group_index}"
            clone["id"] = clone_id
            clone["dialogueBeats"] = beats
            clone["speakingCharacterIds"] = [speaker] if speaker else []
            clone["primarySpeakerId"] = speaker
            clone["continuityFromShotId"] = previous_id
            if group_index > 1:
                label = character_names.get(speaker, speaker or "the next speaker")
                clone["action"] = (
                    f"{str(raw.get('action') or '').strip()} Conversational coverage shifts to {label}."
                ).strip()
                clone["prompt"] = (
                    f"{str(raw.get('prompt') or '').strip()} Single-speaker coverage on {label}; "
                    "the other visible characters listen without speaking."
                ).strip()
            expanded.append(clone)
            previous_id = clone_id
    return expanded


def _shot_complexity(shot: dict) -> tuple[int, int, int]:
    dialogue = shot.get("dialogueBeats") if isinstance(shot.get("dialogueBeats"), list) else []
    dialogue_words = sum(
        len(str(beat.get("text") or "").split())
        for beat in dialogue if isinstance(beat, dict)
    )
    action_words = len(str(shot.get("action") or "").split())
    return dialogue_words * 2 + action_words, dialogue_words, action_words


def _assign_series_shot_durations(shots: list[dict], target: float) -> None:
    """Allocate a near-target runtime with deterministic 5/10/15-second clips."""
    if not shots:
        return
    durations = [SERIES_SHOT_IDEAL_SECONDS for _shot in shots]
    target_units = max(len(shots), min(len(shots) * 3, int(math.floor(target / 5.0 + 0.5))))
    current_units = len(shots) * 2
    complexity = [_shot_complexity(shot) for shot in shots]

    if target_units < current_units:
        for index in sorted(range(len(shots)), key=lambda value: (complexity[value], value)):
            if current_units <= target_units:
                break
            durations[index] = 5
            current_units -= 1
    elif target_units > current_units:
        for index in sorted(range(len(shots)), key=lambda value: (complexity[value], -value), reverse=True):
            if current_units >= target_units:
                break
            durations[index] = 15
            current_units += 1

    # At an approximately ten-second average, exchange concise coverage for
    # longer dialogue/action beats without changing the episode total.
    short = [
        index for index, (_score, dialogue_words, action_words) in enumerate(complexity)
        if durations[index] == 10 and dialogue_words <= 8 and action_words <= 14
    ]
    long = [
        index for index, (_score, dialogue_words, action_words) in enumerate(complexity)
        if durations[index] == 10 and (dialogue_words >= 18 or action_words >= 24)
    ]
    for short_index, long_index in zip(short[:max(1, len(shots) // 4)], reversed(long)):
        if short_index == long_index:
            continue
        durations[short_index] = 5
        durations[long_index] = 15

    for shot, duration in zip(shots, durations):
        shot["durationSeconds"] = duration


def normalize_planning_result(stage: str, result: Any, series: dict, episode: dict) -> dict:
    if not isinstance(result, dict):
        raise ValueError(f"Series Lab {stage} response is not an object")
    normalized = copy.deepcopy(result)
    character_ids, character_lookup = _resolver([
        item for item in series.get("characters", []) if isinstance(item, dict)
    ])
    location_ids, location_lookup = _resolver([
        item for item in series.get("locations", []) if isinstance(item, dict)
    ])
    prop_ids, prop_lookup = _resolver([
        item for item in series.get("props", []) if isinstance(item, dict)
    ])
    if stage == "outline":
        outline = normalized.get("outline")
        if not isinstance(outline, dict) or not isinstance(outline.get("beats"), list):
            raise ValueError("Series outline is incomplete")
        outline["beats"] = [str(item).strip() for item in outline["beats"] if str(item).strip()][:12]
        if not outline["beats"]:
            raise ValueError("Series outline has no beats")
        return {"outline": outline}
    if stage == "script":
        scenes = normalized.get("script")
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("Series script has no scenes")
        for index, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                raise ValueError(f"Series scene {index + 1} is invalid")
            # Provider IDs are untrusted aliases. Assign the persisted UID here
            # so later stages can only reference one canonical scene identity.
            scene_id = _planning_uid("scene")
            scene["id"] = scene_id
            scene["order"] = index + 1
            scene["locationId"] = _resolve(scene.get("locationId"), location_ids, location_lookup)
            if scene["locationId"] not in location_ids:
                raise ValueError(f"Scene {scene_id} uses unknown location {scene['locationId']}")
            participants = []
            for raw in scene.get("participatingCharacterIds", []):
                resolved = _resolve(raw, character_ids, character_lookup)
                if resolved not in character_ids:
                    raise ValueError(f"Scene {scene_id} uses unknown character {resolved}")
                if resolved not in participants:
                    participants.append(resolved)
            scene["participatingCharacterIds"] = participants
            beats = scene.get("beats") if isinstance(scene.get("beats"), list) else []
            for beat_index, beat in enumerate(beats):
                if not isinstance(beat, dict):
                    raise ValueError(f"Scene {scene_id} has invalid beat {beat_index + 1}")
                beat["id"] = _planning_uid("scene_beat")
            scene["beats"] = beats
            dialogue = scene.get("dialogue") if isinstance(scene.get("dialogue"), list) else []
            for beat in dialogue:
                if not isinstance(beat, dict):
                    raise ValueError(f"Scene {scene_id} has invalid dialogue")
                character_id = _resolve(beat.get("characterId"), character_ids, character_lookup)
                if character_id not in character_ids:
                    raise ValueError(f"Scene {scene_id} dialogue uses unknown character {character_id}")
                beat["id"] = _planning_uid("dialogue")
                beat["characterId"] = character_id
                if character_id not in participants:
                    participants.append(character_id)
            scene["dialogue"] = dialogue
        return {"script": scenes}
    if stage == "shots":
        shots = normalized.get("shots")
        if not isinstance(shots, list):
            raise ValueError("Complete Series Lab shot plans require a shots array")
        character_names = {
            str(item.get("id")): str(item.get("name") or item.get("id"))
            for item in series.get("characters", [])
            if isinstance(item, dict) and item.get("id")
        }
        shots = _split_dialogue_speaker_turns(
            shots, character_ids, character_lookup, character_names,
        )
        profile = series_shot_count_profile(episode)
        if not int(profile["minimum"]) <= len(shots) <= int(profile["maximum"]):
            raise ValueError(
                f"Series shot plan for {float(profile['target']):g}s requires "
                f"{int(profile['minimum'])}–{int(profile['maximum'])} clips at 5–15 seconds each "
                f"(ideal about {int(profile['ideal'])}); received {len(shots)}"
            )
        provider_shot_ids: dict[str, str] = {}
        for index, shot in enumerate(shots):
            if not isinstance(shot, dict):
                raise ValueError(f"Series shot {index + 1} is invalid")
            provider_id = str(shot.get("id") or f"provider_shot_{index + 1}").strip()
            if provider_id in provider_shot_ids:
                raise ValueError(
                    f"Series shot plan repeats provider shot ID {provider_id}; every shot alias must be unique"
                )
            provider_shot_ids[provider_id] = _planning_uid("shot")
        script_scenes = [
            item for item in episode.get("script", [])
            if isinstance(item, dict) and item.get("id")
        ]
        scene_ids = {str(item.get("id")) for item in script_scenes}
        scenes_by_dialogue_id: dict[str, set[str]] = {}
        scenes_by_location_id: dict[str, list[str]] = {}
        for scene in script_scenes:
            scene_id = str(scene.get("id"))
            location_id = str(scene.get("locationId") or "")
            if location_id:
                scenes_by_location_id.setdefault(location_id, []).append(scene_id)
            for beat in scene.get("dialogue", []):
                if isinstance(beat, dict) and beat.get("id"):
                    scenes_by_dialogue_id.setdefault(str(beat["id"]), set()).add(scene_id)
        for index, shot in enumerate(shots):
            if not isinstance(shot, dict):
                raise ValueError(f"Series shot {index + 1} is invalid")
            provider_id = str(shot.get("id") or f"provider_shot_{index + 1}").strip()
            shot_id = provider_shot_ids[provider_id]
            shot["id"] = shot_id
            shot["order"] = index + 1
            shot["sceneId"] = str(shot.get("sceneId") or "").strip()
            if shot["sceneId"] not in scene_ids:
                dialogue_scene_ids: set[str] = set()
                for beat in shot.get("dialogueBeats", []):
                    if not isinstance(beat, dict) or not beat.get("id"):
                        continue
                    dialogue_scene_ids.update(scenes_by_dialogue_id.get(str(beat["id"]), set()))
                if len(dialogue_scene_ids) == 1:
                    shot["sceneId"] = next(iter(dialogue_scene_ids))
                else:
                    resolved_location = _resolve(
                        shot.get("locationId"), location_ids, location_lookup,
                    )
                    location_scenes = scenes_by_location_id.get(resolved_location, [])
                    if len(location_scenes) == 1:
                        shot["sceneId"] = location_scenes[0]
            if shot["sceneId"] not in scene_ids:
                valid_scene_ids = ", ".join(sorted(scene_ids)) or "(none)"
                raise ValueError(
                    f"Shot {shot_id} uses unknown scene {shot['sceneId']}; "
                    f"valid scene IDs: {valid_scene_ids}"
                )
            visible = []
            for raw in shot.get("visibleCharacterIds", []):
                resolved = _resolve(raw, character_ids, character_lookup)
                if resolved not in character_ids:
                    raise ValueError(f"Shot {shot_id} uses unknown visible character {resolved}")
                if resolved not in visible:
                    visible.append(resolved)
            raw_continuity_id = str(shot.get("continuityFromShotId") or "").strip()
            if raw_continuity_id and raw_continuity_id not in provider_shot_ids:
                raise ValueError(
                    f"Shot {shot_id} references unknown continuity shot {raw_continuity_id}"
                )
            shot["continuityFromShotId"] = (
                provider_shot_ids[raw_continuity_id] if raw_continuity_id else ""
            )
            dialogue = shot.get("dialogueBeats") if isinstance(shot.get("dialogueBeats"), list) else []
            dialogue_speakers = []
            for dialogue_index, beat in enumerate(dialogue):
                if not isinstance(beat, dict):
                    raise ValueError(f"Shot {shot_id} has invalid dialogue")
                resolved = _resolve(beat.get("characterId"), character_ids, character_lookup)
                if resolved not in character_ids:
                    raise ValueError(f"Shot {shot_id} dialogue uses unknown character {resolved}")
                if resolved not in visible:
                    raise ValueError(f"Shot {shot_id} speaker {resolved} is not visible")
                # Shot dialogue IDs are runtime-local identifiers. Providers
                # often copy the source scene beat ID into a later shot, which
                # makes canon validation report a false cross-shot reference.
                # Re-key them deterministically to the owning shot while
                # preserving the actual line, speaker and delivery.
                beat["id"] = _planning_uid("shot_dialogue")
                beat["characterId"] = resolved
                if resolved not in dialogue_speakers:
                    dialogue_speakers.append(resolved)
            if len(dialogue_speakers) > 1:
                raise ValueError(
                    f"Shot {shot_id} contains dialogue from {len(dialogue_speakers)} speakers; "
                    "split every speaker turn across separate shots"
                )
            shot["dialogueBeats"] = dialogue

            # Providers occasionally populate speakingCharacterIds with every
            # visible participant. Dialogue beats are the authoritative proof
            # of who actually speaks, so repair that harmless schema drift
            # without dropping any spoken line. Explicit speakers only fill an
            # otherwise silent/underspecified shot, and never exceed the
            # single-speaker Series clip contract.
            declared_speakers = []
            for raw in shot.get("speakingCharacterIds", []):
                resolved = _resolve(raw, character_ids, character_lookup)
                if resolved not in visible:
                    raise ValueError(f"Shot {shot_id} speaker {resolved} is not visible")
                if resolved not in declared_speakers:
                    declared_speakers.append(resolved)
            speakers = list(dialogue_speakers)
            for resolved in declared_speakers:
                if len(speakers) >= 1:
                    break
                if resolved not in speakers:
                    speakers.append(resolved)
            shot["visibleCharacterIds"] = visible
            shot["speakingCharacterIds"] = speakers
            primary = _resolve(shot.get("primarySpeakerId"), character_ids, character_lookup)
            shot["primarySpeakerId"] = primary if primary in speakers else (speakers[0] if speakers else "")
            location_id = _resolve(shot.get("locationId"), location_ids, location_lookup)
            if location_id and location_id not in location_ids:
                raise ValueError(f"Shot {shot_id} uses unknown location {location_id}")
            shot["locationId"] = location_id
            resolved_props = []
            for raw in shot.get("propIds", []):
                resolved = _resolve(raw, prop_ids, prop_lookup)
                if resolved not in prop_ids:
                    raise ValueError(f"Shot {shot_id} uses unknown prop {resolved}")
                if resolved not in resolved_props:
                    resolved_props.append(resolved)
            shot["propIds"] = resolved_props
            shot["renderStrategy"] = shot.get("renderStrategy") if shot.get("renderStrategy") in {
                "auto", "direct", "first_frame", "references", "first_last"
            } else "auto"
            shot["referencePolicy"] = {
                "mode": "automatic", "manualIncludeAssetIds": [], "manualExcludeAssetIds": [],
            }
            shot["attempts"] = []
        _assign_series_shot_durations(shots, float(profile["target"]))
        from .series_render import apply_series_shot_duration
        for shot in shots:
            apply_series_shot_duration(series, shot)
        return {"shots": shots}
    if stage == "canon_validation":
        issues = normalized.get("issues")
        if not isinstance(issues, list):
            raise ValueError("Canon validation response has no issues array")
        normalized_issues = []
        for item in issues[:30]:
            if not isinstance(item, dict):
                continue
            item["id"] = _planning_uid("continuity_issue")
            normalized_issues.append(item)
        return {"issues": normalized_issues}
    if stage == "canon_delta":
        result_delta = {}
        existing_ids = {
            str(item.get("id")) for item in episode.get("canonSnapshot", {}).get("currentFacts", [])
            if isinstance(item, dict) and item.get("id")
        }
        for group in ("add", "change"):
            items = normalized.get(group)
            if not isinstance(items, list):
                raise ValueError(f"Canon delta {group} is not an array")
            result_delta[group] = []
            for index, item in enumerate(items[:12]):
                if not isinstance(item, dict):
                    continue
                provider_item_id = str(item.get("id") or "")
                item_id = _planning_uid("fact") if group == "add" else provider_item_id
                if group == "change" and item_id not in existing_ids:
                    raise ValueError(f"Canon change references unknown fact {item_id}")
                result_delta[group].append({
                    "id": item_id, "description": str(item.get("description") or ""),
                    "sourceEpisodeId": episode["id"], "status": "proposed", "decision": "pending",
                })
        retires = normalized.get("retire")
        if not isinstance(retires, list):
            raise ValueError("Canon delta retire is not an array")
        result_delta["retire"] = []
        for item in retires[:12]:
            if not isinstance(item, dict):
                continue
            fact_id = str(item.get("factId") or "")
            if fact_id not in existing_ids:
                raise ValueError(f"Canon retire references unknown fact {fact_id}")
            result_delta["retire"].append({"factId": fact_id, "decision": "pending"})
        return result_delta
    raise ValueError("Unsupported Series Lab planning stage")


def apply_planning_stage(episode: dict, stage: str, result: dict) -> dict:
    updated = copy.deepcopy(episode)
    if stage == "outline":
        updated["outline"] = copy.deepcopy(result["outline"])
        updated["status"] = "outline"
    elif stage == "script":
        updated["script"] = copy.deepcopy(result["script"])
        updated["status"] = "script"
    elif stage == "shots":
        updated["shots"] = copy.deepcopy(result["shots"])
        updated["status"] = "shot_plan"
    elif stage == "canon_validation":
        updated["continuityIssues"] = copy.deepcopy(result["issues"])
    elif stage == "canon_delta":
        updated["proposedCanonDelta"] = {
            "baseRevision": updated["canonRevisionAtCreation"],
            "sourceEpisodeId": updated["id"],
            **copy.deepcopy(result),
        }
    else:
        raise ValueError("Unsupported Series Lab planning stage")
    return updated
