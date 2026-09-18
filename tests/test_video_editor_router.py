"""ASGI contracts for the extracted Video Editor HTTP routers."""

from __future__ import annotations

import ast
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routers.video_editor import (
    create_video_editor_jobs_router,
    create_video_editor_router,
    reset_video_editor_jobs,
)
from services.media_refs import parse_media_ref


PROBE = {
    "duration": 2.5,
    "width": 1280,
    "height": 720,
    "fps": 30.0,
    "has_audio": True,
    "pixel_format": "yuv420p",
    "has_alpha": False,
}
AUDIO_PROBE = {"duration": 8.0, "has_audio": True}
EDITOR_HTTP_SURFACE = [
    ("POST", "/api/v1/video-editor/probe", "probe_video_editor_source"),
    ("POST", "/api/v1/video-editor/probe-audio", "probe_video_editor_audio_source"),
    ("GET", "/api/v1/video-editor/thumbnail", "serve_video_editor_thumbnail"),
    ("POST", "/api/v1/video-editor/screenshot", "capture_video_editor_frame"),
    ("POST", "/api/v1/video-editor/export", "start_video_editor_export"),
]
JOBS_HTTP_SURFACE = [
    ("GET", "/api/v1/video-editor/export/{job_id}", "get_video_editor_export"),
    ("POST", "/api/v1/video-editor/export/{job_id}/cancel", "cancel_video_editor_export"),
]
ROUTER_SOURCE = Path(__file__).parents[1] / "app" / "routers" / "video_editor.py"


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

    def run_now(self) -> None:
        self.target(*self.args, **self.kwargs)


def _route_surface(router):
    found = []
    for route in router.routes:
        methods = sorted(
            method for method in (route.methods or set()) if method not in {"HEAD", "OPTIONS"}
        )
        for method in methods:
            found.append((method, route.path, route.endpoint.__name__))
    return found


def _roots(tmp_path: Path) -> dict[str, Path]:
    roots = {
        "default": tmp_path / "outputs",
        "film": tmp_path / "outputs" / "film",
        "__uploads__": tmp_path / "uploads",
    }
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    return roots


def _harness(tmp_path: Path):
    roots = _roots(tmp_path)
    events: list[tuple] = []
    reset_video_editor_jobs()
    DeferredThread.instances.clear()

    def workspace_dir(workspace=None):
        ws = "default" if workspace is None else workspace
        if not isinstance(ws, str) or not re.fullmatch(
            r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)", ws,
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid workspace name. Use letters, numbers, hyphens, "
                    "underscores, without spaces or path separators."
                ),
            )
        path = roots.get(ws)
        if path is None:
            path = tmp_path / "outputs" / ws
            path.mkdir(parents=True, exist_ok=True)
            roots[ws] = path
        return str(path)

    def resolve_input_path(value: str, workspace: str | None = None) -> str | None:
        value, workspace = parse_media_ref(value, workspace)
        if not value:
            return None
        name = value.rsplit("/", 1)[-1]
        if value.startswith("/api/v1/uploads/"):
            candidate = roots["__uploads__"] / name
            return str(candidate) if candidate.is_file() else None
        if value.startswith("/api/v1/file/"):
            candidate = Path(workspace_dir(workspace or "default")) / name
            return str(candidate) if candidate.is_file() else None
        if os.path.isabs(value):
            real = os.path.realpath(value)
            allowed = [os.path.realpath(str(item)) for item in roots.values()]
            if any(real == root or real.startswith(root + os.sep) for root in allowed):
                return real if os.path.isfile(real) else None
            return None
        upload = roots["__uploads__"] / name
        if upload.is_file():
            return str(upload)
        candidate = Path(workspace_dir(workspace or "default")) / name
        return str(candidate) if candidate.is_file() else None

    def publish(job: dict, adapter: str):
        events.append(("publish", adapter, job.get("status"), job.get("phase")))
        return {"id": job["task_id"], "root_id": job["root_task_id"]}

    app = FastAPI()
    app.include_router(create_video_editor_router(
        workspace_dir=workspace_dir,
        get_active_workspace=lambda: "default",
        resolve_input_path=resolve_input_path,
        publish_legacy_task=publish,
        thumbnail_cache_dir=str(tmp_path / "thumbs"),
    ))
    app.include_router(create_video_editor_jobs_router())
    return TestClient(app), roots, events


def _export_body(source="clip.mp4", workspace="default", **updates):
    body = {
        "name": "Edited",
        "workspace": workspace,
        "width": 1280,
        "height": 720,
        "fps": 30,
        "clips": [{"source": source, "transition": "none"}],
    }
    body.update(updates)
    return body


def test_router_exposes_the_extracted_http_surface(tmp_path):
    reset_video_editor_jobs()
    editor = create_video_editor_router(
        workspace_dir=lambda workspace=None: str(tmp_path),
        get_active_workspace=lambda: "default",
        resolve_input_path=lambda value, workspace=None: None,
        publish_legacy_task=None,
        thumbnail_cache_dir=str(tmp_path / "thumbs"),
    )
    jobs = create_video_editor_jobs_router()
    assert _route_surface(editor) == EDITOR_HTTP_SURFACE
    assert _route_surface(jobs) == JOBS_HTTP_SURFACE
    export = next(route for route in editor.routes if route.path == "/api/v1/video-editor/export")
    assert export.status_code == 202


def test_router_does_not_import_monolith_gradio_or_weights():
    tree = ast.parse(ROUTER_SOURCE.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    joined = " ".join(modules).lower()
    assert all(
        not module.startswith(("wgp", "launch", "gradio", "torch"))
        and "launch_runtime" not in module
        and "safetensors" not in module
        for module in modules
    )
    assert "gradio" not in joined
    assert "torch" not in joined


def test_probe_and_probe_audio_return_media_contracts(tmp_path):
    client, roots, _events = _harness(tmp_path)
    (roots["film"] / "clip.mp4").write_bytes(b"fake-mp4")
    (roots["film"] / "score.mp3").write_bytes(b"fake-mp3")
    with patch("routers.video_editor.probe_media", return_value=PROBE) as probe:
        response = client.post("/api/v1/video-editor/probe", json={
            "source": "clip.mp4", "workspace": "film",
        })
    assert response.status_code == 200
    assert response.json() == PROBE
    assert probe.call_args[0][0].endswith("film/clip.mp4")
    with patch("routers.video_editor.probe_audio", return_value=AUDIO_PROBE) as probe_audio:
        audio = client.post("/api/v1/video-editor/probe-audio", json={
            "source": "/api/v1/file/score.mp3?workspace=film",
            "workspace": "film",
        })
    assert audio.status_code == 200
    assert audio.json() == AUDIO_PROBE
    assert probe_audio.call_args[0][0].endswith("film/score.mp3")


def test_missing_resource_and_wrong_workspace_are_rejected(tmp_path):
    client, roots, _events = _harness(tmp_path)
    (roots["film"] / "clip.mp4").write_bytes(b"fake-mp4")
    (roots["film"] / "score.mp3").write_bytes(b"fake-mp3")
    (roots["default"] / "notes.txt").write_bytes(b"text")

    missing = client.post("/api/v1/video-editor/probe", json={
        "source": "missing.mp4", "workspace": "film",
    })
    assert missing.status_code == 400
    assert "could not be found" in missing.json()["detail"].lower()

    wrong = client.post("/api/v1/video-editor/probe", json={
        "source": "clip.mp4", "workspace": "default",
    })
    assert wrong.status_code == 400
    assert "could not be found" in wrong.json()["detail"].lower()

    audio_wrong = client.post("/api/v1/video-editor/probe-audio", json={
        "source": "score.mp3", "workspace": "default",
    })
    assert audio_wrong.status_code == 400
    assert "could not be found" in audio_wrong.json()["detail"].lower()

    unsupported = client.post("/api/v1/video-editor/probe", json={
        "source": "notes.txt", "workspace": "default",
    })
    assert unsupported.status_code == 400
    assert "unsupported video format" in unsupported.json()["detail"].lower()

    thumb_missing = client.get("/api/v1/video-editor/thumbnail", params={"source": "missing.mp4"})
    assert thumb_missing.status_code == 400
    thumb_wrong = client.get(
        "/api/v1/video-editor/thumbnail",
        params={"source": "/api/v1/file/clip.mp4?workspace=default"},
    )
    assert thumb_wrong.status_code == 400

    shot_missing = client.post("/api/v1/video-editor/screenshot", json={
        "source": "missing.mp4", "time": 0.2, "name": "frame", "workspace": "film",
    })
    assert shot_missing.status_code == 400
    shot_wrong = client.post("/api/v1/video-editor/screenshot", json={
        "source": "clip.mp4", "time": 0.2, "name": "frame", "workspace": "default",
    })
    assert shot_wrong.status_code == 400


def test_thumbnail_and_screenshot_keep_response_shape(tmp_path):
    client, roots, _events = _harness(tmp_path)
    (roots["default"] / "clip.mp4").write_bytes(b"fake-mp4")
    jpeg = tmp_path / "thumbs" / "preview.jpg"
    jpeg.parent.mkdir(parents=True, exist_ok=True)
    jpeg.write_bytes(b"jpeg-bytes")

    with patch("routers.video_editor.ensure_media_thumbnail", return_value=str(jpeg)):
        thumbnail = client.get("/api/v1/video-editor/thumbnail", params={"source": "clip.mp4"})
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"].startswith("image/jpeg")
    assert thumbnail.content == b"jpeg-bytes"

    def fake_extract(_source, output_path, _time):
        Path(output_path).write_bytes(b"png")
        return {"time": 0.2, "width": 1280, "height": 720}

    with patch("routers.video_editor.extract_frame", side_effect=fake_extract):
        shot = client.post("/api/v1/video-editor/screenshot", json={
            "source": "clip.mp4", "time": 0.2, "name": "hero frame", "workspace": "default",
        })
    assert shot.status_code == 200
    body = shot.json()
    assert body["filename"].endswith("_hero_frame_frame.png")
    assert body["url"] == f"/api/v1/file/{body['filename']}"
    assert body["time"] == 0.2
    assert (roots["default"] / body["filename"]).is_file()


def test_export_validates_clips_and_missing_or_foreign_sources(tmp_path):
    client, roots, _events = _harness(tmp_path)
    (roots["film"] / "clip.mp4").write_bytes(b"fake-mp4")
    empty = client.post("/api/v1/video-editor/export", json={"clips": [], "workspace": "film"})
    assert empty.status_code == 400
    assert empty.json()["detail"] == "Add at least one video clip"
    bad_fps = client.post("/api/v1/video-editor/export", json=_export_body(workspace="film", fps=12))
    assert bad_fps.status_code == 400
    assert bad_fps.json()["detail"] == "Unsupported frame rate"

    with patch("routers.video_editor.threading.Thread", DeferredThread):
        queued = client.post(
            "/api/v1/video-editor/export",
            json=_export_body(source="missing.mp4", workspace="film"),
        )
        assert queued.status_code == 202
        DeferredThread.instances[-1].run_now()
    failed = client.get(f"/api/v1/video-editor/export/{queued.json()['job_id']}")
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert "could not be found" in failed.json()["error"].lower()

    reset_video_editor_jobs()
    DeferredThread.instances.clear()
    with patch("routers.video_editor.threading.Thread", DeferredThread):
        foreign = client.post(
            "/api/v1/video-editor/export",
            json=_export_body(source="clip.mp4", workspace="default"),
        )
        DeferredThread.instances[-1].run_now()
    assert client.get(
        f"/api/v1/video-editor/export/{foreign.json()['job_id']}"
    ).json()["status"] == "failed"


def test_export_queues_publishes_and_completes_without_ffmpeg(tmp_path):
    client, roots, events = _harness(tmp_path)
    (roots["film"] / "clip.mp4").write_bytes(b"fake-mp4")

    def fake_render(_clips, output_path, *, progress, **_settings):
        progress(40, "Encoding editor timeline…")
        Path(output_path).write_bytes(b"fake editor mp4")
        return {"duration": 1.5, "clip_count": 1}

    with patch("routers.video_editor.threading.Thread", DeferredThread), patch(
        "routers.video_editor.render_project", side_effect=fake_render,
    ):
        response = client.post("/api/v1/video-editor/export", json=_export_body(workspace="film"))
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "queued"
        assert body["workspace"] == "film"
        assert body["task_id"].startswith("task-video-editor-")
        assert body["resource_requirements"] == ["local_cpu:ffmpeg"]
        assert events[0][0:3] == ("publish", "video-editor", "queued")
        DeferredThread.instances[-1].run_now()

    status = client.get(f"/api/v1/video-editor/export/{body['job_id']}")
    assert status.status_code == 200
    completed = status.json()
    assert completed["status"] == "completed"
    assert completed["filename"].endswith(".mp4")
    assert (roots["film"] / completed["filename"]).read_bytes() == b"fake editor mp4"
    sidecar = Path(str(roots["film"] / completed["filename"])).with_suffix(".meta.json")
    assert sidecar.is_file()
    assert client.get("/api/v1/video-editor/export/missing-job").status_code == 404


def test_queued_cancel_is_immediate_and_never_renders(tmp_path):
    client, roots, _events = _harness(tmp_path)
    (roots["default"] / "clip.mp4").write_bytes(b"fake-mp4")
    rendered = []

    def fake_render(_clips, output_path, **_kwargs):
        rendered.append(output_path)
        Path(output_path).write_bytes(b"should-not-write")
        return {"duration": 1.0}

    with patch("routers.video_editor.threading.Thread", DeferredThread), patch(
        "routers.video_editor.render_project", side_effect=fake_render,
    ):
        queued = client.post("/api/v1/video-editor/export", json=_export_body())
        job_id = queued.json()["job_id"]
        cancelled = client.post(f"/api/v1/video-editor/export/{job_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["cancel_mode"] == "immediate"
        DeferredThread.instances[-1].run_now()
    assert rendered == []
    assert client.get(f"/api/v1/video-editor/export/{job_id}").json()["status"] == "cancelled"
    assert client.post("/api/v1/video-editor/export/missing/cancel").status_code == 404


def test_running_cancel_waits_for_ffmpeg_boundary_and_removes_output(tmp_path):
    client, roots, _events = _harness(tmp_path)
    (roots["default"] / "clip.mp4").write_bytes(b"fake-mp4")
    render_started = threading.Event()
    release_render = threading.Event()
    next_step: list[bool] = []

    def blocking_render(_clips, output_path, *, progress, **_settings):
        Path(output_path).write_bytes(b"partial mp4")
        Path(output_path).with_suffix(".meta.json").write_text("{}", encoding="utf-8")
        progress(55, "Halfway through FFmpeg…")
        render_started.set()
        assert release_render.wait(timeout=2)
        progress(75, "Current FFmpeg subprocess reached its safe boundary")
        next_step.append(True)
        return {"duration": 2.0}

    @contextmanager
    def acquire(_lane, *, task_id, description, cancelled):
        yield

    with patch("routers.video_editor.render_project", side_effect=blocking_render), patch(
        "routers.video_editor.resource_scheduler.coordinator.acquire", acquire,
    ):
        queued = client.post("/api/v1/video-editor/export", json=_export_body())
        job_id = queued.json()["job_id"]
        assert render_started.wait(timeout=2)
        cancelling = client.post(f"/api/v1/video-editor/export/{job_id}/cancel")
        assert cancelling.json()["status"] == "cancelling"
        assert cancelling.json()["cancel_mode"] == "deferred"
        release_render.set()
        terminal = None
        deadline = time.time() + 3
        while time.time() < deadline:
            terminal = client.get(f"/api/v1/video-editor/export/{job_id}").json()
            if terminal["status"] in {"cancelled", "failed", "completed"}:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("export did not finish after cancel")
    assert terminal["status"] == "cancelled"
    assert terminal["cancel_mode"] == "deferred"
    assert next_step == []
    assert list(roots["default"].glob("*_Edited.mp4")) == []
    assert list(roots["default"].glob("*_Edited.meta.json")) == []
