import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.lips_creator import create_lips_creator_router
from services.character_kit_library import (
    LIPS_CREATOR_LIBRARY_FILENAME, CharacterKitRevisionConflict,
    normalize_character_kit, patch_character_kit, read_character_kit_library,
)


def pack():
    return {"version": 1, "id": "lips", "name": "Lips", "style": "cutout", "poses": {}, "eyes": {},
            "mouth": {}, "anchors": {}, "provenance": [], "mouthMapping": {"A": "round", "U": "round"},
            "mouthPrompts": {"round": "smaller lips"}}


def test_lips_collection_is_separate_revision_guarded_and_workspace_scoped(tmp_path):
    patch_character_kit(str(tmp_path / "a"), "lips", pack(), base_revision=0)
    options = {"library_filename": LIPS_CREATOR_LIBRARY_FILENAME}
    first = patch_character_kit(str(tmp_path / "a"), "lips", pack(), base_revision=0, **options)
    assert first["revision"] == 1
    with pytest.raises(CharacterKitRevisionConflict):
        patch_character_kit(str(tmp_path / "a"), "lips", pack(), base_revision=0, **options)
    assert read_character_kit_library(str(tmp_path / "b"), **options)["kits"] == {}
    assert (tmp_path / "a" / LIPS_CREATOR_LIBRARY_FILENAME).is_file()
    assert read_character_kit_library(str(tmp_path / "a"))["revision"] == 1
    assert first["kits"]["lips"]["mouthMapping"] == {"A": "round", "U": "round"}


@pytest.mark.parametrize("mapping", [{"Z": "wide"}, {"A": "smile"}, {"A": []}, {"A": True}, []])
def test_invalid_sound_assignments_are_rejected(mapping):
    with pytest.raises(ValueError, match="sound assignments"):
        normalize_character_kit({**pack(), "mouthMapping": mapping})


def test_lips_http_create_read_conflict_delete_and_character_isolation(tmp_path):
    app = FastAPI()
    app.include_router(create_lips_creator_router(lambda name: str(tmp_path / (name or "default"))), prefix="/api/v1/character-kits")
    client = TestClient(app)
    root = "/api/v1/character-kits/lips-creator"
    assert client.get(root + "/library?workspace=a").json()["revision"] == 0
    body = {"workspace": "a", "baseRevision": 0, "kit": pack()}
    saved = client.patch(root + "/packs/lips", json=body)
    assert saved.status_code == 200
    assert client.patch(root + "/packs/lips", json=body).status_code == 409
    assert client.get(root + "/library?workspace=b").json()["kits"] == {}
    assert read_character_kit_library(str(tmp_path / "a"))["kits"] == {}
    invalid = {**body, "baseRevision": 1, "kit": {**pack(), "mouthMapping": {"A": "unknown"}}}
    assert client.patch(root + "/packs/lips", json=invalid).status_code == 400
    deleted = client.request("DELETE", root + "/packs/lips", json={"workspace": "a", "baseRevision": 1})
    assert deleted.status_code == 200 and deleted.json()["kits"] == {}
    assert (tmp_path / "a" / (LIPS_CREATOR_LIBRARY_FILENAME + ".v1.json")).exists()


def test_saved_candidates_do_not_replace_the_approved_mouth(tmp_path):
    current = {"id": "current", "name": "Current", "source": "/api/v1/uploads/current.png", "kind": "overlay", "alphaStatus": "transparent", "reviewState": "approved"}
    candidate = {**current, "id": "candidate", "name": "Candidate", "source": "/api/v1/uploads/new.png", "reviewState": "pending"}
    value = {**pack(), "mouth": {"wide": current}, "mouthCandidates": {"wide": candidate}}
    options = {"library_filename": LIPS_CREATOR_LIBRARY_FILENAME}
    patch_character_kit(str(tmp_path), "lips", value, base_revision=0, **options)
    restored = read_character_kit_library(str(tmp_path), **options)["kits"]["lips"]
    assert restored["mouth"]["wide"]["source"] == current["source"]
    assert restored["mouthCandidates"]["wide"]["source"] == candidate["source"]
    assert restored["mouthCandidates"]["wide"]["reviewState"] == "pending"


def test_description_mode_survives_save_even_with_a_previous_reference(tmp_path):
    reference = {"id": "ref", "name": "Reference", "source": "/reference.png", "kind": "image", "alphaStatus": "opaque", "reviewState": "approved"}
    options = {"library_filename": LIPS_CREATOR_LIBRARY_FILENAME}
    patch_character_kit(str(tmp_path), "lips", {**pack(), "base": reference, "mouthGenerationMode": "description"}, base_revision=0, **options)
    restored = read_character_kit_library(str(tmp_path), **options)["kits"]["lips"]
    assert restored["mouthGenerationMode"] == "description"
    assert restored["base"]["source"] == reference["source"]
    with pytest.raises(ValueError, match="generation mode"):
        normalize_character_kit({**pack(), "mouthGenerationMode": "invalid"})
