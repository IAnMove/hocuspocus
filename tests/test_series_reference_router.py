import copy
import json
from pathlib import Path

from services.series_library import normalize_series_library
from services.series_reference_router import route_shot_references


EXAMPLE = Path(__file__).parents[1] / "docs" / "series-lab" / "example-series-library-v1.json"


def fixtures():
    library = normalize_series_library(json.loads(EXAMPLE.read_text(encoding="utf-8")), "default")
    series = library["seriesById"]["series_signal"]
    episode = series["episodesById"]["episode_1"]
    return series, episode


def test_character_location_prop_priority_and_stable_order():
    series, episode = fixtures()
    shot = episode["shots"][0]
    first = route_shot_references(series, episode, shot)
    second = route_shot_references(copy.deepcopy(series), copy.deepcopy(episode), copy.deepcopy(shot))
    assert first == second
    roles = [item["referenceRole"] for item in first["selected"]]
    assert roles[:2] == ["primary_speaker_identity", "visible_character_identity"]
    assert "location_variant" in roles
    assert "plot_critical_prop" in roles


def test_absent_character_never_routes_even_manual():
    series, episode = fixtures()
    shot = copy.deepcopy(episode["shots"][6])  # only Mara is visible
    shot["referencePolicy"]["manualIncludeAssetIds"] = ["asset_ivo"]
    result = route_shot_references(series, episode, shot)
    assert "asset_ivo" not in [item["assetId"] for item in result["selected"]]
    assert any("absent" in warning for warning in result["warnings"])


def test_primary_speaker_wins_constrained_budget():
    series, episode = fixtures()
    shot = copy.deepcopy(episode["shots"][0])
    shot["referencePolicy"]["maxReferencesOverride"] = 1
    result = route_shot_references(series, episode, shot)
    assert [item["assetId"] for item in result["selected"]] == ["asset_mara"]
    assert result["omitted"]


def test_location_is_never_inferred_from_bible():
    series, episode = fixtures()
    shot = copy.deepcopy(episode["shots"][7])
    shot.pop("locationId", None)
    result = route_shot_references(series, episode, shot)
    assert not any(item["entityType"] == "location" for item in result["selected"])


def test_location_uses_id_first_then_label_only_as_migration_fallback():
    series, episode = fixtures()
    shot = copy.deepcopy(episode["shots"][0])
    location = series["locations"][0]
    shot["locationId"] = location["name"]
    migrated = route_shot_references(series, episode, shot)
    assert any(
        item["entityType"] == "location" and item["entityId"] == location["id"]
        for item in migrated["selected"]
    )
    second = copy.deepcopy(location)
    second.update({"id": location["name"], "name": "Different", "referenceAssetIds": []})
    series["locations"].append(second)
    exact = route_shot_references(series, episode, shot)
    assert not any(
        item["entityType"] == "location" and item["entityId"] == location["id"]
        for item in exact["selected"]
    )


def test_direct_mode_submits_no_accidental_references():
    series, episode = fixtures()
    shot = copy.deepcopy(episode["shots"][0])
    shot["renderStrategy"] = "direct"
    result = route_shot_references(series, episode, shot)
    assert result["strategy"] == "direct"
    assert result["selected"] == []


def test_reference_mode_with_empty_set_falls_back_to_direct():
    series, episode = fixtures()
    shot = copy.deepcopy(episode["shots"][7])
    shot["renderStrategy"] = "references"
    shot.pop("locationId", None)
    result = route_shot_references(series, episode, shot)
    assert result["strategy"] == "direct"
    assert result["errors"]


def test_crowd_requires_composed_start_frame_warning():
    series, episode = fixtures()
    third = copy.deepcopy(series["characters"][0])
    third.update({"id": "char_third", "name": "Third", "referenceAssetIds": []})
    series["characters"].append(third)
    shot = copy.deepcopy(episode["shots"][0])
    shot["visibleCharacterIds"].append("char_third")
    result = route_shot_references(series, episode, shot)
    assert result["strategy"] == "references"
    assert any("composed start frame" in warning for warning in result["warnings"])
    assert result["errors"]


def test_auto_crowd_without_references_uses_direct_generation_with_warning():
    series, episode = fixtures()
    third = copy.deepcopy(series["characters"][0])
    third.update({"id": "char_third", "name": "Third", "referenceAssetIds": []})
    series["characters"].append(third)
    for character in series["characters"]:
        character["referenceAssetIds"] = []
        character.pop("primaryReferenceAssetId", None)
    series["locations"] = []
    series["props"] = []
    series["assets"] = {}
    shot = copy.deepcopy(episode["shots"][0])
    shot["visibleCharacterIds"].append("char_third")
    shot.pop("locationId", None)
    shot["propIds"] = []
    shot["renderStrategy"] = "auto"

    result = route_shot_references(series, episode, shot)

    assert result["strategy"] == "direct"
    assert result["selected"] == []
    assert result["errors"] == []
    assert any("improvise this crowd composition" in warning for warning in result["warnings"])


def test_auto_continuity_without_previous_output_uses_direct_generation():
    series, episode = fixtures()
    for character in series["characters"]:
        character["referenceAssetIds"] = []
        character.pop("primaryReferenceAssetId", None)
    series["locations"] = []
    series["props"] = []
    series["assets"] = {}
    shot = copy.deepcopy(episode["shots"][1])
    shot["continuityFromShotId"] = episode["shots"][0]["id"]
    shot.pop("locationId", None)
    shot["propIds"] = []
    shot["renderStrategy"] = "auto"

    result = route_shot_references(series, episode, shot)

    assert result["strategy"] == "direct"
    assert result["selected"] == []
    assert result["errors"] == []


def test_previous_video_routes_as_reference_not_fake_first_frame():
    series, episode = fixtures()
    previous = episode["shots"][0]
    previous["approvedAttemptId"] = "attempt_previous"
    previous["attempts"] = [{
        "id": "attempt_previous", "status": "completed", "outputAssetIds": ["asset_previous"],
    }]
    series["assets"]["asset_previous"] = {
        "id": "asset_previous", "kind": "video", "uri": "outputs/previous.mp4",
        "ownerType": "attempt", "ownerId": "attempt_previous", "metadata": {},
    }
    shot = copy.deepcopy(episode["shots"][1])
    shot["continuityFromShotId"] = previous["id"]
    result = route_shot_references(series, episode, shot)
    assert result["strategy"] == "references"
    assert result["selected"][0]["referenceRole"] == "previous_segment"


def test_first_last_capability_falls_back_with_warning():
    series, episode = fixtures()
    shot = copy.deepcopy(episode["shots"][0])
    shot["renderStrategy"] = "first_last"
    result = route_shot_references(series, episode, shot)
    assert result["strategy"] == "references"
    assert any("first-and-last" in warning for warning in result["warnings"])
