"""Produce the pending assets of one game, one asset at a time.

The shape follows ``series_produce.py``. A dependency that is not approved is
skipped; resume runs that step once the dependency is approved. This job never
approves an asset. Animation grouping waits for J6.
"""
from __future__ import annotations

import contextlib
import copy
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.game_estimate import record_run
from services.game_generators import REGISTRY
from services.game_generators.base import GenContext
from services.game_inputs import asset_inputs
from services.game_jobs import GameJobStore
from services.game_library import add_attempt, read_library, write_library
from services.game_tools import GameToolError

ACTIVE = ("queued", "running", "cancelling")
_OPEN = {"pending", "rejected", "failed"}
_TERMINAL = {"done", "failed", "skipped"}
_TIERS = (
    ("character",),
    ("sprite", "item", "icon", "ui", "tile", "tileset", "background"),
    ("animation", "vfx"),
    ("model3d", "character3d"),
    ("sfx", "music", "jingle", "voice"),
)
_RANK = {kind: tier for tier, group in enumerate(_TIERS) for kind in group}
INTERRUPTED = "The server restarted during this production; resume to continue"


class ProduceError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 409, problems: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.code, self.status, self.problems = code, status, problems


@dataclass
class ProduceDeps:
    call: Callable[[str, dict], dict]
    loopback: Callable[[str, dict], dict]
    workspace_dir: Callable[[str], str]
    read_game: Callable[[str, str], dict]
    write_attempt: Callable[..., None]
    inline: bool = False
    lock: Any = None


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key != "workspace"}


def _owns(name: str, asset_id: str, others: list[str]) -> bool:
    """True when the file belongs to this asset and not to a longer sibling id."""
    if not name.startswith(f"{asset_id}-"):
        return False
    return not any(len(other) > len(asset_id) and name.startswith(f"{other}-") for other in others)


def archive_raw_outputs(workspace: str, game: dict[str, Any], asset_id: str, attempt_id: str) -> list[str]:
    """Move ``<asset-id>-*`` files from the workspace root into the attempt's ``raw/``.

    A longer id wins: ``heroe-idle-still.png`` stays when the asset is ``heroe``
    and ``heroe-idle`` is also in the game. Files stay put until the asset succeeds.
    """
    root = Path(workspace)
    if not root.is_dir():
        return []
    others = [str(item.get("id")) for item in game.get("assets") or [] if item.get("id") and item.get("id") != asset_id]
    dest = root / "game" / str(game.get("id") or "game") / asset_id / attempt_id / "raw"
    moved = []
    for path in list(root.iterdir()):
        if path.is_file() and _owns(path.name, asset_id, others):
            dest.mkdir(parents=True, exist_ok=True)
            path.replace(dest / path.name)
            moved.append(path.name)
    return moved


class GameProduce:
    def __init__(self, deps: ProduceDeps) -> None:
        self.deps = deps
        self._threads: dict[str, threading.Thread] = {}
        self._cancel: set[str] = set()
        self._lock = threading.Lock()
        # Held across the busy check and the first save, so two starts cannot both pass.
        self._admit = threading.Lock()

    def _store(self, workspace: str) -> GameJobStore:
        return GameJobStore(self.deps.workspace_dir(workspace))

    def _library(self) -> Any:
        """The library lock, re-entrant in the app. Tests without one get a no-op."""
        return self.deps.lock if self.deps.lock is not None else contextlib.nullcontext()

    def start(self, workspace: str, game_id: str, asset_ids: list[str] | None = None, kinds: list[str] | None = None,
              rerender: bool = False, candidates: int | None = None) -> dict[str, Any]:
        game = self.deps.read_game(workspace, game_id)
        steps = _group_animation_steps(_steps(game, asset_ids, kinds, rerender))
        job = {
            "jobId": f"game-produce-{uuid.uuid4().hex[:8]}", "workspace": workspace, "gameId": game_id,
            "status": "completed" if not steps else "queued", "rerender": bool(rerender), "candidates": candidates,
            "steps": steps, "createdAt": time.time(), "message": "Nothing to produce" if not steps else "Queued",
        }
        with self._admit:
            self.check_idle(workspace, game_id)
            if not steps:
                job["finishedAt"] = time.time()
                self._store(workspace).save(job)
                return job
            thread = self._register(workspace, job)
        self._go(workspace, job["jobId"], thread)
        return self._store(workspace).load(job["jobId"]) or job

    def check_idle(self, workspace: str, game_id: str) -> None:
        """Raise ``already_running`` (409) while another job for this game is active."""
        if any(job.get("gameId") == game_id and job.get("status") in ACTIVE for job in self.jobs(workspace)):
            raise ProduceError("already_running", "This game is already being produced")

    def jobs(self, workspace: str) -> list[dict[str, Any]]:
        return [self._reconcile(workspace, job) for job in self._store(workspace).list()]

    def status(self, workspace: str, job_id: str) -> dict[str, Any]:
        try:
            job = self._store(workspace).load(job_id)
        except ValueError:  # a blank or path-like id names no checkpoint; an unreadable one is gone too
            job = None
        if not job:
            raise ProduceError("not_found", "Production job not found", 404)
        return self._reconcile(workspace, job)

    def cancel(self, workspace: str, job_id: str) -> dict[str, Any]:
        job = self.status(workspace, job_id)
        with self._lock:
            self._cancel.add(job_id)
        if job.get("status") in ACTIVE:
            job.update(status="cancelling", message="Stopping; resume to continue")
            self._store(workspace).save(job)
        return job

    def resume(self, workspace: str, job_id: str) -> dict[str, Any]:
        with self._admit:
            job = self.status(workspace, job_id)
            if job.get("status") in ACTIVE:
                return job
            self.check_idle(workspace, job["gameId"])
            self._requeue(job, self.deps.read_game(workspace, job["gameId"]))
            job.update(status="queued", message="Resuming", error=None, finishedAt=None)
            thread = self._register(workspace, job)
        self._go(workspace, job_id, thread)
        return self._store(workspace).load(job_id) or job

    def _requeue(self, job: dict, game: dict) -> None:
        """Queue unfinished steps, steps lost to a shutdown, and steps whose dependency is now approved."""
        for step in job.get("steps") or []:
            if not _retry(step, game):
                continue
            step.update(status="queued", error=None, reason=None)
            asset = _find_asset(game, step.get("assetId"))
            if asset is not None and asset.get("status") == "generating":
                self._release(job, step)

    def _reconcile(self, workspace: str, job: dict) -> dict:
        """A job that says it is running without a live thread was cut by a restart."""
        if job.get("status") not in ACTIVE:
            return job
        thread = self._threads.get(job["jobId"])
        if thread is not None and (thread.ident is None or thread.is_alive()):
            return job
        self._interrupt(workspace, job)
        return job

    def _interrupt(self, workspace: str, job: dict) -> None:
        """Running steps go back to the queue. Resume runs them again with the same attempt id."""
        for step in job.get("steps") or []:
            if step.get("status") != "running":
                continue
            step["status"] = "queued"
            self._release(job, step)
        job.update(status="interrupted", message=INTERRUPTED, finishedAt=time.time())
        self._store(workspace).save(job)

    def _register(self, workspace: str, job: dict) -> threading.Thread | None:
        """Claim the job for one worker and save it. ``None`` when a live worker already has it."""
        job_id = job["jobId"]
        with self._lock:
            running = self._threads.get(job_id)
            if running is not None and (running.ident is None or running.is_alive()):
                return None
            self._cancel.discard(job_id)
            if self.deps.inline:
                thread = threading.current_thread()
            else:
                thread = threading.Thread(target=self._run, args=(workspace, job_id), name=f"game-produce-{job_id}", daemon=True)
            self._threads[job_id] = thread
        try:
            self._store(workspace).save(job)
        except Exception:  # an unsaved job must not look claimed by a thread that never starts
            with self._lock:
                self._threads.pop(job_id, None)
            raise
        return thread

    def _go(self, workspace: str, job_id: str, thread: threading.Thread | None) -> None:
        if thread is None:
            return
        if not self.deps.inline:
            thread.start()
            return
        try:
            self._run(workspace, job_id)
        finally:
            self._threads.pop(job_id, None)

    def _save(self, job: dict, **patch: Any) -> None:
        job.update(patch)
        if job.get("status") == "running" and self._cancelled(job["jobId"]):
            job["status"] = "cancelling"
        job["updatedAt"] = time.time()
        self._store(job["workspace"]).save(job)

    def _cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancel

    def _run(self, workspace: str, job_id: str) -> None:
        job = self._store(workspace).load(job_id)
        if not job:
            return
        try:
            self._work(job)
        except Exception as error:  # the worker must not die with the job still saying running
            self._crashed(workspace, job, error)

    def _work(self, job: dict) -> None:
        job_id = job["jobId"]
        self._save(job, status="running", message="Producing")
        for step in job["steps"]:
            if step.get("status") in _TERMINAL:
                continue
            if self._cancelled(job_id):
                break
            self._one(job, step)
        if self._cancelled(job_id) and any(step.get("status") not in _TERMINAL for step in job["steps"]):
            self._save(job, status="cancelled", message="Cancelled; resume to continue", finishedAt=time.time())
            return
        failed = any(step.get("status") == "failed" for step in job["steps"])
        message = "Completed with failed assets" if failed else "Completed"
        self._save(job, status="completed", finishedAt=time.time(), message=message)

    def _crashed(self, workspace: str, job: dict, error: Exception) -> None:
        """A shutdown leaves the job interrupted. Anything else fails the running step and the job."""
        text = _error_text(error)
        try:
            if _interrupted_error(text):
                self._interrupt(workspace, job)
                return
            for step in job.get("steps") or []:
                if step.get("status") == "running":
                    step.update(status="failed", error=text)
                    self._release(job, step)
            self._save(job, status="failed", error=text, message=f"Stopped: {text}", finishedAt=time.time())
        except Exception:  # the job store itself failed; a status read marks the job interrupted
            return

    def _one(self, job: dict, step: dict) -> None:
        step["status"] = "running"
        step["attemptId"] = step.get("attemptId") or uuid.uuid4().hex[:8]
        self._save(job, message=step["assetId"])
        claimed = self._claim(job, step)
        if claimed is None:
            self._save(job)
            return
        game, asset = claimed
        started = time.monotonic()
        try:
            result = self._generate(job, game, asset, step["attemptId"])
        except Exception as error:  # one asset fails; the batch continues. SystemExit leaves the step running.
            self._not_generated(job, step, asset, error)
            return
        try:
            self._succeed(job, step, game, asset, result, time.monotonic() - started)
        except Exception as error:  # the asset was removed, the library is too large, or the disk is full
            self._abandon(job, step, error)

    def _claim(self, job: dict, step: dict) -> tuple[dict, dict] | None:
        """Read the asset and mark it generating under one lock. ``None`` when the step is settled."""
        try:
            with self._library():
                game = self.deps.read_game(job["workspace"], job["gameId"])
                asset = _find_asset(game, step["assetId"])
                if not _claimable(job, step, game, asset):
                    return None
                self.deps.write_attempt(job["workspace"], job["gameId"], asset["id"], None, "generating")
        except Exception as error:  # a missing game or an unwritable library fails this step only
            step.update(status="failed", error=_error_text(error))
            return None
        return game, asset

    def _generate(self, job: dict, game: dict, asset: dict, attempt_id: str):
        generator = REGISTRY.get(asset["kind"])
        if generator is None:
            raise GameToolError("missing_generator", asset["kind"])
        running = copy.deepcopy(asset)
        if isinstance(job.get("candidates"), int) and job["candidates"] > 0:
            running["candidates"] = job["candidates"]
        ctx = GenContext(
            workspace=job["workspace"], game=game, asset=running, attempt_id=attempt_id,
            call=self.deps.call, loopback=self.deps.loopback, workspace_dir=self.deps.workspace_dir,
            cancelled=lambda: self._cancelled(job["jobId"]), log=lambda _message: None, steps=[],
        )
        return generator.run(ctx)

    def _not_generated(self, job: dict, step: dict, asset: dict, error: Exception) -> None:
        if _interrupted_error(_error_text(error)):
            raise error
        if self._cancelled(job["jobId"]) and getattr(error, "code", None) == "cancelled":
            # A cancel inside the tool wait is not a bad asset. The step waits for resume.
            step.update(status="queued", error=None)
            self._release(job, step)
            self._save(job)
            return
        self._fail(job, step, asset, error)

    def _succeed(self, job: dict, step: dict, game: dict, asset: dict, result: Any, elapsed: float) -> None:
        provenance = result.provenance if isinstance(getattr(result, "provenance", None), dict) else {"steps": []}
        common = list(getattr(result, "warnings", None) or [])
        shared = {"provenance": provenance, "inputs": asset_inputs(game, asset)}
        for attempt_id, files, metrics, own in _candidates(result, step["attemptId"]):
            warnings = [*_for_candidate(common, attempt_id), *own]
            attempt = {"id": attempt_id, "status": "ok", "createdAt": iso_now(), "files": files, "metrics": metrics, "warnings": warnings, **shared}
            self.deps.write_attempt(job["workspace"], job["gameId"], asset["id"], attempt, "review")
        step.update(status="done", error=None, reason=None)
        self._save(job)
        _record_elapsed(self.deps.workspace_dir(job["workspace"]), game, asset, job.get("candidates"), elapsed)
        try:
            archive_raw_outputs(self.deps.workspace_dir(job["workspace"]), game, asset["id"], step["attemptId"])
        except OSError as error:
            step["archiveWarning"] = str(error)[:300]
            self._save(job)

    def _abandon(self, job: dict, step: dict, error: Exception) -> None:
        """The attempt could not be stored. The step fails and the batch goes on."""
        if step.get("status") != "done":
            step.update(status="failed", error=_error_text(error))
        self._release(job, step)
        self._save(job)

    def _fail(self, job: dict, step: dict, asset: dict, error: Exception) -> None:
        message = _error_text(error)
        attempt = {"id": step["attemptId"], "status": "failed", "createdAt": iso_now(), "note": message, "provenance": {"steps": []}}
        try:
            self.deps.write_attempt(job["workspace"], job["gameId"], asset["id"], attempt, "pending")
        except Exception as write_error:  # the batch still continues when the library write fails
            message = f"{message}; {type(write_error).__name__}: {write_error}"[:500]
        step.update(status="failed", error=message)
        self._save(job)

    def _release(self, job: dict, step: dict) -> None:
        """A dead worker is not still generating. Pending lets a later batch see the asset.

        Only an asset still marked generating changes. Work a newer batch finished stays.
        """
        try:
            with self._library():
                game = self.deps.read_game(job["workspace"], job["gameId"])
                asset = _find_asset(game, step["assetId"])
                if asset is None or asset.get("status") != "generating":
                    return
                self.deps.write_attempt(job["workspace"], job["gameId"], step["assetId"], None, "pending")
        except Exception:
            return


def build_produce(call: Callable[[str, dict], dict], app_url: Callable[[], str], token: Callable[[], str],
                  workspace_dir: Callable[[str], str], lock: Any, *, inline: bool = False,
                  loopback: Callable[[str, dict], dict] | None = None) -> GameProduce:
    """Wire one producer. Launch passes ``call`` and the video-production loopback pieces."""
    if loopback is None:
        from services.music_production import loopback_mcp
        loopback = loopback_mcp(app_url, token)

    def read_game(workspace: str, game_id: str) -> dict:
        with lock:
            library = read_library(workspace_dir(workspace))
        for game in library.get("games") or []:
            if game.get("id") == game_id:
                return game
        raise ProduceError("not_found", "Game not found", 404)

    def write_attempt(workspace: str, game_id: str, asset_id: str, attempt: dict | None, status: str) -> None:
        directory = workspace_dir(workspace)
        now = iso_now()
        with lock:
            library = read_library(directory)
            if attempt is not None:
                library, _asset = add_attempt(library, game_id, asset_id, attempt, now=now)
            game = next(item for item in library["games"] if item["id"] == game_id)
            found = next(item for item in game["assets"] if item["id"] == asset_id)
            found["status"] = status
            found["updatedAt"] = now
            write_library(directory, library, now=now)

    deps = ProduceDeps(
        call=call, loopback=loopback, workspace_dir=workspace_dir, read_game=read_game,
        write_attempt=write_attempt, inline=inline, lock=lock,
    )
    return GameProduce(deps)


def _steps(game: dict, asset_ids: list[str] | None, kinds: list[str] | None, rerender: bool) -> list[dict]:
    wanted = _select(game.get("assets") or [], asset_ids, kinds, rerender)
    index = {asset["id"]: position for position, asset in enumerate(game.get("assets") or [])}
    ordered = sorted(wanted, key=lambda asset: (_RANK.get(asset.get("kind"), 99), index.get(asset["id"], 0)))
    return [{"assetId": asset["id"], "kind": asset.get("kind"), "status": "queued"} for asset in ordered]


def _select(assets: list[dict], asset_ids: list[str] | None, kinds: list[str] | None, rerender: bool) -> list[dict]:
    ids = set(asset_ids) if asset_ids is not None else None
    kind_set = set(kinds) if kinds is not None else None
    found = []
    for asset in assets:
        if ids is not None and asset.get("id") not in ids:
            continue
        if kind_set is not None and asset.get("kind") not in kind_set:
            continue
        if _wanted(asset, rerender):
            found.append(asset)
    return found


def _wanted(asset: dict, rerender: bool) -> bool:
    status = asset.get("status")
    return status in _OPEN or (bool(rerender) and status == "stale" and not asset.get("locked"))


def _claimable(job: dict, step: dict, game: dict, asset: dict | None) -> bool:
    """Settle the step when its asset is gone, no longer open, or waits on a dependency."""
    if asset is None:
        step.update(status="failed", error="missing asset")
        return False
    if not _wanted(asset, bool(job.get("rerender"))):
        # A newer batch already produced it, or someone approved it. Do not run it twice.
        step.update(status="skipped", reason="not_open", error=None)
        return False
    if not _ready(game, asset):
        step.update(status="skipped", reason="waiting_dependency", error=None)
        return False
    return True


def _retry(step: dict, game: dict) -> bool:
    """Resume runs unfinished steps, steps lost to a shutdown, and steps whose dependency is now approved."""
    status = step.get("status")
    if status == "skipped" and step.get("reason") == "waiting_dependency":
        asset = _find_asset(game, step.get("assetId"))
        return asset is not None and _ready(game, asset)
    return status not in _TERMINAL or _interrupted_error(step.get("error"))


def _group_animation_steps(steps: list[dict]) -> list[dict]:
    """One step per action. J0 left ``groupActions`` false, so clips are not shared."""
    from services.game_generators.animation import GAME_ANIMATION_DEFAULTS
    if GAME_ANIMATION_DEFAULTS["groupActions"]:
        return list(steps)
    return list(steps)


def _find_asset(game: dict, asset_id: str) -> dict | None:
    for asset in game.get("assets") or []:
        if asset.get("id") == asset_id:
            return asset
    return None


def _ready(game: dict, asset: dict) -> bool:
    by_id = {item.get("id"): item for item in game.get("assets") or []}
    for dep in asset.get("dependsOn") or []:
        other = by_id.get(dep)
        if not other or other.get("status") != "approved":
            return False
    return True


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _error_text(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"[:500]


def _for_candidate(warnings: list, attempt_id: str) -> list:
    """Warnings for every candidate, without those tagged for another one."""
    return [item for item in warnings if not isinstance(item, dict) or item.get("candidate") in (None, attempt_id)]


def _candidates(result: Any, fallback: str) -> list[tuple[str, dict, dict, list]]:
    """``(attemptId, files, metrics, ownWarnings)`` per candidate.

    ``metrics["candidates"]`` gives each candidate its own files and metrics.
    Without it, only the first id in ``attemptIds`` gets the result's files.
    """
    metrics = _mapping(getattr(result, "metrics", None))
    listed = _listed_candidates(metrics.get("candidates"))
    if listed:
        return listed
    files = _mapping(getattr(result, "files", None))
    return [
        (attempt_id, files if index == 0 else {}, metrics if index == 0 else {}, [])
        for index, attempt_id in enumerate(_attempt_ids(metrics, fallback))
    ]


def _listed_candidates(raw: Any) -> list[tuple[str, dict, dict, list]]:
    if not isinstance(raw, list):
        return []
    found = []
    for item in raw:
        if isinstance(item, dict) and str(item.get("id") or "").strip():
            own = item.get("warnings") if isinstance(item.get("warnings"), list) else []
            found.append((str(item["id"]), _mapping(item.get("files")), _mapping(item.get("metrics")), list(own)))
    return found


def _attempt_ids(metrics: dict, fallback: str) -> list[str]:
    raw = metrics.get("attemptIds")
    if isinstance(raw, list):
        found = [str(item) for item in raw if str(item).strip()]
        if found:
            return found
    return [fallback]


def _record_elapsed(root: str, game: dict, asset: dict, candidates: Any, elapsed: float) -> None:
    running = asset
    if isinstance(candidates, int) and candidates > 0:
        running = {**asset, "candidates": candidates}
    try:
        record_run(root, game, running, elapsed)
    except Exception:  # timing history is a hint; it never fails a finished asset
        return


def _interrupted_error(error: Any) -> bool:
    """A dying server, not a bad asset. Resume must run the step again."""
    text = str(error or "")
    return text.startswith("CancelledError") or "Executor shutdown" in text
