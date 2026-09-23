"""The gallery can fetch media facts for outputs it already lists."""

from __future__ import annotations

from collections import OrderedDict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from routers.output_facts import MAX_NAMES, create_output_facts_router
from services import media_dimensions
from services.media_thumbnails import ensure_fitted_thumbnail


@pytest.fixture(autouse=True)
def isolated_facts(monkeypatch):
    monkeypatch.setattr(media_dimensions, "_facts", OrderedDict())
    monkeypatch.setattr(media_dimensions, "_queue", OrderedDict())
    monkeypatch.setattr(media_dimensions, "_cache_dir", None)
    monkeypatch.setattr(media_dimensions, "_worker", None)


@pytest.fixture
def client(tmp_path):
    roots = {"default": tmp_path / "default", "__uploads__": tmp_path / "uploads"}
    for root in roots.values():
        root.mkdir()

    def resolve(name, workspace):
        path = roots.get(workspace or "default", roots["default"]) / name
        return str(path) if path.is_file() else None

    app = FastAPI()
    app.include_router(create_output_facts_router(resolve))
    return TestClient(app), roots


def test_facts_report_sizes_and_colours_that_are_known(client, tmp_path):
    http, roots = client
    Image.new("RGB", (640, 360), (20, 160, 60)).save(roots["default"] / "still.png")
    (roots["default"] / "clip.mp4").write_bytes(b"not probed yet")
    (roots["default"] / "song.mp3").write_bytes(b"audio")

    first = http.post("/api/v1/outputs/facts", json={"names": ["still.png", "clip.mp4", "song.mp3", "missing.png"]})
    assert first.status_code == 200
    assert first.json() == {"facts": {"still.png": {"width": 640, "height": 360}}}

    # The worker records a colour later; the next request carries it.
    preview = ensure_fitted_thumbnail(str(roots["default"] / "still.png"), str(tmp_path / "cache"), is_video=False, size="sm")
    media_dimensions.note_preview(str(roots["default"] / "still.png"), preview)
    second = http.post("/api/v1/outputs/facts", json={"names": ["still.png"]}).json()["facts"]["still.png"]
    assert second["width"] == 640 and second["color"].startswith("#")


def test_facts_follow_the_requested_workspace(client):
    http, roots = client
    Image.new("RGB", (100, 300)).save(roots["__uploads__"] / "upload.png")
    assert http.post("/api/v1/outputs/facts", json={"names": ["upload.png"]}).json() == {"facts": {}}
    listed = http.post("/api/v1/outputs/facts", json={"names": ["upload.png"], "workspace": "__uploads__"}).json()
    assert listed == {"facts": {"upload.png": {"width": 100, "height": 300}}}


def test_facts_reject_invalid_requests(client):
    http, _roots = client
    assert http.post("/api/v1/outputs/facts", json={"names": [""]}).status_code == 400
    assert http.post("/api/v1/outputs/facts", json={"names": ["x" * 600]}).status_code == 400
    assert http.post("/api/v1/outputs/facts", json={"names": ["a.png"] * (MAX_NAMES + 1)}).status_code == 422
    assert http.post("/api/v1/outputs/facts", json={"names": "a.png"}).status_code == 422
