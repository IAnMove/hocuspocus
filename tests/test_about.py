"""About page: repository, author and the deployed commit pinned at startup."""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app_identity
from routers.about import create_about_router
from services.asset_manifest import build_asset_manifest


def test_about_reports_backend_and_ui_build(tmp_path):
    backend = app_identity.startup_identity()
    (tmp_path / "build-info.json").write_text(json.dumps({"schema": 1, "commit": backend["commit"], "branch": "development",
                                                          "build_id": "abc-1", "built_at": "2026-09-27T18:30:43+00:00", "files": {}}))
    api = FastAPI()
    api.include_router(create_about_router(tmp_path))
    body = TestClient(api).get("/api/v1/about").json()
    assert body["repository"] == "https://github.com/IAnMove/hocuspocus"
    assert body["author"] == {"x_handle": "theinaog", "x_url": "https://x.com/theinaog"}
    assert body["backend"]["commit"] == backend["commit"] and body["backend"]["started_at"]
    assert body["ui"] == {"commit": backend["commit"], "branch": "development", "build_id": "abc-1", "built_at": "2026-09-27T18:30:43+00:00"}
    assert body["in_sync"] is (backend["commit"] != "unknown")
    assert {item["name"] for item in body["credits"]} >= {"Maestro", "WanGP", "ACE-Step"}


def test_about_without_build_receipt_is_not_in_sync(tmp_path):
    body = app_identity.about_payload(tmp_path)
    assert body["ui"] == {} and body["in_sync"] is False


def test_startup_identity_is_pinned(monkeypatch):
    first = app_identity.startup_identity()
    monkeypatch.setattr(app_identity, "_git", lambda *args, **kwargs: "f" * 40)
    assert app_identity.startup_identity() is first


def test_runtime_identity_carries_backend_and_ui_commits(tmp_path):
    from services.live_stats import get_runtime_identity
    (tmp_path / "index.html").write_text("<html></html>")
    (tmp_path / "build-info.json").write_text(json.dumps({"commit": "c" * 40}))
    identity = get_runtime_identity(tmp_path)
    assert identity["commit"] == app_identity.startup_identity()["commit"] and identity["ui_commit"] == "c" * 40


def test_asset_manifests_record_the_running_commit(tmp_path):
    manifest = build_asset_manifest(tmp_path / "clip.mp4", tool="test")
    assert manifest["origin"]["app"] == app_identity.manifest_app_ref()
    assert manifest["origin"]["app"]["commit"] == app_identity.startup_identity()["commit"]
