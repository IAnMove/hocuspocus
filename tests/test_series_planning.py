import copy
import re

import pytest

from services.series_library import create_series_episode, create_series_project
from services.series_planning import (
    apply_planning_stage,
    canon_preparation_prompt,
    canon_preparation_schema,
    known_series_bootstrap_prompt,
    known_series_bootstrap_schema,
    merge_series_canon_proposal,
    normalize_canon_preparation,
    normalize_known_series_bootstrap,
    normalize_planning_result,
    planning_output_token_budget,
    planning_prompt,
    planning_schema,
    planning_stages,
    series_shot_count_profile,
)


def prepared():
    series = create_series_project()
    series["characters"] = [
        {"id": "char_a", "name": "Ada", "aliases": [], "referenceAssetIds": []},
        {"id": "char_b", "name": "Bo", "aliases": [], "referenceAssetIds": []},
    ]
    series["locations"] = [{"id": "loc_a", "name": "Lab", "referenceAssetIds": []}]
    episode = create_series_episode(series, title="Pilot", premise="A test")
    return series, episode


def assert_uid(value: str, prefix: str) -> None:
    assert re.fullmatch(rf"{prefix}_[0-9a-f]{{32}}", value)


def script_result():
    return {"script": [{
        "id": "scene_a", "order": 7, "locationId": "Lab", "locationVariantId": "",
        "time": "night", "participatingCharacterIds": ["Ada", "char_b"],
        "purpose": "test", "entryState": "calm", "exitState": "alert",
        "beats": [{"id": "beat_a", "kind": "dialogue", "summary": "Ada speaks"}],
        "dialogue": [{
            "id": "line_a", "characterId": "Ada", "text": "Ready?",
            "emotion": "focused", "delivery": "quiet",
        }],
    }]}


def shot_result(count=8):
    return {"shots": [{
        "id": f"shot_{index + 1}", "sceneId": "scene_a", "order": index + 10,
        "durationSeconds": 8, "framing": "medium", "camera": "locked", "action": "Test",
        "dialogueBeats": [], "visibleCharacterIds": ["Ada", "Bo"],
        "speakingCharacterIds": ["Ada"], "primarySpeakerId": "Ada",
        "locationId": "Lab", "locationVariantId": "", "wardrobeByCharacterId": {},
        "propIds": [], "emotionalStateByCharacterId": {"char_a": "focused"},
        "continuityFromShotId": "", "renderStrategy": "auto",
        "prompt": "Ada and Bo in the lab", "negativePrompt": "captions",
    } for index in range(count)]}


def test_scopes_and_schemas_are_bounded():
    assert planning_stages("outline") == ["outline"]
    assert planning_stages("complete")[-1] == "canon_delta"
    shot_schema = planning_schema("shots")["properties"]["shots"]
    assert shot_schema["minItems"] == 5
    assert shot_schema["maxItems"] == 15
    assert shot_schema["items"]["properties"]["durationSeconds"]["enum"] == [5, 10, 15]
    assert shot_schema["items"]["properties"]["speakingCharacterIds"]["maxItems"] == 1
    long_episode = {"targetDurationSeconds": 600}
    assert series_shot_count_profile(long_episode) == {
        "target": 600.0, "minimum": 40, "ideal": 60, "maximum": 120,
    }
    assert planning_schema("shots", long_episode)["properties"]["shots"]["minItems"] == 40
    assert planning_output_token_budget("shots", long_episode) > 9000
    assert canon_preparation_schema()["properties"]["characters"]["maxItems"] == 2
    bootstrap = known_series_bootstrap_schema()["properties"]
    assert bootstrap["characters"]["maxItems"] == 12
    assert bootstrap["relationships"]["maxItems"] == 24
    assert bootstrap["props"]["maxItems"] == 12
    with pytest.raises(ValueError):
        planning_stages("unknown")


def test_prompt_uses_frozen_snapshot_and_excludes_attempt_history():
    series, episode = prepared()
    episode["attempts"] = [{"huge": "secret runtime history"}]
    series["priorEpisodeSummaries"] = [{
        "id": "episode_previous", "number": 1, "title": "Previously",
        "outlineBeats": ["Ada discovered the signal"],
    }]
    prompt, system = planning_prompt("outline", series, episode, "A new idea")
    assert "A new idea" in prompt
    assert "canonSnapshot" in prompt
    assert "secret runtime history" not in prompt
    assert "Ada discovered the signal" in prompt
    assert "never rewrite" in system

    episode["script"] = script_result()["script"]
    shots_prompt, _ = planning_prompt("shots", series, episode)
    assert 'The only valid scene IDs are ["scene_a"]' in shots_prompt


def test_script_resolves_labels_to_authoritative_ids():
    series, episode = prepared()
    result = normalize_planning_result("script", script_result(), series, episode)
    scene = result["script"][0]
    assert_uid(scene["id"], "scene")
    assert scene["order"] == 1
    assert scene["locationId"] == "loc_a"
    assert scene["participatingCharacterIds"] == ["char_a", "char_b"]
    assert scene["dialogue"][0]["characterId"] == "char_a"
    assert_uid(scene["beats"][0]["id"], "scene_beat")
    assert_uid(scene["dialogue"][0]["id"], "dialogue")
    assert len({scene["id"], scene["beats"][0]["id"], scene["dialogue"][0]["id"]}) == 3


def test_shots_require_visible_speaker_ids_and_keep_attempts_empty():
    series, episode = prepared()
    episode = apply_planning_stage(episode, "script", normalize_planning_result(
        "script", script_result(), series, episode,
    ))
    result = normalize_planning_result("shots", shot_result(), series, episode)
    assert len(result["shots"]) == 8
    assert result["shots"][0]["visibleCharacterIds"] == ["char_a", "char_b"]
    assert result["shots"][0]["speakingCharacterIds"] == ["char_a"]
    assert result["shots"][0]["attempts"] == []
    assert result["shots"][0]["referencePolicy"]["mode"] == "automatic"

    invalid = shot_result()
    invalid["shots"][0]["visibleCharacterIds"] = ["Bo"]
    with pytest.raises(ValueError, match="not visible"):
        normalize_planning_result("shots", invalid, series, episode)


def test_shots_repair_invented_scene_id_only_from_authoritative_evidence():
    series, episode = prepared()
    episode = apply_planning_stage(episode, "script", normalize_planning_result(
        "script", script_result(), series, episode,
    ))
    raw = shot_result()
    raw["shots"][0]["sceneId"] = "scn_lab_activation"
    raw["shots"][0]["dialogueBeats"] = [{
        "id": "line_a", "characterId": "Ada", "text": "Ready?",
        "emotion": "focused", "delivery": "quiet",
    }]

    normalized = normalize_planning_result("shots", raw, series, episode)["shots"]
    assert normalized[0]["sceneId"] == episode["script"][0]["id"]

    ambiguous = shot_result()
    ambiguous["shots"][0]["sceneId"] = "scn_invented"
    episode["script"].append({
        **copy.deepcopy(episode["script"][0]),
        "id": "scene_b",
        "dialogue": [{
            **copy.deepcopy(episode["script"][0]["dialogue"][0]),
            "id": "line_b",
        }],
    })
    with pytest.raises(ValueError, match="valid scene IDs:.*scene_b"):
        normalize_planning_result("shots", ambiguous, series, episode)


def test_shots_split_inflated_declared_speakers_without_dropping_dialogue():
    series, episode = prepared()
    series["characters"].append({
        "id": "char_c", "name": "Cy", "aliases": [], "referenceAssetIds": [],
    })
    episode = apply_planning_stage(episode, "script", normalize_planning_result(
        "script", script_result(), series, episode,
    ))
    raw = shot_result()
    first = raw["shots"][0]
    first["visibleCharacterIds"] = ["Ada", "Bo", "Cy"]
    first["speakingCharacterIds"] = ["Ada", "Bo", "Cy"]
    first["dialogueBeats"] = [{
        "id": "line_a", "characterId": "Ada", "text": "Ready?",
        "emotion": "focused", "delivery": "quiet",
    }, {
        "id": "line_b", "characterId": "Bo", "text": "Ready.",
        "emotion": "calm", "delivery": "dry",
    }]

    normalized = normalize_planning_result("shots", raw, series, episode)["shots"]

    assert len(normalized) == 9
    assert normalized[0]["visibleCharacterIds"] == ["char_a", "char_b", "char_c"]
    assert normalized[0]["speakingCharacterIds"] == ["char_a"]
    assert normalized[1]["speakingCharacterIds"] == ["char_b"]
    assert normalized[1]["continuityFromShotId"] == normalized[0]["id"]
    assert_uid(normalized[0]["id"], "shot")
    assert_uid(normalized[1]["id"], "shot")
    assert_uid(normalized[0]["dialogueBeats"][0]["id"], "shot_dialogue")
    assert_uid(normalized[1]["dialogueBeats"][0]["id"], "shot_dialogue")
    assert len({
        normalized[0]["id"], normalized[1]["id"],
        normalized[0]["dialogueBeats"][0]["id"],
        normalized[1]["dialogueBeats"][0]["id"],
    }) == 4
    assert [
        line["characterId"]
        for shot in normalized[:2] for line in shot["dialogueBeats"]
    ] == ["char_a", "char_b"]


def test_shots_deterministically_split_three_actual_dialogue_speakers():
    series, episode = prepared()
    series["characters"].append({
        "id": "char_c", "name": "Cy", "aliases": [], "referenceAssetIds": [],
    })
    episode = apply_planning_stage(episode, "script", normalize_planning_result(
        "script", script_result(), series, episode,
    ))
    raw = shot_result()
    first = raw["shots"][0]
    first["visibleCharacterIds"] = ["Ada", "Bo", "Cy"]
    first["speakingCharacterIds"] = ["Ada", "Bo", "Cy"]
    first["dialogueBeats"] = [
        {
            "id": f"line_{character}", "characterId": character, "text": "Line",
            "emotion": "calm", "delivery": "dry",
        }
        for character in ("Ada", "Bo", "Cy")
    ]

    normalized = normalize_planning_result("shots", raw, series, episode)["shots"]
    assert len(normalized) == 10
    assert len({shot["id"] for shot in normalized}) == len(normalized)
    assert all(re.fullmatch(r"shot_[0-9a-f]{32}", shot["id"]) for shot in normalized)
    assert [shot["speakingCharacterIds"] for shot in normalized[:3]] == [
        ["char_a"], ["char_b"], ["char_c"],
    ]
    assert all(len(shot["speakingCharacterIds"]) <= 1 for shot in normalized)


def test_shots_reject_duplicate_provider_aliases_before_persisting_uids():
    series, episode = prepared()
    episode["script"] = script_result()["script"]
    raw = shot_result()
    raw["shots"][1]["id"] = raw["shots"][0]["id"]
    with pytest.raises(ValueError, match="repeats provider shot ID"):
        normalize_planning_result("shots", raw, series, episode)


def test_shot_count_scales_with_duration_and_clip_limits():
    series, episode = prepared()
    episode["script"] = script_result()["script"]
    with pytest.raises(ValueError, match="requires 5–15 clips at 5–15 seconds each"):
        normalize_planning_result("shots", shot_result(4), series, episode)
    episode["targetDurationSeconds"] = 600
    with pytest.raises(ValueError, match="requires 40–120 clips"):
        normalize_planning_result("shots", shot_result(12), series, episode)


def test_shot_durations_are_normalized_toward_episode_target():
    series, episode = prepared()
    episode["targetDurationSeconds"] = 80
    episode["script"] = script_result()["script"]
    raw = shot_result(8)
    for shot in raw["shots"]:
        shot["durationSeconds"] = 2
    normalized = normalize_planning_result("shots", raw, series, episode)["shots"]
    assert sum(shot["durationSeconds"] for shot in normalized) == pytest.approx(80)
    assert all(shot["durationSeconds"] in {5, 10, 15} for shot in normalized)
    assert max(shot["durationSeconds"] for shot in normalized) <= 15


def test_ten_minute_plan_uses_sixty_short_clips_without_long_video_substitution():
    series, episode = prepared()
    episode["targetDurationSeconds"] = 600
    episode["script"] = script_result()["script"]
    raw = shot_result(60)
    normalized = normalize_planning_result("shots", raw, series, episode)["shots"]
    assert len(normalized) == 60
    assert sum(shot["durationSeconds"] for shot in normalized) == 600
    assert set(shot["durationSeconds"] for shot in normalized) <= {5, 10, 15}


def test_apply_stages_never_mutates_canon_or_input():
    series, episode = prepared()
    original = copy.deepcopy(episode)
    updated = apply_planning_stage(episode, "outline", {"outline": {"beats": ["One"]}})
    assert episode == original
    assert updated["status"] == "outline"
    assert updated["canonSnapshot"] == original["canonSnapshot"]
    assert series["canon"]["revision"] == 1


def test_canon_delta_remains_pending_until_separate_commit():
    series, episode = prepared()
    result = normalize_planning_result("canon_delta", {
        "add": [{"id": "fact_new", "description": "New fact"}], "change": [], "retire": [],
    }, series, episode)
    updated = apply_planning_stage(episode, "canon_delta", result)
    added = updated["proposedCanonDelta"]["add"][0]
    assert added["decision"] == "pending"
    assert_uid(added["id"], "fact")
    assert added["id"] != "fact_new"
    assert series["canon"]["currentFacts"] == []


def test_canon_preparation_is_bounded_reviewable_and_preserves_current_facts():
    series, _episode = prepared()
    series["canon"]["currentFacts"] = [{"id": "fact_old", "description": "Established", "status": "approved"}]
    raw = {
        "canon": {
            "worldSummary": "A precise world", "immutableRules": [{"id": "rule one", "description": "No time travel"}],
            "forbiddenChanges": ["No resurrection"], "themes": ["trust"],
            "longArcs": [{"id": "arc one", "title": "Signal", "description": "Find its source"}],
        },
        "characters": [{
            "id": "ada", "name": "Ada", "role": "lead", "personality": "focused",
            "desire": "truth", "need": "trust", "flaw": "isolated", "longArc": "opens up",
            "voiceAndDialogue": "precise", "appearance": "short dark hair", "identityLock": "same face",
            "wardrobeVariants": [{"id": "ada default", "label": "Default", "description": "blue coat"}],
        }],
        "relationships": [],
        "locations": [{
            "id": "lab", "name": "Lab", "purpose": "research", "description": "circular lab",
            "variants": [{"id": "lab night", "label": "Night", "description": "emergency lights"}],
        }],
    }
    proposal = normalize_canon_preparation(raw, series)
    assert proposal["canon"]["currentFacts"][0]["id"] == "fact_old"
    assert proposal["characters"][0]["approval"] == "draft"
    assert proposal["characters"][0]["wardrobeVariants"][0]["id"] == "ada_default"
    assert proposal["locations"][0]["variants"][0]["referenceAssetIds"] == []
    prompt, _system = canon_preparation_prompt(series, "Keep it grounded")
    assert "Keep it grounded" in prompt


def test_known_series_bootstrap_is_rich_draft_and_resolves_character_names():
    series, _episode = prepared()
    raw = {
        "setup": {
            "title": "Known Show", "premise": "An established ensemble premise",
            "logline": "Familiar characters face new original situations", "format": "episodic",
            "defaultEpisodeDurationSeconds": 90, "language": "Español", "genre": "Comedia",
            "tone": "Observacional", "audience": "Adulto", "visualStyle": "Era-accurate television",
            "characterVisualStyle": "Stable fictional character silhouettes",
            "cameraLanguage": "Ensemble coverage", "masterUniversePrompt": "Preserve Known Show canon",
            "rightsNote": "Unofficial draft; verify publication rights.",
        },
        "canon": {
            "worldSummary": "Established world", "immutableRules": [{"id": "rule one", "description": "No magic"}],
            "currentFacts": [{"id": "fact one", "description": "The ensemble knows each other"}],
            "forbiddenChanges": ["Do not rewrite identities"], "themes": ["friendship"],
            "longArcs": [{"id": "arc one", "title": "Recurring tension", "description": "Never fully resolved"}],
            "timeline": [{"id": "time one", "description": "Status quo established", "occurredAt": "Original run"}],
        },
        "characters": [{
            "id": "lead one", "name": "Lead One", "aliases": ["Lead"], "role": "lead",
            "personality": "observant", "desire": "comfort", "need": "growth", "flaw": "avoidant",
            "longArc": "recurring stasis", "voiceAndDialogue": "dry conversational rhythm",
            "appearance": "established fictional appearance", "identityLock": "stable era and silhouette",
            "wardrobeVariants": [{"id": "lead default", "label": "Default", "description": "era-correct wardrobe"}],
        }, {
            "id": "friend two", "name": "Friend Two", "aliases": [], "role": "friend",
            "personality": "energetic", "desire": "recognition", "need": "patience", "flaw": "impulsive",
            "longArc": "recurring schemes", "voiceAndDialogue": "fast rhythm",
            "appearance": "established fictional appearance", "identityLock": "stable era and silhouette",
            "wardrobeVariants": [],
        }],
        "relationships": [{
            "id": "lead friend", "fromCharacterId": "Lead One", "toCharacterId": "Friend Two",
            "label": "friends", "dynamic": "mutual friction", "evolution": "returns to status quo",
        }],
        "locations": [{
            "id": "main place", "name": "Main Place", "purpose": "ensemble hub",
            "description": "recognizable established layout", "variants": [],
        }],
        "props": [{
            "id": "lead item", "name": "Lead Item", "kind": "personal",
            "description": "recurring object", "ownerCharacterId": "Lead", "variants": [],
        }],
    }
    proposal = normalize_known_series_bootstrap(raw, series)
    assert proposal["sourceMode"] == "known_universe_experimental"
    assert proposal["characters"][0]["approval"] == "draft"
    assert proposal["relationships"][0]["fromCharacterId"] == "lead_one"
    assert proposal["props"][0]["ownerCharacterId"] == "lead_one"
    assert proposal["canon"]["currentFacts"][0]["status"] == "draft"
    assert proposal["canon"]["timeline"][0]["occurredAt"] == "Original run"
    prompt, system = known_series_bootstrap_prompt(series, "Quiero nuevos capítulos de Seinfeld")
    assert "Quiero nuevos capítulos de Seinfeld" in prompt
    assert "NOT live web research" in system
    assert "Do not reproduce scripts" in system

    series["title"] = "Old title"
    series["characters"] = [{
        "id": "lead_one", "name": "Old lead", "referenceAssetIds": ["asset_portrait"],
        "primaryReferenceAssetId": "asset_portrait", "currentState": {"mood": "saved"},
    }]
    series["assets"] = {"asset_portrait": {"id": "asset_portrait"}}
    series["episodesById"] = {"episode_saved": {"id": "episode_saved"}}
    merged = merge_series_canon_proposal(series, proposal, bootstrap_known_series=True)
    assert merged["title"] == "Known Show"
    assert merged["characters"][0]["referenceAssetIds"] == ["asset_portrait"]
    assert merged["characters"][0]["currentState"] == {"mood": "saved"}
    assert merged["assets"] == series["assets"]
    assert merged["episodesById"] == series["episodesById"]
    assert merged["canon"]["approval"] == "draft"
    assert merged["canon"]["currentFacts"][0]["id"] == "fact_one"
