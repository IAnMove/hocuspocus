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
import shutil
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

import numpy as np

from services import lipsync_qa, song_analysis as audio_analysis
from services.production_disk import require_free_disk
from services.production_publication import publication_catalog, publication_handlers
from services.production_resume import open_mcp
from services.production_resource_gate import guard_mcp
from services.production_shot_plan import plan_shots
from services.production_timing import StageWatch, timing_summary
from services.production_usage import attach_usage, usage_summary
from services.production_structure import require_direction
from services.production_quality import expand_quality
from services.production_review import review_for_status
from services.production_scene3d import export_scene3d_clips, validate_scene3d_shot
from services.production_style_presets import expand_style_preset
from services.production_commands import extra_catalog, extra_handlers
from services.production_control import Cancelled, sleep_until
from services.production_package import editable_summary
from services.production_sheets import compose_group, make_frames_sheet
from services.production_wait import MAX_WAIT_S, wait_for_status
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
    from services.production_windows import shot_windows as _shot_windows
    return _shot_windows(spec, score)


def segments(windows: list[dict], score: dict, clip_ok: Callable[[str], bool], fill: list[dict]) -> list[tuple[dict, float, float]]:
    """Scene cuts; an h3 shot longer than its clip is cut at the clip end and the rest filled on bar lines."""
    from services.production_windows import segments as _segments
    return _segments(windows, score, clip_ok, fill)


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
        # Remembered so release_uploads can drop the copy once the run is complete and nothing refers to it.
        self.state.setdefault("uploads", []).append(target.name)
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
        from services.production_stage_frames import cast_sheets
        cast_sheets(self, spec)

    def _attempt(self, group: str, key: str) -> int:
        from services.production_stage_frames import attempt_image
        return attempt_image(self, group, key)

    def frame_prompt(self, spec: dict, w: dict) -> str:
        from services.production_stage_frames import frame_prompt
        return frame_prompt(self, spec, w)

    def frames(self, spec: dict, windows: list[dict]) -> None:
        from services.production_stage_frames import shoot_frames
        shoot_frames(self, spec, windows)

    def preview(self, request: dict) -> None:
        from services.production_stage_frames import run_preview
        run_preview(self, request)


    def clip_job(self, spec: dict, w: dict, seed: int, take: int = 0) -> str | None:
        from services.production_stage_clips import submit_clip
        return submit_clip(self, spec, w, seed, take)

    def clips(self, spec: dict, windows: list[dict], retake: tuple[str, ...] = (), pause: float = 60) -> None:
        from services.production_stage_clips import shoot_clips
        shoot_clips(self, spec, windows, retake, pause)

    def judge_take(self, w: dict, name: str | None, take: int, vocals: str | None) -> bool:
        from services.production_stage_clips import judge_take
        return judge_take(self, w, name, take, vocals)


    def scenes(self, spec: dict, windows: list[dict]) -> None:
        from services.production_stage_scenes import export_scenes
        export_scenes(self, spec, windows)

    def scene_document(self, shot: dict, a: float, b: float, score: dict, clips: dict, style: dict, stills: dict) -> dict:
        from services.production_stage_scenes import scene_document
        return scene_document(self, shot, a, b, score, clips, style, stills)

    def package(self, spec: dict, windows: list[dict]) -> None:
        from services.production_stage_scenes import package_shots
        package_shots(self, spec, windows)

    def _finish_package(self, previous: str | None, previous_error: object, package_error: str | None) -> None:
        from services.production_stage_scenes import finish_package
        finish_package(self, previous, previous_error, package_error)

    def repackage(self, spec: dict) -> None:
        from services.production_stage_scenes import repackage
        repackage(self, spec)

    def edit(self, doc: dict, ops: list[dict]) -> dict:
        from services.production_stage_scenes import edit_document
        return edit_document(self, doc, ops)

    def scene_ops(self, shot: dict, a: float, b: float, dur: float, score: dict, clips: dict, style: dict, stills: dict) -> list[dict]:
        from services.production_stage_scenes import scene_layer_ops
        return scene_layer_ops(self, shot, a, b, dur, score, clips, style, stills)


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
        from services.production_stage_scenes import build_montage
        build_montage(self, spec)

    def animatic(self, spec: dict, windows: list[dict]) -> None:
        from services.production_stage_scenes import build_animatic
        build_animatic(self, spec, windows)

    def run(self, spec: dict, retake: tuple[str, ...] = (), through: str = "all") -> None:
        from services.production_stage_run import execute_run
        execute_run(self, spec, retake, through)



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
        {"name": RUN, "mutation": True, "description": ("Produce a music video from one spec, in the background: K song candidates (best lyric recall, no cut "
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
                                          "project": {"type": "object", "required": ["kind", "id"], "properties": {"kind": {"enum": ["story", "episode"]}, "id": {"type": "string"}}},
                                          "package": {"type": "boolean", "description": "true: make a finished production editable shot by shot (scene documents, manifest, montage origins) without any GPU or export"},
                                          "auto_resume": {"type": "boolean", "description": "true: after a server restart this production continues by itself (for 24 h). Off unless asked (or HOCUS_PRODUCTION_AUTORESUME=1)."},
                                          "through": {"enum": ["all", "frames", "animatic"]},
                                          "preview": {"type": "object", "required": ["prompts"], "properties": {
                                              "prompts": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "string"}},
                                              "image_model": {"type": "string"}, "image_steps": {"type": "integer"},
                                              "resolution": {"type": "string"},
                                              "seeds": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "integer"}}}}},
                                         ["workspace", "production_id"])},
        {"name": PLAN, "mutation": False, "description": "Turn an eight-field brief into a spec that passes a dry run. Fields: tema, publico, duracion, musica, estilo, protagonista, cta, limites, plus lyrics (required: the plan does not write them) and an optional footer (small print on every scene).",
         "inputSchema": envelope({"brief": {"type": "object"}}, ["brief"])},
        {"name": STATUS, "mutation": False, "description": "Short summary of a production: status, progress, stage timings, usage (mcp_calls, response_bytes, h3_takes, gpu_seconds, cpu_seconds, retry_seconds, reused_seconds), per-clip lip-sync verdicts, video and contact-sheet URLs, code review (execution, technical, artistic, retake_keys), last log lines. wait_s blocks until the chosen until condition or the wait elapses. A client may still poll at 300 s; the server accepts up to 1200 s.",
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
            "Authorization": f"Bearer {token()}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            # The production's own steps: its agent call is already in Activity, these are not agent work.
            "X-Hocus-Caller": "production"})
        with open_mcp(request, timeout=600, sleep=sleep) as response:
            result = json.loads(response.read()).get("result") or {}
        if isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]
        try:
            return json.loads(result["content"][0]["text"])
        except (KeyError, IndexError, ValueError):
            return {"error": result}
    return call


def _refuse_locked_retake(production: Production, data: dict) -> tuple[str, ...]:
    """A named retake of a locked shot is shot_locked before status is saved as running."""
    retake = tuple(item for item in (data.get("retake") or ()) if isinstance(item, str))
    if data.get("package") is True:
        return retake
    from services.production_shot_review import assert_obsolete_unlocked, assert_retake_unlocked
    try:
        assert_retake_unlocked(production, retake)
        assert_obsolete_unlocked(production)
    except ProductionError as error:
        from fastapi import HTTPException
        raise HTTPException(422, {"code": error.code, "message": str(error), "retryable": False}) from error
    return retake


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
            retake = _refuse_locked_retake(production, data)
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
                args = (spec, retake, through)
        with _lock:
            if _slot_busy(key):
                raise HTTPException(409, {"code": "already_running", "message": "This production is running", "retryable": True})
            # Bind only after this slot is ours. Stamping identity rewrites the
            # production file; doing that while a shot/song edit holds the slot
            # drops the edit's clips, takes and scene revision.
            if data.get("package") is not True:
                from services.production_generation_link import attach_music
                from services.production_stage_run import adopt_prepared_identity
                registered = attach_music(production, data, spec if preview is None else {})
                adopt_prepared_identity(production)
            thread = threading.Thread(target=target, args=args, name=f"production-{data['production_id']}", daemon=True)
            _threads[key] = thread
            thread.start()
        return {"version": 1, "status": "completed", "operation": RUN, "result": {"production_id": data["production_id"], "running": True, **(registered if data.get("package") is not True else {})}}

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
