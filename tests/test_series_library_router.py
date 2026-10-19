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


def test_series_reads_stay_200_after_a_silent_assembly_record(tmp_path):
    """routers/series_assembly copies the episode's loudness into the series asset; a silent mix used to store
    -Infinity, and then GET /api/v1/series and GET /api/v1/series/{id} answered 500 for the whole workspace."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import routers.series_library as routes
    from services.series_library import series_library_path, write_series_library, read_series_library

    names = ("_resolve_workspace", "_library_lock", "_read_library", "_write_library", "_project_or_404",
             "_series_library_workspace", "_series_library_lock", "_read_series_workspace", "_write_series_workspace",
             "_series_project_or_404", "_workspace_dir", "_safe_join")
    before = {name: getattr(routes, name, None) for name in names}
    root = str(tmp_path)
    try:
        _bind_series_library_runtime(
            resolve_workspace=lambda value: value or "default", library_lock=threading.RLock(),
            read_library=lambda workspace: read_series_library(root, workspace),
            write_library=lambda workspace, value: write_series_library(root, value, workspace),
            project_or_404=lambda current, series_id: current["seriesById"][series_id])
        app = FastAPI()
        app.include_router(create_series_library_router())
        client = TestClient(app, raise_server_exceptions=False)
        made = client.post("/api/v1/series", json={"workspace": "default", "title": "Silent"}).json()
        library = read_series_library(root, "default")
        library["seriesById"][made["id"]].setdefault("assets", {})["asset_silent"] = {
            "id": "asset_silent", "workspaceId": "default", "kind": "video", "uri": "outputs/silent.mp4",
            "ownerType": "series", "ownerId": made["id"], "isDerivedThumbnail": False,
            "metadata": {"loudness": {"applied": False, "before": {"lufs": float("-inf"), "truePeakDb": float("-inf"), "rangeLu": 0.0}}}}
        write_series_library(root, library, "default")
        assert client.get("/api/v1/series", params={"workspace": "default"}).status_code == 200
        assert client.get(f"/api/v1/series/{made['id']}", params={"workspace": "default"}).status_code == 200
        # A file written before the repair still loads.
        path = series_library_path(root)
        Path(path).write_text(Path(path).read_text(encoding="utf-8").replace('"lufs":null', '"lufs":-Infinity'), encoding="utf-8")
        assert "-Infinity" in Path(path).read_text(encoding="utf-8")
        assert client.get("/api/v1/series", params={"workspace": "default"}).status_code == 200
    finally:
        _bind_series_library_runtime(
            resolve_workspace=before["_resolve_workspace"], library_lock=before["_library_lock"],
            read_library=before["_read_library"], write_library=before["_write_library"],
            project_or_404=before["_project_or_404"], workspace_dir=before["_workspace_dir"], safe_join=before["_safe_join"])
