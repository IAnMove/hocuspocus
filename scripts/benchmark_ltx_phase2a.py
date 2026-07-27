#!/usr/bin/env python3
"""Submit one reproducible LTX Phase 2A job and record timings/resources."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil
import requests
from PIL import Image


DEFAULT_PROMPT = (
    "A matte red toy sphere rests on a neutral gray tabletop. "
    "The camera remains locked. The sphere rolls slowly to the right. "
    "Soft studio light, simple background, no text, no cuts."
)

I2V_PROMPT = (
    "Preserve the exact character, composition, colors, and flat low-poly "
    "illustration style of the reference image. The small coral robot turns "
    "its head slightly and gives one gentle wave while the blue leaves sway. "
    "A slow, subtle camera push-in; stable geometry, no cuts, no text."
)


def _gpu_sample(server_pid: int) -> dict:
    query = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=utilization.gpu,memory.used,power.draw",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()[0]
    util, memory, power = (float(part.strip()) for part in query.split(","))
    apps = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,used_memory",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    process_memory = 0
    for line in apps.splitlines():
        try:
            pid_text, memory_text = (part.strip() for part in line.split(",", 1))
            if int(pid_text) == server_pid:
                process_memory += int(memory_text)
        except ValueError:
            continue
    return {
        "gpu_utilization_percent": util,
        "gpu_memory_total_mib": memory,
        "gpu_power_watts": power,
        "server_gpu_memory_mib": process_memory,
    }


def _rss_tree(process: psutil.Process) -> int:
    items = [process]
    try:
        items.extend(process.children(recursive=True))
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        pass
    total = 0
    for item in items:
        try:
            total += item.memory_info().rss
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
    return total


def _probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=width,height,avg_frame_rate,nb_frames,nb_read_frames,duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)["streams"][0]


def _phase_kind(phase: str, message: str) -> str:
    value = f"{phase} {message}".lower()
    if "loading model" in value:
        return "model_load"
    if "model loaded" in value or "encoding prompt" in value:
        return "text_and_prepare"
    if "denoising first pass" in value:
        return "stage_1"
    if "denoising second pass" in value:
        return "stage_2"
    if "vae decoding" in value:
        return "vae_decode"
    return "other"


def derive_phase_timings(transitions: list[dict], total_seconds: float) -> dict:
    """Approximate wall-clock phase durations from API status transitions."""
    starts: dict[str, float] = {}
    vae_events: list[float] = []
    for event in transitions:
        kind = _phase_kind(event.get("phase", ""), event.get("message", ""))
        elapsed = float(event["elapsed_seconds"])
        if kind == "vae_decode":
            vae_events.append(elapsed)
        elif kind != "other" and kind not in starts:
            starts[kind] = elapsed

    # Two-stage LTX reports a transient "VAE Decoding" callback at the end of
    # pass 1 before pass 2 starts. Only the final event is the actual output
    # decode; count the transient interval as inter-stage work.
    if vae_events:
        stage_2_start = starts.get("stage_2", -1.0)
        final_vae = next(
            (value for value in reversed(vae_events) if value > stage_2_start),
            vae_events[-1],
        )
        starts["vae_decode"] = final_vae

    order = ["model_load", "text_and_prepare", "stage_1", "stage_2", "vae_decode"]
    durations = {}
    for index, name in enumerate(order):
        if name not in starts:
            durations[name] = None
            continue
        following = next(
            (starts[item] for item in order[index + 1 :] if item in starts),
            total_seconds,
        )
        durations[name] = round(max(0.0, following - starts[name]), 3)
    return {"starts_seconds": starts, "durations_seconds": durations}


def _resolve_output(
    repository: Path, workspace: str, filenames: list[str]
) -> Path | None:
    for filename in filenames:
        raw = Path(filename)
        candidates = (
            [raw]
            if raw.is_absolute()
            else [
                repository / "app" / "outputs" / workspace / raw,
                repository / "app" / "outputs" / raw,
                repository / "app" / raw,
            ]
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
    return None


def _adapt_reference(
    source: Path, resolution: str, strategy: str, repository: Path
) -> Path:
    """Create an exact-size deterministic canvas so WanGP keeps orientation."""
    if strategy == "source":
        return source
    width_text, height_text = resolution.lower().split("x", 1)
    target = (int(width_text), int(height_text))
    image = Image.open(source).convert("RGB")
    scale = (
        min(target[0] / image.width, target[1] / image.height)
        if strategy == "contain"
        else max(target[0] / image.width, target[1] / image.height)
    )
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = (target[0] - resized.width) // 2
    top = (target[1] - resized.height) // 2
    if strategy == "contain":
        background = image.getpixel((0, 0))
        canvas = Image.new("RGB", target, background)
        canvas.paste(resized, (left, top))
    else:
        canvas = resized.crop((-left, -top, -left + target[0], -top + target[1]))
    destination = (
        repository
        / "app"
        / "outputs"
        / "benchmarks"
        / "phase2a"
        / "reference"
        / f"{source.stem}-{resolution}-{strategy}.png"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="PNG", optimize=False)
    return destination.resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:42020")
    parser.add_argument("--server-pid", required=True, type=int)
    parser.add_argument("--model", required=True)
    parser.add_argument("--run-label", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--workspace", default="phase2a")
    parser.add_argument("--resolution", default="512x512")
    parser.add_argument("--frames", default=17, type=int)
    parser.add_argument("--steps", required=True, type=int)
    parser.add_argument("--guidance", required=True, type=float)
    parser.add_argument(
        "--profile",
        default=-1,
        type=float,
        help=(
            "Per-job WanGP/MMGP memory profile override. Use 3.5 for the "
            "VeryLowRAM/HighVRAM fallback without reserved pinned memory."
        ),
    )
    parser.add_argument("--seed", default=424242, type=int)
    parser.add_argument(
        "--prompt",
        help="Defaults to the fixed T2V prompt, or the fixed I2V prompt with --image-start.",
    )
    parser.add_argument("--image-start", type=Path)
    parser.add_argument(
        "--fit-strategy",
        choices=("source", "contain", "cover"),
        default="source",
    )
    parser.add_argument("--poll-seconds", default=0.5, type=float)
    parser.add_argument("--request-timeout", default=1.0, type=float)
    args = parser.parse_args()

    repository = args.repository.resolve()
    image_start = args.image_start.resolve() if args.image_start else None
    if image_start and not image_start.is_file():
        parser.error(f"image input does not exist: {image_start}")
    if image_start:
        image_start = _adapt_reference(
            image_start, args.resolution, args.fit_strategy, repository
        )
    prompt = args.prompt or (I2V_PROMPT if image_start else DEFAULT_PROMPT)

    payload = {
        "prompt": prompt,
        "model_type": args.model,
        "resolution": args.resolution,
        "video_length": args.frames,
        "num_inference_steps": args.steps,
        "guidance_scale": args.guidance,
        "guidance_phases": 2 if args.guidance > 1.0 else 1,
        "override_profile": args.profile,
        "seed": args.seed,
        "image_mode": 0,
        "negative_prompt": "",
        "repeat_generation": 1,
        "activated_loras": [],
        "loras_multipliers": "",
        "audio_prompt_type": "",
        "video_prompt_type": "",
        "image_prompt_type": "S" if image_start else "",
        "image_start": str(image_start) if image_start else None,
        "generation_mode": "video",
        "workspace": args.workspace,
        "settings_version": 2.56,
        "_phase2a_fit_strategy": args.fit_strategy if image_start else None,
    }

    base_url = args.base_url.rstrip("/")
    process = psutil.Process(args.server_pid)
    workspace_dir = repository / "app" / "outputs"
    if args.workspace != "default":
        workspace_dir /= args.workspace
    workspace_dir.mkdir(parents=True, exist_ok=True)
    files_before = {item.resolve() for item in workspace_dir.iterdir()}
    started_wall = datetime.now(timezone.utc).isoformat()
    response = requests.post(
        f"{base_url}/api/v1/generate", json=payload, timeout=30
    )
    response.raise_for_status()
    job_id = response.json()["job_id"]
    started = time.monotonic()

    transitions: list[dict] = []
    samples: list[dict] = []
    previous_state = None
    final_status = None
    response_failures = 0
    response_latencies = []
    output_first_seen = None
    first_new_video_path = None

    while True:
        elapsed = time.monotonic() - started
        requested = time.monotonic()
        try:
            status_response = requests.get(
                f"{base_url}/api/v1/status/{job_id}",
                timeout=args.request_timeout,
            )
            latency = time.monotonic() - requested
            response_latencies.append(latency)
            status_response.raise_for_status()
            status = status_response.json()
        except requests.RequestException as exc:
            latency = time.monotonic() - requested
            response_failures += 1
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
        if output_first_seen is None:
            try:
                new_videos = sorted(
                    item.resolve()
                    for item in workspace_dir.iterdir()
                    if item.resolve() not in files_before
                    and item.suffix.lower() in {".mp4", ".webm", ".mkv"}
                )
            except OSError:
                new_videos = []
            if new_videos:
                output_first_seen = elapsed
                first_new_video_path = str(new_videos[0])

        try:
            gpu = _gpu_sample(args.server_pid)
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            gpu = {}
        memory = psutil.virtual_memory()
        samples.append(
            {
                "elapsed_seconds": round(elapsed, 3),
                "rss_bytes": _rss_tree(process),
                "system_used_ram_bytes": memory.used,
                **gpu,
            }
        )

        if status is not None and status["status"] in {
            "completed",
            "failed",
            "cancelled",
        }:
            final_status = status
            break
        time.sleep(args.poll_seconds)

    total_seconds = time.monotonic() - started
    output_path = _resolve_output(
        repository, args.workspace, final_status.get("output_files") or []
    )
    output_probe = _probe(output_path) if output_path else None
    phase_timings = derive_phase_timings(transitions, total_seconds)
    vae_start = phase_timings["starts_seconds"].get("vae_decode")
    if vae_start is not None and output_first_seen is not None:
        phase_timings["durations_seconds"]["vae_decode_until_file_seen"] = round(
            max(0.0, output_first_seen - vae_start), 3
        )
        phase_timings["durations_seconds"]["video_write_after_file_seen"] = round(
            max(0.0, total_seconds - output_first_seen), 3
        )
    else:
        phase_timings["durations_seconds"]["vae_decode_until_file_seen"] = None
        phase_timings["durations_seconds"]["video_write_after_file_seen"] = None

    def peak(key: str):
        values = [item[key] for item in samples if key in item]
        return max(values) if values else None

    def average(key: str):
        values = [item[key] for item in samples if key in item]
        return round(statistics.fmean(values), 3) if values else None

    report = {
        "schema_version": 1,
        "run_label": args.run_label,
        "started_at_utc": started_wall,
        "server_pid": args.server_pid,
        "job_id": job_id,
        "payload": payload,
        "status": final_status,
        "timing": {
            "total_seconds": round(total_seconds, 3),
            **phase_timings,
        },
        "responsiveness": {
            "polls": len(response_latencies) + response_failures,
            "failed_or_timed_out_polls": response_failures,
            "max_successful_latency_seconds": (
                round(max(response_latencies), 3) if response_latencies else None
            ),
        },
        "resources": {
            "peak_process_tree_rss_bytes": peak("rss_bytes"),
            "peak_system_used_ram_bytes": peak("system_used_ram_bytes"),
            "peak_server_gpu_memory_mib": peak("server_gpu_memory_mib"),
            "peak_total_gpu_memory_mib": peak("gpu_memory_total_mib"),
            "peak_gpu_utilization_percent": peak("gpu_utilization_percent"),
            "average_gpu_utilization_percent": average("gpu_utilization_percent"),
            "peak_gpu_power_watts": peak("gpu_power_watts"),
            "average_gpu_power_watts": average("gpu_power_watts"),
        },
        "output_path": str(output_path) if output_path else None,
        "first_new_video_path": first_new_video_path,
        "output_probe": output_probe,
        "transitions": transitions,
        "samples": samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "samples"}, indent=2))
    return 0 if final_status["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
