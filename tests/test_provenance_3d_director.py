"""Folder vs Workspace provenance for 3D, Rig, Director and alternative songs."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import alternative_songs, director_pipeline, model3d_service, rig_service
from app.services.asset_manifest import (
    SCHEMA_NAME,
    AssetManifestError,
    publish_generation_sidecar,
    read_asset_manifest,
)
from app.services.generation_provenance import provenance_from_manifest


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


def _capture_publish(monkeypatch):
    captured: dict = {}
    real = publish_generation_sidecar

    def wrapped(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = dict(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(
        "app.services.asset_manifest.publish_generation_sidecar", wrapped,
    )
    return captured


def _assert_folder_only(loaded: dict, folder: str, *, tool: str):
    assert loaded["origin"]["tool"] == tool
    assert loaded["origin"]["actor"] == "unknown"
    assert loaded["origin"]["output_folder"] == folder
    assert loaded["origin"].get("workspace_id") in (None, "")
    proven = provenance_from_manifest(loaded)
    assert proven["tool"] == tool
    assert proven["actor"] == "unknown"
    assert proven["output_folder"] == folder
    assert proven["workspace_id"] is None
    return proven


def test_model3d_writer_passes_output_folder_not_workspace_collection(tmp_path, monkeypatch):
    job_id = "model3d-folder-only"
    jobs_dir = tmp_path / "model3d-jobs"
    output_dir = tmp_path / "outputs"
    captured = _capture_publish(monkeypatch)
    monkeypatch.setattr(
        model3d_service, "installation_status",
        lambda: {"installed": True, "install_hint": None},
    )
    monkeypatch.setattr(
        model3d_service.uuid, "uuid4", lambda: SimpleNamespace(hex=job_id),
    )
    monkeypatch.setattr(model3d_service.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(model3d_service, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(model3d_service, "HF_CACHE_DIR", tmp_path / "model3d-cache")
    monkeypatch.setattr(model3d_service, "_python_path", lambda: Path("/fake/python"))
    monkeypatch.setattr(model3d_service.subprocess, "Popen", _successful_popen)
    dummy_ref = tmp_path / "minimax-ref.png"
    dummy_ref.write_bytes(b"png")
    monkeypatch.setattr(
        model3d_service, "_condition_text_job_with_minimax",
        lambda *_args, **_kwargs: str(dummy_ref),
    )

    model3d_service.start_job(
        body={"prompt": "A small arcade cabinet"},
        image_paths={},
        output_dir=str(output_dir),
        workspace="studio-a",
    )
    model3d_service._run_job_serialized(job_id, str(output_dir))

    kwargs = captured["kwargs"]
    assert kwargs.get("output_folder") == "studio-a"
    assert kwargs.get("workspace_id") in (None, "")
    assert kwargs.get("tool") == "model3d"
    sidecar = captured["args"][1]
    assert sidecar["job_id"] == job_id
    assert sidecar["task_id"] == f"task-model3d-{job_id}"
    assert sidecar["root_task_id"] == f"task-model3d-{job_id}"

    completed = model3d_service.get_job(job_id)
    output = output_dir / completed["filename"]
    loaded = read_asset_manifest(output)
    proven = _assert_folder_only(loaded, "studio-a", tool="model3d")
    assert proven["command"]["job_id"] == job_id
    assert proven["command"]["task_id"] == f"task-model3d-{job_id}"
    assert proven["command"]["root_task_id"] == f"task-model3d-{job_id}"
    assert proven["provider"] == "hunyuan3d"
    assert proven["model_id"] == "hunyuan3d-2-turbo"


def test_model3d_writer_keeps_wizard_command_provenance(tmp_path):
    output = tmp_path / "wizard.glb"
    output.write_bytes(b"mesh")
    task_id = "canonical-model3d-wizard-job"
    model3d_service._publish_model3d_result({
        "job_id": "wizard-job",
        "task_id": task_id,
        "root_task_id": task_id,
        "workspace": "physical-folder",
        "created_at": 1_700_000_000,
        "started_at": 1_700_000_002,
        "provenance": {
            "actor": "wizard",
            "tool": "studio",
            "capability": "start_generation",
            "command": {"command_id": "command-wizard-3d"},
        },
    }, output, {
        "generation_mode": "model3d",
        "params": {"model_type": "hunyuan3d-2-turbo", "provider": "hunyuan3d"},
    })

    loaded = read_asset_manifest(output)
    assert loaded["origin"]["tool"] == "studio"
    assert loaded["origin"]["actor"] == "wizard"
    assert loaded["origin"]["capability"] == "start_generation"
    assert loaded["origin"]["output_folder"] == "physical-folder"
    assert loaded["origin"].get("workspace_id") in (None, "")
    assert loaded["execution"]["command_id"] == "command-wizard-3d"
    assert loaded["execution"]["task_id"] == task_id


def test_model3d_strips_absolute_output_folder_path(tmp_path, monkeypatch):
    job_id = "model3d-abs-folder"
    jobs_dir = tmp_path / "model3d-jobs"
    output_dir = tmp_path / "outputs"
    captured = _capture_publish(monkeypatch)
    monkeypatch.setattr(
        model3d_service, "installation_status",
        lambda: {"installed": True, "install_hint": None},
    )
    monkeypatch.setattr(
        model3d_service.uuid, "uuid4", lambda: SimpleNamespace(hex=job_id),
    )
    monkeypatch.setattr(model3d_service.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(model3d_service, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(model3d_service, "HF_CACHE_DIR", tmp_path / "model3d-cache")
    monkeypatch.setattr(model3d_service, "_python_path", lambda: Path("/fake/python"))
    monkeypatch.setattr(model3d_service.subprocess, "Popen", _successful_popen)
    dummy_ref = tmp_path / "minimax-ref.png"
    dummy_ref.write_bytes(b"png")
    monkeypatch.setattr(
        model3d_service, "_condition_text_job_with_minimax",
        lambda *_args, **_kwargs: str(dummy_ref),
    )

    created = model3d_service.start_job(
        body={"prompt": "A small arcade cabinet"},
        image_paths={},
        output_dir=str(output_dir),
        workspace="studio-a",
    )
    with model3d_service._lock:
        model3d_service._jobs[created["job_id"]]["workspace"] = str(tmp_path / "studio-a")
    model3d_service._run_job_serialized(job_id, str(output_dir))

    assert captured["kwargs"]["output_folder"] == "studio-a"
    completed = model3d_service.get_job(job_id)
    loaded = read_asset_manifest(output_dir / completed["filename"])
    _assert_folder_only(loaded, "studio-a", tool="model3d")


def test_rig_writer_passes_output_folder_not_workspace_collection(tmp_path, monkeypatch):
    job_id = "rig-folder-only"
    jobs_dir = tmp_path / "rig-jobs"
    output_dir = tmp_path / "outputs"
    source = tmp_path / "source.glb"
    source.write_bytes(b"source asset")
    captured = _capture_publish(monkeypatch)
    monkeypatch.setattr(
        rig_service, "installation_status",
        lambda: {"installed": True, "install_hint": None},
    )
    monkeypatch.setattr(
        rig_service.uuid, "uuid4", lambda: SimpleNamespace(hex=job_id),
    )
    monkeypatch.setattr(rig_service.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(rig_service, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(rig_service, "_python_path", lambda: Path("/fake/python"))
    monkeypatch.setattr(rig_service.subprocess, "Popen", _successful_popen)

    rig_service.start_job(
        body={"engine": "procedural", "animations": ["idle"]},
        source_path=str(source),
        output_dir=str(output_dir),
        workspace="studio-b",
    )
    rig_service._run_job_serialized(job_id, str(output_dir))

    kwargs = captured["kwargs"]
    assert kwargs.get("output_folder") == "studio-b"
    assert kwargs.get("workspace_id") in (None, "")
    assert kwargs.get("tool") == "rig"
    sidecar = captured["args"][1]
    assert sidecar["job_id"] == job_id
    assert sidecar["task_id"] == f"task-rig-{job_id}"

    completed = rig_service.get_job(job_id)
    loaded = read_asset_manifest(output_dir / completed["filename"])
    proven = _assert_folder_only(loaded, "studio-b", tool="rig")
    assert proven["command"]["job_id"] == job_id
    assert proven["command"]["task_id"] == f"task-rig-{job_id}"
    assert proven["provider"] == "local"
    assert proven["model_id"] == "rig-procedural"


def test_glb_survives_when_inner_sidecar_publish_raises(tmp_path, monkeypatch):
    job_id = "model3d-sidecar-raise"
    jobs_dir = tmp_path / "model3d-jobs"
    output_dir = tmp_path / "outputs"
    monkeypatch.setattr(
        model3d_service, "installation_status",
        lambda: {"installed": True, "install_hint": None},
    )
    monkeypatch.setattr(
        model3d_service.uuid, "uuid4", lambda: SimpleNamespace(hex=job_id),
    )
    monkeypatch.setattr(model3d_service.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(model3d_service, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(model3d_service, "HF_CACHE_DIR", tmp_path / "model3d-cache")
    monkeypatch.setattr(model3d_service, "_python_path", lambda: Path("/fake/python"))
    monkeypatch.setattr(model3d_service.subprocess, "Popen", _successful_popen)
    dummy_ref = tmp_path / "minimax-ref.png"
    dummy_ref.write_bytes(b"png")
    monkeypatch.setattr(
        model3d_service, "_condition_text_job_with_minimax",
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
    output = output_dir / completed["filename"]
    assert completed["status"] == "completed"
    assert output.is_file()
    assert output.read_bytes() == b"generated asset"
    assert not output.with_suffix(".meta.json").is_file()


def test_director_assembly_folder_only_does_not_invent_workspace_id(tmp_path):
    media = tmp_path / "minimax_h3_pipe-7_multiclip.mp4"
    media.write_bytes(b"video")
    director_pipeline._write_director_assembly_sidecar(
        str(media),
        {
            "params": {
                "model_type": "minimax_h3",
                "director_pipeline_id": "pipe-7",
                "provider": "minimax",
            },
            "generation_mode": "video",
            "created_at": 1_700_000_100,
        },
        "night-shift",
    )
    loaded = read_asset_manifest(media)
    proven = _assert_folder_only(loaded, "night-shift", tool="director")
    assert proven["command"]["pipeline_id"] == "pipe-7"
    assert proven["model_id"] == "minimax_h3"
    assert proven["provider"] == "minimax"
    raw = json.loads(media.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert raw["schema"] == SCHEMA_NAME
    assert raw["pipeline_id"] == "pipe-7"
    assert raw["origin"]["tool"] == "director"


def test_director_timing_records_folder_and_command_ids(tmp_path):
    media = tmp_path / "final.mp4"
    media.write_bytes(b"video")
    pipeline = {
        "id": "pipe-timing",
        "workspace": "night-shift",
        "job_id": "job-timing",
        "task_id": "task-director-pipe-timing",
        "root_task_id": "task-director-pipe-timing",
        "created_at": 100.0,
        "_completed_at": 410.0,
        "_prompt_generation_time_sec": 10.0,
        "_image_generation_time_sec": 20.0,
        "_video_generation_time_sec": 250.0,
        "_assembly_time_sec": 5.0,
        "video_model": "minimax_h3_legacy",
        "params": {"pipeline_type": "short_film_story", "production_kind": "story"},
    }
    assert director_pipeline.persist_pipeline_output_timing(
        str(tmp_path), "final.mp4", pipeline,
    )
    loaded = read_asset_manifest(media)
    proven = _assert_folder_only(loaded, "night-shift", tool="director")
    assert proven["command"]["pipeline_id"] == "pipe-timing"
    assert proven["command"]["job_id"] == "job-timing"
    assert proven["command"]["task_id"] == "task-director-pipe-timing"
    assert proven["command"]["root_task_id"] == "task-director-pipe-timing"
    assert proven["model_id"] == "minimax_h3_legacy"


def test_director_timing_strips_absolute_workspace_path(tmp_path):
    media = tmp_path / "final.mp4"
    media.write_bytes(b"video")
    assert director_pipeline.persist_pipeline_output_timing(
        str(tmp_path),
        "final.mp4",
        {
            "id": "pipe-abs",
            "workspace": str(tmp_path / "night-shift"),
            "created_at": 100.0,
            "_completed_at": 110.0,
        },
    )
    loaded = read_asset_manifest(media)
    _assert_folder_only(loaded, "night-shift", tool="director")


def test_alternative_songs_folder_only_does_not_invent_workspace_id(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    sidecar = alternative_songs.load_sidecar(str(video))
    alternative_songs.attach_song(sidecar, audio_name="en.mp3", duration_seconds=9)
    sidecar["workspace"] = "night-shift"
    alternative_songs.save_sidecar(str(video), sidecar)
    loaded = read_asset_manifest(video)
    _assert_folder_only(loaded, "night-shift", tool="studio")


def test_alternative_songs_mounted_output_keeps_director_command_ids(tmp_path):
    output = tmp_path / "clip_en_mv.mp4"
    output.write_bytes(b"video")
    song = alternative_songs.attach_song(
        {"params": {}}, audio_name="en.mp3", duration_seconds=9,
    )
    alternative_songs.write_mounted_sidecar(
        output_path=str(output),
        parent_name="clip.mp4",
        parent_sidecar={
            "pipeline_id": "pipe-director",
            "task_id": "task-director-pipe-director",
            "root_task_id": "task-director-pipe-director",
            "params": {
                "pipeline_type": "music_video",
                "model_type": "minimax_h3",
                "director_pipeline_id": "pipe-director",
            },
        },
        song=song,
        planned=[{
            "name": "shot.mp4",
            "path": str(tmp_path / "shot.mp4"),
            "duration": 4,
            "used": 4,
            "extra": False,
        }],
        job_id="alt-song-9",
        workspace="night-shift",
    )
    loaded = read_asset_manifest(output)
    proven = _assert_folder_only(loaded, "night-shift", tool="alternative-songs")
    assert proven["command"]["job_id"] == "alt-song-9"
    assert proven["command"]["pipeline_id"] == "pipe-director"
    assert proven["command"]["task_id"] == "task-director-pipe-director"
    assert proven["model_id"] == "minimax_h3"
