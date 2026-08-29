#!/usr/bin/env python3
"""Queue presenter + portrait character jokes with mixed 10s/14s durations."""
from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("MAESTRO_API", "http://127.0.0.1:42005")
ROOT = Path(__file__).resolve().parent
CLIPS_FILE = Path(os.environ.get("JOKE_CLIPS_FILE", str(ROOT / "joke_round_portrait.json")))
RESOLUTION = os.environ.get("JOKE_RESOLUTION", "544x960")
CLIPS = json.loads(CLIPS_FILE.read_text(encoding="utf-8"))


def h3_frames(seconds: float) -> int:
    requested = float(seconds) * 24.0
    aligned = 5 + max(0, math.ceil((requested - 5) / 17.0)) * 17
    return int(min(345, max(124, aligned)))


def prompt_for(item: dict) -> str:
    style = item.get("style") or "Cómic cinematográfico, grano suave, no fotorealismo 3D."
    who = item["who"]
    speaker = item.get("speaker") or who.split(",")[0]
    joke = item["joke"]
    if item.get("role") == "presenter":
        action = "Mira a cámara, señala con el micro y lanza el reto. No canta."
    else:
        action = (
            "Mira a cámara, toma aire y suelta el chiste de una vez. "
            "No canta. No es un rapero."
        )
    return (
        f"integrated_multimodal_description: [Shot 1] {style} {who}. "
        f"{action} Encuadre vertical 9:16, plano medio, ligero zoom. "
        f"{speaker} dice: <d>[Spanish] {joke}</d> "
        "PORTRAIT COMPOSITION LOCK: Compose natively for the full 544x960 vertical portrait "
        "canvas. Never letterbox a landscape frame inside it. "
        "\n\noverall_soundscape: N/A\n\nnon_diegetic_music: N/A"
    )


def post(path: str, body: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def main() -> None:
    queued = []
    for index, item in enumerate(CLIPS, start=1):
        seconds = float(item.get("seconds") or 10)
        frames = h3_frames(seconds)
        duration = round(frames / 24.0, 3)
        label = item.get("role") or "joke"
        series = item["series"]
        body = {
            "prompt": prompt_for(item),
            "model_type": "minimax_h3_legacy",
            "resolution": RESOLUTION,
            "video_length": frames,
            "num_inference_steps": 20,
            "guidance_scale": 1.0,
            "seed": -1,
            "image_mode": 0,
            "negative_prompt": "",
            "repeat_generation": 1,
            "activated_loras": [],
            "loras_multipliers": "",
            "settings_version": 2.52,
            "flow_shift": 12.0,
            "h3_audio_shift": 3.0,
            "h3_audio_prompt": "",
            "h3_ref_image_size": "match",
            "h3_reference_mode": "first_frame",
            "h3_model_profile": "quality",
            "minimax_h3_turbo_mode": False,
            "h3_allow_low_memory_fallback": False,
            "video_prompt_type": "",
            "audio_prompt_type": "",
            "image_prompt_type": "",
            "generation_mode": "video",
            "multi_prompts_gen_type": 2,
            "duration_seconds": duration,
            "_duration_seconds": duration,
            "_batch_label": f"joke-r2-{index:02d}-{label}-{series}",
        }
        try:
            result = post("/api/v1/generate", body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()
            raise SystemExit(f"Clip {index} {series} failed: {exc.code} {detail}") from exc
        queued.append({
            "index": index,
            "role": label,
            "series": series,
            "seconds": duration,
            "frames": frames,
            "joke": item["joke"],
            **result,
        })
        print(
            f"{index:02d} {label:9} {series:24} {duration:5}s "
            f"{result.get('job_id')} {result.get('status')}"
        )
        time.sleep(0.3)
    out = ROOT / f"{CLIPS_FILE.stem}_jobs.json"
    out.write_text(json.dumps(queued, ensure_ascii=False, indent=2), encoding="utf-8")
    jokes = [item for item in queued if item.get("role") != "presenter"]
    total = sum(float(item["seconds"]) for item in jokes)
    print(f"Queued {len(queued)} clips → {out}")
    print(f"Character jokes {len(jokes)} = {total:.1f}s (~{total/60:.1f} min, packs of ~1 min)")


if __name__ == "__main__":
    main()
