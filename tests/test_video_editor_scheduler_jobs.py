"""Model-free scheduler contract tests for editor and comic animatic jobs.

The editor export runs the mounted router module (``routers.video_editor``),
which owns the only job registry. Importing ``app.launch`` initializes the full
Maestro application, so ``start_comic_animatic`` is extracted from the comics
router and runs against that same registry. The animatic worker is the real
``services.comic_animatic`` function, with its video-editor callables pointed
at that registry. No FFmpeg process, model, or GPU runtime is used.
"""
from __future__ import annotations

import ast
import copy
from datetime import datetime
import json
import math
import os
import re
import sys
import threading
import time
import types
import uuid
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

import routers.video_editor as editor_router
import services.comic_animatic as comic_animatic
from services.asset_manifest import SCHEMA_NAME


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"
COMICS = ROOT / "app" / "routers" / "comics.py"
LANE_KEY = "local_cpu:ffmpeg"


class _HTTPException(Exception):
    def __init__(self, *, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _ResourceAcquireCancelled(Exception):
    pass


@lru_cache(maxsize=1)
def _tree() -> ast.Module:
    return ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))


def _function(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in _tree().body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            selected = copy.deepcopy(node)
            selected.decorator_list = []
            found.append(selected)
    for relative in (
        "app/services/canonical_task_fields.py",
        "app/services/canonical_task_publishers.py",
        "app/services/canonical_task_sync.py",
    ):
        path = ROOT / relative
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                selected = copy.deepcopy(node)
                selected.decorator_list = []
                found.append(selected)
    if len(found) == 1:
        return found[0]
    if found:
        raise AssertionError(f"Function {name!r} found {len(found)} times")
    if name == "start_comic_animatic":
        comics = ast.parse(COMICS.read_text(encoding="utf-8"), filename=str(COMICS))
        for node in ast.walk(comics):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                selected = copy.deepcopy(node)
                selected.decorator_list = []
                return selected
    raise AssertionError(f"Function {name!r} not found in launch or comics router")


def _load(*names: str, namespace: dict) -> dict:
    module = ast.Module(body=[_function(name) for name in names], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(LAUNCH), "exec"), namespace)
    return namespace


def _module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


def _editor_body(workspace: str = "captured-editor") -> dict:
    return {
        "name": "Scheduler editor test",
        "workspace": workspace,
        "width": 1280,
        "height": 720,
        "fps": 30,
        "clips": [{"source": "clip.mp4", "transition": "none"}],
    }


def _animatic_body(workspace: str = "captured-animatic") -> dict:
    return {
        "comic_id": "comic-contract",
        "comic_title": "Scheduler animatic test",
        "workspace": workspace,
        "width": 1280,
        "height": 720,
        "fps": 30,
        "transition": "crossfade",
        "transition_duration": 0.35,
        "panels": [{"source": "panel.webp", "duration": 1.5}],
    }


def _harness(monkeypatch, tmp_path: Path) -> dict:
    events: list[tuple] = []
    render_calls: list[str] = []
    render_settings: list[dict] = []
    workspace_calls: list[str] = []

    class DeferredThread:
        instances: list["DeferredThread"] = []

        def __init__(self, *, target, args=(), kwargs=None, **_ignored):
            self.target = target
            self.args = tuple(args)
            self.kwargs = dict(kwargs or {})
            self.started = False
            self.__class__.instances.append(self)

        def start(self) -> None:
            self.started = True
            events.append(("thread_start", self.target.__name__))

        def run_now(self) -> None:
            self.target(*self.args, **self.kwargs)

    class Coordinator:
        @contextmanager
        def acquire(self, requested_lane, *, task_id, description, cancelled):
            events.append(("lane_wait", requested_lane.key, task_id, description))
            if cancelled():
                raise _ResourceAcquireCancelled(task_id)
            events.append(("lane_acquire", requested_lane.key, task_id))
            try:
                yield
            finally:
                events.append(("lane_release", requested_lane.key, task_id))

    def default_render_project(_clips, output_path, *, progress, **settings):
        render_calls.append("export")
        render_settings.append(settings)
        progress(37, "Encoding editor timeline…")
        Path(output_path).write_bytes(b"fake editor mp4")
        return {"duration": 1.0}

    def default_render_animatic(_panels, output_path, *, progress, **_settings):
        render_calls.append("animatic")
        progress(43, "Encoding comic animatic…")
        Path(output_path).write_bytes(b"fake animatic mp4")
        return {"duration": 1.5}

    video_editor_module = _module(
        "services.video_editor",
        normalise_time_card_text=lambda value: str(value or "").strip(),
        render_project=default_render_project,
        render_comic_animatic=default_render_animatic,
        build_source_provenance_manifest=lambda clips: {
            "version": 1,
            "clips": [{
                "index": index,
                "source": clip.get("source"),
                "sidecar_status": "missing",
            } for index, clip in enumerate(clips)],
        },
    )
    # The animatic worker imports its renderer lazily from services.video_editor.
    monkeypatch.setitem(sys.modules, "services.video_editor", video_editor_module)

    def workspace_dir(workspace=None) -> str:
        workspace_calls.append(workspace)
        path = tmp_path / str(workspace)
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def publish(job: dict, adapter: str) -> dict:
        events.append(("publish", job["status"], job.get("phase"), copy.deepcopy(job)))
        assert adapter == "video-editor"
        return {"id": job["task_id"], "root_id": job["root_task_id"]}

    def active_workspace():
        raise AssertionError("explicit workspace was not captured")

    def resolve_in_workspace(source, workspace=None):
        return str(tmp_path / str(workspace) / os.path.basename(source))

    scheduler = SimpleNamespace(
        coordinator=Coordinator(),
        ResourceAcquireCancelled=_ResourceAcquireCancelled,
    )
    fake_threading = SimpleNamespace(Thread=DeferredThread)

    # The editor half: the real router module, its registry and runtime binding.
    editor_router.reset_video_editor_jobs()
    monkeypatch.setattr(editor_router, "_runtime", editor_router._Runtime())
    editor_router._bind_video_editor_runtime(
        workspace_dir=workspace_dir,
        get_active_workspace=active_workspace,
        resolve_input_path=lambda value, workspace=None: None,
        publish_legacy_task=publish,
        thumbnail_cache_dir=str(tmp_path / "thumbs"),
    )
    monkeypatch.setattr(editor_router, "threading", fake_threading)
    monkeypatch.setattr(editor_router, "resource_scheduler", scheduler)
    monkeypatch.setattr(editor_router, "_resolve_video_editor_source", resolve_in_workspace)
    monkeypatch.setattr(editor_router, "_resolve_video_editor_audio_source", resolve_in_workspace)
    for name in ("render_project", "build_source_provenance_manifest", "normalise_time_card_text"):
        monkeypatch.setattr(
            editor_router, name,
            lambda *args, _name=name, **kwargs: getattr(video_editor_module, _name)(*args, **kwargs),
        )
    jobs = editor_router._video_editor_jobs

    # The animatic worker is the real module. Its video-editor names point at
    # this test's registry and are restored when the test ends.
    monkeypatch.setattr(comic_animatic, "resource_scheduler", scheduler)
    monkeypatch.setattr(comic_animatic, "_VIDEO_EDITOR_FFMPEG_LANE", editor_router._VIDEO_EDITOR_FFMPEG_LANE)
    monkeypatch.setattr(comic_animatic, "_VIDEO_EDITOR_TERMINAL", editor_router._VIDEO_EDITOR_TERMINAL)
    monkeypatch.setattr(comic_animatic, "_video_editor_job_snapshot", editor_router._video_editor_job_snapshot)
    monkeypatch.setattr(comic_animatic, "_video_editor_job_update", editor_router._video_editor_job_update)
    monkeypatch.setattr(comic_animatic, "_video_editor_cancel_requested", editor_router._video_editor_cancel_requested)
    monkeypatch.setattr(comic_animatic, "_remove_video_editor_output_bundle", editor_router._remove_video_editor_output_bundle)
    monkeypatch.setattr(comic_animatic, "_finish_video_editor_cancelled", editor_router._finish_video_editor_cancelled)
    monkeypatch.setattr(comic_animatic, "_resolve_comic_animatic_image", resolve_in_workspace)
    namespace = {
        "HTTPException": _HTTPException,
        "os": os,
        "re": re,
        "threading": fake_threading,
        "time": time,
        "uuid": uuid,
        "get_active_workspace": active_workspace,
        "workspace_dir": workspace_dir,
        "video_editor_task_identity": editor_router._video_editor_task_identity,
        "register_video_editor_job": editor_router._register_video_editor_job,
        "video_editor_job_update": editor_router._video_editor_job_update,
        "public_video_editor_job": editor_router._public_video_editor_job,
        "ffmpeg_lane_key": LANE_KEY,
        "run_comic_animatic": comic_animatic._run_comic_animatic,
        "start_video_editor_export": editor_router._start_video_editor_export,
        "cancel_video_editor_export": editor_router.cancel_video_editor_export,
    }
    _load("start_comic_animatic", namespace=namespace)
    namespace.update({
        "DeferredThread": DeferredThread,
        "events": events,
        "jobs": jobs,
        "render_calls": render_calls,
        "render_settings": render_settings,
        "video_editor_module": video_editor_module,
        "workspace_calls": workspace_calls,
    })
    return namespace


def test_editor_soundtrack_is_resolved_and_reaches_renderer(monkeypatch, tmp_path):
    harness = _harness(monkeypatch, tmp_path)
    body = _editor_body("music-workspace")
    body["soundtrack"] = {
        "name": "score.mp3",
        "source": "/api/v1/file/score.mp3",
        "trim_start": 1,
        "trim_end": 8,
        "volume": 0.6,
        "loop": True,
    }

    response = harness["start_video_editor_export"](body)
    harness["DeferredThread"].instances[-1].run_now()

    soundtrack = harness["render_settings"][0]["soundtrack"]
    assert soundtrack["resolved_path"].endswith("music-workspace/score.mp3")
    assert soundtrack["volume"] == 0.6
    assert soundtrack["loop"] is True
    job = harness["jobs"][response["job_id"]]
    assert job["status"] == "completed"


@pytest.mark.parametrize(
    ("start_name", "body_factory", "workspace"),
    [
        ("start_video_editor_export", _editor_body, "explicit-editor"),
        ("start_comic_animatic", _animatic_body, "explicit-animatic"),
    ],
)
def test_post_reserves_identity_and_publishes_queued_before_thread_under_250ms(
    monkeypatch,
    tmp_path,
    start_name,
    body_factory,
    workspace,
):
    harness = _harness(monkeypatch, tmp_path)

    started_at = time.monotonic()
    response = harness[start_name](body_factory(workspace))
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.250
    assert response["job_id"]
    assert response["task_id"].startswith("task-video-editor-")
    assert response["root_task_id"] == response["task_id"]
    assert response["workspace"] == workspace
    assert response["status"] == "queued"
    assert response["resource_requirements"] == [LANE_KEY]
    assert harness["workspace_calls"] == [workspace]
    assert [event[0] for event in harness["events"][:2]] == ["publish", "thread_start"]
    assert harness["events"][0][1:3] == ("queued", "queued")
    assert harness["render_calls"] == []


@pytest.mark.parametrize(
    ("start_name", "body_factory"),
    [
        ("start_video_editor_export", _editor_body),
        ("start_comic_animatic", _animatic_body),
    ],
)
def test_queued_cancel_never_acquires_ffmpeg_lane_or_renders(
    monkeypatch,
    tmp_path,
    start_name,
    body_factory,
):
    harness = _harness(monkeypatch, tmp_path)
    response = harness[start_name](body_factory())

    cancelled = harness["cancel_video_editor_export"](response["job_id"])
    harness["DeferredThread"].instances[-1].run_now()

    assert cancelled["status"] == "cancelled"
    assert cancelled["phase"] == "cancelled"
    assert cancelled["cancel_mode"] == "immediate"
    assert harness["jobs"][response["job_id"]]["status"] == "cancelled"
    assert harness["render_calls"] == []
    assert not any(event[0].startswith("lane_") for event in harness["events"])
    assert [event[1] for event in harness["events"] if event[0] == "publish"] == [
        "queued",
        "cancelled",
    ]


def test_running_cancel_waits_for_safe_boundary_then_removes_output_bundle(
    monkeypatch,
    tmp_path,
):
    harness = _harness(monkeypatch, tmp_path)
    render_started = threading.Event()
    release_render = threading.Event()
    started_next_ffmpeg_step: list[bool] = []

    def blocking_render(_clips, output_path, *, progress, **_settings):
        harness["render_calls"].append("export")
        Path(output_path).write_bytes(b"partial mp4")
        Path(output_path).with_suffix(".meta.json").write_text("{}", encoding="utf-8")
        progress(55, "Halfway through FFmpeg…")
        render_started.set()
        assert release_render.wait(timeout=2)
        progress(75, "Current FFmpeg subprocess reached its safe boundary")
        started_next_ffmpeg_step.append(True)
        return {"duration": 2.0}

    harness["video_editor_module"].render_project = blocking_render
    response = harness["start_video_editor_export"](_editor_body())
    deferred = harness["DeferredThread"].instances[-1]
    worker = threading.Thread(target=deferred.run_now, daemon=True)
    worker.start()
    assert render_started.wait(timeout=2)

    output_path = Path(deferred.args[3])
    sidecar_path = output_path.with_suffix(".meta.json")
    cancelling = harness["cancel_video_editor_export"](response["job_id"])

    assert cancelling["status"] == "cancelling"
    assert cancelling["phase"] == "cancelling"
    assert cancelling["acquired_resources"] == [LANE_KEY]
    assert output_path.exists() and sidecar_path.exists()
    assert worker.is_alive()
    assert not any(
        event[0] == "publish" and event[1] == "cancelled"
        for event in harness["events"]
    )

    release_render.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    terminal = harness["jobs"][response["job_id"]]
    assert terminal["status"] == "cancelled"
    assert terminal["phase"] == "cancelled"
    assert terminal["cancel_mode"] == "deferred"
    assert terminal["acquired_resources"] == []
    assert started_next_ffmpeg_step == []
    assert not output_path.exists()
    assert not sidecar_path.exists()

    release_index = max(
        index for index, event in enumerate(harness["events"])
        if event[0] == "lane_release"
    )
    cancelled_index = max(
        index for index, event in enumerate(harness["events"])
        if event[0] == "publish" and event[1] == "cancelled"
    )
    assert cancelled_index > release_index


@pytest.mark.parametrize(
    ("start_name", "body_factory", "render_kind"),
    [
        ("start_video_editor_export", _editor_body, "export"),
        ("start_comic_animatic", _animatic_body, "animatic"),
    ],
)
def test_progress_and_terminal_publish_without_get_and_sidecar_keeps_task_hierarchy(
    monkeypatch,
    tmp_path,
    start_name,
    body_factory,
    render_kind,
):
    harness = _harness(monkeypatch, tmp_path)
    response = harness[start_name](body_factory())
    deferred = harness["DeferredThread"].instances[-1]

    deferred.run_now()

    terminal = harness["jobs"][response["job_id"]]
    assert terminal["status"] == "completed"
    assert terminal["phase"] == "completed"
    assert terminal["acquired_resources"] == []
    assert harness["render_calls"] == [render_kind]

    publications = [event[3] for event in harness["events"] if event[0] == "publish"]
    statuses = [item["status"] for item in publications]
    phases = [item["phase"] for item in publications]
    assert statuses[0] == "queued"
    assert "waiting_resource" in statuses
    assert "running" in statuses
    assert statuses[-1] == "completed"
    assert "rendering" in phases
    assert any(item["acquired_resources"] == [LANE_KEY] for item in publications)
    assert any(0 < int(item["progress"]) < 100 for item in publications)

    output_path = Path(deferred.args[-1])
    sidecar_path = output_path.with_suffix(".meta.json")
    assert output_path.exists()
    assert sidecar_path.exists()
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert sidecar["schema"] == SCHEMA_NAME
    assert sidecar["origin"]["actor"] == "unknown"
    assert sidecar["job_id"] == response["job_id"]
    assert sidecar["task_id"] == response["task_id"]
    assert sidecar["root_task_id"] == response["root_task_id"]
    if render_kind == "export":
        assert sidecar["origin"]["tool"] == "video-editor"
        editor = sidecar["params"]["video_editor"]
        assert editor["version"] == 2
        assert editor["source_manifest"]["clips"][0]["source"] == "clip.mp4"
    else:
        assert sidecar["origin"]["tool"] == "comic-animatic"


def test_canonical_adapter_exposes_real_lane_cancel_contract_and_control_route():
    captured: list[dict] = []

    def upsert(workspace, task_id, **fields):
        value = {"workspace": workspace, "id": task_id, **fields}
        captured.append(value)
        return value

    namespace = {
        "HTTPException": _HTTPException,
        "datetime": datetime,
        "math": math,
        "resource_scheduler": SimpleNamespace(
            cpu_lane=lambda name: SimpleNamespace(key=f"local_cpu:{name}"),
        ),
        "time": time,
        "_GENERIC_TASK_CONFIG": {
            "video-editor": ("Video editor", "ffmpeg", False),
        },
        "_upsert_canonical_task": upsert,
    }
    _load(
        "_task_legacy_id",
        "_task_status",
        "_task_timestamp",
        "_canonical_legacy_progress",
        "_publish_generic_legacy_task",
        "_control_canonical_task",
        namespace=namespace,
    )
    cancelled_ids: list[str] = []
    namespace["cancel_video_editor_export"] = lambda job_id: cancelled_ids.append(job_id)

    namespace["_publish_generic_legacy_task"]({
        "job_id": "video-edit-contract",
        "task_id": "task-video-editor-contract",
        "root_task_id": "task-root-contract",
        "workspace": "editing-room",
        "status": "cancelling",
        "phase": "cancelling",
        "current": 55,
        "total": 100,
        "progress": 55,
        "resource_lane": LANE_KEY,
        "acquired_resources": [LANE_KEY],
        "cancel_mode": "deferred",
        "safe_boundary": "after_current_ffmpeg_render",
    }, "video-editor")

    task = captured[-1]
    assert task["status"] == "running"
    assert task["phase"] == "cancelling"
    assert task["resource_requirements"] == [LANE_KEY]
    assert task["acquired_resources"] == [LANE_KEY]
    assert task["cancelable"] is False
    assert task["metadata"]["cancel_mode"] == "deferred"
    assert task["metadata"]["safe_boundary"] == "after_current_ffmpeg_render"

    namespace["_control_canonical_task"]({
        "backend_job_id": "video-edit-contract",
        "metadata": {"adapter": "video-editor"},
    }, "cancel")
    assert cancelled_ids == ["video-edit-contract"]
