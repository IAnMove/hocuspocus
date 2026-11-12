"""Exercise Viggle's real frame extraction without loading a model or GPU."""

import ast
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import time
from types import SimpleNamespace
import uuid

from fastapi import HTTPException
from PIL import Image
import pytest

from services.kernel.config import ConfigStore
from services.kernel.workspaces import WorkspaceService
from services.wangp_submission import JsonRequest, prepare_viggle_recast, probe_video, resolve_wangp_media


EDIT_REQUESTS = Path(__file__).parents[1] / "app" / "services" / "studio_edit_requests.py"
DIRECTOR = Path(__file__).parents[1] / "app" / "routers" / "llm_director.py"


@pytest.fixture
def extract(tmp_path, monkeypatch):
    """Load the real endpoint and resolver while avoiding launcher side effects."""
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "outputs" / "demo"
    uploads.mkdir()
    workspace.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    selected = []
    for path, names in (
        (EDIT_REQUESTS, {"extract_frames_endpoint"}),
        (DIRECTOR, {"_resolve_wangp_visual_media"}),
    ):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
                node.decorator_list = []
                selected.append(node)
    assert len(selected) == 2
    engine = SimpleNamespace(server_config={"save_path": "outputs", "services": {"active_workspace": "demo"}})
    workspaces = WorkspaceService(ConfigStore(lambda: engine))
    namespace = {
        "Request": object,
        "HTTPException": HTTPException,
        "os": os,
        "re": re,
        "uuid": uuid,
        "time": time,
        "wgp": engine,
        "_workspace_dir": workspaces.workspace_dir,
        "_get_active_workspace": lambda: "demo",
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(EDIT_REQUESTS), "exec"), namespace)

    def submit(video_path, **options):
        body = {"video_path": video_path, "start_time": 0, **options}
        return asyncio.run(namespace["extract_frames_endpoint"](JsonRequest(body)))

    return submit, uploads, workspace


def make_video(path, size):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
         f"color=c=red:s={size}:r=24:d=0.125", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )


@pytest.mark.parametrize(
    ("url", "root", "size"),
    [
        ("/api/v1/uploads/source%20clip.mp4", "uploads", (832, 480)),
        ("/api/v1/file/source%20clip.mp4?workspace=demo", "workspace", (480, 832)),
        ("/api/v1/file/source%20clip.mp4", "workspace", (480, 832)),
    ],
)
def test_canonical_source_keeps_root_identity_and_frame_dimensions(extract, url, root, size):
    submit, uploads, workspace = extract
    make_video(uploads / "source clip.mp4", "832x480")
    make_video(workspace / "source clip.mp4", "480x832")

    result = submit(url, wangp_media=True, **({"workspace": "demo"} if root == "uploads" else {}))

    with Image.open(result["start_path"]) as frame:
        assert frame.size == size
    assert Path(result["start_path"]).parent == uploads
    assert result["start_url"] == f"/api/v1/uploads/{Path(result['start_path']).name}"
    assert "end_path" not in result


def test_wangp_accepts_the_absolute_upload_path_from_legacy_roundtrip(extract):
    submit, uploads, _ = extract
    source = uploads / "source.mp4"
    make_video(source, "832x480")
    result = submit(str(source), wangp_media=True, start_time=None, end_time=0.04)
    with Image.open(result["end_path"]) as frame:
        assert frame.size == (832, 480)
    assert "start_path" not in result


def test_wangp_frame_session_uses_server_time_with_fractional_seconds(extract, monkeypatch):
    submit, uploads, _ = extract
    source = uploads / "source.mp4"
    make_video(source, "832x480")
    server_time = 1_750_000_000.123456
    monkeypatch.setattr(time, "time", lambda: server_time)
    result = submit(str(source), wangp_media=True, session_started_at=1)
    assert result["session_started_at"] == server_time
    assert "session_started_at" not in submit(str(source))


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/file/source.mp4?workspace=other",
        "/api/v1/uploads/../external.mp4",
        "/api/v1/uploads/%2E%2E/external.mp4",
        "https://example.com/source.mp4",
        "/api/v1/uploads/source.mp4",
    ],
)
def test_wangp_rejects_missing_or_foreign_media_before_extracting(extract, url):
    submit, uploads, workspace = extract
    # A basename in a different root must never substitute for the selected URL.
    (workspace / "source.mp4").write_bytes(b"not decoded")
    (uploads.parent / "external.mp4").write_bytes(b"not decoded")
    with pytest.raises(HTTPException) as error:
        submit(url, wangp_media=True, workspace="demo")
    assert error.value.status_code == 400
    assert not list(uploads.glob("frame_*.png"))


@pytest.mark.parametrize("workspace", ["../foreign", "demo space"])
def test_wangp_rejects_invalid_workspace_before_extracting(extract, workspace):
    submit, uploads, _ = extract
    with pytest.raises(HTTPException) as error:
        submit("/api/v1/uploads/source.mp4", wangp_media=True, workspace=workspace)
    assert error.value.status_code == 400
    assert "Invalid workspace" in error.value.detail
    assert not list(uploads.glob("frame_*.png"))


@pytest.mark.parametrize("via_symlink", [False, True])
def test_wangp_rejects_absolute_and_symlink_escape(extract, via_symlink):
    submit, uploads, _ = extract
    source = uploads.parent / "external.mp4"
    source.write_bytes(b"not decoded")
    value = str(source)
    if via_symlink:
        (uploads / "escape.mp4").symlink_to(source)
        value = "/api/v1/uploads/escape.mp4"
    with pytest.raises(HTTPException) as error:
        submit(value, wangp_media=True)
    assert error.value.status_code == 400
    assert not list(uploads.glob("frame_*.png"))


@pytest.mark.parametrize("absolute", [False, True])
def test_legacy_extraction_keeps_absolute_and_relative_paths(extract, absolute):
    submit, uploads, workspace = extract
    source = (uploads if absolute else workspace) / "legacy.mp4"
    make_video(source, "832x480")
    result = submit(str(source) if absolute else source.name)
    with Image.open(result["start_path"]) as frame:
        assert frame.size == (832, 480)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_display_rotation_keeps_extracted_frame_valid_for_viggle(extract, rotation):
    submit, uploads, workspace = extract
    raw = uploads / "raw.mp4"
    source = uploads / "phone.mp4"
    make_video(raw, "832x480")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-display_rotation", str(rotation),
         "-i", str(raw), "-c", "copy", str(source)],
        check=True, capture_output=True,
    )
    result = submit("/api/v1/uploads/phone.mp4", wangp_media=True)
    expected = (480, 832) if rotation in (90, 270) else (832, 480)
    with Image.open(result["start_path"]) as frame:
        assert frame.size == expected
    assert probe_video(source)[:2] == expected

    def resolve(value, selected_workspace):
        return resolve_wangp_media(
            value, selected_workspace, uploads_dir=uploads, workspace_dir=workspace,
        )

    params = prepare_viggle_recast(
        {"video_path": "/api/v1/uploads/phone.mp4", "ref_image_path": result["start_url"],
         "workspace": "demo"},
        resolve, uploads,
    )
    assert params["resolution"] == f"{expected[0]}x{expected[1]}"
    assert params["image_refs"] == [result["start_path"]]


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({}, (832, 480)),
        ({"tags": {"rotate": "90"}}, (480, 832)),
        ({"tags": {"rotate": "180"}}, (832, 480)),
        ({"tags": {"rotate": "270"}}, (480, 832)),
        ({"side_data_list": [{"rotation": 0}], "tags": {"rotate": "90"}}, (832, 480)),
        ({"side_data_list": [{"rotation": -90}], "tags": {"rotate": "180"}}, (480, 832)),
    ],
)
def test_probe_uses_display_matrix_before_legacy_rotation_tag(monkeypatch, metadata, expected):
    payload = {"streams": [{"width": 832, "height": 480, **metadata}], "format": {"duration": "3.5"}}
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(payload)))
    assert probe_video("phone.mp4") == (*expected, 3.5)
