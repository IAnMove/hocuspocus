"""Shared, dependency-free platform selection for launchers and services.

Selection describes a supported recipe, not proof that its models were tested
on this machine. No imports of torch, package installation or weight downloads.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import platform as host_platform
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
# Receipts written before this scheme hashed whole shared files, so a Windows-only
# recipe edit looked like a Linux reinstall. Scheme 2 hashes the resolved recipe.
FINGERPRINT_SCHEME = 2


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
    """Hash the resolved recipe plus the files that install that engine.

    ``profiles.json`` and ``runtime_install.js`` are not hashed whole.
    Platform edits stay inside ``recipe()``, and install-step edits bump
    ``installStepsVersion`` on that engine (or its ``windows`` override).
    """
    spec = recipe(engine, platform)
    root = APP_DIR.parent
    paths = [spec["constraintFile"],
             "vendor_revisions.js", "hunyuan_native.js", "torch.js", "scripts/runtime_verify.py",
             "scripts/runtime_pip.py", "scripts/runtime_failed.py", "scripts/runtime_vendor.py",
             "app/runtime/vendors.json", "app/services/runtime_sources.py",
             f"app/runtime/locks/{platform}-{engine}.txt"]
    if engine == "wangp":
        paths.append("app/scripts/install_gguf_kernels.py")
    if engine == "hunyuan3d":
        paths.append("app/services/hunyuan3d/build_mesh_painter.py")
        paths.append("app/services/hunyuan3d/patch_windows_sources.py")
        if platform == "win32":
            paths.append("scripts/windows_toolchain.py")
    if "/vendor/" not in spec["requirements"]:
        paths.append(spec["requirements"])
    digest = hashlib.sha256(f"{engine}:{platform}:{FINGERPRINT_SCHEME}".encode())
    digest.update(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode())
    for name in paths:
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def _receipt_path(spec: dict) -> Path:
    return APP_DIR.parent / spec["env"] / ".hocus-runtime-profile.json"


def _matching_identity(receipt: dict, spec: dict) -> bool:
    return (receipt.get("profile") == spec["id"]
            and receipt.get("cudaCalculation") is bool(spec.get("cuda")))


def _rewrite_fingerprint(path: Path, receipt: dict, fingerprint: str) -> None:
    updated = {**receipt, "fingerprint": fingerprint, "fingerprintScheme": FINGERPRINT_SCHEME}
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(updated, indent=2), encoding="utf-8")
    temporary.replace(path)


def _inspect_passes(engine: str, platform: str, spec: dict) -> bool:
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


def installation_current(engine: str, platform: str) -> bool:
    spec = recipe(engine, platform)
    try:
        path = _receipt_path(spec)
        receipt = json.loads(path.read_text())
        if not isinstance(receipt, dict) or not _matching_identity(receipt, spec):
            return False
        fingerprint = dependency_fingerprint(engine, platform)
        current = (receipt.get("fingerprintScheme") == FINGERPRINT_SCHEME
                   and receipt.get("fingerprint") == fingerprint)
        legacy = receipt.get("fingerprintScheme") != FINGERPRINT_SCHEME
        if not current and not legacy:
            return False
        if not _inspect_passes(engine, platform, spec):
            return False
        if legacy:
            _rewrite_fingerprint(path, receipt, fingerprint)
        return True
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, TypeError):
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


# Engines whose Windows install compiles native code (Hunyuan3D: diso and the
# mesh painter extensions). Kept here, not in profiles.json, because that file
# feeds every engine's install fingerprint.
WINDOWS_COMPILER_ENGINES = {"hunyuan3d"}
MSVC_MISSING_REASON = (
    "{label} needs the Microsoft C++ Build Tools to compile its native parts on Windows. "
    "Install Visual Studio 2022 Build Tools with \"Desktop development with C++\" from "
    "https://visualstudio.microsoft.com/visual-cpp-build-tools/, then run Install again."
)
MSVC_TOO_NEW_REASON = (
    "{label} compiles CUDA 12.8 extensions, and CUDA 12.8 only accepts Visual Studio 2019 "
    "or 2022 compilers (MSVC 14.2x-14.4x); only MSVC {found} was found. Install Visual "
    "Studio 2022 Build Tools with \"Desktop development with C++\" alongside it from "
    "https://visualstudio.microsoft.com/visual-cpp-build-tools/, then run Install again."
)
# nvcc 12.8 host_config.h rejects _MSC_VER >= 1950 (Visual Studio 2026).
MSVC_CUDA_LIMIT = (14, 50)


def _visual_studio_roots() -> list[Path]:
    """Installations from vswhere plus the standard folders.

    vswhere can list nothing while a toolset is on disk (an unregistered or
    mid-registration instance), and setuptools then reports that Visual C++
    is missing, so the folders are scanned as well.
    """
    roots: list[Path] = []
    bases = {os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)",
             os.environ.get("ProgramFiles") or r"C:\Program Files"}
    for base in bases:
        vswhere = Path(base) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
        if vswhere.is_file():
            try:
                listed = subprocess.run(
                    [str(vswhere), "-all", "-prerelease", "-products", "*", "-property", "installationPath"],
                    capture_output=True, text=True, timeout=15,
                ).stdout
                roots.extend(Path(line.strip()) for line in listed.splitlines() if line.strip())
            except (OSError, subprocess.SubprocessError):
                pass
        roots.extend(sorted((Path(base) / "Microsoft Visual Studio").glob("*/*")))
    unique: dict[str, Path] = {}
    for root in roots:
        unique.setdefault(os.path.normcase(str(root)), root)
    return list(unique.values())


def _msvc_toolsets() -> list[tuple[tuple[int, ...], str, Path]]:
    """(version, toolset, vcvars64.bat) for each installed x64 MSVC toolset."""
    found = []
    for root in _visual_studio_roots():
        vcvars = root / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
        if not vcvars.is_file():
            continue
        for tools in (root / "VC" / "Tools" / "MSVC").glob("*"):
            if (tools / "bin" / "Hostx64" / "x64" / "cl.exe").is_file():
                found.append((_version(tools.name), tools.name, vcvars))
    return sorted(found)


def find_msvc() -> dict | None:
    """Newest MSVC toolset that CUDA 12.8 accepts, as the vcvars call to use."""
    usable = [item for item in _msvc_toolsets() if item[0][:2] < MSVC_CUDA_LIMIT]
    if not usable:
        return None
    _version_key, toolset, vcvars = usable[-1]
    return {"vcvars": str(vcvars), "toolset": toolset}


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
    # Only gate installs that have yet to happen: a working install stays usable.
    needs_compiler = [item for name, item in result["engines"].items()
                      if name in WINDOWS_COMPILER_ENGINES and item["supported"]
                      and item.get("installed") is False]
    if result["platform"] == "win32" and needs_compiler:
        # Install steps load this toolset with vcvars64.bat before building.
        result["msvc"] = find_msvc()
        if result["msvc"] is None:
            newest = _msvc_toolsets()
            for item in needs_compiler:
                item["supported"] = False
                item["reason"] = (MSVC_TOO_NEW_REASON.format(label=item["label"], found=newest[-1][1])
                                  if newest else MSVC_MISSING_REASON.format(label=item["label"]))
            # Only optional engines were gated; preserve platform-aware core support.
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
