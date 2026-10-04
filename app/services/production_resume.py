"""Resume a music-video production after the server process dies.

A ``*.production.json`` left ``running`` is continued in-process when MCP is on,
the file was written within 24 hours and the production asked for it
(``production.run`` with ``auto_resume: true``, kept in the state file) or the
server was started with ``HOCUS_PRODUCTION_AUTORESUME=1``. The saved ``through``
stage is repeated: a crashed animatic or frames stop does not become a full GPU
run. Nothing restarts GPU work on its own otherwise: stopping a server on purpose
stays stopped. The resume is not an agent call.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

MAX_AGE_SECONDS = 24 * 60 * 60
ENV_FLAG = "HOCUS_PRODUCTION_AUTORESUME"
RETRY_DELAYS = (5, 15, 45)
log = logging.getLogger(__name__)


def open_mcp(request: urllib.request.Request, *, timeout: float, sleep: Callable[[float], None]):
    """Three tries. URLError and HTTP 502/503 wait 5s, then 15s, then 45s."""
    saved: BaseException | None = None
    for delay in RETRY_DELAYS:
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            if error.code not in (502, 503):
                raise
            saved = error
        except urllib.error.URLError as error:
            saved = error
        sleep(delay)
    if saved is None:
        raise RuntimeError("production MCP retry made no attempt")
    raise saved


def mcp_active(app_url: Callable[[], str], token: Callable[[], str]) -> bool:
    try:
        return bool(token()) and bool(app_url())
    except Exception:
        return False


def production_id_of(path: Path) -> str:
    suffix = ".production.json"
    name = path.name
    return name[: -len(suffix)] if name.endswith(suffix) else path.stem


def file_is_fresh(path: Path, now: float) -> bool:
    try:
        return now - path.stat().st_mtime <= MAX_AGE_SECONDS
    except OSError:
        return False


def wants_resume(state: dict) -> bool:
    if state.get("auto_resume") is True:
        return True
    return os.environ.get(ENV_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def load_running(path: Path) -> dict | None:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict) or state.get("status") != "running":
        return None
    if not isinstance(state.get("spec"), dict) or not wants_resume(state):
        return None
    return state


def thread_alive(threads: dict[str, threading.Thread], key: str) -> bool:
    thread = threads.get(key)
    return bool(thread and thread.is_alive())


def resume_through(state: dict | None) -> str:
    """Repeat the stage that was running. A crashed animatic must not become a full GPU run."""
    through = state.get("through") if isinstance(state, dict) else None
    return through if through in {"all", "frames", "animatic"} else "all"


def start_production(production: Any, spec: dict, key: str, threads: dict[str, threading.Thread], lock: threading.Lock) -> bool:
    with lock:
        if thread_alive(threads, key):
            return False
        through = resume_through(getattr(production, "state", None))
        thread = threading.Thread(target=production.run, args=(spec, (), through), name=f"production-{production.id}", daemon=True)
        threads[key] = thread
        thread.start()
        return True


def _workspace_item(item: Any) -> tuple[str | None, str | None]:
    if isinstance(item, dict):
        name, path = item.get("name"), item.get("path")
    else:
        name, path = item, None
    if not isinstance(name, str) or not name:
        return None, None
    return name, path if isinstance(path, str) else None


def workspace_roots(list_workspaces: Callable[[], Any], workspace_dir: Callable[[str], str]) -> list[tuple[str, Path]]:
    roots: list[tuple[str, Path]] = []
    for item in list_workspaces():
        name, path = _workspace_item(item)
        if name is None:
            continue
        if path is None:
            try:
                path = workspace_dir(name)
            except Exception:
                log.warning("production resume skipped workspace %s", name)
                continue
        roots.append((name, Path(path)))
    return roots


def _resume_file(path: Path, key: str, workspace: str, production_type: Any, mcp: Callable, workspace_dir: Callable[[str], str],
                 uploads_dir: Callable[[], str], threads: dict, lock: threading.Lock, now: float) -> bool:
    if not file_is_fresh(path, now) or thread_alive(threads, key):
        return False
    state = load_running(path)
    if state is None:
        return False
    try:
        production = production_type(workspace, production_id_of(path), workspace_dir=workspace_dir, uploads_dir=uploads_dir, mcp=mcp)
        return start_production(production, state["spec"], key, threads, lock)
    except Exception:
        log.warning("production resume skipped %s", path.name)
        return False


def _resume_root(workspace: str, root: Path, production_type: Any, mcp: Callable, workspace_dir: Callable[[str], str],
                 uploads_dir: Callable[[], str], threads: dict, lock: threading.Lock, now: float) -> list[str]:
    if not root.is_dir():
        return []
    started = []
    for path in sorted(root.glob("*.production.json")):
        key = f"{workspace}/{production_id_of(path)}"
        if _resume_file(path, key, workspace, production_type, mcp, workspace_dir, uploads_dir, threads, lock, now):
            started.append(key)
    return started


def resume_running(list_workspaces: Callable[[], Any], workspace_dir: Callable[[str], str], uploads_dir: Callable[[], str],
                   app_url: Callable[[], str], token: Callable[[], str], *, threads: dict[str, threading.Thread],
                   lock: threading.Lock, now: float | None = None) -> list[str]:
    if not mcp_active(app_url, token):
        return []
    from services.music_production import Production, loopback_mcp

    moment = time.time() if now is None else now
    mcp = loopback_mcp(app_url, token)
    started: list[str] = []
    for workspace, root in workspace_roots(list_workspaces, workspace_dir):
        started.extend(_resume_root(workspace, root, Production, mcp, workspace_dir, uploads_dir, threads, lock, moment))
    return started


def resume_on_startup(list_workspaces: Callable[[], Any], workspace_dir: Callable[[str], str], uploads_dir: Callable[[], str],
                      app_url: Callable[[], str], token: Callable[[], str]) -> list[str]:
    """Startup entry: continue recent running productions whose worker is gone."""
    from services import music_production

    return resume_running(
        list_workspaces, workspace_dir, uploads_dir, app_url, token,
        threads=music_production._threads, lock=music_production._lock,
    )
