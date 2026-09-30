"""Music-video production from one spec: the only creative input an agent writes.

``production.run`` starts (or resumes) a background run in the workspace; ``production.status``
returns a short summary and can wait until that status changes (``wait_s``, max 300 s). The run drives the same public MCP tools an agent would call
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
import json
import os
import shutil
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

# Moved code looks these up on this module at call time; tests patch the names here.
from services import lipsync_qa, song_analysis as audio_analysis
from services.production_disk import release_completed, require_free_disk
from services.production_publication import publication_catalog, publication_handlers
from services.production_resume import open_mcp
from services.production_resource_gate import guard_mcp
from services.production_shot_plan import plan_shots
from services.production_timing import StageWatch, timing_summary
from services.production_usage import attach_usage, usage_summary
from services.production_structure import require_direction
from services.production_quality import expand_quality
from services.production_review import review_for_status
from services.production_scene_retry import apply_scene_export_failure, finish_scene_exports
from services.production_scene3d import export_scene3d_clips, validate_scene3d_shot
from services.production_style_presets import expand_style_preset
from services.production_commands import extra_catalog, extra_handlers
from services.production_control import Cancelled, arm, checkpoint, disarm, sleep_until
from services.production_package import (attach_origins, clip_replacements, contrast_warnings, doc_digest, durable_document, editable_summary,
                                         lyric_for, manifest_rows, write_manifest)
from services.production_shot_edit import render_shot
from services.production_sheets import compose_group, make_frames_sheet
from services.production_wait import MAX_WAIT_S, wait_for_status
from services.video2d_edit import MAX_OPERATIONS
from services.production_clips import clip_job as _clip_job, clips as _clips, judge_take as _judge_take
from services.production_images import (FRAME_ATTEMPTS, FRAME_RESOLUTIONS, attempt as _attempt_image, cast as _cast,
                                        frame_prompt as _frame_prompt, frames as _frames, image as _image, preview as _preview)
from services.production_montage import montage as _montage
from services.production_scene_ops import (DYMO_READABLE, contact_sheet_filter, h3_frames_for, lyric_span, scene_fingerprint,
                                           seam_look, segments, shot_windows, theme_colours, theme_lyric_style, title_cue_count,
                                           title_span)
from services.production_song import analyze as _analyze, pick_song, score as _score, song as _song
from services.production_state import failure_reason, log as _log_state, note_held, note_stop as _note_stop, save as _save_state

RUN, STATUS, PLAN = "production.run", "production.status", "production.plan"
OMARCHY_THEMES: dict[str, dict] = json.loads((Path(__file__).resolve().parents[1] / "shared" / "omarchy_themes.json").read_text(encoding="utf-8"))["entries"]
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
        "quality": {"enum": ["draft", "standard", "max"], "description": "how much the run spends to make it good: fills song seeds and max_takes the spec left out and sets the bar dry_run measures (share of stills, clips per minute)"}},
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
    return require_direction(spec)


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
    def save(self, *, force: bool = False) -> None:
        return _save_state(self, force=force)

    def log(self, line: str) -> None:
        return _log_state(self, line)

    def note_stop(self, error: BaseException) -> None:
        return _note_stop(self, error)

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
        return _image(self, key, prompt, refs, res, seed, model, steps, attempt)

    # steps
    def song(self, spec: dict) -> None:
        return _song(self, spec)

    def analyze(self, spec: dict) -> None:
        return _analyze(self, spec)

    def score(self) -> dict:
        return _score(self)

    def cast(self, spec: dict) -> None:
        return _cast(self, spec)

    def _attempt(self, group: str, key: str) -> int:
        return _attempt_image(self, group, key)

    def frame_prompt(self, spec: dict, w: dict) -> str:
        return _frame_prompt(self, spec, w)

    def frames(self, spec: dict, windows: list[dict]) -> None:
        return _frames(self, spec, windows)

    def preview(self, request: dict) -> None:
        return _preview(self, request)

    def clip_job(self, spec: dict, w: dict, seed: int, take: int = 0) -> str | None:
        return _clip_job(self, spec, w, seed, take)

    def clips(self, spec: dict, windows: list[dict], retake: tuple[str, ...] = (), pause: float = 60) -> None:
        return _clips(self, spec, windows, retake, pause)

    def judge_take(self, w: dict, name: str | None, take: int, vocals: str | None) -> bool:
        return _judge_take(self, w, name, take, vocals)

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
        for shot, a, b in segs:
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
        from services.production_scene_ops import scene_ops as _scene_ops
        return _scene_ops(self, shot, a, b, dur, score, clips, style, stills)

    @staticmethod
    def _title_ops(shot: dict, dur: float, style: dict) -> tuple[list[dict], int]:
        from services.production_scene_ops import title_ops
        return title_ops(shot, dur, style)

    def _lyric_ops(self, shot: dict, a: float, b: float, dur: float, score: dict, style: dict, used: int) -> list[dict]:
        from services.production_scene_ops import lyric_ops
        return lyric_ops(self, shot, a, b, dur, score, style, used)

    @staticmethod
    def _footer_ops(dur: float, style: dict) -> list[dict]:
        from services.production_scene_ops import footer_ops
        return footer_ops(dur, style)

    def montage(self, spec: dict) -> None:
        return _montage(self, spec)

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
            release_completed(self.root, self.state, self.id)
            self.save()


def status_summary(state: dict, workspace: str, root: str | None = None) -> dict[str, Any]:
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
    return summary


# ---------------------------------------------------------------- MCP
def command_catalog() -> list[dict[str, Any]]:
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
        {"name": STATUS, "description": "Short summary of a production: status, stage timings, usage (mcp_calls, response_bytes, h3_takes), per-clip lip-sync verdicts, video and contact-sheet URLs, code review (execution, technical, artistic, retake_keys), last log lines. wait_s blocks until that status value changes or the wait elapses.",
         "inputSchema": envelope({"workspace": ws, "production_id": pid,
                                  "wait_s": {"type": "integer", "minimum": 0, "maximum": MAX_WAIT_S, "default": 0,
                                             "description": "Seconds to wait until status changes. 0 returns at once. Maximum 300."}},
                                 ["workspace", "production_id"])},
        *extra_catalog(),
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
            return {"version": 1, "status": "completed", "operation": RUN, "result": dry_run(data.get("spec"))}
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
        state = await wait_for_status(path, data.get("wait_s", 0))
        summary = await asyncio.to_thread(status_summary, state, data["workspace"], str(path.parent))    # the review opens video files
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

    return {RUN: run, STATUS: status, PLAN: plan, **extra_handlers(workspace_dir, uploads_dir, app_url, token), **publication_handlers(workspace_dir)}
