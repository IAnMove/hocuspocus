"""Conservative resource lanes for generation workflow scheduling.

Tasks may overlap only when they use distinct execution resources.  A local
GPU is always a single-capacity lane, regardless of whether a task generates
an image or a video.  Remote work is grouped by server origin, so two APIs on
the same host remain sequential by default while a remote API can overlap a
local GPU task.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import threading
import time
from typing import Callable, Iterator
from urllib.parse import urlparse


REMOTE_PROVIDERS = frozenset({
    "anthropic", "deepseek", "minimax", "openai", "openai-compatible", "remote",
})

# Machine-readable owner tags for the local GPU hand-off hook. The human label
# is deliberately separate: matching strings such as ``"Maestro WGP ..."``
# made runtime ownership depend on product branding and silently broke when
# the UI was renamed to HocusPocus.
GPU_ENGINE_H3_LEGACY = "h3-legacy"
GPU_ENGINE_LOCAL_LLM = "local-llm"
GPU_ENGINE_WGP = "wgp"
_GPU_ENGINE_TAG = "[gpu-engine:"


def gpu_engine_description(engine: str, label: str) -> str:
    """Attach a stable engine identity to an observable task description."""
    normalized = str(engine or "").strip().lower()
    if normalized not in {
        GPU_ENGINE_H3_LEGACY,
        GPU_ENGINE_LOCAL_LLM,
        GPU_ENGINE_WGP,
    }:
        raise ValueError(f"Unknown GPU engine: {engine}")
    return f"{_GPU_ENGINE_TAG}{normalized}] {str(label or '').strip()}".strip()


def gpu_engine_kind(description: str) -> str:
    """Return the stable engine kind encoded in a scheduler description.

    Narrow legacy aliases keep callers from older builds safe during a rolling
    restart. New callers use :func:`gpu_engine_description` and therefore stay
    independent of visible product copy.
    """
    owner = str(description or "").strip().lower()
    if owner.startswith(_GPU_ENGINE_TAG):
        closing = owner.find("]", len(_GPU_ENGINE_TAG))
        if closing > 0:
            return owner[len(_GPU_ENGINE_TAG):closing]
    if owner.startswith(("maestro h3 legacy", "hocuspocus lab h3 legacy")):
        return GPU_ENGINE_H3_LEGACY
    if owner.startswith(("maestro wgp", "hocuspocus lab wgp")):
        return GPU_ENGINE_WGP
    if owner.startswith("local llm"):
        return GPU_ENGINE_LOCAL_LLM
    return ""


def _server_origin(url: str, fallback: str) -> str:
    raw = str(url or "").strip()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.hostname:
        scheme = parsed.scheme or "https"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{scheme}://{parsed.hostname.lower()}{port}"
    return fallback


@dataclass(frozen=True)
class ResourceLane:
    key: str
    label: str
    location: str
    capacity: int = 1


class ResourceAcquireCancelled(RuntimeError):
    """Raised when a task is cancelled before its resource lease begins."""


def local_gpu_lane(gpu_index: int = 0) -> ResourceLane:
    index = max(0, int(gpu_index or 0))
    return ResourceLane(f"local_gpu:{index}", f"Local GPU {index}", "local")


def cpu_lane(name: str = "llm") -> ResourceLane:
    safe_name = str(name or "task").strip().lower().replace(" ", "_")
    return ResourceLane(f"local_cpu:{safe_name}", f"Local CPU · {safe_name}", "local")


def remote_lane(provider: str, base_url: str = "") -> ResourceLane:
    normalized_provider = str(provider or "remote").strip().lower()
    defaults = {
        "anthropic": "https://api.anthropic.com",
        "deepseek": "https://api.deepseek.com",
        "minimax": "https://api.minimax.io",
        "openai": "https://api.openai.com",
    }
    origin = _server_origin(base_url, defaults.get(normalized_provider, f"provider:{normalized_provider}"))
    return ResourceLane(f"remote:{origin}", f"Remote · {origin}", "remote")


def llm_lane(
    provider: str,
    *,
    base_url: str = "",
    device: str = "cpu",
    gpu_index: int = 0,
) -> ResourceLane:
    normalized = str(provider or "local").strip().lower()
    if normalized in REMOTE_PROVIDERS:
        return remote_lane(normalized, base_url)
    if str(device or "cpu").strip().lower().startswith(("cuda", "gpu")):
        return local_gpu_lane(gpu_index)
    return cpu_lane("llm")


def image_lane(model: str, *, base_url: str = "", gpu_index: int = 0) -> ResourceLane:
    normalized = str(model or "").strip().lower()
    if normalized == "minimax:image-01" or normalized.startswith("minimax:"):
        return remote_lane("minimax", base_url)
    return local_gpu_lane(gpu_index)


def video_lane(model: str, *, base_url: str = "", gpu_index: int = 0) -> ResourceLane:
    # Current Maestro video models, including MiniMax H3, execute locally.
    # A future remote integration must provide its server URL explicitly.
    if base_url:
        return remote_lane(str(model or "video"), base_url)
    return local_gpu_lane(gpu_index)


def may_overlap(first: ResourceLane, second: ResourceLane) -> bool:
    """Return whether two tasks use genuinely independent resources."""
    return first.key != second.key


class ResourceCoordinator:
    """Own per-resource semaphores and expose observable queue state."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._thread_state = threading.local()
        self._slots: dict[str, threading.BoundedSemaphore] = {}
        self._state: dict[str, dict] = {}
        self._next_ticket = 0
        self._prepare_hooks: dict[
            str, Callable[[ResourceLane, str, str], None]
        ] = {}

    def _slot(self, lane: ResourceLane) -> threading.BoundedSemaphore:
        with self._guard:
            slot = self._slots.get(lane.key)
            if slot is None:
                slot = threading.BoundedSemaphore(max(1, lane.capacity))
                self._slots[lane.key] = slot
                self._state[lane.key] = {
                    "key": lane.key,
                    "label": lane.label,
                    "location": lane.location,
                    "active": 0,
                    "waiting": 0,
                    "tasks": [],
                    "waiters": [],
                    # The condition shares the coordinator guard so ticket
                    # inspection, removal, and slot hand-off are atomic.
                    "condition": threading.Condition(self._guard),
                }
            return slot

    def _remove_waiter_locked(self, lane: ResourceLane, waiter: dict) -> bool:
        """Remove one queued ticket and wake the next ticket in its lane."""
        state = self._state[lane.key]
        for index, queued in enumerate(state["waiters"]):
            if queued is waiter:
                state["waiters"].pop(index)
                state["waiting"] = max(0, state["waiting"] - 1)
                state["condition"].notify_all()
                return True
        return False

    def shared_lock(self, lane: ResourceLane) -> threading.BoundedSemaphore:
        """Return the coordinator-owned primitive for legacy FIFO adapters.

        The main Maestro generation queue already has tested FIFO and abort
        semantics around a lock. Giving it this exact semaphore lets migrated
        engines acquire through :meth:`acquire` without introducing a second
        GPU lock or allowing two owners of the same physical device.
        """
        return self._slot(lane)

    def set_prepare_hook(
        self,
        lane: ResourceLane,
        hook: Callable[[ResourceLane, str, str], None] | None,
    ) -> None:
        """Install a post-acquisition runtime handoff hook for one lane."""
        self._slot(lane)
        with self._guard:
            if hook is None:
                self._prepare_hooks.pop(lane.key, None)
            else:
                self._prepare_hooks[lane.key] = hook

    @contextmanager
    def adopt_acquired(
        self,
        lane: ResourceLane,
        *,
        task_id: str,
        description: str = "",
    ) -> Iterator[ResourceLane]:
        """Observe a lease whose coordinator semaphore is already held.

        Maestro's original video queue owns FIFO/cancellation semantics around
        the same physical semaphore returned by :meth:`shared_lock`.  Once
        that queue has acquired it, this adapter performs the normal runtime
        hand-off and makes the owner visible in :meth:`snapshot` without
        attempting to acquire the semaphore a second time.

        Callers must hold ``shared_lock(lane)`` for the whole context.
        """
        self._slot(lane)
        held = getattr(self._thread_state, "held", None)
        if held is None:
            held = {}
            self._thread_state.held = held
        if held.get(lane.key, 0) > 0:
            held[lane.key] += 1
            try:
                yield lane
            finally:
                held[lane.key] -= 1
                if held[lane.key] <= 0:
                    held.pop(lane.key, None)
            return

        held[lane.key] = 1
        active = False
        try:
            with self._guard:
                prepare_hook = self._prepare_hooks.get(lane.key)
            if prepare_hook is not None:
                prepare_hook(lane, task_id, description)

            started_at = time.time()
            with self._guard:
                state = self._state[lane.key]
                state["active"] += 1
                state["tasks"].append({
                    "id": task_id,
                    "description": description,
                    "started_at": started_at,
                })
                active = True
            yield lane
        finally:
            held[lane.key] = max(0, held.get(lane.key, 1) - 1)
            if held[lane.key] <= 0:
                held.pop(lane.key, None)
            if active:
                with self._guard:
                    state = self._state[lane.key]
                    state["active"] = max(0, state["active"] - 1)
                    state["tasks"] = [
                        task for task in state["tasks"]
                        if task["id"] != task_id
                    ]

    @contextmanager
    def acquire(
        self,
        lane: ResourceLane,
        *,
        task_id: str,
        description: str = "",
        cancelled: Callable[[], bool] | None = None,
        poll_interval: float = 0.1,
    ) -> Iterator[ResourceLane]:
        held = getattr(self._thread_state, "held", None)
        if held is None:
            held = {}
            self._thread_state.held = held
        if held.get(lane.key, 0) > 0:
            # A parent operation may deliberately retain a CUDA lease across
            # several observable child calls. Re-entering that same physical
            # lane on the same thread must not deadlock on its semaphore.
            if cancelled is not None and cancelled():
                raise ResourceAcquireCancelled(
                    f"Task {task_id} was cancelled before re-entering {lane.key}"
                )
            held[lane.key] += 1
            try:
                yield lane
            finally:
                held[lane.key] -= 1
                if held[lane.key] <= 0:
                    held.pop(lane.key, None)
            return

        slot = self._slot(lane)
        queued_at = time.time()
        waiter = {
            "id": task_id,
            "description": description,
            "queued_at": queued_at,
        }
        with self._guard:
            state = self._state[lane.key]
            self._next_ticket += 1
            waiter["ticket"] = self._next_ticket
            state["waiting"] += 1
            state["waiters"].append(waiter)
            condition = state["condition"]
        acquired = False
        active = False
        active_task = None
        waiting = True
        held_registered = False
        try:
            interval = max(0.01, float(poll_interval or 0.1))
            while True:
                if cancelled is not None and cancelled():
                    with self._guard:
                        self._remove_waiter_locked(lane, waiter)
                    raise ResourceAcquireCancelled(
                        f"Task {task_id} was cancelled while waiting for {lane.key}"
                    )
                with self._guard:
                    state = self._state[lane.key]
                    # A ticket may acquire only when it reaches the front of
                    # its lane. This makes arrival order authoritative rather
                    # than merely observable in the status snapshot.
                    if state["waiters"] and state["waiters"][0] is waiter:
                        if slot.acquire(blocking=False):
                            acquired = True
                            state["waiters"].pop(0)
                            state["waiting"] = max(0, state["waiting"] - 1)
                            waiting = False
                            held[lane.key] = held.get(lane.key, 0) + 1
                            held_registered = True
                            state["active"] += 1
                            active_task = {
                                "id": task_id,
                                "description": description,
                                "started_at": time.time(),
                            }
                            state["tasks"].append(active_task)
                            active = True
                            condition.notify_all()
                            break
                    # A bounded wait keeps compatibility with legacy callers
                    # that acquire shared_lock() directly: their semaphore
                    # release cannot itself notify this condition.
                    condition.wait(timeout=interval)
            # Close the small race between the final cancellation check and
            # semaphore acquisition. A cancelled waiter must never start a
            # provider call merely because the previous owner just released.
            if cancelled is not None and cancelled():
                raise ResourceAcquireCancelled(
                    f"Task {task_id} was cancelled while acquiring {lane.key}"
                )
            # Ownership was registered before leaving the ticket hand-off.
            # A cleanup hook may itself call a migrated service on this lane;
            # treating that call as reentrant avoids deadlocking on the
            # semaphore that this hook already owns.
            with self._guard:
                prepare_hook = self._prepare_hooks.get(lane.key)
            if prepare_hook is not None:
                prepare_hook(lane, task_id, description)
            if cancelled is not None and cancelled():
                raise ResourceAcquireCancelled(
                    f"Task {task_id} was cancelled while preparing {lane.key}"
                )
            yield lane
        finally:
            if held_registered:
                held[lane.key] = max(0, held.get(lane.key, 1) - 1)
                if held[lane.key] <= 0:
                    held.pop(lane.key, None)
            with self._guard:
                state = self._state[lane.key]
                if waiting:
                    self._remove_waiter_locked(lane, waiter)
                if active:
                    state["active"] = max(0, state["active"] - 1)
                    state["tasks"] = [
                        task for task in state["tasks"] if task is not active_task
                    ]
                condition.notify_all()
            if acquired:
                slot.release()
                with self._guard:
                    condition.notify_all()

    def snapshot(self) -> list[dict]:
        with self._guard:
            return [
                {
                    **{
                        key: value
                        for key, value in state.items()
                        if key != "condition"
                    },
                    "tasks": [dict(task) for task in state["tasks"]],
                    "waiters": [dict(task) for task in state["waiters"]],
                }
                for state in self._state.values()
            ]


coordinator = ResourceCoordinator()
