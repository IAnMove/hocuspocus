"""Model-free contract for reopening Director's canonical task on resume."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services import director_pipeline


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "app" / "launch.py"


def _load_endpoint(namespace: dict):
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))
    node = next(
        copy.deepcopy(candidate)
        for candidate in tree.body
        if isinstance(candidate, ast.FunctionDef)
        and candidate.name == "director_pipeline_resume"
    )
    node.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, str(LAUNCH), "exec"), namespace)
    return namespace["director_pipeline_resume"]


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

    endpoint = _load_endpoint({
        "_init_pipeline": lambda: None,
        "wgp": SimpleNamespace(server_config={"save_path": "outputs"}),
        "_get_active_workspace": lambda: "default",
        "_reset_canonical_task_for_resume": lambda workspace, task_id: resets.append(
            (workspace, task_id)
        ),
        "_publish_director_task": publish,
    })

    with patch.object(
        director_pipeline, "resume_pipeline", return_value=(True, "resumed"),
    ), patch.object(
        director_pipeline, "get_pipeline", return_value=pipeline,
    ):
        result = endpoint(pipeline_id)

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
