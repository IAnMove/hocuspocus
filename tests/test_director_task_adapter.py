"""Model-free tests for Director's canonical task compatibility adapter."""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
import time


_ROOT = Path(__file__).resolve().parents[1]


def _load_adapter():
    source_path = _ROOT / "app" / "_launch_runtime.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    wanted = {
        "_task_status",
        "_task_timestamp",
        "_publish_director_task",
    }
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in wanted
    ]
    captured = {}

    def upsert(workspace, task_id, **fields):
        captured.clear()
        captured.update({"workspace": workspace, "id": task_id, **fields})
        return dict(captured)

    namespace = {
        "datetime": datetime,
        "time": time,
        "_upsert_canonical_task": upsert,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), source_path, "exec"), namespace)
    return namespace["_publish_director_task"], captured


def test_director_adapter_publishes_terminal_statuses_and_outputs():
    publish, captured = _load_adapter()
    expected_statuses = {
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "crashed": "interrupted",
        "preview_ready": "completed",
    }

    for raw_status, canonical_status in expected_statuses.items():
        result = publish({
            "id": f"pipeline-{raw_status}",
            "status": raw_status,
            "phase": raw_status,
            "updated_at": 200.0,
            "_completed_at": 199.0,
            "progress": {"current": 1, "total": 1, "message": raw_status},
            "output_files": [f"{raw_status}.mp4"],
        }, "default")

        assert result["status"] == canonical_status
        assert captured["cancelable"] is False
        assert captured["completed_at"] == 199.0
        assert captured["result_refs"] == [f"{raw_status}.mp4"]


def test_director_adapter_keeps_live_pipeline_cancelable():
    publish, captured = _load_adapter()

    publish({
        "id": "pipeline-running",
        "status": "running",
        "phase": "generating_video",
        "progress": {"current": 2, "total": 5, "message": "Rendering"},
    }, "default")

    assert captured["status"] == "running"
    assert captured["cancelable"] is True
    assert captured["completed_at"] is None


def test_director_adapter_uses_concrete_lane_keys_not_phase_names():
    publish, captured = _load_adapter()

    publish({
        "id": "pipeline-lanes",
        "status": "running",
        "phase": "planning",
        "resource_schedule": {"lanes": {
            "planning": {"key": "remote:https://api.minimax.io"},
            "images": {"key": "remote:https://api.minimax.io"},
            "video": {"key": "local_gpu:0"},
        }},
    }, "default")

    assert captured["resource_requirements"] == [
        "remote:https://api.minimax.io", "local_gpu:0",
    ]
