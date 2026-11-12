"""Installation tab backend: status, jobs, uninstall and routes, without Pinokio or an install."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.install_manager import create_install_manager_router
from services import install_catalog, install_jobs, install_remove
from services.install_launcher import LauncherTarget, resolve
from services.install_manager import InstallManager
from services.install_status import Footprint, SizeMeter, directory_footprint

SAM = install_catalog.get("sam")
H3 = install_catalog.get("minimax_h3")
ALL = install_catalog.components()


def wait_for(condition, seconds: float = 3.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def populate(root: Path, component, weight_dir: str | None = None) -> None:
    for relative in component.remove:
        target = root / relative
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x")
        else:
            (target / "bin").mkdir(parents=True, exist_ok=True)
            (target / "bin" / "python").write_text("x" * 100)
    (root / "app" / ".runtime").mkdir(parents=True, exist_ok=True)
    (root / "app" / ".runtime" / f"{component.engine}.managed").write_text("rev")
    if weight_dir:
        (root / weight_dir).mkdir(parents=True, exist_ok=True)
        (root / weight_dir / "model.safetensors").write_text("weights")


class FakeProcess:
    pid = 4242

    def __init__(self) -> None:
        self.finished = threading.Event()

    def wait(self) -> None:
        self.finished.wait(3)


def jobs_for(root: Path, *, installed=lambda engine: True, in_use=lambda engine: False,
             resolver=None, process: FakeProcess | None = None, alive=lambda pid: False):
    process = process or FakeProcess()
    launched = []
    target = LauncherTarget("pterm", "pinokio://127.0.0.1:42000/api/x", root)
    manager = install_jobs.InstallJobs(
        root, installed=installed, in_use=in_use, resolve=resolver or (lambda _root: (target, None)),
        launch=lambda tgt, script, log: launched.append(script) or process, client_alive=alive)
    return manager, process, launched


def test_log_lines_drop_colour_codes_and_progress_redraws():
    raw = "\x1b[32mInstalling\x1b[0m\r10%\r55%\r100%\nDone\n\n"
    assert install_jobs.clean_log_lines(raw, 10) == ["100%", "Done"]
    assert install_jobs.clean_log_lines("a\nb\nc\nd", 2) == ["c", "d"]


def test_directory_footprint_counts_files_and_ignores_links(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one").write_bytes(b"x" * 10)
    (tmp_path / "two").write_bytes(b"x" * 5)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "huge").write_bytes(b"x" * 1000)
    (tmp_path / "link").symlink_to(outside)
    assert directory_footprint(tmp_path) == Footprint(total=15, unshared=15)


def test_a_file_that_uv_hard_linked_from_its_cache_is_not_freed_by_removing_the_folder(tmp_path):
    cache, env = tmp_path / "uv-cache", tmp_path / "env"
    cache.mkdir()
    env.mkdir()
    (cache / "wheel").write_bytes(b"x" * 100)
    os.link(cache / "wheel", env / "torch.so")  # what uv does: same bytes, second name
    (env / "own").write_bytes(b"x" * 7)
    # The 100 bytes stay in the cache after the env goes: only the file nobody else links is freed.
    assert directory_footprint(env) == Footprint(total=107, unshared=7)


def test_size_meter_answers_at_once_and_fills_in_later(tmp_path):
    gate = threading.Event()
    meter = SizeMeter(measure=lambda path: gate.wait(3) and Footprint(7, 3))
    assert meter.get(tmp_path) is None
    gate.set()
    wait_for(lambda: meter.get(tmp_path) == Footprint(7, 3))
    meter.invalidate(tmp_path)
    assert meter.get(tmp_path / "missing") == Footprint(0, 0)


def test_uninstall_removes_the_environment_and_marker_but_keeps_downloaded_models(tmp_path):
    populate(tmp_path, SAM, weight_dir="app/ckpts/sam")
    removal = install_remove.plan(SAM, tmp_path, in_use=lambda engine: False)
    install_remove.execute(removal)
    assert not (tmp_path / SAM.env).exists()
    assert not (tmp_path / "app/.runtime/sam.managed").exists()
    assert (tmp_path / "app/ckpts/sam/model.safetensors").exists()


def test_uninstall_refuses_a_running_engine_and_a_linked_environment(tmp_path):
    populate(tmp_path, H3)
    with pytest.raises(install_remove.RemovalRefused) as running:
        install_remove.plan(H3, tmp_path, in_use=lambda engine: engine == "minimax_h3")
    assert running.value.code == install_remove.IN_USE
    shared = tmp_path / "elsewhere"
    shared.mkdir()
    link = tmp_path / H3.env
    link.rename(tmp_path / "moved")
    link.symlink_to(shared)
    with pytest.raises(install_remove.RemovalRefused) as linked:
        install_remove.plan(H3, tmp_path, in_use=lambda engine: False)
    assert linked.value.code == install_remove.SHARED_ENVIRONMENT


def test_install_job_succeeds_when_the_component_is_installed_afterwards(tmp_path):
    manager, process, launched = jobs_for(tmp_path, installed=lambda engine: engine == "sam")
    job = manager.start_install(SAM, ALL)
    assert launched == ["sam_install.js"] and job["state"] == install_jobs.RUNNING
    process.finished.set()
    wait_for(lambda: manager.job(SAM)["state"] == install_jobs.SUCCEEDED)


def test_install_job_fails_when_pterm_exits_but_nothing_is_installed(tmp_path):
    manager, process, _ = jobs_for(tmp_path, installed=lambda engine: False)
    manager.start_install(SAM, ALL)
    process.finished.set()
    wait_for(lambda: manager.job(SAM)["state"] == install_jobs.FAILED)
    assert manager.job(SAM)["code"] == install_jobs.NOT_INSTALLED_AFTER_RUN


def test_only_one_change_runs_at_a_time(tmp_path):
    manager, process, _ = jobs_for(tmp_path)
    manager.start_install(SAM, ALL)
    with pytest.raises(install_jobs.JobRefused) as busy:
        manager.start_install(H3, ALL)
    assert busy.value.code == install_jobs.BUSY
    process.finished.set()


def test_install_is_refused_without_a_pinokio_launcher(tmp_path):
    manager, _, launched = jobs_for(tmp_path, resolver=lambda _root: (None, "no_pterm"))
    with pytest.raises(install_jobs.JobRefused) as refused:
        manager.start_install(SAM, ALL)
    assert refused.value.code == install_jobs.LAUNCHER_UNAVAILABLE and launched == []


def test_a_running_job_with_a_dead_client_is_closed_after_a_server_restart(tmp_path):
    first, process, _ = jobs_for(tmp_path, alive=lambda pid: True)
    first.start_install(SAM, ALL)
    restarted, _, _ = jobs_for(tmp_path, installed=lambda engine: True, alive=lambda pid: False)
    assert restarted.job(SAM)["state"] == install_jobs.SUCCEEDED
    process.finished.set()


def test_uninstall_job_runs_and_reports(tmp_path):
    populate(tmp_path, SAM)
    manager, _, _ = jobs_for(tmp_path)
    manager.start_uninstall(SAM, ALL)
    wait_for(lambda: manager.job(SAM)["state"] == install_jobs.SUCCEEDED)
    assert not (tmp_path / SAM.env).exists()


def fake_profiles(root: Path, supported=(), installed=()) -> dict:
    engines = {name: {"supported": name in supported, "installed": name in installed, "reason": "needs more VRAM",
                      "env": "app/env"} for name in ("core", "wangp")}
    for component in ALL:
        engines[component.engine] = {"supported": component.engine in supported,
                                     "installed": component.engine in installed, "reason": "needs more VRAM"}
    engines["wangp"]["supported"] = engines["wangp"]["installed"] = True
    engines["core"]["supported"] = True
    return {"engines": engines}


def manager_for(root: Path, **profile_args) -> tuple[InstallManager, FakeProcess]:
    process = FakeProcess()
    target = LauncherTarget("pterm", "ref", root)
    profiles = fake_profiles(root, **profile_args)
    holder = {}
    manager = InstallManager(
        root, detect=lambda inspect: profiles, in_use=lambda engine: False,
        jobs=install_jobs.InstallJobs(
            root, installed=lambda engine: profiles["engines"][engine]["installed"], in_use=lambda engine: False,
            resolve=lambda _root: (target, None), launch=lambda *args: process, client_alive=lambda pid: False,
            on_change=lambda component: holder["manager"]._changed(component)))
    holder["manager"] = manager
    return manager, process


def test_status_lists_every_component_with_its_state(tmp_path):
    (tmp_path / "app/env").mkdir(parents=True)
    populate(tmp_path, SAM)
    populate(tmp_path, H3)
    manager, _ = manager_for(tmp_path, supported={"sam", "minimax_h3", "hunyuan3d"}, installed={"sam"})
    wait_for(lambda: manager.status() and manager.status()["components"][3]["sizeBytes"] is not None
             and manager.status()["components"][3]["reclaimableBytes"] is not None)
    status = {row["id"]: row for row in manager.status()["components"]}
    assert status["sam"]["state"] == "installed"
    assert status["minimax_h3"]["state"] == "needs_update"
    assert status["hunyuan3d"]["state"] == "not_installed" and status["hunyuan3d"]["sizeBytes"] == 0
    assert status["rigging"]["state"] == "unsupported" and status["rigging"]["reason"] == "needs more VRAM"
    assert status["sam"]["estimatedBytes"] > 0 and status["sam"]["restartRequired"] is False
    assert status["sam"]["reclaimableBytes"] > 0, "what the removal deletes is counted, not only the environment"
    assert status["hunyuan3d"]["reclaimableBytes"] == 0
    assert manager.status()["base"]["installed"] is True


def client_for(manager: InstallManager) -> TestClient:
    app = FastAPI()
    app.include_router(create_install_manager_router(lambda: manager))
    return TestClient(app)


def test_routes_report_status_and_start_jobs(tmp_path):
    manager, process = manager_for(tmp_path, supported={"sam"}, installed=set())
    client = client_for(manager)
    assert [row["id"] for row in client.get("/api/v1/system/install").json()["components"]] == [c.id for c in ALL]
    started = client.post("/api/v1/system/install/sam/install")
    assert started.status_code == 202 and started.json()["state"] == "running"
    assert client.get("/api/v1/system/install").json()["busy"] == "sam"
    again = client.post("/api/v1/system/install/sam/install")
    assert again.status_code == 409 and again.json()["detail"]["code"] == install_jobs.BUSY
    assert client.get("/api/v1/system/install/sam/output?lines=5").json() == {"lines": []}
    process.finished.set()


def test_routes_explain_refusals(tmp_path):
    manager, _ = manager_for(tmp_path, supported={"sam"})
    client = client_for(manager)
    unknown = client.post("/api/v1/system/install/nope/install")
    assert unknown.status_code == 404 and unknown.json()["detail"]["code"] == "unknown_component"
    unsupported = client.post("/api/v1/system/install/rigging/install")
    assert unsupported.status_code == 409
    assert unsupported.json()["detail"] == {"code": "unsupported", "message": "needs more VRAM"}
    assert client.get("/api/v1/system/install/sam/output?lines=0").status_code == 422


def test_launcher_needs_a_pinokio_checkout_and_the_pterm_client(tmp_path):
    inside = tmp_path / "api" / "hocuspocus"
    inside.mkdir(parents=True)
    target, reason = resolve(inside, {"HOCUS_PINOKIO_PORT": "42100"}, which=lambda name: "/bin/pterm")
    assert reason is None and target.ref == "pinokio://127.0.0.1:42100/api/hocuspocus"
    assert resolve(tmp_path / "worktree", {}, which=lambda name: "/bin/pterm")[1] == "not_in_pinokio"
    assert resolve(inside, {}, which=lambda name: None)[1] == "no_pterm"
    forced = resolve(tmp_path, {"HOCUS_PINOKIO_REF": "pinokio://h:1/api/y"}, which=lambda name: "/bin/pterm")
    assert forced[0].ref == "pinokio://h:1/api/y"


def test_engine_in_use_answers_even_when_the_service_cannot_be_imported(monkeypatch):
    # The core runtime has no websocket client, so importing the H3 service raises there.
    import builtins
    from services import install_manager
    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "services" and args and args[2] and "minimax_h3_service" in args[2]:
            raise ImportError("websocket")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    assert install_manager._engine_in_use("minimax_h3") is False
    assert install_manager._engine_in_use("unknown_engine") is False


def test_sam_is_runtime_running_follows_the_sidecar_process(monkeypatch):
    from services import inpaint_service

    class Live:
        def poll(self):
            return None

    class Dead:
        def poll(self):
            return 0

    monkeypatch.setattr(inpaint_service, "_sam_process", Live())
    assert inpaint_service.is_runtime_running() is True
    monkeypatch.setattr(inpaint_service, "_sam_process", Dead())
    assert inpaint_service.is_runtime_running() is False
    monkeypatch.setattr(inpaint_service, "_sam_process", None)
    assert inpaint_service.is_runtime_running() is False


def test_engine_in_use_sees_every_live_sidecar_and_worker(monkeypatch):
    from services import (
        creation_model_service,
        inpaint_service,
        install_manager,
        minimax_h3_service,
        model3d_service,
        rig_service,
        see_through_layers,
    )

    monkeypatch.setattr(minimax_h3_service, "is_runtime_running", lambda: True)
    monkeypatch.setattr(creation_model_service, "runtime_status", lambda: {"warm": True})
    monkeypatch.setattr(inpaint_service, "is_runtime_running", lambda: True)
    monkeypatch.setattr(model3d_service, "has_active_jobs", lambda model_id=None: model_id is None)
    monkeypatch.setattr(rig_service, "has_active_unirig_jobs", lambda: True)
    monkeypatch.setattr(rig_service, "has_active_jobs", lambda engine=None: engine == "mia")
    monkeypatch.setattr(see_through_layers, "is_running", lambda: True)

    assert install_manager._engine_in_use("minimax_h3") is True
    assert install_manager._engine_in_use("creation_models") is True
    assert install_manager._engine_in_use("sam") is True
    assert install_manager._engine_in_use("hunyuan3d") is True
    assert install_manager._engine_in_use("trellis2") is False
    assert install_manager._engine_in_use("rigging") is True
    assert install_manager._engine_in_use("mia") is True
    assert install_manager._engine_in_use("see_through") is True

    monkeypatch.setattr(model3d_service, "has_active_jobs", lambda model_id=None: model_id == "trellis2")
    assert install_manager._engine_in_use("hunyuan3d") is False
    assert install_manager._engine_in_use("trellis2") is True

    monkeypatch.setattr(creation_model_service, "runtime_status", lambda: {"warm": False})
    monkeypatch.setattr(inpaint_service, "is_runtime_running", lambda: False)
    monkeypatch.setattr(minimax_h3_service, "is_runtime_running", lambda: False)
    monkeypatch.setattr(rig_service, "has_active_unirig_jobs", lambda: False)
    monkeypatch.setattr(rig_service, "has_active_jobs", lambda engine=None: False)
    monkeypatch.setattr(model3d_service, "has_active_jobs", lambda model_id=None: False)
    monkeypatch.setattr(see_through_layers, "is_running", lambda: False)
    assert install_manager._engine_in_use("creation_models") is False
    assert install_manager._engine_in_use("sam") is False
    assert install_manager._engine_in_use("minimax_h3") is False
    assert install_manager._engine_in_use("rigging") is False
    assert install_manager._engine_in_use("mia") is False
    assert install_manager._engine_in_use("see_through") is False


def test_engine_in_use_sees_a_live_mia_job():
    from services import install_manager, rig_service

    with rig_service._lock:
        rig_service._jobs["install-probe"] = {"status": "running", "engine": "mia"}
    try:
        assert install_manager._engine_in_use("mia") is True
        assert install_manager._engine_in_use("rigging") is False
    finally:
        with rig_service._lock:
            rig_service._jobs.pop("install-probe", None)
