"""Make-It-Animatable (engine ``mia``): an optional Linux rig for humanoids.

The neural step and the Blender export live in the vendored checkout. This
module only answers whether that checkout is installed, and which humanoid
refusals should name it. The server never switches engines.
"""

from __future__ import annotations

from pathlib import Path

ENGINE = "mia"
SUGGEST_REASONS = frozenset({"turned", "hands_stuck", "not_upright"})
SUGGEST_HINT = (
    "Make-It-Animatable is installed and can rig a humanoid in this pose. "
    "Choose the Make-It-Animatable engine and run again. The engine was not switched."
)
INSTALL_HINT = (
    "Open HocusPocus Lab in Pinokio and run 'Install Make-It-Animatable'. "
    "Linux only. The demo weights are about 2.33 GB on disk."
)

_RIGGING_DIR = Path(__file__).resolve().parent
_MIA_DIR = _RIGGING_DIR.parent / "mia"
ENV_DIR = _MIA_DIR / "env"
MARKER = ENV_DIR / ".maestro_mia_v1.installed"
VENDOR_DIR = _MIA_DIR / "vendor" / "Make-It-Animatable"
WORKER_PATH = _RIGGING_DIR / "rig_worker_mia.py"
CWD = _RIGGING_DIR

# Demo checkpoints from the pinned README (``output/best/new``), not the v2 set.
WEIGHT_RELATIVE = (
    "output/best/new/bw.pth",
    "output/best/new/bw_normal.pth",
    "output/best/new/joints.pth",
    "output/best/new/joints_coarse.pth",
    "output/best/new/pose.pth",
)
TEMPLATE_RELATIVE = "data/Mixamo/bones.fbx"

# UniRig and this engine take the local GPU lane. Procedural and humanoid stay on CPU.
GPU_RIG_ENGINES = frozenset({ENGINE, "unirig"})


def uses_gpu(engine: str) -> bool:
    return engine in GPU_RIG_ENGINES


def python_path() -> Path | None:
    from services.runtime_environment import python_path as managed_python_path
    from services.runtime_profiles import managed_ready

    candidate = managed_python_path(ENV_DIR)
    if candidate.is_file() and managed_ready(ENGINE):
        return candidate
    return None


def weights_ready() -> bool:
    needed = (*WEIGHT_RELATIVE, TEMPLATE_RELATIVE)
    return all((VENDOR_DIR / relative).is_file() for relative in needed)


def installed() -> bool:
    ready = python_path() and MARKER.is_file() and VENDOR_DIR.is_dir() and WORKER_PATH.is_file()
    return bool(ready and weights_ready())


def installation_status() -> dict:
    ready = installed()
    return {"installed": ready, "install_hint": None if ready else INSTALL_HINT}


def capability() -> dict:
    status = installation_status()
    return {
        "id": ENGINE,
        "label": "Make-It-Animatable",
        "description": (
            "Predicts a Mixamo-style skeleton for a humanoid in any pose, then bakes the clip library. "
            "Linux only. Use it when the standard humanoid rig refuses a turned, hands-down or not-upright mesh."
        ),
        "installed": status["installed"],
        "install_hint": status["install_hint"],
    }


def suggestion_hint(engine: str, code: object, reason: object) -> str | None:
    """Sentence to append when the humanoid rig refused a pose this engine can try.

    ``None`` unless that engine is installed, so a machine without it keeps today's error text.
    """
    if engine != "humanoid" or code != "not_humanoid" or reason not in SUGGEST_REASONS:
        return None
    if not installed():
        return None
    return SUGGEST_HINT
