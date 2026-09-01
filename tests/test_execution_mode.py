import ast
import importlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import wave

import pytest

from services import execution_mode


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
