"""Select a CUDA-compatible x64 MSVC toolset without changing the user's machine.

CUDA 12.8 rejects MSVC 19.50+ (VS 18). Discover side-by-side toolsets with
vswhere, activate the selected version, and keep setuptools from reselecting
the newest installation. Used only by Windows Hunyuan native builds.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def prepare_rasterizer(source: Path, destination: Path) -> None:
    """Build the pinned 2.1 source on MSVC without editing the vendor checkout.

    Upstream uses size_t in IntArrayRef initializer lists. MSVC correctly rejects
    that narrowing conversion (C2398); Torch tensor dimensions are int64_t.
    """
    relative = "lib/custom_rasterizer_kernel/grid_neighbor.cpp"
    original = (source / relative).read_text(encoding="utf-8")
    count = 0

    def dimensions(match):
        nonlocal count
        parts = match[1].split(",")
        for index, part in enumerate(parts):
            if ".size()" in part:
                parts[index] = f"static_cast<int64_t>({part.strip()})"
                count += 1
        return "torch::zeros({" + ",".join(parts) + "}"

    patched = re.sub(r"torch::zeros\(\{([^{}]+)\}", dimensions, original)
    if count != 13:
        raise RuntimeError("Hunyuan3D 2.1 rasterizer source changed; review the Windows dimension fix")
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns(
        "build", "*.egg-info", "*.pyd", "*.so", "__pycache__"))
    (destination / relative).write_text(patched, encoding="utf-8")
    # Linux long is 64-bit; Windows long is 32-bit. Match Torch's kInt64
    # storage on both the host and CUDA paths, including the depth sentinel.
    for filename in (destination / "lib/custom_rasterizer_kernel").iterdir():
        if filename.suffix not in {".cpp", ".cu"}:
            continue
        text = filename.read_text(encoding="utf-8")
        text = text.replace("data_ptr<long>()", "data_ptr<int64_t>()")
        text = re.sub(r"\blong\s*\*", "int64_t*", text)
        text = text.replace("(long)maxint", "(int64_t)maxint")
        filename.write_text(text, encoding="utf-8")


def compatible_toolsets(installations: list[Path]) -> list[tuple[str, Path, Path]]:
    candidates = []
    for root in installations:
        vcvars = root / "VC/Auxiliary/Build/vcvarsall.bat"
        if not vcvars.is_file():
            continue
        for toolset in (root / "VC/Tools/MSVC").glob("*"):
            if not re.fullmatch(r"\d+\.\d+\.\d+", toolset.name):
                continue
            version = tuple(map(int, toolset.name.split(".")))
            compiler = toolset / "bin/Hostx64/x64/cl.exe"
            if (14, 20) <= version < (14, 50) and compiler.is_file():
                candidates.append((toolset.name, vcvars, compiler))
    return sorted(candidates, key=lambda c: tuple(map(int, c[0].split("."))), reverse=True)


def installations(env: dict[str, str]) -> list[Path]:
    program_dirs = [Path(env[k]) for k in ("PROGRAMFILES(X86)", "PROGRAMFILES") if env.get(k)]
    locator = shutil.which("vswhere", path=env.get("PATH"))
    if not locator:
        locator = next((str(p / "Microsoft Visual Studio/Installer/vswhere.exe")
                        for p in program_dirs
                        if (p / "Microsoft Visual Studio/Installer/vswhere.exe").is_file()), None)
    roots = []
    if locator:
        result = subprocess.run([locator, "-all", "-products", "*", "-format", "json", "-utf8"],
                                env=env, capture_output=True, encoding="utf-8", check=True, timeout=30)
        roots.extend(Path(item["installationPath"]) for item in json.loads(result.stdout))
    # Also supports offline/older installations without vswhere.
    for directory in program_dirs:
        roots.extend((directory / "Microsoft Visual Studio").glob("*/*"))
    if env.get("VSINSTALLDIR"):
        roots.append(Path(env["VSINSTALLDIR"]))
    return list(dict.fromkeys(roots))


def activate(vcvars: Path, version: str, env: dict[str, str]) -> dict[str, str]:
    # An already active VS 18 must not make vcvarsall skip initialization.
    clean = {k: v for k, v in env.items() if not k.startswith(("VSCMD_", "__VSCMD", "__VCVARS"))
             and k not in {"VSINSTALLDIR", "VCINSTALLDIR", "VCTOOLSINSTALLDIR", "VCTOOLSVERSION",
                           "VISUALSTUDIOVERSION", "INCLUDE", "LIB", "LIBPATH"}}
    if any(c in str(vcvars) for c in ('"', '%', '!', '\r', '\n')):
        raise RuntimeError("Visual Studio installation path contains unsupported shell characters")
    comspec = env.get("COMSPEC", "cmd.exe")
    command = f'"{comspec}" /d /u /s /c ""{vcvars}" x64 -vcvars_ver={version} >nul && set"'
    result = subprocess.run(command, env=clean, capture_output=True, encoding="utf-16le",
                            errors="replace", check=True, timeout=60)
    activated = dict(clean)
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key:
            activated[key.upper()] = value
    return activated


def build_environment(inherited: dict[str, str] | None = None, *, cuda: str = "12.8") -> dict[str, str]:
    env = {k.upper(): v for k, v in (os.environ if inherited is None else inherited).items()}
    if sys.platform != "win32":
        raise RuntimeError("The MSVC toolchain helper is Windows-only")
    if cuda != "12.8":
        raise RuntimeError(f"No MSVC selection policy for CUDA {cuda}")
    nvcc = shutil.which("nvcc", path=env.get("PATH"))
    if not nvcc:
        raise RuntimeError("CUDA Toolkit 12.8 (nvcc) is missing; repair Pinokio's AI prerequisites")
    output = subprocess.run([nvcc, "--version"], env=env, capture_output=True,
                            text=True, check=True, timeout=30).stdout
    if not re.search(r"release " + re.escape(cuda) + r"(?:,|\s)", output):
        raise RuntimeError(f"Hunyuan3D requires CUDA Toolkit {cuda}; selected nvcc is {nvcc}. "
                           "Select the matching toolkit in Pinokio before retrying Install.")
    cuda_root = Path(nvcc).resolve().parent.parent
    # NVIDIA's installer uses lib/x64; Pinokio's conda toolkit uses lib.
    cuda_lib = next((p for p in (cuda_root / "lib/x64", cuda_root / "lib")
                     if (p / "cudart.lib").is_file()), None)
    if not (cuda_root / "include/cuda.h").is_file() or cuda_lib is None:
        raise RuntimeError(f"Incomplete CUDA Toolkit at {cuda_root}; headers and x64 libraries are required")
    candidates = compatible_toolsets(installations(env))
    failures = []
    for version, vcvars, compiler in candidates:
        try:
            selected = activate(vcvars, version, env)
            selected["PATH"] = str(compiler.parent) + os.pathsep + selected.get("PATH", "")
            if not all(selected.get(name) for name in ("INCLUDE", "LIB")):
                raise RuntimeError("vcvarsall did not provide Windows SDK include/library paths")
            selected["LIB"] = str(cuda_lib) + os.pathsep + selected["LIB"]
            selected.update({"CUDA_HOME": str(cuda_root), "CUDA_PATH": str(cuda_root),
                             "DISTUTILS_USE_SDK": "1", "MSSDK": "1",
                             "CC": str(compiler), "CXX": str(compiler),
                             "NVCC_CCBIN": str(compiler.parent)})
            print(f"[Hunyuan3D] CUDA {cuda}; MSVC {version}: {compiler}", flush=True)
            return selected
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            failures.append(f"MSVC {version}: {exc}")
    detail = " ".join(failures)
    raise RuntimeError("No usable CUDA 12.8-compatible MSVC x64 toolset. "
                       "Install Visual Studio 2022 Build Tools with MSVC v143 (14.3x/14.4x) "
                       "or VS 2019 MSVC v142, plus the Windows SDK, then retry Install. "
                       "VS 18 / MSVC 14.50+ alone is incompatible. " + detail)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cuda", default="12.8")
    parser.add_argument("--script", help="Run a Python native-build helper in the selected environment")
    args = parser.parse_args()
    try:
        env = build_environment(cuda=args.cuda)
        if args.script:
            subprocess.run([sys.executable, args.script], env=env, check=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Error: HOCUS_RUNTIME_FAILED. {exc}") from exc


if __name__ == "__main__":
    main()
