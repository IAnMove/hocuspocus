"""The optional asset library: every file is licensed, nothing downloads without asking, files are served by hash."""
import copy
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.asset_library import create_asset_library_router
from services import asset_library as module
from services.asset_manifest import AssetManifestError, build_asset_manifest, validate_asset_manifest

ROOT = Path(__file__).resolve().parents[1]
HDR = b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 1\n\x80\x80\x80\x81"
CUBE = b'TITLE "identity"\nLUT_3D_SIZE 2\n0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n'
ACTION = {"X-Hocus-Action": "install-library"}


def _entry(data, kind, **extra):
    return {"kind": kind, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "collection": "studio",
            "license": "CC0-1.0", "source": "polyhaven", "source_url": "https://polyhaven.com/a/studio_small_08",
            "author": "Sergej Majboroda", "retrieved_at": "2026-10-03", **extra}


def library_manifest(data=None):
    data = data or {"studio/studio.hdr": HDR, "studio/identity.cube": CUBE}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        for name, value in data.items():
            bundle.writestr(name, value)
    payload = archive.getvalue()
    kinds = {".hdr": "hdri", ".cube": "lut"}
    files = {name: _entry(value, kinds[Path(name).suffix]) for name, value in data.items()}
    manifest = {"schema": "hocuspocus.asset-library", "revision": 1, "files": files, "collections": {
        "studio": {"title": "Studio", "files": list(files), "dependencies": [], "size": sum(len(v) for v in data.values()),
                   "archive": {"url": "https://github.com/IAnMove/hocuspocus/releases/download/library-v1/studio.zip",
                               "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}}}}
    return manifest, payload


def test_the_shipped_catalog_follows_the_contract():
    shipped = json.loads((ROOT / "app" / "resources" / "asset_library.json").read_text())
    assert module.validate_library_manifest(shipped) is shipped
    schema = json.loads((ROOT / "docs" / "development" / "asset-library-v1.schema.json").read_text())
    assert schema["$defs"]["file"]["properties"]["kind"]["enum"] == sorted(module.LIBRARY_KINDS, key=schema["$defs"]["file"]["properties"]["kind"]["enum"].index)
    assert set(schema["$defs"]["file"]["required"]) >= {"license", "source_url", "author", "retrieved_at"}


def _broken(change):
    manifest, _payload = library_manifest()
    change(manifest)
    with pytest.raises(module.LibraryManifestError) as caught:
        module.validate_library_manifest(manifest)
    return str(caught.value)


@pytest.mark.parametrize("key", ["license", "source_url", "author", "source", "retrieved_at"])
def test_a_file_without_its_license_or_source_is_rejected(key):
    assert "studio/studio.hdr" in _broken(lambda m: m["files"]["studio/studio.hdr"].pop(key))


@pytest.mark.parametrize("change,needle", [
    (lambda m: m["files"]["studio/studio.hdr"].update(license="CC-BY-4.0"), "license"),
    (lambda m: m["files"]["studio/studio.hdr"].update(source_url="http://polyhaven.com/x"), "source_url"),
    (lambda m: m["files"]["studio/studio.hdr"].update(retrieved_at="yesterday"), "retrieved_at"),
    (lambda m: m["files"]["studio/studio.hdr"].update(kind="lut"), "kind"),
    (lambda m: m["files"]["studio/studio.hdr"].update(kind="video"), "kind"),
    (lambda m: m["files"]["studio/studio.hdr"].update(sha256="xyz"), "sha256"),
    (lambda m: m["files"].update({"../escape.hdr": m["files"].pop("studio/studio.hdr")}), "relative"),
    (lambda m: m["collections"]["studio"].update(size=1), "size"),
    (lambda m: m["collections"]["studio"]["archive"].update(url="https://evil.example/studio.zip"), "archive"),
    (lambda m: m["collections"]["studio"]["archive"].update(url="http://github.com/studio.zip"), "archive"),
    (lambda m: m["collections"]["studio"].update(dependencies=["missing"]), "dependencies"),
    (lambda m: m["collections"]["studio"].update(files=["studio/studio.hdr"], size=len(HDR)), "exactly one collection"),
    (lambda m: m.update(schema="other"), "schema"),
    (lambda m: m.update(revision=0), "revision"),
])
def test_the_contract_is_enforced(change, needle):
    assert needle in _broken(change)


def test_license_provenance_reaches_the_asset_manifest(tmp_path):
    manifest, _payload = library_manifest()
    library = module.AssetLibrary(tmp_path, manifest)
    built = build_asset_manifest(tmp_path / "studio.hdr", tool="asset-library", execution_mode="import",
                                 license=library.license_for("studio/studio.hdr"))
    assert built["asset"]["kind"] == "hdri"
    assert built["origin"]["license"] == {"spdx": "CC0-1.0", "source": "polyhaven",
                                          "source_url": "https://polyhaven.com/a/studio_small_08",
                                          "author": "Sergej Majboroda", "retrieved_at": "2026-10-03"}
    assert validate_asset_manifest(built)["origin"]["license"]["spdx"] == "CC0-1.0"
    assert "license" not in build_asset_manifest(tmp_path / "plain.png", tool="upload")["origin"]
    for bad in ({"spdx": "CC0-1.0"}, {"source_url": "https://x.example/"}, "CC0"):
        with pytest.raises(AssetManifestError):
            build_asset_manifest(tmp_path / "a.hdr", tool="asset-library", license=bad)
    tampered = copy.deepcopy(built)
    tampered["origin"]["license"] = {"spdx": "", "source_url": "https://x.example/"}
    with pytest.raises(AssetManifestError):
        validate_asset_manifest(tampered)


def _client(tmp_path, opener):
    manifest, payload = library_manifest()
    library = module.AssetLibrary(tmp_path / "cache", manifest)
    app = FastAPI()
    app.include_router(create_asset_library_router(library, opener=opener))
    return library, payload, TestClient(app)


def _settle(http):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = http.get("/api/v1/library").json()
        if state["job"] and state["job"]["status"] != "running":
            return state
        time.sleep(0.01)
    pytest.fail("library download did not settle")


def test_listing_never_downloads_and_installing_needs_the_explicit_action(tmp_path):
    library, _payload, http = _client(tmp_path, lambda *a, **k: pytest.fail("unexpected network"))
    state = http.get("/api/v1/library").json()
    assert state["items"] == [] and state["job"] is None
    row = state["collections"][0]
    assert row["id"] == "studio" and row["kinds"] == ["hdri", "lut"] and row["licenses"] == ["CC0-1.0"]
    assert row["installed"] is False and "gallery" not in row
    assert http.post("/api/v1/library/install", json={"collections": ["studio"]}).status_code == 403
    assert http.post("/api/v1/library/install", json={"collections": ["nope"]}, headers=ACTION).status_code == 422
    key = library.key("studio/studio.hdr")
    assert http.get(f"/api/v1/library/files/{key}").status_code == 409
    assert http.head(f"/api/v1/library/files/{key}").headers["content-length"] == str(len(HDR))
    assert http.get("/api/v1/library/files/" + "0" * 64 + ".hdr").status_code == 404
    assert http.get("/api/v1/library/files/..%2Fsecret.hdr").status_code == 404


def test_install_serves_files_by_hash_with_their_licenses(tmp_path):
    opened = []
    library, payload, http = _client(tmp_path, lambda url, timeout=30: opened.append(url) or io.BytesIO(payload))
    job = http.post("/api/v1/library/install", json={"collections": ["studio"]}, headers=ACTION)
    assert job.status_code == 202
    state = _settle(http)
    assert state["job"]["status"] == "complete" and opened == [library.collections["studio"]["archive"]["url"]]
    assert {item["name"] for item in state["items"]} == {"studio/studio.hdr", "studio/identity.cube"}
    item = next(item for item in state["items"] if item["kind"] == "hdri")
    assert item["license"] == "CC0-1.0" and item["source_url"].startswith("https://")
    served = http.get(item["url"])
    assert served.status_code == 200 and served.content == HDR
    assert served.headers["content-type"] == "image/vnd.radiance" and "immutable" in served.headers["cache-control"]
    assert http.get(f"/api/v1/library/files/{library.key('studio/identity.cube')}").text.startswith("TITLE")
    assert sorted(path.name for path in (tmp_path / "cache").iterdir()) == sorted(
        [library.key(name) for name in library.files] + ["studio.installed.json"])


def test_a_corrupted_cached_file_is_not_served(tmp_path):
    library, payload, http = _client(tmp_path, lambda *a, **k: io.BytesIO(payload))
    http.post("/api/v1/library/install", json={"collections": ["studio"]}, headers=ACTION)
    _settle(http)
    target = tmp_path / "cache" / library.key("studio/studio.hdr")
    target.write_bytes(b"x" * len(HDR))
    assert http.get(f"/api/v1/library/files/{library.key('studio/studio.hdr')}").status_code == 409
    assert http.get("/api/v1/library").json()["collections"][0]["installed"] is False


def test_a_bad_archive_is_never_published_and_cancel_works(tmp_path):
    from threading import Event

    entered, release = Event(), Event()
    answers = {"payload": b"not the archive"}

    def opener(url, timeout=30):
        entered.set()
        assert release.wait(5)
        return io.BytesIO(answers["payload"])

    library, payload, http = _client(tmp_path, opener)
    release.set()
    http.post("/api/v1/library/install", json={"collections": ["studio"]}, headers=ACTION)
    assert _settle(http)["job"]["status"] == "failed"
    assert not any((tmp_path / "cache").glob("*.hdr"))
    release.clear()
    entered.clear()
    answers["payload"] = payload
    job = http.post("/api/v1/library/install", json={"collections": ["studio"]}, headers=ACTION).json()
    assert entered.wait(5)
    assert http.post("/api/v1/library/install", json={"collections": ["studio"]}, headers=ACTION).status_code == 409
    assert http.delete(f"/api/v1/library/install/{job['id']}").status_code == 403
    assert http.delete("/api/v1/library/install/unknown", headers=ACTION).status_code == 404
    assert http.delete(f"/api/v1/library/install/{job['id']}", headers=ACTION).status_code == 200
    release.set()
    assert _settle(http)["job"]["status"] == "cancelled"
    assert not library.installed("studio")
