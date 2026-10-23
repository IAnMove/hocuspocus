"""Starts this launcher's Pinokio scripts from the server, through the ``pterm`` client.

Three facts about ``pterm start`` shape this module: it streams the script's terminal
output, it exits 0 whether the script worked or not, and when the client dies Pinokio
stops the script. So the client runs detached, in its own session, with its output in a
file, and callers judge success by looking at what ended up installed, never at the exit
code. Stopping or restarting HocusPocus while an install runs can still interrupt it
because Pinokio ends the app's child processes.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

DEFAULT_PINOKIO_PORT = "42000"
REF_ENV = "HOCUS_PINOKIO_REF"
PORT_ENV = "HOCUS_PINOKIO_PORT"

NOT_IN_PINOKIO = "not_in_pinokio"
NO_PTERM = "no_pterm"


@dataclass(frozen=True)
class LauncherTarget:
    pterm: str
    ref: str
    root: Path


def resolve(root: Path, environ: Mapping[str, str] | None = None,
            which: Callable[[str], str | None] = shutil.which) -> tuple[LauncherTarget | None, str | None]:
    """The way to reach this checkout's Pinokio launcher, or the reason code why there is none.

    A checkout outside ``<pinokio>/api/`` (a development worktree) is not a Pinokio app,
    unless ``HOCUS_PINOKIO_REF`` names one. ``HOCUS_PINOKIO_PORT`` overrides the default 42000.
    """
    environ = os.environ if environ is None else environ
    ref = environ.get(REF_ENV)
    if not ref:
        if root.parent.name != "api":
            return None, NOT_IN_PINOKIO
        ref = f"pinokio://127.0.0.1:{environ.get(PORT_ENV) or DEFAULT_PINOKIO_PORT}/api/{root.name}"
    pterm = which("pterm")
    if not pterm:
        return None, NO_PTERM
    return LauncherTarget(pterm=pterm, ref=ref, root=root), None


def start(target: LauncherTarget, script: str, log_path: Path) -> subprocess.Popen:
    """Run ``pterm start <script>`` detached, writing its output to ``log_path``."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    detach: dict = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
        if sys.platform == "win32" else {"start_new_session": True}
    )
    with log_path.open("wb") as log:
        return subprocess.Popen(
            [target.pterm, "start", script, "--ref", target.ref],
            cwd=target.root, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **detach,
        )
