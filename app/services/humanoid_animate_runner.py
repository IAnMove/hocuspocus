"""Run the CPU humanoid animate worker (``services.humanoid_rig.worker`` in animate mode) and read its answer.

The app process does not import pygltflib: the worker runs in the rigging interpreter (``rig_service.cpu_worker_python``).
``model3d.animate`` and the seated clips of Video 3D scenes (``world3d_rest_place``) both call ``execute_animate``.
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path

_REFUSAL_CODES = ("not_humanoid", "invalid_input")
logger = logging.getLogger(__name__)


class AnimateRefused(ValueError):
    """The worker declined the source or the animation file; the same request always fails the same way."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _python() -> Path:
    from services.rig_service import cpu_worker_python

    python = cpu_worker_python()
    if python is None:
        raise RuntimeError("Humanoid rig runtime is not installed")
    return python


def _worker_payload(completed: subprocess.CompletedProcess[str]) -> dict:
    line = next((item for item in reversed(completed.stdout.splitlines()) if item.startswith("MAESTRO_RESULT ")), "")
    if not line:
        detail = (completed.stderr or completed.stdout or "").strip()[:400]
        raise RuntimeError(detail or f"Humanoid animate worker exited {completed.returncode}")
    payload = json.loads(line[len("MAESTRO_RESULT "):])
    if payload.get("ok"):
        return payload
    code = str(payload.get("error") or "rig_failed")
    reason = str(payload.get("reason") or code)
    if code in _REFUSAL_CODES:
        raise AnimateRefused(code, reason if code == "invalid_input" else f"{code}: {reason}")
    logger.warning("Humanoid animate worker failed: %s\n%s", reason, (completed.stderr or "")[-4000:])
    raise RuntimeError(f"Humanoid animate worker failed: {reason}")


def execute_animate(request: dict, output: Path, *, python: Path | None = None) -> dict:
    """Run the CPU worker. The app process does not import pygltflib."""
    from services.rig_service import APP_DIR
    from services.runtime_environment import isolated_environment

    python = python or _python()
    env = isolated_environment(python)
    env["PYTHONUNBUFFERED"] = "1"
    with tempfile.TemporaryDirectory(prefix="humanoid-animate-") as folder:
        request_path = Path(folder) / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        try:
            completed = subprocess.run(
                [str(python), "-m", "services.humanoid_rig.worker", "--request", str(request_path), "--output", str(output)],
                cwd=str(APP_DIR),
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Humanoid animate worker timed out") from exc
    return _worker_payload(completed)
