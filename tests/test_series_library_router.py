"""Series library HTTP is shared by full launch and core runtime."""
from __future__ import annotations

import ast
import copy
import threading
from pathlib import Path

from fastapi import HTTPException

from routers.series_library import (
    _bind_series_library_runtime,
    create_series_library_router,
)


ROOT = Path(__file__).resolve().parents[1]


def test_launch_and_core_labs_mount_the_shared_series_library_router():
    launch = (ROOT / "app" / "_launch_runtime.py").read_text(encoding="utf-8")
    core = (ROOT / "app" / "routers" / "core_labs.py").read_text(encoding="utf-8")
    assert "create_series_library_router()" in launch
    assert "create_series_library_router()" in core
    assert "def get_series_library" not in launch
    tree = ast.parse((ROOT / "app" / "routers" / "series_library.py").read_text(encoding="utf-8"))
    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert {"get_series_library", "list_series_projects", "create_series_project_endpoint"}.issubset(names)


def test_create_series_conflict_and_get_round_trip():
    library = {"seriesById": {}, "seriesOrder": []}
    lock = threading.RLock()

    def write(_workspace, value):
        snapshot = copy.deepcopy(value)
        library.clear()
        library.update(snapshot)
        return snapshot

    _bind_series_library_runtime(
        resolve_workspace=lambda value: value or "default",
        library_lock=lock,
        read_library=lambda _workspace: library,
        write_library=write,
        project_or_404=lambda current, series_id: current["seriesById"][series_id],
    )
    router = create_series_library_router()

    def endpoint(method: str, path: str):
        for route in router.routes:
            if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
                return route.endpoint
        raise AssertionError(f"missing {method} {path}")

    created = endpoint("POST", "/api/v1/series")({"workspace": "default", "title": "Night Shift"})
    assert created["id"] in library["seriesById"]
    listed = endpoint("GET", "/api/v1/series")("default")
    assert listed["workspaceId"] == "default"
    assert listed["series"][0]["id"] == created["id"]
    fetched = endpoint("GET", "/api/v1/series/{series_id}")(created["id"], "default")
    assert fetched["id"] == created["id"]
    try:
        endpoint("POST", "/api/v1/series")({"workspace": "default", "series": created})
        raise AssertionError("expected 409")
    except HTTPException as exc:
        assert exc.status_code == 409
