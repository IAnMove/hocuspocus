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


def test_save_keeps_bundled_scene3d_plates(env):
    """Drive shots put /scene3d/*.jpg on the background; that is app media, not an external URL."""
    library, _, _ = env
    document = _world()
    document["slots"][1]["sourceUrl"] = "/scene3d/drive-coast.jpg"
    saved = library.save(workspace=WS, editor="video3d", document=document, metadata={"title": "Coast road"})
    stored = library.get(saved["id"])["document"]
    assert stored["slots"][1]["sourceUrl"] == "/scene3d/drive-coast.jpg"
    assert stored["slots"][0]["sourceUrl"] == ""
    applied = library.apply(saved["id"], workspace=WS)
    assert applied["document"]["slots"][1]["sourceUrl"] == "/scene3d/drive-coast.jpg"
    with pytest.raises(TemplateError) as traversal:
        library.save(workspace=WS, editor="video3d",
                     document=_world(slots=[{**_world()["slots"][0], "sourceUrl": "/scene3d/../secret.glb"}]),
                     metadata={"title": "Nope"})
    assert traversal.value.code == "external_media"


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


def test_save_without_media_clears_slot_owned_and_scene_audio(env):
    """Default save (no sample files) must empty every slot-owned locator and drop
    scene audio that cannot be a slot. Otherwise a spoken Video 3D shot, a TV
    screen, world SFX, a 2D frame sequence or attached music makes Save fail."""
    library, _, workspace = env
    (workspace / "voice.wav").write_bytes(b"RIFF-voice")
    (workspace / "tv.mp4").write_bytes(b"mp4-tv")
    (workspace / "portal.png").write_bytes(b"\x89PNG-portal")
    (workspace / "f1.png").write_bytes(b"\x89PNG-f1")
    (workspace / "f2.png").write_bytes(b"\x89PNG-f2")
    (workspace / "line.wav").write_bytes(b"RIFF-line")
    spoken = _world()
    spoken["slots"][0]["speech"] = {
        "version": 1, "enabled": True, "start": 0, "offset": 0, "gain": 1, "strength": 0.8,
        "audio": {"url": f"/api/v1/file/voice.wav?workspace={WS}", "filename": "voice.wav"},
        "clips": [{"id": "line-1", "audio": {"url": f"/api/v1/file/line.wav?workspace={WS}", "filename": "line.wav"}}],
    }
    spoken["slots"][1]["screen"] = {
        "sourceUrl": f"/api/v1/file/tv.mp4?workspace={WS}",
        "poseSequence": [{"sourceUrl": f"/api/v1/file/sky.png?workspace={WS}", "duration": 1}],
    }
    spoken["worldSfx"] = [{"id": "portal", "kind": "media_portal", "sourceUrl": f"/api/v1/file/portal.png?workspace={WS}"}]
    saved = library.save(workspace=WS, editor="video3d", document=spoken, metadata={"title": "Spoken"})
    stored = library.get(saved["id"])["document"]
    assert stored["slots"][0]["sourceUrl"] == "" and "audio" not in stored["slots"][0]["speech"]
    assert "audio" not in stored["slots"][0]["speech"]["clips"][0]
    assert stored["slots"][1]["screen"]["sourceUrl"] == "" and "poseSequence" not in stored["slots"][1]["screen"]
    assert "sourceUrl" not in stored["worldSfx"][0] and "soundtrack" not in stored

    scene = _scene2d()
    scene["layers"][0]["sequence"] = {"kind": "frames", "sources": [
        f"/api/v1/file/f1.png?workspace={WS}", f"/api/v1/file/f2.png?workspace={WS}"], "fps": 12, "loop": "loop"}
    scene["audioTracks"] = [{"id": "m", "filename": f"/api/v1/file/song.wav?workspace={WS}"}]
    saved2d = library.save(workspace=WS, editor="video2d", document=scene, metadata={"title": "Card seq"})
    stored2d = library.get(saved2d["id"])["document"]
    assert stored2d["layers"][0]["source"] == "" and stored2d["layers"][0]["sequence"]["sources"] == ["", ""]
    assert "audioTracks" not in stored2d


def test_include_media_packs_speech_and_apply_rewrites_it(env):
    library, _, workspace = env
    (workspace / "voice.wav").write_bytes(b"RIFF-voice")
    spoken = _world()
    spoken["slots"][0]["speech"] = {
        "audio": {"url": f"/api/v1/file/voice.wav?workspace={WS}", "filename": "voice.wav"},
        "facePack": {"url": f"/api/v1/file/sky.png?workspace={WS}", "filename": "sky.png"},
    }
    saved = library.save(workspace=WS, editor="video3d", document=spoken, include_media=True,
                         metadata={"title": "With voice"})
    stored = library.get(saved["id"])["document"]
    assert stored["slots"][0]["speech"]["audio"]["url"].startswith("media/")
    assert stored["slots"][0]["speech"]["facePack"]["url"].startswith("media/")
    applied = library.apply(saved["id"], workspace=WS)
    url = applied["document"]["slots"][0]["speech"]["audio"]["url"]
    assert url.startswith("/api/v1/file/tpl-") and url.endswith("?workspace=space")
    assert applied["document"]["slots"][0]["speech"]["facePack"]["url"].startswith("/api/v1/file/tpl-")
    assert any(name.endswith(".wav") for name in applied["copiedMedia"])


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


def test_inline_preview_data_url(env):
    import base64
    library, _, _ = env
    png = b"\x89PNG\r\n\x1a\nframe"
    saved = library.save(workspace=WS, editor="video3d", document=_world(), metadata={"title": "Inline"},
                         preview="data:image/png;base64," + base64.b64encode(png).decode())
    assert library.preview_path(saved["id"]).read_bytes() == png
    with pytest.raises(TemplateError):
        library.save(workspace=WS, editor="video3d", document=_world(), metadata={"title": "Bad"}, preview="data:image/png;base64,@@@")


def test_community_index_lists_installs_and_verifies(env):
    import hashlib
    from services.template_community import CommunityIndex
    library, make, workspace = env
    saved = library.save(workspace=WS, editor="video3d", document=_world(), include_media=True, metadata={"title": "Shared", "author": {"x": "ana"}})
    name, package = library.export(saved["id"])
    index = {"kind": "hocuspocus.community-index", "version": 1, "updatedAt": "2026-09-28", "templates": [
        {"id": saved["id"], "editor": "video3d", "title": "Shared", "author": {"x": "ana"}, "license": "CC0-1.0",
         "sha256": hashlib.sha256(package).hexdigest(), "bytes": len(package),
         "package": f"https://community.example/templates/{name}", "preview": "https://community.example/p.jpg"},
        {"id": "evil/elsewhere", "sha256": "0" * 64, "package": "https://evil.example/x.hptemplate"},
        {"id": "bad", "sha256": "nope", "package": "http://community.example/x"}]}
    served = {"https://community.example/index.json": json.dumps(index).encode(), f"https://community.example/templates/{name}": package}
    fetch = lambda url, limit: served[url]  # noqa: E731
    other = make("other")
    community = CommunityIndex(other, index_url="https://community.example/index.json", fetch=fetch)
    listing = community.listing()
    assert [item["id"] for item in listing["templates"]] == [saved["id"]] and listing["templates"][0]["state"] == "available"
    installed = community.install(saved["id"])
    assert installed["source"] == "community"
    assert community.listing(refresh=True)["templates"][0]["state"] == "installed"
    served[f"https://community.example/templates/{name}"] = package + b"tampered"
    with pytest.raises(TemplateError) as mismatch:
        community.install(saved["id"])
    assert mismatch.value.code == "checksum_mismatch"
    down = CommunityIndex(other, index_url="https://down.example/index.json", fetch=lambda url, limit: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(TemplateError) as unavailable:
        down.listing()
    assert unavailable.value.code == "index_unavailable"


def test_community_index_builder_validates_paths_and_publishes_hashes(env, tmp_path):
    import hashlib
    import importlib.util
    library, _, _ = env
    saved = library.save(workspace=WS, editor="video3d", document=_world(), preview="shot.png", metadata={"title": "Launch", "author": {"x": "ana"}})
    _, package = library.export(saved["id"])
    templates = tmp_path / "templates"
    (templates / "ana").mkdir(parents=True)
    (templates / "ana" / "launch.hptemplate").write_bytes(package)
    (templates / "bob").mkdir()
    (templates / "bob" / "stolen.hptemplate").write_bytes(package)
    spec = importlib.util.spec_from_file_location("community_index", Path(__file__).resolve().parents[1] / "scripts" / "community_index.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    index, errors = module.build(templates, tmp_path / "site", "https://example.org/community/")
    assert [entry["id"] for entry in index["templates"]] == ["ana/launch"]
    entry = index["templates"][0]
    assert entry["sha256"] == hashlib.sha256(package).hexdigest() and entry["package"] == "https://example.org/community/templates/ana/launch.hptemplate"
    assert entry["preview"].endswith("previews/ana--launch.png") and (tmp_path / "site" / "previews" / "ana--launch.png").is_file()
    assert len(errors) == 1 and "bob/stolen" in errors[0]
