"""Workspace delete must see a live Game produce checkpoint."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.workspace_outputs import create_workspace_router
from services.game_jobs import GameJobStore, active_produce_jobs
from services.kernel.paths import PathPolicy


def test_active_produce_jobs_sees_live_statuses_only(tmp_path):
    store = GameJobStore(str(tmp_path))
    store.save({"jobId": "done-one", "status": "completed"})
    store.save({"jobId": "failed-one", "status": "failed"})
    assert active_produce_jobs(str(tmp_path)) == []
    store.save({"jobId": "live-one", "status": "running", "gameId": "bosque"})
    store.save({"jobId": "wait-one", "status": "queued"})
    store.save({"jobId": "stop-one", "status": "cancelling"})
    assert {job["jobId"] for job in active_produce_jobs(str(tmp_path))} == {
        "live-one", "wait-one", "stop-one",
    }


def _workspace_delete_client(root: Path) -> TestClient:
    def workspace_dir(name="default"):
        return str(root if name == "default" else root / name)

    app = FastAPI()
    app.include_router(create_workspace_router(
        list_workspaces=lambda: [],
        get_active_workspace=lambda: "default",
        persist_active=lambda name, apply_save_paths=True: workspace_dir(name),
        workspace_dir=workspace_dir,
        generation_idle=lambda: True,
        jobs=lambda: [],
        safe_join=PathPolicy().safe_join,
        save_path=lambda: str(root),
    ))
    return TestClient(app)


@pytest.mark.parametrize("status", ["queued", "running", "cancelling"])
def test_delete_workspace_refuses_an_active_game_produce(tmp_path, status):
    arcade = tmp_path / "arcade"
    arcade.mkdir()
    (arcade / "library.json").write_text("{}", encoding="utf-8")
    GameJobStore(str(arcade)).save({
        "jobId": "game-produce-live", "workspace": "arcade", "gameId": "bosque", "status": status,
    })
    client = _workspace_delete_client(tmp_path)
    response = client.delete("/api/v1/workspaces/arcade")
    assert response.status_code == 409, response.text
    assert "game produce" in response.json()["detail"]
    assert (arcade / "library.json").exists()
    assert (arcade / ".game-jobs-v1" / "game-produce-live.json").exists()


def test_delete_workspace_proceeds_when_game_produce_finished(tmp_path):
    arcade = tmp_path / "arcade"
    arcade.mkdir()
    (arcade / "library.json").write_text("{}", encoding="utf-8")
    GameJobStore(str(arcade)).save({
        "jobId": "game-produce-done", "workspace": "arcade", "gameId": "bosque", "status": "completed",
    })
    client = _workspace_delete_client(tmp_path)
    response = client.delete("/api/v1/workspaces/arcade")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ok"
    assert not arcade.exists()
