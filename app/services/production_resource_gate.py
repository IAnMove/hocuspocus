"""Optional per-admission resource checks for productions on a shared workstation."""
from __future__ import annotations

import os
import logging
import shutil
import subprocess
import time
from collections.abc import Callable
from types import SimpleNamespace

from services.production_control import Cancelled, sleep_until
from services.world3d_renderer_support import scene_render_device

GPU_OPERATIONS = frozenset({"generation.music", "generation.image", "generation.speech", "generation.sfx",
                            "generate", "scenes.world3d.export", "scenes.video2d.export"})
GPU_WAIT_ENV = "HOCUS_PRODUCTION_GPU_WAIT_SECONDS"
DEFAULT_GPU_WAIT_SECONDS = 3600.0
GPU_POLL_SECONDS = 30.0


class ResourceUnavailable(ValueError):
    """The workstation, not the request, stops this admission: the disk is low or the GPU stayed busy."""


def gpu_wait_seconds() -> float:
    """How long one admission waits for other GPU jobs before it fails. ``0`` waits without a limit."""
    raw = os.environ.get(GPU_WAIT_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_GPU_WAIT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_GPU_WAIT_SECONDS
    return value if 0 <= value < float("inf") else DEFAULT_GPU_WAIT_SECONDS


def guard_workspace_mcp(mcp, workspace_dir, *, cancelled: Callable[[], bool] | None = None, **probes):
    """Apply the same admission policy to each workspace-scoped Series Lab call.

    ``cancelled`` tells whether the job making the call was asked to stop; it ends a GPU wait early."""
    def call(operation, arguments):
        if operation not in GPU_OPERATIONS:
            return mcp(operation, arguments)
        workspace = (arguments.get("input") or {}).get("workspace")
        if not isinstance(workspace, str) or not workspace.strip():
            raise ValueError("resource_workspace_required: use an explicit workspace")
        context = SimpleNamespace(root=workspace_dir(workspace), log=logging.getLogger(__name__).info,
                                  _cancel=SimpleNamespace(is_set=cancelled) if cancelled else None)
        return guard_mcp(context, mcp, **probes)(operation, arguments)
    return call


def external_gpu_jobs(report: str, own_pid: int, limit_mb: float):
    busy = []
    for line in report.splitlines():
        fields = line.split(",")
        if len(fields) != 2:
            raise ValueError("resource_probe_failed: invalid nvidia-smi response")
        pid, memory = int(fields[0].strip()), float(fields[1].strip())
        if pid != own_pid and memory > limit_mb:
            busy.append(pid)
    return busy


def _check_disk(production, run, usage, minimum: float) -> None:
    report = run(["df", "-h", str(production.root)], capture_output=True, text=True, timeout=10, check=True)
    free = usage(production.root).free / 1024 ** 3
    production.log(f"resource df: {report.stdout.splitlines()[-1]}")
    if free < minimum:
        raise ResourceUnavailable(f"resource_disk_low: {free:.2f} GiB free; need {minimum:g}. Stop and ask before deleting files.")


def _busy_gpu(production, run, limit: float) -> list[int]:
    report = run(["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"],
                 capture_output=True, text=True, timeout=10, check=True)
    busy = external_gpu_jobs(report.stdout.strip(), os.getpid(), limit) if report.stdout.strip() else []
    production.log(f"resource nvidia-smi: {report.stdout.strip() or 'no GPU jobs'}")
    return busy


def _pause(production, seconds: float, sleep) -> None:
    """Sleep before the next GPU probe. A cancel of the production (``production._cancel``) ends the wait at once."""
    try:
        sleep_until(getattr(production, "_cancel", None), seconds, sleep)
    except Cancelled:
        production.log("resource waiting: cancelled")
        raise Cancelled("Cancelled while waiting for the GPU") from None


def guard_mcp(production, mcp, *, run=subprocess.run, usage=shutil.disk_usage, sleep=time.sleep, clock=time.monotonic):
    def call(operation, arguments):
        minimum = float(os.environ.get("HOCUS_PRODUCTION_MIN_FREE_GB", "0"))
        limit = float(os.environ.get("HOCUS_PRODUCTION_EXTERNAL_VRAM_MB", "0"))
        if operation in {"scenes.world3d.export", "scenes.video2d.export"} and scene_render_device() == "cpu":
            limit = 0  # The owned browser forces SwiftShader and H.264 uses libx264.
        if operation not in GPU_OPERATIONS or (minimum <= 0 and limit <= 0):
            return mcp(operation, arguments)
        patience, started = gpu_wait_seconds(), None
        while True:
            if minimum > 0:
                _check_disk(production, run, usage, minimum)
            busy = _busy_gpu(production, run, limit) if limit > 0 else []
            if not busy:
                return mcp(operation, arguments)
            if started is None:
                started = clock()
                production.log(f"resource waiting: external GPU jobs {busy} exceed {limit:g} MiB")
            waited = clock() - started
            if patience and waited >= patience:
                raise ResourceUnavailable(
                    f"resource_gpu_busy: external GPU jobs {busy} still use more than {limit:g} MiB after "
                    f"{waited / 60:.0f} min ({GPU_WAIT_ENV}={patience:g}). Resume when the GPU is free.")
            _pause(production, min(GPU_POLL_SECONDS, patience - waited) if patience else GPU_POLL_SECONDS, sleep)
    return call
