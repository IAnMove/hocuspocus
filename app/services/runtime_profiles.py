"""Shared, dependency-free platform selection for launchers and services.

Selection describes a supported recipe, not proof that its models were tested
on this machine. No imports of torch, package installation or weight downloads.
"""
from __future__ import annotations

import copy
import hashlib
import json
import platform as host_platform
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads((APP_DIR / "runtime" / "profiles.json").read_text(encoding="utf-8"))


def normalize_arch(value: str) -> str:
    value = value.lower()
    return {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(value, value)


def _version(value: str) -> tuple[int, ...]:
    parts = tuple(int(n) for n in re.findall(r"\d+", value))
    return (parts + (0, 0, 0))[:3]


def recipe(engine: str, platform: str, arch: str | None = None) -> dict:
    base = copy.deepcopy(catalog()["engines"][engine])
    override = base.pop("windows", {}) if platform == "win32" else {}
    base.pop("windows", None)
    pins = {**base["constraints"], **override.get("constraints", {})}
    base.update(override)
    base["constraints"] = {k: v for k, v in pins.items() if v is not None}
    arch = normalize_arch(arch or ("arm64" if platform == "darwin" else "x64"))
    if base.get("cuda"):
        base["id"] = f"{platform}-x64-nvidia-{engine}"
    else:
        base["id"] = f"{platform}-{arch}-core-{engine}"
    base["engine"] = engine
    base["constraintFile"] = f"app/runtime/constraints/{platform}-{engine}.txt"
    return base


def dependency_fingerprint(engine: str, platform: str) -> str:
    spec = recipe(engine, platform)
    root = APP_DIR.parent
    paths = ["app/runtime/profiles.json", spec["constraintFile"], "runtime_install.js",
             "vendor_revisions.js", "hunyuan_native.js", "torch.js", "scripts/runtime_verify.py",
             "scripts/runtime_pip.py", "scripts/runtime_failed.py", "scripts/runtime_vendor.py",
             "app/runtime/vendors.json", "app/services/runtime_sources.py",
             f"app/runtime/locks/{platform}-{engine}.txt"]
    if engine == "wangp":
        paths.append("app/scripts/install_gguf_kernels.py")
    if engine == "hunyuan3d":
        paths.append("app/services/hunyuan3d/build_mesh_painter.py")
    if "/vendor/" not in spec["requirements"]:
        paths.append(spec["requirements"])
    digest = hashlib.sha256(f"{engine}:{platform}".encode())
    for name in paths:
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def installation_current(engine: str, platform: str) -> bool:
    spec = recipe(engine, platform)
    try:
        receipt = json.loads((APP_DIR.parent / spec["env"] / ".hocus-runtime-profile.json").read_text())
        if not isinstance(receipt, dict):
            return False
        matches = (receipt.get("fingerprint") == dependency_fingerprint(engine, platform)
                   and receipt.get("profile") == spec["id"]
                   and receipt.get("cudaCalculation") is bool(spec.get("cuda")))
        if not matches:
            return False
        from services.runtime_sources import sources_current
        if not sources_current(spec.get("vendors", []), APP_DIR.parent):
            return False
        from services.runtime_environment import isolated_environment, python_path
        executable = python_path(APP_DIR.parent / spec["env"], kind=spec["environment"], platform=platform)
        result = subprocess.run(
            [str(executable), "-I", str(APP_DIR.parent / "scripts" / "runtime_verify.py"),
             "--engine", engine, "--inspect"],
            env=isolated_environment(executable), capture_output=True, timeout=15,
        )
        return result.returncode == 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return False


def _common_reason(manifest: dict, platform: str, arch: str, gpu: str) -> str | None:
    if platform == "darwin" and arch == "arm64":
        return None
    if platform not in manifest["platforms"]:
        return f"No installation recipe for {platform}. Supported: Windows, Linux and Apple Silicon."
    if arch not in manifest["architectures"]:
        return f"No installation recipe for architecture {arch}; x64 is required."
    if gpu not in manifest["accelerators"]:
        return "Local AI installation currently requires NVIDIA; CPU/AMD/Intel/MPS recipes are not enabled."
    return None


def _engine_support(definition: dict, platform: str, arch: str, driver: str | None, common: str | None, manifest: dict) -> tuple[str | None, str | None, str | None]:
    macos_core = platform == "darwin" and arch == "arm64"
    reason = common
    warning = None
    if macos_core and definition.get("cuda"):
        reason = "Local NVIDIA engine; hidden on Apple Silicon core/remote."
    elif not reason and platform not in definition["platforms"]:
        reason = definition.get("unsupportedReason", "No compatible engine recipe.")
    minimum = None
    if definition.get("cuda"):
        minimum = manifest["driverMinimum"][definition["cuda"]].get(platform)
    if not reason and driver and minimum and _version(driver) < _version(minimum):
        reason = f"{definition['label']} needs NVIDIA driver >= {minimum} for CUDA {definition['cuda']} (detected {driver})."
    if not reason and not driver and definition.get("cuda"):
        warning = "NVIDIA driver version could not be verified; the runtime check must confirm CUDA before use."
    return reason, warning, minimum


def select_profiles(platform: str, arch: str, gpu: str, driver: str | None = None) -> dict:
    """Pure selection; unknown/unsupported capabilities never silently use CUDA."""
    arch = normalize_arch(arch)
    gpu = (gpu or "unknown").lower()
    manifest = catalog()
    common = _common_reason(manifest, platform, arch, gpu)
    engines = {}
    for name, definition in manifest["engines"].items():
        reason, warning, minimum = _engine_support(definition, platform, arch, driver, common, manifest)
        engines[name] = {**recipe(name, platform, arch), "supported": reason is None, "reason": reason,
                         "warning": warning, "driverMinimum": minimum}
    required = [
        engines[name]["supported"]
        for name, definition in manifest["engines"].items()
        if definition.get("required") and platform in definition.get("platforms", [])
    ]
    return {"version": manifest["version"], "revision": manifest["revision"],
            "platform": platform, "architecture": arch, "gpu": gpu, "driver": driver,
            "supported": all(required) if required else False,
            "engines": engines}


def detect_profiles(*, platform: str | None = None, arch: str | None = None,
                    gpu: str | None = None, inspect_engines: set[str] | None = None) -> dict:
    driver = None
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        versions = [line.strip() for line in result.stdout.splitlines()
                    if re.fullmatch(r"\d+(?:\.\d+)+", line.strip())]
        if versions:
            driver = min(versions, key=_version)
            gpu = "nvidia"
    except (OSError, subprocess.SubprocessError):
        pass
    result = select_profiles(platform or sys.platform, arch or host_platform.machine(),
                             gpu or "unknown", driver)
    for name, item in result["engines"].items():
        if inspect_engines is None or name in inspect_engines:
            item["installed"] = installation_current(name, result["platform"]) if item["supported"] else False
    return result


def require_supported(engine: str) -> dict:
    selected = detect_profiles()["engines"][engine]
    if not selected["supported"]:
        raise RuntimeError(selected["reason"])
    return selected


def managed_ready(engine: str) -> bool:
    """Existing pre-profile installs keep working until their first migration.

    Once managed setup starts, a failed/partial install cannot fall back to old
    legacy markers. Only a verified matching environment is then usable.
    """
    if not (APP_DIR / ".runtime" / f"{engine}.managed").exists():
        return True
    item = detect_profiles(inspect_engines={engine})["engines"][engine]
    return item["supported"] and item["installed"]
