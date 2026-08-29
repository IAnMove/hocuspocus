#!/usr/bin/env python3
"""After the live queue: more Jackson/Weta claymation scenes and two music videos."""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT.parent / "app"
OUTPUTS = APP / "outputs"
LOG = ROOT / "overnight_surprise.log"

CLAY = (
    "Stop-motion Aardman claymation, plasticine puppets with visible fingerprints, "
    "16:9, Peter Jackson / Weta cinematic light. Not live action, not CGI smooth, no rappers."
)


def detect_api() -> str:
    env = os.environ.get("MAESTRO_API")
    if env:
        return env.rstrip("/")
    for port in (42003, 42006, 42005, 42004):
        url = f"http://127.0.0.1:{port}"
        try:
            urllib.request.urlopen(url, timeout=2)
            return url
        except Exception:
            continue
    raise RuntimeError("No Maestro HTTP port found")


API = detect_api()


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


def h3_frames(seconds: float) -> int:
    requested = float(seconds) * 24.0
    aligned = 5 + max(0, math.ceil((requested - 5) / 17.0)) * 17
    return int(min(345, max(124, aligned)))


def live_jobs() -> list[dict]:
    data = request_json("GET", "/api/v1/jobs")
    jobs = data.get("jobs") if isinstance(data, dict) else data
    if not isinstance(jobs, list):
        jobs = []
    return [
        job for job in jobs
        if str(job.get("status") or "") in {
            "queued", "running", "cancelling", "waiting_resource", "created",
        }
    ]


def live_pipelines() -> list[dict]:
    try:
        data = request_json("GET", "/api/v1/director/pipelines/active")
        return data.get("pipelines") or []
    except Exception:
        return []


def wait_idle(reason: str) -> None:
    while True:
        jobs = live_jobs()
        pipes = live_pipelines()
        if not jobs and not pipes:
            log(f"idle: {reason}")
            return
        job = jobs[0] if jobs else {}
        log(
            f"waiting {reason}: jobs={len(jobs)} pipelines={len(pipes)} "
            f"{job.get('job_id') or ''} {(job.get('message') or '')[:70]}"
        )
        time.sleep(20)


def wait_job(job_id: str, timeout_s: int = 8 * 3600) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = request_json("GET", f"/api/v1/status/{job_id}")
        status = str(job.get("status") or "")
        log(f"job {job_id} {status}: {job.get('message') or ''}")
        if status in {"completed", "failed", "cancelled", "crashed"}:
            if status != "completed":
                raise RuntimeError(f"job {job_id} {status}: {job.get('error')}")
            return job
        time.sleep(20)
    raise TimeoutError(f"job {job_id} timed out")


def queue_clip(
    *,
    prompt: str,
    frames: int,
    label: str,
    resolution: str = "960x544",
    negative: str = "live action, photoreal humans, modern rappers, concert stage, CGI smooth",
) -> dict:
    seconds = round(frames / 24.0, 3)
    body = {
        "prompt": prompt,
        "model_type": "minimax_h3_legacy",
        "resolution": resolution,
        "video_length": frames,
        "num_inference_steps": 20,
        "guidance_scale": 1.0,
        "seed": -1,
        "image_mode": 0,
        "negative_prompt": negative,
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
        "spoken_language": "Español de España",
        "duration_seconds": seconds,
        "_duration_seconds": seconds,
        "_batch_label": label,
    }
    return request_json("POST", "/api/v1/generate", body)


def visual_prompt(style: str, visual: str, spoken: str = "") -> str:
    spoken = f" {spoken}" if spoken else ""
    return (
        f"integrated_multimodal_description: [Shot 1] {style} {visual}{spoken}\n\n"
        "overall_soundscape: N/A\n\n"
        "non_diegetic_music: N/A"
    )


def dialogue(line: str) -> str:
    return f"<d>[Spanish] {line}</d>"


def concat_clips(filenames: list[str], destination: Path, list_name: str) -> None:
    list_file = ROOT / list_name
    lines = []
    for name in filenames:
        path = OUTPUTS / name if not str(name).startswith("/") else Path(name)
        if not path.is_file():
            raise RuntimeError(f"clip missing: {path}")
        lines.append(f"file '{path}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-movflags", "+faststart", str(destination),
    ]
    log("concat " + destination.name)
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    try:
        from services.mix_concat import concat_with_tail_hold_and_crossfade
        paths = [
            (OUTPUTS / name if not str(name).startswith("/") else Path(name))
            for name in filenames
        ]
        if concat_with_tail_hold_and_crossfade(
            [str(path) for path in paths],
            str(destination),
        ):
            return
        log("soft concat failed; hard cut fallback")
    except Exception as exc:
        log(f"soft concat unavailable ({exc}); hard cut fallback")
    subprocess.run(cmd, check=True)


def write_mix_sidecar(
    destination: Path,
    clips: list[str],
    *,
    result_kind: str,
    extra: dict | None = None,
) -> None:
    extra = extra or {}
    payload = {
        "result_kind": result_kind,
        "generation_mode": "video",
        "created_at": time.time(),
        "params": {
            "result_kind": result_kind,
            "production_kind": result_kind,
            "pipeline_type": "music_video" if result_kind == "music_video" else "short_film_story",
            "source_clips": clips,
            **extra,
        },
    }
    destination.with_suffix(".meta.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def mux_song(video: Path, audio: Path, destination: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", str(video), "-i", str(audio),
        "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0",
        "-shortest", "-movflags", "+faststart", str(destination),
    ]
    log("mux " + destination.name)
    subprocess.run(cmd, check=True)
    write_mix_sidecar(
        destination,
        [video.name],
        result_kind="music_video",
        extra={"audio_path": str(audio), "pipeline_type": "music_video"},
    )


def job_mp4(job: dict) -> str:
    files = [name for name in (job.get("output_files") or []) if str(name).endswith(".mp4")]
    if not files:
        raise RuntimeError(f"no mp4: {job.get('job_id')} {job}")
    return files[0]


def generate_sequence(name: str, style: str, shots: list[dict], resolution: str = "960x544") -> Path:
    log(f"sequence {name} {len(shots)} shots")
    queued = []
    for index, shot in enumerate(shots, start=1):
        line = shot.get("line") or ""
        spoken = dialogue(line) if line else ""
        prompt = visual_prompt(style, shot["visual"], spoken)
        frames = int(shot.get("frames") or h3_frames(shot.get("seconds") or 8))
        submitted = queue_clip(
            prompt=prompt,
            frames=frames,
            label=f"overnight-{name}-{index:02d}-{shot['label']}",
            resolution=resolution,
            negative=shot.get("negative") or (
                "live action, photoreal humans, modern rappers, concert stage, CGI smooth"
            ),
        )
        log(f"queued {name}/{shot['label']}: {submitted.get('job_id')}")
        queued.append(submitted)
        time.sleep(0.25)
    filenames = []
    for item in queued:
        job = wait_job(item["job_id"])
        filename = job_mp4(job)
        filenames.append(filename)
        log(f"done {item['job_id']} {filename}")
    destination = OUTPUTS / f"overnight_{name}_multiclip.mp4"
    concat_clips(filenames, destination, f"overnight_{name}_concat.txt")
    write_mix_sidecar(
        destination,
        filenames,
        result_kind="series_episode",
        extra={
            "name": name,
            "api": API,
            "jobs": [item.get("job_id") for item in queued],
            "pipeline_type": "short_film_story",
        },
    )
    log(f"sequence done {destination.name}")
    return destination


def finish_bagend() -> None:
    files = [
        "minimax_h3_813f5ea0.mp4",
        "minimax_h3_25713ef7.mp4",
        "minimax_h3_530b3815.mp4",
        "minimax_h3_ae1773f5.mp4",
        "minimax_h3_6dc08a2b.mp4",
        "minimax_h3_964ccfb5.mp4",
        "minimax_h3_3181dd43.mp4",
        "minimax_h3_e9fdc118.mp4",
    ]
    missing = [name for name in files if not (OUTPUTS / name).is_file()]
    if missing:
        log("bagend missing " + ", ".join(missing) + "; skip concat")
        return
    destination = OUTPUTS / "claymation_bagend_multiclip.mp4"
    concat_clips(files, destination, "claymation_bagend_concat.txt")
    write_mix_sidecar(
        destination,
        files,
        result_kind="series_episode",
        extra={"source": "claymation_bagend", "pipeline_type": "short_film_story"},
    )
    log("bagend concat ready " + destination.name)


def queue_jokes() -> None:
    env = os.environ.copy()
    env["MAESTRO_API"] = API
    log("queueing joke round")
    result = subprocess.run(
        [sys.executable, str(ROOT / "queue_joke_round.py")],
        env=env,
        check=False,
    )
    if result.returncode != 0:
        log(f"joke round failed exit={result.returncode}")
        return
    log("joke round queued")
    wait_idle("jokes")


MORIA = [
    {
        "label": "columnas",
        "seconds": 10,
        "visual": (
            "Vast claymation Moria hall: endless dwarven pillars of plasticine stone, "
            "Fellowship of tiny puppets walking a narrow causeway, torch glow, "
            "Peter Jackson / Weta scale, dust motes in a high shaft of light."
        ),
    },
    {
        "label": "tambores",
        "seconds": 8,
        "visual": (
            "Close on clay goblin drums in shadow. Plasticine hands strike hides. "
            "The Fellowship freeze on the causeway, looking up into the dark."
        ),
    },
    {
        "label": "puente",
        "seconds": 10,
        "visual": (
            "Narrow Bridge of Khazad-dûm. Claymation Gandalf, pointed hat and long beard, "
            "stands in the middle with staff planted. Behind him the Fellowship huddles. "
            "Ahead, a glow of fire grows."
        ),
    },
    {
        "label": "balrog",
        "seconds": 12,
        "visual": (
            "The Balrog of Morgoth as a huge claymation fire-shadow with a whip of flame, "
            "horns and mane of smoke, filling the gulf. Weta creature design in plasticine. "
            "Gandalf is tiny on the bridge."
        ),
    },
    {
        "label": "no-puedes-pasar",
        "seconds": 12,
        "visual": (
            "Medium on claymation Gandalf on the bridge, staff raised toward the Balrog. "
            "The Fellowship watches from the far ledge."
        ),
        "line": "No puedes pasar.",
    },
    {
        "label": "azote",
        "seconds": 10,
        "visual": (
            "The fiery whip lashes the bridge. Gandalf's staff meets it. Sparks of clay fire. "
            "The stone cracks under their feet."
        ),
    },
    {
        "label": "caida",
        "seconds": 10,
        "visual": (
            "The bridge breaks. Claymation Gandalf falls into the abyss, looking up, "
            "cloak and beard streaming. Frodo reaches from the ledge."
        ),
        "line": "¡Gandalf!",
    },
    {
        "label": "huida",
        "seconds": 10,
        "visual": (
            "The Fellowship flees up the stairs of Moria, tiny plasticine figures, "
            "empty broken bridge behind them, last embers of the Balrog in the gulf."
        ),
    },
]

WEATHERTOP = [
    {
        "label": "ruinas",
        "seconds": 10,
        "visual": (
            "Weathertop at dusk: broken ring of clay stones on a windy hill. "
            "Four hobbit puppets camp with a small fire. Aragorn in a dark cloak watches the horizon."
        ),
    },
    {
        "label": "nazgul",
        "seconds": 10,
        "visual": (
            "Five Ringwraiths as tall black claymation figures with hoods, no faces, "
            "climbing the hill. The fire is small. The hobbits huddle."
        ),
    },
    {
        "label": "anillo",
        "seconds": 8,
        "visual": (
            "Close on claymation Frodo. He puts the One Ring on his finger. "
            "The world goes pale and the Nazgûl become clear crowned shadows."
        ),
    },
    {
        "label": "herida",
        "seconds": 8,
        "visual": (
            "The Witch-king stabs toward Frodo with a Morgul blade. "
            "Frodo falls back among the stones. Sam reaches for him."
        ),
    },
    {
        "label": "antorcha",
        "seconds": 10,
        "visual": (
            "Aragorn charges with a flaming torch, driving the Nazgûl back from the hobbits. "
            "Plasticine fire, swirling cloaks, Weta ranger."
        ),
        "line": "¡Atrás!",
    },
    {
        "label": "alba",
        "seconds": 10,
        "visual": (
            "Dawn on Weathertop. The Nazgûl are gone. Aragorn kneels and holds wounded Frodo. "
            "Sam, Merry and Pippin watch, terrified and loyal."
        ),
        "line": "Hay que llevarlo a Rivendel.",
    },
]

KONG = [
    {
        "label": "altar",
        "seconds": 10,
        "visual": (
            "Skull Island night, 1933 Jackson / Weta jungle. Claymation Ann Darrow in a gold "
            "dress tied to a tribal altar of logs and flowers. Torches, steam, giant leaves."
        ),
    },
    {
        "label": "arboles",
        "seconds": 10,
        "visual": (
            "The jungle parts. A gigantic claymation gorilla face fills the frame: "
            "King Kong 2005, scarred, wet fur in plasticine, amber eyes."
        ),
    },
    {
        "label": "mira",
        "seconds": 10,
        "visual": (
            "Kong looks at Ann. She looks back, tiny, shaking, then still. "
            "No crew, no cameras, just the two of them and the jungle."
        ),
        "line": "No me hagas daño.",
    },
    {
        "label": "mano",
        "seconds": 10,
        "visual": (
            "Kong's huge clay hand unties Ann and lifts her gently. "
            "She holds the thumb. Firelight on gold dress and dark fur."
        ),
    },
    {
        "label": "cumbre",
        "seconds": 12,
        "visual": (
            "Kong climbs a cliff with Ann in his fist. Skull Island sunrise over a sea of mist "
            "and stone heads. Wide Weta landscape in stop-motion."
        ),
    },
    {
        "label": "amanecer",
        "seconds": 10,
        "visual": (
            "On the peak, Kong sits. Ann stands on his palm and looks at the sunrise with him. "
            "Two silhouettes, one tiny, one enormous."
        ),
        "line": "Eres hermoso.",
    },
]

FANGORN_STYLE = (
    "warm ancient-forest folk hymn, low male choir, wooden percussion, bassoon, "
    "slow processional of trees, Spanish lyrics, no rap, no pop, no trap, no modern concert"
)
FANGORN_LYRICS = """[Estrofa]
Las raíces recuerdan el hacha
la corteza guarda el invierno
si el orco pisa el musgo
el bosque abre los ojos

[Estribillo]
Nos levantamos, nos levantamos
Treebeard lleva el paso
la tierra camina
y el hacha se queda atrás

[Estrofa]
Hojas como banderas viejas
barba de liquen, voz de pozo
Isengard humea lejos
nosotros no tenemos prisa

[Estribillo]
Nos levantamos, nos levantamos
Treebeard lleva el paso
la tierra camina
y el hacha se queda atrás
"""
FANGORN_SHOTS = [
    {
        "label": "duerme",
        "seconds": 10,
        "visual": (
            "Fangorn Forest at dawn, claymation: enormous Ent faces half-asleep in the trees, "
            "moss beards, Peter Jackson / Weta. A hobbit-sized Merry and Pippin sleep in roots."
        ),
    },
    {
        "label": "treebeard",
        "seconds": 10,
        "visual": (
            "Treebeard the Ent as a walking claymation tree-giant, slow, kind, terrible. "
            "Merry and Pippin ride in his branches."
        ),
    },
    {
        "label": "marcha",
        "seconds": 12,
        "visual": (
            "Last March of the Ents: dozens of tree-giants stride through mist, "
            "roots tearing soil, hills moving, Jackson epic landscape in stop-motion."
        ),
    },
    {
        "label": "isengard",
        "seconds": 10,
        "visual": (
            "Isengard from the Ent perspective: Orthanc black spike, pits, wheels, fire. "
            "The forest arrives at the rim like a wave of timber."
        ),
    },
    {
        "label": "inunda",
        "seconds": 10,
        "visual": (
            "Ents breach a dam. Water floods the industrial pits of Isengard. "
            "Orcs flee as tiny plasticine figures. Orthanc stands in a new lake."
        ),
    },
    {
        "label": "orillas",
        "seconds": 10,
        "visual": (
            "Treebeard stands in the water around Orthanc, satisfied, slow. "
            "Merry and Pippin on his shoulders watch the steam rise."
        ),
    },
]

KONG_MV_STYLE = (
    "1930s Hollywood adventure orchestra, jungle drums, muted trumpets, "
    "Max Steiner / Kong 2005 homage, lush strings, Spanish lyrics, "
    "no rap, no pop, no trap, no modern concert"
)
KONG_MV_LYRICS = """[Estrofa]
La isla tiene dientes de piedra
el vapor sube de la selva
una mujer de vestido de oro
espera donde acaba el mapa

[Estribillo]
Kong, Kong, rey de la cumbre
la ciudad no cabe en tu mano
si el mundo quiere un espectáculo
tú solo quieres el amanecer

[Estrofa]
Ann no grita, Ann mira
el pulgar es un balcón
Nueva York es un juguete lejos
aquí el cielo es de verdad

[Estribillo]
Kong, Kong, rey de la cumbre
la ciudad no cabe en tu mano
si el mundo quiere un espectáculo
tú solo quieres el amanecer
"""
KONG_MV_SHOTS = [
    {
        "label": "vapor",
        "seconds": 10,
        "visual": (
            "Skull Island from the sea, 1933 steamer, claymation, Jackson fog and stone heads. "
            "No modern ships."
        ),
    },
    {
        "label": "danza",
        "seconds": 10,
        "visual": (
            "Village night, torches, dancers, Ann in gold on the altar, "
            "Weta tribal design in plasticine."
        ),
    },
    {
        "label": "aparece",
        "seconds": 12,
        "visual": (
            "Kong breaks the trees, huge claymation gorilla, 2005 design, "
            "Ann tiny against his chest."
        ),
    },
    {
        "label": "liana",
        "seconds": 10,
        "visual": (
            "Kong and a Vastatosaurus rex fight on a cliff while Ann clings to vines. "
            "Stop-motion monster movie, Jackson camera."
        ),
    },
    {
        "label": "cumbre",
        "seconds": 10,
        "visual": (
            "Sunrise on the peak. Kong and Ann share the view. "
            "Gold dress, wet fur, mist ocean."
        ),
    },
    {
        "label": "ciudad",
        "seconds": 12,
        "visual": (
            "Brief New York 1933 claymation: Kong on a frozen pond stage, then the Empire State, "
            "biplanes, Ann below. Tragic and huge, not a concert, no rappers."
        ),
    },
]


def ace_step_song(style: str, lyrics: str, duration: int = 72) -> Path:
    log("ACE-Step song")
    music = request_json("POST", "/api/v1/director/generate-music", {
        "style": style,
        "lyrics": lyrics,
        "instrumental": False,
        "duration_seconds": duration,
        "model_type": "ace_step_v1_5_xl_sft_lm_4b",
        "seed": -1,
    }, timeout=1800)
    audio_path = str(music.get("audio_path") or "")
    filename = str(music.get("filename") or "")
    path = Path(audio_path) if audio_path else OUTPUTS / filename
    if not path.is_file() and filename:
        path = OUTPUTS / filename
    if not path.is_file():
        raise RuntimeError(f"ACE-Step produced no file: {music}")
    log(f"song {path}")
    return path


CARTOON = (
    "2D cartoon rubber-hose, thick ink outlines, saturated paint, Saturday-morning look, "
    "16:9, not live action, no rappers."
)
CLAY_CUTE = (
    "Stop-motion plasticine cartoon, round Aardman faces, candy colours, fingerprints, "
    "16:9, not live action, no rappers."
)
CLAY_NOIR = (
    "Stop-motion claymation film-noir, high contrast practical light, plasticine suits, "
    "16:9, not live action, no rappers."
)
CLAY_POP = (
    "Claymation pop-cartoon, oversized heads, bright plasticine, fingerprints, "
    "16:9, not live action, no rappers."
)

TITANIC_DOOR = [
    {
        "label": "naufragio",
        "seconds": 10,
        "visual": (
            "Cartoon Titanic at night, freezing Atlantic, stars. A wooden door floats. "
            "Clay-painted Rose in a wet evening dress holds the board. Jack treads water."
        ),
    },
    {
        "label": "sube",
        "seconds": 10,
        "visual": (
            "Changed ending: Jack climbs onto the door beside Rose. Both fit. "
            "They huddle, laughing, breath in the cold cartoon air."
        ),
        "line": "Mira, cabemos los dos.",
    },
    {
        "label": "rescate",
        "seconds": 10,
        "visual": (
            "A cartoon lifeboat finds them both awake. Crew pulls Jack and Rose aboard. "
            "The wreck is a silhouette behind them."
        ),
        "line": "¡Estamos vivos!",
    },
    {
        "label": "ny",
        "seconds": 10,
        "visual": (
            "New York harbour, 1912 cartoon. Jack and Rose stand at the rail of a rescue ship, "
            "Statue of Liberty ahead. They hold hands. Both lived."
        ),
        "line": "Nunca la sueltes.",
    },
]

TITANIC_PROA = [
    {
        "label": "proa",
        "seconds": 12,
        "visual": (
            "Titanic bow at golden hour, plasticine cartoon. Jack holds Rose at the rail, "
            "arms open, spray and sunset. No live action."
        ),
        "line": "Vuela conmigo.",
    },
    {
        "label": "vuela",
        "seconds": 10,
        "visual": (
            "Rose leans into the wind, arms wide, Jack behind her. Cartoon clouds, "
            "the ship cutting the Atlantic. They smile like a poster."
        ),
        "line": "Soy la reina del mundo.",
    },
    {
        "label": "beso",
        "seconds": 8,
        "visual": (
            "Close two-shot, clay fingerprints on cheeks, they kiss at the prow. "
            "The sun is huge and orange behind the funnels."
        ),
    },
    {
        "label": "camarote",
        "seconds": 8,
        "visual": (
            "Changed beat: they sneak back to steerage, dancing among cartoon immigrants, "
            "still in the bow pose as a joke, laughing."
        ),
        "line": "Otra vez, más despacio.",
    },
]

TERMINATOR_HASTA = [
    {
        "label": "acero",
        "seconds": 10,
        "visual": (
            "Cyberdyne steel mill, claymation T-800 (Arnold 1991) in a leather jacket, "
            "T-1000 frozen in a splash of liquid nitrogen as chrome ice. Sparks, orange slag."
        ),
    },
    {
        "label": "pistola",
        "seconds": 8,
        "visual": (
            "T-800 raises a clay shotgun toward the frozen T-1000. Sarah and John Connor watch."
        ),
        "line": "Hasta la vista, baby.",
    },
    {
        "label": "hielo",
        "seconds": 8,
        "visual": (
            "The frozen T-1000 shatters into chrome shards. Then the shards melt into a puddle "
            "and reform into a small harmless chrome puppy, changed ending."
        ),
    },
    {
        "label": "helado",
        "seconds": 10,
        "visual": (
            "Changed ending: T-800, Sarah and John sit at a 90s diner. The chrome puppy eats "
            "ice cream from a cup. T-800 gives a thumbs-up. No lava, no sacrifice."
        ),
        "line": "Misión cumplida. Pedimos tres copas.",
    },
]

CASABLANCA_AVION = [
    {
        "label": "pista",
        "seconds": 10,
        "visual": (
            "Casablanca airfield fog, claymation noir. Rick in a trench coat, Ilsa in a pale suit, "
            "Renault nearby. A small plane waits with prop turning."
        ),
    },
    {
        "label": "mirada",
        "seconds": 8,
        "visual": (
            "Rick looks at Ilsa. The usual goodbye staging. Then he shakes his head and takes her hand."
        ),
        "line": "Siempre nos quedará París. Y el asiento de ventanilla.",
    },
    {
        "label": "suben",
        "seconds": 10,
        "visual": (
            "Changed ending: Rick AND Ilsa climb into the plane together. Laszlo salutes from the fog, "
            "smiling. Renault lights a cigarette and shrugs."
        ),
        "line": "Redondea a dos, Louie.",
    },
    {
        "label": "despegue",
        "seconds": 10,
        "visual": (
            "The plane lifts through cartoon fog. Rick and Ilsa at the tiny window. "
            "The airport shrinks. They do not stay on the tarmac."
        ),
    },
]

JURASSIC_PICNIC = [
    {
        "label": "lluvia",
        "seconds": 10,
        "visual": (
            "Jurassic Park Ford Explorer in a downpour, claymation. A huge T-rex head fills the windshield. "
            "Two children freeze in the back seat. Spielberg night, plasticine rain."
        ),
    },
    {
        "label": "rugido",
        "seconds": 8,
        "visual": (
            "The T-rex leans down, water dripping from clay teeth. Then it sniffs a sandwich "
            "the boy holds up. Curiosity, not a hunt."
        ),
        "line": "¿Quieres la mitad?",
    },
    {
        "label": "paseo",
        "seconds": 10,
        "visual": (
            "Changed ending: the T-rex walks beside the jeep like a wet dog. Kids on the hood. "
            "Lex and Tim laugh. The lawyer is stuck in a toilet hut, unharmed, waving."
        ),
    },
    {
        "label": "picnic",
        "seconds": 10,
        "visual": (
            "Dawn picnic on the grass: T-rex lying down, kids feeding it crackers, "
            "Grant and Sattler watching in disbelief. A park that actually works."
        ),
        "line": "Bienvenida a Jurassic Park.",
    },
]

ET_CACAO = [
    {
        "label": "luna",
        "seconds": 10,
        "visual": (
            "ET and Elliott on a BMX crossing the full moon, cute claymation silhouette, "
            "Spielberg poster pose, fingerprints on the tires."
        ),
        "line": "ET, teléfono, casa.",
    },
    {
        "label": "nave",
        "seconds": 8,
        "visual": (
            "The spaceship opens in the forest clearing. ET looks at Elliott. "
            "Then ET closes the ramp with a finger and shakes his head."
        ),
        "line": "Casa es aquí.",
    },
    {
        "label": "cocina",
        "seconds": 10,
        "visual": (
            "Changed ending: suburban kitchen, ET in a bathrobe on a chair, cocoa mug in both hands. "
            "Elliott's family around the table. Gertie puts a flowerpot hat on ET."
        ),
    },
    {
        "label": "sofa",
        "seconds": 8,
        "visual": (
            "Living room night. ET and Elliott share a blanket and a cartoon movie on a CRT. "
            "The spaceship is a night-light on the shelf. He stayed."
        ),
        "line": "Amigos para siempre.",
    },
]

INCEPTION_PEONZA = [
    {
        "label": "orilla",
        "seconds": 10,
        "visual": (
            "Inception beach, claymation Cobb in a wet suit, children turning. "
            "A spinning top on the wooden table in the next room, still going."
        ),
    },
    {
        "label": "casa",
        "seconds": 8,
        "visual": (
            "Cobb walks into the house, ignores the top, hugs the kids. "
            "Mal is not there. The rooms are ordinary and sunlit."
        ),
        "line": "Ya he vuelto.",
    },
    {
        "label": "cae",
        "seconds": 8,
        "visual": (
            "Changed ending: close on the top. It wobbles and falls, clay fingerprint on the wood. "
            "It is real. The children laugh in the garden."
        ),
    },
    {
        "label": "jardin",
        "seconds": 10,
        "visual": (
            "Cobb plays football with the kids. No totems, no cities folding. "
            "A suburban Saturday. He does not look back at the table."
        ),
    },
]

INDIANA_ROCA = [
    {
        "label": "templo",
        "seconds": 10,
        "visual": (
            "Raiders cartoon serial: Indiana Jones in a dusty temple, gold idol on a pedestal, "
            "rubber-hose 2D, torches, vines."
        ),
    },
    {
        "label": "cambia",
        "seconds": 8,
        "visual": (
            "Indy swaps a bag of sand for the idol. The pedestal sinks. "
            "The huge round boulder wakes in the tunnel."
        ),
        "line": "Esto no iba a pasar.",
    },
    {
        "label": "corre",
        "seconds": 10,
        "visual": (
            "Indy sprints toward camera, boulder filling the corridor, cartoon speed lines. "
            "Satipo is already outside, not dead, holding the whip."
        ),
    },
    {
        "label": "salida",
        "seconds": 8,
        "visual": (
            "Changed ending: the boulder rolls into a museum gift-shop display. "
            "Indy dusts his hat. A clerk stamps a postcard. Adventure over, everyone fine."
        ),
        "line": "Sello de salida, por favor.",
    },
]

MATRIX_FIDEOS = [
    {
        "label": "lobby",
        "seconds": 10,
        "visual": (
            "The Matrix lobby, claymation: Neo in a long coat, Trinity beside him, "
            "green-tint marble, agents in sunglasses at the metal detector."
        ),
    },
    {
        "label": "balas",
        "seconds": 10,
        "visual": (
            "Neo leans back in cartoon bullet-time, coat like a flag. "
            "Then he straightens, bored, and the bullets hang as harmless clay dots."
        ),
        "line": "Ya no hace falta.",
    },
    {
        "label": "gafas",
        "seconds": 8,
        "visual": (
            "Changed ending: Neo takes an agent's glasses off gently. The agent sits down. "
            "Trinity holsters nothing because there is nothing to fire."
        ),
    },
    {
        "label": "fideos",
        "seconds": 10,
        "visual": (
            "Neon noodle bar, rain on the window. Neo, Trinity and a retired Agent Smith "
            "share a bowl. Peaceful Chinatown claymation. No machines in the sky."
        ),
        "line": "El sabor es real.",
    },
]

BLADE_AMANECER = [
    {
        "label": "azotea",
        "seconds": 10,
        "visual": (
            "Blade Runner 2049-meets-1982 rooftop rain, claymation Roy Batty, white hair, "
            "naked torso, Deckard hanging from a ledge. Neo-noir plasticine."
        ),
    },
    {
        "label": "salva",
        "seconds": 8,
        "visual": (
            "Roy pulls Deckard up instead of letting him fall. They sit in the rain. "
            "A dove is a clay bird in Roy's hand."
        ),
        "line": "Yo he visto cosas que no creeríais.",
    },
    {
        "label": "paloma",
        "seconds": 8,
        "visual": (
            "Changed ending: Roy does not die. He opens his hand and the dove flies. "
            "He smiles, still alive, rain on his face."
        ),
        "line": "Todavía no es momento.",
    },
    {
        "label": "tejado",
        "seconds": 10,
        "visual": (
            "Dawn over a clay Los Angeles. Roy and Deckard drink from paper cups on the roof. "
            "The dove sits on the rail. Both stay."
        ),
    },
]


RYAN = [
    {
        "label": "lanchas",
        "seconds": 10,
        "visual": (
            "Saving Private Ryan, claymation Omaha Beach dawn. Higgins boats packed with "
            "plasticine US soldiers, grey Channel, sky of lead. Spielberg 1998, fingerprints on helmets."
        ),
    },
    {
        "label": "rampa",
        "seconds": 10,
        "visual": (
            "The ramp drops. Captain Miller in a wet uniform steps into surf and Czech hedgehogs. "
            "Stop-motion chaos, no live action, no rappers."
        ),
        "line": "¡Fuera! ¡A la playa!",
    },
    {
        "label": "playa",
        "seconds": 12,
        "visual": (
            "Wide Omaha: clay soldiers behind hedgehogs, smoke, a cliff of bunkers. "
            "Miller waves the squad forward through wet sand."
        ),
    },
    {
        "label": "ryan",
        "seconds": 10,
        "visual": (
            "A Norman field after the beach. Young Private Ryan with a pack, among paratroopers. "
            "Miller's squad has found him."
        ),
        "line": "¿Yo? ¿Por qué yo?",
    },
    {
        "label": "ganatelo",
        "seconds": 10,
        "visual": (
            "Miller wounded by a bridge, looking at Ryan. The squad is around them. "
            "Clay close-up, rain starting."
        ),
        "line": "Gánatelo.",
    },
    {
        "label": "tumba",
        "seconds": 10,
        "visual": (
            "Normandy cemetery, old Ryan at a white cross, family behind him. "
            "He stands straight, clay tears, American flag bokeh. Same plasticine world."
        ),
        "line": "Dime que he sido un hombre bueno.",
    },
]

ENEMY_MINE = [
    {
        "label": "combate",
        "seconds": 10,
        "visual": (
            "Enemy Mine, 1985: two tiny clay fighters over a red-yellow planet, Davidge's Earth ship "
            "and a Drac saucer, space dogfight, Wolfgang Petersen, not CGI smooth."
        ),
    },
    {
        "label": "choque",
        "seconds": 10,
        "visual": (
            "Both craft crash on Fyrine IV: volcanic rock, steam vents, two wrecks far apart. "
            "Stop-motion alien desert."
        ),
    },
    {
        "label": "cara",
        "seconds": 10,
        "visual": (
            "Human Davidge in a torn flightsuit faces Jeriba the Drac, reptilian clay face, "
            "both armed with wreckage, circling in a canyon."
        ),
        "line": "¿Tú también has bajado?",
    },
    {
        "label": "cueva",
        "seconds": 10,
        "visual": (
            "A cave shelter. Davidge and Jeriba share food. Jeriba teaches him Drac with hand signs "
            "and a clay book. Enemies becoming partners."
        ),
        "line": "No somos tan distintos.",
    },
    {
        "label": "zammis",
        "seconds": 10,
        "visual": (
            "Jeriba gives birth to Zammis, a small Drac infant of plasticine. Davidge helps, stunned, "
            "then holds the child."
        ),
        "line": "Lo voy a cuidar.",
    },
    {
        "label": "cielo",
        "seconds": 10,
        "visual": (
            "Years later: Davidge, bearded clay, walks Zammis under Fyrine's two suns. "
            "The wrecks are gardens. They look up at a rescue ship and do not hide."
        ),
        "line": "Esta es nuestra casa.",
    },
]


def run_war_and_alien_scenes() -> None:
    log("ryan and enemy mine start")
    films = (
        ("ryan_omaha", CLAY + " Saving Private Ryan, Omaha to the grave.", RYAN),
        ("enemy_mine", CLAY + " Enemy Mine, Davidge and Jeriba on Fyrine IV.", ENEMY_MINE),
    )
    for name, style, shots in films:
        try:
            generate_sequence(name, style, shots)
        except Exception as exc:
            log(f"film {name} failed: {exc}")
    log("ryan and enemy mine done")


def run_iconic_scenes() -> None:
    """Mythic movie beats in clay/cartoon, several with kinder endings."""
    log("iconic movie scenes start")
    films = (
        ("titanic_puerta", CARTOON + " Titanic, Jack and Rose, both live.", TITANIC_DOOR),
        ("titanic_proa", CLAY_CUTE + " Titanic bow, I'm flying.", TITANIC_PROA),
        ("terminator_hasta", CLAY_POP + " T2 steel mill, Hasta la vista, diner ending.", TERMINATOR_HASTA),
        ("casablanca_avion", CLAY_NOIR + " Casablanca, both board the plane.", CASABLANCA_AVION),
        ("jurassic_picnic", CLAY_CUTE + " Jurassic Park rain, T-rex picnic.", JURASSIC_PICNIC),
        ("et_cacao", CLAY_CUTE + " ET moon, then he stays for cocoa.", ET_CACAO),
        ("inception_peonza", CLAY_NOIR + " Inception, the top falls, he is home.", INCEPTION_PEONZA),
        ("indiana_roca", CARTOON + " Raiders boulder, gift-shop ending.", INDIANA_ROCA),
        ("matrix_fideos", CLAY_POP + " Matrix lobby, then noodles in peace.", MATRIX_FIDEOS),
        ("bladerunner_amanecer", CLAY_NOIR + " Blade Runner rain, Roy lives.", BLADE_AMANECER),
    )
    for name, style, shots in films:
        try:
            generate_sequence(name, style, shots)
        except Exception as exc:
            log(f"iconic {name} failed: {exc}")
    log("iconic movie scenes done")


def music_video(name: str, style: str, lyrics: str, shots: list[dict], visual_style: str) -> Path:
    song = ace_step_song(style, lyrics)
    video = generate_sequence(name, visual_style, shots)
    destination = OUTPUTS / f"overnight_{name}_mv.mp4"
    mux_song(video, song, destination)
    log(f"music video {destination.name}")
    return destination


def main() -> None:
    log(f"overnight start api={API}")
    wait_idle("user-queue")
    try:
        finish_bagend()
    except Exception as exc:
        log(f"bagend concat skipped: {exc}")
    try:
        queue_jokes()
    except Exception as exc:
        log(f"jokes skipped: {exc}")

    films = (
        ("moria", CLAY + " Dark Moria, dwarven halls, fire gulf.", MORIA),
        ("weathertop", CLAY + " Weathertop dusk, Nazgûl, ranger.", WEATHERTOP),
        ("kong_ann", CLAY + " King Kong 2005, Skull Island, Ann Darrow.", KONG),
    )
    for name, style, shots in films:
        try:
            generate_sequence(name, style, shots)
        except Exception as exc:
            log(f"film {name} failed: {exc}")

    videos = (
        (
            "fangorn",
            FANGORN_STYLE,
            FANGORN_LYRICS,
            FANGORN_SHOTS,
            CLAY + " Fangorn Ents, Treebeard, Last March, Isengard flood.",
        ),
        (
            "skull_island",
            KONG_MV_STYLE,
            KONG_MV_LYRICS,
            KONG_MV_SHOTS,
            CLAY + " King Kong 2005 music video, Skull Island and 1933 New York.",
        ),
    )
    for name, style, lyrics, shots, visual in videos:
        try:
            music_video(name, style, lyrics, shots, visual)
        except Exception as exc:
            log(f"mv {name} failed: {exc}")
    try:
        run_iconic_scenes()
    except Exception as exc:
        log(f"iconic scenes failed: {exc}")
    log("overnight surprise finished")


if __name__ == "__main__":
    main()
