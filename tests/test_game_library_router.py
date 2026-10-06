"""HTTP contract for the game library."""
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.game_library import create_game_library_router


def _client(tmp_path):
    app = FastAPI()
    app.include_router(create_game_library_router(workspace_dir=lambda _name: str(tmp_path), lock=threading.RLock()))
    return TestClient(app)


def test_invalid_palette_is_422_and_stale_revision_is_409(tmp_path):
    client = _client(tmp_path)
    created = client.post("/api/v1/games", json={"workspace": "lab", "game": {"id": "bosque", "title": "Bosque"}})
    assert created.status_code == 201
    revision = created.json()["revision"]
    palette = client.put("/api/v1/games/bosque", json={
        "workspace": "lab", "base_revision": revision, "patch": {"style": {"palette": ["red"]}},
    })
    assert palette.status_code == 422
    assert palette.json()["detail"]["code"] == "invalid_palette"
    assert palette.json()["detail"]["problems"]
    conflict = client.put("/api/v1/games/bosque", json={
        "workspace": "lab", "base_revision": 0, "patch": {"title": "Otro"},
    })
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "revision_conflict"


def test_dependency_cycle_and_presets(tmp_path):
    client = _client(tmp_path)
    cycle = client.post("/api/v1/games", json={"workspace": "lab", "game": {
        "id": "bosque", "title": "Bosque",
        "assets": [
            {"id": "a", "kind": "sprite", "spec": {"character": "b"}},
            {"id": "b", "kind": "sprite", "spec": {"character": "a"}},
        ],
    }})
    assert cycle.status_code == 422
    assert cycle.json()["detail"]["code"] == "dependency_cycle"
    created = client.post("/api/v1/games", json={"workspace": "lab", "game": {"id": "bosque", "title": "Bosque"}})
    assert created.status_code == 201
    missing_asset = client.patch("/api/v1/games/bosque/assets/a", json={
        "workspace": "lab", "base_revision": created.json()["revision"], "patch": {"name": "A"},
    })
    assert missing_asset.status_code == 404
    assert missing_asset.json()["detail"]["code"] == "asset_not_found"
    presets = client.get("/api/v1/games/presets")
    assert presets.status_code == 200
    assert len(presets.json()["actions"]) == 14
    assert len(presets.json()["presets"]) == 8


def test_missing_game_is_404(tmp_path):
    client = _client(tmp_path)
    missing = client.get("/api/v1/games/nope", params={"workspace": "lab"})
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "game_not_found"
    extra = client.post("/api/v1/games", json={"workspace": "lab", "game": {"id": "bosque", "title": "Bosque"}, "extra": 1})
    assert extra.status_code == 422
