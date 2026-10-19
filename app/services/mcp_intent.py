"""Replay a stored mutation result for the same intent_id.

Read-only catalogs do not use this. A different payload for the same id conflicts.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from pathlib import Path

INTENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}")


class IntentConflict(ValueError):
    pass


def intent_digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _intent_path(root: Path, operation: str, intent_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", operation).strip("-") or "operation"
    return root / ".mcp-intents" / safe / f"{intent_id}.json"


def load_intent(root: Path, operation: str, intent_id: str, digest: str) -> dict | None:
    path = _intent_path(root, operation, intent_id)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    # A zero-byte or blank record is a write that never reached the disk (a power cut
    # after the rename). No result was stored, so the operation runs again.
    if not text.strip():
        return None
    stored = json.loads(text)
    if not isinstance(stored, dict) or stored.get("digest") != digest:
        raise IntentConflict("intent_id was already used with different parameters")
    result = stored.get("result")
    if not isinstance(result, dict):
        raise IntentConflict("Stored intention is unreadable")
    return result


def store_intent(root: Path, operation: str, intent_id: str, digest: str, result: dict) -> None:
    path = _intent_path(root, operation, intent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_durably(path, json.dumps({"digest": digest, "result": result}, ensure_ascii=False))


def write_text_durably(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` so a power cut leaves the old file or the new one, never an empty one.

    The temporary file is synced before the rename and the folder after it.
    """
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    """Best effort: Windows cannot open a folder to sync it, and some file systems refuse it."""
    if os.name == "nt":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def check_intent_id(intent_id: Any) -> str:
    if type(intent_id) is not str or not INTENT_RE.fullmatch(intent_id):
        raise IntentConflict("An exact intent_id is required")
    return intent_id
