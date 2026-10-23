"""Install and uninstall jobs for optional components, one at a time.

An install runs the component's Pinokio script through ``install_launcher`` and an
uninstall deletes folders on a thread. Each job is a small JSON file in
``app/.runtime/install-jobs`` so a page reload, or a server restart while the detached
Pinokio client keeps working, still finds it. A running install that has no live client
is closed by looking at what is installed.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Callable

import psutil

from services import install_launcher, install_remove
from services.install_catalog import Component

RUNNING, SUCCEEDED, FAILED = "running", "succeeded", "failed"
INSTALL, UNINSTALL = "install", "uninstall"

BUSY = "install_in_progress"
LAUNCHER_UNAVAILABLE = "launcher_unavailable"
NOT_INSTALLED_AFTER_RUN = "not_installed_after_run"
INTERRUPTED = "interrupted"
REMOVAL_FAILED = "removal_failed"

LOG_READ_BYTES = 64 * 1024
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


class JobRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _client_alive(pid: int | None) -> bool:
    """The Pinokio client is a node process whose command line names pterm."""
    if not pid:
        return False
    try:
        return any("pterm" in part for part in psutil.Process(pid).cmdline())
    except (psutil.Error, OSError):
        return False


def clean_log_lines(raw: str, count: int) -> list[str]:
    """Last ``count`` lines of terminal output without colour codes or progress-bar redraws."""
    text = _ANSI.sub("", raw)
    lines = [line.rsplit("\r", 1)[-1].rstrip() for line in text.split("\n")]
    return [line for line in lines if line.strip()][-count:]


class InstallJobs:
    def __init__(
        self,
        root: Path,
        *,
        installed: Callable[[str], bool],
        in_use: Callable[[str], bool],
        resolve: Callable[..., tuple] = install_launcher.resolve,
        launch: Callable[..., object] = install_launcher.start,
        client_alive: Callable[[int | None], bool] = _client_alive,
        clock: Callable[[], float] = time.time,
        on_change: Callable[[Component], None] = lambda component: None,
    ) -> None:
        self._root = root
        self._dir = root / "app" / ".runtime" / "install-jobs"
        self._installed, self._in_use = installed, in_use
        self._resolve, self._launch, self._client_alive = resolve, launch, client_alive
        self._clock, self._on_change = clock, on_change
        self._lock = threading.RLock()
        self._active: set[str] = set()  # components whose thread in this process is still working

    # -- persistence -------------------------------------------------------------------
    def _path(self, component_id: str) -> Path:
        return self._dir / f"{component_id}.json"

    def _log_path(self, component_id: str) -> Path:
        return self._dir / f"{component_id}.log"

    def _save(self, job: dict) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        temporary = self._path(job["component"]).with_suffix(".tmp")
        temporary.write_text(json.dumps(job, indent=2), encoding="utf-8")
        temporary.replace(self._path(job["component"]))

    def _read(self, component_id: str) -> dict | None:
        try:
            return json.loads(self._path(component_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # -- reading -----------------------------------------------------------------------
    def job(self, component: Component) -> dict | None:
        """The latest job for a component, closing it first if its client has vanished."""
        with self._lock:
            job = self._read(component.id)
            if job and job["state"] == RUNNING and not self._is_live(job):
                job = self._finish(job, component, self._outcome(job, component))
            return job

    def running(self, components: tuple[Component, ...]) -> dict | None:
        for component in components:
            job = self.job(component)
            if job and job["state"] == RUNNING:
                return job
        return None

    def log_tail(self, component_id: str, count: int = 60) -> list[str]:
        try:
            with self._log_path(component_id).open("rb") as handle:
                handle.seek(0, 2)
                handle.seek(max(0, handle.tell() - LOG_READ_BYTES))
                return clean_log_lines(handle.read().decode("utf-8", "replace"), count)
        except OSError:
            return []

    # -- starting ----------------------------------------------------------------------
    def start_install(self, component: Component, components: tuple[Component, ...]) -> dict:
        with self._lock:
            self._ensure_idle(components)
            target, reason = self._resolve(self._root)
            if target is None:
                raise JobRefused(LAUNCHER_UNAVAILABLE, reason or LAUNCHER_UNAVAILABLE)
            job = self._new_job(component, INSTALL)
            try:
                process = self._launch(target, component.script, self._log_path(component.id))
            except OSError as error:
                raise JobRefused(LAUNCHER_UNAVAILABLE, f"Could not start Pinokio's pterm: {error}") from error
            job["pid"] = process.pid
            self._save(job)
            self._active.add(component.id)
        threading.Thread(target=self._watch_client, args=(job, component, process), daemon=True).start()
        return job

    def start_uninstall(self, component: Component, components: tuple[Component, ...]) -> dict:
        with self._lock:
            self._ensure_idle(components)
            removal = install_remove.plan(component, self._root, self._in_use)
            job = self._new_job(component, UNINSTALL)
            self._save(job)
            self._active.add(component.id)
        threading.Thread(target=self._run_removal, args=(job, removal), daemon=True).start()
        return job

    # -- internals ---------------------------------------------------------------------
    def _ensure_idle(self, components: tuple[Component, ...]) -> None:
        busy = self.running(components)
        if busy:
            raise JobRefused(BUSY, f"Another change is running: {busy['kind']} {busy['component']}.")

    def _new_job(self, component: Component, kind: str) -> dict:
        return {"component": component.id, "kind": kind, "state": RUNNING, "startedAt": self._clock(),
                "finishedAt": None, "code": None, "message": None, "pid": None}

    def _is_live(self, job: dict) -> bool:
        """Our own thread is working, or (after a server restart) the detached client still runs."""
        if job["component"] in self._active:
            return True
        return job["kind"] == INSTALL and self._client_alive(job.get("pid"))

    def _outcome(self, job: dict, component: Component) -> tuple[str, str | None, str | None]:
        if job["kind"] == UNINSTALL:
            return FAILED, INTERRUPTED, "The removal was interrupted. Run it again to finish."
        if self._installed(component.engine):
            return SUCCEEDED, None, None
        return FAILED, NOT_INSTALLED_AFTER_RUN, "The installer ended but the component is not installed."

    def _finish(self, job: dict, component: Component, outcome: tuple[str, str | None, str | None]) -> dict:
        with self._lock:
            current = self._read(job["component"]) or job
            if current["state"] != RUNNING:
                return current
            state, code, message = outcome
            done = {**current, "state": state, "code": code, "message": message, "finishedAt": self._clock()}
            self._save(done)
        self._on_change(component)
        return done

    def _watch_client(self, job: dict, component: Component, process) -> None:
        try:
            process.wait()
        finally:
            self._active.discard(component.id)
        self._finish(job, component, self._outcome(job, component))

    def _run_removal(self, job: dict, removal: install_remove.RemovalPlan) -> None:
        try:
            install_remove.execute(removal)
            outcome = (SUCCEEDED, None, None)
        except OSError as error:
            outcome = (FAILED, REMOVAL_FAILED, f"{type(error).__name__}: {error}")
        finally:
            self._active.discard(removal.component.id)
        self._finish(job, removal.component, outcome)
