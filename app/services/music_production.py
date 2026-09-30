"""Music-video production from one spec: the only creative input an agent writes.

``production.run`` starts (or resumes) a background run in the workspace; ``production.status``
returns a short summary and can wait until that status changes (``wait_s``, max 1200 s). The run drives the same public MCP tools an agent would call
(generation.music/image, generate with H3 driving audio, scenes.video2d.edit/export,
montages.save/export) through the app's own MCP endpoint, plus the local audio.analyze and
qa.lipsync functions. Decisions a model used to make by looking are made here by numbers:
the song with the best lyric recall and no cut ending wins, clips that fail lip-sync are
retaken until the next measured r does not beat the best r already kept, or 4 takes are recorded.
Long instrumental stretches are filled on bar lines.
State lives in <workspace>/<id>.production.json. A running file younger than 24h resumes on startup when MCP is on.
"""
from __future__ import annotations

import asyncio
import hashlib
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
from services.production_disk import discard, release_completed, require_free_disk
from services.production_publication import publication_catalog, publication_handlers
from services.production_resume import open_mcp
from services.production_resource_gate import guard_mcp
from services.production_shot_plan import is_auto_pad, place_pads, plan_shots
from services.production_timing import StageWatch, timing_summary
from services.production_usage import attach_usage, usage_summary
from services.production_structure import require_direction
from services.production_trailer_audio import attach as attach_trailer_audio
from services.production_quality import expand_quality
from services.production_review import review_for_status
from services.production_scene_retry import apply_scene_export_failure, finish_scene_exports, skip_montage
from services.production_scene3d import export_scene3d_clips, validate_scene3d_shot
from services.production_style_presets import expand_style_preset
from services.production_commands import extra_catalog, extra_handlers
from services.production_control import Cancelled, arm, checkpoint, disarm, sleep_until
from services.production_package import (attach_origins, clip_replacements, contrast_warnings, doc_digest, durable_document, editable_summary,
                                         lyric_for, manifest_rows, write_manifest)
from services.production_shot_edit import render_shot
from services.production_sheets import compose_group, make_frames_sheet
from services.production_takes import another_take, better_take, note_seconds, obsolete_clip, pending_windows, take_settled
from services.production_wait import MAX_WAIT_S, wait_for_status
from services.video2d_edit import MAX_OPERATIONS
from services.video2d_edit_titles import TITLE_BUILDERS

RUN, STATUS, PLAN = "production.run", "production.status", "production.plan"
OMARCHY_THEMES: dict[str, dict] = json.loads((Path(__file__).resolve().parents[1] / "shared" / "omarchy_themes.json").read_text(encoding="utf-8"))["entries"]
FRAME_ATTEMPTS = 2                                       # start-frame rounds per run
FRAME_RESOLUTIONS = ("1280x704", "1152x640", "1024x576")   # after an out-of-memory the next attempt is smaller
# dymo punches its letters out of the tape: on a dark picture they vanish. Dark letters on cream tape read on any picture.
DYMO_READABLE = {"color": "#141210", "box": {"kind": "tape", "color": "#F4EEE2", "opacity": 1, "padding": 0.72, "radius": 0.18}}
MAX_LOST_JOBS = 3                                        # per shot: then a vanished job counts as a failed take
H3_FRAMES = [124 + 17 * k for k in range(14)]            # H3 window lengths (124 … 345 frames at 24 fps)
STEPS = ("song", "analyze", "cast", "frames", "clips", "scenes", "montage")
_threads: dict[str, threading.Thread] = {}
_edits: dict[str, threading.Thread] = {}
_lock = threading.Lock()


def _slot_busy(key: str) -> bool:
    """A live run or a shot/song edit is already writing this production JSON."""
    run = _threads.get(key)
    edit = _edits.get(key)
    return bool(run and run.is_alive()) or bool(edit and edit.is_alive())


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
                                                   "image_model": {"type": "string"}, "image_steps": {"type": "integer"},
                                                   "lyric_template": {"type": "string"}, "lyric_style": {"type": "object"},
                                                   "theme": {"type": "string", "description": "Omarchy colour theme id (app/shared/omarchy_themes.json): screen shots, lyric and footer colours"},
                                                   "content": {"enum": ["screen"], "description": "what auto-planned non-sung shots are: the native desktop (default: a short H3 clip, or stills when given)"},
                                                   "singer": {"type": "boolean", "description": "false: nobody sings on screen (auto-planned shots have no sung H3 shots)"},
                                                   "title_style": {"type": "object"}, "footer": {"type": "string"},
                                                   "footer_style": {"type": "object"}, "finish": {"type": "object"}}},
        "cast": {"type": "array", "items": {"type": "object", "required": ["id", "sheet_prompt"],
                                         "properties": {"image_model": {"type": "string"}, "image_steps": {"type": "integer"},
                                                        "count": {"type": "integer", "minimum": 1, "maximum": 6, "description": "how many distinct subjects this reference stands for (a group image); default 1, or the size of its group"},
                                                        "single_prompt": {"type": "string", "description": "plain one-subject portrait. Default: the sheet prompt plus a full-body view on a neutral background"},
                                                        "group": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4,
                                                                  "description": "ids of other cast entries: one reference image with their portraits side by side (no sheet_prompt needed)"}}}},
        "stills": {"type": "object", "description": "name -> durable media URL"},
        "shots": {"anyOf": [{"type": "string", "const": "auto"}, {"type": "array", "maxItems": 60, "items": {"type": "object", "required": ["key", "kind"], "properties": {
            "key": {"type": "string"}, "kind": {"enum": ["h3", "still", "clip", "screen", "scene3d"]}, "line": {"type": "integer"}, "span": {"type": "integer"},
            "t0": {"type": "number"}, "after": {"type": "integer"}, "cast": {"type": "array"}, "sing": {"type": "boolean"},
            "frame": {"type": "string"}, "action": {"type": "string"}, "still": {"type": "string"}, "clip": {"type": "string"},
            "image_model": {"type": "string"}, "image_steps": {"type": "integer"}, "graphic": {"type": "object"},
            "scene3d": {"type": "object", "description": "Native Video 3D: template or document, GLB subject/slots, camera, atmosphere and movement"},
            "desktop": {"type": "object", "description": "kind screen: tiling desktop fields (layout, apps, focus, workspace, switch, theme)"},
            "focus": {"type": "object"}, "zoom": {"type": "array"}, "camera": {"type": "string"}, "title": {"type": "object"},
            "allow": {"type": "array", "maxItems": 3, "items": {"enum": ["still", "dark", "secondary"]},
                      "description": "Deliberate: still skips frozen_shot, dark skips black_bars, secondary skips duplicate_people and appearance_changed"}}}}]},
        "fill": {"type": "array", "description": "Shots used to fill instrumental stretches longer than a clip"},
        "max_takes": {"type": "integer", "minimum": 1, "maximum": 5},
        "structure": {"enum": ["clip", "trailer"], "description": "clip (default): verse/chorus shots on the song's lines; trailer: five beats on time (presentation, tension, escalation, reveal, close) with designed silence, risers and hits"},
        "treatment": {"type": "object", "description": "what happens: arc (what changes first image to last), want, obstacle, moments [{at, event}] (at: chorus2, bridge, line:N), motifs. dry_run checks the plan carries it"},
        "quality": {"enum": ["draft", "standard", "max"], "description": "how much the run spends to make it good: fills song seeds and max_takes the spec left out and sets the bar dry_run measures (share of stills, clips per minute)"},
        "resolution": {"type": "object", "properties": {
            "frames": {"enum": ["1280x704", "1152x640", "1024x576", "1536x1024", "1024x1536"]},
            "clips": {"enum": ["1280x704", "1152x640", "1024x576"]}}},
        "enhance": {"type": "object", "properties": {
            "method": {"enum": ["flashvsr", "rife"]},
            "scale": {"enum": [2, 4]}}}},
}


def _require_spec_fields(spec: dict) -> None:
    for key in SPEC_SCHEMA["required"]:
        if key not in spec:
            raise ProductionError("invalid_spec", f"spec.{key} is required")
    song = spec["song"]
    if not isinstance(song, dict) or not all(k in song for k in ("lyrics", "caption", "duration", "bpm")):
        raise ProductionError("invalid_spec", "spec.song needs lyrics, caption, duration and bpm")
    if not isinstance(spec.get("style"), dict):
        raise ProductionError("invalid_spec", "spec.style must be an object")


def _image_models(spec: dict) -> list:
    style = spec["style"]
    cast = spec.get("cast", [])
    return [
        style.get("image_model"),
        *(c.get("image_model") for c in cast if isinstance(c, dict)),
        *(s.get("image_model") for s in spec["shots"] if isinstance(s, dict)),
    ]


def _require_image_models(spec: dict) -> None:
    for model in _image_models(spec):
        if model is not None and (not isinstance(model, str) or not 1 <= len(model) <= 120):
            raise ProductionError("invalid_spec", "image_model must be a model selector")


def _require_shot(shot: Any, keys: set) -> None:
    if not isinstance(shot, dict) or not shot.get("key") or shot.get("kind") not in ("h3", "still", "clip", "screen", "scene3d"):
        raise ProductionError("invalid_spec", "each shot needs key and kind h3|still|clip|screen|scene3d")
    if shot["key"] in keys:
        raise ProductionError("invalid_spec", f"duplicate shot key {shot['key']}")
    keys.add(shot["key"])
    if shot["kind"] == "h3" and not (shot.get("frame") and shot.get("action")):
        raise ProductionError("invalid_spec", f"h3 shot {shot['key']} needs frame and action")


def _require_scene3d(shot: Any) -> None:
    if not isinstance(shot, dict) or shot.get("kind") != "scene3d":
        return
    try:
        validate_scene3d_shot(shot)
    except ValueError as error:
        raise ProductionError("invalid_spec", str(error)) from error


def _require_shots(spec: dict) -> None:
    keys: set = set()
    for shot in spec["shots"]:
        _require_shot(shot, keys)
    for shot in [*spec["shots"], *(spec.get("fill") or [])]:
        _require_scene3d(shot)


def validate_spec(spec: Any) -> dict:
    spec = expand_quality(expand_style_preset(spec))
    spec = plan_shots(spec)
    if not isinstance(spec, dict):
        raise ProductionError("invalid_spec", "spec must be an object")
    _require_spec_fields(spec)
    _require_image_models(spec)
    _require_shots(spec)
    from services.production_resolution import check_resolution
    return require_direction(check_resolution(spec))


# ---------------------------------------------------------------- pure planning helpers (tested)
def h3_frames_for(seconds: float) -> int:
    need = int(np.ceil(seconds * 24))
    return next((f for f in H3_FRAMES if f >= need), H3_FRAMES[-1])


def shot_windows(spec: dict, score: dict) -> list[dict]:
    lines = score.get("lines") or []
    try:
        duration = float(score.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    out = []
    for index, shot in enumerate(spec["shots"]):
        if is_auto_pad(shot):
            continue
        line = lines[shot["line"]] if isinstance(shot.get("line"), int) and 0 <= shot["line"] < len(lines) else None
        if "t0" in shot:
            t0 = float(shot["t0"])
        elif line:
            t0 = line["t0"] - 0.25
        elif isinstance(shot.get("after"), int) and 0 <= shot["after"] < len(lines):
            t0 = lines[shot["after"]]["t1"] + 0.3
        else:
            t0 = 0.0
        # an `after` card uses last.t1 + 0.3; when the last lyric ends at the song
        # end that start is past duration and segments() drops it (b - a <= 0).
        if duration > 0 and t0 >= duration:
            t0 = max(0.0, duration - 4.0)
        if line:
            last = lines[min(len(lines) - 1, shot["line"] + shot.get("span", 1) - 1)]
            t1 = last["t1"] + 0.2
        elif "t1" in shot:
            try:
                t1 = float(shot["t1"])
            except (TypeError, ValueError):
                t1 = t0 + 4
        else:
            t1 = t0 + 4                       # untitled cards; a trailer bakes t1 so a held beat is not 4 s
        out.append({**shot, "i": index, "t0": round(max(0.0, t0), 3), "t1": round(t1, 3)})
    try:
        bpm = float(score.get("bpm") or 120) or 120.0
    except (TypeError, ValueError):
        bpm = 120.0
    shots = spec.get("shots") if isinstance(spec.get("shots"), list) else []
    if spec.get("auto_pads") or any(is_auto_pad(shot) for shot in shots):
        return place_pads(out, spec, duration, bpm)
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


def title_span(dur: float) -> tuple[float, float] | None:
    """Inset 0.1 s when the scene is long enough; otherwise fill the scene. None if nothing fits."""
    if dur <= 0:
        return None
    if dur > 0.3:
        start, length = 0.1, round(dur - 0.2, 3)
    else:
        start, length = 0.0, round(dur, 3)
    if length <= 0:
        return None
    return start, length


def lyric_span(line: dict, a: float, b: float, dur: float) -> tuple[float, float] | None:
    """Scene-relative start/duration for a score line, or None if it would be rejected by edit."""
    if line["t1"] <= a or line["t0"] >= b:
        return None
    start = round(max(0.0, line["t0"] - a), 3)
    length = round(min(b, line["t1"] + 0.15) - max(a, line["t0"]), 3)
    if length <= 0 or start + length - dur > 1e-6:
        return None
    return start, length


def seam_look(line: dict, a: float, b: float) -> dict:
    """A line that runs across a cut keeps one continuous caption: no entrance in the scene it continues into, no exit before the cut."""
    look: dict = {}
    if line["t0"] < a - 0.02:
        look["enter"] = {"preset": "none", "duration": 0.05}
    if line["t1"] + 0.15 > b + 0.02:
        look["exit"] = {"preset": "none", "duration": 0.05}
    return look


def title_cue_count(template: str, fields: dict, start: float, length: float) -> int:
    builder = TITLE_BUILDERS.get(template)
    if builder is None:
        return 1
    try:
        return max(1, len(builder(fields, {"start": start, "duration": length, "width": 1920, "height": 1080})))
    except Exception:
        return 1


def scene_fingerprint(shot: dict, style: dict, stills: dict, score: dict, start: float, end: float) -> str:
    """Invalidate a rendered scene when its spec, window, or lyric timing changes on resume."""
    source = {"shot": shot, "style": style, "stills": stills, "lines": score.get("lines") or [],
              "start": round(float(start), 3), "end": round(float(end), 3)}
    return hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()[:16]


def contact_sheet_filter(duration: float) -> str:
    """Sample the whole song into the 24-cell review sheet, including its final card."""
    return f"fps={24 / max(duration, 1):.8f},scale=320:-1,tile=6x4"


def theme_colours(theme: str | None) -> dict:
    if not theme:
        return {}
    if theme not in OMARCHY_THEMES:
        raise ProductionError("invalid_spec", f"unknown theme {theme}")
    return OMARCHY_THEMES[theme]


def theme_lyric_style(theme: str | None) -> dict:
    """Default lyric look for an Omarchy theme: square mono plate in the theme's surface colour."""
    colours = theme_colours(theme)
    return {"color": colours["fg"], "font": "mono", "weight": 700,
            "box": {"kind": "solid", "color": colours["surface"], "opacity": 0.92, "padding": 0.5, "radius": 0}} if colours else {}


# ---------------------------------------------------------------- run
def failure_reason(status: dict) -> str:
    """One short line for the log and production.status: an OOM, the job error, or what the status said."""
    if status.get("oom_info"):
        return "out of GPU memory"
    error = status.get("error")
    if isinstance(error, dict):
        error = error.get("message") or error.get("text") or json.dumps(error)
    text = str(error or status.get("message") or status.get("status") or "no output")
    return " ".join(text.split())[:120]


def note_held(state: dict, key: str, hold: bool = True) -> None:
    """Record or clear a shot whose scene plays its start frame instead of a clip."""
    if hold:
        held = state.setdefault("held", [])
        if key not in held:
            held.append(key)
        return
    held = state.get("held")
    if held and key in held:
        held.remove(key)


class Production:
    on_landed: Callable[[str, str | None], None] | None = None      # set while a round of clips is being waited for

    def __init__(self, workspace: str, production_id: str, *, workspace_dir: Callable[[str], str], uploads_dir: Callable[[], str],
                 mcp: Callable[[str, dict], dict]):
        self.ws, self.id = workspace, production_id
        self.root = Path(workspace_dir(workspace))
        self.uploads = Path(uploads_dir())
        self.path = self.root / f"{production_id}.production.json"
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.mcp = attach_usage(guard_mcp(self, mcp), self.state, self.save)
        self.lost: set[str] = set()

    # state
    def save(self) -> None:
        from services.production_state import allow_save
        if not allow_save(self.path, self.state):
            return
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False))
        tmp.replace(self.path)

    def _unlocked(self, windows: list[dict], retake: tuple[str, ...] = ()) -> list[dict]:
        from services.production_shot_review import unlocked_windows
        return unlocked_windows(self, windows, retake)

    def log(self, line: str) -> None:
        self.state.setdefault("log", []).append(line[:200])
        self.state["log"] = self.state["log"][-60:]
        self.save()

    def note_stop(self, error: BaseException) -> None:
        """A cooperative cancel stays resumable. Anything else is a failed run with its reason."""
        if isinstance(error, Cancelled):
            self.state.update(status="cancelled", error=None)
            return
        self.state.update(status="failed", error=f"{type(error).__name__}: {error}"[:300])

    # media helpers
    def upload(self, name: str) -> tuple[str, str]:
        """Copy a workspace file into uploads; returns (path, url) as /api/v1/upload would."""
        src = self.root / name
        target = self.uploads / f"{uuid.uuid4().hex}{src.suffix.lower()}"
        self.uploads.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        return str(target), f"/api/v1/uploads/{target.name}"

    def wait(self, jobs: dict[str, str | None], poll: float = 6) -> dict[str, str | None]:
        """Output file per key, or None. Why a job gave nothing is kept in self.failures[key]."""
        done: dict[str, str | None] = {}
        self.failures: dict[str, str] = {}
        self.lost = set()
        unknown: dict[str, int] = {}
        while len(done) < len(jobs):
            for key, job in jobs.items():
                if key in done:
                    continue
                if not job:
                    done[key], self.failures[key] = None, "not admitted"
                    continue
                s = self.mcp("status", {"job_id": job})
                if s.get("status") == "completed":
                    done[key] = (s.get("output_files") or [None])[0]
                    from services.production_perf import remember_performance
                    remember_performance(getattr(self, "state", None), key, s)
                elif s.get("status") is None:            # a status hiccup is not a lost job yet
                    unknown[key] = unknown.get(key, 0) + 1
                    if unknown[key] >= 5:
                        done[key] = None
                        self.lost.add(key)      # the queue no longer knows this job (a restart drops the queue)
                elif s.get("status") in ("failed", "error", "cancelled", "discarded"):
                    done[key] = None
                if key in done and not done[key]:
                    self.failures[key] = failure_reason(s)
                if key in done and self.on_landed:
                    self.on_landed(key, done[key])      # each result is recorded the moment it lands, not when the slowest one does
            if len(done) < len(jobs):
                sleep_until(getattr(self, "_cancel", None), poll, time.sleep)
        return done

    def image(self, key: str, prompt: str, refs: list[str] | None, res: str, seed: int,
              model: str = "flux2_klein_9b", steps: int | None = None, attempt: int = 0) -> str | None:
        params = {"prompt": prompt, "model_type": model, "resolution": res, "seed": seed, "guidance_scale": 1,
                  "num_inference_steps": steps or (40 if model.startswith("qwen_image_21") else 4)}
        if refs:
            params.update(image_refs=refs, video_prompt_type="I")
        r = self.mcp("generation.image", {"version": 2, "intent_id": f"{self.id}-{key}-{seed}" + (f"-r{attempt}" if attempt else ""),
                                                 "input": {"workspace": self.ws, "params": params}})       # the journal answers a repeated intent with the old (maybe failed) job
        return ((r.get("receipt") or {}).get("result") or {}).get("job_id")

    # steps
    def song(self, spec: dict) -> None:
        from services.production_song import generate_song
        generate_song(self, spec)

    def analyze(self, spec: dict) -> None:
        from services.production_song import analyze_song
        analyze_song(self, spec)

    def score(self) -> dict:
        return json.loads((self.root / self.state["score"]).read_text())

    def cast(self, spec: dict) -> None:
        cast = self.state.setdefault("cast", {})
        settings = spec.get("style") or {}
        style = settings.get("image", "")
        jobs = {c["id"]: self.image("cast-" + c["id"], c["sheet_prompt"] if style in c["sheet_prompt"] else f"{c['sheet_prompt']} {style}".strip(), None, "1536x1024", c.get("seed", 5),
                                     c.get("image_model", settings.get("image_model", "flux2_klein_9b")), c.get("image_steps", settings.get("image_steps")),
                                     self._attempt("cast_attempts", c["id"]))
                for c in spec.get("cast") or [] if c["id"] not in cast and not c.get("group")}
        for cid, name in self.wait(jobs).items():
            if name:
                cast[cid] = self.upload(name)[1]
        from services.production_cast_portrait import ensure_portraits, group_sources
        ensure_portraits(self, spec)
        for c in spec.get("cast") or []:      # a group reference: the members' portraits side by side in one picture
            members = c.get("group") or []
            if members and c["id"] not in cast and all(member in cast for member in members):
                out = f"{self.id}-group-{c['id']}.png"
                if compose_group(group_sources(self, members), self.root / out):
                    cast[c["id"]] = self.upload(out)[1]
        self.log(f"cast: {len(cast)}")
        absent = [c["id"] for c in spec.get("cast") or [] if c["id"] not in cast]
        if absent:
            raise ProductionError("cast_incomplete", "no reference sheet for " + ", ".join(f"{cid} ({self.failures.get(cid, 'no output')})" for cid in absent))

    def _attempt(self, group: str, key: str) -> int:
        """How many times this image was already submitted, so a resume asks for a fresh job instead of the journal's old answer."""
        counts = self.state.setdefault(group, {})
        if key not in counts:
            counts[key] = 1 if any(line.startswith(("frames:", "cast:")) for line in self.state.get("log") or []) else 0
            return counts[key]
        counts[key] += 1
        return counts[key]

    def frame_prompt(self, spec: dict, w: dict) -> str:
        """Start-frame prompt: the look, the shot, and how many distinct subjects the cast references stand for
        (a model given a sheet with several views tends to draw the character several times)."""
        style = (spec.get("style") or {}).get("image", "")
        counts = {c["id"]: int(c.get("count", len(c.get("group") or []) or 1)) for c in spec.get("cast") or [] if isinstance(c, dict)}
        subjects = sum(counts.get(c, 1) for c in w.get("cast", []) if c in self.state.get("cast", {}))
        guard = f" Exactly {subjects} distinct {'subject' if subjects == 1 else 'subjects'} in the frame, no duplicated characters." if subjects else ""
        return f"{style} {w['frame']}{guard}".strip()

    def frames(self, spec: dict, windows: list[dict]) -> None:
        """One start frame per H3 shot. A missing frame is asked for again (new job; a smaller picture after an
        out-of-memory) up to FRAME_ATTEMPTS times; what still fails is reported in ``frame_failures``."""
        windows = self._unlocked(windows)
        frames = self.state.setdefault("frames", {})
        failures = self.state.setdefault("frame_failures", {})
        settings = spec.get("style") or {}
        for _round in range(FRAME_ATTEMPTS):
            missing = [w for w in windows if w["kind"] == "h3" and w["key"] not in frames]
            if not missing:
                break
            from services.production_cast_portrait import frame_references
            from services.production_resolution import frame_resolution
            jobs = {}
            for w in missing:
                attempt = self._attempt("frame_attempts", w["key"])
                res = frame_resolution(spec, attempt, failures.get(w["key"], ""))
                refs = frame_references(w, self.state.get("cast") or {}, self.state.get("cast_single") or {})
                jobs[w["key"]] = self.image("frame-" + w["key"], self.frame_prompt(spec, w), refs or None, res, w.get("seed", 3) + (attempt or 0),
                                            w.get("image_model", settings.get("image_model", "flux2_klein_9b")), w.get("image_steps", settings.get("image_steps")), attempt)
            for key, name in self.wait(jobs).items():
                if name:
                    frames[key] = name
                    failures.pop(key, None)
                else:
                    failures[key] = self.failures.get(key, "no output")
                    self.log(f"frame {key} failed ({failures[key]})")
            self.save()
        self.log(f"frames: {len(frames)}")
        self.state["frames_sheet"] = make_frames_sheet(self.root, frames, f"{self.id}-frames.jpg")
        from services.production_subject_count import note_media
        note_media(self, spec, windows, "frame")
        absent = [w["key"] for w in windows if w["kind"] == "h3" and w["key"] not in frames]
        if absent:
            raise ProductionError("frames_incomplete", "no start frame for " + ", ".join(f"{key} ({failures.get(key, 'no output')})" for key in absent[:6]))

    def preview(self, request: dict) -> None:
        """Generate three look tests before committing GPU time to a song or clips."""
        self._cancel = arm(self.ws, self.id)
        self.state.update(status="running", preview_frames={})
        self.save()
        try:
            model = request.get("image_model", "flux2_klein_9b")
            jobs = {str(index): self.image(f"preview-{index}", prompt, None, request.get("resolution", "1280x704"),
                                           (request.get("seeds") or [101, 102, 103])[index], model,
                                           request.get("image_steps"))
                    for index, prompt in enumerate(request["prompts"])}
            self.state["preview_frames"] = {key: self.upload(name)[1] for key, name in self.wait(jobs).items() if name}
            self.state["status"] = "preview_completed" if len(self.state["preview_frames"]) == 3 else "failed"
            self.log(f"preview: {len(self.state['preview_frames'])}/3")
        except Exception as error:
            self.note_stop(error)
        disarm(self.ws, self.id)
        self.state["finished"] = time.time()
        self.save()

    def clip_job(self, spec: dict, w: dict, seed: int, take: int = 0) -> str | None:
        """Retakes change strategy, not only the seed: even takes are driven by the full mix (best on the
        pilot, r 0.41 vs 0.16), odd takes by the isolated vocals for songs whose mix drowns the voice."""
        frames = h3_frames_for(w["t1"] - w["t0"])
        vocals = self.score().get("vocals_file")
        source = vocals if take % 2 == 1 and vocals and w.get("sing") else self.state["song"]["file"]
        slice_name = f"{self.id}-slice-{w['key']}-{take}.wav"
        import subprocess
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(w["t0"]), "-t", str(frames / 24), "-i", str(self.root / source),
                        "-ar", "48000", "-ac", "2", str(self.root / slice_name)], check=True)
        discard(self.state, slice_name)
        sing = " (S1) sings the lead vocal of the mapped driving audio, lips, jaw and breath in precise sync with every syllable." if w.get("sing") else ""
        prompt = (f"integrated_multimodal_description: [Shot 1] {(spec.get('style') or {}).get('video', '')} {w['action']}{sing}\n"
                  "overall_soundscape: The mapped driving audio: the song.\nnon_diegetic_music: N/A")
        from services.production_resolution import clip_resolution
        params = {"prompt": prompt, "model_type": "minimax_h3_fused_turbo", "resolution": clip_resolution(spec), "seed": seed, "generation_mode": "video",
                  "workspace": self.ws, "image_prompt_type": "S", "image_start": self.upload(self.state["frames"][w["key"]])[0],
                  "video_length": frames, "sliding_window_size": frames, "num_inference_steps": 4, "guidance_scale": 1, "image_mode": 0,
                  "input_video_strength": 1.0, "audio_prompt_type": "A", "audio_guide": self.upload(slice_name)[0]}
        # a resumed run must not collide with the journal entry of an earlier take
        r = self.mcp("generate", {"request_id": f"{self.id}-{w['key']}-{seed}-{uuid.uuid4().hex[:8]}", "params": params})
        job = r.get("job_id") or (r.get("result") or {}).get("job_id")
        if not job:
            self.log(f"clip {w['key']} not admitted: {json.dumps(r)[:140]}")
        return job

    def clips(self, spec: dict, windows: list[dict], retake: tuple[str, ...] = (), pause: float = 60) -> None:
        """Shoot missing clips (or retake keys). Flat lip-sync r, max_takes, or 4 recorded takes stop an automatic
        shoot; an explicit retake may pass the cap. The best r is kept. A fully failed round waits before the next."""
        windows = self._unlocked(windows, retake)
        self.state.setdefault("clips", {})
        tried = self.state.setdefault("clip_takes", {})
        max_takes = int(spec.get("max_takes", 3))
        vocals = self.score().get("vocals_file")
        # A song switch leaves files on disk and flags the shot. Treat those keys
        # like an explicit retake so the new window can spend max_takes again.
        stale = tuple(key for key, clip in self.state["clips"].items() if obsolete_clip(clip))
        retake = tuple(dict.fromkeys((*retake, *stale)))
        pending = pending_windows(windows, self.state, retake)
        for w in pending:          # productions saved before clip_takes existed: count their logged takes
            tried.setdefault(w["key"], sum(1 for line in self.state.get("log") or [] if line.startswith(f"clip {w['key']} take ")))
        budget = {w["key"]: tried[w["key"]] + max_takes for w in pending}
        while pending:
            checkpoint(getattr(self, "_cancel", None))
            started = time.perf_counter()
            by_key = {w["key"]: w for w in pending}
            retry_keys: set[str] = set()
            landed: set[str] = set()
            lost = self.state.setdefault("clip_lost", {})

            def land(key: str, name: str | None) -> None:
                """Judge and record one clip as soon as it exists: a restart mid-round keeps the ones already shot."""
                if key in landed:
                    return
                landed.add(key)
                if key in self.lost and lost.get(key, 0) < MAX_LOST_JOBS:
                    lost[key] = lost.get(key, 0) + 1      # not a take: the job vanished, so shoot it again
                    self.log(f"clip {key}: job lost (queue restarted), not counted as a take")
                    retry_keys.add(key)
                    return
                tried[key] += 1
                if another_take(self.judge_take(by_key[key], name, tried[key], vocals), tried[key], budget[key], key in retake):
                    retry_keys.add(key)
                self.save()

            self.on_landed = land
            try:
                names = self.wait({w["key"]: self.clip_job(spec, w, 7000 + w["i"] * 10 + tried[w["key"]], tried[w["key"]]) for w in pending})
            finally:
                self.on_landed = None
            for w in pending:
                land(w["key"], names.get(w["key"]))         # a wait that reports only at the end (a stub) lands them here
            retry = [w for w in pending if w["key"] in retry_keys]
            note_seconds(self.state, pending, time.perf_counter() - started)
            self.save()
            if retry and not any(names.values()):
                sleep_until(getattr(self, "_cancel", None), pause, time.sleep)
            pending = retry
        from services.production_subject_count import note_media
        note_media(self, spec, windows, "clip")
        from services.production_smoothness import note_outputs
        note_outputs(self, "clip")

    def judge_take(self, w: dict, name: str | None, take: int, vocals: str | None) -> bool:
        """Record one take; True when the clip needs no more takes. Sung shots keep the best lip-sync r; other shots keep the best visual score."""
        key, failed, clips = w["key"], self.state.setdefault("clip_failures", {}), self.state.setdefault("clips", {})
        if not name:
            failed[key] = self.failures.get(key, "no output")
            self.log(f"clip {key} take {take}: failed ({failed[key]})")
            return False
        failed.pop(key, None)
        from services.production_clip_qa import clip_qa
        qa = clip_qa(str(self.root / name), bool(w.get("sing")), str(self.root / vocals) if vocals else None, w["t0"], w["t1"])
        drive = "vocals" if (take - 1) % 2 == 1 and w.get("sing") else "mix"
        self.log(f"clip {key} take {take} ({drive}): {qa.get('verdict')} r={qa.get('best_r')}")
        self.state.setdefault("takes", {}).setdefault(key, []).append(
            {"file": name, "take": take, "verdict": qa.get("verdict"), "r": qa.get("best_r"), "drive": drive})
        best = clips.get(key)
        # Obsolete r was measured on the previous song; ranking it would keep the
        # old take and throw away the clip shot against the new window.
        ranking = None if obsolete_clip(best) else best
        previous = (ranking.get("qa") or {}).get("best_r") if ranking else None
        if not ranking or better_take(qa, (ranking.get("qa") or {})):
            if ranking and ranking.get("file") and ranking["file"] != name:
                discard(self.state, ranking["file"])
            clips[key] = {"file": name, "qa": qa, "url": self.upload(name)[1]}
        else:
            discard(self.state, name)
        return take_settled(qa, previous)

    def scenes(self, spec: dict, windows: list[dict]) -> None:
        score = self.score()
        from services.production_preview import ensure_caption_contrast
        ensure_caption_contrast(self, spec, windows, score)
        clips = self.state.get("clips", {})
        segs = segments(windows, score, lambda k: k in clips, spec.get("fill") or [])
        self.state["segments"] = [[s["key"], a, b] for s, a, b in segs]
        done = self.state.setdefault("scenes", {})
        style, stills = spec.get("style") or {}, spec.get("stills") or {}
        docs: dict[str, dict] = {}
        from services.production_shot_review import is_locked
        for shot, a, b in segs:
            if is_locked(self, shot["key"]):
                continue
            dur = round(b - a, 3)
            used = (clips.get(shot["key"]) or (clips.get(shot.get("clip")) if shot["kind"] == "clip" else None) or {}).get("file")
            prior = done.get(shot["key"], {})
            fingerprint = scene_fingerprint(shot, style, stills, score, a, b)
            if (prior.get("dur") == dur and prior.get("file") and prior.get("clip") == used
                    and prior.get("fingerprint") == fingerprint):
                continue
            doc = self.scene_document(shot, a, b, score, clips, style, stills)
            docs[shot["key"]] = doc
            r = self.mcp("scenes.video2d.export", {"version": 1, "intent_id": f"{self.id}-scene-{shot['key']}-{int(time.time())}",
                                                   "input": {"workspace": self.ws, "document": doc}})
            done[shot["key"]] = {"intent": (r.get("receipt") or {}).get("commandId"), "dur": dur, "clip": used,
                                  "fingerprint": fingerprint, "file": None}
            self.save()
        failed = finish_scene_exports(
            self.mcp, self.ws, self.id, done, docs,
            lambda seconds: sleep_until(getattr(self, "_cancel", None), seconds, time.sleep), self.save, self.log)
        apply_scene_export_failure(self.state, failed)
        self.log(f"scenes: {sum(1 for s in done.values() if s.get('file'))}/{len(segs)}")
        from services.production_smoothness import note_outputs
        note_outputs(self, "scene")

    def scene_document(self, shot: dict, a: float, b: float, score: dict, clips: dict, style: dict, stills: dict) -> dict:
        shot, style = render_shot(shot, style)
        dur = round(b - a, 3)
        doc = {"version": 1, "name": shot["key"], "width": 1920, "height": 1080, "fps": 24, "duration": dur, "layers": [], "texts": []}
        return self.edit(doc, self.scene_ops(shot, a, b, dur, score, clips, style, stills))

    def package(self, spec: dict, windows: list[dict]) -> None:
        """Save what a person needs to retouch the video shot by shot: a durable scene document per shot and a manifest
        (see production_package). Never fails the run: the video is already made."""
        score, clips = self.score(), self.state.get("clips", {})
        segs = segments(windows, score, lambda k: k in clips, spec.get("fill") or [])
        style, stills = spec.get("style") or {}, spec.get("stills") or {}
        swap, saved = clip_replacements(clips, self.ws), self.state.setdefault("scene_docs", {})
        for shot, a, b in segs:
            key = shot["key"]
            try:
                doc = durable_document(self.scene_document(shot, a, b, score, clips, style, stills), swap)
                digest = doc_digest(doc)
                if (saved.get(key) or {}).get("digest") == digest:
                    continue
                result = self.mcp("scenes.document.save", {"version": 1, "intent_id": f"{self.id}-doc-{key}-{digest}",
                                                           "input": {"workspace": self.ws, "name": f"{self.id}-{key}", "document": doc}})
                name = (result.get("result") or {}).get("name")
                if not name:
                    raise ProductionError("scene_doc_failed", json.dumps(result)[:160])
                note = " · ".join(part for part in (shot.get("action"), f"seed {shot['seed']}" if shot.get("seed") is not None else "") if part)
                saved[key] = {"scene": name, "digest": digest, "lyric": lyric_for(score.get("lines") or [], a, b), "note": note,
                              "warnings": contrast_warnings(self.mcp, doc)}
            except Exception as error:      # one shot's document must not stop the others
                self.log(f"package {key}: {type(error).__name__}: {error}"[:200])
        manifest = write_manifest(self.root, self.id, spec.get("title", self.id), manifest_rows(self.state, spec, segs, score, saved),
                                  self.state.get("montage_file"))
        self.state["package"] = {"manifest": manifest, "scene_docs": len(saved),
                                 "warnings": sum(len(item.get("warnings") or []) for item in saved.values())}
        self.log(f"package: {len(saved)} scene documents, manifest {manifest}")

    def _finish_package(self, previous: str | None, previous_error: object, package_error: str | None) -> None:
        """Restore the finished status. A leftover final is not success, and this must never look running:
        auto-resume would start a full GPU production.run."""
        if package_error:
            self.state["error"] = package_error
            self.state["status"] = previous if previous in ("completed", "failed") else "failed"
        elif previous == "failed":
            self.state["status"] = "failed"
            self.state["error"] = previous_error
        elif self.state.get("final"):
            self.state.update(status="completed", error=None)
        else:
            self.state["status"] = "failed"
            if previous_error:
                self.state["error"] = previous_error
        self.state["finished"] = time.time()
        self.save()

    def repackage(self, spec: dict) -> None:
        """Package a production that is already finished (no GPU, no export): scene documents, manifest and the
        montage clips' origins. This is how an older production becomes editable."""
        previous, previous_error = self.state.get("status"), self.state.get("error")
        try:
            windows = shot_windows(spec, self.score())
            self.package(spec, windows)
            file = self.state.get("montage_file")
            if file:
                current = (self.mcp("montages.get", {"version": 1, "input": {"workspace": self.ws, "file": file}}).get("result") or {})
                montage = current.get("montage") or current
                if attach_origins(montage, self.state.get("scene_docs") or {}, self.id) and montage.get("clips"):
                    revision = current.get("revision") or montage.get("revision")
                    saved = self.mcp("montages.save", {"version": 1, "intent_id": f"{self.id}-origins-{int(time.time())}",
                                                       "input": {"workspace": self.ws, "montage": montage, "file": file, "expected_revision": revision}})
                    if "result" not in saved:
                        raise ProductionError("montage_failed", json.dumps(saved)[:200])
        except Exception as error:
            self._finish_package(previous, previous_error, f"{type(error).__name__}: {error}"[:300])
            return
        self._finish_package(previous, previous_error, None)

    def edit(self, doc: dict, ops: list[dict]) -> dict:
        # scenes.video2d.edit admits 32 ops; a long still with timed lyrics exceeds that in one shot.
        for index in range(0, len(ops), MAX_OPERATIONS):
            chunk = ops[index:index + MAX_OPERATIONS]
            r = self.mcp("scenes.video2d.edit", {"version": 1, "input": {"document": doc, "operations": chunk, "full": True}})
            if "result" not in r:
                raise ProductionError("scene_edit_failed", json.dumps(r)[:300])
            doc = r["result"]["document"]
        return doc

    def scene_ops(self, shot: dict, a: float, b: float, dur: float, score: dict, clips: dict, style: dict, stills: dict) -> list[dict]:
        ops: list[dict] = []
        clip = clips.get(shot["key"]) or (clips.get(shot.get("clip")) if shot["kind"] == "clip" else None)
        if shot["kind"] == "scene3d" and not clip:
            raise ProductionError("scene3d_export_failed", f"scene3d clip missing: {shot['key']}")
        if clip:
            note_held(self.state, shot["key"], False)
            ops.append({"op": "add_layer", "id": "bg", "source": clip["url"], "type": "video", "preset": shot.get("camera", "camera-locked")})
            skip = round(max(0.0, a - shot.get("t0", a)) + ((clip.get("qa") or {}).get("suggested_sync_s") or 0), 3) if shot["kind"] == "h3" else 0
            # the animation duration is also the video span (sceneTimeline.getSceneLayerTiming): a camera preset's
            # shorter duration would freeze the clip mid-scene, so it always covers the scene (+ the skipped head)
            anim: dict[str, Any] = {"end": {"x": 50, "y": 50, "scale": 1.0, "rotation": 0},
                                    "duration": round(dur + skip, 3)}
            if skip > 0:
                anim["trimStart"] = skip
            ops.append({"op": "update_layer", "id": "bg", "patch": {"fill": True, "animation": anim}})
        elif shot["kind"] == "screen":
            desktop = {"theme": style.get("theme") or "tokyo-night", "layout": "triple", "apps": "mixed", "focus": "0", "workspace": "1",
                       "switch": "none", **{k: str(v) for k, v in (shot.get("desktop") or {}).items()}}
            ops.append({"op": "add_title", "id": "desk", "template": "desktop", "fields": desktop, "start": 0, "duration": dur})
        else:
            zoom = shot.get("zoom") or [1.0, 1.1]
            source = stills.get(shot.get("still"), shot.get("still"))
            if not source and shot["kind"] == "h3" and shot["key"] in self.state.get("frames", {}):
                source = self.upload(self.state["frames"][shot["key"]])[1]      # clip failed: hold its start frame
                note_held(self.state, shot["key"])
            ops += [{"op": "add_layer", "id": "bg", "source": source, "type": "image", "preset": shot.get("camera", "camera-push-in")},
                    {"op": "update_layer", "id": "bg", "patch": {"fill": True, "focus": shot.get("focus", {"x": 50, "y": 50}), "animation": {
                        "start": {"x": 50, "y": 50, "scale": zoom[0], "rotation": 0}, "end": {"x": 50, "y": 50, "scale": zoom[1], "rotation": 0}}}}]
        title_ops, used = self._title_ops(shot, dur, style)
        ops.extend(title_ops)
        ops.extend(self._lyric_ops(shot, a, b, dur, score, style, used))
        ops.extend(self._footer_ops(dur, style))
        if style.get("finish"):
            ops.append({"op": "set_finish", **style["finish"]})
        return ops

    @staticmethod
    def _title_ops(shot: dict, dur: float, style: dict) -> tuple[list[dict], int]:
        from services.production_scene_ops import title_ops
        return title_ops(shot, dur, style)

    def _lyric_ops(self, shot: dict, a: float, b: float, dur: float, score: dict, style: dict, used: int) -> list[dict]:
        from services.production_scene_ops import lyric_ops
        return lyric_ops(self.log, shot, a, b, dur, score, style, used)

    @staticmethod
    def _footer_ops(dur: float, style: dict) -> list[dict]:
        from services.production_scene_ops import footer_ops
        return footer_ops(dur, style)

    def montage(self, spec: dict) -> None:
        if skip_montage(self.state):
            return
        score, scenes = self.score(), self.state["scenes"]
        clips = [{"id": k, "name": k, "source": f"/api/v1/file/{scenes[k]['file']}?workspace={self.ws}", "trimStart": 0, "trimEnd": scenes[k]["dur"],
                  "muted": True, "fit": "fill", "transition": "none"} for k, _, _ in self.state["segments"] if scenes.get(k, {}).get("file")]
        montage = {"version": 1, "name": spec["title"], "width": 1920, "height": 1080, "fps": 24, "clips": clips, "audioCues": [], "overlays": [],
                   "soundtrack": {"source": f"/api/v1/file/{self.state['song']['file']}?workspace={self.ws}", "trimStart": 0, "trimEnd": score["duration"], "volume": 1.0, "loop": False}}
        attach_origins(montage, self.state.get("scene_docs") or {}, self.id)
        montage = attach_trailer_audio(self, spec, montage)
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
            # montages.export queues a Video Editor job. cancelled is terminal there
            # (user cancel or resource scheduler); polling only completed/failed hangs.
            if status.get("status") in ("completed", "failed", "cancelled", "discarded", "error"):
                break
            sleep_until(getattr(self, "_cancel", None), 4, time.sleep)
        # start_export pre-fills filename when the job is created. A failed
        # render still carries that planned name; only a completed export is a video.
        if not isinstance(status, dict) or status.get("status") != "completed" or not status.get("filename"):
            raise ProductionError("montage_failed", failure_reason(status) if isinstance(status, dict) else "export job lost")
        self.state["final"] = status["filename"]
        if self.state["final"]:
            import subprocess
            sheet = f"{self.id}-contact.jpg"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(self.root / self.state["final"]), "-vf", contact_sheet_filter(score["duration"]),
                            "-frames:v", "1", str(self.root / sheet)])
            self.state["contact_sheet"] = sheet
        from services.production_smoothness import note_outputs
        note_outputs(self, "final")
        self.log(f"montage: {status.get('status')}")

    def animatic(self, spec: dict, windows: list[dict]) -> None:
        """CPU preview from the start frames. A new export is stored apart from ``final``."""
        from services.production_preview import (
            animatic_report, claim_animatic_video, completed_cut_final,
            restore_cut_artifacts, snapshot_cut_artifacts,
        )
        previous = completed_cut_final(self.state)
        kept = snapshot_cut_artifacts(self.root, self.state)
        self.state["animatic_warnings"] = animatic_report(spec, windows, self.score(), self.state)
        self.state["caption_gate"] = "warn"
        try:
            self.scenes(spec, windows)
            self.montage(spec)
        finally:
            self.state.pop("caption_gate", None)
            restore_cut_artifacts(self.root, self.state, kept)
            claim_animatic_video(self.state, previous if isinstance(previous, str) else None)

    def run(self, spec: dict, retake: tuple[str, ...] = (), through: str = "all") -> None:
        self._cancel = arm(self.ws, self.id)
        prior_status = self.state.get("status")
        from services.production_preview import keep_completed_cut, remember_completed_cut
        remember_completed_cut(self.state, prior_status, through)
        self.state.update(spec=spec, status="running", started=self.state.get("started") or time.time(), through=through)
        from services.production_close import note_resume
        note_resume(self)
        self.save()
        try:
            checkpoint(self._cancel)
            from services.production_preview import log_title_cards
            log_title_cards(self, spec)
            watch = StageWatch(self)
            watch.call("song", self.song, spec)
            watch.call("analyze", self.analyze, spec)
            watch.call("cast", self.cast, spec)
            windows = shot_windows(spec, self.score())
            watch.call("frames", self.frames, spec, windows)
            if through == "frames":
                self.state["status"] = "frames_ready"
                self.log("frames: ready for a clean restart before clips")
                return
            if through == "animatic":
                try:
                    self.animatic(spec, windows)
                except Exception as error:
                    if isinstance(error, Cancelled) or not keep_completed_cut(self.state, prior_status):
                        raise
                    self.log(f"animatic failed: {type(error).__name__}: {error}"[:200])
                if keep_completed_cut(self.state, prior_status):
                    self.state.update(status="completed", error=None)
                elif self.state.get("status") != "failed":
                    self.state["status"] = "animatic_ready"
                    self.log("animatic: ready; a resume continues with clips")
                return
            watch.call("clips", self.clips, spec, windows, retake)
            if any(s.get("kind") == "scene3d" for s in [*spec["shots"], *(spec.get("fill") or [])]):
                watch.call("clips", export_scene3d_clips, self, spec, windows, retake)
            from services.production_enhance import enhance_clips
            enhance_clips(self, spec)
            watch.call("scenes", self.scenes, spec, windows)
            try:
                self.package(spec, windows)
            except Exception as error:      # the video is made; editability is a bonus that must not fail the run
                self.log(f"package failed: {type(error).__name__}: {error}"[:200])
            watch.call("montage", self.montage, spec)
            self.state["package"] = {**(self.state.get("package") or {}), "montage": self.state.get("montage_file")}
            # A leftover final from a previous completed run is not success: scene
            # export can fail, skip montage, and still leave that filename in state.
            if self.state.get("status") != "failed" and self.state.get("final"):
                self.state.update(status="completed", error=None)
            elif self.state.get("status") != "failed":
                self.state["status"] = "failed"
        except Exception as error:  # the run is resumable; a cancel keeps the files and the spec
            self.note_stop(error)
        finally:
            disarm(self.ws, self.id)
            self.state["finished"] = time.time()
            from services.production_close import close_run
            close_run(self, retake)
            release_completed(self.root, self.state, self.id)
            self.save()


def status_summary(state: dict, workspace: str, root: str | None = None, production_id: str | None = None) -> dict[str, Any]:
    url = lambda name: f"/api/v1/file/{name}?workspace={workspace}" if name else None
    clips = state.get("clips") or {}
    summary = {"status": state.get("status", "unknown"), "error": state.get("error"),
            "song": (state.get("song") or {}).get("file"),
            "clips": {**{k: "failed" for k in state.get("clip_failures") or {}}, **{k: (v.get("qa") or {}).get("verdict") for k, v in clips.items()}},
            "failures": state.get("clip_failures") or None,
            "frame_failures": state.get("frame_failures") or None,
            "frames_sheet": url(state.get("frames_sheet")),
            "held": list(state.get("held", [])),
            "preview_frames": state.get("preview_frames") or None,
            "frames_ready": len(state.get("frames") or {}),
            "scenes": sum(1 for s in (state.get("scenes") or {}).values() if s.get("file")),
            "video": url(state.get("final")), "animatic": url(state.get("animatic_video")),
            "animatic_warnings": state.get("animatic_warnings") or None,
            "contact_sheet": url(state.get("contact_sheet")), "log": (state.get("log") or [])[-8:],
            "timing": timing_summary(state), "usage": usage_summary(state), "editable": editable_summary(state)}
    from services.production_subject_count import mismatches
    counted = mismatches(state)
    if counted:
        summary["subject_counts"] = counted
    from services.production_smoothness import for_status
    smooth = for_status(state)
    if smooth:
        summary["smoothness"] = smooth
    summary.update(review_for_status(state, root))
    from services.production_progress import progress_summary
    summary["progress"] = progress_summary(state, root)
    from services.production_shot_review import apply_artistic
    apply_artistic(summary, root, production_id)
    return summary


# ---------------------------------------------------------------- MCP
def command_catalog() -> list[dict[str, Any]]:
    from services.production_shot_commands import review_catalog
    envelope = lambda props, required: {"type": "object", "additionalProperties": False, "required": ["version", "input"], "properties": {
        "version": {"type": "integer", "const": 1},
        "input": {"type": "object", "additionalProperties": False, "required": required, "properties": props}}}
    ws = {"type": "string", "minLength": 1, "maxLength": 120}
    pid = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"}
    return publication_catalog() + [
        {"name": RUN, "description": ("Produce a music video from one spec, in the background: K song candidates (best lyric recall, no cut "
                                      "ending), analysis, cast sheets, start frames, H3 clips driven by the exact song slice with automatic "
                                      "lip-sync retakes, one Video 2D scene per shot with timed lyric captions, instrumental gaps filled on bar "
                                      "lines, montage and export. Pass spec to start; pass only production_id to resume (missing clips are retried "
                                      "and their scenes re-exported); retake lists clip keys to shoot again, keeping the better take. "
                                      "Returns immediately; "
                                      "poll production.status. dry_run checks the spec before any GPU work. "
                                      "through frames stops after the start frames (frames_ready); through animatic builds a CPU preview "
                                      "from those frames (animatic_ready) and a later run continues at the clips. "
                                      "See docs/agents/VIDEO_PRODUCTION_RUNBOOK.md."),
         "inputSchema": envelope({"workspace": ws, "production_id": pid, "spec": SPEC_SCHEMA,
                                          "retake": {"type": "array", "items": {"type": "string", "maxLength": 80}, "maxItems": 20},
                                          "dry_run": {"type": "boolean"},
                                          "package": {"type": "boolean", "description": "true: make a finished production editable shot by shot (scene documents, manifest, montage origins) without any GPU or export"},
                                          "auto_resume": {"type": "boolean", "description": "true: after a server restart this production continues by itself (for 24 h). Off unless asked (or HOCUS_PRODUCTION_AUTORESUME=1)."},
                                          "through": {"enum": ["all", "frames", "animatic"]},
                                          "preview": {"type": "object", "required": ["prompts"], "properties": {
                                              "prompts": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "string"}},
                                              "image_model": {"type": "string"}, "image_steps": {"type": "integer"},
                                              "resolution": {"type": "string"},
                                              "seeds": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "integer"}}}}},
                                         ["workspace", "production_id"])},
        {"name": PLAN, "description": "Turn an eight-field brief into a spec that passes a dry run. Fields: tema, publico, duracion, musica, estilo, protagonista, cta, limites, plus lyrics (required: the plan does not write them) and an optional footer (small print on every scene).",
         "inputSchema": envelope({"brief": {"type": "object"}}, ["brief"])},
        {"name": STATUS, "description": "Short summary of a production: status, progress, stage timings, usage (mcp_calls, response_bytes, h3_takes, gpu_seconds, cpu_seconds, retry_seconds, reused_seconds), per-clip lip-sync verdicts, video and contact-sheet URLs, code review (execution, technical, artistic, retake_keys), last log lines. wait_s blocks until the chosen until condition or the wait elapses. A client may still poll at 300 s; the server accepts up to 1200 s.",
         "inputSchema": envelope({"workspace": ws, "production_id": pid,
                                  "wait_s": {"type": "integer", "minimum": 0, "maximum": MAX_WAIT_S, "default": 0,
                                             "description": "Seconds to wait. 0 returns at once. Maximum 1200. 300 remains a safe client poll."},
                                  "until": {"enum": ["change", "stage", "done"], "default": "change",
                                            "description": "change: status value changes. stage: status or stage name changes. done: completed, failed, or cancelled."}},
                                 ["workspace", "production_id"])},
        *extra_catalog(),
        *review_catalog(),
    ]


def loopback_mcp(app_url: Callable[[], str], token: Callable[[], str], sleep: Callable[[float], None] = time.sleep) -> Callable[[str, dict], dict]:
    def call(tool: str, arguments: dict) -> dict:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}).encode()
        request = urllib.request.Request(app_url().rstrip("/") + "/api/v1/mcp", data=body, method="POST", headers={
            "Authorization": f"Bearer {token()}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        with open_mcp(request, timeout=600, sleep=sleep) as response:
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
        if data.get("dry_run") is True:
            from services.production_dry_run import dry_run
            return {"version": 1, "status": "completed", "operation": RUN, "result": dry_run(data.get("spec"), root=workspace_dir(data["workspace"]))}
        if not token() or not app_url():
            raise HTTPException(503, {"code": "mcp_unavailable", "message": "Enable MCP access so the production can call the studio tools", "retryable": False})
        key = f"{data['workspace']}/{data['production_id']}"
        with _lock:
            busy = _slot_busy(key)
        if busy:
            raise HTTPException(409, {"code": "already_running", "message": "This production is running: wait for production.status to finish (or use another production_id) before sending a new spec", "retryable": True})
        production = Production(data["workspace"], data["production_id"], workspace_dir=workspace_dir, uploads_dir=uploads_dir, mcp=loopback_mcp(app_url, token))
        if "auto_resume" in data:
            production.state["auto_resume"] = data["auto_resume"] is True
        preview = data.get("preview")
        if preview is not None:
            if (not isinstance(preview, dict) or not isinstance(preview.get("prompts"), list)
                    or len(preview["prompts"]) != 3 or any(not isinstance(p, str) or not p.strip() for p in preview["prompts"])
                    or ("seeds" in preview and (not isinstance(preview["seeds"], list) or len(preview["seeds"]) != 3))):
                raise HTTPException(422, {"code": "invalid_preview", "message": "preview needs three prompts and optionally three seeds", "retryable": False})
            target = production.preview
            args = (preview,)
        else:
            try:
                require_free_disk(production.root)
                spec = validate_spec(data.get("spec") or production.state.get("spec"))
            except ProductionError as error:
                raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": False}) from error
            through = data.get("through", "all")
            if through not in ("all", "frames", "animatic"):
                raise HTTPException(422, {"code": "invalid_stage", "message": "through must be all, frames or animatic", "retryable": False})
            if data.get("package") is True:
                if production.state.get("status") not in ("completed", "failed"):
                    raise HTTPException(422, {"code": "not_finished", "message": "package needs a finished production", "retryable": False})
                target, args = production.repackage, (spec,)
            else:
                target = production.run
                args = (spec, tuple(data.get("retake") or ()), through)
        with _lock:
            if _slot_busy(key):
                raise HTTPException(409, {"code": "already_running", "message": "This production is running", "retryable": True})
            thread = threading.Thread(target=target, args=args, name=f"production-{data['production_id']}", daemon=True)
            _threads[key] = thread
            thread.start()
        return {"version": 1, "status": "completed", "operation": RUN, "result": {"production_id": data["production_id"], "running": True}}

    async def status(arguments: Any) -> dict:
        data = _input(arguments)
        path = Path(workspace_dir(data["workspace"])) / f"{data['production_id']}.production.json"
        if not path.exists():
            raise HTTPException(404, {"code": "production_not_found", "message": "No production with this id in the workspace", "retryable": False})
        state = await wait_for_status(path, data.get("wait_s", 0), until=data.get("until"))
        waited = state.pop("waited_s", None) if isinstance(state, dict) else None
        summary = await asyncio.to_thread(status_summary, state, data["workspace"], str(path.parent), data["production_id"])    # the review opens video files
        if isinstance(waited, int):
            summary["waited_s"] = waited
        return {"version": 1, "status": "completed", "operation": STATUS, "result": summary}

    async def plan(arguments: Any) -> dict:
        from services.production_plan import PlanError, plan_brief
        data = (arguments or {}).get("input") if isinstance(arguments, dict) else None
        if not isinstance(data, dict):
            raise HTTPException(422, {"code": "invalid_command", "message": "Use version 1 with input.brief", "retryable": False})
        try:
            spec = plan_brief(data.get("brief"))
        except PlanError as error:
            raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": False}) from error
        return {"version": 1, "status": "completed", "operation": PLAN, "result": {"spec": spec}}

    from services.production_shot_commands import review_handlers
    return {RUN: run, STATUS: status, PLAN: plan, **extra_handlers(workspace_dir, uploads_dir, app_url, token), **publication_handlers(workspace_dir), **review_handlers(workspace_dir, uploads_dir, app_url, token)}
