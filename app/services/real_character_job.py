"""``model3d.real.make``: one realistic (PS2-era) 3D person made on the server, from two English prompts to a character that talks.

The Studio 3D panel «Realista (PS2)», the MCP tools ``model3d.real.*`` and the Wizard's ``make_real_character`` all start this job, so
what an agent makes a person reopens in the panel and remakes with one field changed (``services/real_character_recipe.py``).
It does in one job what ``scripts/dev/real_character.py`` did from outside, step by step, each step saved on the job file
(``.real-character-jobs-v1`` of the workspace) so it is followed after a reload:

1. ``guides``: the mould's two guide pictures (``anime_make.real_guides``: nothing is built or rigged yet);
2. ``body``: the body guide painted with the clothes (``generation.image``, Qwen, the guide as ``image_refs``, ``KI``, 2048x1024);
3. ``head``: the head guide painted with the face and hair;
4. ``character``: ``make_character`` with both pictures: the textured, rigged GLBs, the face relief and the make's warnings;
5. ``kit``: the photo face kit from ``face_pose_file``: a cutout kit ``real-<name>`` rigged with warp mouths (``rig_character``).

A make of a name already made reuses what did not change. A picture is keyed by a hash of its whole prompt, the seed, the model and
the guide (``picture_key``), so a new ``outfit_prompt`` repaints only the body and a new ``face_prompt`` only the head and the kit; a
picture made by an earlier job of the name (one that failed later, too) is found by its key. The drawn ``anime_head`` kit of
``model3d.anime.make`` is not made: ``kit_id`` is the photo kit. A failed face kit does not fail the character: the job completes with
``talk_kit_failed`` and the next make tries the kit again.
"""
from __future__ import annotations

import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.anime_make import make_character, real_guides, slug as name_slug
from services.character_animation_job import AnimationJobError, JobStore
from services.character_kit_library import CharacterKitRevisionConflict, patch_character_kit, read_character_kit_library
from services.local_generation import LocalTools, ToolError, file_url
from services.make_gates import note
from services.mcp_intent import intent_digest
from services.production_image_defaults import default_image_steps
from services.real_character_recipe import (OPERATION, character_key, full_prompts, given_key, latest, make_traits, picture_key, resolve_input,
                                            resolved_traits, write_recipe)

JOBS_DIR = ".real-character-jobs-v1"
ACTIVE = ("queued", "running", "cancelling")
STEPS = ("guides", "body", "head", "character", "kit")
INTERRUPTED = "The server restarted while this character was being made; make it again and what was already made is kept"
RESOLUTION = "2048x1024"   # each atlas picture is 2:1; 2048x1536 runs out of memory (CHARACTER_STYLES.md)
KIT_METHOD = "real-face-tile"
_SAVE_TRIES = 4


class RealJobError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.status = code, status


@dataclass
class RealJobDeps:
    call: Callable[[str, dict[str, Any]], dict[str, Any]]   # LocalMcp.call: generation.image, jobs.wait, jobs.cancel
    workspace_dir: Callable[[str], str]
    inline: bool = False
    make: Callable[..., dict[str, Any]] | None = None    # make_character; a test passes a lighter one
    rig: Callable[..., dict[str, Any]] | None = None     # flat_rig.rig_character; a test passes one that needs no face


def _now() -> float:
    return time.time()


def _step(job: dict, step_id: str) -> dict:
    return next(item for item in job["steps"] if item["id"] == step_id)


def public(job: dict) -> dict:
    return {key: value for key, value in job.items() if key not in {"digest"}}


def kit_notes(report: dict) -> list[dict]:
    """A face kit's report (``talk_report``) as make-style notes: the rig's warnings per pose, its notices, and a base pose whose
    mouth was not found."""
    notes = [note(code, f"The face kit's {pose} pose: {code.replace('_', ' ')}. Look at the rig review before using the kit.", pose=pose)
             for pose, codes in sorted((report.get("warnings") or {}).items()) for code in codes]
    if (report.get("mouthFound") or {}).get("base") is False and not any(item["code"] == "mouth_not_found" for item in notes):
        notes.append(note("mouth_not_found", "The face kit found no mouth on the photograph: it will not talk until a mouth line is placed "
                                             "in Characters › Face Rig.", pose="base"))
    notes.extend(note(str(item.get("code")), "The face kit was rigged without the landmark models: the mouth was placed by the painted-mark search only.")
                 for item in report.get("notices") or [] if item.get("code"))
    return notes


def talk_report(report: dict | None) -> dict | None:
    """What the reply and the recipe keep of a rig: the review sheet, the mouth found per pose, the warnings."""
    if not report:
        return None
    return {"kit_id": report.get("kit_id"), "review": report.get("review"), "unwipedPoses": report.get("unwipedPoses") or [],
            "mouthFound": {pose: item.get("mouthFound") for pose, item in (report.get("poses") or {}).items()},
            "warnings": report.get("warnings") or {}, "notices": report.get("notices") or [], "headKey": report.get("headKey"), "face": report.get("face")}


class RealCharacterJobs:
    # One GPU: realistic characters are made one after another.
    _gpu = threading.Lock()

    def __init__(self, deps: RealJobDeps) -> None:
        self.deps = deps
        self._threads: dict[str, threading.Thread] = {}
        self._tools: dict[str, LocalTools] = {}
        self._guard = threading.Lock()

    # ----- reading -----

    def _root(self, workspace: str) -> Path:
        return Path(self.deps.workspace_dir(workspace))

    def _store(self, workspace: str) -> JobStore:
        return JobStore(str(self._root(workspace)), JOBS_DIR)

    def _alive(self, job_id: str) -> bool:
        thread = self._threads.get(job_id)
        return thread is not None and (thread.ident is None or thread.is_alive())

    def live_jobs(self, workspace_dir: str) -> list[dict]:
        """The jobs in this folder a worker of this service is running (``services.workspace_busy`` probe). Reads only."""
        return [{"jobId": job["jobId"], "status": job["status"], "workspace": job.get("workspace")}
                for job in JobStore(workspace_dir, JOBS_DIR).list() if job.get("status") in ACTIVE and self._alive(str(job.get("jobId") or ""))]

    def jobs(self, workspace: str) -> list[dict]:
        return [public(self._reconcile(workspace, job)) for job in self._store(workspace).list()]

    def status(self, workspace: str, job_id: str) -> dict:
        try:
            job = self._store(workspace).load(job_id)
        except AnimationJobError as error:   # JobStore refuses a job id that is a path
            raise RealJobError("invalid_job", "Invalid job id") from error
        if not job:
            raise RealJobError("job_not_found", "Realistic character job not found", 404)
        return public(self._reconcile(workspace, job))

    def _reconcile(self, workspace: str, job: dict) -> dict:
        """A job that says it is active with no thread here was cut by a restart: it is interrupted, what it made is kept."""
        if job.get("status") not in ACTIVE or self._alive(job.get("jobId", "")):
            return job
        job.update(status="interrupted", error=INTERRUPTED, finishedAt=_now(), updatedAt=_now(), generationJob=None)
        for step in job.get("steps") or []:
            if step["status"] == "running":
                step["status"] = "waiting"
        self._store(workspace).save(job)
        return job

    # ----- starting and stopping -----

    def _replay(self, workspace: str, intent_id: str | None, digest: str) -> dict | None:
        if not intent_id:
            return None
        found = next((job for job in self._store(workspace).list() if job.get("intentId") == intent_id), None)
        if found and found.get("digest") != digest:
            raise RealJobError("intent_conflict", "This intent_id was used with other input", 409)
        return public(self._reconcile(workspace, found)) if found else None

    def _check_revision(self, workspace: str, base_revision: Any) -> None:
        if base_revision is None:
            return
        current = int(read_character_kit_library(str(self._root(workspace))).get("revision") or 0)
        if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision != current:
            raise RealJobError("revision_conflict", f"The character library is at revision {current}, not {base_revision}", 409)

    def _prepare(self, workspace: str, payload: dict) -> tuple[str, dict]:
        """The name and the input the job runs with, or why it cannot run: nothing is asked of the model before this passes."""
        name = str(payload.get("name") or "").strip()
        if not name or len(name) > 64:
            raise RealJobError("invalid_name", "name must be a nonempty string (max 64)")
        root = self._root(workspace)
        effective = resolve_input({key: value for key, value in payload.items() if key not in ("workspace", "name")}, latest(root, name))
        self._check_revision(workspace, payload.get("base_revision"))
        for field in ("texture", "texture_head"):
            if field in effective and not (root / effective[field]).is_file():
                raise RealJobError("texture_missing", f"{field} {effective[field]} is not a picture of workspace {workspace}", 404)
        return name, effective

    def start(self, workspace: str, payload: dict, intent_id: str | None = None) -> dict:
        """Make (or remake) one realistic character. Returns the job; a make of a name that is being made returns that job."""
        digest = intent_digest({"workspace": workspace, **payload})
        replayed = self._replay(workspace, intent_id, digest)
        if replayed:
            return replayed
        name, effective = self._prepare(workspace, payload)
        with self._guard:
            running = next((job for job in self.jobs(workspace) if job.get("slug") == name_slug(name) and job.get("status") in ACTIVE), None)
            if running:
                return running
            job = {"jobId": f"real-{uuid.uuid4().hex[:12]}", "operation": OPERATION, "workspace": workspace, "name": name, "slug": name_slug(name),
                   "intentId": intent_id, "digest": digest, "status": "queued", "stage": STEPS[0], "input": effective,
                   "steps": [{"id": step, "status": "waiting"} for step in STEPS], "createdAt": _now(), "updatedAt": _now()}
            self._store(workspace).save(job)
            thread = threading.Thread(target=self._run, args=(workspace, job["jobId"]), name=f"real-character-{job['jobId']}", daemon=True)
            self._threads[job["jobId"]] = thread
        if self.deps.inline:
            thread.run()
            return public(self._store(workspace).load(job["jobId"]) or job)
        thread.start()
        return public(job)

    def cancel(self, workspace: str, job_id: str) -> dict:
        job = self.status(workspace, job_id)
        if job.get("status") not in ACTIVE:
            return job
        stored = self._store(workspace).load(job_id) or job
        stored.update(status="cancelling", updatedAt=_now())
        self._store(workspace).save(stored)
        tools = self._tools.get(job_id)
        if tools and stored.get("generationJob"):
            tools.cancel(stored["generationJob"])
        return public(stored)

    # ----- the worker -----

    def _cancelled(self, store: JobStore, job_id: str) -> bool:
        return (store.load(job_id) or {}).get("status") == "cancelling"

    def _update(self, store: JobStore, job: dict, **changes: Any) -> None:
        job.update(changes, updatedAt=_now())
        stored = store.load(job["jobId"]) or {}
        if stored.get("status") == "cancelling" and job.get("status") == "running":
            job["status"] = "cancelling"   # a cancel that arrived while a step ran is not lost
        store.save(job)

    def _begin(self, store: JobStore, job: dict, step_id: str) -> dict:
        if self._cancelled(store, job["jobId"]):
            raise ToolError("cancelled", "the job was cancelled")
        step = _step(job, step_id)
        step["status"] = "running"
        self._update(store, job, stage=step_id)
        return step

    def _run(self, workspace: str, job_id: str) -> None:
        store = self._store(workspace)
        job = store.load(job_id) or {}
        tools = LocalTools(self.deps.call, workspace, str(self._root(workspace)), cancelled=lambda: self._cancelled(store, job_id),
                           on_job=lambda generation_job: self._update(store, job, generationJob=generation_job))
        self._tools[job_id] = tools
        try:
            with self._gpu:
                self._update(store, job, status="running")
                work = self._work(workspace, job)
                self._guides(store, job, work)
                for part in ("body", "head"):
                    self._paint(store, job, tools, part, work)
                self._character(store, job, work)
                self._kit(store, job, work)
                self._finish(store, job, work)
        except ToolError as error:
            cancelled = error.code == "cancelled"
            self._fail_step(job, "" if cancelled else str(error))
            self._update(store, job, status="cancelled" if cancelled else "failed", error="" if cancelled else str(error)[:500],
                         errorCode=error.code, finishedAt=_now(), generationJob=None)
        except Exception as error:   # the job reports whatever stopped it
            self._fail_step(job, str(error))
            self._update(store, job, status="failed", error=f"{error}"[:500], errorCode=getattr(error, "code", type(error).__name__),
                         finishedAt=_now(), generationJob=None)
        finally:
            self._tools.pop(job_id, None)

    @staticmethod
    def _fail_step(job: dict, error: str) -> None:
        for step in job.get("steps") or []:
            if step["status"] == "running":
                step.update(status="failed", error=error[:300]) if error else step.update(status="waiting")

    def _work(self, workspace: str, job: dict) -> dict:
        """What the steps share: the folder, the newest recipe of the name and every picture an earlier job of the name made, by key."""
        root = self._root(workspace)
        prior = latest(root, job["name"])
        pool = {}
        for older in reversed(self._store(workspace).list()):
            if older.get("slug") == job["slug"]:
                pool.update({step["key"]: step["file"] for step in older.get("steps") or [] if step.get("key") and step.get("file")})
        for part, picture in ((prior or {}).get("pictures") or {}).items():
            if part in ("body", "head") and picture.get("key") and picture.get("file"):
                pool.setdefault(picture["key"], picture["file"])
        return {"root": root, "prior": prior, "pool": pool, "prompts": full_prompts(job["input"]), "keys": {}, "files": {}, "reused": []}

    def _guides(self, store: JobStore, job: dict, work: dict) -> None:
        step = self._begin(store, job, "guides")
        guides = real_guides(work["root"], job["name"], make_traits(job["input"]))
        work["guides"] = {"body": guides["guides"]["body"], "head": guides["guides"]["head"]}
        work["files"].update(guide_body_file=guides["guide_body_file"], guide_head_file=guides["guide_head_file"])
        step.update(status="done", files=[guides["guide_body_file"], guides["guide_head_file"]])
        self._update(store, job)

    def _image_params(self, job: dict, prompt: str, guide_file: str) -> dict:
        model = job["input"]["image_model"]
        params = {"model_type": model, "prompt": prompt, "resolution": RESOLUTION, "seed": job["input"]["seed"],
                  "num_inference_steps": default_image_steps(model), "image_refs": [file_url(guide_file, job["workspace"])],
                  "video_prompt_type": "KI"}
        if "turbo" in model:
            params["guidance_scale"] = 1.0   # the Turbo runs 8 steps at CFG 1; another model keeps its own guidance
        return params

    def _paint(self, store: JobStore, job: dict, tools: LocalTools, part: str, work: dict) -> None:
        """One picture: the one given, the one an earlier job painted with the same key, or a new one."""
        step = self._begin(store, job, part)
        given = job["input"].get("texture" if part == "body" else "texture_head")
        if given:
            key, file, status = given_key(work["root"] / given), given, "given"
        else:
            model = job["input"]["image_model"]
            key = picture_key(model, default_image_steps(model), work["prompts"][part], job["input"]["seed"], work["guides"][part])
            file = work["pool"].get(key)
            status = "reused" if file and (work["root"] / file).is_file() else "painting"
            step.update(key=key)
            if status == "painting":
                self._update(store, job)
                guide = work["files"]["guide_body_file" if part == "body" else "guide_head_file"]
                file = tools.image(f"{job['jobId']}-{part}", self._image_params(job, work["prompts"][part], guide), f"real-{job['slug']}-{part}-{key[:10]}")
        work["keys"][part], work["files"][f"{part}_picture"] = key, file
        step.update(status="done" if status == "painting" else status, key=key, file=file)
        self._update(store, job)

    def _character(self, store: JobStore, job: dict, work: dict) -> None:
        step = self._begin(store, job, "character")
        traits = make_traits(job["input"])
        key = character_key(traits, work["keys"]["body"], work["keys"]["head"])
        prior = work["prior"] or {}
        rigged = ((prior.get("made") or {}).get("rigged_file")) or ""
        if (prior.get("keys") or {}).get("character") == key and rigged and (work["root"] / rigged).is_file():
            made, status = prior["made"], "reused"
        else:
            make = self.deps.make or make_character
            made = make(work["root"], job["workspace"], job["name"], f"{OPERATION}:{job['slug']}:{key}",
                        {**traits, "texture": work["files"]["body_picture"], "texture_head": work["files"]["head_picture"]}, face_kit=False)
            status = "done"
        work["keys"]["character"], work["made"] = key, made
        step.update(status=status, key=key, file=made.get("rigged_file"))
        self._update(store, job)

    def _kit(self, store: JobStore, job: dict, work: dict) -> None:
        step = self._begin(store, job, "kit")
        work["kit"], work["kit_error"] = None, None
        if not job["input"]["talk_kit"]:
            step.update(status="skipped")
            self._update(store, job)
            return
        head_key, kit_id = work["keys"]["head"], f"real-{job['slug']}"
        kit = (read_character_kit_library(str(work["root"])).get("kits") or {}).get(kit_id)
        stored = ((work["prior"] or {}).get("talk_kit")) or {}
        if kit and _kit_head_key(kit) == head_key and stored.get("headKey") == head_key:
            work["kit"] = stored
            step.update(status="reused", key=head_key, kit_id=kit_id)
        else:
            try:
                work["kit"] = talk_report(self._make_kit(job, work, kit_id, head_key))
                step.update(status="done", key=head_key, kit_id=kit_id)
            except Exception as error:   # the character stands without its face kit: said, and tried again by the next make
                work["kit_error"] = str(error)[:300]
                step.update(status="failed", key=head_key, error=work["kit_error"])
        self._update(store, job)

    def _make_kit(self, job: dict, work: dict, kit_id: str, head_key: str) -> dict:
        """A cutout kit whose base is the front of the head picture (a copy named by the head's key, so the kit never changes under a
        later make), rigged with warp mouths: the photograph's own pixels."""
        from services.flat_rig import rig_character
        from services.tool_sidecars import rig_sidecars

        root, workspace = work["root"], job["workspace"]
        face_file = f"real-{job['slug']}-face-{head_key[:10]}.png"
        if not (root / face_file).is_file():
            shutil.copyfile(root / work["made"]["face_pose_file"], root / face_file)
        base = {"id": f"{kit_id}-base", "name": f"{job['name']} base", "source": file_url(face_file, workspace), "kind": "image", "alphaStatus": "opaque",
                "reviewState": "approved", "workspace": workspace, "width": 1024, "height": 1024}
        character = {"version": 1, "id": kit_id, "name": job["name"], "style": "cutout", "base": base, "poses": {"neutral": dict(base)},
                     "mouth": {}, "eyes": {}, "anchors": {},
                     "provenance": [{"method": KIT_METHOD, "operation": OPERATION, "image": face_file, "headKey": head_key}]}
        revision = _save_kit(str(root), kit_id, character)
        rigged = (self.deps.rig or rig_character)(str(root), workspace, kit_id, base_revision=revision, style={"mouthStyle": "warp"})
        rig_sidecars(rigged, workspace=workspace, kit_id=kit_id, folder=str(root), request={"poses": None})
        return {**rigged, "kit_id": kit_id, "headKey": head_key, "face": face_file}

    def _finish(self, store: JobStore, job: dict, work: dict) -> None:
        recipe = self._recipe(job, work)
        write_recipe(work["root"], {**recipe, "made": work["made"]})
        made = {key: value for key, value in work["made"].items() if key not in ("kit_id", "poses", "preview", "face")}
        kit = work["kit"] or {}
        warnings = list(made.get("warnings") or []) + kit_notes(kit)
        if work["kit_error"]:
            warnings.append(note("talk_kit_failed", f"The photo face kit could not be made: {work['kit_error']} The character is ready; make it again to retry the kit."))
        face = kit.get("face") or made.get("face_pose_file")
        result = {**made, "kit_id": recipe["kit_id"], "poses": ["base", "neutral"] if recipe["kit_id"] else [], "preview": file_url(face, job["workspace"]) if face else None, "face": None,
                  "talk_kit": kit or None, "recipe": recipe, "warnings": warnings,
                  "reused": [step["id"] for step in job["steps"] if step["status"] in ("reused", "given")]}
        self._update(store, job, status="completed", stage="done", finishedAt=_now(), generationJob=None, result=result)

    def _recipe(self, job: dict, work: dict) -> dict:
        effective, made, kit = job["input"], work["made"], work["kit"]
        pictures = {part: {"file": work["files"][f"{part}_picture"], "key": work["keys"][part], "given": bool(effective.get(field))}
                    for part, field in (("body", "texture"), ("head", "texture_head"))}
        if kit and kit.get("face"):
            pictures["face"] = {"file": kit["face"], "key": work["keys"]["head"]}
        return {"version": 1, "operation": OPERATION, "name": job["name"], "slug": job["slug"], "workspace": job["workspace"], "jobId": job["jobId"],
                "madeAt": datetime.now(timezone.utc).isoformat(timespec="microseconds"), "input": effective, "traits": resolved_traits(effective),
                "prompts": {"outfit": effective.get("outfit_prompt"), "face": effective.get("face_prompt"), **work["prompts"]},
                "seed": effective["seed"], "image_model": effective["image_model"],
                "guides": {"body": work["files"]["guide_body_file"], "head": work["files"]["guide_head_file"]}, "pictures": pictures,
                "files": {key: made.get(key) for key in ("file", "rigged_file", "face_pose_file")},
                "keys": {**work["keys"], "kit": (kit or {}).get("headKey")}, "kit_id": (kit or {}).get("kit_id"), "talk_kit": kit}


def _kit_head_key(kit: dict) -> str | None:
    made = next((entry for entry in kit.get("provenance") or [] if entry.get("method") == KIT_METHOD), None)
    return made.get("headKey") if made else None


def _save_kit(root: str, kit_id: str, character: dict) -> int:
    """Save the kit as the library is now (a retry on a revision race); the new revision."""
    for attempt in range(_SAVE_TRIES):
        library = read_character_kit_library(root)
        try:
            saved = patch_character_kit(root, kit_id, character, base_revision=int(library["revision"]), make_active=False)
            return int(saved["revision"])
        except CharacterKitRevisionConflict:
            if attempt == _SAVE_TRIES - 1:
                raise
    raise RuntimeError("unreachable")
