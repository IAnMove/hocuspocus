"""Portable regression checks for side-by-side Windows CUDA build tools."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("windows_toolchain", ROOT / "scripts/windows_toolchain.py")
toolchain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(toolchain)


def add_toolset(root, version):
    vcvars = root / "VC/Auxiliary/Build/vcvarsall.bat"
    vcvars.parent.mkdir(parents=True, exist_ok=True)
    vcvars.touch()
    compiler = root / "VC/Tools/MSVC" / version / "bin/Hostx64/x64/cl.exe"
    compiler.parent.mkdir(parents=True, exist_ok=True)
    compiler.touch()
    return compiler


def test_newest_visual_studio_does_not_override_compatible_side_by_side_tools(tmp_path):
    old = tmp_path / "VS 2019"
    new = tmp_path / "VS 18"
    add_toolset(new, "14.51.36231")
    add_toolset(old, "14.29.30133")
    add_toolset(new, "14.39.33519")
    result = toolchain.compatible_toolsets([old, new])
    assert [item[0] for item in result] == ["14.39.33519", "14.29.30133"]
    assert result[1][2].name == "cl.exe"


def test_incomplete_or_incompatible_toolset_is_not_selected(tmp_path):
    compiler = add_toolset(tmp_path, "14.29.30133")
    compiler.unlink()
    add_toolset(tmp_path, "14.51.36231")
    assert toolchain.compatible_toolsets([tmp_path]) == []


@pytest.fixture
def windows_build(tmp_path, monkeypatch):
    cuda = tmp_path / "CUDA toolkit"
    (cuda / "bin").mkdir(parents=True)
    (cuda / "include").mkdir()
    (cuda / "include/cuda.h").touch()
    nvcc = cuda / "bin/nvcc.exe"
    nvcc.touch()
    vs = tmp_path / "VS"
    add_toolset(vs, "14.29.30133")
    monkeypatch.setattr(toolchain.sys, "platform", "win32")
    monkeypatch.setattr(toolchain.shutil, "which", lambda *a, **kw: str(nvcc))
    monkeypatch.setattr(toolchain, "installations", lambda env: [vs])
    monkeypatch.setattr(toolchain.subprocess, "run", lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, "Cuda compilation tools, release 12.8, V12.8.93"))
    monkeypatch.setattr(toolchain, "activate", lambda *a:
                        {"PATH": "engine-bin", "INCLUDE": "sdk-include", "LIB": "sdk-lib"})
    return cuda


@pytest.mark.parametrize("layout", ["lib", "lib/x64"])
def test_conda_and_nvidia_toolkit_layouts_both_reach_the_linker(windows_build, layout):
    lib = windows_build / layout
    lib.mkdir(parents=True)
    (lib / "cudart.lib").touch()
    env = toolchain.build_environment({"PATH": "pinokio-tools"})
    assert env["LIB"].startswith(str(lib))
    assert env["CUDA_HOME"] == str(windows_build)
    assert env["DISTUTILS_USE_SDK"] == "1"
    assert env["PATH"].endswith("engine-bin")
    assert "14.29.30133" in env["NVCC_CCBIN"]


def test_missing_compiler_reports_actionable_recovery(windows_build, monkeypatch):
    (windows_build / "lib").mkdir()
    (windows_build / "lib/cudart.lib").touch()
    monkeypatch.setattr(toolchain, "installations", lambda env: [])
    with pytest.raises(RuntimeError, match="VS 2019 MSVC v142"):
        toolchain.build_environment({})


def test_mismatched_cuda_is_rejected_before_compilation(windows_build, monkeypatch):
    monkeypatch.setattr(toolchain.subprocess, "run", lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, "Cuda compilation tools, release 13.0, V13.0.0"))
    with pytest.raises(RuntimeError, match="requires CUDA Toolkit 12.8"):
        toolchain.build_environment({})


def test_activation_clears_previous_visual_studio_and_preserves_engine(monkeypatch):
    def run(command, **kwargs):
        assert '-vcvars_ver=14.29.30133' in command
        assert '/u' in command and kwargs['encoding'] == 'utf-16le'
        env = kwargs["env"]
        assert "VSCMD_VER" not in env and "INCLUDE" not in env
        assert env["PATH"] == "engine-bin"
        return subprocess.CompletedProcess(command, 0, "Path=selected-tools;engine-bin\nINCLUDE=sdk\nLIB=sdk-lib\n")
    monkeypatch.setattr(toolchain.subprocess, "run", run)
    result = toolchain.activate(Path("VS tools/vcvarsall.bat"), "14.29.30133",
                                {"VSCMD_VER": "18", "INCLUDE": "wrong-sdk", "PATH": "engine-bin"})
    assert result["PATH"] == "selected-tools;engine-bin"
    assert result["INCLUDE"] == "sdk"


def test_other_platforms_cannot_accidentally_run_msvc(monkeypatch):
    monkeypatch.setattr(toolchain.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="Windows-only"):
        toolchain.build_environment({})


def test_dimension_fix_only_changes_temporary_build_source(tmp_path):
    original = tmp_path / "vendor"
    relative = Path("lib/custom_rasterizer_kernel/grid_neighbor.cpp")
    (original / relative).parent.mkdir(parents=True)
    text = "torch::zeros({items.size() / 3, 3}, options);\n" * 13
    (original / relative).write_text(text)
    gpu = original / relative.parent / "rasterizer_gpu.cu"
    gpu.write_text("long* p = t.data_ptr<long>(); auto z = (long)maxint;\n")
    destination = tmp_path / "build copy"
    toolchain.prepare_rasterizer(original, destination)
    fixed = (destination / relative).read_text()
    assert fixed.count("static_cast<int64_t>(items.size() / 3)") == 13
    assert ", 3}" in fixed
    assert (original / relative).read_text() == text
    assert (destination / relative.parent / gpu.name).read_text() == (
        "int64_t* p = t.data_ptr<int64_t>(); auto z = (int64_t)maxint;\n")
    assert "data_ptr<long>()" in gpu.read_text()


def test_dimension_fix_rejects_unexpected_upstream_changes(tmp_path):
    source = tmp_path / "vendor"
    cpp = source / "lib/custom_rasterizer_kernel/grid_neighbor.cpp"
    cpp.parent.mkdir(parents=True)
    cpp.write_text("// different upstream implementation\n")
    with pytest.raises(RuntimeError, match="source changed"):
        toolchain.prepare_rasterizer(source, tmp_path / "build")
    assert not (tmp_path / "build").exists()
