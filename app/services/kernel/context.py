"""The runtime context: the kernel services of one server, built once."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from services import resource_scheduler
from services.generation import get_wgp
from services.kernel.config import ConfigStore
from services.kernel.jobs import GenerationQueue
from services.kernel.paths import PathPolicy
from services.kernel.tasks import CanonicalTasks
from services.kernel.workspaces import WorkspaceService


@dataclass(frozen=True)
class RuntimeContext:
    """The shared services a feature slice may use, and nothing else.

    The dataclass is frozen, but the services it holds are the live ones: the
    dictionaries and locks behind ``jobs`` are the same objects every holder of
    the context sees. Engine and LLM ports join the fields when their slices land.
    """

    profile: Literal["full", "core"]
    config: ConfigStore
    workspaces: WorkspaceService
    paths: PathPolicy
    jobs: GenerationQueue
    scheduler: resource_scheduler.ResourceCoordinator
    tasks: CanonicalTasks


def build_context(
    *,
    profile: Literal["full", "core"],
    is_legacy_h3_model: Callable[[str | None], bool],
    is_minimax_h3_model: Callable[[str | None], bool],
    cancel_legacy_h3: Callable[[], Any],
    task_publisher: Callable[[], Callable[[dict], Any] | None],
    wgp_provider: Callable[[], Any] = get_wgp,
) -> RuntimeContext:
    """Build the services of one server, wired to each other.

    ``wgp_provider`` is the engine the configuration and the workspaces read
    (the bound WanGP by default). The three callables and the lookup are what
    the generation queue needs from the engine and the task cluster; they are
    called when a job is built or cancelled, so they may name functions defined
    after the context is built. Building starts no thread and writes no file.
    """
    config = ConfigStore(wgp_provider)
    workspaces = WorkspaceService(config)
    return RuntimeContext(
        profile=profile,
        config=config,
        workspaces=workspaces,
        paths=PathPolicy(workspaces),
        jobs=GenerationQueue(
            config,
            workspaces,
            is_legacy_h3_model=is_legacy_h3_model,
            is_minimax_h3_model=is_minimax_h3_model,
            cancel_legacy_h3=cancel_legacy_h3,
            task_publisher=task_publisher,
        ),
        scheduler=resource_scheduler.coordinator,
        tasks=CanonicalTasks(workspaces),
    )
