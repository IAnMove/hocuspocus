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

# Optional UniRig AI engine: separate Python 3.11 env installed on demand
# through rigging_install.js ("Install AI Rigging (UniRig)" in the menu).
RIGGING_DIR = Path(__file__).resolve().parent / "rigging"
RIGGING_ENV_DIR = RIGGING_DIR / "env"
RIGGING_MARKER = RIGGING_ENV_DIR / ".maestro_rigging_v1.installed"
UNIRIG_WORKER_PATH = RIGGING_DIR / "rig_worker_unirig.py"
UNIRIG_VENDOR_DIR = RIGGING_DIR / "vendor" / "UniRig"
HF_CACHE_DIR = Path(__file__).resolve().parents[1] / "ckpts" / "rig" / "huggingface"

ANIMATIONS: list[dict[str, str]] = [
    {"id": "idle", "label": "Idle Sway", "description": "Gentle side-to-side spine sway, stronger toward the top.", "category": "Ambient"},
    {"id": "breathe", "label": "Breathe", "description": "Soft squash-and-stretch breathing loop.", "category": "Ambient"},
    {"id": "hover", "label": "Hover", "description": "Smooth floating loop for pickups, drones, props and spirits.", "category": "Ambient"},
    {"id": "alert", "label": "Alert Look", "description": "A cautious scan with a small ready-state lean.", "category": "Game"},
    {"id": "walk", "label": "Walk Cycle", "description": "In-place game walk with body bob, yaw and articulated sway.", "category": "Locomotion"},
    {"id": "run", "label": "Run Cycle", "description": "Fast in-place sprint loop with stronger lift and compression.", "category": "Locomotion"},
    {"id": "strafe", "label": "Strafe Loop", "description": "Side-to-side evasive locomotion for gameplay shots.", "category": "Locomotion"},
    {"id": "jump", "label": "Jump", "description": "Anticipation, airborne stretch and a clean landing loop.", "category": "Action"},
    {"id": "attack", "label": "Attack Lunge", "description": "Quick wind-up, forward strike and recovery.", "category": "Action"},
    {"id": "hit", "label": "Hit Reaction", "description": "Sharp sideways recoil followed by recovery to idle.", "category": "Action"},
    {"id": "roll", "label": "Combat Roll", "description": "Full forward tumble suitable for creatures and game props.", "category": "Action"},
    {"id": "charge", "label": "Charge Up", "description": "Escalating pulse and tense sway for power-up moments.", "category": "Action"},
    {"id": "victory", "label": "Victory Jump", "description": "Celebratory jump with a complete showcase turn.", "category": "Cinematic"},
    {"id": "bounce", "label": "Bounce", "description": "Rhythmic hops with squash on landing.", "category": "Stylized"},
    {"id": "spin", "label": "Turntable Spin", "description": "Full 360 degree showcase rotation.", "category": "Cinematic"},
    {"id": "wobble", "label": "Wobble Dance", "description": "Playful yaw wiggle with sway and a light hop.", "category": "Stylized"},
]
ANIMATION_IDS = {item["id"] for item in ANIMATIONS}

# These profiles tune Maestro's procedural chain and guide clip selection.
# They are intentionally not presented as semantic humanoid/creature
# retargeting: the procedural engine still builds a robust single chain,
# while UniRig remains responsible for predicting a richer skeleton.
RIG_PROFILES: list[dict[str, Any]] = [
    {
        "id": "prop",
        "label": "Prop / object",
        "description": "Simple pickups, logos and softly deforming standalone objects.",
        "default_spine_joints": 3,
        "default_axis_mode": "auto",
        "default_weight_falloff": 3.5,
        "recommended_animations": ["hover", "bounce", "spin", "wobble", "charge", "hit"],
        "allowed_animations": [
            "idle", "breathe", "hover", "alert", "jump", "attack", "hit", "roll",
            "charge", "victory", "bounce", "spin", "wobble",
        ],
    },
    {
        "id": "vehicle",
        "label": "Vehicle / mechanical",
        "description": "Ships, cars, robots and hard-surface machinery using a short, stiff dominant-axis chain.",
        "default_spine_joints": 3,
        "default_axis_mode": "auto",
        "default_weight_falloff": 5.5,
        "recommended_animations": ["hover", "alert", "strafe", "attack", "hit", "charge", "spin"],
        "allowed_animations": [
            "idle", "hover", "alert", "strafe", "jump", "attack", "hit", "roll",
            "charge", "victory", "bounce", "spin", "wobble",
        ],
    },
    {
        "id": "humanoid",
        "label": "Humanoid",
        "description": "Upright characters. Uses a denser Y-up body chain; it is a procedural approximation, not semantic limb retargeting.",
        "default_spine_joints": 7,
        "default_axis_mode": "y",
        "default_weight_falloff": 2.4,
        "recommended_animations": [
            "idle", "breathe", "alert", "walk", "run", "strafe", "jump", "attack",
            "hit", "roll", "charge", "victory",
        ],
        "allowed_animations": [item["id"] for item in ANIMATIONS],
    },
    {
        "id": "quadruped",
        "label": "Quadruped / creature",
        "description": "Four-legged and horizontally oriented creatures using a flexible dominant-axis chain.",
        "default_spine_joints": 7,
        "default_axis_mode": "auto",
        "default_weight_falloff": 2.0,
        "recommended_animations": ["idle", "breathe", "alert", "walk", "run", "jump", "attack", "hit", "charge"],
        "allowed_animations": [
            "idle", "breathe", "alert", "walk", "run", "jump", "attack", "hit", "roll",
            "charge", "victory", "bounce", "spin", "wobble",
        ],
    },
    {
        "id": "flying",
        "label": "Flying creature / drone",
        "description": "Birds, winged creatures, ships and drones with a light dominant-axis chain.",
        "default_spine_joints": 5,
        "default_axis_mode": "auto",
        "default_weight_falloff": 2.8,
        "recommended_animations": ["hover", "idle", "alert", "strafe", "attack", "hit", "roll", "charge"],
        "allowed_animations": [
            "idle", "breathe", "hover", "alert", "strafe", "jump", "attack", "hit", "roll",
            "charge", "victory", "bounce", "spin", "wobble",
        ],
    },
    {
        "id": "serpentine",
        "label": "Serpentine / tentacle",
        "description": "Snakes, tails, tentacles and elongated flexible meshes with a long smooth chain.",
        "default_spine_joints": 9,
        "default_axis_mode": "auto",
        "default_weight_falloff": 1.6,
        "recommended_animations": ["idle", "breathe", "hover", "alert", "strafe", "attack", "hit", "charge", "wobble"],
        "allowed_animations": [
            "idle", "breathe", "hover", "alert", "strafe", "attack", "hit", "roll",
            "charge", "victory", "bounce", "spin", "wobble",
        ],
    },
]
RIG_PROFILES_BY_ID = {profile["id"]: profile for profile in RIG_PROFILES}
DEFAULT_RIG_PROFILE = "prop"

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


def _unirig_python_path() -> Path | None:
    candidates = [RIGGING_ENV_DIR / "python.exe", RIGGING_ENV_DIR / "bin" / "python"]
    return next((path for path in candidates if path.is_file()), None)


def installation_status() -> dict[str, Any]:
    python_path = _python_path()
    installed = bool(python_path and INSTALL_MARKER.is_file() and WORKER_PATH.is_file())
    return {
        "installed": installed,
        "install_hint": None if installed else "Run Maestro's standard Install or Update action (the rig worker shares the Hunyuan3D runtime).",
    }


UNIRIG_REPO = "VAST-AI/UniRig"


def is_unirig_downloaded() -> bool:
    """Whether the UniRig weights snapshot is cached locally."""
    repo_cache = HF_CACHE_DIR / "hub" / f"models--{UNIRIG_REPO.replace('/', '--')}" / "snapshots"
    if not repo_cache.is_dir():
        return False
    return any(path.is_dir() for path in repo_cache.iterdir())


def delete_unirig_cache() -> list[str]:
    """Remove the cached UniRig weights (the runtime env stays installed)."""
    repo_cache = HF_CACHE_DIR / "hub" / f"models--{UNIRIG_REPO.replace('/', '--')}"
    if not repo_cache.exists():
        return []
    shutil.rmtree(repo_cache)
    return [UNIRIG_REPO]


def unirig_installation_status() -> dict[str, Any]:
    python_path = _unirig_python_path()
    installed = bool(python_path and RIGGING_MARKER.is_file() and UNIRIG_WORKER_PATH.is_file() and UNIRIG_VENDOR_DIR.is_dir())
    return {
        "installed": installed,
        "install_hint": None if installed else "Open the Maestro item in Pinokio and run 'Install AI Rigging (UniRig)'. Needs an NVIDIA GPU with 8GB+ VRAM; weights (~2GB) download on first use.",
    }


def capabilities() -> dict[str, Any]:
    with _lock:
        active = sum(1 for job in _jobs.values() if job["status"] in {"queued", "running"})
    status = installation_status()
    unirig_status = unirig_installation_status()
    return {
        "engines": [
            {
                "id": "procedural",
                "label": "Procedural (fast)",
                "description": "Spine-chain skeleton with distance-based skinning. Works on any object; no extra downloads.",
                "installed": status["installed"],
                "install_hint": status["install_hint"],
            },
            {
                "id": "unirig",
                "label": "UniRig (AI)",
                "description": "VAST-AI UniRig predicts a real skeleton and learned skinning weights. Best for characters and creatures; ~8GB VRAM.",
                "installed": unirig_status["installed"],
                "install_hint": unirig_status["install_hint"],
            },
        ],
        "animations": ANIMATIONS,
        "rig_profiles": RIG_PROFILES,
        "default_rig_profile": DEFAULT_RIG_PROFILE,
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
    # Each engine has its own runtime; gate on the one actually requested.
    if str(body.get("engine") or "procedural") != "unirig":
        runtime = installation_status()
        if not runtime["installed"]:
            raise RuntimeError(runtime["install_hint"])

    with _lock:
        _prune_finished_jobs_locked()
        active = sum(1 for job in _jobs.values() if job["status"] in {"queued", "running"})
    if active >= _MAX_ACTIVE_JOBS:
        raise ValueError("Too many queued rig jobs; wait for the current ones to finish or cancel them")

    engine = str(body.get("engine") or "procedural")
    if engine not in {"procedural", "unirig"}:
        raise ValueError(f"Unknown rig engine: {engine}")
    if engine == "unirig":
        unirig_status = unirig_installation_status()
        if not unirig_status["installed"]:
            raise RuntimeError(unirig_status["install_hint"])

    raw_profile = body.get("rig_profile")
    profile_was_explicit = raw_profile is not None and str(raw_profile).strip() != ""
    rig_profile = str(raw_profile).strip().lower() if profile_was_explicit else DEFAULT_RIG_PROFILE
    profile = RIG_PROFILES_BY_ID.get(rig_profile)
    if profile is None:
        raise ValueError(f"Unknown rig profile: {rig_profile}")

    # Preserve the pre-profile API behaviour when old clients omit the field:
    # all clips and the original 5/auto/2 defaults remain valid. New clients
    # get the selected profile's curated clips and fitting defaults.
    animations = body.get("animations")
    if animations is None:
        animations = (
            list(profile["recommended_animations"])
            if profile_was_explicit
            else [item["id"] for item in ANIMATIONS]
        )
    if not isinstance(animations, list) or not animations:
        raise ValueError("Select at least one animation")
    if len(animations) > len(ANIMATION_IDS):
        raise ValueError(f"Select at most {len(ANIMATION_IDS)} animations")
    if any(not isinstance(item, str) for item in animations):
        raise ValueError("Animation identifiers must be strings")
    animations = list(dict.fromkeys(item.strip() for item in animations))
    if not animations or any(not item for item in animations):
        raise ValueError("Animation identifiers cannot be empty")
    invalid = [item for item in animations if item not in ANIMATION_IDS]
    if invalid:
        raise ValueError(f"Unknown animations: {', '.join(map(str, invalid))}")
    if profile_was_explicit:
        allowed = set(profile["allowed_animations"])
        incompatible = [item for item in animations if item not in allowed]
        if incompatible:
            raise ValueError(
                f"Animations not available for the {rig_profile} profile: "
                + ", ".join(map(str, incompatible))
            )

    default_spine_joints = int(profile["default_spine_joints"]) if profile_was_explicit else 5
    default_axis_mode = str(profile["default_axis_mode"]) if profile_was_explicit else "auto"
    default_weight_falloff = float(profile["default_weight_falloff"]) if profile_was_explicit else 2.0
    try:
        spine_joints = max(2, min(9, int(body.get("spine_joints") or default_spine_joints)))
    except (TypeError, ValueError):
        spine_joints = default_spine_joints
    axis_mode = str(body.get("axis_mode") or default_axis_mode).lower()
    if axis_mode not in {"auto", "x", "y", "z"}:
        raise ValueError(f"Unknown skeleton axis: {axis_mode}")
    try:
        weight_falloff = max(1.0, min(6.0, float(body.get("weight_falloff") or default_weight_falloff)))
    except (TypeError, ValueError):
        weight_falloff = default_weight_falloff

    request_data = {
        "engine": engine,
        "source": os.path.abspath(source_path),
        "rig_profile": rig_profile,
        "animations": [str(item) for item in animations],
        "spine_joints": spine_joints,
        "axis_mode": axis_mode,
        "weight_falloff": weight_falloff,
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
        "rig_profile": rig_profile,
        **({"spine_joints": spine_joints} if engine == "procedural" else {}),
        "axis_mode": axis_mode,
        "weight_falloff": weight_falloff,
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
    with _lock:
        job = _jobs.get(job_id)
        request_data = job.get("request") if job else None
    if not request_data:
        return
    engine = request_data.get("engine") or "procedural"
    if engine == "unirig":
        python_path = _unirig_python_path()
        worker_path = UNIRIG_WORKER_PATH
        worker_cwd = RIGGING_DIR
        # GPU inference plus a one-time weights download on first use.
        inactivity_limit = 15 * 60
        time_limit = 2 * 3600
    else:
        python_path = _python_path()
        worker_path = WORKER_PATH
        worker_cwd = SERVICE_DIR
        inactivity_limit = _WORKER_INACTIVITY_LIMIT_SECONDS
        time_limit = _WORKER_TIME_LIMIT_SECONDS
    if not python_path:
        _update_job(job_id, status="failed", phase="failed", error="Rig runtime is not installed")
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

    command = [str(python_path), str(worker_path), "--request", str(request_path), "--output", str(output_path)]
    env = os.environ.copy()
    if engine == "unirig":
        # Same network isolation as the Hunyuan3D worker: the public UniRig
        # weights must not inherit Pinokio's HF credentials or proxy setup.
        for env_var in (
            "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HF_TOKEN_PATH",
            "HF_ENDPOINT", "HF_INFERENCE_ENDPOINT", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
            "http_proxy", "https_proxy", "all_proxy", "no_proxy",
            "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE",
        ):
            env.pop(env_var, None)
        HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        env.update({
            "HF_HOME": str(HF_CACHE_DIR),
            "HUGGINGFACE_HUB_CACHE": str(HF_CACHE_DIR / "hub"),
            "HF_ENDPOINT": "https://huggingface.co",
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
            "TOKENIZERS_PARALLELISM": "false",
        })
    env.update({"PYTHONUNBUFFERED": "1"})
    lines: list[str] = []
    result_summary: dict[str, Any] = {}
    try:
        _update_job(job_id, status="running", phase="starting", message="Starting rig worker", progress=0.02)
        process = subprocess.Popen(
            command,
            cwd=str(worker_cwd),
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
        deadline = time.monotonic() + time_limit
        timeout_reason: dict[str, str] = {}

        def _watchdog() -> None:
            while process.poll() is None:
                time.sleep(5)
                now = time.monotonic()
                if now - activity["at"] > inactivity_limit:
                    timeout_reason["error"] = f"Rig worker produced no output for {inactivity_limit // 60} minutes"
                elif now > deadline:
                    timeout_reason["error"] = f"Rig job exceeded the {time_limit // 60} minute limit"
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

        rig_metrics = (
            {
                "joint_count": result_summary.get("joint_count", 0),
                "animation_chain_joints": result_summary.get("animation_chain_joints", 0),
            }
            if engine == "unirig"
            else {"spine_joints": result_summary.get("joints", request_data["spine_joints"])}
        )
        sidecar = output_path.with_suffix(".meta.json")
        sidecar.write_text(
            json.dumps(
                {
                    "generation_mode": "model3d",
                    "mode": "model3d",
                    "job_id": job_id,
                    "created_at": time.time(),
                    "params": {
                        "model_type": f"rig-{request_data['engine']}",
                        "rigged": True,
                        "rig_engine": request_data["engine"],
                        "rig_profile": request_data.get("rig_profile", DEFAULT_RIG_PROFILE),
                        "source_file": source.name,
                        "animations": result_summary.get("animations") or request_data["animations"],
                        **rig_metrics,
                        "axis_mode": result_summary.get("axis_mode", request_data.get("axis_mode", "auto")),
                        "weight_falloff": result_summary.get("weight_falloff", request_data.get("weight_falloff", 2.0)),
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
            rig_profile=result_summary.get("rig_profile", request_data.get("rig_profile", DEFAULT_RIG_PROFILE)),
            **rig_metrics,
            axis_mode=result_summary.get("axis_mode", request_data.get("axis_mode", "auto")),
            weight_falloff=result_summary.get("weight_falloff", request_data.get("weight_falloff", 2.0)),
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


def _cmdline_is_rig_worker(cmdline: str) -> bool:
    return (WORKER_PATH.name in cmdline and "hunyuan3d" in cmdline) or (
        UNIRIG_WORKER_PATH.name in cmdline and "rigging" in cmdline
    )


def _is_rig_worker(pid: int) -> bool:
    proc_cmdline = Path("/proc") / str(pid) / "cmdline"
    try:
        if proc_cmdline.is_file():
            cmdline = proc_cmdline.read_bytes().replace(b"\x00", b" ").decode("utf-8", "replace")
            return _cmdline_is_rig_worker(cmdline)
    except OSError:
        return False
    try:
        import psutil

        cmdline = " ".join(psutil.Process(pid).cmdline())
        return _cmdline_is_rig_worker(cmdline)
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
