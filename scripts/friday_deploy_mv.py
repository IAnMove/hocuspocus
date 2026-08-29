#!/usr/bin/env python3
"""Wise cinema-sage song: don't deploy on Friday. Then landscape H3 MV."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:42004"
ROOT = Path(__file__).resolve().parent
LOG = ROOT / "friday_deploy_mv.log"
OUTPUTS = Path("/home/ina/pinokio/api/Maestro-next.git/app/outputs")

STYLE = (
    "wise cinematic mentor song, Star Wars swamp sage choir, slow drums, "
    "temple bells, dry humor, Spanish lyrics with inverted Yoda cadence on the hook, "
    "no rap, no trap, no pop, no concert stage"
)
LYRICS = """[Estrofa]
En el pantano el maestro cierra los ojos
el pager parpadea, el cluster ya tose
viernes de tarde, el merge está listo
si esto se rompe, el sábado es tu oficio

[Estribillo]
En viernes, desplegar no debes
si cae producción, el finde te come
hasta el lunes no llegan refuerzos
en viernes, desplegar no debes

[Estrofa]
El mago gris mira el diff y no firma
el sensei apaga la luz del CPD
el sabio pequeño verde dice despacio
mejor el lunes, joven sysadmin impaciente

[Estribillo]
En viernes, desplegar no debes
si cae producción, el finde te come
hasta el lunes no llegan refuerzos
en viernes, desplegar no debes
"""
SCENE = (
    "Videoclip landscape 16:9: grandes sabios del cine enseñan a no desplegar en viernes. "
    "Estética cinematográfica: un maestro pequeño verde de pantano tipo Yoda, un mago gris "
    "con bastón tipo Gandalf, un sensei de dojo tipo Miyagi. No raperos. "
    "El aprendizaje: no desplieges en viernes; si sale mal te quedas sin fin de semana "
    "y hasta el lunes no vienen los refuerzos. "
    "Visuales: pantano, consejo de maestros, sala de servidores al fondo, pager, "
    "pantalla en rojo un viernes a las 18:00, el sysadmin joven que quiere pulsar Deploy. "
    "Narrativa de fábula, coros en off, 16:9. Sin MCs, hoodies, cadenas ni escenario."
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
    (ROOT / "friday_deploy_song.json").write_text(
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
                "contemporary streetwear, Friday party club"
            ),
            "direct_video_master_prompt": (
                "Cine de maestros: pantano, consejo, dojo y CPD al fondo, 16:9. "
                "Sabios tipo Yoda, Gandalf y Miyagi enseñan: no desplieges en viernes. "
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
    (ROOT / "friday_deploy_pipeline.json").write_text(
        json.dumps({
            "source": source,
            "audio_path": audio_path,
            "pipeline": pipeline,
            "clip_count": len(clips),
        }, indent=2),
        encoding="utf-8",
    )
    wait_pipeline(pipeline["pipeline_id"])
    log("friday deploy music video done")


if __name__ == "__main__":
    main()
