"""Render and cut an episode in every language with one call (``series.episode.produce``).

1x02 was a dozen tool calls per language, each followed by polling: render the
original, render each language version, then assemble each one. This job does
that on the server with the same tools (run in process, see ``local_mcp``):

1. ``series.episode.render_native`` with ``approve`` for the original, then for
   each language version. A render that ends with failed shots is resumed once.
   Only the shots without an approved take made from their current inputs are
   rendered (``stale_shots``), so producing again after a fix just recuts;
   ``rerender`` renders every shot again (after a change in the render code).
2. ``series.assembly.start`` for each language (subtitles burned in by
   default) and the chapter files when they are ready.

An episode with a staged review (``series_review``, mode ``plan`` or ``preview``) renders only what its review lets
through (``series_review_gate``) and, while shots still wait for an approval, stops before the cut as ``waiting`` with
those shots; resuming after the approvals renders again (previews' finals) and cuts.

Steps are saved as they finish, so a restart or a cancel resumes where it stopped.
Each step and the job carry ``progress``, the child job's own message (text, as
the UI shows it), and ``progressCount`` ``{done, total}``: finished shots or
clips. Missing counts stay null.
"""
from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from services.series_jobs import SeriesJobStore
from services.series_language_versions import LANGUAGES
from services.series_shot_plan import language_key

KIND = "produce"
RENDER_RETRIES = 1
# A cut that fails is made again once per run (a resume gives another run), like a render.
ASSEMBLY_RETRIES = 1
ACTIVE = ("queued", "running", "cancelling")
INTERRUPTED = "The server restarted during this production; resume to continue"
UP_TO_DATE = "Every shot already has an up-to-date approved take"


def _count(child: dict[str, Any]) -> dict[str, Any]:
    """Finished count from a render or a cut. ``done`` is how many are done."""
    done, total = child.get("current"), child.get("total")
    if type(done) is not int or type(total) is not int:
        done = total = None
    return {"done": done, "total": total}


def _show(job: dict, step: dict, progress: str | None, count: dict[str, Any]) -> None:
    """``progress`` stays text: stored jobs and the UI read it as a string."""
    step.update(progress=progress, progressCount=count)
    job.update(progress=progress, progressCount=count)


class ProduceError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.status = code, status


@dataclass
class ProduceDeps:
    call: Callable[[str, dict], dict]
    workspace_dir: Callable[[str], str]
    read_library: Callable[[str], dict]
    # (workspace, series, episode, language) -> shot ids whose approved take is missing or out of date.
    stale_shots: Callable[[str, str, str, str], list[str]] | None = None
    # (workspace, series, episode, language) -> shots a staged review (series_review) holds the cut for.
    review_blockers: Callable[[str, str, str, str], list[dict]] | None = None
    sleep: Callable[[float], None] = time.sleep
    poll_seconds: float = 5.0
    # Optional: a scripted H3 shot reads kits for its start frame, writes the take, or lets a test import it.
    read_kits: Callable[[str], dict] | None = None
    import_take: Callable[[dict], Any] | None = None
    write_library: Callable[[str, dict], Any] | None = None


def _result(reply: dict, label: str) -> dict:
    if not isinstance(reply, dict) or reply.get("_is_error"):
        error = (reply or {}).get("error") if isinstance(reply, dict) else None
        raise ProduceError("tool_failed", f"{label}: {(error or {}).get('message') if isinstance(error, dict) else reply}"[:500], 502)
    return reply.get("result") if isinstance(reply.get("result"), dict) else reply


class SeriesProduce:
    def __init__(self, deps: ProduceDeps) -> None:
        self.deps = deps
        self._threads: dict[str, threading.Thread] = {}
        self._cancel: set[str] = set()
        self._lock = threading.Lock()

    def _store(self, workspace: str) -> SeriesJobStore:
        return SeriesJobStore(self.deps.workspace_dir(workspace), KIND)

    def _languages(self, workspace: str, series_id: str, episode_id: str, wanted: list[str] | None) -> tuple[str, list[str]]:
        series = (self.deps.read_library(workspace).get("seriesById") or {}).get(series_id)
        episode = ((series or {}).get("episodesById") or {}).get(episode_id)
        if not series or not episode:
            raise ProduceError("not_found", "Series episode not found", 404)
        original = language_key(series)
        versions = sorted(episode.get("languageVersions") or {})
        languages = list(dict.fromkeys(wanted or [original, *versions]))
        unknown = [lang for lang in languages if lang != original and (lang not in LANGUAGES or lang not in versions)]
        if unknown:
            raise ProduceError("no_version", f"No language version for {', '.join(unknown)}; write it with series.episode.language_version.set", 400)
        return original, languages

    def start(self, workspace: str, series_id: str, episode_id: str, *, languages: list[str] | None = None,
              burn_subtitles: bool = True, rerender: bool = False) -> dict[str, Any]:
        original, languages = self._languages(workspace, series_id, episode_id, languages)
        if any(job.get("episodeId") == episode_id and job.get("status") in ACTIVE for job in self.jobs(workspace)):
            raise ProduceError("already_running", "This episode is already being produced")
        steps = [{"kind": kind, "language": lang, "status": "queued"} for kind in ("render", "assemble") for lang in languages]
        if self._has_video(workspace, series_id, episode_id):
            steps.insert(0, {"kind": "video", "language": original, "status": "queued"})
        job = {"jobId": f"produce-{uuid.uuid4().hex[:12]}", "workspace": workspace, "seriesId": series_id, "episodeId": episode_id,
               "original": original, "languages": languages, "burnSubtitles": bool(burn_subtitles), "rerender": bool(rerender),
               "status": "queued",
               "steps": steps, "chapters": {}, "createdAt": time.time(), "message": "Queued"}
        self._launch(workspace, job)
        return job

    def jobs(self, workspace: str) -> list[dict[str, Any]]:
        return [self._reconcile(workspace, job) for job in self._store(workspace).list()]

    def status(self, workspace: str, job_id: str) -> dict[str, Any]:
        job = self._store(workspace).load(job_id)
        if not job:
            raise ProduceError("not_found", "Production job not found", 404)
        return self._reconcile(workspace, job)

    def _reconcile(self, workspace: str, job: dict) -> dict:
        """A production that says it is running without a live thread here was cut by a restart: interrupted, once."""
        if job.get("status") not in ACTIVE:
            return job
        thread = self._threads.get(job["jobId"])
        if thread is not None and (thread.ident is None or thread.is_alive()):
            return job
        if thread is not None:
            # The worker may have finished after the caller read its running checkpoint.
            job = self._store(workspace).load(job["jobId"]) or job
            if job.get("status") not in ACTIVE:
                return job
        for step in job.get("steps") or []:
            if step.get("status") == "running":
                step["status"] = "queued"
        job.update(status="interrupted", message=INTERRUPTED, finishedAt=time.time())
        self._store(workspace).save(job)
        return job

    def cancel(self, workspace: str, job_id: str) -> dict[str, Any]:
        job = self.status(workspace, job_id)
        with self._lock:
            self._cancel.add(job_id)
        if job["status"] in ACTIVE:
            step = next((item for item in job["steps"] if item["status"] == "running" and item.get("jobId")), None)
            if step and step["kind"] == "render":
                self.deps.call("series.episode.render_native.cancel", self._args(job, job_id=step["jobId"]))
            elif step and step["kind"] == "video":
                # The clip already sent would keep the GPU until it ends.
                from services.series_video_shots import cancel_generation
                cancel_generation(self.deps, step["jobId"])
            job.update(status="cancelling", message="Stopping after the current step")
            self._store(workspace).save(job)
        return job

    def resume(self, workspace: str, job_id: str) -> dict[str, Any]:
        job = self.status(workspace, job_id)
        if job["status"] in ACTIVE:
            return job
        for step in job["steps"]:
            if step["status"] != "done":
                step.update(status="queued", error=None, retries=0)
        job.update(status="queued", message="Resuming", error=None)
        self._launch(workspace, job)
        return job

    def _launch(self, workspace: str, job: dict) -> None:
        """Save the job and run it on a thread; the thread is registered before the save so a reader never sees an orphan.

        A resume can arrive while the run that just saved "failed" is still returning: wait for that thread to end,
        or the resume would see it alive and start nothing."""
        job_id = job["jobId"]
        closing = self._threads.get(job_id)
        if closing is not None and closing.is_alive() and closing is not threading.current_thread():
            closing.join(timeout=10)
        with self._lock:
            running = self._threads.get(job_id)
            if running and running.is_alive():
                return
            self._cancel.discard(job_id)
            thread = threading.Thread(target=self._run, args=(workspace, job_id), name=f"series-produce-{job_id}", daemon=True)
            self._threads[job_id] = thread
        self._store(workspace).save(job)
        thread.start()

    # Worker --------------------------------------------------------------

    def _save(self, job: dict, **patch: Any) -> None:
        job.update(patch)
        self._store(job["workspace"]).save(job)

    def _cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancel

    @staticmethod
    def _args(job: dict, **data: Any) -> dict[str, Any]:
        return {"version": 1, "input": {"workspace": job["workspace"], **data}}

    def _run(self, workspace: str, job_id: str) -> None:
        job = self.status(workspace, job_id)
        self._save(job, status="running", message="Producing")
        for step in job["steps"]:
            if step["status"] == "done":
                continue
            if self._cancelled(job_id):
                self._save(job, status="cancelled", message="Cancelled; resume to continue")
                return
            if step["kind"] == "assemble" and self._waits_for_review(job, step):
                return
            if step["kind"] == "video":
                if self._spend_video(job, step):
                    return
                continue
            self._save(job, message=f"{step['kind'].capitalize()} {step['language']}")
            step["status"] = "running"
            try:
                (self._render if step["kind"] == "render" else self._assemble)(job, step)
                step.update(status="done", error=None)
            except Exception as error:  # report the step; later steps need it
                step.update(status="failed", error=f"{type(error).__name__}: {error}"[:500])
                self._save(job, status="cancelled" if self._cancelled(job_id) else "failed", finishedAt=time.time(),
                           message=f"{step['kind'].capitalize()} {step['language']} failed; resume to retry")
                return
            self._save(job)
        self._save(job, status="completed", finishedAt=time.time(),
                   message=f"Rendered and cut in {', '.join(job['languages'])}")

    def _has_video(self, workspace: str, series_id: str, episode_id: str) -> bool:
        """True when a shot stores a ``video`` object. A plain imported take does not."""
        from services.series_video_shots import needs_video_step
        series = (self.deps.read_library(workspace).get("seriesById") or {}).get(series_id) or {}
        episode = (series.get("episodesById") or {}).get(episode_id) or {}
        return needs_video_step(episode)

    def _spend_video(self, job: dict, step: dict) -> bool:
        """Generate the scripted clips. True when this run stops (waiting on a plan, or the step failed)."""
        from services.series_video_shots import produce_videos
        step["status"] = "running"
        self._save(job, message=f"Video {step['language']}")
        try:
            held = produce_videos(job, step, self.deps, cancelled=lambda: self._cancelled(job["jobId"]),
                                  save=lambda: self._save(job))
        except Exception as error:
            step.update(status="failed", error=f"{type(error).__name__}: {error}"[:500])
            self._save(job, status="cancelled" if self._cancelled(job["jobId"]) else "failed", finishedAt=time.time(),
                       message="Video failed; resume to retry")
            return True
        if held:
            self._save(job)
            return True
        step.update(status="done", error=None)
        self._save(job)
        return False

    def _waits_for_review(self, job: dict, step: dict) -> bool:
        """A staged episode is cut once every shot passed its review. Until then the production stops as ``waiting``
        (not failed) with the shots it waits for; its renders run again on resume, so approved previews get their finals."""
        blockers = self.deps.review_blockers(job["workspace"], job["seriesId"], job["episodeId"], step["language"]) \
            if self.deps.review_blockers else []
        if not blockers:
            job.pop("waiting", None)
            return False
        for item in job["steps"]:
            if item["kind"] == "render":
                item.update(status="queued", jobId=None, retries=0, progress=None, progressCount=None)
        plans = sum(1 for item in blockers if item["reason"] == "plan")
        previews = sum(1 for item in blockers if item["reason"] == "preview")
        self._save(job, status="waiting", waiting=blockers, finishedAt=time.time(),
                   message=f"Waiting for the review: {plans} plans and {previews} previews to approve, "
                           f"{len(blockers) - plans - previews} finals to render; approve them and resume")
        return True

    def _wait(self, job: dict, step: dict, tool: str) -> dict[str, Any]:
        """The step's job when it stops; ``{"status": "unknown"}`` when the server no longer knows it."""
        while True:
            reply = self.deps.call(tool, self._args(job, job_id=step["jobId"]))
            error = reply.get("error") if isinstance(reply, dict) and reply.get("_is_error") else None
            if isinstance(error, dict) and (error.get("status") == 404 or error.get("code") == "not_found"):
                return {"status": "unknown", "message": f"{step['kind']} job {step['jobId']} is gone"}
            current = _result(reply, tool)["job"]
            _show(job, step, current.get("message"), _count(current))
            self._save(job)
            if current.get("status") not in ACTIVE:
                return current
            self.deps.sleep(self.deps.poll_seconds)

    def _render(self, job: dict, step: dict) -> None:
        if not step.get("jobId"):
            data = {"series_id": job["seriesId"], "episode_id": job["episodeId"], "approve": True}
            if step["language"] != job["original"]:
                data["language"] = step["language"]
            if self.deps.stale_shots and not job.get("rerender"):
                stale = self.deps.stale_shots(job["workspace"], job["seriesId"], job["episodeId"], step["language"])
                if not stale:
                    _show(job, step, UP_TO_DATE, {"done": 0, "total": 0})
                    return
                data["shot_ids"] = stale
                step["shots"] = len(stale)
            step["jobId"] = _result(self.deps.call("series.episode.render_native", self._args(job, **data)), "render")["job"]["jobId"]
            self._save(job)
        while True:
            render = self._wait(job, step, "series.episode.render_native.status")
            if render["status"] == "completed":
                return
            failed = [f"{item['shotId']}: {item.get('error')}" for item in render.get("items") or [] if item.get("status") == "failed"]
            # A failed, stopped or interrupted render is resumed (once per run): resuming a production resumes its render.
            if self._cancelled(job["jobId"]) or step.get("retries", 0) >= RENDER_RETRIES:
                raise ProduceError("render_failed", "; ".join(failed[:4]) or render.get("message") or render["status"])
            step["retries"] = step.get("retries", 0) + 1
            if render["status"] == "unknown":
                # The server forgot the render (a restart with a lost store): ask for a new one.
                step["jobId"] = None
                self._save(job)
                return self._render(job, step)
            _result(self.deps.call("series.episode.render_native.resume", self._args(job, job_id=step["jobId"])), "resume render")

    def _assemble(self, job: dict, step: dict) -> None:
        if not step.get("jobId"):
            data = {"series_id": job["seriesId"], "episode_id": job["episodeId"], "burn_subtitles": job["burnSubtitles"]}
            if step["language"] != job["original"]:
                data["language"] = step["language"]
            step["jobId"] = _result(self.deps.call("series.assembly.start", self._args(job, **data)), "assemble")["job"]["jobId"]
            self._save(job)
        cut = self._wait(job, step, "series.assembly.status")
        if cut.get("status") != "completed":
            # A failed, interrupted or forgotten cut is made again (once per run): resuming a production recuts.
            if self._cancelled(job["jobId"]) or step.get("retries", 0) >= ASSEMBLY_RETRIES:
                raise ProduceError("assembly_failed", cut.get("error") or cut.get("message") or cut.get("status"))
            step.update(retries=step.get("retries", 0) + 1, jobId=None)
            self._save(job)
            return self._assemble(job, step)
        job["chapters"][step["language"]] = self._chapter(job, cut)

    def _chapter(self, job: dict, cut: dict) -> dict[str, Any]:
        series = (self.deps.read_library(job["workspace"]).get("seriesById") or {}).get(job["seriesId"]) or {}
        meta = ((series.get("assets") or {}).get(cut.get("assetId")) or {}).get("metadata") or {}
        subtitles = meta.get("subtitles") or {}
        return {"assetId": cut.get("assetId"), "file": cut.get("filename"), "subtitledFile": subtitles.get("file"),
                "srt": subtitles.get("srt"), "loudness": (meta.get("loudness") or {}).get("after")}


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key != "workspace"}
