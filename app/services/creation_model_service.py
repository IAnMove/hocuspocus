"""Isolated, loopback-only ComfyUI runtime for FLUX 3 and Drama 3.

The native generation coordinator owns the GPU and queue. This service runs one
graph at a time and stops its process before returning that lease, including on
failure and cancellation. It never upgrades the WanGP or H3 environments.
"""
import atexit
import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import requests

from services.creation_model_catalog import ASSET_ROOT, ROOT, assets, models_sharing_assets
from services.creation_model_graphs import build_workflow
from services.runtime_environment import engine_python, isolated_environment

SERVICE_DIR = ROOT / "services" / "creation_models"
COMFY_DIR = SERVICE_DIR / "vendor" / "ComfyUI"
INPUT_DIR = SERVICE_DIR / "input"
OUTPUT_DIR = SERVICE_DIR / "output"
_process = None
_port = None
_lock = threading.RLock()


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
    log_dir = ROOT.parent / "logs" / "creation_models"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "latest.log").open("a", encoding="utf-8") as log:
        for line in process.stdout:
            log.write(line)
            log.flush()
            print("[Creation models] " + line.rstrip(), flush=True)


def stop_runtime():
    global _process, _port
    with _lock:
        process, _process, _port = _process, None, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def cancel():
    # Cancellation must not wait on the lock held by the generation thread.
    port = _port
    if port is not None:
        try:
            _request("POST", f"http://127.0.0.1:{port}", "/interrupt", json={}, timeout=3)
        except requests.RequestException:
            pass


def ensure_runtime(progress, cancelled):
    global _process, _port
    if not is_runtime_installed():
        raise RuntimeError("Install FLUX 3 / Drama 3 Support from Pinokio → Advanced first")
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
    _process = subprocess.Popen(command, cwd=COMFY_DIR, env=isolated_environment(python),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    threading.Thread(target=_drain, args=(_process,), daemon=True).start()
    base = f"http://127.0.0.1:{_port}"
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if cancelled():
            raise RuntimeError("Generation cancelled")
        if _process.poll() is not None:
            raise RuntimeError("Creation runtime stopped during startup; see logs/creation_models/latest.log")
        try:
            _request("GET", base, "/system_stats", timeout=2)
            return base
        except requests.RequestException:
            time.sleep(.5)
    raise RuntimeError("Creation runtime startup timed out; see logs/creation_models/latest.log")


def generate(params, job_id, out_dir, progress, cancelled):
    with _lock:
        try:
            download_assets(params["model_type"], lambda message: progress(message, 1, 0, 0))
            base = ensure_runtime(progress, cancelled)
            results = []
            for index in range(int(params.get("repeat_generation", 1))):
                if cancelled():
                    raise RuntimeError("Generation cancelled")
                prefix = f"{params['model_type']}_{job_id}_{index}"
                effective = {**params, "seed": int(params["seed"]) + index}
                graph, output_node = build_workflow(effective, prefix, INPUT_DIR)
                response = _request("POST", base, "/prompt", json={"prompt": graph}).json()
                if response.get("node_errors"):
                    raise RuntimeError("Creation graph validation failed: " + str(response["node_errors"]))
                prompt_id = response["prompt_id"]
                progress("Generating " + params["model_type"], 5, 0, 0)
                deadline = time.monotonic() + 3600
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
                            raise RuntimeError("Creation runtime stopped before returning its output")
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
                        for record in records:
                            source = (OUTPUT_DIR / record.get("subfolder", "") / record["filename"]).resolve()
                            if not source.is_relative_to(OUTPUT_DIR.resolve()) or not source.is_file():
                                raise RuntimeError("Creation runtime returned an invalid output file")
                            destination = Path(out_dir) / source.name
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(source, destination)
                            results.append(str(destination))
                        if not records:
                            raise RuntimeError("Creation runtime completed without output media")
                        break
                    time.sleep(1)
            return results
        finally:
            stop_runtime()
            # The user originals stay in uploads/library; discard job-scoped copies.
            for path in INPUT_DIR.glob("*" + job_id + "*"):
                if path.is_file():
                    path.unlink(missing_ok=True)


atexit.register(stop_runtime)
