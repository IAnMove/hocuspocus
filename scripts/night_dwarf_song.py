#!/usr/bin/env python3
"""After the joke queue: MiniMax song, then landscape H3 music video."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:42004"
ROOT = Path(__file__).resolve().parent
LOG = ROOT / "night_dwarf_song.log"

STYLE = (
    "epic dwarven choir, war drums, deep male baritone, stone halls, "
    "folk metal, original Middle-earth mood, Spanish lyrics, no rap, no pop"
)
LYRICS = """[Estrofa]
Bajo la montaña el fuego no duerme
el pico golpea el corazón de piedra
oro en las vetas, orgullo en la barba
Khazad no olvida, Khazad espera

[Estribillo]
Por las salas de piedra
por el hacha y el pan
si el mundo se apaga
nosotros cantamos

[Estrofa]
Hermanos de yunque, hermanos de mina
la noche es larga, la cerveza es fina
nadie nos compra, nadie nos echa
la raza de enanos guarda la brecha

[Estribillo]
Por las salas de piedra
por el hacha y el pan
si el mundo se apaga
nosotros cantamos
"""
SCENE = (
    "Videoclip de enanos de la Tierra Media. Estética Peter Jackson / Weta: "
    "barbas trenzadas, cotas de malla, hachas, minas de Khazad-dûm, oro y "
    "antorchas. Nadie canta a cámara de rapero moderno. Sin MCs, hoodies, "
    "cadenas ni escenarios de concierto. Enanos bajos y robustos. "
    "Narrativa de montaña, coros en off, landscape 16:9."
)


def log(message: str) -> None:
    line = time.strftime("%H:%M:%S") + " " + message
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def request_json(method: str, path: str, body: dict | None = None, timeout: int = 60) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        API + path,
        data=data,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"{path} {exc.code}: {detail}") from exc


def wait_gpu_idle(timeout_s: int = 8 * 3600) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        data = request_json("GET", "/api/v1/jobs")
        live = [
            job for job in (data.get("jobs") or [])
            if str(job.get("status") or "") in {"queued", "running"}
        ]
        if not live:
            return
        log(f"GPU still busy: {len(live)} job(s)")
        time.sleep(20)
    raise TimeoutError("GPU queue did not idle")


def wait_music_job(job_id: str, timeout_s: int = 1800) -> dict:
    deadline = time.time() + timeout_s
    path = f"/api/v1/stories/music-candidates/jobs/{job_id}"
    while time.time() < deadline:
        job = request_json("GET", path)
        status = str(job.get("status") or "")
        log(f"MiniMax Music {status}: {job.get('message') or ''}")
        if status == "completed":
            return job
        if status in {"failed", "cancelled", "crashed"}:
            raise RuntimeError(f"MiniMax Music {status}: {job.get('error') or job.get('message')}")
        time.sleep(8)
    raise TimeoutError("MiniMax Music timed out")


def main() -> None:
    log("waiting for portrait joke queue to finish")
    wait_gpu_idle()

    music: dict = {}
    audio_path = ""
    log("starting MiniMax Music song")
    try:
        started = request_json("POST", "/api/v1/stories/music-candidates/jobs", {
            "model": "music-3.0",
            "count": 1,
            "prompt": STYLE[:300],
            "lyrics": LYRICS[:3500],
            "instrumental": False,
        })
        job_id = started.get("jobId") or started.get("job_id")
        if not job_id:
            raise RuntimeError(f"MiniMax Music did not return a job id: {started}")
        log(f"MiniMax Music job {job_id}")
        music = wait_music_job(job_id)
        candidates = (music.get("result") or {}).get("candidates") or music.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"MiniMax Music returned no candidates: {json.dumps(music)[:800]}")
        filename = candidates[0]["filename"]
        audio_path = str(candidates[0].get("audio_path") or "")
        if not audio_path or not Path(audio_path).is_file():
            for candidate in (
                Path("/home/ina/pinokio/api/Maestro-next.git/app/outputs") / filename,
                Path("app/outputs") / filename,
            ):
                if candidate.is_file():
                    audio_path = str(candidate)
                    break
            else:
                audio_path = filename
    except Exception as exc:
        log(f"MiniMax Music unavailable ({exc}); falling back to local ACE-Step")
        music = request_json("POST", "/api/v1/director/generate-music", {
            "style": STYLE,
            "lyrics": LYRICS,
            "instrumental": False,
            "duration_seconds": 72,
            "model_type": "ace_step_v1_5_xl_sft_lm_4b",
            "seed": -1,
        }, timeout=1800)
        audio_path = str(music.get("audio_path") or "")
        filename = str(music.get("filename") or Path(audio_path).name)
        if audio_path and not Path(audio_path).is_file():
            alt = Path("/home/ina/pinokio/api/Maestro-next.git/app/outputs") / filename
            if alt.is_file():
                audio_path = str(alt)
    if not audio_path:
        raise RuntimeError("No song file after MiniMax and ACE-Step")
    log(f"song file {Path(audio_path).name} path {audio_path}")
    (ROOT / "night_dwarf_song.json").write_text(
        json.dumps({"job": music, "audio_path": audio_path}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log("analyzing MiniMax song")
    analysis = request_json("POST", "/api/v1/audio/analyze", {
        "audio_path": audio_path if Path(audio_path).is_file() else filename,
        "transcribe": True,
        "extract_vocals": True,
        "lyrics_hint": LYRICS,
    }, timeout=600)

    log("planning landscape clips")
    structure = request_json("POST", "/api/v1/audio/plan-structure", {
        "analysis": analysis,
        "video_model": "minimax_h3_legacy",
        "energy_bias": 0,
    }, timeout=120)
    clips = structure.get("clips") or []
    log(f"planned {len(clips)} landscape clips")

    log("starting landscape music video")
    pipeline = request_json("POST", "/api/v1/director/pipeline/start", {
        "pipeline_type": "music_video",
        "auto_mode": True,
        "scene_description": SCENE,
        "spoken_language": "Español de España",
        "audio_path": audio_path if Path(audio_path).is_file() else filename,
        "planned_clips": clips,
        "lyrics": analysis.get("lyrics") or LYRICS,
        "bpm": analysis.get("bpm"),
        "seamless": False,
        "shot_image_guidance": "prompt_only",
        "video_model": "minimax_h3_legacy",
        "director_aspect_ratio": "16:9",
        "video_params": {
            "resolution": "960x544",
            "num_inference_steps": 20,
            "h3_reference_mode": "first_frame",
            "h3_audio_prompt": (
                "Only explicitly described sounds. If none are described, remain silent."
            ),
            "h3_model_profile": "quality",
        },
        "music_video_treatment": {
            "generation_mode": "direct_video",
            "mode": "narrative",
            "performer_presence": 0,
            "lip_sync": "none",
            "forbidden_elements": (
                "modern rappers, MCs, hoodies, gold chains, concert stages, "
                "human-tall dwarves, contemporary streetwear"
            ),
            "direct_video_master_prompt": (
                "Cinematografía de fantasía tipo trilogía de Peter Jackson, "
                "16:9 landscape: ocres, antorchas, piedra húmeda, enanos de Weta. "
                "Ningún rapero moderno."
            ),
        },
        "allow_clip_text": False,
        "use_director_v2": True,
        "llm_provider": "local",
        "writing_provider": "maestro",
    })
    log(f"pipeline {pipeline.get('pipeline_id')}")
    (ROOT / "night_dwarf_pipeline.json").write_text(
        json.dumps({"music": music, "pipeline": pipeline, "clip_count": len(clips)}, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
