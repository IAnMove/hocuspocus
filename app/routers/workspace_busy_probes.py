"""Which running work each server lets stop a workspace delete.

``services/workspace_busy.py`` is the registry; this is the list of what goes into it.
It sits in the router layer because two job owners are routers (``routers/video_editor.py``)
and because a router may import both layers while a service may not import a router.

Each family module exposes one function, ``busy_jobs(workspace, workspace_dir)``, that
returns its live jobs (see the rules in ``services/workspace_busy.py``). A profile is the
list of families one server runs, so a server only imports and checks what it mounts:
core never loads ``model3d_service`` or the Series render queue just to be asked about them.

Families whose state lives in an object the server builds (the game and Series produce,
native render and voice services, and the Series assembly router) cannot be named here.
The router factory that receives the object registers its probe itself, which is why
those kinds are in :data:`REGISTERED_BY_THE_ROUTER` and not in a profile.
"""
from __future__ import annotations

import importlib

from services import workspace_busy

PROBE_FUNCTION = "busy_jobs"

# Run by both servers.
COMMON: tuple[tuple[str, str], ...] = (
    ("video-editor", "routers.video_editor"),
    ("minimax-music", "services.story_music_jobs"),
    ("minimax-image", "routers.comics"),
)
# The full server (NVIDIA / WanGP) only.
FULL_ONLY: tuple[tuple[str, str], ...] = ()
# The core server (Apple Silicon / remote providers) only.
CORE_ONLY: tuple[tuple[str, str], ...] = ()

PROFILES: dict[str, tuple[tuple[str, str], ...]] = {
    "full": COMMON + FULL_ONLY,
    "core": COMMON + CORE_ONLY,
}

# kind -> the router module whose factory registers it with the object it was given.
REGISTERED_BY_THE_ROUTER: dict[str, str] = {}


def register_profile(name: str) -> None:
    """Register the probes of one server profile (``"full"`` or ``"core"``). Safe to call again."""
    try:
        families = PROFILES[name]
    except KeyError:
        raise ValueError(f"Unknown workspace busy profile: {name!r}") from None
    for kind, module in families:
        workspace_busy.register(kind, getattr(importlib.import_module(module), PROBE_FUNCTION))
