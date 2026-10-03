import copy
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.character_kit_face import create_character_kit_face_router

DIGEST = "a" * 64
FACE = {"meshIndex": 0, "center": [0, 1, 0], "size": [.1, .1], "skin": [.5, .3, .2],
        "eyes": {"left": [-.1, 1, 0], "right": [.1, 1, 0], "size": [.04, .02],
                 "skinLeft": [.5, .3, .2], "skinRight": [.5, .3, .2]}}
BASE = "/api/v1/character-kits/speech/profiles/"

def client_for(tmp_path):
    app = FastAPI()
    app.include_router(create_character_kit_face_router(
        workspace_dir=lambda name: str(tmp_path / name), uploads_root=lambda: str(tmp_path / "uploads")))
    return TestClient(app)

def test_profile_roundtrip_isolated_and_old_revisions_preserved(tmp_path):
    client = client_for(tmp_path)
    path = BASE + DIGEST
    data = {"workspace": "episode-one", "revision": 0, "settings": {"face": FACE}}
    assert client.get(path, params={"workspace": data["workspace"]}).status_code == 404
    saved = client.put(path, json=data)
    assert saved.status_code == 200 and saved.json()["revision"] == 1
    assert client.get(path, params={"workspace": data["workspace"]}).json() == saved.json()
    assert client.get(path, params={"workspace": "episode-two"}).status_code == 404
    assert client.put(path, json=data).status_code == 409
    data["revision"] = 1
    data["settings"]["strength"] = .75
    assert client.put(path, json=data).json()["revision"] == 2
    history = tmp_path / "episode-one" / ".speech3d-profiles" / (DIGEST + ".v1.json")
    assert json.loads(history.read_text()) == saved.json()

def test_profiles_reject_path_escape_nonface_settings_and_oversized_data(tmp_path):
    client = client_for(tmp_path)
    payload = {"workspace": "valid", "revision": 0, "settings": {"face": copy.deepcopy(FACE)}}
    for workspace in ["..", "../escape", "x/y", "x\\y"]:
        assert client.put(BASE + DIGEST, json={**payload, "workspace": workspace}).status_code in (400, 422)
    for settings in [{"face": FACE, "audio": "/secret.wav"}, {"face": "invalid"}, {"face": FACE, "lip": "x" * 24001}]:
        assert client.put(BASE + DIGEST, json={**payload, "settings": settings}).status_code == 422
    assert client.put(BASE + "bad", json=payload).status_code == 400


def test_bold_cartoon_profile_preserves_other_character_and_legacy_style(tmp_path):
    client = client_for(tmp_path)
    other_digest = "b" * 64
    legacy = {"workspace": "song", "revision": 0, "settings": {"face": FACE, "style": "toon"}}
    assert client.put(BASE + other_digest, json=legacy).status_code == 200
    bold = {**legacy, "settings": {"face": copy.deepcopy(FACE), "style": "toon-bold"}}
    bold["settings"]["face"]["center"][1] = .98
    assert client.put(BASE + DIGEST, json=bold).status_code == 200
    assert client.get(BASE + DIGEST, params={"workspace": "song"}).json()["settings"] == bold["settings"]
    assert client.get(BASE + other_digest, params={"workspace": "song"}).json()["settings"] == legacy["settings"]


def test_contour_morph_switch_survives_profiles_without_changing_other_models(tmp_path):
    client = client_for(tmp_path)
    other = "b" * 64
    legacy = {"workspace": "song", "revision": 0, "settings": {"face": FACE}}
    assert client.put(BASE + other, json=legacy).status_code == 200
    for morph in (1, "true", None):
        invalid = {**legacy, "settings": {"face": FACE, "morph": morph}}
        assert client.put(BASE + DIGEST, json=invalid).status_code == 422
    selected = {**legacy, "settings": {"face": FACE, "morph": True}}
    assert client.put(BASE + DIGEST, json=selected).status_code == 200
    assert client.get(BASE + DIGEST, params={"workspace": "song"}).json()["settings"] == selected["settings"]
    selected["revision"] = 1
    selected["settings"]["morph"] = False
    assert client.put(BASE + DIGEST, json=selected).status_code == 200
    assert client.get(BASE + DIGEST, params={"workspace": "song"}).json()["settings"]["morph"] is False
    assert client.get(BASE + other, params={"workspace": "song"}).json()["settings"] == legacy["settings"]
