import hashlib
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.character_kit_face import create_character_kit_face_router
from routers import scene3d_profiles as profiles

DIGEST = "/api/v1/character-kits/speech/digest"
BYTES = b"same GLB bytes"


def client_for(tmp_path):
    app = FastAPI()
    app.include_router(create_character_kit_face_router(
        workspace_dir=lambda name: str(tmp_path / name), uploads_root=lambda: str(tmp_path / "uploads")))
    return TestClient(app)


def test_digest_is_content_addressed_and_ignores_filename(tmp_path):
    client = client_for(tmp_path)
    one = tmp_path / "episode-one"
    one.mkdir()
    (one / "mira.glb").write_bytes(BYTES)
    (one / "twin.glb").write_bytes(BYTES)
    (one / "other.glb").write_bytes(b"other GLB bytes")
    expected = hashlib.sha256(BYTES).hexdigest()
    first = client.get(DIGEST, params={"workspace": "episode-one", "filename": "mira.glb"})
    twin = client.get(DIGEST, params={"workspace": "episode-one", "filename": "twin.glb"})
    other = client.get(DIGEST, params={"workspace": "episode-one", "filename": "other.glb"})
    assert first.status_code == 200 and first.json()["digest"] == expected
    assert twin.json()["digest"] == expected
    assert other.json()["digest"] != expected
    assert first.json()["digest"] != "mira.glb"
    assert first.json()["bytes"] == len(BYTES)


def test_digest_rejects_escape_missing_and_oversized_models(tmp_path, monkeypatch):
    client = client_for(tmp_path)
    workspace = tmp_path / "valid"
    workspace.mkdir()
    (workspace / "mira.glb").write_bytes(BYTES)
    assert client.get(DIGEST, params={"workspace": "../escape", "filename": "mira.glb"}).status_code in (400, 422)
    assert client.get(DIGEST, params={"workspace": "valid", "filename": "../mira.glb"}).status_code == 400
    assert client.get(DIGEST, params={"workspace": "valid", "filename": "missing.glb"}).status_code == 404
    assert client.get(DIGEST, params={"workspace": "valid", "filename": "notes.txt"}).status_code == 400
    monkeypatch.setattr(profiles, "MAX_MODEL_BYTES", 4)
    assert client.get(DIGEST, params={"workspace": "valid", "filename": "mira.glb"}).status_code == 413
