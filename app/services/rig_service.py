"""Rig & animate job manager for Maestro's 3D outputs.

Runs the procedural rigging worker (app/services/hunyuan3d/rig_worker.py)
in the Hunyuan3D isolated environment. Jobs are CPU-only and finish in
seconds, but the lifecycle mirrors model3d_service: short-lived worker
subprocess, MAESTRO_EVENT progress streaming, on-disk pid files with a
startup reaper, watchdog timeouts and a bounded in-memory registry.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SERVICE_DIR = Path(__file__).resolve().parent / "hunyuan3d"
ENV_DIR = SERVICE_DIR / "env"
INSTALL_MARKER = ENV_DIR / ".maestro_hunyuan3d_v1.installed"
WORKER_PATH = SERVICE_DIR / "rig_worker.py"
JOBS_DIR = Path(__file__).resolve().parents[1] / "ckpts" / "rig" / "jobs"

ANIMATIONS: list[dict[str, str]] = [
    {"id": "idle", "label": "Idle Sway", "description": "Gentle side-to-side spine sway, stronger toward the top."},
    {"id": "breathe", "label": "Breathe", "description": "Soft squash-and-stretch breathing loop."},
    {"id": "bounce", "label": "Bounce", "description": "Rhythmic hops with squash on landing."},
    {"id": "spin", "label": "Turntable Spin", "description": "Full 360 degree showcase rotation."},
    {"id": "wobble", "label": "Wobble Dance", "description": "Playful yaw wiggle with sway and a light hop."},
]
ANIMATION_IDS = {item["id"] for item in ANIMATIONS}

_jobs: dict[str, dict[str, Any]] = {}
_processes: dict[str, subprocess.Popen] = {}
_lock = threading.RLock()
_rig_slot = threading.Semaphore(1)

_TERMINAL_STATES = {"completed", "failed", "cancelled"}
_MAX_FINISHED_JOBS = 20
_FINISHED_JOB_TTL_SECONDS = 3600
_MAX_ACTIVE_JOBS = 4
# Rigging is CPU-bound and fast; anything slower than this is wedged.
_WORKER_INACTIVITY_LIMIT_SECONDS = 2 * 60
_WORKER_TIME_LIMIT_SECONDS = 10 * 60


def _python_path() -> Path | None:
    candidates = [ENV_DIR / "python.exe", ENV_DIR / "bin" / "python"]
    return next((path for path in candidates if path.is_file()), None)


def installation_status() -> dict[str, Any]:
    python_path = _python_path()
    installed = bool(python_path and INSTALL_MARKER.is_file() and WORKER_PATH.is_file())
    return {
        "installed": installed,
        "install_hint": None if installed else "Run Maestro's standard Install or Update action (the rig worker shares the Hunyuan3D runtime).",
    }


def capabilities() -> dict[str, Any]:
    with _lock:
        active = sum(1 for job in _jobs.values() if job["status"] in {"queued", "running"})
    status = installation_status()
    return {
        "engines": [
            {
                "id": "procedural",
                "label": "Procedural (fast)",
                "description": "Spine-chain skeleton with distance-based skinning. Works on any object; no extra downloads.",
                "installed": status["installed"],
                "install_hint": status["install_hint"],
            },
        ],
        "animations": ANIMATIONS,
        "default_spine_joints": 5,
        "active_jobs": active,
    }


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key not in {"request", "process"}}


def _prune_finished_jobs_locked() -> None:
    now = time.time()
    finished = sorted(
        (item for item in _jobs.items() if item[1]["status"] in _TERMINAL_STATES),
        key=lambda item: item[1].get("updated_at", 0.0),
        reverse=True,
    )
    for index, (job_id, job) in enumerate(finished):
        if index >= _MAX_FINISHED_JOBS or now - job.get("updated_at", 0.0) > _FINISHED_JOB_TTL_SECONDS:
            _jobs.pop(job_id, None)


def start_job(*, body: dict[str, Any], source_path: str, output_dir: str) -> dict[str, Any]:
    runtime = installation_status()
    if not runtime["installed"]:
        raise RuntimeError(runtime["install_hint"])

    with _lock:
        _prune_finished_jobs_locked()
        active = sum(1 for job in _jobs.values() if job["status"] in {"queued", "running"})
    if active >= _MAX_ACTIVE_JOBS:
        raise ValueError("Too many queued rig jobs; wait for the current ones to finish or cancel them")

    engine = str(body.get("engine") or "procedural")
    if engine != "procedural":
        raise ValueError(f"Unknown rig engine: {engine}")
    animations = body.get("animations") or [item["id"] for item in ANIMATIONS]
    if not isinstance(animations, list) or not animations:
        raise ValueError("Select at least one animation")
    invalid = [item for item in animations if item not in ANIMATION_IDS]
    if invalid:
        raise ValueError(f"Unknown animations: {', '.join(map(str, invalid))}")
    try:
        spine_joints = max(2, min(9, int(body.get("spine_joints") or 5)))
    except (TypeError, ValueError):
        spine_joints = 5

    request_data = {
        "engine": engine,
        "source": os.path.abspath(source_path),
        "animations": [str(item) for item in animations],
        "spine_joints": spine_joints,
    }
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0.0,
        "phase": "queued",
        "message": "Queued rig job",
        "error": None,
        "filename": None,
        "url": None,
        "engine": engine,
        "source_file": os.path.basename(source_path),
        "created_at": time.time(),
        "updated_at": time.time(),
        "request": request_data,
    }
    with _lock:
        _jobs[job_id] = job
        initial_response = _public_job(dict(job))
    threading.Thread(target=_run_job, args=(job_id, os.path.abspath(output_dir)), daemon=True).start()
    return initial_response


def _update_job(job_id: str, **updates: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = time.time()
        if job["status"] in _TERMINAL_STATES:
            job.pop("request", None)


def _run_job(job_id: str, output_dir: str) -> None:
    _rig_slot.acquire()
    try:
        with _lock:
            if _jobs.get(job_id, {}).get("status") == "cancelled":
                return
        _run_job_serialized(job_id, output_dir)
    finally:
        _rig_slot.release()


def _cleanup_partial_output(output_path: Path) -> None:
    for stale in (output_path, output_path.with_suffix(".preview.png")):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass


def _run_job_serialized(job_id: str, output_dir: str) -> None:
    python_path = _python_path()
    if not python_path:
        _update_job(job_id, status="failed", phase="failed", error="Rig runtime is not installed")
        return

    with _lock:
        job = _jobs.get(job_id)
        request_data = job.get("request") if job else None
    if not request_data:
        return
    source = Path(request_data["source"])
    stamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
    safe_source = re.sub(r"[^a-zA-Z0-9._-]+", "-", source.stem)[:48]
    filename = f"{stamp}_rigged_{safe_source}_{job_id[:8]}.glb"
    output_path = Path(output_dir) / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    request_path = JOBS_DIR / f"{job_id}.json"
    request_path.write_text(json.dumps(request_data, indent=2), encoding="utf-8")
    pid_path = JOBS_DIR / f"{job_id}.pid"

    command = [str(python_path), str(WORKER_PATH), "--request", str(request_path), "--output", str(output_path)]
    env = os.environ.copy()
    env.update({"PYTHONUNBUFFERED": "1"})
    lines: list[str] = []
    result_summary: dict[str, Any] = {}
    try:
        _update_job(job_id, status="running", phase="starting", message="Starting rig worker", progress=0.02)
        process = subprocess.Popen(
            command,
            cwd=str(SERVICE_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        with _lock:
            _processes[job_id] = process
        try:
            pid_path.write_text(str(process.pid), encoding="utf-8")
        except OSError:
            pass

        activity = {"at": time.monotonic()}
        deadline = time.monotonic() + _WORKER_TIME_LIMIT_SECONDS
        timeout_reason: dict[str, str] = {}

        def _watchdog() -> None:
            while process.poll() is None:
                time.sleep(5)
                now = time.monotonic()
                if now - activity["at"] > _WORKER_INACTIVITY_LIMIT_SECONDS:
                    timeout_reason["error"] = f"Rig worker produced no output for {_WORKER_INACTIVITY_LIMIT_SECONDS // 60} minutes"
                elif now > deadline:
                    timeout_reason["error"] = f"Rig job exceeded the {_WORKER_TIME_LIMIT_SECONDS // 60} minute limit"
                else:
                    continue
                process.kill()
                return

        threading.Thread(target=_watchdog, daemon=True).start()

        assert process.stdout is not None
        for raw_line in process.stdout:
            activity["at"] = time.monotonic()
            line = raw_line.rstrip()
            if not line:
                continue
            print(f"[Rig] {line}")
            lines.append(line)
            lines = lines[-40:]
            if line.startswith("MAESTRO_EVENT "):
                try:
                    event = json.loads(line[len("MAESTRO_EVENT "):])
                    _update_job(
                        job_id,
                        phase=str(event.get("phase") or "running"),
                        message=str(event.get("message") or "Rigging model"),
                        progress=max(0.0, min(0.99, float(event.get("progress", 0.0)))),
                    )
                except Exception:
                    pass
            elif line.startswith("MAESTRO_RESULT "):
                try:
                    result_summary = json.loads(line[len("MAESTRO_RESULT "):])
                except Exception:
                    pass

        exit_code = process.wait()
        with _lock:
            status = _jobs.get(job_id, {}).get("status")
        if status == "cancelled":
            _cleanup_partial_output(output_path)
            return
        if timeout_reason:
            raise RuntimeError(timeout_reason["error"])
        if exit_code != 0 or not output_path.is_file():
            detail = "\n".join(lines[-15:]) or f"Rig worker exited with code {exit_code}"
            raise RuntimeError(detail[-4000:])

        sidecar = output_path.with_suffix(".meta.json")
        sidecar.write_text(
            json.dumps(
                {
                    "generation_mode": "model3d",
                    "mode": "model3d",
                    "job_id": job_id,
                    "created_at": time.time(),
                    "params": {
                        "model_type": "rig-procedural",
                        "rigged": True,
                        "rig_engine": request_data["engine"],
                        "source_file": source.name,
                        "animations": result_summary.get("animations") or request_data["animations"],
                        "spine_joints": request_data["spine_joints"],
                        "prompt": f"Rigged from {source.name}",
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        # Reuse the source's gallery preview for the rigged copy.
        source_preview = source.with_suffix(".preview.png")
        if source_preview.is_file():
            try:
                shutil.copyfile(source_preview, output_path.with_suffix(".preview.png"))
            except OSError:
                pass
        _update_job(
            job_id,
            status="completed",
            phase="completed",
            message="Rigged model saved",
            progress=1.0,
            filename=filename,
            url=f"/api/v1/file/{filename}",
            size=output_path.stat().st_size,
            animations=result_summary.get("animations") or request_data["animations"],
        )
    except Exception as exc:
        with _lock:
            cancelled = _jobs.get(job_id, {}).get("status") == "cancelled"
        if not cancelled:
            _update_job(job_id, status="failed", phase="failed", message="Rigging failed", error=str(exc))
        _cleanup_partial_output(output_path)
    finally:
        with _lock:
            _processes.pop(job_id, None)
        for stale_path in (request_path, pid_path):
            try:
                stale_path.unlink(missing_ok=True)
            except Exception:
                pass


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return _public_job(dict(job)) if job else None


def cancel_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        process = _processes.get(job_id)
        if not job:
            return None
        if job["status"] in _TERMINAL_STATES:
            return _public_job(dict(job))
        job.update({
            "status": "cancelled",
            "phase": "cancelled",
            "message": "Rig job cancelled",
            "updated_at": time.time(),
        })
        job.pop("request", None)
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    return get_job(job_id)


def cancel_all_jobs() -> int:
    with _lock:
        active_ids = [job_id for job_id, job in _jobs.items() if job["status"] in {"queued", "running"}]
    for job_id in active_ids:
        cancel_job(job_id)
    return len(active_ids)


def _is_rig_worker(pid: int) -> bool:
    proc_cmdline = Path("/proc") / str(pid) / "cmdline"
    try:
        if proc_cmdline.is_file():
            cmdline = proc_cmdline.read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
            return WORKER_PATH.name in cmdline and "hunyuan3d" in cmdline
    except OSError:
        return False
    try:
        import psutil

        cmdline = " ".join(psutil.Process(pid).cmdline())
        return WORKER_PATH.name in cmdline and "hunyuan3d" in cmdline
    except Exception:
        return False


def _reap_stale_jobs() -> None:
    if not JOBS_DIR.is_dir():
        return
    for pid_path in JOBS_DIR.glob("*.pid"):
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = 0
        if pid > 0 and _is_rig_worker(pid):
            print(f"[Rig] Terminating orphaned rig worker from a previous run (pid {pid})")
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        try:
            pid_path.unlink(missing_ok=True)
        except OSError:
            pass
    for request_path in JOBS_DIR.glob("*.json"):
        try:
            request_path.unlink(missing_ok=True)
        except OSError:
            pass


atexit.register(cancel_all_jobs)

try:
    _reap_stale_jobs()
except Exception as exc:  # Never block Maestro startup on cleanup.
    print(f"[Rig] Stale job cleanup skipped: {exc}")
