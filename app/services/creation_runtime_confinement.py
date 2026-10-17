"""Memory confinement for the FLUX 3 / Drama 3 ComfyUI runtime.

Drama 3 holds about 42 GB of RAM (ComfyUI pins up to 57 GB) on a 64 GB machine. When the
machine runs short, ``systemd-oomd`` kills a whole cgroup, and a runtime that lives inside
the server's cgroup takes the server with it. On Linux with a systemd user manager the
runtime therefore starts as ``systemd-run --user --scope ... -p MemoryHigh=H -p MemoryMax=M``:
its own cgroup, a soft limit (the kernel throttles and reclaims first, so it gets slower) and
a hard limit (the kernel kills inside that cgroup, never the server). Everywhere else the
command runs as it always did.

The scope lives outside the server's cgroup, so a server that is killed leaves the runtime
behind. ``runtime.json`` names the runtime and the server that started it, and
``sweep_orphan_runtime`` stops a runtime whose server is gone.
"""
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

DEFAULT_MEMORY_PERCENT = 80
MIN_MEMORY_PERCENT = 30
MAX_MEMORY_PERCENT = 95
SOFT_LIMIT_PERCENT = 90
PROBE_SECONDS = 5
TERMINATE_SECONDS = 15
KILL_SECONDS = 5
OOM_EXIT_CODES = (-9, 137)
CGROUP_ROOT = Path("/sys/fs/cgroup")
SESSION_KEYS = ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
OUT_OF_MEMORY_MESSAGE = (
    "The FLUX 3 / Drama 3 runtime ran out of memory and was stopped; the server and your other programs "
    "were not touched. Close memory-heavy programs or lower creation_runtime_memory_percent and try again."
)
_support = None  # the systemd-run path, False once the probe failed, None before the first probe
_support_lock = threading.Lock()
_sweep_lock = threading.Lock()


def _log(message):
    print("[Creation models] " + message, flush=True)


def _on_linux():
    return sys.platform.startswith("linux")


def memory_percent_setting(services):
    """Read ``creation_runtime_memory_percent``: 0 turns confinement off, 30-95 is the share of the RAM.

    A missing, negative or unreadable value means the default, so a typo never removes the protection.
    """
    raw = (services or {}).get("creation_runtime_memory_percent", DEFAULT_MEMORY_PERCENT)
    try:
        value = DEFAULT_MEMORY_PERCENT if isinstance(raw, bool) or raw is None else float(raw)
    except (TypeError, ValueError):
        return DEFAULT_MEMORY_PERCENT
    if not math.isfinite(value) or value < 0:
        return DEFAULT_MEMORY_PERCENT
    return clamp_percent(value)


def clamp_percent(value):
    """0 stays 0 (confinement off); any other share is held between 30 and 95 %."""
    return 0 if not value else int(min(max(value, MIN_MEMORY_PERCENT), MAX_MEMORY_PERCENT))


def physical_memory_bytes():
    """Installed RAM from ``os.sysconf``; None where the platform does not say."""
    if not _on_linux():
        return None
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return None


def memory_limits(percent, ram=None):
    """``MemoryMax`` is ``percent`` of the RAM and ``MemoryHigh`` 90 % of that, in whole bytes."""
    ram = physical_memory_bytes() if ram is None else ram
    percent = clamp_percent(percent)
    if not percent or not ram:
        return None
    hard = ram * percent // 100
    return {"max": hard, "high": hard * SOFT_LIMIT_PERCENT // 100, "percent": percent, "ram": ram}


def session_environment(env, inherited=None):
    """``env`` plus the two variables ``systemd-run --user`` needs to find the user's manager."""
    source = os.environ if inherited is None else inherited
    result = dict(env)
    for key in SESSION_KEYS:
        if key not in result and source.get(key):
            result[key] = source[key]
    if "XDG_RUNTIME_DIR" not in result and hasattr(os, "getuid") and Path(f"/run/user/{os.getuid()}").is_dir():
        result["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
    return result


def _probe():
    if not _on_linux():
        return False
    launcher = shutil.which("systemd-run")
    if launcher is None:
        _log("runtime not confined: systemd-run is not installed")
        return False
    try:
        result = subprocess.run([launcher, "--user", "--scope", "--quiet", "true"], timeout=PROBE_SECONDS,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=session_environment(dict(os.environ)))
    except (OSError, subprocess.TimeoutExpired) as error:
        _log(f"runtime not confined: systemd-run --user did not answer ({type(error).__name__})")
        return False
    if result.returncode != 0:
        _log(f"runtime not confined: there is no systemd user manager (systemd-run exited {result.returncode})")
        return False
    return launcher


def systemd_run_path():
    """The ``systemd-run`` that can start user scopes, or None. The probe runs once per process."""
    global _support
    with _support_lock:
        if _support is None:
            _support = _probe()
        return _support or None


ENV_BIN = "/usr/bin/env"


def isolated_command(command, env):
    """``env -i`` then ``command``: systemd-run keeps the server's libraries; ComfyUI still gets ``env``.

    ``confine`` used to hand the engine environment (conda ``LD_LIBRARY_PATH`` first) to systemd-run
    itself. The probe that decides confinement uses the server's environment, so a working probe
    still launched systemd-run against torch/OpenSSL from the creation-models env, which shadows
    ``libcrypto``/``libsystemd`` and the runtime dies during startup.
    """
    return [ENV_BIN, "-i", "--", *[f"{key}={value}" for key, value in env.items()], *command]


def scope_command(launcher, command, limits):
    # No swap for the runtime: past its limit the kernel stops it, instead of it thrashing the swap that the
    # server and the owner's other programs share (a 100 MB scope swapped out 612 MB without ever dying).
    return [launcher, "--user", "--scope", "--quiet", "--collect", "-p", f"MemoryHigh={limits['high']}",
            "-p", f"MemoryMax={limits['max']}", "-p", "MemorySwapMax=0", "--", *command]


def confine(command, env, percent=None):
    """``(command, env, limits)``: wrapped in its own memory scope, or unchanged with ``limits`` None.

    The returned ``env`` is the server session systemd-run needs. The engine environment is on the
    command via ``env -i``, so conda libraries cannot shadow systemd-run.
    """
    percent = DEFAULT_MEMORY_PERCENT if percent is None else percent
    if not percent:
        _log("runtime not confined: creation_runtime_memory_percent is 0")
        return command, env, None
    limits = memory_limits(percent)
    launcher = systemd_run_path() if limits else None
    if launcher is None:
        return command, env, None
    return (scope_command(launcher, isolated_command(command, env), limits),
            session_environment(dict(os.environ)), limits)


def scope_cgroup(pid):
    """The cgroup directory ``/proc/<pid>/cgroup`` names (cgroup v2), or None."""
    try:
        text = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("0::"):
            return CGROUP_ROOT / line[3:].lstrip("/")
    return None


def _read_int(path):
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def verify_scope(pid, limits):
    """The runtime's own cgroup if the kernel really holds ``MemoryMax`` there, else None."""
    cgroup, own = scope_cgroup(pid), scope_cgroup(os.getpid())
    if cgroup is None or cgroup == own:
        return None
    applied = _read_int(cgroup / "memory.max")
    return cgroup if applied is not None and abs(applied - limits["max"]) <= 1 << 20 else None


def oom_kills(cgroup):
    """The ``oom_kill`` counter of ``memory.events``; None once the cgroup is gone."""
    try:
        for line in (Path(cgroup) / "memory.events").read_text(encoding="utf-8").splitlines():
            name, _, count = line.partition(" ")
            if name == "oom_kill":
                return int(count)
    except (OSError, ValueError):
        pass
    return None


def exited_from_oom(returncode, cgroup=None):
    """True when the runtime was killed with SIGKILL (the kernel's and oomd's way) or its cgroup counted an OOM kill."""
    return returncode in OOM_EXIT_CODES or (cgroup is not None and (oom_kills(cgroup) or 0) > 0)


# --- the record that lets a new server find a runtime its predecessor left behind ------------


def _cmdline(pid):
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part for part in raw.decode("utf-8", "replace").split("\0") if part]


def _start_ticks(pid):
    """Field 22 of ``/proc/<pid>/stat``: when the process started, so a reused pid is told apart."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return int(stat[stat.rindex(")") + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _send(pid, number):
    try:
        os.kill(pid, number)
    except (ProcessLookupError, PermissionError):
        pass


def record_runtime(path, pid, marker):
    """Write ``runtime.json``: the runtime's pid, the marker its command line carries and its server."""
    data = {"pid": pid, "started": time.time(), "marker": marker,
            "owner": {"pid": os.getpid(), "start": _start_ticks(os.getpid())}}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = path.with_name(path.name + ".tmp")
        pending.write_text(json.dumps(data), encoding="utf-8")
        os.replace(pending, path)
    except OSError as error:
        _log(f"could not write {path.name}: {error}")


def _read_record(path):
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
        return record if isinstance(record, dict) and isinstance(record.get("pid"), int) else None
    except (OSError, ValueError):
        return None


def forget_runtime(path, pid=None):
    """Delete ``runtime.json`` once the runtime it names is stopped (a record of another pid stays)."""
    record = _read_record(path)
    if record is None or pid is None or record["pid"] == pid:
        Path(path).unlink(missing_ok=True)


def _is_runtime(pid, marker):
    """``main.py`` run with the marker (the absolute ``extra_model_paths.json`` of this checkout)."""
    arguments = _cmdline(pid)
    return marker in arguments and any(Path(argument).name == "main.py" for argument in arguments)


def _owner_alive(record):
    owner = record.get("owner") or {}
    start = owner.get("start")
    return start is not None and _start_ticks(owner.get("pid")) == start


def _wait_gone(pid, marker, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _is_runtime(pid, marker):
            return True
        time.sleep(0.25)
    return not _is_runtime(pid, marker)


def sweep_orphan_runtime(path, keep_pid=None):
    """Stop a runtime whose server is gone. Returns the pid it stopped, else None.

    A record is an orphan only when its server is no longer running (same pid and start time),
    the pid still runs ComfyUI's ``main.py`` for this checkout, and it is not ``keep_pid``.
    A stale record, or a pid another program reused, is dropped without touching that program.
    """
    with _sweep_lock:
        record = _read_record(path)
        if record is None:
            return None
        pid, marker = record["pid"], str(record.get("marker") or "")
        if pid == keep_pid or _owner_alive(record):
            return None
        stopped = None
        if marker and _is_runtime(pid, marker):
            _send(pid, signal.SIGTERM)
            if not _wait_gone(pid, marker, TERMINATE_SECONDS):
                _send(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
                _wait_gone(pid, marker, KILL_SECONDS)
            stopped = pid
        forget_runtime(path, pid)
        return stopped


def _sweep_quietly(path):
    try:
        pid = sweep_orphan_runtime(path)
        if pid is not None:
            _log(f"stopped an orphan runtime (pid {pid}) left by a server that died")
    except Exception as error:  # a bookkeeping failure must never break the import or a job
        _log(f"orphan sweep failed: {error}")


def sweep_in_background(path):
    """Start-up sweep: nothing at all unless a record exists, and never blocks the caller."""
    if not Path(path).is_file():
        return None
    thread = threading.Thread(target=_sweep_quietly, args=(path,), daemon=True, name="creation-runtime-sweep")
    thread.start()
    return thread
