#!/usr/bin/env python3
"""Queue 15 short H3 clips: one series character, one Spanish joke each."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("MAESTRO_API", "http://127.0.0.1:42004")
ROOT = Path(__file__).resolve().parent
CLIPS_FILE = Path(os.environ.get("JOKE_CLIPS_FILE", str(ROOT / "joke_clips.json")))
RESOLUTION = os.environ.get("JOKE_RESOLUTION", "960x544")
CLIPS = json.loads(CLIPS_FILE.read_text(encoding="utf-8"))


def prompt_for(item: dict) -> str:
    visual = (
        "Cómic cinematográfico, grano suave, no fotorealismo 3D. "
        f"{item['who']}. Mira a cámara y suelta el chiste."
    )
    if item["series"] == "Los Simpson":
        visual = (
            "Dibujo 2D amarillo estilo Los Simpson, líneas planas, no live action. "
            f"{item['who']}. Mira a cámara y suelta el chiste."
        )
    return (
        f"integrated_multimodal_description: [Shot 1] {visual} "
        f"Dice: <d>[Spanish] {item['joke']}</d> "
        "Solo esa frase. Cámara: plano medio, ligero zoom. "
        "\n\noverall_soundscape: Sala quieta. Solo su voz.\n\nnon_diegetic_music: N/A"
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
        body = {
            "prompt": prompt_for(item),
            "model_type": "minimax_h3_legacy",
            "resolution": RESOLUTION,
            "video_length": 124,
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
            "h3_audio_prompt": "Only explicitly described sounds. If none are described, remain silent.",
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
            "duration_seconds": 5.2,
            "_duration_seconds": 5.2,
            "_batch_label": f"joke-{index:02d}-{item['series']}",
        }
        try:
            result = post("/api/v1/generate", body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()
            raise SystemExit(f"Clip {index} {item['series']} failed: {exc.code} {detail}") from exc
        queued.append({
            "index": index,
            "series": item["series"],
            "joke": item["joke"],
            **result,
        })
        print(f"{index:02d} {item['series']}: {result.get('job_id')} {result.get('status')}")
        time.sleep(0.3)
    out = ROOT / f"{CLIPS_FILE.stem}_jobs.json"
    out.write_text(json.dumps(queued, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Queued {len(queued)} clips → {out}")


if __name__ == "__main__":
    main()
