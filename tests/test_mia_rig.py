"""Make-It-Animatable rig engine: install door, worker seam, suggestion, three clients."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import canonical_task_publishers, resource_scheduler, rig_service
from app.services.rigging import mia, mia_predict, rig_worker_mia
from app.services.rigging.mia_predict import blender_namespace
from services import install_catalog
from services.model3d_rig_commands import command_catalog
from services.runtime_profiles import catalog, select_profiles

ROOT = Path(__file__).resolve().parents[1]
PIN = "8fb51382ff6da556cdb95cc03a48200603f3a493"


@pytest.fixture(autouse=True)
def _isolate_rig_jobs():
    with rig_service._lock:
        saved = (dict(rig_service._jobs), dict(rig_service._processes))
        rig_service._jobs.clear()
        rig_service._processes.clear()
    yield
    with rig_service._lock:
        rig_service._jobs.clear()
        rig_service._jobs.update(saved[0])
        rig_service._processes.clear()
        rig_service._processes.update(saved[1])


class _DeferredThread:
    def __init__(self, *_args, **_kwargs):
        pass

    def start(self):
        return None


class _QuietWorker:
    pid = 4242

    def __init__(self, lines):
        self.stdout = [line if line.endswith("\n") else line + "\n" for line in lines]

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def test_mia_stays_absent_until_its_own_install_and_keeps_todays_engines():
    assert mia.installed() is False
    assert mia.weights_ready() is False
    engines = {item["id"]: item for item in rig_service.capabilities()["engines"]}
    assert list(engines) == ["procedural", "unirig", "humanoid", "mia", "meshy"]
    assert engines["mia"]["installed"] is False
    assert "Install Make-It-Animatable" in engines["mia"]["install_hint"]
    assert engines["humanoid"]["installed"] is True or engines["humanoid"]["install_hint"]


def test_catalog_is_linux_only_and_records_the_licences():
    spec = catalog()["engines"]["mia"]
    assert spec["platforms"] == ["linux"]
    assert spec["cuda"] == "12.1"
    assert spec["defaultInstall"] is False
    linux = select_profiles("linux", "x64", "nvidia", "570.26")["engines"]["mia"]
    assert linux["supported"] is True
    old_driver = select_profiles("linux", "x64", "nvidia", "520.0")["engines"]["mia"]
    assert old_driver["supported"] is False
    windows = select_profiles("win32", "x64", "nvidia", "580.82.09")["engines"]["mia"]
    assert windows["supported"] is False
    assert "Linux" in windows["reason"]
    component = next(item for item in install_catalog.components() if item.id == "mia")
    assert "MIT" in component.summary and "Apache-2.0" in component.summary
    assert "no stated dataset licence" in component.summary
    assert component.env in component.remove
    vendor = json.loads((ROOT / "app/runtime/vendors.json").read_text())["make_it_animatable"]
    assert vendor["revision"] == PIN
    assert vendor["marker"].endswith(PIN + ".installed")
    assert "recursive" not in vendor
    assert mia.WEIGHT_RELATIVE == rig_worker_mia.WEIGHT_RELATIVE


def test_blender_export_asks_for_a_rest_pose_glb():
    args = blender_namespace(Path("rest.glb"), Path("bones.fbx"))
    assert args.output_path.endswith(".fbx")
    assert args.rest_path == "rest.glb"
    assert args.reset_to_rest is True
    assert args.template_path == "bones.fbx"
    assert args.animation_path is None


def test_predict_refuses_without_the_checkout(tmp_path):
    with pytest.raises(RuntimeError, match="not installed"):
        rig_worker_mia.predict_rest_glb(tmp_path / "in.glb", tmp_path / "out.glb", 1)


def test_unknown_engine_is_still_rejected_and_mia_needs_its_install(tmp_path):
    source = tmp_path / "hero.glb"
    source.write_bytes(b"glb")
    with pytest.raises(ValueError, match="Unknown rig engine"):
        rig_service.start_job(body={"engine": "nope"}, source_path=str(source), output_dir=str(tmp_path))
    with pytest.raises(RuntimeError, match="Install Make-It-Animatable"):
        rig_service.start_job(body={"engine": "mia", "animations": ["idle"]}, source_path=str(source), output_dir=str(tmp_path))


def test_mia_job_uses_the_gpu_lane_and_its_worker(tmp_path, monkeypatch):
    source = tmp_path / "hero.glb"
    source.write_bytes(b"glb")
    monkeypatch.setattr(rig_service.mia, "installed", lambda: True)
    monkeypatch.setattr(rig_service.mia, "python_path", lambda: Path("/fake/mia/python"))
    monkeypatch.setattr(rig_service.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(rig_service, "JOBS_DIR", tmp_path / "jobs")
    seen = {}

    def popen(command, **kwargs):
        command = [str(part) for part in command]
        if any(part.endswith("rig_worker_mia.py") for part in command):
            seen["command"] = command
            seen["env"] = kwargs["env"]
            output = Path(command[command.index("--output") + 1])
            output.write_bytes(b"glTF-fake")
            return _QuietWorker(['MAESTRO_EVENT {"phase": "predict", "progress": 0.2, "message": "Predicting"}',
                                 'MAESTRO_RESULT {"ok": true, "joint_count": 52, "animation_chain_joints": 6}'])
        # Sidecar publish shells out after the worker. Leave that call alone.
        return subprocess_popen(command, **kwargs)

    subprocess_popen = rig_service.subprocess.Popen

    monkeypatch.setattr(rig_service.subprocess, "Popen", popen)
    created = rig_service.start_job(
        body={"engine": "mia", "animations": ["idle"]}, source_path=str(source), output_dir=str(tmp_path / "out"),
    )
    request = rig_service._jobs[created["job_id"]]["request"]
    assert request["rig_profile"] == "humanoid"
    assert request["engine"] == "mia"
    rig_service._run_job_serialized(created["job_id"], str(tmp_path / "out"))
    assert seen["command"][1].endswith("rig_worker_mia.py")
    assert seen["env"]["HF_HUB_OFFLINE"] == "1"
    # Inherited HF_HOME is fine. This job must not retarget the cache into app/ckpts.
    assert seen["env"].get("HF_HOME") != str(rig_service.HF_CACHE_DIR)
    done = rig_service.get_job(created["job_id"])
    assert done["status"] == "completed"
    assert done["joint_count"] == 52


def test_worker_bakes_clips_onto_a_fake_prediction(tmp_path, monkeypatch):
    from tests.test_glb_cleanup import write_skinned_glb

    source = tmp_path / "hero.glb"
    source.write_bytes(b"glb")
    output = tmp_path / "rigged.glb"

    def fake_predict(_source, destination, _seed):
        write_skinned_glb(destination, False)

    monkeypatch.setattr(rig_worker_mia, "predict_rest_glb", fake_predict)
    rig_worker_mia.run(
        {"source": str(source), "animations": ["idle"], "rig_profile": "humanoid", "animation_bpm": 120, "seed": 3},
        output,
    )
    import pygltflib
    gltf = pygltflib.GLTF2().load(str(output))
    assert gltf.skins and gltf.skins[0].joints
    assert any(animation.name == "Idle Sway" for animation in gltf.animations)


def _refuse(monkeypatch, tmp_path, engine, lines):
    source = tmp_path / "hero.glb"
    source.write_bytes(b"glb")
    job_id = f"mia-refusal-{engine}-{abs(hash(tuple(lines))) % 10**8}"
    monkeypatch.setattr(rig_service, "installation_status", lambda: {"installed": True, "install_hint": None})
    monkeypatch.setattr(rig_service.uuid, "uuid4", lambda: SimpleNamespace(hex=job_id))
    monkeypatch.setattr(rig_service.threading, "Thread", _DeferredThread)
    monkeypatch.setattr(rig_service, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(rig_service, "_python_path", lambda: Path("/fake/python"))
    monkeypatch.setattr(rig_service.subprocess, "Popen", lambda *_a, **_k: _QuietWorker(lines))
    body = {"engine": engine, "animations": ["idle"]}
    rig_service.start_job(body=body, source_path=str(source), output_dir=str(tmp_path / "out"), workspace="studio")
    rig_service._run_job_serialized(job_id, str(tmp_path / "out"))
    return rig_service.get_job(job_id)


def test_humanoid_refusal_is_unchanged_when_mia_is_not_installed(tmp_path, monkeypatch):
    failed = _refuse(monkeypatch, tmp_path, "humanoid",
                     ['MAESTRO_RESULT {"ok": false, "error": "not_humanoid", "reason": "turned"}'])
    assert failed["error"] == "not_humanoid: the model is turned at an angle. Use a model facing the camera straight on."
    assert failed["error_code"] == "not_humanoid"
    assert "suggested_engine" not in failed


@pytest.mark.parametrize("reason", ["turned", "hands_stuck", "not_upright"])
def test_installed_mia_is_suggested_for_the_three_pose_refusals(tmp_path, monkeypatch, reason):
    monkeypatch.setattr(rig_service.mia, "installed", lambda: True)
    failed = _refuse(monkeypatch, tmp_path, "humanoid",
                     [f'MAESTRO_RESULT {{"ok": false, "error": "not_humanoid", "reason": "{reason}"}}'])
    assert failed["suggested_engine"] == "mia"
    assert "was not switched" in failed["error"]
    assert failed["error_reason"] == reason
    assert failed["engine"] == "humanoid"


def test_other_refusals_and_other_engines_do_not_suggest_mia(tmp_path, monkeypatch):
    monkeypatch.setattr(rig_service.mia, "installed", lambda: True)
    arms = _refuse(monkeypatch, tmp_path, "humanoid",
                   ['MAESTRO_RESULT {"ok": false, "error": "not_humanoid", "reason": "arms_raised"}'])
    assert "suggested_engine" not in arms
    procedural = _refuse(monkeypatch, tmp_path, "procedural",
                         ['MAESTRO_RESULT {"ok": false, "error": "not_humanoid", "reason": "turned"}'])
    assert "suggested_engine" not in procedural
    assert "was not switched" not in procedural["error"]


def test_reaper_recognizes_only_this_installs_mia_worker(tmp_path):
    request = tmp_path / "job.json"
    request.write_text("{}", encoding="utf-8")
    cmdline = f"python {mia.WORKER_PATH} --request {request} --output {tmp_path / 'out.glb'}"
    assert rig_service._cmdline_is_rig_worker(cmdline, request)
    assert not rig_service._cmdline_is_rig_worker(f"python {mia.WORKER_PATH} --output out.glb", request)


def test_mia_tasks_take_the_gpu_lane_and_humanoid_stays_on_cpu(monkeypatch):
    captured = {}

    def remember(_workspace, _task_id, **fields):
        captured.update(fields)
        return fields

    monkeypatch.setattr(canonical_task_publishers, "_upsert_canonical_task", remember)
    canonical_task_publishers._publish_generic_legacy_task(
        {"job_id": "j-mia", "engine": "mia", "status": "queued"}, "rig",
    )
    assert captured["resource_requirements"] == [resource_scheduler.local_gpu_lane(0).key]
    canonical_task_publishers._publish_generic_legacy_task(
        {"job_id": "j-human", "engine": "humanoid", "status": "queued"}, "rig",
    )
    assert captured["resource_requirements"] == [resource_scheduler.cpu_lane("rig").key]


def test_mcp_and_the_wizard_share_the_mia_engine():
    submit = command_catalog()[0]
    enum = submit["inputSchema"]["properties"]["input"]["properties"]["engine"]["enum"]
    assert enum == ["unirig", "procedural", "humanoid", "mia", "meshy"]
    launch = (ROOT / "app/_launch_runtime.py").read_text(encoding="utf-8")
    assert "model3d_rig_catalog" in launch
    assert "suggested_engine" in submit["description"]
