"""Run uv only against the selected engine, with explicit dependency constraints."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from services.runtime_environment import isolated_environment  # noqa: E402
from services.runtime_profiles import recipe  # noqa: E402

# Wheels whose only published Linux build carries a stale CPython tag but loads
# its native library through ctypes, so it runs on every supported Python.
# decord 0.6.0 ships only cp36-cp36m-manylinux2010 wheels; bpy 4.2 (UniRig)
# is built for Python 3.11 but its wheel is tagged cp39.
TAG_MISMATCH_ALLOWED = {"decord", "bpy"}
_PLATFORM_MISMATCH = re.compile(r"^The package `([^`]+)` was built for a different platform$")


def check_passes(output: str) -> bool:
    """Accept uv pip check output whose only findings are allowed tag mismatches."""
    findings = [line.strip() for line in output.splitlines()
                if line.strip() and not line.startswith(("Using Python", "Checked ", "Found "))]
    for finding in findings:
        match = _PLATFORM_MISMATCH.match(finding)
        if not match or match.group(1).lower() not in TAG_MISMATCH_ALLOWED:
            return False
    return True


def command(engine: str, arguments: list[str]) -> tuple[list[str], dict[str, str]]:
    spec = recipe(engine, sys.platform)
    if Path(sys.prefix).resolve() != (ROOT / spec["env"]).resolve():
        raise RuntimeError(f"Refusing package changes outside {engine}'s environment")
    if not arguments or arguments[0] not in {"install", "uninstall", "check"}:
        raise ValueError("Expected uv pip install, uninstall or check")
    forbidden = {"--python", "--target", "--prefix", "--system", "--user", "-p", "-t"}
    if any(arg.split("=", 1)[0] in forbidden for arg in arguments):
        raise ValueError("The engine recipe owns the package destination")
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Pinokio's uv executable is unavailable")
    env = isolated_environment(Path(sys.executable))
    env["PIP_CONFIG_FILE"] = os.devnull
    constraints = ROOT / spec["constraintFile"]
    env["PIP_CONSTRAINT"] = str(constraints)
    args = [uv, "--no-config", "pip", *arguments, "--python", sys.executable]
    if arguments[0] == "install":
        args.extend(["--constraint", str(constraints),
                     "--default-index", "https://pypi.org/simple",
                     "--index", f"https://download.pytorch.org/whl/cu{spec['cuda'].replace('.', '')}",
                     "--index-strategy", "unsafe-best-match"])
        lock = ROOT / "app" / "runtime" / "locks" / f"{sys.platform}-{engine}.txt"
        if not lock.is_file():
            raise RuntimeError(f"Missing dependency lock for {engine}")
        args.extend(["--constraint", str(lock)])
        env["PIP_CONSTRAINT"] = str(lock)
    return args, env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    cmd, env = command(args.engine, arguments)
    if arguments[0] == "check":
        result = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        sys.stdout.write(result.stdout)
        if result.returncode and check_passes(result.stdout):
            print("Ignoring wheel tag mismatch for: " + ", ".join(sorted(TAG_MISMATCH_ALLOWED)))
            return
    else:
        result = subprocess.run(cmd, env=env)
    if result.returncode:
        raise SystemExit("Error: HOCUS_RUNTIME_FAILED. Package operation failed; environment was not verified.")


if __name__ == "__main__":
    main()
