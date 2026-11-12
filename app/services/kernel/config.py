"""The live server configuration and its atomic save."""
from __future__ import annotations

import json
import os
import uuid
from typing import Any, Callable

from services.generation import get_wgp


def write_private_json(path: str, payload: str) -> None:
    """Replace ``path`` with ``payload`` atomically and leave it mode 0600.

    A unique temporary file is created with owner-only permissions, fsynced,
    then renamed over the destination. The temporary name is removed if the
    rename does not consume it, including when the rename fails.
    """
    folder = os.path.dirname(os.path.abspath(path)) or "."
    temporary = os.path.join(folder, f".{os.path.basename(path)}.{uuid.uuid4().hex}.tmp")
    try:
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.remove(temporary)
        except OSError:
            pass


class ConfigStore:
    """``wgp.server_config`` and the one place that writes it back to disk.

    The engine is reached through ``wgp_provider`` (``services.generation.get_wgp``
    by default), so a test can give it any object that has ``server_config`` and
    ``server_config_filename``. Nothing is read or written until a method is called.
    """

    def __init__(self, wgp_provider: Callable[[], Any] = get_wgp) -> None:
        self._wgp_provider = wgp_provider

    @property
    def wgp(self) -> Any:
        """The engine module the configuration belongs to."""
        return self._wgp_provider()

    @property
    def server_config(self) -> dict:
        """The live configuration mapping (the same dict object WanGP reads)."""
        return self._wgp_provider().server_config

    def save(self) -> None:
        """Write wgp.server_config atomically with owner-only permissions.

        The file holds API keys and the workspace list. open("w") truncated it
        before writing, so a crash or two concurrent saves could leave it empty,
        and the next start failed to import wgp.
        """
        wgp = self._wgp_provider()
        write_private_json(wgp.server_config_filename, json.dumps(wgp.server_config, indent=4))
