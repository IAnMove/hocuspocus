import json
import shutil
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import services.style_library as style_library_module
from routers.style_library import create_style_library_router
from services.style_library import (
    MINIMAX_H3_1K_SOURCE,
    StyleImportPreflightError,
    StyleLibrary,
    StyleManifestDegradedError,
    migrate_legacy_style_library,
    resolve_style_library_root,
)


def _seed_library(tmp_path):
    library = StyleLibrary(tmp_path / "styles")
    library.raw_dir.mkdir(parents=True)
    library.preview_dir.mkdir(parents=True)
    source = {
        **MINIMAX_H3_1K_SOURCE,
        "revision": "revision-123",
        "lastModified": "2026-08-10T02:58:09Z",
    }
    records = []
    for number, prompt, group in (
        (1, "Cinematic rain over a neon city", "Cinematic"),
        (2, "Flat-color animated comedy", "Animation"),
        (3, "Documentary wildlife close-up", "Documentary"),
    ):
        sample = f"{number:06d}"
        style_id = f"minimax-h3-1k-{sample}"
        (library.raw_dir / f"{sample}.txt").write_text(prompt, encoding="utf-8")
        (library.raw_dir / f"{sample}.mp4").write_bytes(b"video")
        (library.preview_dir / f"{style_id}.jpg").write_bytes(b"preview")
        records.append({
            "id": style_id,
            "modelFamily": "minimax",
            "title": f"Sample {sample}",
            "prompt": prompt,
            "collection": "MiniMax H3 1K",
            "group": group,
            "tags": [group.casefold()],
            "sourceOrder": number,
            "sourceFilename": f"{sample}.txt",
            "videoFilename": f"{sample}.mp4",
            "source": source,
            "importedAt": 100 + number,
        })
    library.manifest_path.write_text(json.dumps({
        "version": 1,
        "source": source,
        "styles": records,
        "deletedIds": [],
        "updatedAt": 200,
    }), encoding="utf-8")
    return library


def test_styles_keep_source_attribution_and_support_filters_and_sorting(tmp_path):
    library = _seed_library(tmp_path)

    result = library.list_styles(
        model_family="minimax",
        collection="MiniMax H3 1K",
        group="Animation",
        query="comedy",
        sort="prompt_asc",
    )

    assert result["total"] == 1
    [style] = result["styles"]
    assert style["source"]["id"] == "huggingface:ostris/minimax_h3_1k"
    assert style["source"]["revision"] == "revision-123"
    assert style["source"]["license"] is None
    assert style["previewUrl"].endswith(f"/{style['id']}/preview")
    assert result["facets"]["groups"] == ["Animation"]


def test_style_deletion_is_tombstoned_and_removes_local_assets(tmp_path):
    library = _seed_library(tmp_path)
    style_id = "minimax-h3-1k-000002"

    result = library.delete_style(style_id)

    assert result["deleted"] is True
    assert library.list_styles()["total"] == 2
    manifest = json.loads(library.manifest_path.read_text(encoding="utf-8"))
    assert style_id in manifest["deletedIds"]
    assert not (library.raw_dir / "000002.mp4").exists()
    assert not (library.raw_dir / "000002.txt").exists()
    assert not (library.preview_dir / f"{style_id}.jpg").exists()


def test_delete_endpoint_requires_explicit_confirmation(tmp_path):
    library = _seed_library(tmp_path)
    router = create_style_library_router(library)
    endpoints = {route.path: route.endpoint for route in router.routes}
    delete_endpoint = endpoints["/api/v1/style-library/styles/{style_id}"]

    with pytest.raises(HTTPException, match="confirm=true") as captured:
        delete_endpoint("minimax-h3-1k-000001", False)

    assert captured.value.status_code == 400
    assert delete_endpoint("minimax-h3-1k-000001", True)["deleted"] is True


def test_corrupt_manifest_is_quarantined_read_only_and_recovers_tombstones(tmp_path):
    library = _seed_library(tmp_path)
    deleted_id = "minimax-h3-1k-000002"
    library.delete_style(deleted_id)
    assert library.manifest_backup_dir.is_dir()
    corrupt = "{this is not valid json"
    library.manifest_path.write_text(corrupt, encoding="utf-8")

    [status] = library.source_status()
    assert status["status"] == "degraded"
    assert status["degraded"] is True
    assert status["recoveryAvailable"] is True
    assert status["styleCount"] == 2
    assert library.list_styles()["total"] == 2
    assert deleted_id not in {item["id"] for item in library.list_styles()["styles"]}
    assert library.manifest_path.read_text(encoding="utf-8") == corrupt
    assert list(library.manifest_quarantine_dir.glob("*.corrupt.json"))

    with pytest.raises(StyleManifestDegradedError, match="recover"):
        library.start_minimax_import()
    with pytest.raises(StyleManifestDegradedError, match="recover"):
        library.delete_style("minimax-h3-1k-000001")
    assert library.manifest_path.read_text(encoding="utf-8") == corrupt

    recovered = library.recover_manifest()
    assert recovered["recovered"] is True
    restored = json.loads(library.manifest_path.read_text(encoding="utf-8"))
    assert deleted_id in restored["deletedIds"]
    assert library.source_status()[0]["status"] == "healthy"
    assert library.list_styles()["total"] == 2


def test_style_storage_resolves_outside_app_and_migrates_atomically(tmp_path, monkeypatch):
    pinokio_home = tmp_path / "pinokio"
    app_dir = pinokio_home / "api" / "example" / "app"
    app_dir.mkdir(parents=True)
    monkeypatch.delenv("MAESTRO_STYLE_LIBRARY_DIR", raising=False)
    monkeypatch.delenv("PINOKIO_HOME", raising=False)

    durable = resolve_style_library_root(app_dir)
    assert durable == pinokio_home / "cache" / "maestro" / "style-library"
    assert app_dir not in durable.parents

    legacy = app_dir / "style_library"
    legacy.mkdir()
    (legacy / "sentinel.txt").write_text("keep", encoding="utf-8")
    resolved, notice = migrate_legacy_style_library(legacy, durable)

    assert resolved == durable
    assert notice and "migrated atomically" in notice
    assert not legacy.exists()
    assert (durable / "sentinel.txt").read_text(encoding="utf-8") == "keep"


def test_import_preflight_rejects_before_worker_or_job_creation(tmp_path, monkeypatch):
    library = StyleLibrary(tmp_path / "styles")
    monkeypatch.setattr(
        style_library_module.shutil,
        "disk_usage",
        lambda _path: shutil._ntuple_diskusage(1_000, 950, 50),
    )

    with pytest.raises(StyleImportPreflightError) as captured:
        library.start_minimax_import()

    detail = captured.value.detail()
    assert detail["code"] == "style_import_insufficient_storage"
    assert detail["freeBytes"] == 50
    assert detail["requiredBytes"] > detail["freeBytes"]
    assert library._jobs == {}
    assert library._active_job_id is None
    assert not library.job_path.exists()


def test_cancel_preserves_partial_files_and_resume_completes(tmp_path, monkeypatch):
    library = StyleLibrary(tmp_path / "styles")
    monkeypatch.setitem(MINIMAX_H3_1K_SOURCE, "expectedStyles", 2)
    monkeypatch.setitem(MINIMAX_H3_1K_SOURCE, "expectedBytes", 100)
    monkeypatch.setattr(
        style_library_module.shutil,
        "disk_usage",
        lambda _path: shutil._ntuple_diskusage(2_000_000_000, 0, 2_000_000_000),
    )
    monkeypatch.setattr(
        library,
        "_dataset_info",
        lambda: SimpleNamespace(sha="revision-resume", last_modified=None),
    )
    download_started = style_library_module.threading.Event()

    def partial_download(*, revision, ignored, cancel_event):
        assert revision == "revision-resume"
        library.raw_dir.mkdir(parents=True, exist_ok=True)
        (library.raw_dir / "000001.txt").write_text("first prompt", encoding="utf-8")
        (library.raw_dir / "000001.mp4").write_bytes(b"partial-video")
        download_started.set()
        assert cancel_event.wait(5)

    monkeypatch.setattr(library, "_download_dataset", partial_download)
    first = library.start_minimax_import()
    assert download_started.wait(5)
    cancelling = library.cancel_import(first["jobId"])
    assert cancelling and cancelling["status"] == "cancelling"

    deadline = time.monotonic() + 5
    cancelled = library.import_status(first["jobId"])
    while cancelled and cancelled["status"] != "cancelled" and time.monotonic() < deadline:
        time.sleep(0.02)
        cancelled = library.import_status(first["jobId"])
    assert cancelled and cancelled["status"] == "cancelled"
    assert cancelled["resumeAvailable"] is True
    assert (library.raw_dir / "000001.mp4").is_file()
    assert not library.manifest_path.exists()

    # A process restart recovers the durable job and its partial media.
    library = StyleLibrary(library.root)
    recovered = library.import_status(first["jobId"])
    assert recovered and recovered["status"] == "cancelled"
    assert (library.raw_dir / "000001.mp4").is_file()
    monkeypatch.setattr(
        library,
        "_dataset_info",
        lambda: SimpleNamespace(sha="revision-resume", last_modified=None),
    )

    def completed_download(*, revision, ignored, cancel_event):
        assert not cancel_event.is_set()
        for number in (1, 2):
            sample = f"{number:06d}"
            (library.raw_dir / f"{sample}.txt").write_text(f"prompt {number}", encoding="utf-8")
            (library.raw_dir / f"{sample}.mp4").write_bytes(f"video {number}".encode())

    def completed_preview(record, cancel_event=None):
        assert cancel_event is None or not cancel_event.is_set()
        destination = library.preview_dir / f"{record['id']}.jpg"
        destination.write_bytes(b"preview")
        return destination

    monkeypatch.setattr(library, "_download_dataset", completed_download)
    monkeypatch.setattr(library, "_ensure_preview_for", completed_preview)
    resumed = library.start_minimax_import()
    assert resumed["jobId"] == first["jobId"]
    assert resumed["resumed"] is True

    deadline = time.monotonic() + 5
    completed = library.import_status(resumed["jobId"])
    while completed and completed["status"] != "completed" and time.monotonic() < deadline:
        time.sleep(0.02)
        completed = library.import_status(resumed["jobId"])
    assert completed and completed["status"] == "completed", completed
    assert completed["resumeAvailable"] is False
    assert library.list_styles()["total"] == 2
