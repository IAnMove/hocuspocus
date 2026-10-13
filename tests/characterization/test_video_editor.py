"""Uploads and the video editor probes, on a one-second clip and half a second of silence."""
from __future__ import annotations

from tests.characterization import media


def test_upload_then_probe(server, golden, tmp_path) -> None:
    clip = media.video(tmp_path / "source" / "clip.mp4")
    with clip.open("rb") as handle:
        uploaded = server.check(golden, "upload clip", "POST", "/api/v1/upload",
                                files={"file": ("clip.mp4", handle, "video/mp4")})
    source = uploaded.json()["url"]
    server.check(golden, "probe uploaded clip", "POST", "/api/v1/video-editor/probe", json={"source": source})

    media.video(server.outputs / "golden_take.mp4", seconds=2, size="48x32", fps=12)
    server.check(golden, "probe workspace clip", "POST", "/api/v1/video-editor/probe",
                 json={"source": "golden_take.mp4", "workspace": "default"})

    media.sound(server.outputs / "golden_track.wav")
    server.check(golden, "probe audio", "POST", "/api/v1/video-editor/probe-audio",
                 json={"source": "golden_track.wav", "workspace": "default"})


def test_probe_errors(server, golden) -> None:
    (server.outputs / "notes.txt").write_text("not media", encoding="utf-8")
    server.check(golden, "probe without source", "POST", "/api/v1/video-editor/probe", json={})
    server.check(golden, "probe missing file", "POST", "/api/v1/video-editor/probe",
                 json={"source": "missing.mp4", "workspace": "default"})
    server.check(golden, "probe unsupported file", "POST", "/api/v1/video-editor/probe",
                 json={"source": "notes.txt", "workspace": "default"})
    server.check(golden, "probe outside workspace", "POST", "/api/v1/video-editor/probe",
                 json={"source": "../../etc/passwd", "workspace": "default"})
    server.check(golden, "probe audio without source", "POST", "/api/v1/video-editor/probe-audio", json={})
    server.check(golden, "export missing job", "GET", "/api/v1/video-editor/export/video-edit-doesnotexist")
