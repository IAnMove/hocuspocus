"""Isolated, loopback-only ComfyUI runtime for FLUX 3 and Drama 3.

The native generation coordinator owns the GPU and queue. This service runs one
graph at a time. After a successful job the process stays warm for an idle
period (``creation_runtime_idle_seconds``, 300 s by default, 0 stops it at once),
so the next job of the same family skips the ~40 GB weight load and keeps the
GPU expert cache. A failure or a cancellation stops the process, a job of the
other family restarts it, and every other GPU user stops it first through
``stop_runtime`` (the GPU hand-off hook) or ``evict_if_idle`` (users that never
take the GPU lane). It never upgrades the WanGP or H3 environments.

On Linux with a systemd user manager the process runs in its own memory cgroup
(``creation_runtime_memory_percent`` of the RAM, 80 % by default, 0 turns it off), so a
memory shortage kills or slows this runtime and not the server. See
``creation_runtime_confinement``.
"""
import atexit
import json
import math
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import requests

from services import creation_runtime_confinement as confinement
from services.creation_model_catalog import ASSET_ROOT, ROOT, assets, models_sharing_assets
from services.creation_model_graphs import build_workflow
from services.creation_runtime_confinement import memory_percent_setting  # noqa: F401  (creation_model_execution reads it here)
from services.runtime_environment import engine_python, isolated_environment

SERVICE_DIR = ROOT / "services" / "creation_models"
COMFY_DIR = SERVICE_DIR / "vendor" / "ComfyUI"
INPUT_DIR = SERVICE_DIR / "input"
OUTPUT_DIR = SERVICE_DIR / "output"
_process = None
_port = None
_family = None
_confinement = None  # {"max", "high", "percent", "ram", "cgroup"} while the running process is confined
_idle_timer = None
_idle_deadline = None
_lock = threading.RLock()
DEFAULT_IDLE_SECONDS = 300.0
MAX_IDLE_SECONDS = 86400.0
# A prompt measured 70-158 s on Drama 3 (323 s at worst); 15 minutes without one
# printed line is a hung process, not a slow one.
STALL_SECONDS = 900.0
_last_output = 0.0


def runtime_family(model_type):
    """Drama 3 and FLUX 3 load different weights, so a warm runtime serves one family."""
    name = str(model_type or "")
    return "flux" if name.startswith("flux3_") else "drama" if name.startswith("drama3_") else name


def idle_seconds_setting(services):
    """Read ``creation_runtime_idle_seconds`` from the services config; a bad value means the default."""
    raw = (services or {}).get("creation_runtime_idle_seconds", DEFAULT_IDLE_SECONDS)
    try:
        value = DEFAULT_IDLE_SECONDS if isinstance(raw, bool) else float(raw)
    except (TypeError, ValueError):
        return DEFAULT_IDLE_SECONDS
    return min(max(value, 0.0), MAX_IDLE_SECONDS) if math.isfinite(value) else DEFAULT_IDLE_SECONDS


def is_runtime_installed():
    from services.runtime_profiles import managed_ready
    return (COMFY_DIR / "main.py").is_file() and managed_ready("creation_models")


def is_model_downloaded(model):
    return all((ASSET_ROOT / name).is_file() and (ASSET_ROOT / name).stat().st_size > 1024
               for name in assets(model)[2])


def delete_model_assets(model):
    deleted = []
    for name in assets(model)[2]:
        path = ASSET_ROOT / name
        if path.is_file():
            path.unlink()
            deleted.append(name)
    return {"deleted": deleted, "model_type": model,
            "affected_models": sorted(models_sharing_assets(model)) if deleted else []}


def download_assets(model, progress=lambda message: None):
    from huggingface_hub import hf_hub_download
    repo, revision, names = assets(model)
    for name in names:
        if (ASSET_ROOT / name).is_file():
            continue
        progress("Downloading " + Path(name).name)
        try:
            # Flatten each remote subfolder into the matching local model folder.
            remote = name if model.startswith("flux3_") else Path(name).name
            path = Path(hf_hub_download(repo, remote, revision=revision))
        except Exception as error:
            if "GatedRepo" in type(error).__name__ or getattr(getattr(error, "response", None), "status_code", None) in (401, 403):
                raise RuntimeError(f"Hugging Face access required for {repo}; authorize the configured account at https://huggingface.co/{repo}") from error
            raise
        destination = ASSET_ROOT / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Hardlink cached immutable assets where possible; avoid a second 39 GB copy.
        try:
            destination.hardlink_to(path)
        except OSError:
            shutil.copyfile(path, destination)


def _request(method, base, suffix, **kwargs):
    with requests.Session() as session:
        session.trust_env = False
        result = session.request(method, base + suffix, timeout=kwargs.pop("timeout", 30), **kwargs)
        if suffix == "/prompt" and result.status_code == 400:
            raise RuntimeError("Creation graph validation failed: " + result.text[:4000])
        result.raise_for_status()
        return result


def _drain(process):
    global _last_output
    log_dir = ROOT.parent / "logs" / "creation_models"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "latest.log").open("a", encoding="utf-8") as log:
        for line in process.stdout:
            _last_output = time.monotonic()
            log.write(line)
            log.flush()
            print("[Creation models] " + line.rstrip(), flush=True)


def _cancel_idle_locked():
    global _idle_timer, _idle_deadline
    timer, _idle_timer, _idle_deadline = _idle_timer, None, None
    if timer is not None:
        timer.cancel()


def _log(message):
    print("[Creation models] " + message, flush=True)


def _record_path():
    return SERVICE_DIR / "runtime.json"


def _stop_locked():
    global _process, _port, _family, _confinement
    _cancel_idle_locked()
    process, _process, _port, _family, _confinement = _process, None, None, None, None
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    # Only a runtime that is really gone leaves the record; a stuck one stays findable for the next sweep.
    confinement.forget_runtime(_record_path(), process.pid)


def stop_runtime():
    with _lock:
        _stop_locked()


def evict_if_idle():
    """Stop a warm runtime for a GPU user that never takes the GPU lane (the SAM service).

    Never waits: while a job holds the lock the runtime is busy and stays. Returns True if it stopped one.
    """
    if not _lock.acquire(blocking=False):
        return False
    try:
        if _process is None:
            return False
        print("[Creation models] runtime released for another GPU engine", flush=True)
        _stop_locked()
        return True
    finally:
        _lock.release()


def _keep_warm_locked(delay):
    """Stop the runtime after ``delay`` idle seconds unless the next job arrives first."""
    global _idle_timer, _idle_deadline
    _cancel_idle_locked()

    def release():
        with _lock:
            if _idle_timer is not timer:
                return
            _stop_locked()
            print("[Creation models] runtime released after idle", flush=True)

    timer = threading.Timer(delay, release)
    timer.daemon = True
    _idle_timer, _idle_deadline = timer, time.monotonic() + delay
    timer.start()
    print(f"[Creation models] runtime kept warm for {delay:g} s", flush=True)


def runtime_status():
    """``warm`` is True while a live process waits for the next job. Never waits for a running job.

    ``confined`` says the live process runs in its own memory cgroup (checked after start) and
    ``memory_max_gb`` is that cgroup's hard limit in GiB.
    """
    process, deadline, limits = _process, _idle_deadline, _confinement
    warm = process is not None and process.poll() is None
    left = None if not warm or deadline is None else round(max(0.0, deadline - time.monotonic()), 1)
    confined = warm and limits is not None
    return {"warm": warm, "family": _family if warm else None, "idle_seconds_left": left,
            "confined": confined, "memory_max_gb": round(limits["max"] / 2**30, 1) if confined else None}


def cancel():
    # Cancellation must not wait on the lock held by the generation thread.
    port = _port
    if port is not None:
        try:
            _request("POST", f"http://127.0.0.1:{port}", "/interrupt", json={}, timeout=3)
        except requests.RequestException:
            pass


def _reusable_base(family):
    """The warm runtime's URL when it can run this job; otherwise stop it, say why, and return None."""
    if _process is None:
        return None
    if _process.poll() is not None:
        reason = "its process exited"
    elif _family != family:
        reason = f"the job needs the {family} family, not {_family}"
    else:
        base = f"http://127.0.0.1:{_port}"
        try:
            _request("GET", base, "/system_stats", timeout=2)
            print("[Creation models] reusing the warm runtime", flush=True)
            return base
        except requests.RequestException:
            reason = "it stopped answering"
    print(f"[Creation models] restarting the runtime: {reason}", flush=True)
    stop_runtime()
    return None


def _exit_error(message):
    """The error for a runtime that is gone: the memory message when it was killed for memory."""
    process, limits = _process, _confinement
    code = None if process is None else process.poll()
    if confinement.exited_from_oom(code, None if limits is None else limits.get("cgroup")):
        return RuntimeError(confinement.OUT_OF_MEMORY_MESSAGE)
    return RuntimeError(message)


def _check_confinement(limits):
    """Keep ``limits`` (plus the cgroup) only if the kernel really holds the memory limit on the running scope."""
    cgroup = None if limits is None else confinement.verify_scope(_process.pid, limits)
    if limits is not None and cgroup is None:
        _log("WARNING: the runtime is NOT confined (systemd did not apply MemoryMax); a memory shortage can reach the server")
    elif limits is not None:
        _log(f"runtime confined: memory.max {limits['max'] / 2**30:.1f} GiB, memory.high {limits['high'] / 2**30:.1f} GiB "
             f"({limits['percent']} % of {limits['ram'] / 2**30:.1f} GiB)")
    return None if cgroup is None else {**limits, "cgroup": cgroup}


def _start_process(command, python, config, memory_percent):
    """Start ComfyUI, in its own memory scope when the machine supports it; returns the scope's limits or None."""
    global _process
    command, env, limits = confinement.confine(command, isolated_environment(python), memory_percent)
    _process = subprocess.Popen(command, cwd=COMFY_DIR, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    confinement.record_runtime(_record_path(), _process.pid, str(config))
    return limits


def ensure_runtime(progress, cancelled, family=None, memory_percent=None):
    global _process, _port, _family, _confinement
    _cancel_idle_locked()
    base = _reusable_base(family)
    if base is not None:
        return base
    if not is_runtime_installed():
        raise RuntimeError("Install FLUX 3 / Drama 3 Support from Pinokio → Advanced first")
    # The previous server may have died and left its runtime running outside our cgroup.
    confinement.sweep_orphan_runtime(_record_path())
    for folder in (INPUT_DIR, OUTPUT_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    config = SERVICE_DIR / "extra_model_paths.json"
    config.write_text(json.dumps({"hocuspocus": {"base_path": str(ASSET_ROOT),
                      **{key: key for key in ("diffusion_models", "vae", "text_encoders")}}}), encoding="utf-8")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        _port = sock.getsockname()[1]
    python = engine_python("creation_models")
    command = [str(python), "main.py", "--listen", "127.0.0.1", "--port", str(_port),
               "--disable-auto-launch", "--enable-triton-backend", "--extra-model-paths-config", str(config),
               "--input-directory", str(INPUT_DIR), "--output-directory", str(OUTPUT_DIR)]
    progress("Starting isolated FLUX 3 / Drama 3 runtime", 2, 0, 0)
    limits = _start_process(command, python, config, memory_percent)
    _family = family
    threading.Thread(target=_drain, args=(_process,), daemon=True).start()
    base = f"http://127.0.0.1:{_port}"
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if cancelled():
            raise RuntimeError("Generation cancelled")
        if _process.poll() is not None:
            raise _exit_error("Creation runtime stopped during startup; see logs/creation_models/latest.log")
        try:
            _request("GET", base, "/system_stats", timeout=2)
            _confinement = _check_confinement(limits)
            return base
        except requests.RequestException:
            time.sleep(.5)
    raise RuntimeError("Creation runtime startup timed out; see logs/creation_models/latest.log")


def _raise_if_memory_killed():
    """Fail a pending prompt when the kernel counted an OOM kill in the runtime's cgroup, even if ComfyUI survived it."""
    limits = _confinement
    if limits is not None and confinement.exited_from_oom(None, limits.get("cgroup")):
        stop_runtime()
        raise RuntimeError(confinement.OUT_OF_MEMORY_MESSAGE)


def _raise_if_stalled(submitted):
    """Fail a pending prompt when the runtime has printed nothing for ``STALL_SECONDS``.

    A runtime that sat warm and silent before this prompt must not count that time,
    so the quiet period starts at the last printed line or at the submission.
    """
    if time.monotonic() - max(_last_output, submitted) >= STALL_SECONDS:
        stop_runtime()
        raise RuntimeError("The creation runtime made no progress for 15 minutes and was stopped; try again")


def _await_output(base, prompt_id, output_node, cancelled, out_dir):
    """Poll one prompt until Comfy reports it, then copy its media into ``out_dir``."""
    submitted = time.monotonic()
    deadline = submitted + 3600
    while True:
        if cancelled():
            cancel()
            raise RuntimeError("Generation cancelled")
        if time.monotonic() >= deadline:
            raise RuntimeError("Creation generation exceeded its one-hour limit")
        try:
            history = _request("GET", base, "/history/" + prompt_id, timeout=5).json().get(prompt_id)
        except (requests.Timeout, requests.ConnectionError):
            # Heavy native kernels can temporarily delay Comfy's HTTP thread.
            # A missed poll is not evidence that inference failed.
            if _process is None or _process.poll() is not None:
                raise _exit_error("Creation runtime stopped before returning its output")
            _raise_if_memory_killed()
            _raise_if_stalled(submitted)
            time.sleep(1)
            continue
        if history:
            status = history.get("status", {})
            if status.get("status_str") == "error":
                errors = [str(message[1].get("exception_message", message[1]))
                          for message in status.get("messages", []) if message[0] == "execution_error"]
                raise RuntimeError("Creation generation failed: " + "; ".join(errors))
            outputs = history.get("outputs", {}).get(output_node, {})
            records = outputs.get("images") or outputs.get("audio") or []
            copied = []
            for record in records:
                source = (OUTPUT_DIR / record.get("subfolder", "") / record["filename"]).resolve()
                if not source.is_relative_to(OUTPUT_DIR.resolve()) or not source.is_file():
                    raise RuntimeError("Creation runtime returned an invalid output file")
                destination = Path(out_dir) / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                copied.append(str(destination))
            if not records:
                raise RuntimeError("Creation runtime completed without output media")
            return copied
        _raise_if_memory_killed()
        _raise_if_stalled(submitted)
        time.sleep(1)


def _release_after_job(succeeded, idle_seconds):
    """Keep the runtime warm after a success; a failure, a cancellation or an idle time of 0 stops it."""
    if not succeeded:
        stop_runtime()
        return
    delay = DEFAULT_IDLE_SECONDS if idle_seconds is None else max(0.0, float(idle_seconds))
    if delay > 0:
        _keep_warm_locked(delay)
    else:
        stop_runtime()


def generate(params, job_id, out_dir, progress, cancelled, on_produce=None, idle_seconds=None, memory_percent=None):
    with _lock:
        succeeded = False
        _cancel_idle_locked()
        try:
            if cancelled():
                raise RuntimeError("Generation cancelled")
            download_assets(params["model_type"], lambda message: progress(message, 1, 0, 0))
            if cancelled():
                raise RuntimeError("Generation cancelled")
            base = ensure_runtime(progress, cancelled, runtime_family(params["model_type"]), memory_percent)
            results = []
            for index in range(int(params.get("repeat_generation", 1))):
                if cancelled():
                    raise RuntimeError("Generation cancelled")
                if on_produce is not None:
                    on_produce()
                prefix = f"{params['model_type']}_{job_id}_{index}"
                effective = {**params, "seed": int(params["seed"]) + index}
                graph, output_node = build_workflow(effective, prefix, INPUT_DIR)
                response = _request("POST", base, "/prompt", json={"prompt": graph}).json()
                if response.get("node_errors"):
                    raise RuntimeError("Creation graph validation failed: " + str(response["node_errors"]))
                prompt_id = response["prompt_id"]
                progress("Generating " + params["model_type"], 5, 0, 0)
                results.extend(_await_output(base, prompt_id, output_node, cancelled, out_dir))
            succeeded = True
            return results
        finally:
            _release_after_job(succeeded, idle_seconds)
            # The user originals stay in uploads/library; discard job-scoped copies.
            for path in INPUT_DIR.glob("*" + job_id + "*"):
                if path.is_file():
                    path.unlink(missing_ok=True)


atexit.register(stop_runtime)
# A server that was killed leaves its runtime running outside the server's cgroup: stop it now, without blocking the import.
confinement.sweep_in_background(_record_path())
