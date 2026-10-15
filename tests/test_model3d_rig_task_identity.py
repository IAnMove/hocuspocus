import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app_identity import startup_identity
from app.services import model3d_service, rig_service
from app.services.asset_manifest import SCHEMA_NAME, AssetManifestError, read_asset_manifest
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
    # The sidecar writer reads the app identity through `git` once; the tests below replace the shared
    # `subprocess.Popen`, so that first read must not happen inside them (the file would fail when run alone).
    startup_identity()
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
    assert completed["url"] == f"/api/v1/file/{completed['filename']}?workspace=studio-a"
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
    assert loaded["origin"]["output_folder"] == "studio-a"
    assert loaded["origin"].get("workspace_id") in (None, "")
    assert loaded["execution"]["job_id"] == job_id
    assert loaded["execution"]["task_id"] == expected_task_id
    assert loaded["execution"]["root_task_id"] == expected_task_id
    assert loaded["generation"]["model"]["id"] == "hunyuan3d-2-turbo"
    assert loaded["generation"]["model"]["provider"] == "hunyuan3d"
    proven = provenance_from_manifest(loaded)
    assert proven["tool"] == "model3d"
    assert proven["actor"] == "unknown"
    assert proven["output_folder"] == "studio-a"
    assert proven["workspace_id"] is None
    assert proven["command"]["job_id"] == job_id
    assert proven["command"]["task_id"] == expected_task_id
    assert proven["provider"] == "hunyuan3d"
    assert proven["model_id"] == "hunyuan3d-2-turbo"


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
    assert completed["url"] == f"/api/v1/file/{completed['filename']}?workspace=studio-b"
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
    assert loaded["origin"]["output_folder"] == "studio-b"
    assert loaded["origin"].get("workspace_id") in (None, "")
    assert loaded["execution"]["job_id"] == job_id
    assert loaded["execution"]["task_id"] == expected_task_id
    assert loaded["execution"]["root_task_id"] == expected_task_id
    assert loaded["generation"]["model"]["id"] == "rig-procedural"
    assert loaded["generation"]["model"]["provider"] == "local"
    proven = provenance_from_manifest(loaded)
    assert proven["tool"] == "rig"
    assert proven["actor"] == "unknown"
    assert proven["output_folder"] == "studio-b"
    assert proven["workspace_id"] is None
    assert proven["command"]["job_id"] == job_id
    assert proven["command"]["task_id"] == expected_task_id
    assert proven["provider"] == "local"
    assert proven["model_id"] == "rig-procedural"


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


class _FailingWorker(_SuccessfulWorker):
    def __init__(self, lines):
        self.stdout = [line + "\n" for line in lines]

    def poll(self):
        return 1

    def wait(self, timeout=None):
        return 1


@pytest.mark.parametrize("lines,code,shown", [
    (['MAESTRO_RESULT {"ok": false, "error": "invalid_input", "reason": "compressed meshes are not supported"}'],
     "invalid_input", "invalid_input: compressed meshes are not supported"),
    (['MAESTRO_RESULT {"ok": false, "error": "not_humanoid", "reason": "turned"}'],
     "not_humanoid", "not_humanoid: the model is turned at an angle"),
    (["Traceback (most recent call last):", '  File "weights.py", line 9, in smooth', "IndexError: index 9 is out of bounds",
      'MAESTRO_RESULT {"ok": false, "error": "rig_failed", "reason": "index 9 is out of bounds"}'],
     None, "IndexError: index 9 is out of bounds"),
])
def test_rig_refusals_keep_their_code_and_crashes_keep_their_trace(tmp_path, monkeypatch, lines, code, shown):
    job_id = "rig-refused"
    source = tmp_path / "source.glb"
    source.write_bytes(b"source asset")
    monkeypatch.setattr(rig_service, "installation_status", lambda: {"installed": True, "install_hint": None})
    monkeypatch.setattr(rig_service.uuid, "uuid4", lambda: SimpleNamespace(hex=job_id))
    monkeypatch.setattr(rig_service.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(rig_service, "JOBS_DIR", tmp_path / "rig-jobs")
    monkeypatch.setattr(rig_service, "_python_path", lambda: Path("/fake/python"))
    monkeypatch.setattr(rig_service.subprocess, "Popen", lambda *_args, **_kwargs: _FailingWorker(lines))

    rig_service.start_job(body={"engine": "procedural", "animations": ["idle"]}, source_path=str(source),
                          output_dir=str(tmp_path / "outputs"), workspace="studio-b")
    rig_service._run_job_serialized(job_id, str(tmp_path / "outputs"))

    failed = rig_service.get_job(job_id)
    assert failed["status"] == "failed"
    assert shown in failed["error"]
    assert failed.get("error_code") == code


# --- rig job control belongs to this install (assets-05) ---------------------------------------------------
# Several installs (the live one, worktrees, a validation or a lent instance) link the SAME ckpts folder, so
# a pid file in it is not proof the process is ours. Job control lives in the install's own settings/ folder
# (like the 3D jobs) and only a worker started with THIS install's request file is ever signalled.

def _sleeping_worker(*argv: str) -> subprocess.Popen:
    """A process that only sleeps; its command line carries ``argv`` like a real worker's does."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", *argv],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _survives(process: subprocess.Popen, seconds: float = 0.6) -> bool:
    try:
        process.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return True
    return False


def test_rig_job_folder_is_inside_this_install_and_not_in_the_shared_ckpts():
    settings = rig_service.APP_DIR / "settings"
    assert rig_service.JOBS_DIR.is_relative_to(settings)
    assert "ckpts" not in rig_service.JOBS_DIR.parts
    assert rig_service.HF_CACHE_DIR.is_relative_to(rig_service.APP_DIR / "ckpts")  # weights stay shared


def test_reaping_leaves_a_worker_of_another_install_alone_and_ends_our_own(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "rig-jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(rig_service, "JOBS_DIR", jobs_dir)
    foreign_worker = str(tmp_path / "other" / "app" / "services" / "hunyuan3d" / "rig_worker.py")
    elsewhere = _sleeping_worker(foreign_worker, "--request", str(tmp_path / "shared" / "rig" / "jobs" / "x.json"))
    ours = _sleeping_worker(foreign_worker, "--request", str(jobs_dir / "ours.json"))
    humanoid = _sleeping_worker("-m", "services.humanoid_rig.worker", "--request", str(jobs_dir / "human.json"))
    try:
        (jobs_dir / "x.pid").write_text(str(elsewhere.pid))
        (jobs_dir / "ours.pid").write_text(str(ours.pid))
        (jobs_dir / "human.pid").write_text(str(humanoid.pid))
        rig_service._reap_stale_jobs()
        assert _survives(elsewhere), "a pid whose command line names another folder is never ours to signal"
        assert ours.wait(timeout=10) is not None
        assert humanoid.wait(timeout=10) is not None
        assert list(jobs_dir.iterdir()) == []
    finally:
        for process in (elsewhere, ours, humanoid):
            process.kill()
            process.wait()


def test_a_pid_file_does_not_vouch_for_a_worker_of_another_job(tmp_path, monkeypatch):
    """The request file must be the one of the pid file's own job, not just any file of this folder."""
    jobs_dir = tmp_path / "rig-jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(rig_service, "JOBS_DIR", jobs_dir)
    worker = str(tmp_path / "app" / "services" / "rigging" / "rig_worker_unirig.py")
    other_job = _sleeping_worker(worker, "--request", str(jobs_dir / "job-b.json"))
    try:
        (jobs_dir / "job-a.pid").write_text(str(other_job.pid))
        rig_service._reap_stale_jobs()
        assert _survives(other_job)
    finally:
        other_job.kill()
        other_job.wait()


def test_a_second_install_sharing_ckpts_does_not_kill_the_first_installs_rig_worker(tmp_path):
    """The real hazard: install B imports rig_service while install A's worker is listed in the shared ckpts."""
    shared_jobs = tmp_path / "shared-ckpts" / "rig" / "jobs"
    shared_jobs.mkdir(parents=True)
    app_b = tmp_path / "install-b" / "app"
    app_b.mkdir(parents=True)
    (app_b / "ckpts").symlink_to(tmp_path / "shared-ckpts", target_is_directory=True)
    own_jobs = app_b / "settings" / "rig-jobs"
    own_jobs.mkdir(parents=True)
    worker_a = str(tmp_path / "install-a" / "app" / "services" / "hunyuan3d" / "rig_worker.py")
    worker_b = str(app_b / "services" / "hunyuan3d" / "rig_worker.py")
    first = _sleeping_worker(worker_a, "--request", str(shared_jobs / "jobA.json"))
    orphan_of_b = _sleeping_worker(worker_b, "--request", str(own_jobs / "jobB.json"))
    try:
        (shared_jobs / "jobA.json").write_text("{}")
        (shared_jobs / "jobA.pid").write_text(str(first.pid))
        (own_jobs / "jobB.pid").write_text(str(orphan_of_b.pid))
        app_dir = Path(rig_service.__file__).resolve().parents[1]
        code = (
            "import sys\nsys.path.insert(0, sys.argv[1])\n"
            "source = open(sys.argv[2], encoding='utf-8').read()\n"
            "scope = {'__name__': 'services.rig_service', '__package__': 'services', '__file__': sys.argv[3]}\n"
            "exec(compile(source, sys.argv[3], 'exec'), scope)\n"
        )
        boot = subprocess.run(
            [sys.executable, "-c", code, str(app_dir), str(Path(rig_service.__file__)), str(app_b / "services" / "rig_service.py")],
            capture_output=True, text=True, timeout=120, cwd=str(tmp_path),
        )
        assert boot.returncode == 0, boot.stderr[-800:]
        assert _survives(first), "install B must not signal the worker install A listed in the shared ckpts"
        assert orphan_of_b.wait(timeout=10) is not None, "install B ends its own previous run's worker"
        assert sorted(path.name for path in shared_jobs.iterdir()) == ["jobA.json", "jobA.pid"]
    finally:
        for process in (first, orphan_of_b):
            process.kill()
            process.wait()


# --- the file URL a finished job reports names the workspace the job ran in (assets-08) ---------------------
# GET /api/v1/file/<name> serves a bare name from the ACTIVE workspace only; a job that ran in another
# workspace reported a URL that answered 404. The MCP doors already added `?workspace=`; the job now says it.

def _model3d_job(job_id, **extra):
    request = model3d_service._prepare_request({"model_id": "hunyuan3d-2-turbo"}, {"front": "reference.png"})
    job = {"job_id": job_id, "task_id": model3d_service._canonical_task_id(job_id), "status": "waiting_resource",
           "progress": 0, "request": request, "updated_at": 0, **extra}
    model3d_service._jobs[job_id] = job
    return job


def test_simulated_model3d_job_reports_a_url_with_its_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(
        model3d_service.execution_mode, "POLICY",
        SimpleNamespace(simulated=True, fail_kind="", fail_count=1, step_delay=0.0),
    )
    job_id = "sim-url-workspace"
    _model3d_job(job_id, workspace="studio c")
    model3d_service._run_job_serialized(job_id, str(tmp_path))
    done = model3d_service.get_job(job_id)
    assert done["status"] == "completed"
    assert done["url"] == f"/api/v1/file/{done['filename']}?workspace=studio%20c"


def test_remote_model3d_job_reports_a_url_with_its_workspace(monkeypatch, tmp_path):
    from app.services import meshy_3d_service

    job_id = "meshy-url-workspace"
    monkeypatch.setattr(model3d_service.execution_mode, "validate_generation", lambda *_a, **_k: None)
    monkeypatch.setattr(model3d_service.execution_mode, "validate_remote_provider", lambda *_a, **_k: None)
    monkeypatch.setattr(model3d_service, "_active_profile", lambda: {"model3d_provider": "meshy"})
    monkeypatch.setattr(model3d_service, "_services", lambda: {"meshy_api_key": "key"})
    monkeypatch.setattr(model3d_service.uuid, "uuid4", lambda: SimpleNamespace(hex=job_id))
    monkeypatch.setattr(model3d_service.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(model3d_service, "_publish_model3d_result", lambda *_a, **_k: None)

    def _generate(*, output_dir, filename_stem, **_kwargs):
        (Path(output_dir) / f"{filename_stem}.glb").write_bytes(b"glb")
        return {"filename": f"{filename_stem}.glb"}

    monkeypatch.setattr(meshy_3d_service, "generate_model", _generate)
    model3d_service.start_job(body={"provider": "meshy", "prompt": "a lamp"}, image_paths={},
                              output_dir=str(tmp_path), workspace="studio-c")
    model3d_service._run_remote_job(job_id, str(tmp_path))
    done = model3d_service.get_job(job_id)
    assert done["status"] == "completed"
    assert done["url"] == f"/api/v1/file/{done['filename']}?workspace=studio-c"


def test_a_job_without_a_workspace_reports_the_default_one(monkeypatch, tmp_path):
    monkeypatch.setattr(
        model3d_service.execution_mode, "POLICY",
        SimpleNamespace(simulated=True, fail_kind="", fail_count=1, step_delay=0.0),
    )
    job_id = "sim-url-default"
    _model3d_job(job_id)
    model3d_service._run_job_serialized(job_id, str(tmp_path))
    assert model3d_service.get_job(job_id)["url"].endswith("?workspace=default")
