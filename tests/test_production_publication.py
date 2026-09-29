import asyncio
import functools
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.production_publication import publication_handlers
from services.publication_server import PublicationHandler, serve_publication


@pytest.fixture
def publication(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    public = tmp_path / "public"
    public.mkdir()
    (public / "index.html").write_text("Another session owns this page")
    for name in ("final.mp4", "sheet.jpg", "song.wav", "hero.glb"):
        (workspace / name).write_bytes(name.encode())
    state = {"status": "completed", "final": "final.mp4", "contact_sheet": "sheet.jpg",
             "song": {"file": "song.wav"}, "spec": {"title": '<script>alert("x")</script> & song'}}
    (workspace / "test.production.json").write_text(json.dumps(state))
    monkeypatch.setenv("HOCUS_PUBLICATION_ROOT", str(public))
    monkeypatch.setenv("HOCUS_PUBLICATION_BASE_URL", "http://127.0.0.1:8844")
    monkeypatch.delenv("HOCUS_PUBLICATION_SERVE", raising=False)
    handler = publication_handlers(lambda ws: str(workspace))["production.publish"]
    arguments = {"version": 1, "input": {"workspace": "ws", "production_id": "test", "slug": "homage", "extras": ["hero.glb"]}}
    return workspace, public, handler, arguments


def call(handler, arguments):
    return asyncio.run(handler(arguments))["result"]


def test_publish_copies_only_selected_assets_and_preserves_existing_page(publication):
    workspace, public, handler, arguments = publication
    (workspace / "private.json").write_text("private")
    result = call(handler, arguments)
    directory = public / ("homage-" + result["publication_id"])
    assert (public / "index.html").read_text() == "Another session owns this page"
    assert (directory / "video.mp4").read_bytes() == b"final.mp4"
    assert not (directory / "private.json").exists()
    assert not (directory / "index.html").exists()
    page = (directory / "homage.html").read_text()
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "Fan-made homage, not affiliated with Nintendo" in page
    assert result["page"].endswith("/homage.html")
    first_mtime = (directory / "video.mp4").stat().st_mtime_ns
    assert call(handler, arguments) == result
    assert (directory / "video.mp4").stat().st_mtime_ns == first_mtime
    (workspace / "final.mp4").write_bytes(b"a new completed retake")
    assert call(handler, arguments)["publication_id"] != result["publication_id"]
    assert (directory / "video.mp4").read_bytes() == b"final.mp4"


@pytest.mark.parametrize("field,value", [("workspace", "../outside"), ("production_id", "../test"), ("slug", "index.html"), ("extras", ["../secret.json"]), ("extras", ["index.html"]), ("extras", ["video.mp4"])])
def test_rejects_traversal_and_reserved_names(publication, field, value):
    _, _, handler, arguments = publication
    arguments["input"][field] = value
    with pytest.raises(HTTPException):
        call(handler, arguments)


def test_refuses_unfinished_production_and_symlinked_source(publication):
    workspace, public, handler, arguments = publication
    path = workspace / "test.production.json"
    state = json.loads(path.read_text())
    state["status"] = "running"
    path.write_text(json.dumps(state))
    with pytest.raises(HTTPException, match="completed production"):
        call(handler, arguments)
    state["status"] = "completed"
    path.write_text(json.dumps(state))
    (workspace / "hero.glb").unlink()
    (workspace / "hero.glb").symlink_to(public / "index.html")
    with pytest.raises(HTTPException, match="regular file"):
        call(handler, arguments)


@pytest.mark.parametrize("name", ["video.mp4", "homage.html", "publication.json"])
def test_existing_publication_is_never_overwritten_if_tampered(publication, name):
    _, public, handler, arguments = publication
    result = call(handler, arguments)
    destination = public / ("homage-" + result["publication_id"])
    (destination / name).write_text("changed externally")
    with pytest.raises(HTTPException):
        call(handler, arguments)
    assert (destination / name).read_text() == "changed externally"


def test_static_server_blocks_listing_and_symlink_escape(tmp_path):
    root = tmp_path / "public"
    root.mkdir()
    (root / "homage.html").write_text("public page")
    private = tmp_path / "private.txt"
    private.write_text("private")
    (root / "escape.txt").symlink_to(private)
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(PublicationHandler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(base + "/homage.html") as response:
            assert response.read() == b"public page"
        for path in ("/", "/escape.txt"):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + path)
            assert error.value.code in (403, 404)
        with pytest.raises(OSError):
            serve_publication(root, "127.0.0.1", server.server_port)
        with urllib.request.urlopen(base + "/homage.html") as response:
            assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_public_mcp_catalog_and_handler_are_registered():
    from services.music_production import command_catalog, command_handlers
    assert any(item["name"] == "production.publish" for item in command_catalog())
    assert "production.publish" in command_handlers(lambda ws: ".", lambda: ".", lambda: "", lambda: "")
