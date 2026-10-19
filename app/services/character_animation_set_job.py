"""Make several animations of a character in turn as ONE server job: the full walks of the five directions.

``characters.animation.make_set`` (MCP), ``make_character_animation_set`` (Wizard) and the button «Crear andares completos» of
Characters › Animaciones start the same job (``POST /api/v1/character-kits/animations/make-set``). A set is a list of sheets in
``app/shared/character_animations.json`` (``sets``): ``walk-12`` (the profile walk), ``walk-directions`` (the profile and the four other
directions) and ``idle-directions``. The job takes the sheets the character does not have yet, one after the other (the GPU makes one
animation at a time), and each one is an ordinary animation job (``services/character_animation_job.py``) of its own, so it shows its
poses in the panel as any other.

* The first sheet is drawn from the character's own picture. Each next sheet also gets, as a second reference, the first pose of the
  sheet its catalog entry names (``reference``): the direction next to it, so the identity carries from one direction to the next.
* The job saves every sheet as pending, like the single job. With ``autoApprove`` («Modo un solo disparo», ``agent_autonomy`` =
  ``one_shot``) each child approves its own sheet when it passes the automatic checks, including that the sheet is not a copy or the
  mirror of another direction of the character; a sheet that fails stays pending and the job goes on with the next one.
* It is resumable. A failure, a cancel or a restart stops the job where it was and keeps every sheet and pose already made: starting the
  set again skips the sheets the character has and makes the rest, and the sheet that stopped keeps its poses.
* A job is a small file under ``.character-animation-set-jobs-v1`` of the workspace (id ``animset-...``), so it can be followed after a
  reload. One set at a time per character and set: a second request returns the running one.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from services.character_animation_job import ACTIVE, DEFAULT_MODEL, AnimationJobError, CharacterAnimationJobs, JobStore, reference_of
from services.character_animations import MAX_ANIMATIONS, catalog

_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")

SETS_DIR = ".character-animation-set-jobs-v1"
PREFIX = "animset-"
POLL_SECONDS = 0.5
ALREADY_MADE = "already made"
INTERRUPTED = "The server restarted while this set was being made; make it again and the sheets and poses already made are kept"
DONE = ("completed", "skipped")


def _now() -> float:
    return time.time()


def public(job: dict[str, Any]) -> dict[str, Any]:
    """The job as a client reads it: its sheets and how many are done."""
    sheets = job.get("sheets") or []
    return {**job, "done": sum(1 for sheet in sheets if sheet["status"] in DONE), "total": len(sheets)}


class CharacterAnimationSets:
    def __init__(self, jobs: CharacterAnimationJobs, *, poll: float = POLL_SECONDS) -> None:
        self.animations, self.poll = jobs, poll
        self._threads: dict[str, threading.Thread] = {}
        self._guard = threading.Lock()
        jobs.live_sources.append(self.live_jobs)

    def _store(self, workspace: str) -> JobStore:
        return JobStore(self.animations.deps.workspace_dir(workspace), SETS_DIR)

    def _alive(self, job_id: str) -> bool:
        thread = self._threads.get(job_id)
        return thread is not None and (thread.ident is None or thread.is_alive())

    # ----- reading -----

    def live_jobs(self, workspace_dir: str) -> list[dict[str, Any]]:
        """The set jobs in this folder that a worker of this service is running (the ``services.workspace_busy`` probe). Reads only."""
        return [{"jobId": job["jobId"], "status": job["status"], "workspace": job.get("workspace")} for job in JobStore(workspace_dir, SETS_DIR).list()
                if job.get("status") in ACTIVE and self._alive(str(job.get("jobId") or ""))]

    def _reconcile(self, workspace: str, job: dict[str, Any]) -> dict[str, Any]:
        """A set that says it is active but has no worker here was cut by a restart: interrupted, what was made kept."""
        if job.get("status") not in ACTIVE or self._alive(job.get("jobId", "")):
            return job
        job.update(status="interrupted", error=INTERRUPTED, finishedAt=_now(), updatedAt=_now())
        for sheet in job.get("sheets") or []:
            if sheet["status"] == "running":
                sheet["status"] = "waiting"
        self._store(workspace).save(job)
        return job

    def jobs(self, workspace: str, kit_id: str | None = None) -> list[dict[str, Any]]:
        listed = [self._reconcile(workspace, job) for job in self._store(workspace).list()]
        return [public(job) for job in listed if not kit_id or job.get("kitId") == kit_id]

    def status(self, workspace: str, job_id: str) -> dict[str, Any]:
        job = self._store(workspace).load(job_id)
        if not job:
            raise AnimationJobError("job_not_found", "Animation set job not found", 404)
        return public(self._reconcile(workspace, job))

    # ----- starting -----

    def _spec(self, set_name: str) -> dict[str, Any]:
        spec = (catalog().get("sets") or {}).get(set_name)
        if not spec:
            raise AnimationJobError("invalid_set", f"Unknown set {set_name}; one of {', '.join(catalog().get('sets') or {})}")
        return spec

    def _new_job(self, workspace: str, kit: dict[str, Any], set_name: str, spec: dict[str, Any], model: str | None, auto_approve: bool) -> dict[str, Any]:
        made = kit.get("animations") or {}
        sheets = [{"animationId": step["animation"], "status": "skipped", "reason": ALREADY_MADE} if step["animation"] in made else
                  {"animationId": step["animation"], "status": "waiting"} for step in spec["sheets"]]
        return {"jobId": f"{PREFIX}{uuid.uuid4().hex[:12]}", "kind": "set", "workspace": workspace, "kitId": kit["id"], "set": set_name, "title": spec["title"]["en"],
                "model": model or DEFAULT_MODEL, "status": "queued", "sheets": sheets, "createdAt": _now(), "updatedAt": _now(),
                **self.animations.auto_fields(auto_approve)}

    def start(self, workspace: str, kit_id: str, set_name: str, *, model: str | None = None, auto_approve: bool = False) -> dict[str, Any]:
        """Make the sheets of ``set_name`` that the character does not have. Returns the job (the running one when this character is already
        making this set). Nothing is asked of the model before the request passes."""
        if model and not _MODEL.fullmatch(model):
            raise AnimationJobError("invalid_model", "model is the id of an image model")
        spec = self._spec(set_name)
        kit = self.animations.kit(workspace, kit_id)
        if not reference_of(kit):
            raise AnimationJobError("no_reference", f"Character Kit {kit.get('name') or kit['id']} has no persistent picture to make poses from")
        with self._guard:
            running = next((job for job in self.jobs(workspace, kit_id) if job.get("set") == set_name and job.get("status") in ACTIVE), None)
            if running:
                return running
            job = self._new_job(workspace, kit, set_name, spec, model, auto_approve)
            missing = [sheet for sheet in job["sheets"] if sheet["status"] == "waiting"]
            if len(kit.get("animations") or {}) + len(missing) > MAX_ANIMATIONS:
                raise AnimationJobError("animation_limit", f"{kit.get('name') or kit['id']} keeps at most {MAX_ANIMATIONS} animations and this set adds {len(missing)}")
            store = self._store(workspace)
            if not missing:
                job.update(status="completed", finishedAt=_now())
                store.save(job)
                return public(job)
            store.save(job)
            thread = threading.Thread(target=self._run, args=(workspace, job["jobId"]), name=f"character-animation-set-{job['jobId']}", daemon=True)
            self._threads[job["jobId"]] = thread
        if self.animations.deps.inline:
            thread.run()
            return public(store.load(job["jobId"]) or job)
        thread.start()
        return public(job)

    def cancel(self, workspace: str, job_id: str) -> dict[str, Any]:
        store = self._store(workspace)
        job = store.load(job_id)
        if not job:
            raise AnimationJobError("job_not_found", "Animation set job not found", 404)
        job = self._reconcile(workspace, job)
        if job.get("status") not in ACTIVE:
            return public(job)
        job.update(status="cancelling", updatedAt=_now())
        store.save(job)
        self._cancel_children(workspace, job)
        return public(job)

    def _cancel_children(self, workspace: str, job: dict[str, Any]) -> None:
        """Stop the sheet being made now. It is found among the character's animation jobs, not in the set's record, which only learns
        the child's id when the child has started."""
        ids = {sheet["animationId"] for sheet in job.get("sheets") or []}
        for child in self.animations.jobs(workspace, job["kitId"]):
            if child.get("animationId") in ids and child.get("status") in ("queued", "running"):
                self.animations.cancel(workspace, child["jobId"])

    # ----- the worker -----

    def _cancelled(self, store: JobStore, job_id: str) -> bool:
        return (store.load(job_id) or {}).get("status") == "cancelling"

    def _update(self, store: JobStore, job: dict[str, Any], **changes: Any) -> None:
        job.update(changes, updatedAt=_now())
        if (store.load(job["jobId"]) or {}).get("status") == "cancelling" and job.get("status") == "running":
            job["status"] = "cancelling"  # a cancel that arrived while a step ran is not lost
        store.save(job)

    def _reference(self, kit: dict[str, Any], step: dict[str, Any]) -> tuple[str | None, list[str]]:
        """The first pose of the sheet this one follows, when the character has it (and it was not rejected)."""
        named = step.get("reference")
        made = (kit.get("animations") or {}).get(named) if named else None
        frames = made.get("frames") if isinstance(made, dict) and made.get("reviewState") != "rejected" else None
        source = (frames[0] or {}).get("source") if frames else None
        return (named, [source]) if source and not str(source).startswith("blob:") else (None, [])

    def _wait(self, store: JobStore, job: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
        """Follow the sheet's own job until it ends; a cancel of the set reaches it."""
        stopped = False
        while child.get("status") in ACTIVE:
            if not stopped and self._cancelled(store, job["jobId"]):
                self._cancel_children(job["workspace"], job)
                stopped = True
            time.sleep(self.poll)
            child = self.animations.status(job["workspace"], child["jobId"])
        return child

    def _record(self, sheet: dict[str, Any], child: dict[str, Any]) -> None:
        sheet.update(status=child["status"] if child["status"] in ("completed", "cancelled") else "failed", jobId=child["jobId"])
        if child["status"] == "completed":
            sheet.update(reviewState=(child.get("result") or {}).get("reviewState", "pending"))
            if "checks" in child:
                sheet.update(autoApproved=bool(child.get("autoApproved")), failed=[check["id"] for check in child["checks"] if not check["ok"]])
        elif child.get("error"):
            sheet["error"] = child["error"]

    def _make(self, store: JobStore, job: dict[str, Any], sheet: dict[str, Any], step: dict[str, Any]) -> str:
        """Make one sheet through the animation job; returns the sheet's final status."""
        workspace = job["workspace"]
        kit = self.animations.kit(workspace, job["kitId"])
        if sheet["animationId"] in (kit.get("animations") or {}):
            sheet.update(status="skipped", reason=ALREADY_MADE)
            return "skipped"
        named, refs = self._reference(kit, step)
        sheet.update(status="running", **({"reference": named} if named else {}))
        self._update(store, job)
        child = self.animations.start(workspace, job["kitId"], sheet["animationId"], model=job["model"], auto_approve=bool(job.get("autoApprove")), references=refs)
        sheet["jobId"] = child["jobId"]
        self._update(store, job)
        self._record(sheet, self._wait(store, job, child))
        return sheet["status"]

    def _run(self, workspace: str, job_id: str) -> None:
        store = self._store(workspace)
        job = store.load(job_id) or {}
        steps = {step["animation"]: step for step in self._spec(job["set"])["sheets"]}
        outcome = "completed"
        try:
            self._update(store, job, status="running")
            for sheet in job["sheets"]:
                if sheet["status"] != "waiting":
                    continue
                if self._cancelled(store, job_id):
                    outcome = "cancelled"
                    break
                outcome = {"cancelled": "cancelled", "completed": "completed", "skipped": "completed"}.get(self._make(store, job, sheet, steps[sheet["animationId"]]), "failed")
                self._update(store, job)
                if outcome != "completed":
                    break
            error = next((f"{sheet['animationId']}: {sheet['error']}" for sheet in job["sheets"] if sheet["status"] == "failed" and sheet.get("error")), "")
            self._update(store, job, status=outcome, finishedAt=_now(), **({"error": error[:500]} if outcome == "failed" else {}))
        except Exception as error:  # the job reports whatever stopped it
            for sheet in job.get("sheets") or []:
                if sheet["status"] == "running":
                    sheet.update(status="failed", error=f"{error}"[:300])
            self._update(store, job, status="failed", error=f"{error}"[:500], errorCode=getattr(error, "code", type(error).__name__), finishedAt=_now())
