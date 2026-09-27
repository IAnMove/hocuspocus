"""Run the HTTP server so that a stop request always ends the process.

Uvicorn's graceful shutdown waits for every open connection to close. Browsers
on the LAN keep polling and streaming connections open, so a stop from Pinokio
(or Ctrl+C) left the process "Waiting for connections to close" forever: the
port was released but the Python process, its GPU memory and its model
threads stayed alive until killed by hand. A second SIGTERM did not help,
because Uvicorn only escalates on a second SIGINT.

This module bounds every stage of a stop:

1. Open connections get ``GRACEFUL_SECONDS`` to finish, then are cut.
2. Any repeated stop request (SIGINT, SIGTERM or SIGHUP) forces the exit.
3. SIGHUP, sent when Pinokio closes the app's terminal, also stops, and on
   Linux the death of the launching shell delivers SIGTERM.
4. The process's own exit hooks (queue autosave, ComfyUI runtime stop,
   3D/rig job cancellation) run with ``EXIT_HOOKS_SECONDS`` to finish.
5. The process then exits without waiting on non-daemon worker threads.
6. A watchdog armed by the first stop request ends the process after
   ``WATCHDOG_SECONDS`` no matter which stage is stuck.
"""

from __future__ import annotations

import atexit
import os
import signal
import sys
import threading
from typing import Any

GRACEFUL_SECONDS = float(os.environ.get("HOCUSPOCUS_GRACEFUL_SECONDS", "5"))
EXIT_HOOKS_SECONDS = float(os.environ.get("HOCUSPOCUS_EXIT_HOOKS_SECONDS", "20"))
WATCHDOG_SECONDS = float(os.environ.get("HOCUSPOCUS_WATCHDOG_SECONDS", "45"))

_watchdog: threading.Timer | None = None
_watchdog_lock = threading.Lock()


def _log(message: str) -> None:
    try:
        print(f"[HocusPocus Lab] {message}", flush=True)
    except Exception:
        pass


def _hard_exit(code: int) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os._exit(code)


def arm_watchdog(seconds: float | None = None) -> None:
    """End the process after ``seconds`` even if shutdown is stuck. Idempotent."""
    global _watchdog
    with _watchdog_lock:
        if _watchdog is not None:
            return

        def expire() -> None:
            _log(f"Shutdown did not finish within {seconds or WATCHDOG_SECONDS:.0f}s; exiting now.")
            _hard_exit(1)

        _watchdog = threading.Timer(seconds or WATCHDOG_SECONDS, expire)
        _watchdog.daemon = True
        _watchdog.start()


def finish_process(code: int = 0) -> None:
    """Run exit hooks within their budget, then end the process."""
    arm_watchdog()
    hooks = threading.Thread(target=atexit._run_exitfuncs, name="exit-hooks", daemon=True)
    hooks.start()
    hooks.join(EXIT_HOOKS_SECONDS)
    if hooks.is_alive():
        _log(f"Exit hooks still running after {EXIT_HOOKS_SECONDS:.0f}s; exiting without them.")
    else:
        _log("Stopped.")
    _hard_exit(code)


def stop_with_parent() -> None:
    """On Linux, receive SIGTERM when the launching shell dies.

    Pinokio runs ``python launch.py`` inside a shell. If that shell is killed
    without forwarding a signal, the server would outlive it holding the GPU;
    the kernel's parent-death signal turns that into an ordinary stop.
    """
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes

        pr_set_pdeathsig = 1
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(pr_set_pdeathsig, int(signal.SIGTERM))
    except Exception:
        pass


def run_until_stopped(app: Any, *, host: str, port: int) -> None:
    """Serve ``app`` until a stop request, then end the process (never returns
    normally). Bind failures still raise ``OSError`` for the caller to report."""
    import uvicorn

    class _Server(uvicorn.Server):
        def handle_exit(self, sig: int, frame: Any) -> None:  # noqa: D401 - uvicorn hook
            arm_watchdog()
            if self.should_exit:
                # Uvicorn escalates only on a repeated SIGINT; a repeated
                # SIGTERM/SIGHUP from a supervisor must force the stop too.
                self.force_exit = True
            super().handle_exit(sig, frame)

    config = uvicorn.Config(app, host=host, port=port, timeout_graceful_shutdown=GRACEFUL_SECONDS)
    server = _Server(config)
    # Uvicorn swaps in its own handlers while serving, then restores the
    # previous ones and re-raises each captured signal. With the defaults in
    # place that re-raise killed the process on SIGTERM before any exit hook
    # ran, and turned SIGINT into a KeyboardInterrupt that skipped the bounded
    # exit and waited on worker threads again. Installing handlers first makes
    # the re-raise land here, where it is harmless.
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), server.handle_exit)
    stop_with_parent()
    try:
        server.run()
    except OSError:
        raise
    except KeyboardInterrupt:
        finish_process(0)
    except SystemExit as exc:
        # Uvicorn exits with status 1 when startup fails (for example a bind
        # race); keep that status but still bound the hooks.
        finish_process(exc.code if isinstance(exc.code, int) else 1)
    finish_process(0 if server.started else 1)
