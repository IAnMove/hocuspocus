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
from app.services.runtime_profiles import select_profiles
from app.services.trellis2 import assets


def test_cuda_link_stubs_never_leak_into_the_runtime_loader_path(tmp_path):
    from app.services.trellis2.install_native import build_environment
    stubs = tmp_path / "lib/stubs"
    stubs.mkdir(parents=True)
    (stubs / "libcuda.so").touch()
    original = {"LD_LIBRARY_PATH": "/host/driver", "LIBRARY_PATH": "/other/build/libs"}
    result = build_environment(tmp_path, original)
    assert result["LD_LIBRARY_PATH"] == original["LD_LIBRARY_PATH"]
    assert str(stubs) in result["LIBRARY_PATH"]
    assert result["CUDA_HOME"] == str(tmp_path)
    assert "CUDA_HOME" not in original


@pytest.mark.parametrize("platform,gpu,compute,memory,supported", [
    ("linux", "nvidia", "8.9", 24564, True),
    ("linux", "nvidia", "8.0", 81920, True),
    ("linux", "nvidia", "9.0", 81920, True),
    ("win32", "nvidia", "8.9", 24564, False),
    ("darwin", "amd", None, None, False),
    ("linux", "amd", None, 24576, False),
    ("linux", "nvidia", "8.6", 16384, False),
    ("linux", "nvidia", "7.5", 24576, False),
    ("linux", "nvidia", "10.0", 32768, False),
    ("linux", "nvidia", None, 24576, False),
    ("linux", "nvidia", "8.9", None, False),
])
def test_optional_trellis_hardware_contract(platform, gpu, compute, memory, supported):
    result = select_profiles(platform, "x64", gpu, "580.82.09", compute, memory)
    engine = result["engines"]["trellis2"]
    assert engine["supported"] is supported
    assert engine["defaultInstall"] is False
    assert engine["env"] != result["engines"]["wangp"]["env"]
    if not supported:
        assert engine["reason"]


def test_trellis_download_receipt_rejects_partial_changed_and_escaping_files(tmp_path):
    assert not assets.downloaded(tmp_path)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    config = bundle / "pipeline.json"
    config.write_bytes(b"{}")
    weight = tmp_path / "weight.safetensors"
    weight.write_bytes(b"12345")
    receipt = {"revisions": {repo: value[0] for repo, value in assets.REPOSITORIES.items()},
               "files": {"bundle/pipeline.json": 2, "weight.safetensors": 5}}
    manifest = tmp_path / "complete.json"
    manifest.write_text(json.dumps(receipt))
    assert assets.downloaded(tmp_path)
    weight.write_bytes(b"123")
    assert not assets.downloaded(tmp_path)
    weight.write_bytes(b"12345")
    receipt["revisions"]["microsoft/TRELLIS.2-4B"] = "main"
    manifest.write_text(json.dumps(receipt))
    assert not assets.downloaded(tmp_path)
    receipt["revisions"] = {repo: value[0] for repo, value in assets.REPOSITORIES.items()}
    outside = tmp_path.parent / "outside.safetensors"
    outside.write_bytes(b"1")
    receipt["files"] = {"bundle/pipeline.json": 2, "../outside.safetensors": 1}
    manifest.write_text(json.dumps(receipt))
    assert not assets.downloaded(tmp_path)


@pytest.mark.parametrize("field", ["compatible", "weights_downloaded"])
def test_trellis_job_refused_before_queue_if_incompatible_or_not_downloaded(monkeypatch, tmp_path, field):
    monkeypatch.setattr(service, "_active_profile", lambda: {})
    monkeypatch.setattr(engines, "installation_status", lambda engine: {
        "installed": True, "compatible": True, "weights_downloaded": True,
        field: False, "install_hint": "Download or install compatible TRELLIS.2 first",
    })
    initial = set(service._jobs)
    with pytest.raises(RuntimeError, match="compatible TRELLIS"):
        service.start_job(body={"provider": "local", "model_id": "trellis2"},
                          image_paths={"front": "x"}, output_dir=str(tmp_path))
    assert set(service._jobs) == initial


def test_official_download_gates_access_before_any_large_snapshot(monkeypatch, tmp_path):
    hub = pytest.importorskip("huggingface_hub")
    from huggingface_hub.errors import GatedRepoError
    downloads = []
    monkeypatch.setattr(hub, "HfApi", lambda: SimpleNamespace(model_info=lambda repo, **k:
        SimpleNamespace(siblings=[SimpleNamespace(rfilename=("ckpts/ss_dec_conv3d_16l8_fp16.safetensors" if repo == "microsoft/TRELLIS-image-large" else "ckpts/model.safetensors" if repo == "microsoft/TRELLIS.2-4B" else "model.safetensors"), size=10)])))
    def metadata(url, **kwargs):
        if "dinov3" in url:
            raise GatedRepoError("gated")
    monkeypatch.setattr(hub, "get_hf_file_metadata", metadata)
    monkeypatch.setattr(hub, "snapshot_download", lambda *a, **k: downloads.append(a))
    with pytest.raises(RuntimeError, match="Accept their Hugging Face access terms"):
        assets.download(tmp_path)
    assert downloads == []
    assert not assets.downloaded(tmp_path)


def test_official_download_builds_complete_local_pipeline_and_repairs_truncation(monkeypatch, tmp_path):
    hub = pytest.importorskip("huggingface_hub")
    inventories = {}
    for repo, (revision, _) in assets.REPOSITORIES.items():
        folder = tmp_path / "hub" / ("models--" + repo.replace("/", "--")) / "snapshots" / revision
        folder.mkdir(parents=True)
        weight_name = "ckpts/ss_dec_conv3d_16l8_fp16.safetensors" if repo == "microsoft/TRELLIS-image-large" else "ckpts/model.safetensors" if repo == "microsoft/TRELLIS.2-4B" else "model.safetensors"
        files = {weight_name: b"weights"}
        if repo == "microsoft/TRELLIS.2-4B":
            config = {"args": {"models": {"decoder": "microsoft/TRELLIS-image-large/ckpts/decoder", "flow": "ckpts/flow"},
                               "image_cond_model": {"args": {}}, "rembg_model": {"args": {}}}}
            files["pipeline.json"] = json.dumps(config).encode()
        for name, data in files.items():
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(data)
        inventories[repo] = (folder, files)
    monkeypatch.setattr(hub, "HfApi", lambda: SimpleNamespace(model_info=lambda repo, **k: SimpleNamespace(
        siblings=[SimpleNamespace(rfilename=name, size=len(data)) for name, data in inventories[repo][1].items()])))
    monkeypatch.setattr(hub, "get_hf_file_metadata", lambda *a, **k: None)
    def snapshot(repo, **kwargs):
        folder, files = inventories[repo]
        for name, data in files.items():
            (folder / name).parent.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(data)
        assert kwargs["revision"] == assets.REPOSITORIES[repo][0]
        return str(folder)
    monkeypatch.setattr(hub, "snapshot_download", snapshot)
    assets.download(tmp_path)
    assert assets.downloaded(tmp_path)
    config = json.loads((tmp_path / "bundle/pipeline.json").read_text())["args"]
    assert config["models"]["decoder"] == str(inventories["microsoft/TRELLIS-image-large"][0] / "ckpts/decoder")
    assert config["image_cond_model"]["args"]["model_name"] == str(inventories["facebook/dinov3-vitl16-pretrain-lvd1689m"][0])
    weight = inventories["microsoft/TRELLIS.2-4B"][0] / "ckpts/model.safetensors"
    weight.write_bytes(b"short")
    assert not assets.downloaded(tmp_path)
    assets.download(tmp_path)
    assert assets.downloaded(tmp_path)


def _catalog_routes(monkeypatch):
    # Only trusted functions from this repository are executed against doubles;
    # request data never provides source code or the extraction path.
    import ast
    import threading
    from fastapi import HTTPException
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "app/_launch_runtime.py").read_text())
    names = {"download_model", "delete_model"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    monkeypatch.setitem(sys.modules, "services.model3d_external", engines)
    namespace = {"HTTPException": HTTPException, "threading": SimpleNamespace(Thread=lambda **k: SimpleNamespace(start=lambda: None)),
                 "_model_downloads_lock": threading.RLock(), "_model_downloads": {}, "time": SimpleNamespace(time=lambda: 1)}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "catalog-routes", "exec"), namespace)
    return namespace


def test_catalog_download_uses_official_route_without_a_wangp_model_definition(monkeypatch):
    routes = _catalog_routes(monkeypatch)
    monkeypatch.setattr(engines, "installation_status", lambda engine: {"installed": True, "compatible": True})
    assert routes["download_model"]("trellis2")["status"] == "downloading"
    assert routes["download_model"]("trellis2")["status"] == "downloading"
    assert len(routes["_model_downloads"]) == 1
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        routes["delete_model"]("trellis2")
    assert error.value.status_code == 409


def test_catalog_refuses_download_on_an_incompatible_machine(monkeypatch):
    from fastapi import HTTPException
    routes = _catalog_routes(monkeypatch)
    monkeypatch.setattr(engines, "installation_status", lambda engine: {
        "installed": False, "compatible": False, "install_hint": "Linux NVIDIA 24GB required"})
    with pytest.raises(HTTPException) as error:
        routes["download_model"]("trellis2")
    assert error.value.status_code == 409
    assert routes["_model_downloads"] == {}


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
