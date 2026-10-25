"""The list of optional installable components, read from one JSON file.

``app/runtime/install_catalog.json`` feeds the Pinokio install dialog, the Advanced
menu and ``runtime_setup.js`` (through ``install_components.js``), and here the server's
Installation status and the web UI. Add a component to that file; nothing else lists them.

Only the standard library is imported: ``scripts/runtime_probe.py`` loads this module with
Pinokio's base Python, before any environment exists.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePosixPath

from services.model_licences import for_id as licence_for_id
from services.runtime_profiles import APP_DIR, catalog as profile_catalog

ROOT = APP_DIR.parent
CATALOG_PATH = APP_DIR / "runtime" / "install_catalog.json"
GIB = 1024 ** 3
# Uninstall may only delete below here: never the launcher, the main env or tracked code.
REMOVABLE_ROOT = PurePosixPath("app/services")


@dataclass(frozen=True)
class Component:
    id: str
    engine: str
    script: str
    title: str
    summary: str
    estimated_bytes: int
    restart_required: bool
    remove: tuple[str, ...]
    licence: str | None = None
    license: str = ""
    ready_file: str = ""

    def __post_init__(self) -> None:
        for relative in self.remove:
            path = PurePosixPath(relative)
            if path.is_absolute() or ".." in path.parts or REMOVABLE_ROOT not in path.parents:
                raise ValueError(f"{self.id}: removable path {relative!r} must stay inside {REMOVABLE_ROOT}")

    @property
    def env(self) -> str:
        """Environment folder from profiles.json, relative to the repository root."""
        return profile_catalog()["engines"][self.engine]["env"]

    def as_dict(self) -> dict:
        payload = {
            "id": self.id, "engine": self.engine, "title": self.title, "summary": self.summary,
            "estimatedBytes": self.estimated_bytes, "restartRequired": self.restart_required,
        }
        record = licence_for_id(self.licence)
        if record:
            payload["licence"] = record
        if self.license:
            payload["license"] = self.license
        return payload


@lru_cache(maxsize=1)
def _load() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def base() -> dict:
    """The always-installed part: title, summary and estimated size."""
    entry = _load()["base"]
    return {"title": entry["title"], "summary": entry["summary"],
            "estimatedBytes": int(entry["estimatedGiB"] * GIB)}


def components() -> tuple[Component, ...]:
    return tuple(
        Component(
            id=entry["id"], engine=entry["engine"], script=entry["script"], title=entry["title"],
            summary=entry["summary"], estimated_bytes=int(entry["estimatedGiB"] * GIB),
            restart_required=bool(entry.get("restartRequired")), remove=tuple(entry["remove"]),
            licence=entry.get("licence") if isinstance(entry.get("licence"), str) else None,
            license=str(entry.get("license") or ""), ready_file=str(entry.get("readyFile") or ""),
        )
        for entry in _load()["components"]
    )


def get(component_id: str) -> Component:
    for component in components():
        if component.id == component_id:
            return component
    raise KeyError(component_id)


def optional_engines() -> frozenset[str]:
    """Engines installed on request. ``defaultInstall`` in profiles.json cannot say this
    for MiniMax H3 Legacy: that flag feeds the install fingerprint, so changing it would
    mark every existing install stale and reinstall 6 GB."""
    return frozenset(component.engine for component in components())
