from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.productions import create_productions_router


def _client() -> TestClient:
    pipelines = {
        "default": [{
            "pipeline_id": "pipe-1", "production_id": "prod-1", "run_id": "run-1",
            "title": "Server anthem", "pipeline_type": "music_video", "status": "failed",
        }],
        "film": [{
            "pipeline_id": "pipe-2", "production_id": "prod-1", "run_id": "run-2",
            "title": "Server anthem", "pipeline_type": "music_video", "status": "completed", "attempt": 2,
        }],
    }
    app = FastAPI()
    app.include_router(create_productions_router(
        list_workspaces=lambda: [{"name": "default"}, {"name": "film"}],
        list_pipelines=lambda workspace: pipelines[workspace],
    ))
    return TestClient(app)


def test_productions_group_runs_and_never_expose_paths():
    client = _client()
    listing = client.get("/api/v1/productions")

    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["productions"][0]["run_ids"] == ["run-1", "run-2"]
    detail = client.get("/api/v1/productions/prod-1")
    assert [item["id"] for item in detail.json()["runs"]] == ["run-1", "run-2"]
    assert "filepath" not in detail.text


def test_runs_filter_by_explicit_workspace_and_production():
    client = _client()

    listing = client.get("/api/v1/runs", params={"workspace": "film", "production_id": "prod-1"})

    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["runs"][0]["id"] == "run-2"
    assert client.get("/api/v1/runs/run-2").status_code == 200
    assert client.get("/api/v1/runs/missing").status_code == 404
    assert client.get("/api/v1/runs", params={"workspace": "missing"}).status_code == 404
