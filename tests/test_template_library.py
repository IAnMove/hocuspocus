"""Template library: save from a workspace, apply into one, portable .hptemplate round trip."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from services.scene_packages import make_workspace_reader
from services.template_commands import TemplateCommands, command_catalog
from services.template_format import TemplateError
from services.template_library import TemplateLibrary

WS = "space"


def _world(**extra):
    document = {
        "version": 1, "units": "meters", "up": "y", "width": 1280, "height": 720, "fps": 24, "duration": 8,
        "camera": {"family": "fixed", "eye": [0, 1, 4], "look": [0, 1, 0], "fov": 40},
        "slots": [
            {"id": "a", "slot": "subject_1", "media": "model3d", "sourceUrl": f"/api/v1/file/hero.glb?workspace={WS}",
             "sourceRef": {"workspaceId": WS, "filename": "hero.glb", "url": f"/api/v1/file/hero.glb?workspace={WS}"},
             "clip": {"name": "Run"}, "position": [0, 0, 0], "rotationY": 0, "scale": 1},
            {"id": "b", "slot": "background", "media": "image", "sourceUrl": f"/api/v1/file/sky.png?workspace={WS}",
             "position": [0, 0, -5], "rotationY": 0, "scale": 1, "clip": None},
        ],
        "soundtrack": [{"id": "m", "audio": {"url": f"/api/v1/file/song.wav?workspace={WS}", "filename": "song.wav"}}],
    }
    document.update(extra)
    return document


def _scene2d():
    return {"version": 1, "name": "Card", "width": 1920, "height": 1080, "fps": 24, "duration": 5,
            "texts": [{"id": "t", "text": "HELLO", "start": 0, "end": 3, "preset": "impact"}],
            "layers": [
                {"id": "bg", "type": "image", "source": f"/api/v1/file/sky.png?workspace={WS}"},
                {"id": "logo", "type": "image", "source": f"/api/v1/file/logo.png?workspace={WS}"},
                {"id": "stars", "type": "image", "source": "/examples/stars.png"},
            ]}


@pytest.fixture()
def env(tmp_path):
    root = tmp_path / "workspaces"
    workspace_dir = lambda name: str(root / name)  # noqa: E731
    (root / WS).mkdir(parents=True)
    for name, data in {"hero.glb": b"glTF-hero", "sky.png": b"\x89PNG-sky", "song.wav": b"RIFF-song",
                       "logo.png": b"\x89PNG-logo", "shot.png": b"\x89PNG-preview"}.items():
        (root / WS / name).write_bytes(data)
    reader = make_workspace_reader(workspace_dir)
    make = lambda folder: TemplateLibrary(tmp_path / folder, workspace_dir=workspace_dir, reader=reader)  # noqa: E731
    return make("library"), make, root / WS


def test_save_without_media_empties_slots_and_keeps_metadata(env):
    library, _, _ = env
    saved = library.save(workspace=WS, editor="video3d", document=_world(), preview="shot.png",
                         metadata={"title": "Rocket launch", "author": {"name": "Ina", "x": "@theinaog"}, "license": "CC-BY-4.0",
                                   "tags": ["Space", "launch"],
                                   "controls": [{"id": "length", "type": "number", "pointer": "/duration", "min": 2, "max": 30}]})
    assert saved["id"] == "theinaog/rocket-launch" and saved["source"] == "user" and saved["previewUrl"]
    assert [slot["target"] for slot in saved["slots"]] == ["subject_1", "background"]
    assert saved["controls"][0]["default"] == 8 and saved["tags"] == ["launch", "space"]
    document = library.get(saved["id"])["document"]
    assert all(slot["sourceUrl"] == "" for slot in document["slots"]) and "soundtrack" not in document
    assert document["slots"][0]["clip"] is None


def test_save_with_media_packs_by_hash_and_apply_materializes_it(env):
    library, _, workspace = env
    saved = library.save(workspace=WS, editor="video3d", document=_world(), include_media=True,
                         metadata={"title": "Launch pad", "slots": [{"id": "hero", "target": "subject_1", "accepts": ["model3d"]}],
                                   "controls": [{"id": "length", "type": "number", "pointer": "/duration", "min": 2, "max": 30}]})
    manifest = library.get(saved["id"])["manifest"]
    assert len(manifest["media"]) == 3
    stored = library.get(saved["id"])["document"]
    assert stored["slots"][0]["sourceUrl"].startswith("media/") and stored["slots"][0]["sourceRef"]["filename"].endswith(".glb")
    (workspace / "robot.glb").write_bytes(b"glTF-robot")
    applied = library.apply(saved["id"], workspace=WS, slots={"hero": f"/api/v1/file/robot.glb?workspace={WS}"},
                            controls={"length": 12})
    document = applied["document"]
    assert document["duration"] == 12 and document["slots"][0]["sourceUrl"].endswith("robot.glb?workspace=space")
    assert document["slots"][1]["sourceUrl"].startswith("/api/v1/file/tpl-") and applied["missingSlots"] == []
    assert sorted(Path(name).suffix for name in applied["copiedMedia"]) == [".png", ".wav"]
    with pytest.raises(TemplateError) as bad:
        library.apply(saved["id"], workspace=WS, controls={"length": 99})
    assert "between" in str(bad.value)
    with pytest.raises(TemplateError) as kind:
        library.apply(saved["id"], workspace=WS, slots={"hero": f"/api/v1/file/sky.png?workspace={WS}"})
    assert kind.value.code == "slot_type"


def test_contract_errors_are_explicit(env):
    library, _, _ = env
    with pytest.raises(TemplateError) as pointer:
        library.save(workspace=WS, editor="video3d", document=_world(), metadata={
            "title": "x", "controls": [{"id": "c", "type": "number", "pointer": "/nope"}]})
    assert "not in the document" in str(pointer.value)
    with pytest.raises(TemplateError) as external:
        library.save(workspace=WS, editor="video3d", document=_world(soundtrack=[{"audio": {"url": "https://evil.example/a.wav"}}]),
                     metadata={"title": "x"})
    assert external.value.code == "external_media"
    with pytest.raises(TemplateError) as target:
        library.save(workspace=WS, editor="video3d", document=_world(), metadata={"title": "x", "slots": [{"id": "s", "target": "prop"}]})
    assert target.value.code == "unknown_slot_target"
    library.save(workspace=WS, editor="video3d", document=_world(), metadata={"title": "Same"})
    with pytest.raises(TemplateError) as exists:
        library.save(workspace=WS, editor="video3d", document=_world(), metadata={"title": "Same"})
    assert exists.value.code == "exists"


def test_video2d_slots_unbound_media_and_examples(env):
    library, _, workspace = env
    with pytest.raises(TemplateError) as unbound:
        library.save(workspace=WS, editor="video2d", document=_scene2d(), metadata={"title": "Card", "slots": [{"id": "bg"}]})
    assert unbound.value.code == "unbound_media" and "logo.png" in str(unbound.value)
    saved = library.save(workspace=WS, editor="video2d", document=_scene2d(), metadata={
        "title": "Card", "controls": [{"id": "headline", "type": "text", "pointer": "/texts/0/text"}]})
    assert [slot["id"] for slot in saved["slots"]] == ["bg", "logo"]
    stored = library.get(saved["id"])["document"]
    assert stored["layers"][2]["source"] == "/examples/stars.png" and stored["layers"][0]["missingAsset"] is True
    applied = library.apply(saved["id"], workspace=WS, slots={"bg": f"/api/v1/file/sky.png?workspace={WS}"},
                            controls={"headline": "BONJOUR"})
    assert applied["document"]["texts"][0]["text"] == "BONJOUR" and applied["missingSlots"] == ["logo"]
    assert applied["document"]["layers"][0]["source"].endswith("sky.png?workspace=space")


def test_package_round_trip_preflight_and_replace(env):
    library, make, workspace = env
    saved = library.save(workspace=WS, editor="video3d", document=_world(), include_media=True, preview="shot.png",
                         metadata={"title": "Portable", "author": {"x": "theinaog"}, "license": "CC0-1.0"})
    exported = library.export_to_workspace(saved["id"], WS)
    data = (workspace / exported["file"]).read_bytes()
    other = make("other")
    report = other.preflight(data)
    assert report["canImport"] and not report["exists"] and report["template"]["license"] == "CC0-1.0" and len(report["media"]) == 3
    imported = other.import_package(data)
    assert imported["source"] == "imported" and imported["id"] == saved["id"] and imported["previewUrl"]
    assert other.preflight(data)["exists"] is True
    with pytest.raises(TemplateError) as exists:
        other.import_package(data)
    assert exists.value.code == "exists"
    assert other.import_package(data, replace=True)["id"] == saved["id"]


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_unsafe_or_incomplete_packages_are_rejected(env):
    library, _, workspace = env
    saved = library.save(workspace=WS, editor="video3d", document=_world(), include_media=True, metadata={"title": "Safe"})
    good = zipfile.ZipFile(io.BytesIO(library.export(saved["id"])[1]))
    members = {name: good.read(name) for name in good.namelist()}
    traversal = library.preflight(_zip({**members, "../evil.txt": b"x"}))
    assert not traversal["canImport"] and traversal["error"]["code"] == "unsafe_package"
    media_name = next(name for name in members if name.startswith("media/"))
    tampered = library.preflight(_zip({**members, media_name: b"not the same bytes"}))
    assert not tampered["canImport"] and tampered["error"]["code"] == "missing_media"
    assert not library.preflight(b"PK\x03\x04garbage")["canImport"]


def test_legacy_world3d_template_is_converted(env):
    library, _, _ = env
    legacy = {"kind": "hocuspocus.world3d.template", "version": 1, "id": "user-1", "title": "Old scenario",
              "includeAssets": True, "document": _world()}
    report = library.preflight(json.dumps(legacy).encode())
    assert report["canImport"] and report["template"]["id"] == "local/old-scenario" and report["issues"][0]["code"] == "legacy"
    imported = library.import_package(json.dumps(legacy).encode())
    document = library.get(imported["id"])["document"]
    assert all(slot["sourceUrl"] == "" for slot in document["slots"])


def test_commands_catalog_and_listing(env):
    library, _, _ = env
    library.save(workspace=WS, editor="video3d", document=_world(), metadata={"title": "Listed", "tags": ["space"]})
    commands = TemplateCommands(library)
    names = [item["name"] for item in command_catalog()]
    assert names[:2] == ["templates.list", "templates.get"] and "templates.apply" in names and "templates.import" in names
    listed = commands.execute("templates.list", {"version": 1, "input": {"editor": "video3d", "tag": "space"}})["result"]
    assert [item["title"] for item in listed["templates"]] == ["Listed"]
    assert commands.execute("templates.list", {"version": 1, "input": {"query": "nothing"}})["result"]["templates"] == []
    with pytest.raises(TemplateError):
        commands.execute("templates.get", {"version": 1, "input": {"id": "x"}, "extra": 1} | {"input": {"nope": 1}})


def test_http_routes_save_apply_download_and_import(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.templates import create_templates_router
    library, make, _ = env
    api = FastAPI()
    api.include_router(create_templates_router(TemplateCommands(library)))
    client = TestClient(api)
    saved = client.post("/api/v1/templates", json={"workspace": WS, "editor": "video3d", "document": _world(), "title": "Web",
                                                     "include_media": True, "preview": "shot.png", "ignored": 1}).json()
    assert saved["id"] == "local/web"
    assert client.get("/api/v1/templates?editor=video3d").json()["templates"][0]["id"] == "local/web"
    assert client.get("/api/v1/templates/local/web/preview").content == b"\x89PNG-preview"
    applied = client.post("/api/v1/templates/local/web/apply", json={"workspace": WS}).json()
    assert applied["document"]["slots"][0]["sourceUrl"].startswith("/api/v1/file/tpl-")
    package = client.get("/api/v1/templates/local/web/package")
    assert package.headers["content-type"] == "application/zip" and "local--web.hptemplate" in package.headers["content-disposition"]
    other = make("other")
    other_api = FastAPI()
    other_api.include_router(create_templates_router(TemplateCommands(other)))
    other_client = TestClient(other_api)
    assert other_client.post("/api/v1/templates/preflight", content=package.content).json()["canImport"]
    assert other_client.post("/api/v1/templates/import", content=package.content).json()["id"] == "local/web"
    assert other_client.post("/api/v1/templates/import", content=package.content).status_code == 409
    assert other_client.delete("/api/v1/templates/local/web").json() == {"deleted": "local/web"}
    assert other_client.get("/api/v1/templates/local/web").status_code == 404


def test_save_update_keeps_packed_media_and_preview(env):
    library, _, workspace = env
    saved = library.save(workspace=WS, editor="video3d", document=_world(), include_media=True, preview="shot.png",
                         metadata={"title": "Keep media", "id": "local/keep-media"})
    packed = library.get(saved["id"])
    media_before = {item["path"]: item["sha256"] for item in packed["manifest"]["media"]}
    preview_before = library.preview_path(saved["id"]).read_bytes()
    updated = library.save(workspace=WS, editor="video3d", document=packed["document"], include_media=True,
                           metadata={"title": "Keep media", "id": saved["id"], "description": "edited"},
                           expected_updated_at=saved["updatedAt"])
    after = library.get(updated["id"])
    assert {item["path"]: item["sha256"] for item in after["manifest"]["media"]} == media_before
    assert after["document"]["slots"][0]["sourceUrl"].startswith("media/")
    assert library.preview_path(updated["id"]).read_bytes() == preview_before
    applied = library.apply(updated["id"], workspace=WS)
    assert applied["copiedMedia"] and applied["document"]["slots"][0]["sourceUrl"].startswith("/api/v1/file/tpl-")
    with pytest.raises(TemplateError) as missing:
        library.save(workspace=WS, editor="video3d", document=packed["document"], include_media=True,
                     metadata={"title": "Clone", "id": "local/clone-media"})
    assert missing.value.code == "missing_media"


def test_apply_reports_missing_packaged_media(env):
    library, _, _ = env
    saved = library.save(workspace=WS, editor="video3d", document=_world(), include_media=True,
                         metadata={"title": "Broken apply"})
    media = next(path for path in library.file(saved["id"], "template.json").parent.glob("media/*"))
    media.unlink()
    with pytest.raises(TemplateError) as missing:
        library.apply(saved["id"], workspace=WS)
    assert missing.value.code == "missing_media"


def test_inline_preview_data_url(env):
    import base64
    library, _, _ = env
    png = b"\x89PNG\r\n\x1a\nframe"
    saved = library.save(workspace=WS, editor="video3d", document=_world(), metadata={"title": "Inline"},
                         preview="data:image/png;base64," + base64.b64encode(png).decode())
    assert library.preview_path(saved["id"]).read_bytes() == png
    with pytest.raises(TemplateError):
        library.save(workspace=WS, editor="video3d", document=_world(), metadata={"title": "Bad"}, preview="data:image/png;base64,@@@")
