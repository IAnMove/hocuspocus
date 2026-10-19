"""The shared uploads router with stub adapters: each branch, without a server, ffmpeg or Torch.

Both servers mount this router (tests/characterization covers the full server, and
tests/test_core_runtime.py the core server); here the injected parts are stubs.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient

from routers.uploads import UPLOAD_EXTENSIONS, create_uploads_router
from services.core_workspace import safe_join
from services.upload_stream import UploadTooLargeError, UploadTranscodeError


class Harness:
    """One router over a temp uploads folder, recording what it asked of its adapters."""

    def __init__(self, tmp_path: Path) -> None:
        self.uploads = tmp_path / "uploads"
        self.outputs = tmp_path / "outputs"
        self.outputs.mkdir()
        self.streamed: list[str] = []
        self.transcoded: list[tuple[str, str, bool]] = []
        self.probed: list[str] = []
        self.stream_error: Exception | None = None
        self.transcode_error: Exception | None = None
        self.probe_result: dict | Exception | None = {"fps": 25.0, "frame_count": 50, "duration_seconds": 2.0,
                                                      "has_audio": True}
        self.router = create_uploads_router(
            uploads_dir=lambda: str(self.uploads),
            stream_upload=self._stream,
            transcode_upload=self._transcode,
            probe_video_metadata=self._probe,
            safe_join=safe_join,
            output_fallback=self._fallback,
        )
        app = FastAPI()
        app.include_router(self.router)
        self.client = TestClient(app)

    async def _stream(self, upload, destination, *, max_bytes):
        self.streamed.append(destination)
        if self.stream_error is not None:
            raise self.stream_error
        data = await upload.read()
        if len(data) > max_bytes:
            raise UploadTooLargeError("too big")
        Path(destination).write_bytes(data)
        return len(data)

    async def _transcode(self, source, destination, *, is_video):
        self.transcoded.append((source, destination, is_video))
        if self.transcode_error is not None:
            raise self.transcode_error
        Path(destination).write_bytes(b"RIFF....WAVE")

    def _probe(self, path):
        self.probed.append(path)
        if isinstance(self.probe_result, Exception):
            raise self.probe_result
        return self.probe_result

    def _fallback(self, filename):
        target = self.outputs / filename
        if not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(target)  # a plain response: the router must still say nosniff

    def upload(self, name: str, payload: bytes = b"bytes", content_type: str = "application/octet-stream"):
        return self.client.post("/api/v1/upload", files={"file": (name, payload, content_type)})

    def stored(self) -> list[str]:
        return sorted(item.name for item in self.uploads.iterdir()) if self.uploads.is_dir() else []


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_the_router_keeps_the_endpoint_names_the_route_table_records(harness: Harness) -> None:
    assert [(sorted(route.methods), route.path, route.endpoint.__name__) for route in harness.router.routes] == [
        (["POST"], "/api/v1/upload", "upload_image"),
        (["GET"], "/api/v1/uploads/{filename}", "serve_upload"),
    ]


@pytest.mark.parametrize("name,expected", [
    ("photo.png", ".png"), ("PHOTO.JPG", ".jpg"), ("clip.mp4", ".mp4"), ("model.glb", ".glb"),
    ("notes.json", ".json"), ("clipboard", ".png"),
    ("evil.html", ".bin"), ("evil.htm", ".bin"), ("evil.svg", ".bin"), ("evil.js", ".bin"), ("evil.mjs", ".bin"),
    ("evil.xml", ".bin"), ("evil.xhtml", ".bin"), ("evil.php", ".bin"), ("evil.html.png.exe", ".bin"),
    ("evil.png.html", ".bin"), ("evil.HTML", ".bin"),
])
def test_only_listed_extensions_survive_and_everything_else_is_stored_as_bin(harness: Harness, name, expected) -> None:
    answer = harness.upload(name)
    assert answer.status_code == 200, answer.text
    assert answer.json()["filename"].endswith(expected)
    assert harness.stored() == [answer.json()["filename"]]


def test_no_page_or_script_type_is_on_the_allow_list() -> None:
    assert not UPLOAD_EXTENSIONS & {".html", ".htm", ".xhtml", ".svg", ".svgz", ".js", ".mjs", ".xml", ".swf", ".php"}


def test_an_upload_over_the_cap_is_refused_before_and_while_streaming(harness: Harness) -> None:
    with patch("routers.uploads.MAX_IMAGE_UPLOAD_BYTES", 4):
        before = harness.upload("big.png", b"12345")
    assert (before.status_code, before.json()["detail"]) == (413, "File too large (max 500 MB)")
    assert harness.streamed == []
    harness.stream_error = UploadTooLargeError("stream cap")
    while_streaming = harness.upload("big.png")
    assert (while_streaming.status_code, while_streaming.json()["detail"]) == (413, "File too large (max 500 MB)")
    assert len(harness.streamed) == 1


def test_compressed_audio_is_transcoded_to_wav_and_the_original_removed(harness: Harness) -> None:
    for name in ("a.mp3", "b.m4a", "c.aac"):
        answer = harness.upload(name)
        assert answer.status_code == 200, answer.text
        assert answer.json()["filename"].endswith(".wav")
    assert all(not is_video for _source, _destination, is_video in harness.transcoded)
    assert len(harness.stored()) == 3 and all(item.endswith(".wav") for item in harness.stored())
    assert not harness.probed


def test_a_transcode_error_answers_400_with_its_message_and_removes_both_files(harness: Harness) -> None:
    harness.transcode_error = UploadTranscodeError("ffmpeg failed", stderr="  Invalid data found  ")
    answer = harness.upload("broken.mp3")
    assert (answer.status_code, answer.json()["detail"]) == (400, "Failed to decode .mp3 audio: Invalid data found")
    assert harness.stored() == []


def test_any_other_transcode_failure_answers_500_and_removes_both_files(harness: Harness) -> None:
    harness.transcode_error = ModuleNotFoundError("No module named 'ffmpeg'")
    answer = harness.upload("broken.aac")
    assert (answer.status_code, answer.json()["detail"]) == (500, "Audio transcode failed: No module named 'ffmpeg'")
    assert harness.stored() == []


def test_a_video_upload_reports_what_the_probe_found(harness: Harness) -> None:
    answer = harness.upload("clip.mov", b"video")
    body = answer.json()
    assert {key: body[key] for key in ("fps", "frame_count", "duration_seconds", "has_audio")} == {
        "fps": 25.0, "frame_count": 50, "duration_seconds": 2.0, "has_audio": True,
    }
    assert harness.probed == [body["path"]]


def test_a_probe_that_fails_or_finds_nothing_leaves_the_plain_answer(harness: Harness) -> None:
    for outcome in (RuntimeError("no decoder"), None, {}):
        harness.probe_result = outcome
        body = harness.upload("clip.mp4").json()
        assert set(body) == {"filename", "path", "url"}


def test_only_video_extensions_are_probed(harness: Harness) -> None:
    for name in ("a.png", "b.wav", "c.glb", "evil.html"):
        harness.upload(name)
    assert harness.probed == []


def test_an_upload_is_served_back_with_nosniff(harness: Harness) -> None:
    body = harness.upload("photo.png", b"png bytes", "image/png").json()
    served = harness.client.get(body["url"])
    assert (served.status_code, served.content) == (200, b"png bytes")
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"


def test_a_name_that_is_not_an_upload_goes_to_the_fallback_which_cannot_escape(harness: Harness, tmp_path: Path) -> None:
    (harness.outputs / "keyframe.png").write_bytes(b"keyframe")
    (tmp_path / "secret.txt").write_text("outside the uploads folder", encoding="utf-8")
    harness.uploads.mkdir()
    fallback = harness.client.get("/api/v1/uploads/keyframe.png")
    assert (fallback.status_code, fallback.content) == (200, b"keyframe")
    assert fallback.headers["x-content-type-options"] == "nosniff"  # the fallback's own response was plain
    assert harness.client.get("/api/v1/uploads/never-there.png").status_code == 404
    # "../secret.txt" is outside uploads: safe_join refuses it and the fallback (here, outputs/) has no such file.
    for name in ("%2e%2e", "%2e%2e%2fsecret.txt", "..%5Csecret.txt"):
        refused = harness.client.get(f"/api/v1/uploads/{name}")
        assert refused.status_code == 404
        assert "outside the uploads folder" not in refused.text
