"""ASGI contracts for the extracted Comics HTTP routers."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.comics import create_comics_animatic_router, create_comics_router
from services import minimax_image_service


COMICS_HTTP_SURFACE = [
    ("POST", "/api/v1/comics", "create_comic_output"),
    ("POST", "/api/v1/comics/history", "create_comic_history"),
    ("GET", "/api/v1/comics/history", "list_comic_history"),
    ("GET", "/api/v1/comics/history/{snapshot_id}", "get_comic_history"),
    ("PUT", "/api/v1/comics/{name}", "update_comic_output"),
    ("GET", "/api/v1/comics/{name}", "get_comic_output"),
    ("POST", "/api/v1/comics/generate/minimax/jobs", "start_comic_minimax_job"),
    ("GET", "/api/v1/comics/generate/minimax/jobs/{job_id}", "get_comic_minimax_job"),
    ("POST", "/api/v1/comics/generate/minimax/jobs/{job_id}/cancel", "cancel_comic_minimax_job"),
    ("POST", "/api/v1/comics/generate/minimax", "generate_comic_minimax"),
]

PREVIEW = "data:image/png;base64," + base64.b64encode(b"preview-bytes").decode("ascii")


def _safe_join(base: str, *parts: str) -> str | None:
    try:
        base_real = os.path.realpath(base)
        joined = os.path.realpath(os.path.join(base_real, *parts))
        if os.path.commonpath((base_real, joined)) != base_real:
            return None
        return joined
    except (ValueError, OSError):
        return None


def _project(**updates):
    project = {
        "version": 2,
        "id": "comic-1",
        "title": "Salt Desert",
        "pages": [{"id": "p1"}],
        "assets": {},
    }
    project.update(updates)
    return project


def _router(tmp_path: Path, *, services=None, publish=None):
    return create_comics_router(
        workspace_dir=lambda workspace=None: str(tmp_path),
        get_active_workspace=lambda: "default",
        safe_join=_safe_join,
        get_services_config=lambda: services or {"minimax_api_key": "test-key"},
        publish_legacy_task=publish or (lambda job, adapter: {"id": f"task-{job['jobId']}", "root_id": f"task-{job['jobId']}"}),
    )


def _client(tmp_path: Path, **kwargs) -> TestClient:
    app = FastAPI()
    app.include_router(_router(tmp_path, **kwargs))
    return TestClient(app)


def _route_surface(router):
    found = []
    for route in router.routes:
        methods = sorted(method for method in (route.methods or set()) if method not in {"HEAD", "OPTIONS"})
        for method in methods:
            found.append((method, route.path, route.endpoint.__name__))
    return found


def test_comics_router_exposes_the_extracted_http_surface(tmp_path):
    assert _route_surface(_router(tmp_path)) == COMICS_HTTP_SURFACE


def test_comics_animatic_router_keeps_the_original_path_and_status():
    router = create_comics_animatic_router(
        workspace_dir=lambda workspace=None: "/tmp",
        get_active_workspace=lambda: "default",
        video_editor_task_identity=lambda _body, job_id: (f"task-{job_id}", f"task-{job_id}", None),
        register_video_editor_job=lambda job: job,
        video_editor_job_update=lambda job_id, **patch: {"job_id": job_id, **patch},
        public_video_editor_job=lambda job: job,
        ffmpeg_lane_key="cpu:ffmpeg",
        run_comic_animatic=lambda *_args: None,
    )
    assert _route_surface(router) == [
        ("POST", "/api/v1/comics/animatic", "start_comic_animatic"),
    ]
    route = router.routes[0]
    assert route.status_code == 202


def test_create_get_and_update_comic_round_trip(tmp_path):
    client = _client(tmp_path)
    created = client.post("/api/v1/comics", json={
        "project": _project(),
        "preview": PREVIEW,
    })
    assert created.status_code == 200
    name = created.json()["name"]
    assert name.endswith(".comic.json")
    loaded = client.get(f"/api/v1/comics/{name}")
    assert loaded.status_code == 200
    assert loaded.json()["project"]["title"] == "Salt Desert"
    updated = client.put(f"/api/v1/comics/{name}", json={
        "project": _project(title="Revised desert"),
    })
    assert updated.status_code == 200
    assert client.get(f"/api/v1/comics/{name}").json()["project"]["title"] == "Revised desert"
    preview = tmp_path / name.replace(".comic.json", ".comic.preview.png")
    assert preview.read_bytes() == b"preview-bytes"


def test_comic_history_deduplicates_identical_checkpoints(tmp_path):
    client = _client(tmp_path)
    first = client.post("/api/v1/comics/history", json={"project": _project()}).json()
    second = client.post("/api/v1/comics/history", json={"project": _project()}).json()
    assert first["id"] == second["id"]
    listed = client.get("/api/v1/comics/history", params={"comic_id": "comic-1"}).json()
    assert len(listed["history"]) == 1
    snapshot = client.get(f"/api/v1/comics/history/{first['id']}")
    assert snapshot.status_code == 200
    assert snapshot.json()["project"]["id"] == "comic-1"


def test_comic_rejects_blob_assets_and_missing_projects(tmp_path):
    client = _client(tmp_path)
    rejected = client.post("/api/v1/comics", json={
        "project": _project(assets={"a": {"source": "blob:http://localhost/1"}}),
        "preview": PREVIEW,
    })
    assert rejected.status_code == 400
    assert client.get("/api/v1/comics/missing.comic.json").status_code == 404


def test_minimax_job_is_observable_and_cancellable_before_provider(tmp_path):
    client = _client(tmp_path)
    with patch("routers.comics.threading.Thread") as thread_cls:
        thread_cls.return_value.start = lambda: None
        started = client.post("/api/v1/comics/generate/minimax/jobs", json={
            "prompt": "A hero at dusk",
            "aspect_ratio": "4:3",
        })
    assert started.status_code == 200
    job_id = started.json()["jobId"]
    cancelled = client.post(f"/api/v1/comics/generate/minimax/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    status = client.get(f"/api/v1/comics/generate/minimax/jobs/{job_id}")
    assert status.json()["jobId"] == job_id
    assert status.json()["status"] == "cancelled"


def test_sync_minimax_generation_encodes_a_local_workspace_reference(tmp_path):
    (tmp_path / "hero.png").write_bytes(b"reference-image")
    client = _client(tmp_path)
    captured = {}

    def fake_generate_image(**kwargs):
        captured.update(kwargs)
        return {
            "name": "minimax-comic.png",
            "prompt": kwargs["prompt"],
            "subject_reference": True,
            "aspect_ratio": kwargs["aspect_ratio"],
        }

    with patch.object(minimax_image_service, "generate_image", fake_generate_image):
        result = client.post("/api/v1/comics/generate/minimax", json={
            "prompt": "The hero crosses the salt desert at dusk.",
            "aspect_ratio": "4:3",
            "subject_reference": "/api/v1/file/hero.png",
        })
    assert result.status_code == 200
    assert captured["aspect_ratio"] == "4:3"
    assert captured["subject_reference"].startswith("data:image/png;base64,")
    assert result.json()["asset"]["metadata"]["aspectRatio"] == "4:3"


def test_private_reference_url_is_rejected_on_sync_generate(tmp_path):
    client = _client(tmp_path)
    with patch.object(minimax_image_service, "generate_image", side_effect=AssertionError("should not call provider")):
        result = client.post("/api/v1/comics/generate/minimax", json={
            "prompt": "A hero at dusk",
            "subject_reference": "http://127.0.0.1/private.png",
        })
    assert result.status_code == 400
    assert result.json()["detail"] == "Character reference URL must be public"
