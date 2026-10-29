"""One operation behind the Installation tab: status, install, uninstall, output.

The HTTP routes call this class and nothing else, so another surface (a Wizard capability,
an MCP tool) can call the same methods later. Installing is deliberately not exposed to
agents yet: it downloads gigabytes, so a person starts it from the tab.
"""
from __future__ import annotations

import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Callable

from services import install_catalog, install_launcher
from services.install_catalog import ROOT, Component
from services.install_jobs import InstallJobs, JobRefused
from services.install_remove import RemovalRefused
from services.install_status import SizeMeter, build

PROFILE_TTL_SECONDS = 15

UNKNOWN_COMPONENT = "unknown_component"
UNSUPPORTED_HERE = "unsupported"


class ManagerError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _detect(inspect_engines: set[str] | None = None) -> dict:
    from services.runtime_profiles import detect_profiles
    return detect_profiles(inspect_engines=inspect_engines)


def _engine_in_use(engine: str) -> bool:
    """Whether a running sidecar or worker holds this engine's environment open."""
    try:
        if engine == "minimax_h3":
            from services import minimax_h3_service
            return minimax_h3_service.is_runtime_running()
        if engine == "creation_models":
            from services import creation_model_service
            return bool(creation_model_service.runtime_status().get("warm"))
        if engine == "sam":
            from services import inpaint_service
            return inpaint_service.is_runtime_running()
        if engine == "hunyuan3d":
            from services import model3d_service
            return model3d_service.has_active_jobs()
        if engine == "trellis2":
            from services import model3d_service
            return model3d_service.has_active_jobs("trellis2")
        if engine == "rigging":
            from services import rig_service
            return rig_service.has_active_unirig_jobs()
        if engine == "mia":
            from services import rig_service
            return rig_service.has_active_jobs("mia")
        if engine == "see_through":
            from services import see_through_layers
            return see_through_layers.is_running()
    except ImportError:
        return False  # the core runtime ships without some of these, and runs no sidecar
    return False


class InstallManager:
    def __init__(
        self,
        root: Path = ROOT,
        *,
        detect: Callable[[set[str] | None], dict] = _detect,
        in_use: Callable[[str], bool] = _engine_in_use,
        meter: SizeMeter | None = None,
        jobs: InstallJobs | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._root, self._detect, self._clock = root, detect, clock
        self._meter = meter or SizeMeter()
        self._jobs = jobs or InstallJobs(
            root, installed=self._installed, in_use=in_use, on_change=self._changed)
        self._profiles: tuple[dict, float] | None = None
        self._lock = threading.Lock()

    # -- hardware and install state ----------------------------------------------------
    def _installed(self, engine: str) -> bool:
        return bool(self._detect({engine})["engines"][engine]["installed"])

    def _changed(self, component: Component) -> None:
        """A job ended: forget what we knew about this component."""
        with self._lock:
            self._profiles = None
        for relative in (component.env, *component.remove):
            self._meter.invalidate(self._root / relative)

    def _current_profiles(self) -> dict:
        with self._lock:
            if self._profiles and self._clock() - self._profiles[1] < PROFILE_TTL_SECONDS:
                return self._profiles[0]
        profiles = self._detect(None)
        with self._lock:
            self._profiles = (profiles, self._clock())
        return profiles

    # -- operations --------------------------------------------------------------------
    def status(self) -> dict:
        _target, reason = install_launcher.resolve(self._root)
        return build(self._current_profiles(), self._jobs, self._meter, self._root, reason)

    def install(self, component_id: str) -> dict:
        component = self._component(component_id)
        engine = self._current_profiles()["engines"][component.engine]
        if not engine["supported"]:
            raise ManagerError(UNSUPPORTED_HERE, engine.get("reason") or "Not available on this computer.")
        return self._run(self._jobs.start_install, component)

    def uninstall(self, component_id: str) -> dict:
        return self._run(self._jobs.start_uninstall, self._component(component_id))

    def output(self, component_id: str, lines: int = 60) -> list[str]:
        return self._jobs.log_tail(self._component(component_id).id, lines)

    # -- helpers -----------------------------------------------------------------------
    @staticmethod
    def _component(component_id: str) -> Component:
        try:
            return install_catalog.get(component_id)
        except KeyError:
            raise ManagerError(UNKNOWN_COMPONENT, f"No component named {component_id!r}.", 404) from None

    def _run(self, action: Callable[[Component, tuple[Component, ...]], dict], component: Component) -> dict:
        try:
            return action(component, install_catalog.components())
        except (JobRefused, RemovalRefused) as refused:
            raise ManagerError(refused.code, refused.message) from refused


@lru_cache(maxsize=1)
def default_manager() -> InstallManager:
    return InstallManager()
