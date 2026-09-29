"""Provider-free contracts: no installed model, network or CUDA required."""
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.asset_manifest import read_asset_manifest
from app.services import model3d_external as engines
from app.services import model3d_service as service


@pytest.mark.parametrize("model_id", ["trellis2", "pixal3d"])
def test_external_request_uses_native_materials_and_durable_model_identity(model_id):
    request = service._prepare_request({"model_id": model_id}, {"front": "/image.png"})
    assert request["model"]["id"] == model_id
    assert request["settings"]["texture_mode"] == "native-pbr"
    assert request["settings"]["output_format"] == "glb"
    assert request["settings"]["resolution"] == 1024
    assert "octree_resolution" not in request["settings"]


@pytest.mark.parametrize("body,images", [
    ({}, {}),
    ({}, {"front": "front.png", "left": "left.png"}),
    ({"prompt": "ignored text"}, {"front": "front.png"}),
    ({"operation": "retexture"}, {"front": "front.png"}),
    ({"texture_mode": "v2-turbo"}, {"front": "front.png"}),
    ({"output_format": "obj"}, {"front": "front.png"}),
    ({"octree_resolution": 256}, {"front": "front.png"}),
    ({"resolution": 768}, {"front": "front.png"}),
    ({"seed": True}, {"front": "front.png"}),
    ({"low_vram": "false"}, {"front": "front.png"}),
    ({"camera_fov": float("nan")}, {"front": "front.png"}),
])
@pytest.mark.parametrize("model_id", ["trellis2", "pixal3d"])
def test_rejects_inputs_that_would_be_silently_ignored(model_id, body, images):
    with pytest.raises(ValueError):
        service._prepare_request({"model_id": model_id, **body}, images)


def test_engine_specific_controls():
    for settings in ({"low_vram": True}, {"camera_fov": 0.2}):
        with pytest.raises(ValueError):
            service._prepare_request({"model_id": "trellis2", **settings}, {"front": "x"})
    request = service._prepare_request(
        {"model_id": "pixal3d", "low_vram": True, "camera_fov": 0.2}, {"front": "x"},
    )
    assert request["settings"]["camera_fov"] == 0.2


def test_runtime_is_per_engine_and_configuration_is_not_gpu_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(engines.sys, "platform", "linux")
    root = tmp_path / "pixal"
    root.mkdir()
    (root / "inference.py").touch()
    python = root / "python"
    python.touch(mode=0o755)
    monkeypatch.setenv("HOCUSPOCUS_PIXAL3D_ROOT", str(root))
    monkeypatch.setenv("HOCUSPOCUS_PIXAL3D_PYTHON", str(python))
    status = engines.installation_status("pixal3d")
    assert status["installed"]
    assert status["validation"] == "configured_not_gpu_validated"
    python.unlink()
    assert not engines.installation_status("pixal3d")["installed"]


def _worker(monkeypatch):
    monkeypatch.syspath_prepend(str(engines.WORKER.parent))
    spec = importlib.util.spec_from_file_location("external3d_test_worker", engines.WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pixal_adapter_passes_its_inputs_without_a_child_process(monkeypatch, tmp_path):
    worker = _worker(monkeypatch)
    calls = []
    monkeypatch.setattr(worker.runpy, "run_path", lambda *a, **k: {"run_inference": lambda **kw: calls.append(kw)})
    request = service._prepare_request({"model_id": "pixal3d", "camera_fov": 0.2, "seed": 7}, {"front": "x"})
    worker.run_pixal(request, tmp_path / "asset.glb", tmp_path)
    assert calls == [{"image_path": "x", "output_path": str(tmp_path / "asset.glb"),
                      "seed": 7, "model_path": "TencentARC/Pixal3D", "low_vram": True,
                      "resolution": 1024, "manual_fov": 0.2}]


def test_trellis_adapter_passes_seed_resolution_and_pbr(monkeypatch, tmp_path):
    from PIL import Image
    worker = _worker(monkeypatch)
    image = tmp_path / "input.png"
    Image.new("RGB", (8, 8)).save(image)
    calls = {}
    mesh = SimpleNamespace(vertices=[], faces=[], attrs=[], coords=[], layout={}, voxel_size=1,
                           simplify=lambda count: None)
    def run(img, **kwargs):
        calls.update(kwargs)
        return [mesh]
    pipeline = SimpleNamespace(cuda=lambda: None, run=run)
    monkeypatch.setitem(sys.modules, "trellis2", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "trellis2.pipelines", SimpleNamespace(
        Trellis2ImageTo3DPipeline=SimpleNamespace(from_pretrained=lambda repo: pipeline)))
    exports = []
    monkeypatch.setitem(sys.modules, "o_voxel", SimpleNamespace(postprocess=SimpleNamespace(
        to_glb=lambda **kw: SimpleNamespace(export=lambda *a, **k: exports.append((a, k))))))
    request = service._prepare_request({"model_id": "trellis2", "resolution": 512, "seed": 8}, {"front": str(image)})
    worker.run_trellis(request, tmp_path / "asset.glb")
    assert calls == {"seed": 8, "pipeline_type": "512"}
    assert exports[0][1] == {"extension_webp": True}


@pytest.mark.parametrize("model_id", ["trellis2", "pixal3d"])
def test_job_dispatches_isolated_worker_and_publishes_actual_engine(monkeypatch, tmp_path, model_id):
    commands = []
    real_popen = service.subprocess.Popen
    class Process:
        pid = 123456789
        stdout = io.StringIO("")
        def poll(self):
            return 0
        def wait(self, **kwargs):
            return 0
    def spawn(command, **kwargs):
        if "--output" not in command:
            return real_popen(command, **kwargs)
        commands.append((command, kwargs))
        Path(command[command.index("--output") + 1]).write_bytes(b"glTF-fake-contract-output")
        return Process()
    monkeypatch.setattr(service, "_active_profile", lambda: {})
    monkeypatch.setattr(service.threading, "Thread", lambda **kw: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(service.subprocess, "Popen", spawn)
    monkeypatch.setattr(service, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(service, "HF_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(engines, "installation_status", lambda engine: {"installed": True})
    monkeypatch.setattr(engines, "runtime_paths", lambda engine: (tmp_path, tmp_path / "isolated-python"))
    created = service.start_job(body={"provider": "local", "model_id": model_id},
                                image_paths={"front": "reference.png"}, output_dir=str(tmp_path / "outputs"))
    job_id = created["job_id"]
    try:
        service._run_job_serialized(job_id, str(tmp_path / "outputs"))
        job = service.get_job(job_id)
        assert job["status"] == "completed", job
        assert commands[0][0][0] == str(tmp_path / "isolated-python")
        assert commands[0][0][1] == str(engines.WORKER)
        assert commands[0][1]["cwd"] == str(tmp_path)
        output = tmp_path / "outputs" / job["filename"]
        sidecar = json.loads(output.with_suffix(".meta.json").read_text())
        assert sidecar["params"]["provider"] == model_id
        assert sidecar["params"]["model_id"] == model_id
        assert sidecar["params"]["model_repo"] == service.MODEL_BY_ID[model_id]["repo"]
        assert read_asset_manifest(output)["execution"]["task_id"] == created["task_id"]
        assert not (tmp_path / "jobs" / f"{job_id}.json").exists()
    finally:
        service._jobs.pop(job_id, None)


@pytest.mark.parametrize("model_id,provider,repo", [
    ("trellis2", "trellis2", "microsoft/TRELLIS.2-4B"),
    ("pixal3d", "pixal3d", "TencentARC/Pixal3D"),
    ("hunyuan3d-2-turbo", "hunyuan3d", "tencent/Hunyuan3D-2"),
])
def test_simulated_job_publishes_selected_engine_identity(monkeypatch, tmp_path, model_id, provider, repo):
    monkeypatch.setattr(
        service.execution_mode,
        "POLICY",
        SimpleNamespace(simulated=True, fail_kind="", fail_count=1, step_delay=0.0),
    )
    request = service._prepare_request({"model_id": model_id}, {"front": "reference.png"})
    job_id = f"sim-{model_id}"
    service._jobs[job_id] = {
        "job_id": job_id,
        "task_id": service._canonical_task_id(job_id),
        "root_task_id": service._canonical_task_id(job_id),
        "status": "waiting_resource",
        "progress": 0,
        "request": request,
        "updated_at": 0,
    }
    try:
        service._run_job_serialized(job_id, str(tmp_path))
        job = service._jobs[job_id]
        assert job["status"] == "completed"
        assert job["simulated"] is True
        sidecar = json.loads((tmp_path / job["filename"]).with_suffix(".meta.json").read_text())
        assert sidecar["params"]["provider"] == provider
        assert sidecar["params"]["model_id"] == model_id
        assert sidecar["params"]["model_repo"] == repo
        loaded = read_asset_manifest(tmp_path / job["filename"])
        assert loaded["generation"]["model"]["provider"] == provider
        assert loaded["generation"]["model"]["id"] == model_id
        assert loaded["generation"]["parameters"]["model_repo"] == repo
    finally:
        service._jobs.pop(job_id, None)
