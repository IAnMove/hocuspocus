"""Make one animation of a character on the server: the Character Creator, the MCP tools and the Wizard all start this job.

An animation is a few poses of the same figure (``services/character_animations.py``). The job makes every pose in turn with the
character's own picture as the identity reference (``generation.image``), keys each on its screen colour (``studio.key``), joins
them into a sprite sheet and saves it on the kit as ``animations.<id>`` waiting for a person's review: the job never approves.

* A pose that was made stays when the job fails, is cancelled or is cut by a restart: the next job for that animation keeps those
  poses and makes the rest. ``pose`` makes one pose of a finished animation again and keeps the others.
* One animation is made at a time on the server (one GPU); a second request for the same animation returns the running job.
* A job is a small file under ``.character-animation-jobs-v1`` of the workspace, so it can be followed after a reload and listed.
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from services.character_animations import CharacterAnimationError, animation_def, build_sheet, normalize_kit_animations, pose_prompt
from services.character_kit_library import CharacterKitRevisionConflict, patch_character_kit, read_character_kit_library
from services.local_generation import LocalTools, ToolError, file_url

JOBS_DIR = ".character-animation-jobs-v1"
ACTIVE = ("queued", "running", "cancelling")
RESUMABLE = ("failed", "cancelled", "interrupted")
INTERRUPTED = "The server restarted while this animation was being made; make it again and the poses already made are kept"
DEFAULT_MODEL = "qwen_image_21"
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_SAVE_TRIES = 4


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

    def __init__(self, root: str) -> None:
        self.directory = os.path.join(root, JOBS_DIR)

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
    return {key: value for key, value in job.items() if key not in {"definition", "reference", "description", "style"}}


class CharacterAnimationJobs:
    # One GPU: animations of every workspace are made one after another.
    _gpu = threading.Lock()

    def __init__(self, deps: AnimationJobDeps) -> None:
        self.deps = deps
        self._threads: dict[str, threading.Thread] = {}
        self._tools: dict[str, LocalTools] = {}
        self._guard = threading.Lock()

    def _store(self, workspace: str) -> JobStore:
        return JobStore(self.deps.workspace_dir(workspace))

    def _kit(self, workspace: str, kit_id: str) -> dict[str, Any]:
        kit = (read_character_kit_library(self.deps.workspace_dir(workspace)).get("kits") or {}).get(kit_id)
        if not kit:
            raise AnimationJobError("kit_not_found", f"Character Kit {kit_id} is not in the {workspace} workspace", 404)
        return kit

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
        thread = self._threads.get(job.get("jobId", ""))
        if job.get("status") not in ACTIVE or (thread is not None and (thread.ident is None or thread.is_alive())):
            return job
        if thread is not None:
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
        return {take["id"]: take["keyed"] for take in latest.get("takes") or [] if take.get("keyed") and take["status"] in ("ready", "reused") and take["id"] in ids}

    def start(self, workspace: str, kit_id: str, animation_id: str, *, custom: dict[str, Any] | None = None, pose: str | None = None,
              model: str | None = None) -> dict[str, Any]:
        """Make (or, with ``pose``, make one pose again of) an animation of a saved character. Returns the job; a request for an
        animation that is already being made returns that job."""
        kit = self._kit(workspace, kit_id)
        made = (kit.get("animations") or {}).get(animation_id)
        try:
            definition = animation_def(animation_id, made=made, custom=custom)
        except CharacterAnimationError as error:
            raise AnimationJobError("invalid_animation", str(error)) from error
        ids = [item["id"] for item in definition["poses"]]
        if pose and (pose not in ids or not made):
            raise AnimationJobError("pose_not_found", f"{animation_id} has no made pose {pose} to make again", 404)
        reference = reference_of(kit)
        if not reference:
            raise AnimationJobError("no_reference", f"Character Kit {kit.get('name') or kit_id} has no persistent picture to make poses from")
        if model and not _MODEL.fullmatch(model):
            raise AnimationJobError("invalid_model", "model is the id of an image model")
        with self._guard:
            for job in self.jobs(workspace, kit_id):
                if job.get("animationId") == animation_id and job.get("status") in ACTIVE:
                    return job
            kept = self._kept(workspace, kit, animation_id, pose, ids)
            takes = [{"id": item, "status": "reused", "keyed": kept[item], "seed": 0} if item in kept else
                     {"id": item, "status": "waiting", "seed": random.randrange(2_000_000_000)} for item in ids]
            job = {"jobId": f"anim-{uuid.uuid4().hex[:12]}", "workspace": workspace, "kitId": kit_id, "animationId": animation_id,
                   "title": definition["title"]["en"], "model": model or DEFAULT_MODEL, "status": "queued", "stage": "poses", "takes": takes,
                   "remake": pose, "createdAt": _now(), "updatedAt": _now(), "definition": definition, "reference": reference,
                   # What the author wrote stays visible on the job, so an animation that is not on the kit yet can be shown and tried again.
                   **({"custom": {"title": definition["title"]["es"], "view": definition["view"], "poses": [item["prompt"] for item in definition["poses"]]}}
                      if definition.get("custom") else {}),
                   "description": (kit.get("lookNotes") or "").strip() or kit.get("name") or kit_id, "style": style_of(kit)}
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

    def _image_params(self, job: dict[str, Any], built: dict[str, str], seed: int) -> dict[str, Any]:
        """One pose's request: the character's picture is the identity reference. The default model runs the settings that work for it;
        another model runs its own steps and guidance, and a distilled one (a few steps) takes no negative prompt."""
        steps, guidance = 40, 1
        if job["model"] != DEFAULT_MODEL and self.deps.model_defaults:
            own = self.deps.model_defaults(job["model"]) or {}
            steps, guidance = own.get("num_inference_steps") or steps, own.get("guidance_scale") or guidance
        params: dict[str, Any] = {"prompt": built["prompt"], "model_type": job["model"], "resolution": built["resolution"], "seed": seed,
                                  "guidance_scale": guidance, "num_inference_steps": steps, "image_refs": [job["reference"]], "video_prompt_type": "I"}
        if steps > 8:
            params["negative_prompt"] = built["negative"]
        return params

    def _take(self, store: JobStore, job: dict[str, Any], take: dict[str, Any], tools: LocalTools, pose: dict[str, Any]) -> None:
        definition = job["definition"]
        built = pose_prompt(definition["id"], pose["id"], job["description"], job.get("style"),
                            custom={"view": definition["view"], "text": pose["prompt"]} if definition.get("custom") else None)
        params = self._image_params(job, built, take["seed"])
        job.setdefault("prompt", built["prompt"])
        take["status"] = "generating"
        self._update(store, job)
        # The file name carries the job: a pose made again never overwrites the picture the saved animation still uses.
        name = tools.image(f"{job['jobId']}-{pose['id']}-image", params, f"{job['kitId']}-{definition['id']}-{pose['id']}-{job['jobId'][-6:]}")
        take.update(status="keying", raw=file_url(name, job["workspace"]))
        self._update(store, job)
        take.update(status="ready", keyed=tools.key(f"{job['jobId']}-{pose['id']}-key", name, built["screen"]))
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

    def _finish(self, store: JobStore, job: dict[str, Any]) -> None:
        definition, workspace = job["definition"], job["workspace"]
        root = self.deps.workspace_dir(workspace)
        sheet = build_sheet([take["keyed"] for take in job["takes"]], uploads_root=self.deps.uploads_root(), workspace_root=root,
                            workspace=workspace, name=f"{job['kitId']}-{definition['id']}", scale_by=definition["scaleBy"], output_dir=root)
        entry: dict[str, Any] = {
            "sheet": {key: sheet[key] for key in ("source", "width", "height", "count", "columns", "rows", "cell")},
            # What the author wrote for a pose stays with it, so that pose can be made again alone.
            "frames": [{"id": take["id"], "source": take["keyed"],
                        **({"prompt": pose["prompt"], "label": pose["label"]["en"]} if definition.get("custom") else {})}
                       for take, pose in zip(job["takes"], definition["poses"])],
            "fps": definition["fps"], "loop": definition["loop"], "facing": definition["facing"], "view": definition["view"],
            "scaleBy": definition["scaleBy"], "model": job["model"], "reviewState": "pending", "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **({"title": definition["title"]["es"]} if definition.get("custom") else {}), **({"prompt": job["prompt"]} if job.get("prompt") else {}),
        }
        normalize_kit_animations({definition["id"]: entry})
        self._save_on_kit(workspace, job["kitId"], definition["id"], entry)
        self._update(store, job, status="completed", finishedAt=_now(), generationJob=None, result={
            "animation": definition["id"], "reviewState": "pending", "sheet": sheet["source"], "count": sheet["count"],
            "frames": [take["keyed"] for take in job["takes"]], "scaleBy": sheet["scaleBy"]})

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
