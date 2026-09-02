from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.workspace_collections import create_workspace_collections_router
from services.workspace_registry import WorkspaceRegistry


def test_workspace_collection_crud_and_revision_conflict(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "workspaces.json")
    app = FastAPI()
    app.include_router(create_workspace_collections_router(registry=lambda: registry))
    client = TestClient(app)

    created = client.post("/api/v1/workspace-collections", json={"name": "Film"})
    assert created.status_code == 201
    workspace_id = created.json()["id"]
    assert client.get("/api/v1/workspace-collections").json()["total"] == 1
    changed = client.put(f"/api/v1/workspace-collections/{workspace_id}", json={
        "expected_revision": 1, "project_ids": ["project-1"],
    })
    assert changed.status_code == 200
    assert changed.json()["project_ids"] == ["project-1"]
    stale = client.put(f"/api/v1/workspace-collections/{workspace_id}", json={
        "expected_revision": 1, "name": "Old",
    })
    assert stale.status_code == 409
    assert client.delete(f"/api/v1/workspace-collections/{workspace_id}").status_code == 204
