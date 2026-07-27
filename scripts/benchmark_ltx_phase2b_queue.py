#!/usr/bin/env python3
"""Run a reproducible four-panel LTX Phase 2B comic queue."""

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
from PIL import Image, ImageDraw

from scripts.benchmark_ltx_phase2a import _gpu_sample, _probe, _rss_tree


SCENES = [
    (
        "rooftop",
        "Preserve the exact anime heroine, rooftop composition, violet-orange palette, "
        "and cel-shaded style. Her scarf and hair move gently in the evening breeze "
        "while she looks toward the skyline. Slow restrained camera push-in, stable "
        "face and hands, no cuts, no text.",
    ),
    (
        "forest",
        "Preserve the exact small low-poly robot, mossy forest composition, teal-green "
        "colors, and faceted style. The robot takes two careful steps and raises its "
        "lamp while nearby leaves sway. Moderate lateral camera drift, stable geometry, "
        "no cuts, no text.",
    ),
    (
        "kitchen",
        "Preserve the exact orange comic-book cat, kitchen composition, cream-red "
        "palette, and inked illustration style. The cat slowly reaches toward the "
        "steaming bowl and blinks once. Locked camera with a subtle handheld breath, "
        "stable markings, no cuts, no text.",
    ),
    (
        "desert",
        "Preserve the exact masked rider, science-fiction desert composition, cobalt-gold "
        "palette, and graphic painted style. The hoverbike idles as dust curls beneath "
        "it and the rider turns their helmet slightly. Gentle camera arc, stable identity, "
        "no cuts, no text.",
    ),
]


def create_references(root: Path, size=(768, 512)) -> list[Path]:
    """Create four deterministic text-free benchmark panels."""

    destination = root / "app" / "outputs" / "benchmarks" / "phase2b" / "references"
    destination.mkdir(parents=True, exist_ok=True)
    width, height = size
    paths = []
    palettes = [
        ("#33275b", "#f49b61", "#17122b"),
        ("#173f36", "#66b89b", "#d3b55b"),
        ("#f1dfbd", "#c34e3e", "#e68945"),
        ("#244d78", "#e5b04a", "#633d65"),
    ]
    for index, ((name, _), colors) in enumerate(zip(SCENES, palettes)):
        image = Image.new("RGB", size, colors[0])
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, height * 0.62, width, height), fill=colors[2])
        if index == 0:
            for x in range(0, width, 90):
                draw.rectangle((x, 245 - x % 70, x + 65, 320), fill="#211b43")
            draw.ellipse((310, 105, 450, 245), fill="#f1bd9c", outline="#21152f", width=8)
            draw.polygon([(330, 115), (430, 90), (455, 180), (305, 175)], fill="#34204c")
            draw.polygon([(260, 235), (500, 235), (450, 490), (300, 490)], fill="#4561a8")
            draw.polygon([(292, 255), (165, 300), (300, 315)], fill=colors[1])
        elif index == 1:
            for x, y, radius in [(100, 120, 90), (650, 140, 110), (530, 250, 80)]:
                draw.polygon(
                    [(x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y)],
                    fill="#39745b",
                )
            draw.rectangle((320, 190, 445, 360), fill="#79a7a3", outline="#102b29", width=8)
            draw.rectangle((340, 130, 425, 220), fill="#9bc5bc", outline="#102b29", width=8)
            draw.ellipse((358, 158, 376, 176), fill="#f7d35d")
            draw.ellipse((392, 158, 410, 176), fill="#f7d35d")
            draw.line((445, 240, 520, 195), fill="#d3b55b", width=16)
        elif index == 2:
            draw.rectangle((90, 80, 680, 390), fill="#f8edcf", outline="#6c302a", width=10)
            draw.ellipse((290, 125, 480, 315), fill=colors[2], outline="#542b27", width=10)
            draw.polygon([(310, 150), (325, 70), (365, 140)], fill=colors[2], outline="#542b27")
            draw.polygon([(405, 140), (450, 72), (465, 165)], fill=colors[2], outline="#542b27")
            draw.ellipse((335, 190, 360, 215), fill="#26333a")
            draw.ellipse((405, 190, 430, 215), fill="#26333a")
            draw.ellipse((500, 310, 650, 390), fill="#f7f0dd", outline=colors[1], width=8)
            draw.arc((515, 275, 635, 350), 200, 340, fill="#ffffff", width=6)
        else:
            draw.ellipse((60, 300, 720, 600), fill="#b97948")
            draw.polygon([(270, 165), (500, 145), (590, 330), (210, 350)], fill="#315c8d")
            draw.ellipse((310, 100, 450, 235), fill="#27324e", outline="#dfae4c", width=9)
            draw.polygon([(330, 145), (430, 130), (415, 185), (340, 190)], fill="#72b7d4")
            draw.ellipse((245, 325, 330, 410), fill="#1f2638", outline="#d8a445", width=8)
            draw.ellipse((480, 315, 565, 400), fill="#1f2638", outline="#d8a445", width=8)
        path = destination / f"{index + 1:02d}-{name}.png"
        image.save(path, format="PNG", optimize=False)
        paths.append(path.resolve())
    return paths


def _phase_time(events: list[dict], needle: str, last=False):
    matches = [
        float(event["elapsed_seconds"])
        for event in events
        if needle.lower() in str(event.get("phase", "")).lower()
    ]
    if not matches:
        return None
    return matches[-1] if last else matches[0]


def derive_task_timings(task: dict) -> dict:
    events = task.get("events") or []
    total = float(task.get("total_seconds") or 0.0)
    loading = _phase_time(events, "Loading model")
    loaded = _phase_time(events, "Model loaded")
    prepare = _phase_time(events, "Preparing Images")
    encoding_candidates = [
        value
        for value in (
            _phase_time(events, "Encoding Prompt"),
            _phase_time(events, "Prefetching Text Embeddings"),
        )
        if value is not None
    ]
    encoding = min(encoding_candidates) if encoding_candidates else None
    stage1 = _phase_time(events, "Denoising First Pass")
    stage2 = _phase_time(events, "Denoising Second Pass")
    vae = _phase_time(events, "VAE Decoding", last=True)
    writing = _phase_time(events, "Writing Output")

    def delta(start, end):
        if start is None or end is None:
            return None
        return round(max(0.0, end - start), 3)

    diffusion_end = vae if vae is not None else writing
    return {
        "model_load_seconds": delta(loading, loaded),
        "image_preparation_seconds": delta(prepare, encoding),
        "text_encoding_seconds": delta(encoding, stage1),
        "diffusion_seconds": delta(stage1, diffusion_end),
        "vae_seconds": delta(vae, writing),
        "write_seconds": delta(writing, total),
        "perceived_total_seconds": round(total, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:42026")
    parser.add_argument("--server-pid", required=True, type=int)
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--model", default="ltx2_22B_distilled_1_1")
    parser.add_argument("--seed", default=626262, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workspace", default="phase2b")
    parser.add_argument("--resolution", default="768x512")
    parser.add_argument("--frames", default=49, type=int)
    parser.add_argument("--steps", default=8, type=int)
    parser.add_argument("--guidance", default=1.0, type=float)
    parser.add_argument("--poll-seconds", default=0.5, type=float)
    args = parser.parse_args()

    repository = args.repository.resolve()
    references = create_references(repository)
    prompts = [prompt for _, prompt in SCENES]
    payload = {
        "prompt": "\n---CLIP_BOUNDARY---\n".join(prompts),
        "model_type": args.model,
        "resolution": args.resolution,
        "video_length": args.frames,
        "per_clip_frames": [args.frames] * len(prompts),
        "sliding_window_size": args.frames,
        "num_inference_steps": args.steps,
        "guidance_scale": args.guidance,
        "guidance_phases": 2 if args.guidance > 1 else 1,
        "seed": args.seed,
        "image_mode": 0,
        "negative_prompt": "",
        "repeat_generation": 1,
        "activated_loras": [],
        "loras_multipliers": "",
        "audio_prompt_type": "",
        "video_prompt_type": "",
        "image_prompt_type": "S",
        "image_start": [str(path) for path in references],
        "multi_prompts_gen_type": 3,
        "generation_mode": "video",
        "workspace": args.workspace,
        "settings_version": 2.56,
        "_phase2b_queue": True,
    }

    base_url = args.base_url.rstrip("/")
    process = psutil.Process(args.server_pid)
    output_dir = repository / "app" / "outputs" / args.workspace
    output_dir.mkdir(parents=True, exist_ok=True)
    files_before = {item.resolve() for item in output_dir.iterdir()}
    response = requests.post(f"{base_url}/api/v1/generate", json=payload, timeout=30)
    response.raise_for_status()
    job_id = response.json()["job_id"]
    started = time.monotonic()
    started_wall = datetime.now(timezone.utc).isoformat()
    samples = []
    transitions = []
    previous = None
    final_status = None
    response_failures = 0

    while True:
        elapsed = time.monotonic() - started
        try:
            status_response = requests.get(
                f"{base_url}/api/v1/status/{job_id}", timeout=1.0
            )
            status_response.raise_for_status()
            status = status_response.json()
        except requests.RequestException:
            response_failures += 1
            status = None
        if status is not None:
            state = (
                status.get("status"),
                status.get("phase"),
                status.get("step"),
                status.get("total_steps"),
            )
            if state != previous:
                transitions.append(
                    {
                        "elapsed_seconds": round(elapsed, 3),
                        "status": state[0],
                        "phase": state[1],
                        "step": state[2],
                        "total_steps": state[3],
                    }
                )
                print(json.dumps(transitions[-1]), flush=True)
                previous = state
            if status.get("status") in {"completed", "failed", "cancelled"}:
                final_status = status
                break
        try:
            gpu = _gpu_sample(args.server_pid)
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            gpu = {}
        samples.append(
            {
                "elapsed_seconds": round(elapsed, 3),
                "rss_bytes": _rss_tree(process),
                **gpu,
            }
        )
        time.sleep(args.poll_seconds)

    total_seconds = time.monotonic() - started
    new_videos = sorted(
        item.resolve()
        for item in output_dir.iterdir()
        if item.resolve() not in files_before
        and item.suffix.lower() in {".mp4", ".webm", ".mkv"}
    )
    probes = {str(path): _probe(path) for path in new_videos}
    task_timings = []
    for task in final_status.get("task_timings") or []:
        task_timings.append({**task, "derived": derive_task_timings(task)})

    def peak(key):
        values = [sample[key] for sample in samples if key in sample]
        return max(values) if values else None

    def average(key):
        values = [sample[key] for sample in samples if key in sample]
        return round(statistics.fmean(values), 3) if values else None

    report = {
        "schema_version": 1,
        "started_at_utc": started_wall,
        "job_id": job_id,
        "payload": payload,
        "status": final_status.get("status"),
        "total_seconds": round(total_seconds, 3),
        "task_timings": task_timings,
        "responsiveness": {
            "failed_or_timed_out_polls": response_failures,
        },
        "resources": {
            "peak_process_tree_rss_bytes": peak("rss_bytes"),
            "peak_server_gpu_memory_mib": peak("server_gpu_memory_mib"),
            "peak_gpu_utilization_percent": peak("gpu_utilization_percent"),
            "average_gpu_utilization_percent": average("gpu_utilization_percent"),
        },
        "output_paths": [str(path) for path in new_videos],
        "output_probes": probes,
        "transitions": transitions,
        "samples": samples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "samples"},
            indent=2,
        )
    )
    return 0 if final_status.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
