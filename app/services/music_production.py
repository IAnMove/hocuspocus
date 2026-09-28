"""Music-video production from one spec: the only creative input an agent writes.

``production.run`` starts (or resumes) a background run in the workspace; ``production.status``
returns a short summary. The run drives the same public MCP tools an agent would call
(generation.music/image, generate with H3 driving audio, scenes.video2d.edit/export,
montages.save/export) through the app's own MCP endpoint, plus the local audio.analyze and
qa.lipsync functions. Decisions a model used to make by looking are made here by numbers:
the song with the best lyric recall and no cut ending wins, clips that fail lip-sync are
retaken with a new seed (max_takes), long instrumental stretches are filled on bar lines.
State lives in <workspace>/<id>.production.json, so a restart resumes where it stopped.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

import numpy as np

from services import lipsync_qa, song_analysis as audio_analysis

RUN, STATUS = "production.run", "production.status"
H3_FRAMES = [124 + 17 * k for k in range(14)]            # H3 window lengths (124 … 345 frames at 24 fps)
STEPS = ("song", "analyze", "cast", "frames", "clips", "scenes", "montage")
_threads: dict[str, threading.Thread] = {}
_lock = threading.Lock()


class ProductionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- spec
SPEC_SCHEMA: dict[str, Any] = {
    "type": "object", "required": ["title", "song", "style", "shots"], "properties": {
        "title": {"type": "string", "maxLength": 120},
        "song": {"type": "object", "required": ["lyrics", "caption", "duration", "bpm"], "properties": {
            "lyrics": {"type": "string", "maxLength": 20000}, "caption": {"type": "string", "maxLength": 2000},
            "duration": {"type": "number", "minimum": 10, "maximum": 300}, "bpm": {"type": "integer", "minimum": 60, "maximum": 200},
            "key": {"type": "string"}, "seeds": {"type": "array", "items": {"type": "integer"}, "maxItems": 6},
            "model": {"type": "string"}, "file": {"type": "string", "description": "Use an existing workspace song instead of generating"}}},
        "style": {"type": "object", "properties": {"image": {"type": "string"}, "video": {"type": "string"},
                                                   "lyric_template": {"type": "string"}, "finish": {"type": "object"}}},
        "cast": {"type": "array", "items": {"type": "object", "required": ["id", "sheet_prompt"]}},
        "stills": {"type": "object", "description": "name -> durable media URL"},
        "shots": {"type": "array", "maxItems": 60, "items": {"type": "object", "required": ["key", "kind"], "properties": {
            "key": {"type": "string"}, "kind": {"enum": ["h3", "still", "clip"]}, "line": {"type": "integer"}, "span": {"type": "integer"},
            "t0": {"type": "number"}, "after": {"type": "integer"}, "cast": {"type": "array"}, "sing": {"type": "boolean"},
            "frame": {"type": "string"}, "action": {"type": "string"}, "still": {"type": "string"}, "clip": {"type": "string"},
            "focus": {"type": "object"}, "zoom": {"type": "array"}, "camera": {"type": "string"}, "title": {"type": "object"}}}},
        "fill": {"type": "array", "description": "Shots used to fill instrumental stretches longer than a clip"},
        "max_takes": {"type": "integer", "minimum": 1, "maximum": 5}},
}


def validate_spec(spec: Any) -> dict:
    if not isinstance(spec, dict):
        raise ProductionError("invalid_spec", "spec must be an object")
    for key in SPEC_SCHEMA["required"]:
        if key not in spec:
            raise ProductionError("invalid_spec", f"spec.{key} is required")
    song = spec["song"]
    if not isinstance(song, dict) or not all(k in song for k in ("lyrics", "caption", "duration", "bpm")):
        raise ProductionError("invalid_spec", "spec.song needs lyrics, caption, duration and bpm")
    keys = set()
    for shot in spec["shots"]:
        if not isinstance(shot, dict) or not shot.get("key") or shot.get("kind") not in ("h3", "still", "clip"):
            raise ProductionError("invalid_spec", "each shot needs key and kind h3|still|clip")
        if shot["key"] in keys:
            raise ProductionError("invalid_spec", f"duplicate shot key {shot['key']}")
        keys.add(shot["key"])
        if shot["kind"] == "h3" and not (shot.get("frame") and shot.get("action")):
            raise ProductionError("invalid_spec", f"h3 shot {shot['key']} needs frame and action")
    return spec


# ---------------------------------------------------------------- pure planning helpers (tested)
def h3_frames_for(seconds: float) -> int:
    need = int(np.ceil(seconds * 24))
    return next((f for f in H3_FRAMES if f >= need), H3_FRAMES[-1])


def shot_windows(spec: dict, score: dict) -> list[dict]:
    lines = score.get("lines") or []
    out = []
    for index, shot in enumerate(spec["shots"]):
        line = lines[shot["line"]] if isinstance(shot.get("line"), int) and shot["line"] < len(lines) else None
        if "t0" in shot:
            t0 = float(shot["t0"])
        elif line:
            t0 = line["t0"] - 0.25
        elif isinstance(shot.get("after"), int) and shot["after"] < len(lines):
            t0 = lines[shot["after"]]["t1"] + 0.3
        else:
            t0 = 0.0
        if line:
            last = lines[min(len(lines) - 1, shot["line"] + shot.get("span", 1) - 1)]
            t1 = last["t1"] + 0.2
        else:
            t1 = t0 + 4
        out.append({**shot, "i": index, "t0": round(max(0.0, t0), 3), "t1": round(t1, 3)})
    return out


def segments(windows: list[dict], score: dict, clip_ok: Callable[[str], bool], fill: list[dict]) -> list[tuple[dict, float, float]]:
    """Scene cuts; an h3 shot longer than its clip is cut at the clip end and the rest filled on bar lines."""
    cuts = [w["t0"] for w in windows] + [float(score["duration"])]
    cuts[0] = 0.0
    bar = 4 * float(score.get("beat") or 0.5)
    out, used = [], 0
    for n, shot in enumerate(windows):
        a, b = cuts[n], cuts[n + 1]
        if shot["kind"] == "h3" and clip_ok(shot["key"]) and fill:
            length = h3_frames_for(shot["t1"] - shot["t0"]) / 24 - max(0.0, a - shot["t0"])
            if b - a > length + 0.3:
                out.append((shot, a, a + length))
                t, k = a + length, 0
                while t < b - 0.05:
                    item = fill[used % len(fill)]
                    used += 1
                    end = min(b, t + 2 * bar)
                    out.append(({**item, "key": f"{shot['key']}_fill{k}"}, t, end))
                    t, k = end, k + 1
                continue
        if b - a > 0.05:
            out.append((shot, a, b))
    return out


def pick_song(candidates: dict[str, dict]) -> str:
    good = {k: v for k, v in candidates.items() if v.get("tail_rms", 1) <= audio_analysis.TAIL_CUT_RMS} or candidates
    return max(good, key=lambda k: good[k].get("recall") or 0)


# ---------------------------------------------------------------- run
class Production:
    def __init__(self, workspace: str, production_id: str, *, workspace_dir: Callable[[str], str], uploads_dir: Callable[[], str],
                 mcp: Callable[[str, dict], dict]):
        self.ws, self.id = workspace, production_id
        self.root = Path(workspace_dir(workspace))
        self.uploads = Path(uploads_dir())
        self.mcp = mcp
        self.path = self.root / f"{production_id}.production.json"
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}

    # state
    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False))
        tmp.replace(self.path)

    def log(self, line: str) -> None:
        self.state.setdefault("log", []).append(line[:200])
        self.state["log"] = self.state["log"][-60:]
        self.save()

    # media helpers
    def upload(self, name: str) -> tuple[str, str]:
        """Copy a workspace file into uploads; returns (path, url) as /api/v1/upload would."""
        src = self.root / name
        target = self.uploads / f"{uuid.uuid4().hex}{src.suffix.lower()}"
        self.uploads.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        return str(target), f"/api/v1/uploads/{target.name}"

    def wait(self, jobs: dict[str, str]) -> dict[str, str | None]:
        done: dict[str, str | None] = {}
        while len(done) < len(jobs):
            for key, job in jobs.items():
                if key in done or not job:
                    done.setdefault(key, None)
                    continue
                s = self.mcp("status", {"job_id": job})
                if s.get("status") == "completed":
                    done[key] = (s.get("output_files") or [None])[0]
                elif s.get("status") in ("failed", "error", "cancelled", "discarded"):
                    done[key] = None
            if len(done) < len(jobs):
                time.sleep(6)
        return done

    def image(self, key: str, prompt: str, refs: list[str] | None, res: str, seed: int) -> str | None:
        params = {"prompt": prompt, "model_type": "flux2_klein_9b", "resolution": res, "seed": seed, "guidance_scale": 1, "num_inference_steps": 4}
        if refs:
            params.update(image_refs=refs, video_prompt_type="I")
        r = self.mcp("generation.image", {"version": 2, "intent_id": f"{self.id}-{key}-{seed}", "input": {"workspace": self.ws, "params": params}})
        return ((r.get("receipt") or {}).get("result") or {}).get("job_id")

    # steps
    def song(self, spec: dict) -> None:
        if self.state.get("song"):
            return
        sp = spec["song"]
        if sp.get("file"):
            self.state["song"] = {"file": sp["file"]}
            return self.log(f"song: using {sp['file']}")
        jobs = {}
        for seed in sp.get("seeds") or [11, 22, 33]:
            params = {"prompt": sp["lyrics"], "alt_prompt": sp["caption"], "model_type": sp.get("model", "ace_step_v1_5_xl_sft_lm_4b"), "seed": seed,
                      "generation_mode": "audio", "_audio_sub_mode": "music", "image_mode": 0, "video_length": 0, "lyrics_language": "en",
                      "duration_seconds": sp["duration"], "custom_settings": {"bpm": int(sp["bpm"]), "keyscale": sp.get("key", "A minor"), "timesignature": 4, "language": "en"}}
            r = self.mcp("generation.music", {"version": 2, "intent_id": f"{self.id}-song-{seed}", "input": {"workspace": self.ws, "params": params}})
            jobs[str(seed)] = ((r.get("receipt") or {}).get("result") or {}).get("job_id")
        candidates = {}
        for seed, name in self.wait(jobs).items():
            if not name:
                continue
            score = audio_analysis.analyze(str(self.root / name), sp["lyrics"], out_dir=str(self.root))
            candidates[seed] = {"file": name, "recall": score["recall"], "tail_rms": score["tail_rms"], "score_file": score["score_file"]}
            self.log(f"song seed {seed}: recall {score['recall']} tail {score['tail_rms']}")
        if not candidates:
            raise ProductionError("song_failed", "No song candidate finished")
        best = pick_song(candidates)
        self.state["song"] = candidates[best]
        self.log(f"song: picked seed {best}")

    def analyze(self, spec: dict) -> None:
        if self.state.get("score"):
            return
        song = self.state["song"]
        if not song.get("score_file"):
            song["score_file"] = audio_analysis.analyze(str(self.root / song["file"]), spec["song"]["lyrics"], out_dir=str(self.root))["score_file"]
        self.state["score"] = song["score_file"]
        score = self.score()
        self.log(f"analyze: {score['bpm']} BPM, {len(score['lines'])} lines, recall {score['recall']}")

    def score(self) -> dict:
        return json.loads((self.root / self.state["score"]).read_text())

    def cast(self, spec: dict) -> None:
        cast = self.state.setdefault("cast", {})
        style = (spec.get("style") or {}).get("image", "")
        jobs = {c["id"]: self.image("cast-" + c["id"], c["sheet_prompt"] if style in c["sheet_prompt"] else f"{c['sheet_prompt']} {style}".strip(), None, "1536x1024", c.get("seed", 5))
                for c in spec.get("cast") or [] if c["id"] not in cast}
        for cid, name in self.wait(jobs).items():
            if name:
                cast[cid] = self.upload(name)[1]
        self.log(f"cast: {len(cast)}")

    def frames(self, spec: dict, windows: list[dict]) -> None:
        frames = self.state.setdefault("frames", {})
        style = (spec.get("style") or {}).get("image", "")
        jobs = {}
        for w in windows:
            if w["kind"] != "h3" or w["key"] in frames:
                continue
            refs = [self.state["cast"][c] for c in w.get("cast", []) if c in self.state.get("cast", {})]
            jobs[w["key"]] = self.image("frame-" + w["key"], f"{style} {w['frame']}".strip(), refs or None, "1280x704", w.get("seed", 3))
        for key, name in self.wait(jobs).items():
            if name:
                frames[key] = name
        self.log(f"frames: {len(frames)}")

    def clip_job(self, spec: dict, w: dict, seed: int) -> str | None:
        frames = h3_frames_for(w["t1"] - w["t0"])
        slice_name = f"{self.id}-slice-{w['key']}.wav"
        import subprocess
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(w["t0"]), "-t", str(frames / 24), "-i", str(self.root / self.state["song"]["file"]),
                        "-ar", "48000", "-ac", "2", str(self.root / slice_name)], check=True)
        sing = " (S1) sings the lead vocal of the mapped driving audio, lips, jaw and breath in precise sync with every syllable." if w.get("sing") else ""
        prompt = (f"integrated_multimodal_description: [Shot 1] {(spec.get('style') or {}).get('video', '')} {w['action']}{sing}\n"
                  "overall_soundscape: The mapped driving audio: the song.\nnon_diegetic_music: N/A")
        params = {"prompt": prompt, "model_type": "minimax_h3_fused_turbo", "resolution": "1280x704", "seed": seed, "generation_mode": "video",
                  "workspace": self.ws, "image_prompt_type": "S", "image_start": self.upload(self.state["frames"][w["key"]])[0],
                  "video_length": frames, "sliding_window_size": frames, "num_inference_steps": 4, "guidance_scale": 1, "image_mode": 0,
                  "input_video_strength": 1.0, "audio_prompt_type": "A", "audio_guide": self.upload(slice_name)[0]}
        r = self.mcp("generate", {"request_id": f"{self.id}-{w['key']}-{seed}", "params": params})
        return r.get("job_id") or (r.get("result") or {}).get("job_id")

    def clips(self, spec: dict, windows: list[dict]) -> None:
        clips = self.state.setdefault("clips", {})
        max_takes = int(spec.get("max_takes", 3))
        vocals = self.score().get("vocals_file")
        pending = [w for w in windows if w["kind"] == "h3" and w["key"] not in clips and w["key"] in self.state.get("frames", {})]
        takes = {w["key"]: 0 for w in pending}
        while pending:
            names = self.wait({w["key"]: self.clip_job(spec, w, 7000 + w["i"] * 10 + takes[w["key"]]) for w in pending})
            retry = []
            for w in pending:
                takes[w["key"]] += 1
                name = names.get(w["key"])
                if not name:
                    continue
                qa = lipsync_qa.measure(str(self.root / name), str(self.root / vocals), w["t0"]) if w.get("sing") and vocals else {"verdict": "ok"}
                self.log(f"clip {w['key']} take {takes[w['key']]}: {qa.get('verdict')} r={qa.get('best_r')}")
                best = clips.get(w["key"])
                if not best or (qa.get("best_r") or 0) >= ((best.get("qa") or {}).get("best_r") or 0):
                    clips[w["key"]] = {"file": name, "qa": qa, "url": self.upload(name)[1]}
                if qa["verdict"] == "retake" and takes[w["key"]] < max_takes:
                    retry.append(w)
            self.save()
            pending = retry

    def scenes(self, spec: dict, windows: list[dict]) -> None:
        score = self.score()
        clips = self.state.get("clips", {})
        segs = segments(windows, score, lambda k: k in clips, spec.get("fill") or [])
        self.state["segments"] = [[s["key"], a, b] for s, a, b in segs]
        done = self.state.setdefault("scenes", {})
        style, stills = spec.get("style") or {}, spec.get("stills") or {}
        for shot, a, b in segs:
            dur = round(b - a, 3)
            if done.get(shot["key"], {}).get("dur") == dur and done[shot["key"]].get("file"):
                continue
            doc = {"version": 1, "name": shot["key"], "width": 1920, "height": 1080, "fps": 24, "duration": dur, "layers": [], "texts": []}
            doc = self.edit(doc, self.scene_ops(shot, a, b, dur, score, clips, style, stills))
            r = self.mcp("scenes.video2d.export", {"version": 1, "intent_id": f"{self.id}-scene-{shot['key']}-{int(time.time())}",
                                                   "input": {"workspace": self.ws, "document": doc}})
            done[shot["key"]] = {"intent": (r.get("receipt") or {}).get("commandId"), "dur": dur, "file": None}
            self.save()
        for key, scene in done.items():
            while scene.get("intent") and not scene.get("file"):
                r = self.mcp("scenes.video2d.export.receipt", {"version": 1, "input": {"workspace": self.ws, "intent_id": scene["intent"]}})
                arts = (r.get("receipt") or {}).get("artifacts") or []
                if arts:
                    scene["file"] = arts[0]["name"]
                elif (r.get("task") or {}).get("status") in ("failed", "cancelled"):
                    self.log(f"scene {key} failed")
                    break
                else:
                    time.sleep(4)
        self.log(f"scenes: {sum(1 for s in done.values() if s.get('file'))}/{len(segs)}")

    def edit(self, doc: dict, ops: list[dict]) -> dict:
        r = self.mcp("scenes.video2d.edit", {"version": 1, "input": {"document": doc, "operations": ops, "full": True}})
        if "result" not in r:
            raise ProductionError("scene_edit_failed", json.dumps(r)[:300])
        return r["result"]["document"]

    def scene_ops(self, shot: dict, a: float, b: float, dur: float, score: dict, clips: dict, style: dict, stills: dict) -> list[dict]:
        ops: list[dict] = []
        clip = clips.get(shot["key"]) or (clips.get(shot.get("clip")) if shot["kind"] == "clip" else None)
        if clip:
            ops.append({"op": "add_layer", "id": "bg", "source": clip["url"], "type": "video", "preset": shot.get("camera", "camera-push-in")})
            skip = round(max(0.0, a - shot.get("t0", a)) + ((clip.get("qa") or {}).get("suggested_sync_s") or 0), 3) if shot["kind"] == "h3" else 0
            anim: dict[str, Any] = {"end": {"x": 50, "y": 50, "scale": 1.08 if shot["kind"] == "h3" else 1.15, "rotation": 0}}
            if skip > 0:
                anim.update(trimStart=skip, duration=round(dur + skip, 3))
            ops.append({"op": "update_layer", "id": "bg", "patch": {"fill": True, "animation": anim}})
        else:
            zoom = shot.get("zoom") or [1.0, 1.1]
            ops += [{"op": "add_layer", "id": "bg", "source": stills.get(shot.get("still"), shot.get("still")), "type": "image", "preset": shot.get("camera", "camera-push-in")},
                    {"op": "update_layer", "id": "bg", "patch": {"fill": True, "focus": shot.get("focus", {"x": 50, "y": 50}), "animation": {
                        "start": {"x": 50, "y": 50, "scale": zoom[0], "rotation": 0}, "end": {"x": 50, "y": 50, "scale": zoom[1], "rotation": 0}}}}]
        if shot.get("title"):
            ops.append({"op": "add_title", "id": "tt", "template": shot["title"].get("template", "lower-third-date"), "fields": shot["title"]["fields"],
                        "start": 0.1, "duration": round(dur - 0.2, 3)})
        for index, line in enumerate(score.get("lines") or []):
            if line["t1"] <= a or line["t0"] >= b:
                continue
            ops.append({"op": "add_title", "id": f"ly{index}", "template": style.get("lyric_template", "social-caption"), "fields": {"caption": line["text"]},
                        "start": round(max(0.0, line["t0"] - a), 3), "duration": round(min(b, line["t1"] + 0.15) - max(a, line["t0"]), 3)})
        if style.get("finish"):
            ops.append({"op": "set_finish", **style["finish"]})
        return ops

    def montage(self, spec: dict) -> None:
        score, scenes = self.score(), self.state["scenes"]
        clips = [{"id": k, "name": k, "source": f"/api/v1/file/{scenes[k]['file']}?workspace={self.ws}", "trimStart": 0, "trimEnd": scenes[k]["dur"],
                  "muted": True, "fit": "fill", "transition": "none"} for k, _, _ in self.state["segments"] if scenes.get(k, {}).get("file")]
        montage = {"version": 1, "name": spec["title"], "width": 1920, "height": 1080, "fps": 24, "clips": clips, "audioCues": [], "overlays": [],
                   "soundtrack": {"source": f"/api/v1/file/{self.state['song']['file']}?workspace={self.ws}", "trimStart": 0, "trimEnd": score["duration"], "volume": 1.0, "loop": False}}
        body: dict[str, Any] = {"workspace": self.ws, "montage": montage}
        if self.state.get("montage_file"):
            current = (self.mcp("montages.get", {"version": 1, "input": {"workspace": self.ws, "file": self.state["montage_file"]}}).get("result") or {})
            revision = current.get("revision") or (current.get("montage") or {}).get("revision")
            if revision:
                body.update(file=self.state["montage_file"], expected_revision=revision)
        saved = self.mcp("montages.save", {"version": 1, "intent_id": f"{self.id}-montage-{int(time.time())}", "input": body})
        if "result" not in saved:
            raise ProductionError("montage_failed", json.dumps(saved)[:300])
        self.state["montage_file"] = saved["result"]["file"]
        job = self.mcp("montages.export", {"version": 1, "intent_id": f"{self.id}-export-{int(time.time())}",
                                           "input": {"workspace": self.ws, "file": self.state["montage_file"]}})["result"]["job"]
        while True:
            status = self.mcp("montages.export.status", {"version": 1, "input": {"workspace": self.ws, "job_id": job["job_id"]}})
            status = (status.get("result") or status).get("job", status)
            if status.get("status") in ("completed", "failed"):
                break
            time.sleep(4)
        self.state["final"] = status.get("filename")
        if self.state["final"]:
            import subprocess
            sheet = f"{self.id}-contact.jpg"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(self.root / self.state["final"]), "-vf", "fps=1/2.5,scale=320:-1,tile=6x4",
                            "-frames:v", "1", str(self.root / sheet)])
            self.state["contact_sheet"] = sheet
        self.log(f"montage: {status.get('status')}")

    def run(self, spec: dict) -> None:
        self.state.update(spec=spec, status="running", started=self.state.get("started") or time.time())
        self.save()
        try:
            self.song(spec)
            self.analyze(spec)
            self.cast(spec)
            windows = shot_windows(spec, self.score())
            self.frames(spec, windows)
            self.clips(spec, windows)
            self.scenes(spec, windows)
            self.montage(spec)
            self.state["status"] = "completed" if self.state.get("final") else "failed"
        except Exception as error:  # the run is resumable; keep the reason
            self.state.update(status="failed", error=f"{type(error).__name__}: {error}"[:300])
        self.state["finished"] = time.time()
        self.save()


def status_summary(state: dict, workspace: str) -> dict[str, Any]:
    url = lambda name: f"/api/v1/file/{name}?workspace={workspace}" if name else None
    clips = state.get("clips") or {}
    return {"status": state.get("status", "unknown"), "error": state.get("error"),
            "song": (state.get("song") or {}).get("file"), "clips": {k: (v.get("qa") or {}).get("verdict") for k, v in clips.items()},
            "scenes": sum(1 for s in (state.get("scenes") or {}).values() if s.get("file")),
            "video": url(state.get("final")), "contact_sheet": url(state.get("contact_sheet")), "log": (state.get("log") or [])[-8:]}


# ---------------------------------------------------------------- MCP
def command_catalog() -> list[dict[str, Any]]:
    envelope = lambda props, required: {"type": "object", "additionalProperties": False, "required": ["version", "input"], "properties": {
        "version": {"type": "integer", "const": 1},
        "input": {"type": "object", "additionalProperties": False, "required": required, "properties": props}}}
    ws = {"type": "string", "minLength": 1, "maxLength": 120}
    pid = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"}
    return [
        {"name": RUN, "description": ("Produce a music video from one spec, in the background: K song candidates (best lyric recall, no cut "
                                      "ending), analysis, cast sheets, start frames, H3 clips driven by the exact song slice with automatic "
                                      "lip-sync retakes, one Video 2D scene per shot with timed lyric captions, instrumental gaps filled on bar "
                                      "lines, montage and export. Pass spec to start; pass only production_id to resume. Returns immediately; "
                                      "poll production.status. See docs/agents/VIDEO_PRODUCTION_RUNBOOK.md."),
         "inputSchema": envelope({"workspace": ws, "production_id": pid, "spec": SPEC_SCHEMA}, ["workspace", "production_id"])},
        {"name": STATUS, "description": "Short summary of a production: status, per-clip lip-sync verdicts, video and contact-sheet URLs, last log lines.",
         "inputSchema": envelope({"workspace": ws, "production_id": pid}, ["workspace", "production_id"])},
    ]


def loopback_mcp(app_url: Callable[[], str], token: Callable[[], str]) -> Callable[[str, dict], dict]:
    def call(tool: str, arguments: dict) -> dict:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}).encode()
        request = urllib.request.Request(app_url().rstrip("/") + "/api/v1/mcp", data=body, method="POST", headers={
            "Authorization": f"Bearer {token()}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        with urllib.request.urlopen(request, timeout=600) as response:
            result = json.loads(response.read()).get("result") or {}
        if isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]
        try:
            return json.loads(result["content"][0]["text"])
        except (KeyError, IndexError, ValueError):
            return {"error": result}
    return call


def command_handlers(workspace_dir: Callable[[str], str], uploads_dir: Callable[[], str], app_url: Callable[[], str], token: Callable[[], str]) -> dict:
    from fastapi import HTTPException

    def _input(arguments: Any) -> dict:
        data = (arguments or {}).get("input") if isinstance(arguments, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("workspace"), str) or not isinstance(data.get("production_id"), str):
            raise HTTPException(422, {"code": "invalid_command", "message": "Use version 1 with input.workspace and input.production_id", "retryable": False})
        return data

    async def run(arguments: Any) -> dict:
        data = _input(arguments)
        if not token() or not app_url():
            raise HTTPException(503, {"code": "mcp_unavailable", "message": "Enable MCP access so the production can call the studio tools", "retryable": False})
        production = Production(data["workspace"], data["production_id"], workspace_dir=workspace_dir, uploads_dir=uploads_dir, mcp=loopback_mcp(app_url, token))
        try:
            spec = validate_spec(data.get("spec") or production.state.get("spec"))
        except ProductionError as error:
            raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": False}) from error
        key = f"{data['workspace']}/{data['production_id']}"
        with _lock:
            thread = _threads.get(key)
            if not (thread and thread.is_alive()):
                thread = threading.Thread(target=production.run, args=(spec,), name=f"production-{data['production_id']}", daemon=True)
                _threads[key] = thread
                thread.start()
        return {"version": 1, "status": "completed", "operation": RUN, "result": {"production_id": data["production_id"], "running": True}}

    async def status(arguments: Any) -> dict:
        data = _input(arguments)
        path = Path(workspace_dir(data["workspace"])) / f"{data['production_id']}.production.json"
        if not path.exists():
            raise HTTPException(404, {"code": "production_not_found", "message": "No production with this id in the workspace", "retryable": False})
        return {"version": 1, "status": "completed", "operation": STATUS, "result": status_summary(json.loads(path.read_text()), data["workspace"])}

    return {RUN: run, STATUS: status}
