"""The active workspace and the output folder each workspace name stands for."""
from __future__ import annotations

import os
import re

from fastapi import HTTPException

from services.kernel.config import ConfigStore


class WorkspaceService:
    """Which workspace is active, where a workspace lives and which exist.

    The base output folder is always read from ``server_config["save_path"]``,
    never from ``wgp.save_path`` (which may already include the workspace).
    """

    def __init__(self, config: ConfigStore) -> None:
        self._config = config

    def active(self) -> str:
        """Get current workspace name from server config."""
        wgp = self._config.wgp
        return wgp.server_config.get("services", {}).get("active_workspace", "default")

    def workspace_dir(self, workspace: str = None) -> str:
        """Return a contained output directory for one validated workspace."""
        wgp = self._config.wgp
        ws = self.active() if workspace is None else workspace
        if not isinstance(ws, str) or not re.fullmatch(
            r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)", ws
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid workspace name. Use letters, numbers, hyphens, "
                    "underscores, without spaces or path separators."
                ),
            )

        # Always read base from config, never from wgp.save_path (which may already include workspace)
        base = os.path.realpath(os.path.abspath(
            wgp.server_config.get("save_path", "outputs")
        ))
        ws_dir = base if ws == "default" else os.path.realpath(os.path.join(base, ws))
        try:
            contained = os.path.commonpath((base, ws_dir)) == base
        except (TypeError, ValueError):
            contained = False
        if not contained:
            raise HTTPException(status_code=400, detail="Invalid workspace path.")
        if ws != "default":
            os.makedirs(ws_dir, exist_ok=True)
        return ws_dir

    @staticmethod
    def file_count(path: str) -> int:
        """Non-hidden files directly inside a workspace folder (for delete
        confirms). scandir answers is_file() from the enumeration data on
        Windows — no per-entry stat syscall."""
        try:
            with os.scandir(path) as entries:
                return sum(1 for e in entries if not e.name.startswith(".") and e.is_file())
        except OSError:
            return 0

    def list(self) -> list[dict]:
        """List all workspaces (subdirectories of the base output path + default)."""
        wgp = self._config.wgp
        base = wgp.server_config.get("save_path", "outputs")
        workspaces = [{"name": "default", "path": base, "file_count": self.file_count(base)}]
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                full = os.path.join(base, name)
                if os.path.isdir(full) and not name.startswith(("_", ".")):
                    workspaces.append({"name": name, "path": full, "file_count": self.file_count(full)})
        return workspaces

    def persist_active(self, name: str, apply_save_paths: bool = True) -> str:
        """Write services.active_workspace to config and (optionally) point
        wgp's save paths at it. Pass apply_save_paths=False while a generation
        is running — the in-flight job has locked wgp.save_path to its target
        and the new value takes effect on the next job / restart."""
        wgp = self._config.wgp
        services = wgp.server_config.setdefault("services", {})
        services["active_workspace"] = name
        wgp.server_config["services"] = services
        self._config.save()
        ws_dir = self.workspace_dir(name)
        if apply_save_paths:
            wgp.save_path = ws_dir
            wgp.image_save_path = ws_dir
        return ws_dir
