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


@pytest.fixture(autouse=True)
def isolated_cuda_visibility(monkeypatch):
    monkeypatch.delenv('CUDA_VISIBLE_DEVICES', raising=False)
    monkeypatch.delenv('CUDA_DEVICE_ORDER', raising=False)


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


@pytest.mark.parametrize("engine,module", [("wangp", "xformers.ops"), ("rigging", "bpy"), ("rigging", "flash_attn")])
def test_verification_rejects_accelerator_import_failure(monkeypatch, engine, module):
    from types import SimpleNamespace

    module_spec = importlib.util.spec_from_file_location("runtime_verify_test", ROOT / "scripts/runtime_verify.py")
    helper = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(helper)
    monkeypatch.setattr(helper, "recipe", lambda *a: {
        "cuda": "12.8", "verificationImports": [module],
    })
    monkeypatch.setattr(helper, "sources_current", lambda *a: True)
    monkeypatch.setattr(helper, "inspect_environment", lambda *a: {})
    imported = []

    def importing(name):
        imported.append(name)
        if name == module:
            raise ImportError("incompatible Flash-Attention")
        return SimpleNamespace(version=SimpleNamespace(cuda="12.8"))

    monkeypatch.setattr(helper.importlib, "import_module", importing)
    with pytest.raises(ImportError, match="incompatible Flash-Attention"):
        helper.verify(engine, cuda=False)
    assert imported == ["torch", module]


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


def test_windows_excluded_accelerators_are_absent_from_recipe_and_lock():
    spec = profiles.recipe("wangp", "win32")
    lock = (ROOT / "app/runtime/locks/win32-wangp.txt").read_text()
    for package in spec["excludedPackages"]:
        assert not any(line.startswith((f"{package}==", f"{package} @")) for line in lock.splitlines())
    assert not any("flash_attn" in package or "flash-attn" in package for package in spec["acceleratorPackages"])
    assert f"xformers=={spec['constraints']['xformers']}" in lock


def test_older_driver_keeps_core_available_without_claiming_h3_support():
    result = profiles.select_profiles("linux", "x64", "nvidia", "570.124.06")
    assert result["supported"]
    assert result["engines"]["wangp"]["supported"]
    assert result["engines"]["hunyuan3d"]["supported"]
    assert not result["engines"]["minimax_h3"]["supported"]
    assert "580" in result["engines"]["minimax_h3"]["reason"]


def test_unavailable_platforms_and_accelerators_never_fall_through_to_cuda():
    for platform, arch, gpu in [("linux", "arm64", "nvidia"),
                                ("win32", "x64", "amd"), ("linux", "x64", "amd"), ("linux", "x64", "intel"),
                                ("linux", "x64", "cpu"), ("linux", "x64", "unknown")]:
        result = profiles.select_profiles(platform, arch, gpu)
        assert all(not engine["supported"] and engine["reason"] for engine in result["engines"].values()
                   if engine.get("cuda"))
        # The editing/remote studio still installs instead of stopping the installer.
        assert result["supported"]
        assert result["engines"]["core"]["supported"]
        assert result["engines"]["core"]["id"] == f"{platform}-{profiles.normalize_arch(arch)}-core-core"


def test_core_is_installed_only_where_wangp_cannot_run():
    nvidia = profiles.select_profiles("linux", "x64", "nvidia", "580.82.09")
    assert nvidia["supported"] and nvidia["engines"]["wangp"]["supported"]
    # Both use app/env; selecting both would make each Update replace the other's receipt.
    assert not nvidia["engines"]["core"]["supported"]
    assert nvidia["engines"]["core"]["supersededBy"] == "wangp"
    old_driver = profiles.select_profiles("win32", "x64", "nvidia", "470.10")
    assert not old_driver["engines"]["wangp"]["supported"]
    assert "driver" in old_driver["engines"]["wangp"]["reason"]
    assert old_driver["engines"]["core"]["supported"] and old_driver["supported"]
    for platform, arch in [("darwin", "x64"), ("win32", "arm64"), ("linux", "ia32"), ("freebsd", "x64")]:
        result = profiles.select_profiles(platform, arch, "amd")
        assert not result["supported"]
        assert result["engines"]["core"]["reason"]


def test_core_package_install_has_no_cuda_index(monkeypatch):
    module_spec = importlib.util.spec_from_file_location("runtime_pip_test", ROOT / "scripts/runtime_pip.py")
    helper = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(helper)
    monkeypatch.setattr(helper.shutil, "which", lambda name: name)
    for platform in ("linux", "win32", "darwin"):
        monkeypatch.setattr(helper.sys, "platform", platform)
        monkeypatch.setattr(helper.sys, "prefix", str(ROOT / "app/env"))
        arguments, _env = helper.command("core", ["install", "-r", f"app/runtime/locks/{platform}-core.txt"])
        assert not any("download.pytorch.org" in argument for argument in arguments)
        assert str(ROOT / f"app/runtime/locks/{platform}-core.txt") in arguments


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
    assert result["computeCapability"] is None


def test_pre_turing_gpu_installs_core_with_an_explicit_reason():
    pascal = profiles.select_profiles("linux", "x64", "nvidia", "580.82.09", "6.1")
    assert pascal["supported"] and pascal["engines"]["core"]["supported"]
    assert pascal["computeCapability"] == "6.1"
    for engine in pascal["engines"].values():
        if engine.get("cuda"):
            assert not engine["supported"]
            assert "older than Turing" in engine["reason"] and "6.1" in engine["reason"]
    turing = profiles.select_profiles("win32", "x64", "nvidia", "580.82.09", "7.5")
    assert turing["engines"]["wangp"]["supported"] and not turing["engines"]["core"]["supported"]
    # A driver below the floor still reports the driver when the GPU itself is fine.
    old_driver = profiles.select_profiles("linux", "x64", "nvidia", "470.10", "8.9")
    assert "driver" in old_driver["engines"]["wangp"]["reason"]


def test_detect_profiles_reads_compute_capability_from_nvidia_smi(monkeypatch):
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES', 'GPU-selected')
    def nvidia_smi(command, **_kwargs):
        field = command[1].split("=", 1)[1]
        if field == "compute_cap" and nvidia_smi.legacy:
            raise subprocess.CalledProcessError(2, command, stderr="Field \"compute_cap\" is not a valid field")
        output = {"driver_version": "580.82.09\n", "compute_cap": "8.9\n"}[field]
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    nvidia_smi.legacy = False
    with patch.object(profiles.subprocess, "run", side_effect=nvidia_smi), \
            patch.object(profiles, "installation_current", return_value=False):
        result = profiles.detect_profiles(platform="linux", arch="x64")
    assert result["gpu"] == "nvidia" and result["driver"] == "580.82.09"
    assert result["computeCapability"] == "8.9"
    assert result["cudaDevice"] == "GPU-selected"
    assert result["engines"]["wangp"]["supported"]
    assert not result["engines"]["core"]["supported"]
    nvidia_smi.legacy = True
    with patch.object(profiles.subprocess, "run", side_effect=nvidia_smi), \
            patch.object(profiles, "installation_current", return_value=False):
        legacy = profiles.detect_profiles(platform="linux", arch="x64")
    assert legacy["driver"] == "580.82.09" and legacy["computeCapability"] is None
    assert legacy["engines"]["wangp"]["supported"]
    assert 'compute capability is unverified' in legacy['engines']['wangp']['warning']


@pytest.mark.parametrize('visible,device,capability', [
    (None, 'GPU-selected', '8.9'), ('0,1', 'GPU-selected', '8.9'), ('1,0', 'GPU-old', '6.1'),
    ('GPU-selected', 'GPU-selected', '8.9'), ('', None, None), ('-1', None, None),
])
def test_detect_profiles_gates_the_first_visible_cuda_device(monkeypatch, visible, device, capability):
    monkeypatch.setenv('CUDA_DEVICE_ORDER', 'PCI_BUS_ID')
    if visible is None:
        monkeypatch.delenv('CUDA_VISIBLE_DEVICES', raising=False)
    else:
        monkeypatch.setenv('CUDA_VISIBLE_DEVICES', visible)
    calls = []

    def nvidia_smi(command, **_kwargs):
        calls.append(command)
        selected = next((value.split('=', 1)[1] for value in command if value.startswith('--id=')), None)
        field = command[1].split('=', 1)[1]
        if field == 'uuid,pci.bus_id':
            output = 'GPU-old, 00000000:65:00.0\nGPU-selected, 00000000:01:00.0'
        else:
            output = '580.82.09' if field == 'driver_version' else ('6.1' if selected == 'GPU-old' else '8.9')
        return subprocess.CompletedProcess(command, 0, stdout=output + '\n', stderr='')

    monkeypatch.setattr(profiles.subprocess, 'run', nvidia_smi)
    monkeypatch.setattr(profiles, 'installation_current', lambda *_args: False)
    result = profiles.detect_profiles(platform='linux', arch='x64', gpu='nvidia')
    assert result['cudaDevice'] == device
    assert result['computeCapability'] == capability
    assert result['engines']['wangp']['supported'] == (capability == '8.9')
    if device is None:
        assert not calls
    else:
        assert all('--id=' + device in command for command in calls if '--query-gpu=uuid,pci.bus_id' not in command)


@pytest.mark.parametrize('order,visible,expected_device,capability', [
    (None, None, None, None), ('FASTEST_FIRST', '0,1', None, None),
    ('FASTEST_FIRST', '1,0', None, None), ('PCI_BUS_ID', '0,1', 'GPU-new', '8.9'),
    ('PCI_BUS_ID', '1,0', 'GPU-old', '6.1'), (None, 'GPU-new', 'GPU-new', '8.9'),
])
def test_cuda_ordinal_is_not_assumed_to_be_the_nvml_index(monkeypatch, order, visible, expected_device, capability):
    if order is not None:
        monkeypatch.setenv('CUDA_DEVICE_ORDER', order)
    if visible is not None:
        monkeypatch.setenv('CUDA_VISIBLE_DEVICES', visible)
    calls = []

    def nvidia_smi(command, **_kwargs):
        calls.append(command)
        field = command[1].split('=', 1)[1]
        selected = next((part.split('=', 1)[1] for part in command if part.startswith('--id=')), None)
        if field == 'uuid,pci.bus_id':
            output = 'GPU-old, 00000000:65:00.0\nGPU-new, 00000000:01:00.0'
        elif field == 'driver_version':
            output = '580.82.09'
        else:
            output = '8.9' if selected in ('1', 'GPU-new') else '6.1'
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr='')

    monkeypatch.setattr(profiles.subprocess, 'run', nvidia_smi)
    result = profiles.detect_profiles(platform='linux', arch='x64', gpu='nvidia', inspect_engines=set())
    assert result['cudaDevice'] == expected_device
    assert result['computeCapability'] == capability
    assert result['engines']['wangp']['supported'] == (capability != '6.1')
    if expected_device is None:
        assert 'CUDA_DEVICE_ORDER' in result['engines']['wangp']['warning']
        assert not any('--query-gpu=compute_cap' in command for command in calls)


@pytest.mark.parametrize('selector', ['99', 'GPU-missing'])
def test_an_out_of_range_cuda_selector_does_not_enable_the_nvidia_recipe(monkeypatch, selector):
    monkeypatch.setenv('CUDA_VISIBLE_DEVICES', selector)

    def nvidia_smi(command, **_kwargs):
        if '--query-gpu=uuid,pci.bus_id' in command:
            return subprocess.CompletedProcess(command, 0, stdout='GPU-only, 00000000:01:00.0', stderr='')
        raise subprocess.CalledProcessError(6, command)

    monkeypatch.setattr(profiles.subprocess, 'run', nvidia_smi)
    result = profiles.detect_profiles(platform='linux', arch='x64', gpu='nvidia', inspect_engines=set())
    assert not result['engines']['wangp']['supported']
    assert result['engines']['core']['supported']
    assert 'not available' in result['engines']['wangp']['warning']


def test_unavailable_nvidia_smi_keeps_a_known_nvidia_machine_explicitly_unverified(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise OSError('nvidia-smi unavailable')

    monkeypatch.setattr(profiles.subprocess, 'run', unavailable)
    result = profiles.detect_profiles(platform='linux', arch='x64', gpu='nvidia', inspect_engines=set())
    assert result['engines']['wangp']['supported']
    assert result['cudaDevice'] is None and result['computeCapability'] is None
    assert 'could not be verified' in result['engines']['wangp']['warning']


def test_incomplete_inventory_does_not_claim_one_gpu_is_the_only_gpu(monkeypatch):
    def nvidia_smi(command, **_kwargs):
        field = command[1].split('=', 1)[1]
        assert field != 'compute_cap', 'an incomplete inventory cannot identify CUDA lane 0'
        output = '580.82.09' if field == 'driver_version' else 'GPU-known, 00000000:01:00.0\nGPU-other, [N/A]'
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr='')

    monkeypatch.setattr(profiles.subprocess, 'run', nvidia_smi)
    result = profiles.detect_profiles(platform='linux', arch='x64', inspect_engines=set())
    assert result['cudaDevice'] is None and result['computeCapability'] is None
    assert 'identity could not be verified' in result['engines']['wangp']['warning']


@pytest.mark.parametrize('order', [None, 'FASTEST_FIRST', 'PCI_BUS_ID'])
def test_a_single_gpu_has_unambiguous_identity_in_every_cuda_order(monkeypatch, order):
    if order:
        monkeypatch.setenv('CUDA_DEVICE_ORDER', order)

    def nvidia_smi(command, **_kwargs):
        field = command[1].split('=', 1)[1]
        if field != 'uuid,pci.bus_id':
            assert '--id=GPU-only' in command
        output = {'uuid,pci.bus_id': 'GPU-only, 00000000:01:00.0', 'driver_version': '580.82.09', 'compute_cap': '8.9'}[field]
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr='')

    monkeypatch.setattr(profiles.subprocess, 'run', nvidia_smi)
    result = profiles.detect_profiles(platform='linux', arch='x64', inspect_engines=set())
    assert result['cudaDevice'] == 'GPU-only' and result['computeCapability'] == '8.9'
    assert result['engines']['wangp']['warning'] is None


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


def test_windows_recipe_edits_do_not_change_the_linux_fingerprint():
    import copy
    data = copy.deepcopy(profiles.catalog())
    with patch.object(profiles, "catalog", lambda: data):
        linux_before = profiles.dependency_fingerprint("wangp", "linux")
        windows_before = profiles.dependency_fingerprint("wangp", "win32")
        data["engines"]["wangp"]["windows"]["torch"] = "9.9.9"
        assert profiles.dependency_fingerprint("wangp", "linux") == linux_before
        assert profiles.dependency_fingerprint("wangp", "win32") != windows_before
        linux_before = profiles.dependency_fingerprint("wangp", "linux")
        windows_now = profiles.dependency_fingerprint("wangp", "win32")
        data["engines"]["wangp"]["torch"] = "9.8.0"
        assert profiles.dependency_fingerprint("wangp", "linux") != linux_before
        assert profiles.dependency_fingerprint("wangp", "win32") == windows_now
        linux_now = profiles.dependency_fingerprint("wangp", "linux")
        data["engines"]["wangp"]["windows"]["installStepsVersion"] = 2
        assert profiles.dependency_fingerprint("wangp", "linux") == linux_now
        assert profiles.dependency_fingerprint("wangp", "win32") != windows_now


def test_legacy_receipt_is_rewritten_once_when_inspect_passes(tmp_path):
    profiles.catalog()
    app = tmp_path / "app"
    env = app / "env"
    env.mkdir(parents=True)
    path = env / ".hocus-runtime-profile.json"
    path.write_text(json.dumps({
        "fingerprint": "old-whole-file-hash",
        "profile": "linux-x64-nvidia-wangp",
        "cudaCalculation": True,
        "packages": {},
    }))
    passed = subprocess.CompletedProcess([], 0)
    with patch.object(profiles, "APP_DIR", app), \
            patch.object(profiles, "dependency_fingerprint", return_value="new-fingerprint"), \
            patch("services.runtime_sources.sources_current", return_value=True), \
            patch.object(profiles.subprocess, "run", return_value=passed):
        assert profiles.installation_current("wangp", "linux")
        updated = json.loads(path.read_text())
        assert updated["fingerprintScheme"] == profiles.FINGERPRINT_SCHEME
        assert updated["fingerprint"] == "new-fingerprint"
        assert updated["packages"] == {}
        path.write_text(json.dumps({**updated, "fingerprint": "changed-after-migration"}))
        assert not profiles.installation_current("wangp", "linux")
        assert json.loads(path.read_text())["fingerprint"] == "changed-after-migration"


def test_legacy_receipt_is_kept_when_inspect_fails(tmp_path):
    profiles.catalog()
    app = tmp_path / "app"
    env = app / "env"
    env.mkdir(parents=True)
    path = env / ".hocus-runtime-profile.json"
    original = {"fingerprint": "old-whole-file-hash", "profile": "linux-x64-nvidia-wangp", "cudaCalculation": True}
    path.write_text(json.dumps(original))
    failed = subprocess.CompletedProcess([], 1)
    with patch.object(profiles, "APP_DIR", app), \
            patch("services.runtime_sources.sources_current", return_value=True), \
            patch.object(profiles.subprocess, "run", return_value=failed):
        assert not profiles.installation_current("wangp", "linux")
    assert json.loads(path.read_text()) == original


def test_native_helpers_affect_installation_fingerprint(tmp_path):
    # Exercise the hashing contract using an isolated source copy, no working tree mutation.
    import shutil
    source = tmp_path / "source"
    for name in ["app/runtime", "app/services/hunyuan3d/requirements.txt", "app/services/hunyuan3d/build_mesh_painter.py",
                 "app/services/hunyuan3d/patch_windows_sources.py",
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
    assert args[args.index("--build-constraint") + 1] == str(ROOT / profile["constraintFile"])
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


def _detect_windows(installed: bool, toolsets: list) -> dict:
    with patch.object(profiles.subprocess, "run", side_effect=OSError),             patch.object(profiles, "installation_current", return_value=installed),             patch.object(profiles, "_msvc_toolsets", return_value=toolsets) as probe:
        result = profiles.detect_profiles(platform="win32", arch="x64", gpu="nvidia")
    return result, probe


def test_windows_hunyuan3d_install_is_skipped_with_a_reason_without_msvc():
    result, _ = _detect_windows(installed=False, toolsets=[])
    item = result["engines"]["hunyuan3d"]
    assert item["supported"] is False
    assert "Build Tools" in item["reason"] and "Desktop development with C++" in item["reason"]
    assert result["engines"]["wangp"]["supported"] is True
    assert result["supported"] is True  # Hunyuan3D is optional; the main install continues.


def test_windows_hunyuan3d_rejects_a_compiler_cuda_12_8_cannot_use():
    vs2026 = [((14, 51, 36231), "14.51.36231", Path("vs18/vcvars64.bat"))]
    result, _ = _detect_windows(installed=False, toolsets=vs2026)
    item = result["engines"]["hunyuan3d"]
    assert item["supported"] is False
    assert "14.51.36231" in item["reason"] and "2022" in item["reason"]


def test_windows_hunyuan3d_uses_the_cuda_compatible_toolset_or_an_existing_install():
    both = [((14, 29, 30133), "14.29.30133", Path("vs2019/vcvars64.bat")),
            ((14, 51, 36231), "14.51.36231", Path("vs18/vcvars64.bat"))]
    result, _ = _detect_windows(installed=False, toolsets=both)
    assert result["engines"]["hunyuan3d"]["supported"] is True
    assert result["msvc"] == {"vcvars": str(Path("vs2019/vcvars64.bat")), "toolset": "14.29.30133"}
    result, probe = _detect_windows(installed=True, toolsets=[])
    assert result["engines"]["hunyuan3d"]["supported"] is True
    probe.assert_not_called()


def test_msvc_toolsets_are_found_on_disk_when_vswhere_lists_nothing(tmp_path):
    x86, x64 = tmp_path / "x86", tmp_path / "x64"
    for base, install, toolset in ((x86, "2019/BuildTools", "14.29.30133"),
                                   (x64, "18/Community", "14.51.36231")):
        root = base / "Microsoft Visual Studio" / install
        (root / "VC/Auxiliary/Build").mkdir(parents=True)
        (root / "VC/Auxiliary/Build/vcvars64.bat").write_text("", encoding="utf-8")
        cl = root / "VC/Tools/MSVC" / toolset / "bin/Hostx64/x64/cl.exe"
        cl.parent.mkdir(parents=True)
        cl.write_bytes(b"")
    (x86 / "Microsoft Visual Studio/Installer").mkdir(parents=True)
    (x86 / "Microsoft Visual Studio/Installer/vswhere.exe").write_bytes(b"")
    empty = subprocess.CompletedProcess([], 0, stdout="")
    with patch.dict(profiles.os.environ, {"ProgramFiles(x86)": str(x86), "ProgramFiles": str(x64)}),             patch.object(profiles.subprocess, "run", return_value=empty):
        assert [item[1] for item in profiles._msvc_toolsets()] == ["14.29.30133", "14.51.36231"]
        chosen = profiles.find_msvc()
    assert chosen["toolset"] == "14.29.30133"
    assert chosen["vcvars"].endswith(str(Path("2019/BuildTools/VC/Auxiliary/Build/vcvars64.bat")))


def test_non_windows_profiles_never_probe_msvc():
    for platform, arch, gpu in [("linux", "x64", "nvidia"), ("darwin", "arm64", "apple")]:
        with patch.object(profiles.subprocess, "run", side_effect=OSError), \
                patch.object(profiles, "installation_current", return_value=False), \
                patch.object(profiles, "find_msvc", side_effect=AssertionError("Windows only")):
            assert profiles.detect_profiles(platform=platform, arch=arch, gpu=gpu)["supported"]
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


def test_install_summary_names_missing_features_and_why():
    module_spec = importlib.util.spec_from_file_location("runtime_probe_test", ROOT / "scripts/runtime_probe.py")
    probe = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(probe)

    def summary(*args):
        result = profiles.select_profiles(*args)
        for engine in result["engines"].values():
            engine.setdefault("installed", False)
        return probe.summary(result)

    amd = summary("linux", "x64", "amd")
    assert "editing studio" in amd[0]
    assert len(amd) == 2 and "NVIDIA" in amd[1] and "(WanGP)" in amd[1] and "(UniRig)" in amd[1]
    old_driver = summary("win32", "x64", "nvidia", "470.1")
    # Engines blocked by the same driver floor share one line.
    assert any("(WanGP)" in line and "(Hunyuan3D)" in line and "528.33" in line for line in old_driver)
    pascal = summary("linux", "x64", "nvidia", "580.82.09", "6.1")
    assert "editing studio" in pascal[0]
    assert any("(WanGP)" in line and "older than Turing" in line and "6.1" in line for line in pascal)
    nvidia = summary("linux", "x64", "nvidia", "580.82.09")
    assert nvidia[0].startswith("Installs the full studio")
    assert not any(line.startswith("Not available") for line in nvidia)
    assert "(SAM 3.1)" in nvidia[-1] and "Advanced" in nvidia[-1]
    assert summary("darwin", "x64", "apple")[0].startswith("Nothing can be installed")
