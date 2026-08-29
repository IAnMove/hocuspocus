#!/usr/bin/env python3
"""Portrait dwarf MV (reuse song), then dark LOTR orc song + landscape MV."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:42004"
ROOT = Path(__file__).resolve().parent
LOG = ROOT / "portrait_dwarf_then_orcs.log"
OUTPUTS = Path("/home/ina/pinokio/api/Maestro-next.git/app/outputs")
DWARF_SONG = OUTPUTS / (
    "2026-08-20-08h27m07s_seed607414041_[Estrofa]Bajo la montaña "
    "el fuego no duermeel pico golpea el corazón de piedraoro en las vetas,.wav"
)

DWARF_LYRICS = """[Estrofa]
Bajo la montaña el fuego no duerme
el pico golpea el corazón de piedra
oro en las vetas, orgullo en la barba
Khazad no olvida, Khazad espera

[Estribillo]
Por las salas de piedra
por el hacha y el pan
si el mundo se apaga
nosotros cantamos
"""
DWARF_SCENE = (
    "Videoclip vertical 9:16 de enanos de la Tierra Media. Estética Peter Jackson / Weta: "
    "barbas trenzadas, cotas de malla, hachas, minas de Khazad-dûm, oro y antorchas. "
    "Enanos bajos y robustos llenando el marco alto. Cámara que recorre de botas a yelmo. "
    "Nadie canta a cámara de rapero moderno. Sin MCs, hoodies, cadenas ni escenarios. "
    "Narrativa de montaña, coros en off, portrait 9:16."
)

ORC_STYLE = (
    "dark Mordor war chant, guttural male choir, war drums, grinding iron, "
    "ash and fire, Uruk-hai march, original Middle-earth orc mood, "
    "Spanish lyrics, no rap, no pop, no modern trap"
)
ORC_LYRICS = """[Estrofa]
Nacimos en foso, en hierro y en grito
la luna es un hueso, la tierra un delito
Isengard sopla, Mordor nos llama
la carne es el peaje, la guerra la cama

[Estribillo]
Somos la marea, somos el diente
si el bosque se quema, avanzamos de frente
ni rey ni piedad, ni sol en la frente
los orcos no olvidan, los orcos no mienten

[Estrofa]
Uruk de la forja, negro de ceniza
el látigo canta, la fosa precisa
Minas Morgul abre su boca de piedra
la noche es el reino, la sangre la seda

[Estribillo]
Somos la marea, somos el diente
si el bosque se quema, avanzamos de frente
ni rey ni piedad, ni sol en la frente
los orcos no olvidan, los orcos no mienten
"""
ORC_SCENE = (
    "Videoclip landscape 16:9 de orcos del Señor de los Anillos. Estética Peter Jackson / Weta: "
    "Uruk-hai, orcos de Mordor y de las Minas de Moria, armaduras negras, cimitarras, "
    "estandartes de Ojo, ceniza, forjas de Isengard, fosos, Minas Morgul. "
    "Orcos como protagonistas: bajos o deformes, no humanos altos, no raperos. "
    "Sin MCs, hoodies, cadenas, ni escenarios de concierto. "
    "Narrativa de guerra oscura, coros en off, landscape 16:9."
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
        pipelines = []
        try:
            listing = request_json("GET", "/api/v1/director/pipelines")
            pipelines = [
                item for item in (listing.get("pipelines") or listing or [])
                if isinstance(item, dict)
                and str(item.get("status") or "") in {"queued", "running"}
            ]
        except Exception:
            pipelines = []
        if not live and not pipelines:
            return
        log(f"still busy: jobs={len(live)} pipelines={len(pipelines)}")
        time.sleep(20)
    raise TimeoutError("queue did not idle")


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


def resolve_audio_path(filename: str, audio_path: str) -> str:
    if audio_path and Path(audio_path).is_file():
        return audio_path
    for candidate in (OUTPUTS / filename, Path("app/outputs") / filename):
        if candidate.is_file():
            return str(candidate)
    return audio_path or filename


def generate_minimax_song(style: str, lyrics: str) -> tuple[str, dict]:
    log("starting MiniMax Music song")
    started = request_json("POST", "/api/v1/stories/music-candidates/jobs", {
        "model": "music-3.0",
        "count": 1,
        "prompt": style[:300],
        "lyrics": lyrics[:3500],
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


def generate_ace_step_song(style: str, lyrics: str) -> tuple[str, dict]:
    log("MiniMax Music blocked; generating local ACE-Step song")
    music = request_json("POST", "/api/v1/director/generate-music", {
        "style": style,
        "lyrics": lyrics,
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


def start_music_video(
    *,
    audio_path: str,
    lyrics: str,
    scene: str,
    aspect: str,
    resolution: str,
    master: str,
    forbidden: str,
) -> dict:
    log(f"analyzing {Path(audio_path).name}")
    analysis = request_json("POST", "/api/v1/audio/analyze", {
        "audio_path": audio_path,
        "transcribe": True,
        "extract_vocals": True,
        "lyrics_hint": lyrics,
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
        "scene_description": scene,
        "spoken_language": "Español de España",
        "audio_path": audio_path,
        "planned_clips": clips,
        "lyrics": analysis.get("lyrics") or lyrics,
        "bpm": analysis.get("bpm"),
        "seamless": False,
        "shot_image_guidance": "prompt_only",
        "video_model": "minimax_h3_legacy",
        "director_aspect_ratio": aspect,
        "video_params": {
            "resolution": resolution,
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
            "forbidden_elements": forbidden,
            "direct_video_master_prompt": master,
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
    return {"analysis": analysis, "clips": clips, "pipeline": pipeline}


def main() -> None:
    if not DWARF_SONG.is_file():
        raise RuntimeError(f"Missing dwarf song: {DWARF_SONG}")

    log("starting portrait dwarf music video with reused song")
    dwarf = start_music_video(
        audio_path=str(DWARF_SONG),
        lyrics=DWARF_LYRICS,
        scene=DWARF_SCENE,
        aspect="9:16",
        resolution="544x960",
        master=(
            "Cinematografía de fantasía tipo trilogía de Peter Jackson, "
            "9:16 portrait: ocres, antorchas, piedra húmeda, enanos de Weta "
            "llenos en el marco vertical. Ningún rapero moderno."
        ),
        forbidden=(
            "modern rappers, MCs, hoodies, gold chains, concert stages, "
            "human-tall dwarves, contemporary streetwear, letterbox bars"
        ),
    )
    (ROOT / "portrait_dwarf_pipeline.json").write_text(
        json.dumps({
            "audio_path": str(DWARF_SONG),
            "pipeline": dwarf["pipeline"],
            "clip_count": len(dwarf["clips"]),
        }, indent=2),
        encoding="utf-8",
    )
    wait_pipeline(dwarf["pipeline"]["pipeline_id"])
    log("portrait dwarf music video done")

    wait_gpu_idle()
    try:
        audio_path, music = generate_minimax_song(ORC_STYLE, ORC_LYRICS)
        source = "minimax"
    except Exception as exc:
        log(f"MiniMax Music unavailable ({exc})")
        audio_path, music = generate_ace_step_song(ORC_STYLE, ORC_LYRICS)
        source = "ace_step"
    if not audio_path or not Path(audio_path).is_file():
        raise RuntimeError(f"Orc song file missing: {audio_path}")
    log(f"orc song source={source} file={Path(audio_path).name}")
    (ROOT / "orc_song.json").write_text(
        json.dumps({"source": source, "job": music, "audio_path": audio_path}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    orc = start_music_video(
        audio_path=audio_path,
        lyrics=ORC_LYRICS,
        scene=ORC_SCENE,
        aspect="16:9",
        resolution="960x544",
        master=(
            "Cinematografía de fantasía oscura tipo trilogía de Peter Jackson, "
            "16:9 landscape: ceniza, hierro, fuego verde, orcos y Uruk-hai de Weta. "
            "Ningún rapero moderno. Los orcos son los protagonistas."
        ),
        forbidden=(
            "modern rappers, MCs, hoodies, gold chains, concert stages, "
            "handsome humans as orcs, contemporary streetwear, elves as heroes"
        ),
    )
    (ROOT / "orc_pipeline.json").write_text(
        json.dumps({
            "source": source,
            "audio_path": audio_path,
            "pipeline": orc["pipeline"],
            "clip_count": len(orc["clips"]),
        }, indent=2),
        encoding="utf-8",
    )
    wait_pipeline(orc["pipeline"]["pipeline_id"])
    log("orc music video done")


if __name__ == "__main__":
    main()
