"""Character Kit library HTTP is shared by full launch and core runtime."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from routers.character_kit_library import (
    _bind_character_kit_library_runtime,
    create_character_kit_library_router,
)


ROOT = Path(__file__).resolve().parents[1]


def test_launch_and_core_labs_mount_the_shared_character_kit_router():
    launch = (ROOT / "app" / "_launch_runtime.py").read_text(encoding="utf-8")
    core = (ROOT / "app" / "routers" / "core_labs.py").read_text(encoding="utf-8")
    assert "create_character_kit_library_router()" in launch
    assert "create_character_kit_library_router()" in core
    assert "def get_character_kit_library" not in launch


def test_the_voice_band_route_stores_the_type_and_rejects_a_bad_one(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from services.character_kit_library import patch_character_kit, read_character_kit_library

    preset = {"provider": "local", "model": "qwen3_tts_customvoice", "voiceId": "ryan"}
    kit = {"version": 1, "id": "gary", "name": "Gary", "style": "cutout", "poses": {},
           "mouth": {}, "eyes": {}, "anchors": {}, "provenance": [], "voice": preset}
    patch_character_kit(str(tmp_path), "gary", kit, base_revision=0)
    _bind_character_kit_library_runtime(workspace_dir=lambda _ws: str(tmp_path), conflict=lambda exc: HTTPException(409, "conflict"))
    app = FastAPI()
    app.include_router(create_character_kit_library_router())
    client = TestClient(app)
    bad = client.post("/api/v1/character-kits/library/kits/gary/voice-band", json={"workspace": "cast", "voiceType": "ghost"})
    assert bad.status_code == 400
    ok = client.post("/api/v1/character-kits/library/kits/gary/voice-band", json={"workspace": "cast", "voiceType": "man"})
    assert ok.status_code == 200, ok.text
    saved = read_character_kit_library(str(tmp_path))["kits"]["gary"]["voice"]
    assert saved["voiceType"] == "man" and "pitchBandHz" not in saved
    assert saved["voiceId"] == "ryan"


def test_conflict_adapter_is_used_for_patch():
    seen = []

    def workspace_dir(value):
        return "/tmp/kits"

    def conflict(exc):
        seen.append(exc)
        return HTTPException(status_code=409, detail="conflict")

    _bind_character_kit_library_runtime(workspace_dir=workspace_dir, conflict=conflict)
    router = create_character_kit_library_router()
    assert any(getattr(route, "path", None) == "/api/v1/character-kits/library" for route in router.routes)
    assert seen == []
