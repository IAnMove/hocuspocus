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
from typing import Iterator
from urllib.parse import urlparse


REMOTE_PROVIDERS = frozenset({
    "anthropic", "deepseek", "minimax", "openai", "openai-compatible", "remote",
})


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
        self._slots: dict[str, threading.BoundedSemaphore] = {}
        self._state: dict[str, dict] = {}

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
                }
            return slot

    @contextmanager
    def acquire(
        self,
        lane: ResourceLane,
        *,
        task_id: str,
        description: str = "",
    ) -> Iterator[ResourceLane]:
        slot = self._slot(lane)
        with self._guard:
            state = self._state[lane.key]
            state["waiting"] += 1
        slot.acquire()
        started_at = time.time()
        with self._guard:
            state = self._state[lane.key]
            state["waiting"] -= 1
            state["active"] += 1
            state["tasks"].append({
                "id": task_id,
                "description": description,
                "started_at": started_at,
            })
        try:
            yield lane
        finally:
            with self._guard:
                state = self._state[lane.key]
                state["active"] = max(0, state["active"] - 1)
                state["tasks"] = [task for task in state["tasks"] if task["id"] != task_id]
            slot.release()

    def snapshot(self) -> list[dict]:
        with self._guard:
            return [
                {**state, "tasks": [dict(task) for task in state["tasks"]]}
                for state in self._state.values()
            ]


coordinator = ResourceCoordinator()
