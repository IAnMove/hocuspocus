"""Publish the port the server actually bound, for local agents and scripts.

Pinokio proposes a port, but the server moves to the next free one when it is
taken and only says so in the log. Agents then guessed the port from the log.
``settings/server-endpoint.json`` holds the effective address while this
process runs, next to ``mcp-access.json``. A client should check ``pid``: a
file left by a killed process names a port nobody serves.
"""

from __future__ import annotations

import atexit
import json
import os
import secrets
import time
from pathlib import Path


def endpoint_record(*, host: str, display_host: str, port: int) -> dict:
    url = f"http://{display_host}:{port}"
    return {
        "url": url, "mcp_url": f"{url}/api/v1/mcp", "host": host, "port": port,
        "pid": os.getpid(), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def publish_server_endpoint(path: str | os.PathLike, *, host: str, display_host: str, port: int) -> dict:
    """Write the record atomically and remove it when this process exits."""
    target = Path(path)
    record = endpoint_record(host=host, display_host=display_host, port=port)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(6)}.tmp")
    try:
        temporary.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    atexit.register(withdraw_server_endpoint, target, record["pid"])
    return record


def withdraw_server_endpoint(path: str | os.PathLike, pid: int) -> None:
    """Remove the record only if it still names ``pid``; a newer server may own it."""
    target = Path(path)
    try:
        if json.loads(target.read_text(encoding="utf-8")).get("pid") == pid:
            target.unlink()
    except (OSError, ValueError):
        pass
