#!/usr/bin/env python3
"""Run a small reproducible Maestro LTX baseline and record resource peaks."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil
import requests


def _gpu_memory_by_pid() -> dict[int, int]:
    command = [
        "nvidia-smi",
        "--query-compute-apps=pid,used_memory",
        "--format=csv,noheader,nounits",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    memory = {}
    for line in result.stdout.splitlines():
        try:
            pid_text, mib_text = (part.strip() for part in line.split(",", 1))
            memory[int(pid_text)] = int(mib_text)
        except (TypeError, ValueError):
            continue
    return memory


def _process_rss_bytes(process: psutil.Process) -> int:
    processes = [process]
    try:
        processes.extend(process.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    total = 0
    for item in processes:
        try:
            total += item.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def _probe_output(path: Path) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,nb_frames,duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)["streams"][0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--server-pid", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default="ltx2_22B_distilled_gguf_q6_k")
    parser.add_argument("--resolution", default="512x512")
    parser.add_argument("--frames", default=17, type=int)
    parser.add_argument("--steps", default=8, type=int)
    parser.add_argument("--seed", default=424242, type=int)
    parser.add_argument("--job-id")
    args = parser.parse_args()

    payload = {
        "prompt": (
            "A matte red toy sphere rests on a neutral gray tabletop. "
            "The camera remains locked. The sphere rolls slowly to the right. "
            "Soft studio light, simple background, no text, no cuts."
        ),
        "model_type": args.model,
        "resolution": args.resolution,
        "video_length": args.frames,
        "num_inference_steps": args.steps,
        "guidance_scale": 1.0,
        "guidance_phases": 1,
        "seed": args.seed,
        "image_mode": 0,
        "negative_prompt": "",
        "repeat_generation": 1,
        "activated_loras": [],
        "loras_multipliers": "",
        "settings_version": 2.56,
        "audio_prompt_type": "",
        "video_prompt_type": "",
        "image_prompt_type": "",
        "generation_mode": "video",
    }

    base_url = args.base_url.rstrip("/")
    process = psutil.Process(args.server_pid)
    started_wall = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    job_created_at = None
    if args.job_id:
        job_id = args.job_id
        try:
            jobs_response = requests.get(f"{base_url}/api/v1/jobs", timeout=5)
            jobs_response.raise_for_status()
            for active_job in jobs_response.json().get("jobs", []):
                if active_job.get("job_id") == job_id:
                    job_created_at = active_job.get("created_at")
                    break
        except requests.RequestException:
            pass
    else:
        response = requests.post(f"{base_url}/api/v1/generate", json=payload, timeout=30)
        response.raise_for_status()
        job_id = response.json()["job_id"]

    peak_rss = 0
    peak_system_used = 0
    peak_gpu_process = 0
    peak_gpu_total = 0
    first_progress_seconds = None
    transitions = []
    previous_state = None
    final_status = None

    while True:
        elapsed = (
            time.time() - job_created_at
            if job_created_at is not None
            else time.monotonic() - started
        )
        try:
            status_response = requests.get(
                f"{base_url}/api/v1/status/{job_id}",
                timeout=5,
            )
            status_response.raise_for_status()
            status = status_response.json()
        except requests.RequestException as exc:
            status = None
            state = ("unresponsive", "", 0, 0, type(exc).__name__)
            if state != previous_state:
                transitions.append(
                    {
                        "elapsed_seconds": round(elapsed, 3),
                        "status": state[0],
                        "phase": state[1],
                        "step": state[2],
                        "total_steps": state[3],
                        "message": state[4],
                    }
                )
                print(json.dumps(transitions[-1]), flush=True)
                previous_state = state

        if status is not None:
            state = (
                status.get("status"),
                status.get("phase"),
                status.get("step"),
                status.get("total_steps"),
                status.get("message"),
            )
            if state != previous_state:
                transitions.append(
                    {
                        "elapsed_seconds": round(elapsed, 3),
                        "status": state[0],
                        "phase": state[1],
                        "step": state[2],
                        "total_steps": state[3],
                        "message": state[4],
                    }
                )
                print(json.dumps(transitions[-1]), flush=True)
                previous_state = state
            if first_progress_seconds is None and int(status.get("step") or 0) > 0:
                first_progress_seconds = elapsed

        rss = _process_rss_bytes(process)
        system_memory = psutil.virtual_memory()
        gpu_by_pid = _gpu_memory_by_pid()
        peak_rss = max(peak_rss, rss)
        peak_system_used = max(peak_system_used, system_memory.used)
        peak_gpu_process = max(peak_gpu_process, gpu_by_pid.get(args.server_pid, 0))
        peak_gpu_total = max(peak_gpu_total, sum(gpu_by_pid.values()))

        if status is not None and status["status"] in {"completed", "failed", "cancelled"}:
            final_status = status
            break
        time.sleep(1)

    elapsed = (
        time.time() - job_created_at
        if job_created_at is not None
        else time.monotonic() - started
    )
    output_probe = None
    output_path = None
    if final_status["status"] == "completed" and final_status["output_files"]:
        output_path = Path(final_status["output_files"][0])
        if not output_path.is_absolute():
            candidates = [
                Path("app") / "outputs" / output_path,
                Path("app") / output_path,
            ]
            output_path = next(
                (candidate for candidate in candidates if candidate.is_file()),
                candidates[0],
            )
        output_path = output_path.resolve()
        try:
            output_probe = _probe_output(output_path)
        except (OSError, subprocess.CalledProcessError, KeyError, IndexError) as exc:
            output_probe = {"error": str(exc)}

    report = {
        "started_at_utc": started_wall,
        "base_url": base_url,
        "server_pid": args.server_pid,
        "job_id": job_id,
        "payload": payload,
        "status": final_status,
        "timing": {
            "total_seconds": round(elapsed, 3),
            "first_progress_seconds": (
                None if first_progress_seconds is None else round(first_progress_seconds, 3)
            ),
        },
        "peaks": {
            "process_tree_rss_bytes": peak_rss,
            "system_used_ram_bytes": peak_system_used,
            "server_gpu_memory_mib": peak_gpu_process,
            "all_compute_processes_gpu_memory_mib": peak_gpu_total,
        },
        "transitions": transitions,
        "output_path": None if output_path is None else str(output_path),
        "output_probe": output_probe,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if final_status["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
