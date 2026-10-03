"""Optional per-admission resource checks for productions on a shared workstation."""
from __future__ import annotations

import os
import shutil
import subprocess
import time

from services.world3d_renderer_support import scene_render_device

GPU_OPERATIONS = frozenset({"generation.music", "generation.image", "generate", "scenes.world3d.export", "scenes.video2d.export"})


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


def guard_mcp(production, mcp, *, run=subprocess.run, usage=shutil.disk_usage, sleep=time.sleep):
    def call(operation, arguments):
        minimum = float(os.environ.get("HOCUS_PRODUCTION_MIN_FREE_GB", "0"))
        limit = float(os.environ.get("HOCUS_PRODUCTION_EXTERNAL_VRAM_MB", "0"))
        if operation in {"scenes.world3d.export", "scenes.video2d.export"} and scene_render_device() == "cpu":
            limit = 0  # The owned browser forces SwiftShader and H.264 uses libx264.
        if operation not in GPU_OPERATIONS or (minimum <= 0 and limit <= 0):
            return mcp(operation, arguments)
        waiting = False
        while True:
            if minimum > 0:
                report = run(["df", "-h", str(production.root)], capture_output=True, text=True, timeout=10, check=True)
                free = usage(production.root).free / 1024 ** 3
                production.log(f"resource df: {report.stdout.splitlines()[-1]}")
                if free < minimum:
                    raise ValueError(f"resource_disk_low: {free:.2f} GiB free; need {minimum:g}. Stop and ask before deleting files.")
            if limit > 0:
                report = run(["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, check=True)
                busy = external_gpu_jobs(report.stdout.strip(), os.getpid(), limit) if report.stdout.strip() else []
                production.log(f"resource nvidia-smi: {report.stdout.strip() or 'no GPU jobs'}")
                if busy:
                    if not waiting:
                        production.log(f"resource waiting: external GPU jobs {busy} exceed {limit:g} MiB")
                    waiting = True
                    sleep(30)
                    continue
            return mcp(operation, arguments)
    return call
