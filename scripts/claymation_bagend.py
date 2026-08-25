#!/usr/bin/env python3
"""After the Vader IT trilogy: 1–2 min claymation Bag End (Gandalf knocks, talks to Frodo)."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("MAESTRO_API", "http://127.0.0.1:42005")
ROOT = Path(__file__).resolve().parent
APP = ROOT.parent / "app"
OUTPUTS = APP / "outputs"
LOG = ROOT / "claymation_bagend.log"
VADER_SCRIPT = "vader_it_trilogy.py"

STYLE = (
    "Stop-motion Aardman claymation, plasticine puppets with visible fingerprints, "
    "16:9, Shire sunset light, Bag End round green door. Not live action, not CGI smooth, no rappers."
)

SUBJECTS = [
    {"character_id": "gandalf", "speaker_name": "Gandalf"},
    {"character_id": "frodo", "speaker_name": "Frodo"},
]

SHOTS = [
    {
        "label": "estableciendo",
        "frames": 294,
        "visual": (
            "Wide hillside of Hobbiton. Bag End's round green door in a grassy hill. "
            "A tall grey claymation wizard walks the path toward the door."
        ),
        "speaker": None,
        "line": "",
    },
    {
        "label": "llamada",
        "frames": 243,
        "visual": (
            "Close on the round green door. Claymation Gandalf, pointed hat and long plasticine beard, "
            "knocks three times with his staff. The door stays closed until the last knock."
        ),
        "speaker": None,
        "line": "",
    },
    {
        "label": "llegas-tarde",
        "frames": 243,
        "visual": (
            "The round door opens. Claymation Frodo, curly plasticine hair and waistcoat, looks up at Gandalf."
        ),
        "speaker": "frodo",
        "line": "Llegas tarde.",
    },
    {
        "label": "un-mago-nunca",
        "frames": 311,
        "visual": (
            "Medium two-shot on the threshold. Claymation Gandalf leans on his staff, calm half-smile. "
            "Frodo listens."
        ),
        "speaker": "gandalf",
        "line": "Un mago nunca llega tarde, Frodo Bolsón. Ni pronto. Llega exactamente cuando se propone.",
    },
    {
        "label": "entra",
        "frames": 243,
        "visual": (
            "Frodo steps aside and gestures into the warm round hallway of Bag End."
        ),
        "speaker": "frodo",
        "line": "Entra, te estábamos esperando.",
    },
    {
        "label": "el-te",
        "frames": 260,
        "visual": (
            "Inside Bag End: round rooms, wooden beams, hearth glow. Claymation Gandalf ducks under the lintel."
        ),
        "speaker": "gandalf",
        "line": "¿Y el té? Una taza no le viene mal a un mago viajado.",
    },
    {
        "label": "hogar",
        "frames": 277,
        "visual": (
            "Gandalf and Frodo sit by the fire. A clay teapot, two cups, pipe smoke. "
            "They smile."
        ),
        "speaker": None,
        "line": "",
    },
    {
        "label": "humo",
        "frames": 277,
        "visual": (
            "Close on claymation Gandalf blowing a slow smoke ring toward the round window. "
            "Frodo watches, content."
        ),
        "speaker": None,
        "line": "",
    },
]


def log(message: str) -> None:
    line = time.strftime("%H:%M:%S") + " " + message
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def h3_seconds(frames: int) -> float:
    return round(frames / 24.0, 3)


def clip_plans() -> list[dict]:
    plans = []
    start = 0.0
    for index, shot in enumerate(SHOTS, start=1):
        duration = h3_seconds(shot["frames"])
        speaker = shot["speaker"]
        line = shot["line"]
        if speaker and line:
            spoken = f"<d>[Spanish] {line}</d>"
            beats = [{
                "speaker_id": speaker,
                "spoken_text": line,
                "delivery": "calm, Spanish of Spain, stop-motion puppet mouth",
            }]
        else:
            spoken = ""
            beats = []
        prompt = (
            f"integrated_multimodal_description: [Shot 1] {STYLE} {shot['visual']} {spoken}\n\n"
            "overall_soundscape: N/A\n\n"
            "non_diegetic_music: N/A"
        )
        plans.append({
            "shot_id": f"shot-{index}",
            "video_prompt": prompt,
            "image_prompt": "",
            "duration_sec": duration,
            "duration_frames": shot["frames"],
            "_director_duration_sec": duration,
            "_director_h3_prompt_mode": "t2va",
            "_director_subjects_on_screen": SUBJECTS,
            "_director_dialogue_beats": beats,
            "metadata": {
                "label": shot["label"],
                "start": round(start, 3),
                "end": round(start + duration, 3),
            },
        })
        start += duration
    return plans


def planned_clips(plans: list[dict]) -> list[dict]:
    clips = []
    for plan in plans:
        meta = plan["metadata"]
        clips.append({
            "label": meta["label"],
            "start": meta["start"],
            "end": meta["end"],
            "duration_sec": plan["duration_sec"],
            "duration_frames": plan["duration_frames"],
        })
    return clips


def compile_plans(plans: list[dict]) -> list[dict]:
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    from services.director.h3_dialogue import compile_h3_clip_plans

    compiled = copy.deepcopy(plans)
    compile_h3_clip_plans(compiled)
    return compiled


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


def process_running(needle: str) -> bool:
    proc = Path("/proc")
    if not proc.is_dir():
        return False
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except OSError:
            continue
        if needle in cmdline:
            return True
    return False


def wait_previous_work() -> None:
    log("waiting for Vader IT trilogy and any GPU jobs to finish")
    while True:
        data = request_json("GET", "/api/v1/jobs")
        live = [
            job for job in (data.get("jobs") or [])
            if str(job.get("status") or "") in {"queued", "running"}
        ]
        try:
            active = request_json("GET", "/api/v1/director/pipelines/active").get("pipelines") or []
        except Exception:
            active = []
        vader_alive = process_running(VADER_SCRIPT)
        if not live and not active and not vader_alive:
            log("GPU idle; starting claymation Bag End")
            time.sleep(15)
            return
        log(
            f"still busy: jobs={len(live)} pipelines={len(active)} "
            f"vader_script={'yes' if vader_alive else 'no'}"
        )
        time.sleep(20)


def wait_job(job_id: str, timeout_s: int = 8 * 3600) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = request_json("GET", f"/api/v1/status/{job_id}")
        status = str(job.get("status") or "")
        msg = job.get("message") or job.get("progress") or ""
        log(f"job {job_id} {status}: {msg}")
        if status in {"completed", "failed", "cancelled", "crashed"}:
            if status != "completed":
                raise RuntimeError(f"job {job_id} {status}: {job.get('error')}")
            return job
        time.sleep(20)
    raise TimeoutError(f"job {job_id} timed out")


def queue_shot(plan: dict) -> dict:
    frames = int(plan["duration_frames"])
    seconds = float(plan["duration_sec"])
    body = {
        "prompt": plan["video_prompt"],
        "model_type": "minimax_h3_legacy",
        "resolution": "960x544",
        "video_length": frames,
        "num_inference_steps": 20,
        "guidance_scale": 1.0,
        "seed": -1,
        "image_mode": 0,
        "negative_prompt": "live action, photoreal humans, modern rappers, concert stage, CGI smooth",
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
        "_batch_label": f"claymation-bagend-{plan['shot_id']}-{plan['metadata']['label']}",
    }
    return request_json("POST", "/api/v1/generate", body)


def concat_clips(filenames: list[str], destination: Path) -> None:
    list_file = ROOT / "claymation_bagend_concat.txt"
    lines = []
    for name in filenames:
        path = OUTPUTS / name
        if not path.is_file():
            raise RuntimeError(f"clip missing: {path}")
        lines.append(f"file '{path}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
        str(destination),
    ]
    log("concat " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def write_sidecar(destination: Path, filenames: list[str], jobs: list[dict]) -> None:
    sidecar = destination.with_suffix(".meta.json")
    sidecar.write_text(json.dumps({
        "result_kind": "series_episode",
        "params": {
            "pipeline_type": "short_film_story",
            "result_kind": "series_episode",
            "production_kind": "series_episode",
            "source": "claymation_bagend",
            "clips": filenames,
        },
        "generation_mode": "video",
        "created_at": time.time(),
        "jobs": [{"job_id": job.get("job_id"), "label": job.get("label")} for job in jobs],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def existing_outputs() -> dict[str, str]:
    pipeline = ROOT / "claymation_bagend_pipeline.json"
    found: dict[str, str] = {}
    if not pipeline.is_file():
        return found
    data = json.loads(pipeline.read_text(encoding="utf-8"))
    for job in data.get("jobs") or []:
        label = str(job.get("label") or "")
        job_id = str(job.get("job_id") or "")
        name = f"minimax_h3_{job_id}.mp4"
        if label and job_id and (OUTPUTS / name).is_file():
            found[label] = name
    return found


def main() -> None:
    plans = clip_plans()
    wait_previous_work()
    already = existing_outputs()
    queued = []
    filenames: list[str] = []
    pending: list[dict] = []
    for plan in plans:
        label = plan["metadata"]["label"]
        if label in already:
            log(f"skip {plan['shot_id']} {label}: {already[label]}")
            filenames.append(already[label])
            queued.append({
                "job_id": Path(already[label]).stem.replace("minimax_h3_", "", 1),
                "status": "completed",
                "label": label,
                "shot_id": plan["shot_id"],
                "reused": True,
            })
            continue
        submitted = queue_shot(plan)
        log(f"queued {plan['shot_id']} {label}: {submitted.get('job_id')}")
        item = {**submitted, "label": label, "shot_id": plan["shot_id"]}
        queued.append(item)
        pending.append(item)
        filenames.append("")
        time.sleep(0.3)
    (ROOT / "claymation_bagend_pipeline.json").write_text(
        json.dumps({"mode": "direct_generate", "jobs": queued, "plans": planned_clips(plans)}, indent=2),
        encoding="utf-8",
    )
    pending_index = 0
    for index, name in enumerate(filenames):
        if name:
            continue
        item = pending[pending_index]
        pending_index += 1
        job = wait_job(item["job_id"])
        files = [fname for fname in (job.get("output_files") or []) if str(fname).endswith(".mp4")]
        if not files:
            raise RuntimeError(f"{item['shot_id']} completed without mp4: {job}")
        filenames[index] = files[0]
        log(f"{item['shot_id']} file={files[0]}")
    destination = OUTPUTS / "claymation_bagend_multiclip.mp4"
    concat_clips(filenames, destination)
    write_sidecar(destination, filenames, queued)
    log(f"claymation Bag End done: {destination.name}")


if __name__ == "__main__":
    main()
