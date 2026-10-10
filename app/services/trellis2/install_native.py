"""Build the pinned upstream CUDA packages only in TRELLIS.2's environment."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "scripts"))
from services.runtime_profiles import recipe
from runtime_pip import command


def build_environment(prefix: Path, inherited: dict[str, str]) -> dict[str, str]:
    env = dict(inherited)
    stubs = [prefix / "lib/stubs", prefix / "targets/x86_64-linux/lib/stubs"]
    stubs = [path for path in stubs if (path / "libcuda.so").is_file()]
    if not stubs:
        raise RuntimeError("CUDA Toolkit driver link stubs are missing; repair the TRELLIS.2 toolkit")
    env["CUDA_HOME"] = str(prefix)
    # Conda GCC uses a sysroot without the host driver's unversioned libcuda.
    # Link against the Toolkit stub, but never put it on the runtime loader path.
    env["LIBRARY_PATH"] = os.pathsep.join([str(prefix / "lib"), *(str(p) for p in stubs),
                                          *filter(None, env.get("LIBRARY_PATH", "").split(os.pathsep))])
    env.setdefault("MAX_JOBS", "2")
    return env


def main() -> None:
    spec = recipe("trellis2", sys.platform)
    if sys.platform != "linux" or Path(sys.prefix).resolve() != (ROOT / spec["env"]).resolve():
        raise RuntimeError("Build TRELLIS.2 only in its isolated Linux environment")
    nvcc = shutil.which("nvcc")
    if not nvcc:
        raise RuntimeError("CUDA Toolkit 12.4 compiler is missing; install the Pinokio AI bundle")
    version = subprocess.check_output([nvcc, "--version"], text=True)
    if "release 12.4," not in version:
        raise RuntimeError("TRELLIS.2 needs CUDA Toolkit 12.4. Other CUDA runtimes remain isolated.")
    os.environ.update(build_environment(Path(sys.prefix).resolve(), dict(os.environ)))
    vendor = ROOT / "app/services/model3d_runtimes/trellis2/vendor"
    packages = ["flash-attn==2.7.3", str(vendor / "utils3d"), str(vendor / "nvdiffrast"),
                str(vendor / "nvdiffrec"), str(vendor / "CuMesh"), str(vendor / "FlexGEMM"),
                str(vendor / "TRELLIS.2/o-voxel")]
    for package in packages:
        cmd, env = command("trellis2", ["install", "--no-build-isolation", package])
        subprocess.run(cmd, env=env, check=True, cwd=ROOT)


if __name__ == "__main__":
    main()
