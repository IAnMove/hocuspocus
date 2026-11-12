"""Model-free contract for reopening Director's canonical task on resume."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from routers import director as director_routes
from services import director_pipeline


def test_resume_reopens_and_republishes_the_same_director_root():
    pipeline_id = "pipeline-recovered"
    pipeline = {
        "id": pipeline_id,
        "workspace": "project-a",
        "status": "running",
        "phase": "generating_video",
    }
    resets: list[tuple[str, str]] = []
    published: list[tuple[dict, str]] = []

    def publish(snapshot: dict, workspace: str):
        published.append((dict(snapshot), workspace))
        return {
            "id": f"task-director-{pipeline_id}",
            "root_id": f"task-director-{pipeline_id}",
        }

    with patch.object(director_routes, "_init_pipeline", lambda: None), patch.object(
        director_routes, "wgp", SimpleNamespace(server_config={"save_path": "outputs"}),
    ), patch.object(
        director_routes, "_get_active_workspace", lambda: "default",
    ), patch.object(
        director_routes, "_reset_canonical_task_for_resume",
        lambda workspace, task_id: resets.append((workspace, task_id)),
    ), patch.object(
        director_routes, "_publish_director_task", publish,
    ), patch.object(
        director_pipeline, "resume_pipeline", return_value=(True, "resumed"),
    ), patch.object(
        director_pipeline, "get_pipeline", return_value=pipeline,
    ):
        result = director_routes.director_pipeline_resume(pipeline_id)

    task_id = f"task-director-{pipeline_id}"
    assert resets == [("project-a", task_id)]
    assert published == [(pipeline, "project-a")]
    assert result == {
        "status": "running",
        "phase": "generating_video",
        "pipeline_id": pipeline_id,
        "task_id": task_id,
        "root_task_id": task_id,
    }
