"""Replay a stored mutation result for the same intent_id.

Read-only catalogs do not use this. A different payload for the same id conflicts.
"""

from __future__ import annotations

import hashlib
import json
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
    stored = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(stored, dict) or stored.get("digest") != digest:
        raise IntentConflict("intent_id was already used with different parameters")
    result = stored.get("result")
    if not isinstance(result, dict):
        raise IntentConflict("Stored intention is unreadable")
    return result


def store_intent(root: Path, operation: str, intent_id: str, digest: str, result: dict) -> None:
    path = _intent_path(root, operation, intent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"digest": digest, "result": result}, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def check_intent_id(intent_id: Any) -> str:
    if type(intent_id) is not str or not INTENT_RE.fullmatch(intent_id):
        raise IntentConflict("An exact intent_id is required")
    return intent_id
