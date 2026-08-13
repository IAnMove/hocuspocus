"""Unit coverage for canonical-task adapter helpers without importing launch."""
from __future__ import annotations

import ast
import math
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import resource_scheduler


ROOT = Path(__file__).parents[1]
LAUNCH_PATH = ROOT / "app" / "launch.py"
SOURCE = LAUNCH_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(LAUNCH_PATH))


class DummyHTTPException(Exception):
    def __init__(self, *, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _function(name: str) -> ast.FunctionDef:
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} not found")


def _load_helpers(*names: str, save_path: Path | None = None) -> dict:
    selected = [_function(name) for name in names]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "HTTPException": DummyHTTPException,
        "math": math,
        "os": os,
        "re": re,
        "resource_scheduler": resource_scheduler,
        "wgp": SimpleNamespace(server_config={
            "save_path": str(save_path or ROOT / "outputs"),
            "services": {"active_workspace": "active-one"},
        }),
    }
    exec(compile(module, str(LAUNCH_PATH), "exec"), namespace)
    return namespace


def test_workspace_dir_accepts_only_exact_names_and_returns_real_paths(tmp_path):
    helpers = _load_helpers("_get_active_workspace", "_workspace_dir", save_path=tmp_path)
    workspace_dir = helpers["_workspace_dir"]

    assert workspace_dir("default") == os.path.realpath(tmp_path)
    assert workspace_dir(None) == os.path.realpath(tmp_path / "active-one")
    assert workspace_dir("Project_2-test") == os.path.realpath(tmp_path / "Project_2-test")

    for invalid in ("", ".", "..", "../escape", "nested/name", "nested\\name",
                    " leading", "trailing ", "has.dot", "café", 123):
        with pytest.raises(DummyHTTPException) as error:
            workspace_dir(invalid)
        assert error.value.status_code == 400


def test_workspace_dir_rejects_valid_named_symlink_that_escapes_base(tmp_path):
    base = tmp_path / "outputs"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    link = base / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlinks are unavailable on this platform")

    workspace_dir = _load_helpers(
        "_get_active_workspace", "_workspace_dir", save_path=base,
    )["_workspace_dir"]
    with pytest.raises(DummyHTTPException) as error:
        workspace_dir("linked")
    assert error.value.status_code == 400


@pytest.mark.parametrize(
    ("legacy_percent", "expected"),
    [(0, 0.0), (1, 0.01), (8, 0.08), (50, 0.5), (100, 1.0)],
)
def test_canonical_legacy_progress_converts_percent_to_fraction(
    legacy_percent, expected,
):
    progress = _load_helpers("_canonical_legacy_progress")[
        "_canonical_legacy_progress"
    ]
    assert progress(0, 0, legacy_percent) == pytest.approx(expected)


def test_canonical_legacy_progress_prioritizes_current_total_and_clamps():
    progress = _load_helpers("_canonical_legacy_progress")[
        "_canonical_legacy_progress"
    ]
    assert progress(1, 8, 100) == pytest.approx(0.125)
    assert progress(10, 8, 0) == 1.0
    assert progress(-1, 8, 100) == 0.0


@pytest.mark.parametrize(
    "adapter", ["_publish_generation_task", "_publish_generic_legacy_task"],
)
def test_legacy_adapters_use_the_canonical_progress_helper(adapter):
    calls = {
        node.func.id
        for node in ast.walk(_function(adapter))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_canonical_legacy_progress" in calls


def test_task_event_cursor_prefers_latest_valid_cursor():
    cursor = _load_helpers("_task_event_cursor")["_task_event_cursor"]

    assert cursor(3, "8") == 8
    assert cursor("12", "broken") == 12
    assert cursor(-4, -2) == 0


def _load_publisher(name: str):
    selected = [
        _function(helper)
        for helper in ("_task_legacy_id", "_task_status", "_task_timestamp", name)
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    captured = {}

    def upsert(workspace, task_id, **fields):
        captured.clear()
        captured.update({"workspace": workspace, "id": task_id, **fields})
        return dict(captured)

    namespace = {
        "datetime": __import__("datetime").datetime,
        "resource_scheduler": resource_scheduler,
        "time": __import__("time"),
        "_GENERIC_TASK_CONFIG": {
            "story-plan": ("Story Lab planning", "llm-planning", True),
            "comic-plan": ("Comic planning", "llm-planning", True),
            "video-editor": ("Video editor", "ffmpeg", False),
            "model3d": ("3D generation", "model3d", False),
            "rig": ("Character rigging", "rig", False),
        },
        "_upsert_canonical_task": upsert,
        "_canonical_legacy_progress": lambda current, total, progress: 0.0,
    }
    exec(compile(module, str(LAUNCH_PATH), "exec"), namespace)
    return namespace[name], captured


def test_series_remote_lane_uses_normalized_origin_and_no_fake_acquisition():
    publish, captured = _load_publisher("_publish_series_task")

    publish({
        "jobId": "series-plan-1",
        "workspace": "default",
        "status": "running",
        "request": {
            "writingProvider": "minimax",
            "writingModel": "MiniMax-M3",
            "writingBaseUrl": "https://api.minimax.io/v1",
        },
    }, "series-plan")

    assert captured["resource_requirements"] == ["remote:https://api.minimax.io"]
    assert captured["acquired_resources"] == []


@pytest.mark.parametrize(
    ("engine", "expected"),
    [("procedural", "local_cpu:rig"), ("unirig", "local_gpu:0")],
)
def test_rig_adapter_declares_its_actual_engine_lane(engine, expected):
    publish, captured = _load_publisher("_publish_generic_legacy_task")

    publish({
        "job_id": f"rig-{engine}",
        "workspace": "default",
        "status": "running",
        "engine": engine,
    }, "rig")

    assert captured["resource_requirements"] == [expected]


def test_generic_adapter_preserves_service_owned_task_identity():
    publish, captured = _load_publisher("_publish_generic_legacy_task")

    publish({
        "job_id": "backend-id",
        "task_id": "task-model3d-backend-id",
        "root_task_id": "task-series-root",
        "workspace": "default",
        "status": "queued",
    }, "model3d")

    assert captured["id"] == "task-model3d-backend-id"
    assert captured["root_id"] == "task-series-root"
