#!/usr/bin/env python3
"""Wait for the portrait joke queue, then MiniMax song, then landscape MV."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:42004"
ROOT = Path(__file__).resolve().parent
LOG = ROOT / "portrait_then_dwarf.log"

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

SHOTS = [
    (
        "[Shot 1] Minas de Khazad-dûm, 16:9 landscape. Enanos bajos y robustos "
        "con barbas trenzadas y cotas de malla pican piedra junto a vetas de oro. "
        "Antorchas, vapor, pico contra roca. Nadie mira a cámara como rapero. "
        "Cámara: travelling lento por la galería."
    ),
    (
        "[Shot 1] Sala de piedra con mesas, 16:9 landscape. Coro de enanos "
        "alza jarras de cerveza y hachas. Barbas, yelmos, fuego de hogar. "
        "Nadie con hoodie ni cadena de oro moderna. Cámara: plano general "
        "que se acerca al yunque."
    ),
    (
        "[Shot 1] Puente de piedra sobre abismo, 16:9 landscape. Tres enanos "
        "con hachas avanzan en formación bajo antorchas. Estética Weta, "
        "bajos y anchos. Sin escenario de concierto. Cámara: contrapicado "
        "que sigue el paso."
    ),
    (
        "[Shot 1] Gran puerta de Khazad-dûm al amanecer, 16:9 landscape. "
        "Enanos en silueta, banderas de casa, pico y pan. El coro suena "
        "fuera de campo. Nadie canta a cámara. Cámara: retrocede hacia el valle."
    ),
]


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


def compact_prompt(visual: str) -> str:
    return (
        f"integrated_multimodal_description: {visual} "
        "Cinematografía Peter Jackson / Weta, ocres y antorchas. "
        "Enanos de Tierra Media, no humanos altos, no raperos. "
        "\n\noverall_soundscape: Pico, piedra, fuego lejano. Sin voz a cámara.\n\n"
        "non_diegetic_music: N/A"
    )


def resolve_audio_path(filename: str, audio_path: str) -> str:
    if audio_path and Path(audio_path).is_file():
        return audio_path
    for candidate in (
        Path("/home/ina/pinokio/api/Maestro-next.git/app/outputs") / filename,
        Path("app/outputs") / filename,
    ):
        if candidate.is_file():
            return str(candidate)
    return audio_path or filename


def generate_minimax_song() -> tuple[str, dict]:
    log("starting MiniMax Music song")
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
    audio_path = resolve_audio_path(filename, str(candidates[0].get("audio_path") or ""))
    return audio_path, music


def generate_ace_step_song() -> tuple[str, dict]:
    log("MiniMax Music blocked; generating local ACE-Step song so the video can start")
    music = request_json("POST", "/api/v1/director/generate-music", {
        "style": STYLE,
        "lyrics": LYRICS,
        "instrumental": False,
        "duration_seconds": 72,
        "model_type": "ace_step_v1_5_xl_sft_lm_4b",
        "seed": -1,
    }, timeout=1800)
    filename = str(music.get("filename") or "")
    audio_path = resolve_audio_path(filename, str(music.get("audio_path") or ""))
    if not audio_path:
        raise RuntimeError("ACE-Step returned no audio path")
    return audio_path, music


def clip_plans_for(clips: list[dict]) -> list[dict]:
    plans = []
    for index, clip in enumerate(clips):
        visual = SHOTS[index % len(SHOTS)]
        plans.append({
            "shot_id": f"shot-{index + 1}",
            "video_prompt": compact_prompt(visual),
            "image_prompt": "",
            "duration_sec": clip.get("duration_sec"),
            "duration_frames": clip.get("duration_frames"),
            "_director_duration_sec": clip.get("duration_sec"),
            "metadata": {
                "label": clip.get("label") or f"section-{index + 1}",
                "start": clip.get("start"),
                "end": clip.get("end"),
            },
        })
    return plans


def main() -> None:
    log("waiting for portrait joke queue to finish")
    wait_gpu_idle()

    existing = Path(
        "/home/ina/pinokio/api/Maestro-next.git/app/outputs/"
        "2026-08-20-08h27m07s_seed607414041_[Estrofa]Bajo la montaña el fuego no duermeel pico golpea el corazón de piedraoro en las vetas,.wav"
    )
    try:
        audio_path, music = generate_minimax_song()
        source = "minimax"
    except Exception as exc:
        log(f"MiniMax Music unavailable ({exc})")
        if existing.is_file():
            log(f"reusing existing local song {existing.name}")
            audio_path, music = str(existing), {"reused": True, "audio_path": str(existing)}
            source = "ace_step_existing"
        else:
            audio_path, music = generate_ace_step_song()
            source = "ace_step"
    if not audio_path or not Path(audio_path).is_file():
        raise RuntimeError(f"Song file missing: {audio_path}")
    log(f"song source={source} file={Path(audio_path).name}")
    (ROOT / "night_dwarf_song.json").write_text(
        json.dumps({"source": source, "job": music, "audio_path": audio_path}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log("analyzing song")
    analysis = request_json("POST", "/api/v1/audio/analyze", {
        "audio_path": audio_path,
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
    if not clips:
        raise RuntimeError("plan-structure returned no clips")
    log(f"planned {len(clips)} landscape clips; MiniMax M3 will write prompts")

    log("starting landscape music video")
    pipeline = request_json("POST", "/api/v1/director/pipeline/start", {
        "pipeline_type": "music_video",
        "auto_mode": True,
        "scene_description": SCENE,
        "spoken_language": "Español de España",
        "audio_path": audio_path,
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
        "llm_provider": "minimax",
        "llm_model_id": "MiniMax-M3",
        "llm_remote_url": "https://api.minimax.io",
        "writing_provider": "minimax",
        "writing_model": "MiniMax-M3",
    })
    log(f"pipeline {pipeline.get('pipeline_id')}")
    (ROOT / "night_dwarf_pipeline.json").write_text(
        json.dumps({
            "source": source,
            "audio_path": audio_path,
            "pipeline": pipeline,
            "clip_count": len(clips),
        }, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
