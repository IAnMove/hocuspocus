"""Story Lab library HTTP is shared by full launch and core runtime."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_launch_and_core_labs_mount_the_shared_story_library_router():
    launch = (ROOT / "app" / "_launch_runtime.py").read_text(encoding="utf-8")
    core = (ROOT / "app" / "routers" / "core_labs.py").read_text(encoding="utf-8")
    router = (ROOT / "app" / "routers" / "story_library.py").read_text(encoding="utf-8")
    assert "create_story_library_router()" in launch
    assert "create_story_library_router()" in core
    assert "def get_story_library" not in launch
    assert "@router.get(\"/api/v1/stories/library\")" in router
    assert "@router.delete(\"/api/v1/stories/library/projects/{project_id}\")" in router
