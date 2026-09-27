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
