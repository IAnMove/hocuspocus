"""Make one animation of a character on the server: the Character Creator, the MCP tools and the Wizard all start this job.

An animation is a few poses of the same figure (``services/character_animations.py``). The job makes every pose in turn with the
character's own picture as the identity reference (``generation.image``), keys each on its screen colour (``studio.key``), joins
them into a sprite sheet and saves it on the kit as ``animations.<id>`` waiting for a person's review: the job never approves.

* A pose that was made stays when the job fails, is cancelled or is cut by a restart: the next job for that animation keeps those
  poses and makes the rest. ``pose`` makes one pose of a finished animation again and keeps the others.
* One animation is made at a time on the server (one GPU); a second request for the same animation returns the running job.
* ``autoApprove`` («Modo un solo disparo», ``agent_autonomy`` = ``one_shot``) lets the job approve what it made when the sheet passes the
  automatic checks (``services/character_animation_checks.py``): the approval is the agent's review (``reviewedBy: agent``), the job
  reports ``autoApproved`` and ``checks``, and a sheet that fails stays pending for a person with the list of what failed.
* A job is a small file under ``.character-animation-jobs-v1`` of the workspace, so it can be followed after a reload and listed.
* ``references`` are extra pictures (the picture of another direction of the same character) sent after the character's own as
  ``image_refs``: a model that takes only one reference refuses them, and the job goes on with the character's picture alone
  (``refsDropped``). ``services/character_animation_set_job.py`` makes several animations in turn with this.
* The sheet of a twelve-pose cycle is a grid of six columns, and the entry saved on the kit carries ``motion`` and ``dir``
  (``services/character_animation_directions.py``); the checks of a direction also read the other directions of the kit.
* ``method`` ``video`` (optional; the default is the pose-by-pose path above) makes a catalog walk from one LTX-2.3 clip
  guided by the gait skeleton (``services/walk_video_method.py``), keys it and samples the same sheet. It needs the distilled
  weights and the union-control LoRA. Without them, or for anything that is not a walk, the request fails and this path is
  not used. ``make_set`` stays pose by pose.
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from services import agent_autonomy
from services.character_animation_checks import failed, sheet_checks, summary
from services.character_animation_cycle_checks import sibling_sheets
from services.character_animation_directions import contract_of
from services.character_animation_guides import gait_of, guide_for, guided_prompt, tries
from services.character_animation_review import AnimationReviewError, review_kit_animation
from services.character_animations import (MAX_ANIMATIONS, CharacterAnimationError, animation_def, build_sheet, normalize_kit_animations,
                                           pose_prompt)
from services.character_kit_face_cleanup import resolve_character_kit_image
from services.character_kit_library import CharacterKitRevisionConflict, patch_character_kit, read_character_kit_library
from services.local_generation import LocalTools, ToolError, file_url
from services.production_image_defaults import DEFAULT_IMAGE_MODEL, default_image_steps, model_takes_negative_prompt
from services.walk_video_method import LTX_MODEL, NOT_INSTALLED, WalkVideoError, accept_walk_method, clip_fields, fill_video_takes, weights_present

JOBS_DIR = ".character-animation-jobs-v1"
ACTIVE = ("queued", "running", "cancelling")
RESUMABLE = ("failed", "cancelled", "interrupted")
INTERRUPTED = "The server restarted while this animation was being made; make it again and the poses already made are kept"
AUTO_APPROVE_OFF = ("autoApprove was ignored: agent_autonomy is review, so a person approves this animation in Personajes › Animaciones "
                    "(or the owner turns on «Modo un solo disparo» in Ajustes › Servicios).")
DEFAULT_MODEL = DEFAULT_IMAGE_MODEL
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_SAVE_TRIES = 4
MAX_REFERENCES = 4


class AnimationJobError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.status = code, status


@dataclass
class AnimationJobDeps:
    call: Callable[[str, dict[str, Any]], dict[str, Any]]
    workspace_dir: Callable[[str], str]
    uploads_root: Callable[[], str]
    # The steps and guidance a model runs with (its own defaults), so a turbo model keeps its few steps.
    model_defaults: Callable[[str], dict[str, Any]] | None = None
    inline: bool = False
    # The services config now (``agent_autonomy`` lives there): read when a job starts and again when it ends, so a mode the owner
    # switches off meanwhile is respected. None means «review».
    services: Callable[[], Mapping[str, Any]] | None = None
    # None asks the disk whether LTX-2.3 distilled and the union-control LoRA are installed. A test can answer instead.
    walk_video_ready: Callable[[], bool] | None = None


def _now() -> float:
    return time.time()


def reference_of(kit: dict[str, Any]) -> str | None:
    """The picture every pose is made from: the character's own identity, never a pose of one of its animations."""
    source = ((kit.get("identityReference") or kit.get("base") or {}).get("source") or "")
    return source if source and not source.startswith("blob:") else None


def style_of(kit: dict[str, Any]) -> str | None:
    made = next((entry for entry in kit.get("provenance") or [] if entry.get("method") == "character-style-create" and isinstance(entry.get("style"), str)), None)
    return made["style"] if made else None


class JobStore:
    """One JSON file per job, replaced atomically."""

    def __init__(self, root: str, directory: str = JOBS_DIR) -> None:
        self.directory = os.path.join(root, directory)

    def path(self, job_id: str) -> str:
        if not job_id or os.path.basename(job_id) != job_id or job_id in {".", ".."}:
            raise AnimationJobError("invalid_job", "Invalid animation job id")
        return os.path.join(self.directory, f"{job_id}.json")

    def save(self, job: dict[str, Any]) -> None:
        os.makedirs(self.directory, exist_ok=True)
        path = self.path(job["jobId"])
        temporary = f"{path}.{uuid.uuid4().hex}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, path)

    def load(self, job_id: str) -> dict[str, Any] | None:
        try:
            with open(self.path(job_id), encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    def list(self) -> list[dict[str, Any]]:
        names = [name[:-5] for name in os.listdir(self.directory) if name.endswith(".json")] if os.path.isdir(self.directory) else []
        jobs = [job for job in (self.load(name) for name in names) if job]
        return sorted(jobs, key=lambda job: float(job.get("createdAt") or 0), reverse=True)


def public(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key not in {"definition", "reference", "description", "style", "extraRefs"}}


class CharacterAnimationJobs:
    # One GPU: animations of every workspace are made one after another.
    _gpu = threading.Lock()

    def __init__(self, deps: AnimationJobDeps) -> None:
        self.deps = deps
        self._threads: dict[str, threading.Thread] = {}
        self._tools: dict[str, LocalTools] = {}
        self._guard = threading.Lock()
        # Other services that make animations through this one (the set job) add their live jobs to the same busy probe.
        self.live_sources: list[Callable[[str], list[dict[str, Any]]]] = []

    def _store(self, workspace: str) -> JobStore:
        return JobStore(self.deps.workspace_dir(workspace))

    def _kit(self, workspace: str, kit_id: str) -> dict[str, Any]:
        kit = (read_character_kit_library(self.deps.workspace_dir(workspace)).get("kits") or {}).get(kit_id)
        if not kit:
            raise AnimationJobError("kit_not_found", f"Character Kit {kit_id} is not in the {workspace} workspace", 404)
        return kit

    def kit(self, workspace: str, kit_id: str) -> dict[str, Any]:
        """The character as it is in the library now (the set job reads what the last sheet added)."""
        return self._kit(workspace, kit_id)

    def auto_fields(self, requested: bool) -> dict[str, Any]:
        """What a job records of an ``autoApprove`` request (the set job records the same)."""
        return self._auto_fields(requested)

    def _alive(self, job_id: str) -> bool:
        """Whether a worker thread of this service still owns the job (one that has not started yet counts)."""
        thread = self._threads.get(job_id)
        return thread is not None and (thread.ident is None or thread.is_alive())

    def live_jobs(self, workspace_dir: str) -> list[dict[str, Any]]:
        """The jobs in this folder that a worker of this service is running (``services.workspace_busy`` probe).

        Reads only. A checkpoint that says running without a thread was cut by a restart: it is not
        busy, and ``jobs()`` turns it into ``interrupted`` the next time something reads it.
        """
        own = [
            {"jobId": job["jobId"], "status": job["status"], "workspace": job.get("workspace")}
            for job in JobStore(workspace_dir).list()
            if job.get("status") in ACTIVE and self._alive(str(job.get("jobId") or ""))
        ]
        return [*own, *(item for source in self.live_sources for item in source(workspace_dir))]

    def jobs(self, workspace: str, kit_id: str | None = None) -> list[dict[str, Any]]:
        listed = [self._reconcile(workspace, job) for job in self._store(workspace).list()]
        return [public(job) for job in listed if not kit_id or job.get("kitId") == kit_id]

    def status(self, workspace: str, job_id: str) -> dict[str, Any]:
        job = self._store(workspace).load(job_id)
        if not job:
            raise AnimationJobError("job_not_found", "Animation job not found", 404)
        return public(self._reconcile(workspace, job))

    def _reconcile(self, workspace: str, job: dict[str, Any]) -> dict[str, Any]:
        """A job that says it is active but has no thread here was cut by a restart: it is interrupted, its poses kept."""
        if job.get("status") not in ACTIVE or self._alive(job.get("jobId", "")):
            return job
        if job.get("jobId") in self._threads:
            stored = self._store(workspace).load(job["jobId"]) or job
            if stored.get("status") not in ACTIVE:
                return stored
        job.update(status="interrupted", error=INTERRUPTED, finishedAt=_now(), updatedAt=_now())
        for take in job.get("takes") or []:
            if take["status"] in ("generating", "keying"):
                take["status"] = "waiting"
        self._store(workspace).save(job)
        return job

    def _kept(self, workspace: str, kit: dict[str, Any], animation_id: str, remake: str | None, ids: list[str]) -> dict[str, str]:
        """Poses (id → keyed picture) the new job does not make again: the others when one pose is remade, else those an earlier
        failed, cancelled or interrupted job for this animation had already keyed."""
        if remake:
            frames = (kit.get("animations") or {}).get(animation_id, {}).get("frames") or []
            return {frame["id"]: frame["source"] for frame in frames if frame["id"] != remake and frame["id"] in ids}
        latest = next((job for job in self._store(workspace).list() if job.get("kitId") == kit["id"] and job.get("animationId") == animation_id), None)
        if not latest or latest.get("status") not in RESUMABLE or latest.get("remake"):
            return {}
        made = [take for take in latest.get("takes") or [] if take.get("keyed") and take["status"] in ("ready", "reused")]
        return {take["id"]: take["keyed"] for take in made if take["id"] in ids}

    def _definition(self, kit: dict[str, Any], animation_id: str, custom: dict[str, Any] | None, pose: str | None) -> dict[str, Any]:
        """What to make, or why it cannot be made: nothing is asked of the model before this passes."""
        made = (kit.get("animations") or {}).get(animation_id)
        try:
            definition = animation_def(animation_id, made=made, custom=custom)
        except CharacterAnimationError as error:
            raise AnimationJobError("invalid_animation", str(error)) from error
        if pose and (pose not in [item["id"] for item in definition["poses"]] or not made):
            raise AnimationJobError("pose_not_found", f"{animation_id} has no made pose {pose} to make again", 404)
        if not reference_of(kit):
            raise AnimationJobError("no_reference", f"Character Kit {kit.get('name') or kit['id']} has no persistent picture to make poses from")
        if not made and len(kit.get("animations") or {}) >= MAX_ANIMATIONS:
            # A new id at the cap would spend every GPU pose and only then fail to save on the kit. Making one again is fine.
            raise AnimationJobError("animation_limit", f"Character Kit {kit.get('name') or kit['id']} already has {MAX_ANIMATIONS} animations, the most a kit keeps")
        return definition

    def _new_job(self, workspace: str, kit: dict[str, Any], definition: dict[str, Any], pose: str | None, model: str | None,
                 references: list[str] | None = None, method_name: str = "poses") -> dict[str, Any]:
        ids = [item["id"] for item in definition["poses"]]
        # A guided clip replaces every pose. A pose kept from an earlier pose-by-pose try is not a frame of that clip.
        kept = {} if method_name == "video" else self._kept(workspace, kit, definition["id"], pose, ids)
        takes = [{"id": item, "status": "reused", "keyed": kept[item], "seed": 0} if item in kept else
                 {"id": item, "status": "waiting", "seed": random.randrange(2_000_000_000)} for item in ids]
        job = {"jobId": f"anim-{uuid.uuid4().hex[:12]}", "workspace": workspace, "kitId": kit["id"], "animationId": definition["id"],
               "title": definition["title"]["en"], "model": model or DEFAULT_MODEL, "status": "queued", "stage": "poses", "takes": takes,
               "remake": pose, "createdAt": _now(), "updatedAt": _now(), "definition": definition, "reference": reference_of(kit),
               "description": (kit.get("lookNotes") or "").strip() or kit.get("name") or kit["id"], "style": style_of(kit)}
        if references:
            job["extraRefs"] = references
        if definition.get("custom"):
            # What the author wrote stays visible on the job, so an animation that is not on the kit yet can be shown and tried again.
            job["custom"] = {"title": definition["title"]["es"], "view": definition["view"], "poses": [item["prompt"] for item in definition["poses"]]}
        if method_name == "video":
            job["method"] = "video"
            job["model"] = LTX_MODEL
        return job

    def _services(self) -> Mapping[str, Any]:
        return self.deps.services() if self.deps.services else {}

    def _auto_fields(self, requested: bool) -> dict[str, Any]:
        """What the job records of an ``autoApprove`` request: it counts only in «Modo un solo disparo»; otherwise it is ignored, with the why."""
        if not requested:
            return {}
        return {"autoApprove": True} if agent_autonomy.is_one_shot(self._services()) else {"autoApprove": False, "autoApproveNote": AUTO_APPROVE_OFF}

    @staticmethod
    def _references(references: list[str] | None) -> list[str]:
        found = [str(item or "").strip() for item in references or []]
        if len(found) > MAX_REFERENCES or any(not item or len(item) > 1200 or item.startswith("blob:") for item in found):
            raise AnimationJobError("invalid_reference", f"references are up to {MAX_REFERENCES} persistent picture URLs, not browser blob URLs")
        return found

    def _accept_method(self, method: str | None, definition: dict[str, Any], pose: str | None) -> str:
        try:
            return accept_walk_method(method, definition, pose)
        except WalkVideoError as error:
            raise AnimationJobError(error.code, str(error)) from error

    def _require_video_weights(self) -> None:
        ready = self.deps.walk_video_ready
        if not (weights_present() if ready is None else bool(ready())):
            raise AnimationJobError("ltx_not_installed", NOT_INSTALLED)

    def start(self, workspace: str, kit_id: str, animation_id: str, *, custom: dict[str, Any] | None = None, pose: str | None = None,
              model: str | None = None, auto_approve: bool = False, references: list[str] | None = None,
              method: str | None = None) -> dict[str, Any]:
        """Make (or, with ``pose``, make one pose again of) an animation of a saved character. Returns the job; a request for an
        animation that is already being made returns that job. ``auto_approve`` asks the job to approve what it made when the sheet passes
        the automatic checks; it is ignored (the job says so) unless ``agent_autonomy`` is ``one_shot``. ``references`` are extra pictures
        sent after the character's own (see the module docstring)."""
        if model and not _MODEL.fullmatch(model):
            raise AnimationJobError("invalid_model", "model is the id of an image model")
        extra = self._references(references)
        kit = self._kit(workspace, kit_id)
        definition = self._definition(kit, animation_id, custom, pose)
        chosen = self._accept_method(method, definition, pose)
        with self._guard:
            running = next((job for job in self.jobs(workspace, kit_id) if job.get("animationId") == animation_id and job.get("status") in ACTIVE), None)
            if running:
                return running
            if chosen == "video":
                self._require_video_weights()
            job = {**self._new_job(workspace, kit, definition, pose, model, extra, chosen), **self._auto_fields(auto_approve)}
            self._store(workspace).save(job)
            thread = threading.Thread(target=self._run, args=(workspace, job["jobId"]), name=f"character-animation-{job['jobId']}", daemon=True)
            self._threads[job["jobId"]] = thread
        if self.deps.inline:
            thread.run()
            return public(self._store(workspace).load(job["jobId"]) or job)
        thread.start()
        return public(job)

    def cancel(self, workspace: str, job_id: str) -> dict[str, Any]:
        store = self._store(workspace)
        job = store.load(job_id)
        if not job:
            raise AnimationJobError("job_not_found", "Animation job not found", 404)
        job = self._reconcile(workspace, job)
        if job.get("status") not in ACTIVE:
            return public(job)
        job.update(status="cancelling", updatedAt=_now())
        store.save(job)
        tools = self._tools.get(job_id)
        if tools and job.get("generationJob"):
            tools.cancel(job["generationJob"])
        return public(job)

    # ----- the worker -----

    def _cancelled(self, store: JobStore, job_id: str) -> bool:
        return (store.load(job_id) or {}).get("status") == "cancelling"

    def _update(self, store: JobStore, job: dict[str, Any], **changes: Any) -> None:
        job.update(changes, updatedAt=_now())
        stored = store.load(job["jobId"]) or {}
        if stored.get("status") == "cancelling" and job.get("status") == "running":
            job["status"] = "cancelling"  # a cancel that arrived while a step ran is not lost
        store.save(job)

    def _image_params(self, job: dict[str, Any], built: dict[str, str], seed: int, guide: dict[str, Any] | None = None) -> dict[str, Any]:
        """One pose's request: the character's picture is the identity reference, then the pose's guide (a walk) and the extra pictures.
        Every model runs its own steps and guidance (the server's settings for it, else its definition in app/defaults: the default Turbo
        runs 8 and CFG 1), and one that takes no negative prompt gets none. A model that refused the extra pictures gets the character's
        picture alone and the plain prompt."""
        model = job["model"]
        steps, guidance = default_image_steps(model), 1
        if self.deps.model_defaults:
            own = self.deps.model_defaults(model) or {}
            steps, guidance = own.get("num_inference_steps") or steps, own.get("guidance_scale") or guidance
        alone = bool(job.get("refsDropped"))
        extra = [] if alone else job.get("extraRefs") or []
        shown = None if alone else guide
        refs = [job["reference"], *([file_url(shown["file"], job["workspace"])] if shown else []), *extra]
        params: dict[str, Any] = {"prompt": guided_prompt(built["prompt"], shown, len(extra)), "model_type": model, "resolution": built["resolution"],
                                  "seed": seed, "guidance_scale": guidance, "num_inference_steps": steps, "image_refs": refs, "video_prompt_type": "I"}
        if steps > 8 and model_takes_negative_prompt(model):
            params["negative_prompt"] = built["negative"]
        return params

    def _draw(self, job: dict[str, Any], tools: LocalTools, pose: dict[str, Any], built: dict[str, str], guide: dict[str, Any] | None,
              seed: int, attempt: int, drawn: Callable[[str], None]) -> tuple[str, str]:
        """One drawing of a pose and its key: the raw picture's file name and the keyed URL; ``drawn`` hears of the raw picture before it is
        keyed. A second or third try has names of its own."""
        definition, again = job["definition"], f"-{attempt + 1}" if attempt else ""
        # The file name carries the job: a pose made again never overwrites the picture the saved animation still uses.
        output = f"{job['kitId']}-{definition['id']}-{pose['id']}-{job['jobId'][-6:]}{again}"
        try:
            name = tools.image(f"{job['jobId']}-{pose['id']}-image{again}", self._image_params(job, built, seed, guide), output)
        except ToolError as error:
            if not (job.get("extraRefs") or guide) or job.get("refsDropped") or "image_refs" not in str(error):
                raise
            # This model takes fewer references than were sent: the character's own picture alone is what every pose needs.
            job["refsDropped"] = True
            name = tools.image(f"{job['jobId']}-{pose['id']}-image-alone{again}", self._image_params(job, built, seed, guide), output)
        drawn(name)
        return name, tools.key(f"{job['jobId']}-{pose['id']}-key{again}", name, built["screen"])

    def _take(self, store: JobStore, job: dict[str, Any], take: dict[str, Any], tools: LocalTools, pose: dict[str, Any]) -> None:
        definition, workspace = job["definition"], job["workspace"]
        root = self.deps.workspace_dir(workspace)
        built = pose_prompt(definition["id"], pose["id"], job["description"], job.get("style"),
                            custom={"view": definition["view"], "text": pose["prompt"]} if definition.get("custom") else None)
        guide = guide_for(definition, pose["id"], workspace_root=root, name=f"{job['kitId']}-{definition['id']}-{pose['id']}-guide-{job['jobId'][-6:]}.png")
        job.setdefault("prompt", guided_prompt(built["prompt"], guide, len(job.get("extraRefs") or [])))
        take.update(status="generating", **({"guide": file_url(guide["file"], workspace)} if guide else {}))
        self._update(store, job)

        def keying(name: str) -> None:
            take.update(status="keying", raw=file_url(name, workspace))
            self._update(store, job)

        best: dict[str, Any] | None = None
        for attempt in range(tries(guide)):
            seed = take["seed"] if attempt == 0 else random.randrange(2_000_000_000)
            name, keyed = self._draw(job, tools, pose, built, guide, seed, attempt, keying)
            drawn = {"raw": file_url(name, workspace), "keyed": keyed, "seed": seed}
            if guide:  # a walk pose is measured against its guide and drawn again when its legs are far off
                drawn["gait"] = gait_of(guide, resolve_character_kit_image(keyed, uploads_root=self.deps.uploads_root(), workspace_root=root))
                take["tries"] = attempt + 1
            if best is None or abs(drawn["gait"]["measured"] - guide["expected"]) < abs(best["gait"]["measured"] - guide["expected"]):
                best = drawn
            if not guide or drawn["gait"]["ok"]:
                break
            self._update(store, job)
        take.update(status="ready", **(best or {}))
        self._update(store, job)

    def _run(self, workspace: str, job_id: str) -> None:
        store = self._store(workspace)
        job = store.load(job_id) or {}
        tools = LocalTools(self.deps.call, workspace, self.deps.workspace_dir(workspace), cancelled=lambda: self._cancelled(store, job_id),
                           on_job=lambda generation_job: self._update(store, job, generationJob=generation_job))
        self._tools[job_id] = tools
        try:
            with self._gpu:
                if self._cancelled(store, job_id):
                    raise ToolError("cancelled", "the job was cancelled")
                self._update(store, job, status="running")
                if job.get("method") == "video":
                    self._video_cycle(store, job, tools)
                else:
                    poses = {item["id"]: item for item in job["definition"]["poses"]}
                    for take in job["takes"]:
                        if take["status"] not in ("reused", "ready"):
                            try:
                                self._take(store, job, take, tools, poses[take["id"]])
                            except ToolError as error:
                                take.update(status="waiting") if error.code == "cancelled" else take.update(status="failed", error=str(error)[:300])
                                raise
                self._update(store, job, stage="sheet")
                self._finish(store, job)
        except ToolError as error:
            cancelled = error.code == "cancelled"
            self._update(store, job, status="cancelled" if cancelled else "failed", error="" if cancelled else str(error)[:500],
                         errorCode=error.code, finishedAt=_now(), generationJob=None)
        except Exception as error:  # the job reports whatever stopped it
            self._update(store, job, status="failed", error=f"{error}"[:500], errorCode=getattr(error, "code", type(error).__name__),
                         finishedAt=_now(), generationJob=None)
        finally:
            self._tools.pop(job_id, None)

    def _video_cycle(self, store: JobStore, job: dict[str, Any], tools: LocalTools) -> None:
        """One guided clip, then one keyed frame per pose. A tool error fails the job the same way a pose does."""
        try:
            fill_video_takes(job, tools, workspace_root=self.deps.workspace_dir(job["workspace"]), uploads_root=self.deps.uploads_root(),
                             update=lambda **changes: self._update(store, job, **changes))
        except ToolError as error:
            for take in job["takes"]:
                if take["status"] not in ("ready", "reused"):
                    take.update(status="waiting") if error.code == "cancelled" else take.update(status="failed", error=str(error)[:300])
            raise

    def _finish(self, store: JobStore, job: dict[str, Any]) -> None:
        definition, workspace = job["definition"], job["workspace"]
        root = self.deps.workspace_dir(workspace)
        sheet = build_sheet([take["keyed"] for take in job["takes"]], uploads_root=self.deps.uploads_root(), workspace_root=root,
                            workspace=workspace, name=f"{job['kitId']}-{definition['id']}", scale_by=definition["scaleBy"], output_dir=root,
                            columns=definition.get("columns"))
        entry: dict[str, Any] = {
            "sheet": {key: sheet[key] for key in ("source", "width", "height", "count", "columns", "rows", "cell")},
            # What the author wrote for a pose stays with it, so that pose can be made again alone.
            "frames": [{"id": take["id"], "source": take["keyed"],
                        **({"prompt": pose["prompt"], "label": pose["label"]["en"]} if definition.get("custom") else {}),
                        **{key: take[key] for key in ("guide", "gait") if take.get(key)}}
                       for take, pose in zip(job["takes"], definition["poses"])],
            "fps": definition["fps"], "loop": definition["loop"], "facing": definition["facing"], "view": definition["view"],
            "scaleBy": definition["scaleBy"], "model": job["model"], "reviewState": "pending", "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **contract_of(definition["id"], definition), **clip_fields(job),
            **({"title": definition["title"]["es"]} if definition.get("custom") else {}), **({"prompt": job["prompt"]} if job.get("prompt") else {}),
        }
        normalize_kit_animations({definition["id"]: entry})
        self._save_on_kit(workspace, job["kitId"], definition["id"], entry)
        approval = self._auto_approve(job, sheet, definition) if job.get("autoApprove") else {}
        result = {"animation": definition["id"], "reviewState": approval.get("reviewState", "pending"), "sheet": sheet["source"], "count": sheet["count"],
                  "frames": [take["keyed"] for take in job["takes"]], "scaleBy": sheet["scaleBy"], **clip_fields(job),
                  **{key: approval[key] for key in ("autoApproved", "checks") if key in approval}}
        self._update(store, job, status="completed", finishedAt=_now(), generationJob=None, result=result,
                     **{key: approval[key] for key in ("autoApproved", "checks", "reviewNote") if key in approval})

    def _auto_approve(self, job: dict[str, Any], sheet: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
        """The agent's review of the animation just saved: approved when every automatic check passes, else it stays pending with the
        checks that failed. The approval is the same operation a review over MCP is (``review_kit_animation``, actor ``agent``)."""
        root = self.deps.workspace_dir(job["workspace"])
        siblings = sibling_sheets(self._kit(job["workspace"], job["kitId"]), definition, uploads_root=self.deps.uploads_root(), workspace_root=root)
        checks = sheet_checks(sheet, definition, siblings)
        outcome = {"autoApproved": False, "checks": checks, "reviewState": "pending", "reviewNote": summary(checks)}
        if failed(checks):
            return outcome
        try:
            review = review_kit_animation(self.deps.workspace_dir(job["workspace"]), job["kitId"], definition["id"], "approve", outcome["reviewNote"], "agent",
                                          services=self._services())
        except AnimationReviewError as error:  # the owner switched the mode off while the poses were made: a person decides
            return {**outcome, "reviewNote": str(error)}
        return {**outcome, "autoApproved": True, "reviewState": review["reviewState"]}

    def _save_on_kit(self, workspace: str, kit_id: str, animation_id: str, entry: dict[str, Any]) -> None:
        """Add the animation to the kit as it is now in the library: a character edited while the job ran keeps its edits."""
        root = self.deps.workspace_dir(workspace)
        for attempt in range(_SAVE_TRIES):
            library = read_character_kit_library(root)
            kit = (library.get("kits") or {}).get(kit_id)
            if not kit:
                raise AnimationJobError("kit_not_found", f"Character Kit {kit_id} is no longer in the library", 404)
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
            changed = {**kit, "animations": {**(kit.get("animations") or {}), animation_id: entry}, "updatedAt": stamp,
                       "provenance": [*(kit.get("provenance") or []), {"method": "character-animation-make", "animation": animation_id,
                                                                       "frames": [frame["id"] for frame in entry["frames"]], "model": entry["model"]}][-500:]}
            try:
                patch_character_kit(root, kit_id, changed, base_revision=int(library["revision"]), make_active=False)
                return
            except CharacterKitRevisionConflict:
                if attempt == _SAVE_TRIES - 1:
                    raise
