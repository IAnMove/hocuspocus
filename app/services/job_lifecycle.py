"""Thread-safe state transitions for Maestro's in-process generation jobs.

Jobs are mutable dictionaries shared by API handlers and background workers.
This module keeps terminal-state changes and abort-state registration atomic so
that cancellation cannot be lost to a late ``completed``/``failed`` write.
It deliberately has no dependency on ``launch.py`` or model code, which keeps
the race behavior testable without loading the generation engine.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import count
from typing import Any


TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_lifecycle_lock = threading.RLock()
_registrations: dict[
    str,
    tuple[
        MutableMapping[str, Any],
        MutableMapping[str, Any],
        Callable[[], None] | None,
    ],
] = {}
_generation_queue_condition = threading.Condition(threading.RLock())
_generation_queue_sequence = count()
_generation_queues: dict[
    int,
    deque[tuple[int, object, MutableMapping[str, Any]]],
] = {}
_generation_queue_locks: dict[int, Any] = {}
_job_state_observer: Callable[[Mapping[str, Any]], None] | None = None


def set_job_state_observer(
    observer: Callable[[Mapping[str, Any]], None] | None,
) -> None:
    """Register one best-effort observer for externally visible job changes.

    The lifecycle layer stays independent from the canonical task registry.  A
    host such as ``launch.py`` can subscribe after startup and translate the
    already-atomic job snapshot into SSE/task updates.  Observer failures never
    interfere with generation and callbacks run after lifecycle locks release.
    """
    global _job_state_observer
    with _lifecycle_lock:
        _job_state_observer = observer


def _notify_job_state(job: MutableMapping[str, Any]) -> None:
    with _lifecycle_lock:
        observer = _job_state_observer
        snapshot = dict(job)
        if isinstance(snapshot.get("output_files"), list):
            snapshot["output_files"] = list(snapshot["output_files"])
        if isinstance(snapshot.get("clip_output_files"), dict):
            snapshot["clip_output_files"] = dict(snapshot["clip_output_files"])
    if observer is None:
        return
    try:
        observer(snapshot)
    except Exception:
        # Observability must never turn a successful model transition into a
        # failed generation.  The periodic canonical reconciler remains the
        # recovery path if a registry write is temporarily unavailable.
        pass


@dataclass(frozen=True)
class CancelResult:
    """Result of a cancellation request."""

    changed: bool
    was_running: bool
    abort_signalled: bool


GENERATED_MEDIA_EXTENSIONS = frozenset({
    ".aac", ".flac", ".gif", ".jpeg", ".jpg", ".m4a", ".mkv", ".mov",
    ".mp3", ".mp4", ".ogg", ".png", ".wav", ".webm", ".webp",
})


def collect_job_outputs(
    gen: Mapping[str, Any],
    out_dir: str,
    before: set[str] | None = None,
    *,
    allow_legacy_fallback: bool = False,
) -> list[str]:
    """Return only files explicitly registered by this generation state.

    WGP records generated media in ``file_list`` and ``audio_file_list``.
    Those lists are job-local, unlike a directory before/after scan that can
    accidentally claim a concurrent pipeline operation's output.  A guarded
    one-file fallback remains for older non-Director generators that do not
    register their result.
    """
    output_root = os.path.normcase(os.path.realpath(os.path.abspath(out_dir)))
    owned: list[str] = []
    seen: set[str] = set()
    for list_name in ("artifact_list", "file_list", "audio_file_list"):
        values = gen.get(list_name) or []
        if not isinstance(values, (list, tuple)):
            continue
        for value in values:
            if isinstance(value, tuple):
                value = value[0] if value else None
            if not isinstance(value, str) or not value:
                continue
            # WGP registers both bare filenames (``clip.jpg``) and paths that
            # are already rooted at a relative output directory
            # (``outputs/clip.jpg``).  Blindly joining every relative value to
            # ``out_dir`` turns the latter into ``outputs/outputs/clip.jpg``
            # and silently loses the generated artifact.  Try the two exact
            # interpretations, accepting only an existing direct child of the
            # resolved output root so the ownership boundary remains strict.
            candidates = [value] if os.path.isabs(value) else [
                value,
                os.path.join(out_dir, value),
            ]
            candidate = None
            checked: set[str] = set()
            for registered_path in candidates:
                resolved = os.path.realpath(os.path.abspath(registered_path))
                normalized = os.path.normcase(resolved)
                if normalized in checked:
                    continue
                checked.add(normalized)
                if (
                    os.path.normcase(os.path.dirname(resolved)) == output_root
                    and os.path.isfile(resolved)
                ):
                    candidate = resolved
                    break
            if candidate is None:
                continue
            filename = os.path.basename(candidate)
            if (
                filename.startswith("_continuation_")
                or filename in seen
            ):
                continue
            seen.add(filename)
            owned.append(filename)

    if owned or not allow_legacy_fallback:
        return owned

    # Legacy fallback: accept exactly one newly-created, non-temporary media
    # file.  Ambiguity is safer to report as no output than to claim another
    # operation's artifact and stamp it with this job's metadata.
    try:
        candidates = []
        for filename in sorted(set(os.listdir(out_dir)) - set(before or ())):
            extension = os.path.splitext(filename)[1].lower()
            if (
                extension not in GENERATED_MEDIA_EXTENSIONS
                or filename.startswith("_")
                or not os.path.isfile(os.path.join(out_dir, filename))
            ):
                continue
            candidates.append(filename)
    except OSError:
        return []
    return candidates if len(candidates) == 1 else []


def call_with_sticky_interrupt(
    abort_state: Mapping[str, Any],
    model: Any,
    callable_: Callable[..., Any],
    *args: Any,
    poll_interval: float = 0.02,
    **kwargs: Any,
) -> Any:
    """Run a model call while making a durable abort survive model resets.

    Several model wrappers clear ``_interrupt`` at the beginning of their
    ``generate`` method.  A cancellation can land just before that reset, so
    relay the durable job abort flag until the call exits.  The normal direct
    interrupt remains the fast path; this closes the reset race.
    """

    def _reassert_interrupt() -> None:
        try:
            setattr(model, "_interrupt", True)
        except Exception:
            pass

    if abort_state.get("abort", False):
        _reassert_interrupt()
        return None

    stopped = threading.Event()

    def _relay() -> None:
        while not stopped.wait(poll_interval):
            if abort_state.get("abort", False):
                _reassert_interrupt()

    relay = threading.Thread(
        target=_relay,
        daemon=True,
        name="maestro_abort_relay",
    )
    relay.start()
    try:
        # Close the window between the first check and relay startup.
        if abort_state.get("abort", False):
            _reassert_interrupt()
            return None
        return callable_(*args, **kwargs)
    finally:
        if abort_state.get("abort", False):
            _reassert_interrupt()
        stopped.set()
        relay.join(timeout=max(0.1, poll_interval * 2))


def is_cancel_requested(job: MutableMapping[str, Any]) -> bool:
    """Return whether cancellation is durable for ``job``."""
    with _lifecycle_lock:
        return bool(job.get("cancel_requested")) or job.get("status") in {
            "cancelling", "cancelled",
        }


def snapshot_job(job: MutableMapping[str, Any]) -> dict[str, Any]:
    """Return a consistent shallow snapshot for API polling."""
    with _lifecycle_lock:
        snapshot = dict(job)
        if isinstance(snapshot.get("output_files"), list):
            snapshot["output_files"] = list(snapshot["output_files"])
        if isinstance(snapshot.get("clip_output_files"), dict):
            snapshot["clip_output_files"] = dict(snapshot["clip_output_files"])
        return snapshot


def record_job_outputs(
    job: MutableMapping[str, Any],
    output_files: list[str],
    *,
    clip_output_files: Mapping[int | str, str] | None = None,
    join_output_file: str | None = None,
) -> list[str]:
    """Merge discovered outputs/artifact metadata without changing status."""
    with _lifecycle_lock:
        merged = list(job.get("output_files") or [])
        for filename in output_files:
            if filename not in merged:
                merged.append(filename)
        job["output_files"] = merged
        if clip_output_files:
            current_clip_outputs = job.get("clip_output_files") or {}
            if isinstance(current_clip_outputs, Mapping):
                clip_outputs = dict(current_clip_outputs)
            elif isinstance(current_clip_outputs, (list, tuple)):
                # While a multiclip render is live, launch.py keeps sparse
                # positional progress in a list. Its durable representation
                # is a mapping. Calling dict(list_of_filenames) raised after
                # all clips had already rendered because a filename is not a
                # key/value pair.
                clip_outputs = {
                    str(index): filename
                    for index, filename in enumerate(current_clip_outputs)
                    if filename
                }
            else:
                clip_outputs = {}
            for index, filename in clip_output_files.items():
                try:
                    key = str(int(index))
                except (TypeError, ValueError):
                    continue
                if filename:
                    clip_outputs[key] = filename
            job["clip_output_files"] = clip_outputs
        if join_output_file:
            job["join_output_file"] = join_output_file
        result = list(merged)
    _notify_job_state(job)
    return result


def try_start(job: MutableMapping[str, Any], **updates: Any) -> bool:
    """Atomically move a queued job to running unless it was cancelled."""
    if "status" in updates:
        raise ValueError("status must be changed through a lifecycle transition")
    changed = False
    started = False
    with _lifecycle_lock:
        if is_cancel_requested(job):
            changed = _acknowledge_cancel_locked(job)
        elif job.get("status") == "queued":
            job.update(updates)
            job["started_at"] = job.get("started_at") or time.time()
            job["status"] = "running"
            changed = True
            started = True
    if changed:
        _notify_job_state(job)
    return started


def try_requeue(job: MutableMapping[str, Any], **updates: Any) -> bool:
    """Return a multi-phase job to queued unless cancellation won first."""
    if "status" in updates:
        raise ValueError("status must be changed through a lifecycle transition")
    changed = False
    requeued = False
    with _lifecycle_lock:
        if is_cancel_requested(job):
            changed = _acknowledge_cancel_locked(job)
        elif job.get("status") == "running":
            job.update(updates)
            job["status"] = "queued"
            changed = True
            requeued = True
    if changed:
        _notify_job_state(job)
    return requeued


def update_job(job: MutableMapping[str, Any], **updates: Any) -> bool:
    """Update a live job without replacing a terminal/cancelled message."""
    if "status" in updates:
        raise ValueError("status must be changed through a lifecycle transition")
    updated = False
    with _lifecycle_lock:
        if is_cancel_requested(job) or job.get("status") != "running":
            return False
        job.update(updates)
        updated = True
    if updated:
        _notify_job_state(job)
    return updated


def register_abort_state(
    job: MutableMapping[str, Any],
    job_id: str,
    active_states: MutableMapping[str, MutableMapping[str, Any]],
    state: MutableMapping[str, Any],
    *,
    interrupt_model: Callable[[], None] | None = None,
) -> bool:
    """Register a worker's abort dictionary unless cancellation won first.

    Dummy states for non-Wan tools still receive ``abort=True`` but have no
    interrupt callback. Callback ownership is tracked separately by state
    identity so an old worker cannot interrupt or unregister a newer phase.
    """
    with _lifecycle_lock:
        state.setdefault("abort", False)
        if is_cancel_requested(job) or job.get("status") != "running":
            state["abort"] = True
            return False
        active_states[job_id] = state
        _registrations[job_id] = (job, state, interrupt_model)
        return True


def unregister_abort_state(
    job_id: str,
    active_states: MutableMapping[str, MutableMapping[str, Any]],
    state: MutableMapping[str, Any] | None = None,
) -> None:
    """Remove only the abort state owned by the finishing worker.

    Releasing the matching state is also the worker's cancellation
    acknowledgement.  A stale worker must never settle a newer phase, so the
    terminal transition requires ownership of both the public active state and
    the private registration.
    """
    acknowledged_job: MutableMapping[str, Any] | None = None
    with _lifecycle_lock:
        current = active_states.get(job_id)
        owns_active_state = current is not None and (
            state is None or current is state
        )
        if owns_active_state:
            active_states.pop(job_id, None)
        registration = _registrations.get(job_id)
        owns_registration = registration is not None and (
            state is None or registration[1] is state
        )
        if owns_registration:
            _registrations.pop(job_id, None)
        if (
            owns_active_state
            and owns_registration
            and registration is not None
            and current is registration[1]
            and _acknowledge_cancel_locked(registration[0])
        ):
            acknowledged_job = registration[0]
    if acknowledged_job is not None:
        _notify_job_state(acknowledged_job)


def _acknowledge_cancel_locked(
    job: MutableMapping[str, Any],
    updates: Mapping[str, Any] | None = None,
) -> bool:
    """Settle a requested cancellation while ``_lifecycle_lock`` is held."""
    if job.get("status") in TERMINAL_STATUSES or not is_cancel_requested(job):
        return False
    if updates:
        job.update(updates)
    # Cancellation is absorbing.  Neutral settlement metadata is allowed, but
    # no caller can turn an acknowledged cancellation into completed/failed or
    # replace the stable terminal message.
    job["cancel_requested"] = True
    job["status"] = "cancelled"
    job["phase"] = "cancelled"
    job["message"] = "Cancelled"
    job["finished_at"] = job.get("finished_at") or time.time()
    return True


def _has_active_registration_locked(
    job: MutableMapping[str, Any],
) -> bool:
    """Return whether a worker still owns a registered abort state."""
    return any(registration[0] is job for registration in _registrations.values())


def acknowledge_cancel(
    job: MutableMapping[str, Any],
    **updates: Any,
) -> bool:
    """Acknowledge that a cancelling worker has stopped and released work.

    This is the explicit settlement path for workers that do not own an abort
    state and exit without a normal ``finish_job`` call.  It is idempotent and
    refuses to cancel a job unless a durable cancellation request already won.
    """
    if "status" in updates:
        raise ValueError("status must be changed through a lifecycle transition")
    with _lifecycle_lock:
        changed = _acknowledge_cancel_locked(job, updates)
    if changed:
        _notify_job_state(job)
    return changed


def request_cancel(
    job: MutableMapping[str, Any],
    *,
    job_id: str | None = None,
    active_states: MutableMapping[str, MutableMapping[str, Any]] | None = None,
) -> CancelResult:
    """Atomically request cancellation and signal the matching active state."""
    result: CancelResult
    with _lifecycle_lock:
        status = job.get("status")
        if status in TERMINAL_STATUSES:
            return CancelResult(False, False, False)
        if status == "cancelling":
            return CancelResult(False, False, False)

        was_running = status == "running"
        job["cancel_requested"] = True

        abort_signalled = False
        state = active_states.get(job_id) if active_states is not None and job_id else None
        registration = _registrations.get(job_id) if job_id else None
        if (
            was_running
            and state is not None
            and registration is not None
            and registration[0] is job
            and registration[1] is state
        ):
            state["abort"] = True
            abort_signalled = True
            if registration[2] is not None:
                try:
                    registration[2]()
                except Exception:
                    pass

        if was_running:
            # The request is durable and inference has been signalled, but the
            # worker still owns its resource until finish/unregister/explicit
            # acknowledgement.  Do not publish a terminal timestamp early.
            job["status"] = "cancelling"
            job["phase"] = "cancelling"
            job["message"] = "Cancelling…"
            job["finished_at"] = None
        else:
            # Queued/waiting jobs own no active model invocation and can settle
            # synchronously without a worker acknowledgement.
            _acknowledge_cancel_locked(job)

        result = CancelResult(True, was_running, abort_signalled)
    _notify_job_state(job)
    return result


def finish_job(
    job: MutableMapping[str, Any],
    status: str,
    **updates: Any,
) -> bool:
    """Publish a completed/failed result unless cancellation already won."""
    if status not in {"completed", "failed"}:
        raise ValueError(f"Invalid terminal job status: {status}")
    if "status" in updates:
        raise ValueError("status must be changed through a lifecycle transition")
    changed = False
    published = False
    with _lifecycle_lock:
        if is_cancel_requested(job):
            # A late completed/failed result is only an acknowledgement that
            # the cancelling worker reached its terminal boundary. If it still
            # owns an abort-state registration, keep `cancelling` until
            # unregister_abort_state confirms the worker has released it.
            # Workers without a registration settle directly here.
            if not _has_active_registration_locked(job):
                changed = _acknowledge_cancel_locked(job)
        elif job.get("status") == "running":
            job.update(updates)
            job["finished_at"] = job.get("finished_at") or time.time()
            job["status"] = status
            changed = True
            published = True
    if changed:
        _notify_job_state(job)
    return published


def register_generation_job(
    generation_lock: threading.Lock,
    job: MutableMapping[str, Any],
) -> int:
    """Register ``job`` in the fair queue for one GPU lock.

    Registration is intentionally separate from worker startup. API handlers
    can therefore reserve the FIFO position synchronously, before thread
    scheduling has a chance to reorder a burst of submissions.
    """
    lock_key = id(generation_lock)
    with _generation_queue_condition:
        queue = _generation_queues.setdefault(lock_key, deque())
        token = job.get("_generation_queue_token")
        if (
            job.get("_generation_queue_lock_key") == lock_key
            and token is not None
        ):
            for position, (_, queued_token, _) in enumerate(queue, start=1):
                if queued_token is token:
                    return position

        token = object()
        sequence = next(_generation_queue_sequence)
        queue.append((sequence, token, job))
        # Keep a strong reference while waiters exist so a recycled object id
        # can never inherit another lock's queue.
        _generation_queue_locks[lock_key] = generation_lock
        job["_generation_queue_lock_key"] = lock_key
        job["_generation_queue_token"] = token
        job["_generation_queue_sequence"] = sequence
        _generation_queue_condition.notify_all()
        return len(queue)


def generation_queue_position(
    generation_lock: threading.Lock,
    job: MutableMapping[str, Any],
) -> int | None:
    """Return the 1-based waiting position, or ``None`` once active/terminal."""
    lock_key = id(generation_lock)
    token = job.get("_generation_queue_token")
    if token is None or job.get("_generation_queue_lock_key") != lock_key:
        return None
    with _generation_queue_condition:
        for position, (_, queued_token, _) in enumerate(
            _generation_queues.get(lock_key, ()),
            start=1,
        ):
            if queued_token is token:
                return position
    return None


def _remove_generation_waiter(
    lock_key: int,
    token: object,
    job: MutableMapping[str, Any],
) -> None:
    queue = _generation_queues.get(lock_key)
    if queue is not None:
        for index, (_, queued_token, _) in enumerate(queue):
            if queued_token is token:
                del queue[index]
                break
        if not queue:
            _generation_queues.pop(lock_key, None)
            _generation_queue_locks.pop(lock_key, None)
    if job.get("_generation_queue_token") is token:
        job.pop("_generation_queue_token", None)
        job.pop("_generation_queue_lock_key", None)
    _generation_queue_condition.notify_all()


def acquire_generation_slot(
    generation_lock: threading.Lock,
    job: MutableMapping[str, Any],
    *,
    poll_interval: float = 0.1,
) -> bool:
    """Acquire the GPU lock in registration order, with cancellable waiting."""
    register_generation_job(generation_lock, job)
    lock_key = id(generation_lock)
    token = job.get("_generation_queue_token")

    while True:
        with _generation_queue_condition:
            if is_cancel_requested(job):
                _remove_generation_waiter(lock_key, token, job)
                return False
            queue = _generation_queues.get(lock_key)
            is_head = bool(queue and queue[0][1] is token)
            if not is_head:
                _generation_queue_condition.wait(timeout=poll_interval)
                continue

        # Only the FIFO head is allowed to compete for the underlying mutex.
        if not generation_lock.acquire(timeout=poll_interval):
            continue

        with _generation_queue_condition:
            if is_cancel_requested(job):
                generation_lock.release()
                _remove_generation_waiter(lock_key, token, job)
                return False
            queue = _generation_queues.get(lock_key)
            if not queue or queue[0][1] is not token:
                # Defensive only: the head cannot normally change while this
                # non-cancelled waiter is acquiring the generation mutex.
                generation_lock.release()
                continue
            _remove_generation_waiter(lock_key, token, job)
        return True


@contextmanager
def generation_slot(
    generation_lock: threading.Lock,
    job: MutableMapping[str, Any],
    *,
    poll_interval: float = 0.1,
) -> Iterator[bool]:
    """Context manager form of :func:`acquire_generation_slot`."""
    acquired = acquire_generation_slot(
        generation_lock, job, poll_interval=poll_interval,
    )
    try:
        yield acquired
    finally:
        if acquired:
            generation_lock.release()
            with _generation_queue_condition:
                _generation_queue_condition.notify_all()
