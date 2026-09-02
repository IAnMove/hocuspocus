import ast
import importlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
import wave
from types import SimpleNamespace

import pytest

from services import execution_mode
from services.asset_manifest import SCHEMA_NAME, publish_generation_sidecar, read_asset_manifest


def _load_launch_function(name, namespace):
    source = (Path(__file__).parents[1] / "app" / "_launch_runtime.py").read_text(
        encoding="utf-8",
    )
    tree = ast.parse(source, filename="app/_launch_runtime.py")
    function = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    exec(
        compile(ast.Module(body=[function], type_ignores=[]), "app/_launch_runtime.py", "exec"),
        namespace,
    )
    return namespace[name]


@pytest.fixture(autouse=True)
def restore_execution_policy(monkeypatch):
    original = dict(execution_mode.os.environ)
    yield
    for name in (
        execution_mode.MODE_ENV,
        execution_mode.WORKSPACE_ENV,
        execution_mode.ALLOW_PAID_ENV,
        execution_mode.STEP_DELAY_ENV,
        execution_mode.FAIL_KIND_ENV,
        execution_mode.FAIL_COUNT_ENV,
    ):
        if name in original:
            monkeypatch.setenv(name, original[name])
        else:
            monkeypatch.delenv(name, raising=False)
    importlib.reload(execution_mode)


def load_policy(monkeypatch, mode="simulate", **values):
    monkeypatch.setenv(execution_mode.MODE_ENV, mode)
    monkeypatch.setenv(execution_mode.WORKSPACE_ENV, "e2e_wizard")
    monkeypatch.setenv(execution_mode.STEP_DELAY_ENV, "0")
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return importlib.reload(execution_mode)


def test_simulation_is_boot_locked_and_workspace_isolated(monkeypatch):
    module = load_policy(monkeypatch)
    assert module.policy().public_dict() == {
        "mode": "simulate",
        "workspace": "e2e_wizard",
        "allow_paid": False,
        "step_delay": 0.0,
        "simulated": True,
        "locked_at_boot": True,
    }
    module.validate_generation("e2e_wizard")
    with pytest.raises(module.ExecutionModeError, match="isolated"):
        module.validate_generation("default")
    with pytest.raises(module.ExecutionModeError, match="disabled"):
        module.validate_remote_provider("e2e_wizard", "minimax")


def test_plan_mode_stops_before_queue(monkeypatch):
    module = load_policy(monkeypatch, "plan")
    with pytest.raises(module.ExecutionModeError, match="stops before queue"):
        module.validate_generation("e2e_wizard")


@pytest.mark.parametrize(
    ("generation_mode", "extension"),
    [("image", ".png"), ("audio", ".wav"), ("3d", ".glb")],
)
def test_simulated_executor_writes_valid_chainable_artifacts(
    monkeypatch, tmp_path, generation_mode, extension,
):
    module = load_policy(monkeypatch)
    progress = []
    output = module.create_artifact(
        {"generation_mode": generation_mode},
        str(tmp_path),
        "job123",
        progress=lambda *values: progress.append(values),
    )
    assert output.endswith(extension)
    assert progress[-1][1:] == (92, 4, 4)
    data = tmp_path.joinpath(output.rsplit("/", 1)[-1]).read_bytes()
    if extension == ".png":
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
    elif extension == ".wav":
        with wave.open(output, "rb") as audio:
            assert audio.getnframes() > 0
    else:
        magic, version, length = struct.unpack("<4sII", data[:12])
        assert (magic, version, length) == (b"glTF", 2, len(data))
        assert json.loads(data[20:].decode().rstrip()) == {
            "asset": {"version": "2.0", "generator": "HocusPocus simulation"}
        }


def test_failure_injection_is_kind_specific(monkeypatch, tmp_path):
    module = load_policy(
        monkeypatch,
        HOCUSPOCUS_SIMULATION_FAIL_KIND="audio",
    )
    with pytest.raises(RuntimeError, match="Injected simulated audio"):
        module.create_artifact({"generation_mode": "audio"}, str(tmp_path), "fail")
    assert module.create_artifact(
        {"generation_mode": "audio"}, str(tmp_path), "retry",
    ).endswith(".wav")
    assert module.create_artifact(
        {"generation_mode": "image"}, str(tmp_path), "ok",
    ).endswith(".png")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_simulated_video_is_a_decodable_mp4(monkeypatch, tmp_path):
    module = load_policy(monkeypatch)
    output = module.create_artifact(
        {"generation_mode": "video"}, str(tmp_path), "video",
    )
    with open(output, "rb") as handle:
        assert handle.read(12)[4:8] == b"ftyp"
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", output],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "duration=" in result.stdout


def test_model3d_worker_uses_the_same_simulation_boundary(monkeypatch, tmp_path):
    module = load_policy(monkeypatch)
    from services import model3d_service

    monkeypatch.setattr(model3d_service.execution_mode, "POLICY", module.policy())
    job_id = "model3d-simulated"
    model3d_service._jobs[job_id] = {
        "job_id": job_id,
        "status": "waiting_resource",
        "progress": 0,
        "request": {"settings": {"output_format": "glb"}},
        "updated_at": 0,
    }
    try:
        model3d_service._run_job_serialized(job_id, str(tmp_path))
        job = model3d_service._jobs[job_id]
        assert job["status"] == "completed"
        assert job["simulated"] is True
        assert (tmp_path / job["filename"]).read_bytes().startswith(b"glTF")
    finally:
        model3d_service._jobs.pop(job_id, None)


def test_director_minimax_frame_is_simulated_without_a_provider_call(monkeypatch, tmp_path):
    module = load_policy(monkeypatch)
    from services import director_pipeline

    monkeypatch.setattr(execution_mode, "POLICY", module.policy())
    output = director_pipeline._generate_minimax_director_image(
        prompt="a simulated enchanted server room",
        resolution="1280x720",
        output_dir=str(tmp_path),
        reference_paths=[],
    )
    assert (tmp_path / output).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_simulated_worker_returns_cleanly_when_artifact_creation_is_cancelled(tmp_path):
    def cancelled_artifact(*_args, **_kwargs):
        raise InterruptedError("Simulated generation cancelled")

    namespace = {
        "execution_mode": SimpleNamespace(create_artifact=cancelled_artifact),
        "update_job": lambda *_args, **_kwargs: True,
        "is_cancel_requested": lambda _job: True,
    }
    worker = _load_launch_function("_run_simulated_generation", namespace)
    job = {
        "id": "cancelled-simulation",
        "out_dir": str(tmp_path),
        "params": {"generation_mode": "video"},
    }

    assert worker(job, finalize=True) is False
    assert list(tmp_path.iterdir()) == []


def test_simulated_generation_writes_canonical_asset_manifest(tmp_path):
    artifact = tmp_path / "clip.mp4"

    def create_artifact(*_args, **_kwargs):
        artifact.write_bytes(b"video")
        return str(artifact)

    recorded = []
    namespace = {
        "execution_mode": SimpleNamespace(create_artifact=create_artifact),
        "update_job": lambda *_args, **_kwargs: True,
        "is_cancel_requested": lambda _job: False,
        "record_job_outputs": lambda _job, names: recorded.extend(names),
        "finish_job": lambda *_args, **_kwargs: True,
        "publish_generation_sidecar": publish_generation_sidecar,
        "os": os,
        "time": time,
    }
    worker = _load_launch_function("_run_simulated_generation", namespace)
    job = {
        "id": "sim-job-1",
        "out_dir": str(tmp_path),
        "workspace": "night-shift",
        "task_id": "task-1",
        "root_task_id": "task-1",
        "params": {
            "generation_mode": "video",
            "prompt": "un coro en la sala de servidores",
            "model_type": "minimax_h3",
        },
    }

    assert worker(job, finalize=True) is True
    assert recorded == ["clip.mp4"]
    sidecar = tmp_path / "clip.meta.json"
    raw = json.loads(sidecar.read_text(encoding="utf-8"))
    loaded = read_asset_manifest(artifact, workspace_id="night-shift")
    assert raw["schema"] == SCHEMA_NAME
    assert raw["params"]["prompt"] == "un coro en la sala de servidores"
    assert raw["job_id"] == "sim-job-1"
    assert loaded is not None
    assert loaded["asset"]["kind"] == "video"
    assert loaded["origin"]["workspace_id"] == "night-shift"
    assert loaded["execution"]["mode"] == "simulate"
    assert loaded["technical"]["published_on_generate"] is True


def test_tool_sidecar_publishes_canonical_manifest_without_invented_actor(tmp_path):
    artifact = tmp_path / "clip.mp4"
    artifact.write_bytes(b"video")
    namespace = {
        "os": os,
        "time": time,
        "publish_generation_sidecar": publish_generation_sidecar,
    }
    write = _load_launch_function("_write_tool_sidecar", namespace)
    write(
        str(tmp_path),
        "clip.mp4",
        source_name="source.mp4",
        tool="upscale",
        params={"method": "flashvsr2", "api_key": "secret"},
        elapsed=1.5,
        job_id="tool-job",
        task_id="tool-task",
        workspace="lab",
    )
    loaded = read_asset_manifest(artifact, workspace_id="lab")
    raw = json.loads((tmp_path / "clip.meta.json").read_text(encoding="utf-8"))
    assert loaded is not None
    assert raw["schema"] == SCHEMA_NAME
    assert raw["params"]["edit_sub_mode"] == "upscale"
    assert "secret" not in (tmp_path / "clip.meta.json").read_text(encoding="utf-8")
    assert loaded["origin"]["tool"] == "upscale"
    assert loaded["origin"]["actor"] == "unknown"
    assert loaded["origin"]["workspace_id"] == "lab"
    assert loaded["execution"]["job_id"] == "tool-job"
    assert loaded["execution"]["task_id"] == "tool-task"
    first_id = loaded["asset"]["id"]
    write(
        str(tmp_path),
        "clip.mp4",
        source_name="source.mp4",
        tool="upscale",
        params={"method": "flashvsr2"},
        elapsed=1.5,
        job_id="tool-job",
        workspace="lab",
    )
    other = tmp_path / "clip-b.mp4"
    other.write_bytes(b"video-b")
    write(
        str(tmp_path),
        "clip-b.mp4",
        source_name="source.mp4",
        tool="revoice",
        params={"mode": "clone"},
        elapsed=2,
        job_id="tool-job-2",
        workspace="lab",
    )
    assert read_asset_manifest(artifact, workspace_id="lab")["asset"]["id"] == first_id
    assert read_asset_manifest(other, workspace_id="lab")["asset"]["id"] != first_id
    assert read_asset_manifest(other, workspace_id="lab")["origin"]["tool"] == "revoice"


@pytest.mark.parametrize(
    ("writer_name", "tool", "private_key"),
    [
        ("_write_recast_shot_aware_sidecar", "recast", "_recast_shot_temp_dir"),
        ("_write_repaint_shot_aware_sidecar", "repaint", "_repaint_shot_temp_dir"),
        ("_write_outpaint_shot_aware_sidecar", "outpaint", "_outpaint_shot_temp_dir"),
    ],
)
def test_edit_shot_sidecar_publishes_canonical_manifest_without_invented_actor(
    tmp_path, writer_name, tool, private_key,
):
    artifact = tmp_path / "clip.mp4"
    artifact.write_bytes(b"video")
    write = _load_launch_function(
        writer_name,
        {
            "os": os,
            "time": time,
            "publish_generation_sidecar": publish_generation_sidecar,
        },
    )
    job = {
        "id": f"{tool}-job",
        "workspace": "lab",
        "params": {
            "generation_mode": "video",
            "prompt": "a restored shot",
            "image_start": "/tmp/uploads/hero.png",
            "api_key": "secret",
            "_defer_output_publication": True,
            private_key: "/tmp/private-shot",
        },
    }
    shot_bundle = {
        "frame_count": 16,
        "resolved_seed": 42,
        "published_shots": [{"id": "s1"}],
        "preserve_source_audio": True,
    }
    write(job, str(artifact), shot_bundle, 1.5)
    loaded = read_asset_manifest(artifact, workspace_id="lab")
    raw = json.loads((tmp_path / "clip.meta.json").read_text(encoding="utf-8"))
    text = (tmp_path / "clip.meta.json").read_text(encoding="utf-8")
    assert loaded is not None
    assert raw["schema"] == SCHEMA_NAME
    assert private_key not in raw["params"]
    assert "_defer_output_publication" not in raw["params"]
    assert raw["params"]["video_length"] == 16
    assert raw["params"]["seed"] == 42
    assert raw["params"][f"edit_{tool}_shot_aware"] is True
    assert raw["upload_filenames"]["image_start"] == "hero.png"
    assert "secret" not in text
    assert loaded["origin"]["tool"] == tool
    assert loaded["origin"]["actor"] == "unknown"
    assert loaded["origin"]["workspace_id"] == "lab"
    assert loaded["execution"]["job_id"] == f"{tool}-job"
    first_id = loaded["asset"]["id"]
    write(job, str(artifact), shot_bundle, 1.5)
    assert read_asset_manifest(artifact, workspace_id="lab")["asset"]["id"] == first_id
    other = tmp_path / "clip-b.mp4"
    other.write_bytes(b"video-b")
    write(job, str(other), shot_bundle, 1.5)
    assert read_asset_manifest(other, workspace_id="lab")["asset"]["id"] != first_id
    assert read_asset_manifest(other, workspace_id="lab")["origin"]["tool"] == tool


def test_launch_runtime_has_one_global_policy_boundary_before_inference():
    source = (Path(__file__).parents[1] / "app" / "_launch_runtime.py").read_text(
        encoding="utf-8",
    )
    ast.parse(source)
    assert "@api.exception_handler(execution_mode.ExecutionModeError)" in source
    worker = source.split("def _run_generation(job_id:", 1)[1]
    simulated = worker.index("if execution_mode.policy().simulated:")
    native_model = worker.index("_cancel_h3_idle_release()")
    assert simulated < native_model
    specialist_routes = (
        ("async def repaint_endpoint", "async def recast_endpoint", "_run_repaint"),
        ("async def recast_endpoint", "def _outpaint_geometry", "_run_recast"),
        ("async def outpaint_endpoint", "async def blend_endpoint", "_prepare_and_run_outpaint"),
        ("async def blend_endpoint", "async def inpaint_endpoint", "_run_blend_generation"),
        ("async def tools_upscale", "async def tools_revoice", "_run_tool_upscale"),
        ("async def tools_revoice", "def _run_simulated_generation", "_run_tool_revoice"),
    )
    for start, end, real_worker in specialist_routes:
        route = source.split(start, 1)[1].split(end, 1)[0]
        assert "execution_mode.policy().simulated" in route
        assert real_worker in route
        assert "_run_generation" in route
    tree = ast.parse(source)

    def function_source(name):
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return ast.get_source_segment(source, node)
        raise AssertionError(name)

    for name in (
        "_run_simulated_generation",
        "_write_output_sidecars",
        "_run_sfx_generation",
        "_write_tool_sidecar",
        "_write_recast_shot_aware_sidecar",
        "_write_repaint_shot_aware_sidecar",
        "_write_outpaint_shot_aware_sidecar",
    ):
        body = function_source(name)
        assert "publish_generation_sidecar" in body
        assert "json.dump" not in body
    h3_slice = source.split("generated = minimax_h3_service.generate", 1)[1].split("if not finalize:", 1)[0]
    assert "publish_generation_sidecar" in h3_slice
    assert "json.dump" not in h3_slice
