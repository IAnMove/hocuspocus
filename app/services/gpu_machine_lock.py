"""Cross-process GPU lock for one shared graphics card.

The in-process generation queue still decides which local job runs. This lock
is taken only after that queue has handed the job the process GPU, and it is
released before the process GPU returns to the local queue. The kernel drops
the lock when the holder exits. ``HOCUS_GPU_MACHINE_LOCK`` of ``0``,
``false``, ``no``, or ``off`` takes nothing.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_OFF = {"0", "false", "no", "off"}
_BACKEND: str | None = None


class _Held:
    def __init__(self, fd: int | None, *, noop: bool) -> None:
        self.fd = fd
        self.noop = noop


def machine_lock_enabled() -> bool:
    """Return whether this process should take the machine GPU lock."""
    raw = os.environ.get("HOCUS_GPU_MACHINE_LOCK")
    if raw is None:
        return True
    return raw.strip().lower() not in _OFF


def lock_path() -> Path:
    """Return the flock path. ``HOCUS_GPU_LOCK_PATH`` overrides the default."""
    raw = os.environ.get("HOCUS_GPU_LOCK_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".cache" / "hocuspocus" / "gpu.lock"


def meta_path() -> Path:
    """Return the sibling record of who holds :func:`lock_path`."""
    return lock_path().with_name("gpu.lock.json")


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


def _stopped(should_stop: Callable[[], bool] | None) -> bool:
    if should_stop is None:
        return False
    return bool(should_stop())


def _wait_for_lock(
    fd: int,
    job: dict[str, Any],
    *,
    poll_interval: float,
    should_stop: Callable[[], bool] | None,
    publish: Callable[[Mapping[str, Any]], None] | None,
) -> _Held | None:
    saved: tuple[Any, Any] | None = None
    previous: str | None = None
    while True:
        if _stopped(should_stop):
            _close(fd)
            _settle_stop(job, saved, publish)
            return None
        if _try_lock(fd):
            _write_owner(job)
            _restore(job, saved, publish)
            return _Held(fd, noop=False)
        saved, previous = _announce(job, saved, previous, publish)
        time.sleep(max(0.01, float(poll_interval)))


def _acquire(
    job: dict[str, Any],
    *,
    poll_interval: float,
    should_stop: Callable[[], bool] | None,
    publish: Callable[[Mapping[str, Any]], None] | None,
) -> _Held | None:
    fd = _open_lock()
    if fd is None:
        return _Held(None, noop=True)
    try:
        return _wait_for_lock(
            fd,
            job,
            poll_interval=poll_interval,
            should_stop=should_stop,
            publish=publish,
        )
    except Exception:
        _close(fd)
        raise


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


@contextmanager
def machine_gpu_lock(
    job: dict[str, Any],
    *,
    poll_interval: float = 0.25,
    should_stop: Callable[[], bool] | None = None,
    publish: Callable[[Mapping[str, Any]], None] | None = None,
) -> Iterator[_Held | None]:
    """Hold the machine lock for one GPU job, or yield ``None`` when disabled.

    ``None`` with the lock enabled means the wait was stopped. A noop hold
    is returned when this platform cannot lock, so the job still runs.
    """
    if not machine_lock_enabled():
        yield None
        return
    held = _acquire(
        job,
        poll_interval=poll_interval,
        should_stop=should_stop,
        publish=publish,
    )
    try:
        yield held
    finally:
        if held is not None:
            _release(held)


@contextmanager
def machine_generation(
    job: dict[str, Any],
    acquired: bool,
    *,
    poll_interval: float,
    should_stop: Callable[[], bool] | None,
    publish: Callable[[Mapping[str, Any]], None] | None,
) -> Iterator[bool]:
    """Wrap one acquired process slot with the machine lock.

    The caller releases the process lock after this context exits. A stopped
    wait yields ``False`` so the caller does not start the GPU job.
    """
    if not acquired:
        yield False
        return
    with machine_gpu_lock(
        job,
        poll_interval=poll_interval,
        should_stop=should_stop,
        publish=publish,
    ) as held:
        yield not (machine_lock_enabled() and held is None)
