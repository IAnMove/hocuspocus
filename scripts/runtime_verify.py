"""Verify the active managed engine before recording installation success."""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from services.runtime_profiles import dependency_fingerprint, recipe  # noqa: E402
from services.runtime_sources import sources_current  # noqa: E402


def inspect_environment(engine: str) -> dict:
    spec = recipe(engine, sys.platform)
    expected_prefix = (ROOT / spec["env"]).resolve()
    if Path(sys.prefix).resolve() != expected_prefix:
        raise RuntimeError(f"Wrong environment for {engine}: {sys.prefix}; expected {expected_prefix}")
    if f"{sys.version_info.major}.{sys.version_info.minor}" != spec["python"]:
        raise RuntimeError(f"{engine} requires Python {spec['python']}")
    pins = {**spec["constraints"], **{k: spec[k] for k in ("torch", "torchvision", "torchaudio") if k in spec}}
    for name, wanted in pins.items():
        actual = importlib.metadata.version(name)
        if actual.split("+", 1)[0] != wanted:
            raise RuntimeError(f"{engine}: {name} is {actual}; recipe requires {wanted}")
    return {d.metadata["Name"].lower().replace("_", "-"): d.version
            for d in importlib.metadata.distributions() if d.metadata.get("Name")}


def verify(engine: str, *, cuda: bool = True) -> dict:
    spec = recipe(engine, sys.platform)
    if not sources_current(spec.get("vendors", [])):
        raise RuntimeError(f"{engine}: pinned source checkout is incomplete or has a different revision")
    installed = inspect_environment(engine)
    if not spec.get("cuda"):
        return {"engine": engine, "profile": spec["id"], "python": spec["python"],
                "prefix": str((ROOT / spec["env"]).resolve()), "packages": installed, "cuda": None,
                "cudaCalculation": False, "modelsExecuted": False,
                "fingerprint": dependency_fingerprint(engine, sys.platform)}
    torch = importlib.import_module("torch")
    if torch.version.cuda != spec["cuda"]:
        raise RuntimeError(f"{engine}: expected CUDA {spec['cuda']} wheel; got {torch.version.cuda}")
    for name in ("torchvision", "torchaudio"):
        if name in spec:
            importlib.import_module(name)
    if cuda:
        if not torch.cuda.is_available():
            raise RuntimeError(f"{engine}: CUDA is unavailable; check the NVIDIA driver")
        result = (torch.ones(1, device="cuda") + 1).item()
        if result != 2:
            raise RuntimeError(f"{engine}: CUDA calculation failed")
    return {"engine": engine, "profile": spec["id"], "python": spec["python"],
            "prefix": str((ROOT / spec["env"]).resolve()), "packages": installed, "cuda": torch.version.cuda,
            "cudaCalculation": cuda, "modelsExecuted": False,
            "fingerprint": dependency_fingerprint(engine, sys.platform)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--no-cuda", action="store_true", help="Dependency-only CI check; never used by Install")
    parser.add_argument("--inspect", action="store_true", help="Check installed metadata against receipt without loading Torch")
    args = parser.parse_args()
    target = ROOT / recipe(args.engine, sys.platform)["env"] / ".hocus-runtime-profile.json"
    if args.inspect:
        packages = inspect_environment(args.engine)
        receipt = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or receipt.get("packages") != packages:
            raise RuntimeError("Installed package set changed since runtime verification")
        return
    result = verify(args.engine, cuda=not args.no_cuda)
    temporary = target.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temporary.replace(target)
    print(f"[Runtime] Verified {result['profile']}: dependencies, imports and CUDA={result['cudaCalculation']}")


if __name__ == "__main__":
    main()
