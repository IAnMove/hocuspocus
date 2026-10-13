"""Resolve a UI upload or output path to a local file.

Launch, the core server, rig, model3d and the video editor share this check.
The caller injects path containment, the workspace folder and the outputs root.
"""
from __future__ import annotations

import os
from collections.abc import Callable


def resolve_model3d_input_path(
    value: str,
    workspace: str | None = None,
    *,
    safe_join: Callable[..., str | None],
    workspace_dir: Callable[..., str],
    save_path: Callable[[], str],
) -> str | None:
    """Resolve a UI-provided upload/output path to a local file."""
    if not value:
        return None
    from services.media_refs import parse_media_ref

    value, workspace = parse_media_ref(value, workspace)
    if not value:
        return None
    if value.startswith("/api/v1/uploads/"):
        value = value.rsplit("/", 1)[-1]
        return safe_join(os.path.join(os.getcwd(), "uploads"), value)
    if value.startswith("/api/v1/file/"):
        value = value.rsplit("/", 1)[-1]
        return safe_join(workspace_dir(workspace), value)
    if os.path.isabs(value):
        uploads_root = os.path.realpath(os.path.join(os.getcwd(), "uploads"))
        outputs_root = os.path.realpath(save_path())
        real = os.path.realpath(value)
        if real.startswith(uploads_root + os.sep) or real.startswith(outputs_root + os.sep):
            return real
        return None
    upload_candidate = safe_join(os.path.join(os.getcwd(), "uploads"), value)
    if upload_candidate and os.path.isfile(upload_candidate):
        return upload_candidate
    return safe_join(workspace_dir(workspace), value)
