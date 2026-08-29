#!/usr/bin/env python3
"""MiniMax (or ACE-Step) hobbit song, then landscape H3 music video."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:42004"
ROOT = Path(__file__).resolve().parent
LOG = ROOT / "hobbit_mv.log"
OUTPUTS = Path("/home/ina/pinokio/api/Maestro-next.git/app/outputs")

STYLE = (
    "warm Shire folk song, tin whistle, acoustic guitar, rustic tavern choir, "
    "gentle drums, hobbit drinking song, original Middle-earth countryside mood, "
    "Spanish lyrics, no rap, no pop, no trap"
)
LYRICS = """[Estrofa]
La colina es verde, la puerta es redonda
el pan está caliente, la pipa no se apaga
pies peludos en el césped, la tarde se alarga
la Comarca no corre, la Comarca camina

[Estribillo]
Por el segundo desayuno
por la cerveza y el sol
si el mundo se pone serio
nosotros cantamos igual

[Estrofa]
Bilbo guarda secretos, Frodo mira el camino
Sam no deja el huerto, Merry parte el pan
Pippin se ríe bajo el árbol de la fiesta
pequeños, constantes, dueños del jardín

[Estribillo]
Por el segundo desayuno
por la cerveza y el sol
si el mundo se pone serio
nosotros cantamos igual
"""
SCENE = (
    "Videoclip landscape 16:9 de hobbits del Señor de los Anillos. Estética Peter Jackson / Weta: "
    "hobbits pequeños, pies peludos, rizos, chalecos de paño, la Comarca, puertas redondas, "
    "colinas verdes, humo de pipa, taberna de Bolsón Cerrado, camino del Este. "
    "Hobbits como protagonistas, no humanos altos, no raperos. "
    "Sin MCs, hoodies, cadenas ni escenarios de concierto. "
    "Narrativa pastoral, coros en off, landscape 16:9."
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


def wait_pipeline(pipeline_id: str, timeout_s: int = 8 * 3600) -> dict:
    deadline = time.time() + timeout_s
    path = f"/api/v1/director/pipeline/{pipeline_id}"
    while time.time() < deadline:
        job = request_json("GET", path)
        status = str(job.get("status") or "")
        phase = str(job.get("phase") or "")
        prog = job.get("progress") or {}
        msg = prog.get("message") if isinstance(prog, dict) else prog
        log(f"pipeline {pipeline_id} {status}/{phase}: {msg}")
        if status in {"completed", "failed", "cancelled", "crashed"}:
            if status != "completed":
                raise RuntimeError(f"pipeline {pipeline_id} {status}: {job.get('error')}")
            return job
        time.sleep(20)
    raise TimeoutError(f"pipeline {pipeline_id} timed out")


def resolve_audio_path(filename: str, audio_path: str) -> str:
    if audio_path and Path(audio_path).is_file():
        return audio_path
    for candidate in (OUTPUTS / filename, Path("app/outputs") / filename):
        if candidate.is_file():
            return str(candidate)
    return audio_path or filename


def generate_song() -> tuple[str, dict, str]:
    try:
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
        return audio_path, music, "minimax"
    except Exception as exc:
        log(f"MiniMax Music unavailable ({exc})")
        log("generating local ACE-Step song")
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
        return audio_path, music, "ace_step"


def main() -> None:
    audio_path, music, source = generate_song()
    if not audio_path or not Path(audio_path).is_file():
        raise RuntimeError(f"Song file missing: {audio_path}")
    log(f"song source={source} file={Path(audio_path).name}")
    (ROOT / "hobbit_song.json").write_text(
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
    structure = request_json("POST", "/api/v1/audio/plan-structure", {
        "analysis": analysis,
        "video_model": "minimax_h3_legacy",
        "energy_bias": 0,
    }, timeout=120)
    clips = structure.get("clips") or []
    if not clips:
        raise RuntimeError("plan-structure returned no clips")
    log(f"planned {len(clips)} clips; MiniMax M3 will write prompts")

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
                "human-tall hobbits, contemporary streetwear, elves as heroes, orcs"
            ),
            "direct_video_master_prompt": (
                "Cinematografía de fantasía cálida tipo trilogía de Peter Jackson, "
                "16:9 landscape: verdes, dorados, humo de pipa, hobbits de Weta. "
                "Ningún rapero moderno. Los hobbits son los protagonistas."
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
    (ROOT / "hobbit_pipeline.json").write_text(
        json.dumps({
            "source": source,
            "audio_path": audio_path,
            "pipeline": pipeline,
            "clip_count": len(clips),
        }, indent=2),
        encoding="utf-8",
    )
    wait_pipeline(pipeline["pipeline_id"])
    log("hobbit music video done")


if __name__ == "__main__":
    main()
