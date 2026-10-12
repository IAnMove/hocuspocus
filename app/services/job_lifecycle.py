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
_MISSING = object()
_DURATION_KEYS = ("queue_seconds", "duration_seconds", "_duration_seconds")


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


def _wake_job_waiters(snapshot: Mapping[str, Any]) -> None:
    """Wake jobs.wait. A missing helper must not fail the generation."""
    try:
        from services.jobs_wait import note_job_state
        note_job_state(snapshot)
    except Exception:
        return


def _notify_job_state(job: MutableMapping[str, Any]) -> None:
    with _lifecycle_lock:
        observer = _job_state_observer
        snapshot = dict(job)
        if isinstance(snapshot.get("output_files"), list):
            snapshot["output_files"] = list(snapshot["output_files"])
        if isinstance(snapshot.get("clip_output_files"), dict):
            snapshot["clip_output_files"] = dict(snapshot["clip_output_files"])
    _wake_job_waiters(snapshot)
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


def positional_clip_outputs(value: Any) -> list[Any]:
    """Return clip filenames in shot order for a list or an indexed dict.

    A live multiclip job stores a sparse list. Registration stores
    ``{"0": filename}``. Iterating the dict yields the keys ``"0"`` and
    ``"1"``, which Director then saved as if they were video files.
    """

    if isinstance(value, Mapping):
        indexed: list[tuple[int, Any]] = []
        for key, filename in value.items():
            try:
                index = int(key)
            except (TypeError, ValueError):
                continue
            if index >= 0:
                indexed.append((index, filename or None))
        if not indexed:
            return []
        last = max(index for index, _filename in indexed)
        slots: list[Any] = [None] * (last + 1)
        for index, filename in sorted(indexed, key=lambda item: item[0]):
            if index >= len(slots):
                slots.extend([None] * (index + 1 - len(slots)))
            slots[index] = filename
        return slots
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def new_media_files(out_dir: str, before: Any) -> list[str]:
    """Media files created in ``out_dir`` since ``before``. Hidden and temporary files are never outputs: the
    workspace task database (``.maestro-tasks-v1.sqlite3-wal``) and editor temps are written there during a job."""
    try:
        after = set(os.listdir(out_dir)) if os.path.isdir(out_dir) else set()
    except OSError:
        return []
    return sorted(
        name for name in after - set(before or ())
        if os.path.splitext(name)[1].lower() in GENERATED_MEDIA_EXTENSIONS
        and not name.startswith((".", "_")) and os.path.isfile(os.path.join(out_dir, name))
    )


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


def _required_priority(raw: Any) -> int:
    """Return an integer priority. ``None`` is the FIFO default of zero."""
    if raw is None:
        return 0
    if isinstance(raw, bool) or type(raw) is not int:
        raise ValueError("priority must be an integer")
    return raw


def generation_queue_priority(job: Mapping[str, Any]) -> int:
    """Higher integers run first. Omitted priority keeps registration order."""
    if "priority" in job:
        return _required_priority(job.get("priority"))
    params = job.get("params")
    if isinstance(params, Mapping) and "priority" in params:
        return _required_priority(params.get("priority"))
    return 0


def ensure_generation_priority(payload: Mapping[str, Any]) -> None:
    """Reject a non-integer generate/submit priority before queueing."""
    if "priority" not in payload:
        return
    generation_queue_priority({"priority": payload.get("priority")})


def _non_negative_seconds(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number < 0 or number != number or number == float("inf"):
        return None
    return number


def _explicit_seconds(source: Mapping[str, Any]) -> float | None:
    for key in _DURATION_KEYS:
        if key not in source:
            continue
        parsed = _non_negative_seconds(source.get(key))
        if parsed is not None:
            return parsed
    return None


def _frames_seconds(job: Mapping[str, Any], params: Mapping[str, Any]) -> float | None:
    frames = _non_negative_seconds(params.get("video_length"))
    if frames is None or frames <= 0:
        return None
    fps = _non_negative_seconds(params.get("fps", job.get("fps", 24)))
    if fps is None or fps <= 0:
        return None
    return frames / fps


def generation_queue_seconds(job: Mapping[str, Any]) -> float | None:
    """Known output length in seconds, or ``None`` when length was not declared.

    A one-second still is ``generation_mode=image``. Unknown length does not
    jump ahead of another job that also omitted a length.
    """
    explicit = _explicit_seconds(job)
    if explicit is not None:
        return explicit
    params = job.get("params")
    if not isinstance(params, Mapping):
        params = {}
    else:
        explicit = _explicit_seconds(params)
        if explicit is not None:
            return explicit
    if params.get("generation_mode", job.get("generation_mode")) == "image":
        return 1.0
    return _frames_seconds(job, params)


def _pop_command_priority(command: dict[str, Any]) -> Any:
    """Remove optional priority so strict command schemas do not reject it."""
    found = _MISSING
    if "priority" in command:
        found = command.pop("priority")
    payload = command.get("input")
    if isinstance(payload, dict):
        if "priority" in payload:
            inner = payload.pop("priority")
            if found is _MISSING:
                found = inner
        params = payload.get("params")
        if isinstance(params, dict) and "priority" in params:
            inner = params.pop("priority")
            if found is _MISSING:
                found = inner
            if not params:
                payload.pop("params", None)
    return found


def take_submission_priority(command: Any) -> int | None:
    """Lift optional priority off a generate command before it is frozen."""
    if not isinstance(command, dict):
        return None
    raw = _pop_command_priority(command)
    if raw is _MISSING or raw is None:
        return None
    return _required_priority(raw)


def priority_fields(priority: int | None) -> dict[str, int]:
    """Return the generate-body fragment for one already validated priority."""
    if priority is None:
        return {}
    return {"priority": priority}


MAX_WAIT_ENV = "HOCUS_QUEUE_MAX_WAIT_SECONDS"
DEFAULT_MAX_WAIT_SECONDS = 300.0


def queue_max_wait_seconds() -> float:
    """Wait after which only a higher priority may overtake a job. ``0`` turns aging off."""
    raw = os.environ.get(MAX_WAIT_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_MAX_WAIT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MAX_WAIT_SECONDS
    return value if value >= 0 and value == value and value != float("inf") else DEFAULT_MAX_WAIT_SECONDS


def _overdue(new_job: Mapping[str, Any], queued_job: Mapping[str, Any], now: float, limit: float) -> bool:
    """A job that waited past the limit keeps its place against equal or lower priority.

    Shortest-first alone let images (1 s) overtake TTS lines, which declare a
    20 s cap as their length, for as long as images kept arriving.
    """
    entered = queued_job.get("_queue_entered_at")
    if limit <= 0 or type(entered) is not float or now - entered < limit:
        return False
    return int(new_job.get("_queue_priority", 0)) <= int(queued_job.get("_queue_priority", 0))


def _scheduled_before(
    new_sequence: int,
    new_job: Mapping[str, Any],
    queued_sequence: int,
    queued_job: Mapping[str, Any],
) -> bool:
    """Pending order: higher priority, then shorter known work, then FIFO."""
    new_priority = int(new_job.get("_queue_priority", 0))
    queued_priority = int(queued_job.get("_queue_priority", 0))
    if new_priority != queued_priority:
        return new_priority > queued_priority
    new_seconds = new_job.get("_queue_seconds")
    queued_seconds = queued_job.get("_queue_seconds")
    if (
        type(new_seconds) is float
        and type(queued_seconds) is float
        and new_seconds != queued_seconds
    ):
        return new_seconds < queued_seconds
    return new_sequence < queued_sequence


def _insert_generation_waiter(
    queue: deque[tuple[int, object, MutableMapping[str, Any]]],
    entry: tuple[int, object, MutableMapping[str, Any]],
) -> int:
    """Insert one waiter and return its 1-based position.

    The local GPU lock has a single owner. Ordering the pending queue is
    what lets a short or high-priority job start before a long low-priority
    job that has not taken the GPU yet. The running owner is not preempted.
    A job that has waited ``queue_max_wait_seconds()`` is overtaken only by a
    higher priority.
    """
    sequence, _token, job = entry
    now = time.monotonic()
    job["_queue_entered_at"] = now
    limit = queue_max_wait_seconds()
    floor = 0
    for position, (_, _, queued_job) in enumerate(queue):
        if _overdue(job, queued_job, now, limit):
            floor = position + 1
    index = len(queue)
    for position in range(floor, len(queue)):
        queued_sequence, _, queued_job = queue[position]
        if _scheduled_before(sequence, job, queued_sequence, queued_job):
            index = position
            break
    queue.insert(index, entry)
    return index + 1


def register_generation_job(
    generation_lock: threading.Lock,
    job: MutableMapping[str, Any],
) -> int:
    """Register ``job`` on the single GPU queue before its worker starts.

    Registration stays separate from worker startup so a burst of API calls
    cannot lose its order to thread scheduling. Omitted priority is ``0``.
    Equal priority and equal or unknown length keep registration order.
    """
    priority = generation_queue_priority(job)
    seconds = generation_queue_seconds(job)
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

        job["_queue_priority"] = priority
        job["_queue_seconds"] = None if seconds is None else float(seconds)
        token = object()
        sequence = next(_generation_queue_sequence)
        position = _insert_generation_waiter(queue, (sequence, token, job))
        # Keep a strong reference while waiters exist so a recycled object id
        # can never inherit another lock's queue.
        _generation_queue_locks[lock_key] = generation_lock
        job["_generation_queue_lock_key"] = lock_key
        job["_generation_queue_token"] = token
        job["_generation_queue_sequence"] = sequence
        _generation_queue_condition.notify_all()
        return position


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


def _ready_head(
    queue: deque[tuple[int, object, MutableMapping[str, Any]]] | None,
    token: object,
    job: MutableMapping[str, Any],
    yield_to: Callable[[float], bool] | None,
) -> bool:
    """Whether ``job`` heads the queue and is not standing aside for ``yield_to``."""
    if not (queue and queue[0][1] is token):
        return False
    waited = time.monotonic() - float(job.get("_queue_entered_at") or time.monotonic())
    return yield_to is None or not yield_to(waited)


def _hold_machine_turn(machine: Any, ready: bool, poll_interval: float) -> bool:
    """Whether the ready queue head holds its machine turn (always, without one).

    Only the ready head keeps a ticket or the machine lock: a head that stops
    being ready gives them back, so a local job ahead of it can take its turn.
    """
    if machine is None:
        return True
    if not ready:
        machine.release()
        return False
    if machine.take():
        return True
    with _generation_queue_condition:
        _generation_queue_condition.wait(timeout=poll_interval)
    return False


def acquire_generation_slot(
    generation_lock: threading.Lock,
    job: MutableMapping[str, Any],
    *,
    poll_interval: float = 0.1,
    yield_to: Callable[[float], bool] | None = None,
    machine: Any = None,
) -> bool:
    """Acquire the single GPU lock in scheduled pending order.

    ``yield_to(waited)`` receives how long this job has waited. While it
    returns true, the queue head leaves the free lock to another waiter on the
    same device (see ``ResourceCoordinator.has_waiter_owed_turn``).

    ``machine`` is the job's ``gpu_machine_lock.MachineTurn``. The ready queue
    head takes it before the process lock, so waiting for another instance
    never holds the process GPU. A head that stops being ready gives it back.
    """
    register_generation_job(generation_lock, job)
    lock_key = id(generation_lock)
    token = job.get("_generation_queue_token")

    while True:
        with _generation_queue_condition:
            if is_cancel_requested(job):
                _remove_generation_waiter(lock_key, token, job)
                return False
            queue = _generation_queues.get(lock_key)
            # A worker can fail before entering this function. Cancellation
            # must let its successors advance even if that worker never polls.
            while queue and is_cancel_requested(queue[0][2]):
                _, cancelled_token, cancelled_job = queue[0]
                _remove_generation_waiter(lock_key, cancelled_token, cancelled_job)
            ready = _ready_head(queue, token, job, yield_to)
            if not ready and not getattr(machine, "active", False):
                _generation_queue_condition.wait(timeout=poll_interval)
                continue

        if not _hold_machine_turn(machine, ready, poll_interval):
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
    yield_to: Callable[[float], bool] | None = None,
) -> Iterator[bool]:
    """Context manager form of :func:`acquire_generation_slot`.

    With ``HOCUS_GPU_MACHINE_LOCK=1`` the job also holds the machine lock
    (``services.gpu_machine_lock``), taken before the process GPU.
    """
    from services.gpu_machine_lock import MachineTurn

    machine = MachineTurn(job, publish=_notify_job_state)
    try:
        acquired = acquire_generation_slot(
            generation_lock, job, poll_interval=poll_interval, yield_to=yield_to, machine=machine,
        )
    except BaseException:
        machine.release()
        raise
    try:
        yield acquired
    finally:
        machine.release()
        if acquired:
            generation_lock.release()
            with _generation_queue_condition:
                _generation_queue_condition.notify_all()
            # After the GPU is free: a job's freed buffers stay in its thread's
            # malloc arena until trimmed (services/memory_trim.py).
            from services.memory_trim import trim_process_heap

            trim_process_heap("a generation job")
