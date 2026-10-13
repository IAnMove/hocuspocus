"""Series library: list, create, get, update, duplicate, delete, and the empty job lists."""
from __future__ import annotations

WORKSPACE = "golden-series"


def test_series_project_lifecycle(server, golden) -> None:
    server.client.post("/api/v1/workspaces", json={"name": WORKSPACE})
    server.check(golden, "list empty", "GET", "/api/v1/series", params={"workspace": WORKSPACE})
    created = server.check(golden, "create", "POST", "/api/v1/series",
                           json={"workspace": WORKSPACE, "title": "Golden series", "logline": "A test."})
    series_id = created.json()["id"]
    server.check(golden, "get", "GET", f"/api/v1/series/{series_id}", params={"workspace": WORKSPACE})
    server.check(golden, "update", "PUT", f"/api/v1/series/{series_id}",
                 json={"workspace": WORKSPACE, "baseRevision": 1, "series": {"title": "Golden series, revised"}})
    server.check(golden, "update stale revision", "PUT", f"/api/v1/series/{series_id}",
                 json={"workspace": WORKSPACE, "baseRevision": 1, "series": {"title": "Lost write"}})
    server.check(golden, "update other id", "PUT", f"/api/v1/series/{series_id}",
                 json={"workspace": WORKSPACE, "series": {"id": "someone-else"}})
    server.check(golden, "episode before canon approval", "POST", f"/api/v1/series/{series_id}/episodes",
                 json={"workspace": WORKSPACE, "title": "Pilot"})
    server.check(golden, "list one", "GET", "/api/v1/series", params={"workspace": WORKSPACE})
    server.check(golden, "library", "GET", "/api/v1/series/library", params={"workspace": WORKSPACE})
    server.check(golden, "delete", "DELETE", f"/api/v1/series/{series_id}", params={"workspace": WORKSPACE})
    server.check(golden, "get deleted", "GET", f"/api/v1/series/{series_id}", params={"workspace": WORKSPACE})
    server.check(golden, "list after delete", "GET", "/api/v1/series", params={"workspace": WORKSPACE})


def test_series_job_lists_start_empty(server, golden) -> None:
    for case, path in (
        ("plan recovery", "/api/v1/series/plan/recovery"),
        ("render recovery", "/api/v1/series/render/recovery"),
        ("assembly recovery", "/api/v1/series/assembly/recovery"),
        ("native render recovery", "/api/v1/series/native-render/recovery"),
        ("produce jobs", "/api/v1/series/produce/jobs"),
    ):
        server.check(golden, case, "GET", path, params={"workspace": "default"})
