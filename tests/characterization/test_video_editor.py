"""Uploads (stored name, served bytes, fallback to outputs) and the video editor probes, on a one-second clip and half a second of silence."""
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


def test_upload_png_is_served_back_byte_for_byte(server, golden, tmp_path) -> None:
    picture = media.image(tmp_path / "source" / "picture.png")
    with picture.open("rb") as handle:
        uploaded = server.check(golden, "upload png", "POST", "/api/v1/upload",
                                files={"file": ("picture.png", handle, "image/png")})
    stored = server.root / "uploads" / uploaded.json()["filename"]
    assert stored.read_bytes() == picture.read_bytes()
    served = server.client.get(uploaded.json()["url"])
    assert served.status_code == 200
    assert served.content == picture.read_bytes()
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"


def test_upload_with_a_page_or_script_extension_is_stored_as_bin(server, golden) -> None:
    for name, content_type in (("evil.html", "text/html"), ("evil.svg", "image/svg+xml"),
                               ("evil.js", "application/javascript")):
        payload = b"<script>alert(document.domain)</script>"
        uploaded = server.check(golden, f"upload {name}", "POST", "/api/v1/upload",
                                files={"file": (name, payload, content_type)})
        assert uploaded.json()["filename"].endswith(".bin")
        served = server.client.get(uploaded.json()["url"])
        assert served.status_code == 200
        assert served.content == payload
        assert served.headers["content-type"] == "application/octet-stream"
        assert served.headers["x-content-type-options"] == "nosniff"


def test_upload_without_an_extension_is_named_png(server, golden) -> None:
    uploaded = server.check(golden, "upload no-extension", "POST", "/api/v1/upload",
                            files={"file": ("clipboard", b"pasted bytes", "application/octet-stream")})
    assert uploaded.json()["filename"].endswith(".png")


def test_compressed_audio_upload_is_transcoded_to_wav(server, golden, tmp_path) -> None:
    tone = media.compressed_sound(tmp_path / "source" / "tone.aac")
    with tone.open("rb") as handle:
        uploaded = server.check(golden, "upload aac", "POST", "/api/v1/upload",
                                files={"file": ("tone.aac", handle, "audio/aac")})
    assert uploaded.json()["filename"].endswith(".wav")
    assert [item.name for item in (server.root / "uploads").iterdir()] == [uploaded.json()["filename"]]
    served = server.client.get(uploaded.json()["url"])
    assert served.content[:4] == b"RIFF"
    assert served.headers["content-type"].startswith("audio/")


def test_compressed_audio_that_cannot_be_decoded_is_refused_and_removed(server, golden) -> None:
    media.need_ffmpeg()
    response = server.client.post("/api/v1/upload", files={"file": ("broken.mp3", b"this is not audio", "audio/mpeg")})
    assert response.status_code == 400
    assert response.json()["detail"].startswith("Failed to decode .mp3 audio:")
    assert list((server.root / "uploads").iterdir()) == []


def test_serving_an_upload_that_is_not_there(server, golden) -> None:
    (server.root / "secret.txt").write_text("outside the uploads folder", encoding="utf-8")
    server.check(golden, "serve a missing upload", "GET", "/api/v1/uploads/never-uploaded.png")
    for case, name in (("a parent folder", "%2e%2e"), ("a path out of uploads", "%2e%2e%2fsecret.txt"),
                       ("a path out of uploads with a drive", "..%5C..%5Csecret.txt")):
        response = server.check(golden, f"serve {case}", "GET", f"/api/v1/uploads/{name}")
        assert response.status_code == 404
        assert "outside the uploads folder" not in response.text


def test_an_upload_url_falls_back_to_the_workspace_outputs(server, golden) -> None:
    keyframe = media.image(server.outputs / "keyframe.png")
    served = server.client.get("/api/v1/uploads/keyframe.png")
    assert served.status_code == 200
    assert served.content == keyframe.read_bytes()
    assert served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"


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
