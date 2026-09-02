import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import model3d_service, rig_service
from app.services.asset_manifest import SCHEMA_NAME, AssetManifestError, read_asset_manifest


class _DeferredThread:
    def __init__(self, *_args, **_kwargs):
        pass

    def start(self):
        return None


class _SuccessfulWorker:
    pid = 12345
    stdout = ()

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        return None

    def kill(self):
        return None


@pytest.fixture(autouse=True)
def isolated_job_registries():
    registries = (
        (model3d_service._lock, model3d_service._jobs, model3d_service._processes),
        (rig_service._lock, rig_service._jobs, rig_service._processes),
    )
    snapshots = []
    for lock, jobs, processes in registries:
        with lock:
            snapshots.append((dict(jobs), dict(processes)))
            jobs.clear()
            processes.clear()
    try:
        yield
    finally:
        for (lock, jobs, processes), (saved_jobs, saved_processes) in zip(
            registries, snapshots, strict=True
        ):
            with lock:
                jobs.clear()
                jobs.update(saved_jobs)
                processes.clear()
                processes.update(saved_processes)


def _successful_popen(command, **_kwargs):
    if "--output" in command:
        output_index = command.index("--output") + 1
        Path(command[output_index]).write_bytes(b"generated asset")
    return _SuccessfulWorker()


def test_model3d_job_and_sidecar_share_the_canonical_task_identity(tmp_path, monkeypatch):
    job_id = "model3d-fixed-id"
    jobs_dir = tmp_path / "model3d-jobs"
    output_dir = tmp_path / "outputs"
    monkeypatch.setattr(
        model3d_service,
        "installation_status",
        lambda: {"installed": True, "install_hint": None},
    )
    monkeypatch.setattr(
        model3d_service.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=job_id),
    )
    monkeypatch.setattr(model3d_service.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(model3d_service, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(model3d_service, "HF_CACHE_DIR", tmp_path / "model3d-cache")
    monkeypatch.setattr(model3d_service, "_python_path", lambda: Path("/fake/python"))
    monkeypatch.setattr(model3d_service.subprocess, "Popen", _successful_popen)
    dummy_ref = tmp_path / "minimax-ref.png"
    dummy_ref.write_bytes(b"png")
    monkeypatch.setattr(
        model3d_service,
        "_condition_text_job_with_minimax",
        lambda *_args, **_kwargs: str(dummy_ref),
    )

    created = model3d_service.start_job(
        body={"prompt": "A small arcade cabinet"},
        image_paths={},
        output_dir=str(output_dir),
        workspace="studio-a",
    )

    expected_task_id = f"task-model3d-{job_id}"
    assert created["task_id"] == expected_task_id
    assert created["root_task_id"] == expected_task_id
    assert created["workspace"] == "studio-a"

    model3d_service._run_job_serialized(job_id, str(output_dir))

    completed = model3d_service.get_job(job_id)
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["task_id"] == expected_task_id
    assert completed["root_task_id"] == expected_task_id
    output = output_dir / completed["filename"]
    metadata = json.loads(output.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert metadata["schema"] == SCHEMA_NAME
    assert metadata["job_id"] == job_id
    assert metadata["task_id"] == expected_task_id
    assert metadata["root_task_id"] == expected_task_id
    loaded = read_asset_manifest(output)
    assert loaded is not None
    assert loaded["origin"]["tool"] == "model3d"
    assert loaded["origin"]["actor"] == "unknown"
    assert loaded["origin"]["workspace_id"] == "studio-a"


def test_rig_job_and_sidecar_share_the_canonical_task_identity(tmp_path, monkeypatch):
    job_id = "rig-fixed-id"
    jobs_dir = tmp_path / "rig-jobs"
    output_dir = tmp_path / "outputs"
    source = tmp_path / "source.glb"
    source.write_bytes(b"source asset")
    monkeypatch.setattr(
        rig_service,
        "installation_status",
        lambda: {"installed": True, "install_hint": None},
    )
    monkeypatch.setattr(
        rig_service.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=job_id),
    )
    monkeypatch.setattr(rig_service.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(rig_service, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(rig_service, "_python_path", lambda: Path("/fake/python"))
    monkeypatch.setattr(rig_service.subprocess, "Popen", _successful_popen)

    created = rig_service.start_job(
        body={"engine": "procedural", "animations": ["idle"]},
        source_path=str(source),
        output_dir=str(output_dir),
        workspace="studio-b",
    )

    expected_task_id = f"task-rig-{job_id}"
    assert created["task_id"] == expected_task_id
    assert created["root_task_id"] == expected_task_id
    assert created["workspace"] == "studio-b"

    rig_service._run_job_serialized(job_id, str(output_dir))

    completed = rig_service.get_job(job_id)
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["task_id"] == expected_task_id
    assert completed["root_task_id"] == expected_task_id
    output = output_dir / completed["filename"]
    metadata = json.loads(output.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert metadata["schema"] == SCHEMA_NAME
    assert metadata["job_id"] == job_id
    assert metadata["task_id"] == expected_task_id
    assert metadata["root_task_id"] == expected_task_id
    loaded = read_asset_manifest(output)
    assert loaded is not None
    assert loaded["origin"]["tool"] == "rig"
    assert loaded["origin"]["actor"] == "unknown"
    assert loaded["origin"]["workspace_id"] == "studio-b"


def test_model3d_keeps_generated_file_when_sidecar_publish_fails(tmp_path, monkeypatch):
    job_id = "model3d-sidecar-fail"
    jobs_dir = tmp_path / "model3d-jobs"
    output_dir = tmp_path / "outputs"
    monkeypatch.setattr(
        model3d_service,
        "installation_status",
        lambda: {"installed": True, "install_hint": None},
    )
    monkeypatch.setattr(
        model3d_service.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=job_id),
    )
    monkeypatch.setattr(model3d_service.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(model3d_service, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(model3d_service, "HF_CACHE_DIR", tmp_path / "model3d-cache")
    monkeypatch.setattr(model3d_service, "_python_path", lambda: Path("/fake/python"))
    monkeypatch.setattr(model3d_service.subprocess, "Popen", _successful_popen)
    dummy_ref = tmp_path / "minimax-ref.png"
    dummy_ref.write_bytes(b"png")
    monkeypatch.setattr(
        model3d_service,
        "_condition_text_job_with_minimax",
        lambda *_args, **_kwargs: str(dummy_ref),
    )
    monkeypatch.setattr(
        "app.services.asset_manifest.publish_generation_sidecar",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssetManifestError("disk full while writing sidecar")
        ),
    )

    model3d_service.start_job(
        body={"prompt": "A small arcade cabinet"},
        image_paths={},
        output_dir=str(output_dir),
        workspace="studio-a",
    )
    model3d_service._run_job_serialized(job_id, str(output_dir))

    completed = model3d_service.get_job(job_id)
    assert completed is not None
    assert completed["status"] == "completed"
    output = output_dir / completed["filename"]
    assert output.is_file()
    assert output.read_bytes() == b"generated asset"
    assert not output.with_suffix(".meta.json").is_file()


def test_rig_keeps_generated_file_when_sidecar_publish_fails(tmp_path, monkeypatch):
    job_id = "rig-sidecar-fail"
    jobs_dir = tmp_path / "rig-jobs"
    output_dir = tmp_path / "outputs"
    source = tmp_path / "source.glb"
    source.write_bytes(b"source asset")
    monkeypatch.setattr(
        rig_service,
        "installation_status",
        lambda: {"installed": True, "install_hint": None},
    )
    monkeypatch.setattr(
        rig_service.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=job_id),
    )
    monkeypatch.setattr(rig_service.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(rig_service, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(rig_service, "_python_path", lambda: Path("/fake/python"))
    monkeypatch.setattr(rig_service.subprocess, "Popen", _successful_popen)
    monkeypatch.setattr(
        "app.services.asset_manifest.publish_generation_sidecar",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssetManifestError("disk full while writing sidecar")
        ),
    )

    rig_service.start_job(
        body={"engine": "procedural", "animations": ["idle"]},
        source_path=str(source),
        output_dir=str(output_dir),
        workspace="studio-b",
    )
    rig_service._run_job_serialized(job_id, str(output_dir))

    completed = rig_service.get_job(job_id)
    assert completed is not None
    assert completed["status"] == "completed"
    output = output_dir / completed["filename"]
    assert output.is_file()
    assert output.read_bytes() == b"generated asset"
    assert not output.with_suffix(".meta.json").is_file()
