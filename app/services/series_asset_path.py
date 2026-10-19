"""Resolve a Series asset URI to one file inside a workspace.

Missing files fail closed or are skipped. Both servers fail closed today.
The concatenation policy (skip a missing clip, or refuse the join) stays with
each caller.
"""
from __future__ import annotations

import os
from typing import Any, Callable


def series_asset_local_path(
    workspace: str,
    asset: dict[str, Any],
    *,
    workspace_dir: Callable[[str], str],
    remote_purpose: str,
    on_missing: str = "raise",
) -> str:
    uri = str(asset.get("uri") or "")
    if uri.startswith("https://"):
        raise ValueError(
            f"Remote Series asset {asset.get('id')} must be imported into the workspace before {remote_purpose}"
        )
    folder = os.path.realpath(workspace_dir(workspace))
    relative = uri[len("outputs/"):] if uri.startswith("outputs/") else uri
    candidate = os.path.realpath(os.path.join(folder, relative))
    if candidate != folder and not candidate.startswith(folder + os.sep):
        raise ValueError(f"Series asset {asset.get('id')} leaves its workspace")
    if os.path.isfile(candidate):
        return candidate
    if on_missing == "skip":
        return ""
    if on_missing != "raise":
        raise ValueError(f"Unknown missing-asset policy: {on_missing}")
    raise ValueError(f"Series reference file is missing: {uri}")
