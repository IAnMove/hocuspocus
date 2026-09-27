"""Platform selection and failure recovery without CUDA or an installed app."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from services import runtime_profiles as profiles
from services.runtime_environment import isolated_environment, python_path

ROOT = Path(__file__).resolve().parents[1]


def test_windows_and_linux_choose_distinct_main_abis():
    win = profiles.select_profiles("win32", "AMD64", "nvidia", "581.15")
    linux = profiles.select_profiles("linux", "x86_64", "nvidia", "580.82.09")
    assert win["supported"] and linux["supported"]
    assert win["engines"]["wangp"]["torch"] == "2.7.1"
    assert linux["engines"]["wangp"]["torch"] == "2.7.0"
    assert win["engines"]["wangp"]["constraints"]["xformers"] == "0.0.31.post1"
    assert "torchcodec" not in win["engines"]["wangp"]["constraints"]
    assert linux["engines"]["wangp"]["constraints"]["torchcodec"] == "0.5"
    assert not win["engines"]["rigging"]["supported"]
    assert "flash-attn" in win["engines"]["wangp"]["excludedPackages"]
    assert "xformers.ops" in win["engines"]["wangp"]["verificationImports"]
    assert "verificationImports" not in linux["engines"]["wangp"]


def test_verification_rejects_accelerator_import_failure(monkeypatch):
    from types import SimpleNamespace

    module_spec = importlib.util.spec_from_file_location("runtime_verify_test", ROOT / "scripts/runtime_verify.py")
    helper = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(helper)
    monkeypatch.setattr(helper, "recipe", lambda *a: {
        "cuda": "12.8", "verificationImports": ["xformers.ops"],
    })
    monkeypatch.setattr(helper, "sources_current", lambda *a: True)
    monkeypatch.setattr(helper, "inspect_environment", lambda *a: {})
    imported = []

    def importing(name):
        imported.append(name)
        if name == "xformers.ops":
            raise ImportError("incompatible Flash-Attention")
        return SimpleNamespace(version=SimpleNamespace(cuda="12.8"))

    monkeypatch.setattr(helper.importlib, "import_module", importing)
    with pytest.raises(ImportError, match="incompatible Flash-Attention"):
        helper.verify("wangp", cuda=False)
    assert imported == ["torch", "xformers.ops"]


def test_metadata_inspection_rejects_leftover_incompatible_accelerator(monkeypatch):
    from types import SimpleNamespace

    module_spec = importlib.util.spec_from_file_location("runtime_verify_test", ROOT / "scripts/runtime_verify.py")
    helper = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(helper)
    monkeypatch.setattr(helper, "recipe", lambda *a: {
        "env": sys.prefix, "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "constraints": {}, "excludedPackages": ["flash-attn"],
    })
    monkeypatch.setattr(helper.importlib.metadata, "distributions", lambda: [
        SimpleNamespace(metadata={"Name": "flash_attn"}, version="2.8.2"),
    ])
    with pytest.raises(RuntimeError, match="incompatible package flash-attn"):
        helper.inspect_environment("wangp")


def test_older_driver_keeps_core_available_without_claiming_h3_support():
    result = profiles.select_profiles("linux", "x64", "nvidia", "570.124.06")
    assert result["supported"]
    assert result["engines"]["wangp"]["supported"]
    assert result["engines"]["hunyuan3d"]["supported"]
    assert not result["engines"]["minimax_h3"]["supported"]
    assert "580" in result["engines"]["minimax_h3"]["reason"]


def test_unavailable_platforms_and_accelerators_never_fall_through_to_cuda():
    for platform, arch, gpu in [("linux", "arm64", "nvidia"),
                                ("win32", "x64", "amd"), ("linux", "x64", "intel"),
                                ("linux", "x64", "cpu"), ("linux", "x64", "unknown")]:
        result = profiles.select_profiles(platform, arch, gpu)
        assert not result["supported"]
        assert all(not engine["supported"] and engine["reason"] for engine in result["engines"].values()
                   if engine.get("cuda"))


def test_apple_silicon_installs_core_without_cuda_engines():
    result = profiles.select_profiles("darwin", "arm64", "apple")
    assert result["supported"]
    assert result["engines"]["core"]["supported"]
    assert result["engines"]["core"]["id"] == "darwin-arm64-core-core"
    assert not result["engines"]["wangp"]["supported"]
    assert not result["engines"]["minimax_h3"]["supported"]
    assert not result["engines"]["hunyuan3d"]["supported"]
    assert "NVIDIA" in result["engines"]["wangp"]["reason"]
    intel = profiles.select_profiles("darwin", "x64", "apple")
    assert not intel["supported"]


def test_missing_driver_is_explicitly_unverified():
    result = profiles.select_profiles("win32", "x64", "nvidia")
    assert result["engines"]["wangp"]["warning"]
    assert result["driver"] is None


def test_conda_and_venv_windows_interpreters_are_not_confused(tmp_path):
    assert python_path(tmp_path, kind="conda", platform="win32") == tmp_path / "python.exe"
    assert python_path(tmp_path, kind="venv", platform="win32") == tmp_path / "Scripts/python.exe"
    assert python_path(tmp_path, kind="conda", platform="linux") == tmp_path / "bin/python"


def test_receipt_cannot_hide_an_altered_environment(tmp_path):
    app = tmp_path / "app"
    env = app / "env"
    env.mkdir(parents=True)
    receipt = {"fingerprint": "matching", "profile": "linux-x64-nvidia-wangp", "cudaCalculation": True}
    (env / ".hocus-runtime-profile.json").write_text(json.dumps(receipt))
    with patch.object(profiles, "APP_DIR", app), patch.object(profiles, "dependency_fingerprint", return_value="matching"):
        with patch.object(profiles.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)) as run:
            assert not profiles.installation_current("wangp", "linux")
            assert "--inspect" in run.call_args.args[0]
        with patch.object(profiles.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            assert profiles.installation_current("wangp", "linux")


def test_a_failed_migration_cannot_reuse_legacy_markers(tmp_path):
    app = tmp_path / "app"
    (app / ".runtime").mkdir(parents=True)
    with patch.object(profiles, "APP_DIR", app):
        assert profiles.managed_ready("hunyuan3d")  # Legacy install before migration.
        (app / ".runtime/hunyuan3d.managed").write_text("started")
        failed = {"engines": {"hunyuan3d": {"supported": True, "installed": False}}}
        with patch.object(profiles, "detect_profiles", return_value=failed):
            assert not profiles.managed_ready("hunyuan3d")


def test_non_object_receipts_allow_repair_instead_of_aborting_preflight(tmp_path):
    profiles.catalog()  # Load the real recipe before isolating the receipt root.
    app = tmp_path / "app"
    env = app / "env"
    env.mkdir(parents=True)
    receipt = env / ".hocus-runtime-profile.json"
    with patch.object(profiles, "APP_DIR", app):
        for value in ([], None, "corrupt", 42):
            receipt.write_text(json.dumps(value))
            assert not profiles.installation_current("wangp", "linux")


def test_child_python_does_not_import_from_parent_pythonpath(tmp_path):
    import os
    target = tmp_path / "separate engine"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(target)], check=True)
    executable = python_path(target, kind="venv")
    poison = tmp_path / "inherited packages"
    poison.mkdir()
    (poison / "parent_only_dependency.py").write_text("raise RuntimeError('leaked parent')")
    # Real Windows Python also needs SystemRoot for OS cryptography. Preserve
    # host variables while poisoning only the dependency/manager inputs.
    env = isolated_environment(executable, {**os.environ, "PYTHONPATH": str(poison), "PYTHONHOME": str(tmp_path),
                                          "UV_PYTHON": sys.executable, "PIP_TARGET": str(poison),
                                          "HF_TOKEN": "test-value", "CUDA_VISIBLE_DEVICES": "0"})
    assert "UV_PYTHON" not in env and "PIP_TARGET" not in env
    assert env["HF_TOKEN"] == "test-value" and env["CUDA_VISIBLE_DEVICES"] == "0"
    if sys.platform == "win32":
        assert env["SYSTEMROOT"] == os.environ["SYSTEMROOT"]
    code = "import importlib.util,sys; assert importlib.util.find_spec('parent_only_dependency') is None; print(sys.prefix)"
    result = subprocess.run([str(executable), "-c", code], env=env, capture_output=True, text=True, check=True)
    assert Path(result.stdout.strip()).resolve() == target.resolve()


def test_constraint_files_match_the_selected_recipe():
    for platform in profiles.catalog()["platforms"]:
        for engine, definition in profiles.catalog()["engines"].items():
            if platform not in definition["platforms"]:
                continue
            spec = profiles.recipe(engine, platform)
            actual = dict(line.split("==", 1) for line in (ROOT / spec["constraintFile"]).read_text().splitlines()
                          if line and not line.startswith("#"))
            expected = {**spec["constraints"], **{k: spec[k] + "+cu" + spec["cuda"].replace(".", "")
                        for k in ("torch", "torchvision", "torchaudio") if k in spec}}
            assert actual == expected


def test_native_helpers_affect_installation_fingerprint(tmp_path):
    # Exercise the hashing contract using an isolated source copy, no working tree mutation.
    import shutil
    source = tmp_path / "source"
    for name in ["app/runtime", "app/services/hunyuan3d/requirements.txt", "app/services/hunyuan3d/build_mesh_painter.py",
                 "runtime_install.js", "vendor_revisions.js", "hunyuan_native.js", "torch.js", "scripts/runtime_verify.py",
                 "scripts/runtime_pip.py", "scripts/runtime_failed.py", "scripts/runtime_vendor.py", "scripts/windows_toolchain.py",
                 "app/services/runtime_sources.py"]:
        src, dest = ROOT / name, source / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest) if src.is_dir() else shutil.copy2(src, dest)
    with patch.object(profiles, "APP_DIR", source / "app"):
        before = profiles.dependency_fingerprint("hunyuan3d", "linux")
        helper = source / "app/services/hunyuan3d/build_mesh_painter.py"
        helper.write_text(helper.read_text() + "\n# native build fix\n")
        assert profiles.dependency_fingerprint("hunyuan3d", "linux") != before
        windows_before = profiles.dependency_fingerprint("hunyuan3d", "win32")
        linux_before = profiles.dependency_fingerprint("hunyuan3d", "linux")
        windows_helper = source / "scripts/windows_toolchain.py"
        windows_helper.write_text(windows_helper.read_text() + "\n# Windows-only fix\n")
        assert profiles.dependency_fingerprint("hunyuan3d", "win32") != windows_before
        assert profiles.dependency_fingerprint("hunyuan3d", "linux") == linux_before


def _engine_lib_dirs(executable):
    prefix = executable.parent.parent if executable.parent.name.lower() in {"bin", "scripts"} else executable.parent
    return [] if executable.name.lower() == "python.exe" else [str(prefix / "lib"), str(prefix / "lib64")]


def test_native_library_paths_cannot_leak_from_the_parent_engine(tmp_path):
    import os
    parent = tmp_path / "old engine"
    target = tmp_path / "new engine"
    system_cuda = tmp_path / "cuda toolkit"
    executable = python_path(target)
    env = isolated_environment(executable, {
        "VIRTUAL_ENV": str(parent), "CONDA_PREFIX_1": str(parent),
        "PATH": os.pathsep.join([str(parent / "Library/bin"), str(parent / "bin"), str(system_cuda / "bin")]),
        "LD_LIBRARY_PATH": os.pathsep.join([str(parent / "lib"), str(system_cuda / "lib")]),
        "LD_PRELOAD": str(parent / "lib/injected.so"),
    })
    assert str(parent) not in env["PATH"]
    assert str(parent) not in env["LD_LIBRARY_PATH"]
    assert env["LD_LIBRARY_PATH"].split(os.pathsep) == [*_engine_lib_dirs(executable), str(system_cuda / "lib")]
    assert str(system_cuda / "bin") in env["PATH"]
    assert "LD_PRELOAD" not in env and "CONDA_PREFIX_1" not in env


def test_pinokio_machine_toolchain_survives_engine_isolation(tmp_path):
    import os
    base = tmp_path / "pinokio conda base"
    parent = tmp_path / "parent engine"
    target = tmp_path / "selected engine"
    executable = python_path(target)
    env = isolated_environment(executable, {
        "VIRTUAL_ENV": str(parent), "CONDA_PREFIX": str(base),
        "CONDA_PYTHON_EXE": str(python_path(base)),
        "PATH": os.pathsep.join([str(parent / "bin"), str(base / "bin")]),
        "LD_LIBRARY_PATH": os.pathsep.join([str(parent / "lib"), str(base / "lib")]),
    })
    assert str(parent) not in env["PATH"] and str(parent) not in env["LD_LIBRARY_PATH"]
    assert str(base / "bin") in env["PATH"]  # nvcc/ffmpeg remain reachable.
    assert env["LD_LIBRARY_PATH"].split(os.pathsep) == [*_engine_lib_dirs(executable), str(base / "lib")]


def test_engine_native_libs_outrank_pinokio_base_on_the_loader_path(tmp_path):
    import os
    base = tmp_path / "pinokio conda base"
    target = tmp_path / "h3 engine"
    executable = python_path(target)
    env = isolated_environment(executable, {
        "CONDA_PREFIX": str(base), "CONDA_PYTHON_EXE": str(python_path(base)),
        "LD_LIBRARY_PATH": str(base / "lib"),
    })
    libs = env["LD_LIBRARY_PATH"].split(os.pathsep)
    assert str(base / "lib") in libs
    engine_libs = _engine_lib_dirs(executable)
    if engine_libs:
        assert libs[:len(engine_libs)] == engine_libs
        assert libs.index(engine_libs[0]) < libs.index(str(base / "lib"))


def test_package_helper_ignores_inherited_destinations_and_configuration(monkeypatch):
    import importlib.util
    import os
    import pytest
    spec = importlib.util.spec_from_file_location("runtime_pip_test", ROOT / "scripts/runtime_pip.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    profile = profiles.recipe("wangp", sys.platform)
    executable = python_path(ROOT / profile["env"], kind="venv")
    monkeypatch.setattr(sys, "prefix", str(ROOT / profile["env"]))
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(helper.shutil, "which", lambda _: "/tool/uv")
    monkeypatch.setenv("PIP_TARGET", "/foreign/target")
    monkeypatch.setenv("UV_PYTHON", "/foreign/python")
    monkeypatch.setenv("PIP_CONFIG_FILE", "/foreign/pip.conf")
    args, env = helper.command("wangp", ["install", "numpy"])
    assert args[args.index("--python") + 1] == str(executable)
    assert "--no-config" in args
    assert str(ROOT / profile["constraintFile"]) in args
    assert args.count("--constraint") == 2
    assert "PIP_TARGET" not in env and "UV_PYTHON" not in env
    assert env["PIP_CONFIG_FILE"] == os.devnull
    for override in ["--python=/foreign", "--target", "--prefix", "--system", "--user"]:
        with pytest.raises(ValueError, match="destination"):
            helper.command("wangp", ["install", override])
    monkeypatch.setattr(sys, "prefix", "/foreign/environment")
    with pytest.raises(RuntimeError, match="outside"):
        helper.command("wangp", ["install", "numpy"])


def test_missing_vendor_files_and_changed_revisions_trigger_repair(tmp_path, monkeypatch):
    from services import runtime_sources as sources
    vendor = tmp_path / "vendor with spaces"
    vendor.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(vendor), *args], text=True).strip()

    git("init")
    git("config", "user.name", "Runtime test")
    git("config", "user.email", "runtime@example.invalid")
    git("config", "commit.gpgsign", "false")
    entry = vendor / "main.py"
    edited = vendor / "custom.py"
    entry.write_text("# pinned entry\n")
    edited.write_text("# original\n")
    git("add", "main.py", "custom.py")
    git("commit", "-m", "fixture")
    pinned = git("rev-parse", "HEAD")
    monkeypatch.setattr(sources, "vendor_catalog", lambda: {"fixture": {
        "path": vendor.name, "revision": pinned, "requiredPaths": ["main.py"],
    }})
    assert sources.sources_current(["fixture"], tmp_path)
    entry.unlink()
    edited.write_text("# preserved user edit\n")
    assert not sources.sources_current(["fixture"], tmp_path)
    sources.restore_missing("fixture", tmp_path)
    assert entry.read_text() == "# pinned entry\n"
    assert edited.read_text() == "# preserved user edit\n"
    assert sources.sources_current(["fixture"], tmp_path)
    git("add", "custom.py")
    git("commit", "-m", "different upstream revision")
    assert not sources.sources_current(["fixture"], tmp_path)


# Portable Windows toolchain cases live in this registered CI test module.
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
