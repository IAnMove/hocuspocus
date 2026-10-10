"""Cross-process GPU lock for one shared graphics card.

The lock is off unless ``HOCUS_GPU_MACHINE_LOCK`` is ``1`` (or ``true``,
``yes``, ``on``). Every instance that shares ``HOME`` shares one lock file, so
turning it on is a decision for all of them.

The in-process generation queue still decides which local job runs. Only the
head of that queue takes a turn here, and it takes the turn before the process
GPU: a job that waits for another instance does not block local LLM, 3D, rig
or music work. Waiters are served in ticket order. Each waiter leaves a locked
ticket file in ``gpu.lock.queue`` next to the lock, and only the oldest live
ticket may take the lock, so an instance that runs jobs back to back cannot
keep the GPU from the others. The kernel drops the lock and the ticket locks
when a process exits.

Limits: only jobs that go through ``generation_slot`` take the lock. Workers
that use ``ResourceCoordinator.acquire`` (local LLM, 3D, rig) do not, and a
model can stay in VRAM after the lock is released. A holder that hangs while
alive blocks everyone until it is stopped. One lock file covers every GPU.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_ON = {"1", "true", "yes", "on"}
_BACKEND: str | None = None
# A ticket is locked right after it is created. One that is still unlocked
# after this long belongs to a process that has gone.
_TICKET_GRACE_SECONDS = 5.0


class _Held:
    def __init__(self, fd: int | None, *, noop: bool) -> None:
        self.fd = fd
        self.noop = noop


def machine_lock_enabled() -> bool:
    """Return whether this process should take the machine GPU lock (opt-in)."""
    return os.environ.get("HOCUS_GPU_MACHINE_LOCK", "").strip().lower() in _ON


def lock_path() -> Path:
    """Return the flock path. ``HOCUS_GPU_LOCK_PATH`` overrides the default."""
    raw = os.environ.get("HOCUS_GPU_LOCK_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".cache" / "hocuspocus" / "gpu.lock"


def meta_path() -> Path:
    """Return the sibling record of who holds :func:`lock_path`."""
    return lock_path().with_name("gpu.lock.json")


def queue_dir() -> Path:
    """Return the folder of waiting tickets next to :func:`lock_path`."""
    return lock_path().with_name("gpu.lock.queue")


def pid_alive(pid: object) -> bool:
    """Return whether ``pid`` still names a process."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_alive(pid)
    return _posix_pid_alive(pid)


def _posix_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_pid_alive(pid: int) -> bool:
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    ctypes.windll.kernel32.CloseHandle(handle)
    return True


def read_holder() -> dict[str, Any] | None:
    """Return the live holder record, or ``None`` when the lock is free.

    A pid that has already exited does not count. The kernel has released
    its flock; the json file can stay behind until the next holder writes it.
    """
    try:
        text = meta_path().read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not pid_alive(data.get("pid")):
        return None
    return data


def waiting_message(holder: Mapping[str, Any] | None, *, now: float | None = None) -> str:
    """Return the English sentence published while this process waits."""
    if not isinstance(holder, Mapping) or not holder:
        return "waiting for the GPU: held by another process"
    minutes = _held_minutes(holder.get("since"), now)
    job_id = holder.get("job_id") or "unknown"
    model = holder.get("model") or "unknown"
    return (
        f"waiting for the GPU: held by {_holder_name(holder)} "
        f"(pid {holder.get('pid')}, job {job_id}, model {model}) for {minutes} min"
    )


def _holder_name(holder: Mapping[str, Any]) -> str:
    port = str(holder.get("port") or "").strip()
    if port:
        return f":{port}"
    return "another process"


def _held_minutes(since: object, now: float | None) -> int:
    if isinstance(since, bool) or not isinstance(since, (int, float)):
        return 0
    clock = time.time() if now is None else float(now)
    return max(0, int((clock - float(since)) // 60))


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _text(source: Mapping[str, Any], key: str) -> str:
    value = source.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def owner_record(job: Mapping[str, Any]) -> dict[str, Any]:
    """Return the json record this process writes while it holds the lock."""
    params = _mapping(job.get("params"))
    workspace = _text(job, "workspace") or _text(params, "workspace")
    model = _text(job, "model") or _text(params, "model_type") or _text(params, "model")
    job_id = _text(job, "id") or _text(job, "job_id") or _text(job, "task_id")
    return {
        "pid": os.getpid(),
        "port": os.environ.get("SERVER_PORT", "").strip(),
        "workspace": workspace or os.environ.get("HOCUS_WORKSPACE", "").strip(),
        "job_id": job_id,
        "model": model,
        "since": time.time(),
    }


def lock_backend() -> str:
    """Return ``fcntl``, ``msvcrt``, or ``noop`` when locking is unavailable."""
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = _detect_backend()
    return _BACKEND


def _detect_backend() -> str:
    if os.name == "nt":
        try:
            import msvcrt  # noqa: F401
        except ImportError:
            _warn_unavailable()
            return "noop"
        return "msvcrt"
    try:
        import fcntl  # noqa: F401
    except ImportError:
        _warn_unavailable()
        return "noop"
    return "fcntl"


def _warn_unavailable() -> None:
    log.warning(
        "GPU machine lock is unavailable on this platform; "
        "jobs will not coordinate across processes."
    )


def _try_lock(fd: int) -> bool:
    kind = lock_backend()
    if kind == "fcntl":
        return _try_fcntl(fd)
    if kind == "msvcrt":
        return _try_msvcrt(fd)
    return True


def _try_fcntl(fd: int) -> bool:
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    except OSError as exc:
        if exc.errno in {11, 35}:
            return False
        raise
    return True


def _try_msvcrt(fd: int) -> bool:
    import msvcrt

    try:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    kind = lock_backend()
    if kind == "fcntl":
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
        return
    if kind == "msvcrt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def _open_lock() -> int | None:
    path = lock_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        log.warning(
            "GPU machine lock path %s is not usable; this process will not wait.",
            path,
        )
        return None


def _close(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        return


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_owner(job: Mapping[str, Any]) -> None:
    _write_json(meta_path(), owner_record(job))


def _clear_meta_if_ours(pid: int) -> None:
    path = meta_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return
    if not isinstance(data, dict) or data.get("pid") != pid:
        return
    try:
        path.unlink()
    except OSError:
        return


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        return


def _emit(job: Mapping[str, Any], publish: Callable[[Mapping[str, Any]], None] | None) -> None:
    if publish is None:
        return
    publish(dict(job))


def _announce(
    job: dict[str, Any],
    saved: tuple[Any, Any] | None,
    previous: str | None,
    publish: Callable[[Mapping[str, Any]], None] | None,
) -> tuple[tuple[Any, Any] | None, str | None]:
    message = waiting_message(read_holder())
    if message == previous:
        return saved, previous
    if saved is None:
        saved = (job.get("phase"), job.get("message"))
    job["phase"] = "waiting_gpu"
    job["message"] = message
    _emit(job, publish)
    return saved, message


def _put(job: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        job.pop(key, None)
        return
    job[key] = value


def _restore(
    job: dict[str, Any],
    saved: tuple[Any, Any] | None,
    publish: Callable[[Mapping[str, Any]], None] | None,
) -> None:
    if saved is None:
        return
    phase, message = saved
    _put(job, "phase", phase)
    _put(job, "message", message)
    _emit(job, publish)


def _settle_stop(
    job: dict[str, Any],
    saved: tuple[Any, Any] | None,
    publish: Callable[[Mapping[str, Any]], None] | None,
) -> None:
    status = str(job.get("status") or "")
    if status == "cancelled":
        job["phase"] = "cancelled"
        job["message"] = "Cancelled"
        _emit(job, publish)
        return
    if status == "cancelling" or job.get("cancel_requested"):
        job["phase"] = "cancelling"
        job["message"] = "Cancelling…"
        _emit(job, publish)
        return
    _restore(job, saved, publish)


class _Ticket:
    def __init__(self, fd: int, path: Path) -> None:
        self.fd = fd
        self.path = path


def _new_ticket() -> _Ticket | None:
    folder = queue_dir()
    name = f"{time.time_ns():020d}-{os.getpid()}-{os.urandom(3).hex()}.ticket"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(folder / name), os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o644)
    except OSError:
        log.warning("GPU machine lock queue %s is not usable; waiters are not ordered.", folder)
        return None
    if _try_lock(fd):
        return _Ticket(fd, folder / name)
    _close(fd)
    _unlink(folder / name)
    return None


def _discard_ticket(ticket: _Ticket) -> None:
    # Remove the name first where the platform allows it, so no waiter sees
    # this live ticket unlocked. Windows removes an open file only after close.
    _unlink(ticket.path)
    _close(ticket.fd)
    _unlink(ticket.path)


def _ticket_age(name: str) -> float:
    try:
        born = int(name.split("-", 1)[0])
    except ValueError:
        return float("inf")
    return (time.time_ns() - born) / 1e9


def _ticket_alive(path: Path) -> bool:
    """Whether ``path`` belongs to a live waiter. A dead waiter's ticket is removed."""
    try:
        fd = os.open(str(path), os.O_RDWR)
    except OSError:
        return False
    try:
        if not _try_lock(fd):
            return True
        _unlock(fd)
    finally:
        _close(fd)
    if _ticket_age(path.name) < _TICKET_GRACE_SECONDS:
        return True
    _unlink(path)
    return False


def _first_in_line(ticket: _Ticket) -> bool:
    try:
        names = sorted(entry.name for entry in os.scandir(ticket.path.parent) if entry.name.endswith(".ticket"))
    except OSError:
        return True
    for name in names:
        if name >= ticket.path.name:
            return True
        if _ticket_alive(ticket.path.parent / name):
            return False
    return True


class MachineTurn:
    """One job's turn on the machine GPU: a ticket in line, then the lock.

    :meth:`take` never blocks. The caller polls it while the job is the ready
    head of its local queue, and calls :meth:`release` when the job stops being
    ready, is cancelled, or has finished on the GPU. When the lock is disabled
    every call is a no-op and :meth:`take` returns True.
    """

    def __init__(
        self,
        job: dict[str, Any],
        *,
        publish: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.job = job
        self.publish = publish
        self.enabled = machine_lock_enabled()
        self._fd: int | None = None
        self._ticket: _Ticket | None = None
        self._held: _Held | None = None
        self._saved: tuple[Any, Any] | None = None
        self._previous: str | None = None

    @property
    def active(self) -> bool:
        """Whether this turn holds a ticket or the lock."""
        return self._ticket is not None or self._held is not None or self._fd is not None

    def take(self) -> bool:
        """Return True once this job holds the lock; a False result has announced the wait."""
        if not self.enabled or self._held is not None:
            return True
        if lock_backend() == "noop":
            self._held = _Held(None, noop=True)
            return True
        if self._fd is None:
            self._fd = _open_lock()
            if self._fd is None:
                self._held = _Held(None, noop=True)
                return True
        if self._ticket is None:
            self._ticket = _new_ticket()
        if (self._ticket is None or _first_in_line(self._ticket)) and _try_lock(self._fd):
            _write_owner(self.job)
            self._held, self._fd = _Held(self._fd, noop=False), None
            self._drop_ticket()
            _restore(self.job, self._saved, self.publish)
            self._saved = self._previous = None
            return True
        self._saved, self._previous = _announce(self.job, self._saved, self._previous, self.publish)
        return False

    def release(self) -> None:
        """Give back the ticket and the lock, and undo the waiting message."""
        self._drop_ticket()
        held, self._held = self._held, None
        if held is not None:
            _release(held)
        fd, self._fd = self._fd, None
        if fd is not None:
            _close(fd)
        if self._saved is not None:
            _settle_stop(self.job, self._saved, self.publish)
        self._saved = self._previous = None

    def _drop_ticket(self) -> None:
        ticket, self._ticket = self._ticket, None
        if ticket is not None:
            _discard_ticket(ticket)


def _release(held: _Held) -> None:
    if held.noop or held.fd is None:
        return
    fd = held.fd
    # Drop the record while this process still owns the flock, so a new
    # holder cannot have its json removed after it wins the lock.
    _clear_meta_if_ours(os.getpid())
    try:
        _unlock(fd)
    finally:
        os.close(fd)
