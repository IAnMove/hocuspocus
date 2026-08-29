#!/usr/bin/env python3
"""Three geek Star Wars MVs: Friday kernel, denied merge, works on my machine."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:42004"
ROOT = Path(__file__).resolve().parent
LOG = ROOT / "vader_it_trilogy.log"
OUTPUTS = Path("/home/ina/pinokio/api/Maestro-next.git/app/outputs")

JOBS = [
    {
        "slug": "vader_friday_kernel",
        "style": (
            "dark comic industrial rock, Mustafar fire, sysadmin panic, "
            "Spanish lyrics, no rap, no trap, no pop, no concert stage"
        ),
        "lyrics": """[Estrofa]
Obi-Wan desplegó un viernes, un kernel lleno de oops
panic, stack trace, dmesg en rojo, Anakin solo en el bridge
el maestro se fue a descansar, el aprendiz con el pager
la galaxia en un oops, y el ticket abierto hasta el lunes

[Estribillo]
Se pasó al lado oscuro por un deploy del viernes
un kernel lleno de errores, y Obi-Wan ya no vuelve
si cae producción, el finde te come
Anakin se quedó on-call, y nació Vader

[Estrofa]
No hay rollback, no hay parche, solo lava y logs
el Consejo no responde, Palpatine sí
root en el hypervisor, capa negra, reboot forzado
la lección del kernel: nunca dejes a tu junior solo

[Estribillo]
Se pasó al lado oscuro por un deploy del viernes
un kernel lleno de errores, y Obi-Wan ya no vuelve
si cae producción, el finde te come
Anakin se quedó on-call, y nació Vader
""",
        "scene": (
            "Videoclip landscape 16:9, cómico friki. Anakin / Darth Vader joven frente a "
            "una sala de servidores en llamas tipo Mustafar: pantallas con kernel panic, "
            "dmesg, oops. Obi-Wan Kenobi acaba de desplegar un kernel lleno de errores "
            "un viernes y se va. Anakin se queda solo de guardia. Palpatine ofrece root. "
            "Estética cine espacial + CPD. Sin raperos, sin hoodies, sin concierto."
        ),
        "master": (
            "Mustafar + CPD, 16:9: Anakin solo ante un kernel panic. "
            "Obi-Wan ya no está. Palpatine ofrece root. Ningún rapero."
        ),
    },
    {
        "slug": "vader_denied_merge",
        "style": (
            "tragicomic space opera, git tragedy, choir and distorted bass, "
            "Spanish lyrics, no rap, no trap, no pop, no concert stage"
        ),
        "lyrics": """[Estrofa]
El Consejo lee el pull request, mil comentarios, cero merge
Anakin pide write access, le niegan el rango de master
el CI está verde, la guerra hecha, el PR aprobado con nits
Mace Windu: request changes. Palpatine: te doy root

[Estribillo]
Le negaron el merge a main
y Palpatine le dio producción
sin codeowners, sin review, sin staging
así se nace al lado oscuro

[Estrofa]
Obi-Wan hace force-push, Mustafar es el repo en llamas
el historial reescrito, la rama de Anakin ya no existe
yo he sido tu hermano, yo he reescrito tu main
el Lado Oscuro es un rebase que nadie pidió

[Estribillo]
Le negaron el merge a main
y Palpatine le dio producción
sin codeowners, sin review, sin staging
así se nace al lado oscuro
""",
        "scene": (
            "Videoclip landscape 16:9, cómico friki. Anakin Skywalker ante el Consejo Jedi "
            "como si fuera un code review: hologramas de pull request, nits, request changes. "
            "Le niegan el merge a main. Palpatine le ofrece root en producción. Mustafar es "
            "un git repo en llamas tras un force-push de Obi-Wan. Sin raperos ni concierto."
        ),
        "master": (
            "Templo Jedi como sala de code review, 16:9. Anakin sin merge a main. "
            "Palpatine con root. Mustafar = repo ardiendo. Ningún rapero."
        ),
    },
    {
        "slug": "vader_works_on_my_machine",
        "style": (
            "sarcastic sitcom march, staging vs production, comic choir, "
            "Spanish lyrics, no rap, no trap, no pop, no concert stage"
        ),
        "lyrics": """[Estrofa]
En el Templo el test está verde, en Coruscant todo pasa
en Mustafar peta a la primera, Anakin no lo reproduce
los clones no clonan el bug, el heisenbug lleva capa
Obi-Wan dice: en mi máquina funciona

[Estribillo]
En mi máquina funciona
en producción, el Lado Oscuro
staging no es la galaxia
en mi máquina funciona

[Estrofa]
Palpatine sonríe: eso es un entorno distinto, joven
no hay logs, no hay core, solo arena y lava
Anakin grita al Consejo: aquí no falla
el Consejo: cierra el ticket. Works for us

[Estribillo]
En mi máquina funciona
en producción, el Lado Oscuro
staging no es la galaxia
en mi máquina funciona
""",
        "scene": (
            "Videoclip landscape 16:9, cómico friki. Anakin enseña tests verdes en el Templo "
            "(staging). En Mustafar / producción todo explota. Obi-Wan encoge los hombros: "
            "en mi máquina funciona. Clones que no reproducen el bug. Palpatine apunta a "
            "un entorno distinto. Sin raperos ni escenario de concierto."
        ),
        "master": (
            "Templo = staging verde, Mustafar = producción en llamas, 16:9. "
            "Obi-Wan: en mi máquina funciona. Ningún rapero."
        ),
    },
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


def generate_song(style: str, lyrics: str) -> tuple[str, dict, str]:
    try:
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
        return audio_path, music, "minimax"
    except Exception as exc:
        log(f"MiniMax Music unavailable ({exc})")
        log("generating local ACE-Step song")
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
        return audio_path, music, "ace_step"


def run_one(job: dict) -> None:
    slug = job["slug"]
    log(f"==== {slug} ====")
    audio_path, music, source = generate_song(job["style"], job["lyrics"])
    if not audio_path or not Path(audio_path).is_file():
        raise RuntimeError(f"Song file missing: {audio_path}")
    log(f"song source={source} file={Path(audio_path).name}")
    (ROOT / f"{slug}_song.json").write_text(
        json.dumps({"source": source, "job": music, "audio_path": audio_path}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    analysis = request_json("POST", "/api/v1/audio/analyze", {
        "audio_path": audio_path,
        "transcribe": True,
        "extract_vocals": True,
        "lyrics_hint": job["lyrics"],
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
        "production_kind": "music_video",
        "auto_mode": True,
        "scene_description": job["scene"],
        "spoken_language": "Español de España",
        "audio_path": audio_path,
        "planned_clips": clips,
        "lyrics": analysis.get("lyrics") or job["lyrics"],
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
                "contemporary streetwear"
            ),
            "direct_video_master_prompt": job["master"],
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
    (ROOT / f"{slug}_pipeline.json").write_text(
        json.dumps({
            "source": source,
            "audio_path": audio_path,
            "pipeline": pipeline,
            "clip_count": len(clips),
        }, indent=2),
        encoding="utf-8",
    )
    wait_pipeline(pipeline["pipeline_id"])
    log(f"{slug} done")


def main() -> None:
    for job in JOBS:
        run_one(job)
    log("vader IT trilogy done")


if __name__ == "__main__":
    main()
