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
from routers.canonical_tasks import task_event_cursor


ROOT = Path(__file__).parents[1]
LAUNCH_PATH = ROOT / "app" / "_launch_runtime.py"
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


def test_generation_adapter_publishes_exact_story_song_identity():
    captured = {}

    def upsert(workspace, task_id, **fields):
        captured.update({"workspace": workspace, "id": task_id, **fields})
        return dict(captured)

    namespace = {
        "time": __import__("time"),
        "_public_generation_details": lambda _params: {
            "generation_mode": "audio",
            "model_type": "ace_step_v1_5_xl_sft_lm_4b",
            "model_name": "ACE-Step 1.5 XL",
        },
        "_task_status": lambda value: str(value),
        "_task_timestamp": lambda record, *keys: next(
            (record.get(key) for key in keys if record.get(key) is not None), None,
        ),
        "_canonical_legacy_progress": lambda *_args: 0.0,
        "_is_durable_generation_job": lambda _job: True,
        "_local_gpu_lane": SimpleNamespace(key="local_gpu:0"),
        "_upsert_canonical_task": upsert,
    }
    node = _function("_publish_generation_task")
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(LAUNCH_PATH), "exec"), namespace)

    namespace["_publish_generation_task"]({
        "id": "song-job",
        "workspace": "physical-folder",
        "status": "completed",
        "params": {"model_type": "ace_step_v1_5_xl_sft_lm_4b"},
        "output_files": ["song.wav"],
        "provenance": {
            "actor": "wizard",
            "capability": "generate_story_song",
            "project_id": "story-1",
            "cue_id": "cue-1",
            "candidate_id": "candidate-1",
            "song_version": "1",
        },
    })

    assert captured["project_id"] == "story-1"
    assert captured["entity_type"] == "song_candidate"
    assert captured["entity_id"] == "candidate-1"
    assert captured["metadata"]["cue_id"] == "cue-1"
    assert captured["metadata"]["candidate_id"] == "candidate-1"


def test_task_event_cursor_prefers_latest_valid_cursor():
    assert task_event_cursor(3, "8") == 8
    assert task_event_cursor("12", "broken") == 12
    assert task_event_cursor(-4, -2) == 0


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


def test_generic_adapter_publishes_reserved_music_identity():
    publish, captured = _load_publisher("_publish_generic_legacy_task")

    publish({
        "jobId": "minimax-music-abc123def456",
        "taskId": "task-minimax-music-abc123def456",
        "workspace": "default",
        "status": "queued",
        "generationId": "gen-1",
        "commandId": "cmd-1",
        "candidateId": "song-1",
        "idempotencyKey": "idem-1",
    }, "minimax-music")

    assert captured["metadata"]["generation_id"] == "gen-1"
    assert captured["metadata"]["command_id"] == "cmd-1"
    assert captured["metadata"]["candidate_id"] == "song-1"
    assert captured["metadata"]["idempotency_key"] == "idem-1"


def test_upsert_keeps_reserved_task_identity():
    existing = {
        "id": "task-minimax-music-abc",
        "status": "queued",
        "workflow": "generate_story_song",
        "title": "Story song",
        "metadata": {
            "generation_id": "gen-1",
            "candidate_id": "song-1",
            "command_id": "cmd-1",
            "idempotency_key": "idem-1",
        },
    }
    updated = {}

    class Registry:
        def get(self, _task_id):
            return existing

        def update(self, task_id, **fields):
            updated.update(fields)
            return {**existing, **{key: value for key, value in fields.items()
                                   if key not in {"force", "event_type", "event_exclude_fields"}}}

    namespace = {
        "_task_registry": lambda _workspace: Registry(),
    }
    node = _function("_upsert_canonical_task")
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(LAUNCH_PATH), "exec"), namespace)

    result = namespace["_upsert_canonical_task"](
        "default",
        "task-minimax-music-abc",
        workflow="minimax-music",
        title="MiniMax Music",
        status="queued",
        metadata={
            "adapter": "minimax-music",
            "actor": "unknown",
            "tool": "minimax-music",
            "capability": None,
            "command_id": None,
            "workflow_id": None,
            "run_id": None,
        },
    )

    assert "workflow" not in updated
    assert "title" not in updated
    assert result["workflow"] == "generate_story_song"
    assert result["title"] == "Story song"
    assert result["metadata"]["generation_id"] == "gen-1"
    assert result["metadata"]["candidate_id"] == "song-1"
    assert result["metadata"]["command_id"] == "cmd-1"
    assert result["metadata"]["idempotency_key"] == "idem-1"
    assert result["metadata"]["adapter"] == "minimax-music"
