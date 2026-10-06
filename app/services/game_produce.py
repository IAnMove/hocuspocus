"""Produce the pending assets of one game, one asset at a time.

The shape follows ``series_produce.py``. A dependency that is not approved is
skipped. This job never approves an asset. Animation grouping waits for J6.
"""
from __future__ import annotations

import copy
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.game_estimate import record, steps_for
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
    sleep: Callable[[float], None] = time.sleep
    poll_seconds: float = 2.0
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
        self._active_job = ""

    def _store(self, workspace: str) -> GameJobStore:
        return GameJobStore(self.deps.workspace_dir(workspace))

    def start(self, workspace: str, game_id: str, asset_ids: list[str] | None = None, kinds: list[str] | None = None,
              rerender: bool = False, candidates: int | None = None) -> dict[str, Any]:
        game = self.deps.read_game(workspace, game_id)
        if any(job.get("gameId") == game_id and job.get("status") in ACTIVE for job in self.jobs(workspace)):
            raise ProduceError("already_running", "This game is already being produced")
        steps = _group_animation_steps(_steps(game, asset_ids, kinds, rerender))
        job = {
            "jobId": f"game-produce-{uuid.uuid4().hex[:8]}", "workspace": workspace, "gameId": game_id,
            "status": "completed" if not steps else "queued", "rerender": bool(rerender), "candidates": candidates,
            "steps": steps, "createdAt": time.time(), "message": "Nothing to produce" if not steps else "Queued",
        }
        if not steps:
            job["finishedAt"] = time.time()
            self._store(workspace).save(job)
            return job
        self._launch(workspace, job)
        return self._store(workspace).load(job["jobId"]) or job

    def jobs(self, workspace: str) -> list[dict[str, Any]]:
        return [self._reconcile(workspace, job) for job in self._store(workspace).list()]

    def status(self, workspace: str, job_id: str) -> dict[str, Any]:
        job = self._store(workspace).load(job_id)
        if not job:
            raise ProduceError("not_found", "Production job not found", 404)
        return self._reconcile(workspace, job)

    def cancel(self, workspace: str, job_id: str) -> dict[str, Any]:
        job = self.status(workspace, job_id)
        with self._lock:
            self._cancel.add(job_id)
        if job.get("status") in ACTIVE:
            job.update(status="cancelling", message="Stopping after the current step")
            self._store(workspace).save(job)
        return job

    def resume(self, workspace: str, job_id: str) -> dict[str, Any]:
        job = self.status(workspace, job_id)
        if job.get("status") in ACTIVE:
            return job
        for step in job.get("steps") or []:
            if step.get("status") not in _TERMINAL:
                step.update(status="queued", error=None)
        job.update(status="queued", message="Resuming", error=None, finishedAt=None)
        self._launch(workspace, job)
        return self._store(workspace).load(job_id) or job

    def _reconcile(self, workspace: str, job: dict) -> dict:
        """A job that says it is running without a live thread was cut by a restart."""
        if job.get("status") not in ACTIVE:
            return job
        thread = self._threads.get(job["jobId"])
        if thread is not None and (thread.ident is None or thread.is_alive()):
            return job
        for step in job.get("steps") or []:
            if step.get("status") != "running":
                continue
            step["status"] = "queued"
            _release_generating(self, job, step)
        job.update(status="interrupted", message=INTERRUPTED, finishedAt=time.time())
        self._store(workspace).save(job)
        return job

    def _launch(self, workspace: str, job: dict) -> None:
        job_id = job["jobId"]
        with self._lock:
            running = self._threads.get(job_id)
            if running is not None and (running.ident is None or running.is_alive()):
                return
            self._cancel.discard(job_id)
            if self.deps.inline:
                self._threads[job_id] = threading.current_thread()
            else:
                thread = threading.Thread(target=self._run, args=(workspace, job_id), name=f"game-produce-{job_id}", daemon=True)
                self._threads[job_id] = thread
        self._store(workspace).save(job)
        if self.deps.inline:
            try:
                self._run(workspace, job_id)
            finally:
                self._threads.pop(job_id, None)
            return
        thread.start()

    def _save(self, job: dict, **patch: Any) -> None:
        job.update(patch)
        job["updatedAt"] = time.time()
        self._store(job["workspace"]).save(job)

    def _cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancel

    def _run(self, workspace: str, job_id: str) -> None:
        job = self._store(workspace).load(job_id)
        if not job:
            return
        self._save(job, status="running", message="Producing")
        for step in job["steps"]:
            if step.get("status") in _TERMINAL:
                continue
            if self._cancelled(job_id):
                self._save(job, status="cancelled", message="Cancelled; resume to continue", finishedAt=time.time())
                return
            self._one(job, step)
        failed = any(step.get("status") == "failed" for step in job["steps"])
        message = "Completed with failed assets" if failed else "Completed"
        self._save(job, status="completed", finishedAt=time.time(), message=message)

    def _one(self, job: dict, step: dict) -> None:
        self._active_job = job["jobId"]
        step["status"] = "running"
        step["attemptId"] = step.get("attemptId") or uuid.uuid4().hex[:8]
        self._save(job, message=step["assetId"])
        try:
            game = self.deps.read_game(job["workspace"], job["gameId"])
            asset = _find_asset(game, step["assetId"])
        except ProduceError as error:
            step.update(status="failed", error=str(error))
            self._save(job)
            return
        if asset is None:
            step.update(status="failed", error="missing asset")
            self._save(job)
            return
        if not _ready(game, asset):
            step.update(status="skipped", reason="waiting_dependency", error=None)
            self._save(job)
            return
        self.deps.write_attempt(job["workspace"], job["gameId"], asset["id"], None, "generating")
        started = time.monotonic()
        try:
            result = self._generate(job, game, asset, step["attemptId"])
        except Exception as error:  # one asset fails; the batch continues. SystemExit leaves the step running.
            self._fail(job, step, asset, error)
            return
        self._succeed(job, step, game, asset, result, time.monotonic() - started)

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

    def _succeed(self, job: dict, step: dict, game: dict, asset: dict, result: Any, elapsed: float) -> None:
        metrics = result.metrics if isinstance(getattr(result, "metrics", None), dict) else {}
        files = result.files if isinstance(getattr(result, "files", None), dict) else {}
        warnings = list(getattr(result, "warnings", None) or [])
        provenance = result.provenance if isinstance(getattr(result, "provenance", None), dict) else {"steps": []}
        for index, attempt_id in enumerate(_attempt_ids(metrics, step["attemptId"])):
            attempt = {
                "id": attempt_id, "status": "ok", "createdAt": iso_now(),
                "files": files if index == 0 else {}, "metrics": metrics if index == 0 else {},
                "warnings": warnings, "provenance": provenance, "inputs": asset_inputs(game, asset),
            }
            self.deps.write_attempt(job["workspace"], job["gameId"], asset["id"], attempt, "review")
        step.update(status="done", error=None, reason=None)
        self._save(job)
        _record_elapsed(self.deps.workspace_dir(job["workspace"]), game, asset, job.get("candidates"), elapsed)
        try:
            archive_raw_outputs(self.deps.workspace_dir(job["workspace"]), game, asset["id"], step["attemptId"])
        except OSError as error:
            step["archiveWarning"] = str(error)[:300]
            self._save(job)

    def _fail(self, job: dict, step: dict, asset: dict, error: Exception) -> None:
        message = f"{type(error).__name__}: {error}"[:500]
        attempt = {"id": step["attemptId"], "status": "failed", "createdAt": iso_now(), "note": message, "provenance": {"steps": []}}
        try:
            self.deps.write_attempt(job["workspace"], job["gameId"], asset["id"], attempt, "pending")
        except Exception as write_error:  # the batch still continues when the library write fails
            message = f"{message}; {type(write_error).__name__}: {write_error}"[:500]
        step.update(status="failed", error=message)
        self._save(job)


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
        if asset.get("status") in _OPEN or (rerender and asset.get("status") == "stale" and not asset.get("locked")):
            found.append(asset)
    return found


def _group_animation_steps(steps: list[dict]) -> list[dict]:
    """J6 step 3 decides which actions share a clip. Until then each asset is its own step."""
    return steps


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
    counts = steps_for(game, running)
    if not counts:
        return
    primary = max(counts, key=counts.get)
    try:
        record(root, primary, elapsed)
    except OSError:
        return


def _release_generating(service: GameProduce, job: dict, step: dict) -> None:
    """A dead worker is not still generating. Pending lets a later batch see the asset."""
    try:
        service.deps.write_attempt(job["workspace"], job["gameId"], step["assetId"], None, "pending")
    except Exception:
        return
