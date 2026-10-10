"""The scripts ``series.episode.from_script`` was given, kept per episode.

An agent writes a whole episode from a compact script; the episode only keeps
what the script became (shots, lines, language versions). This keeps the script
itself, so a person or an agent can read and download exactly what was
submitted, and write the episode again from it ("Rewrite from this script")::

    <workspace>/.series-scripts-v1/<series id>/<episode id>.json
    {"version": 1, "seriesId": "...", "episodeId": "...", "revisions": [
        {"revision": 3, "submittedAt": "...", "by": "agent" | "wizard" | "user" | "server",
         "tool": "series.episode.from_script", "created": false, "restoredFrom": 2,
         "shots": 14, "languages": ["spanish", "english"], "digest": "<sha256>", "applied": 1,
         "lastAppliedAt": "...", "script": {...}}]}

Only scripts that were written are kept (``check: true`` writes nothing). The
newest script sent again (or rewritten from) counts on its revision
(``applied``) instead of adding one; a rewrite from an older revision adds one
with ``restoredFrom``. The newest :data:`MAX_REVISIONS` revisions are kept.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = ".series-scripts-v1"
TOOL = "series.episode.from_script"
MAX_REVISIONS = 50
MAX_SCRIPT_BYTES = 4 * 1024 * 1024
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_ACTORS = ("user", "agent", "wizard", "server")
_lock = threading.Lock()


class ScriptHistoryError(ValueError):
    def __init__(self, code: str, message: str, status: int = 404) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _segment(value: str) -> str:
    """A file name for an id: the id itself when it is a plain name, else a digest of it."""
    text = str(value or "")
    if _SAFE.fullmatch(text) and text not in {".", ".."}:
        return text
    return "id-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def history_path(root: str | os.PathLike, series_id: str, episode_id: str) -> Path:
    return Path(root) / SCRIPTS_DIR / _segment(series_id) / f"{_segment(episode_id)}.json"


def script_digest(script: Any) -> str:
    return hashlib.sha256(json.dumps(script, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, Any] | None:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) and isinstance(body.get("revisions"), list) else None


def _save(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def summary(revision: dict[str, Any]) -> dict[str, Any]:
    """A revision without its script: what a list shows."""
    return {key: value for key, value in revision.items() if key != "script"}


def record_script(root: str | os.PathLike, series_id: str, episode_id: str, script: dict[str, Any], *, by: str,
                  created: bool, shots: int, languages: list[str], restored_from: int | None = None,
                  now: str | None = None) -> dict[str, Any]:
    """Keep a script that was written into an episode; returns the revision's summary."""
    encoded = json.dumps(script, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_SCRIPT_BYTES:
        raise ScriptHistoryError("script_too_large", "The script is too large to keep", status=413)
    path, moment, digest = history_path(root, series_id, episode_id), now or _now(), script_digest(script)
    with _lock:
        body = _load(path) or {"version": 1, "seriesId": series_id, "episodeId": episode_id, "revisions": []}
        revisions = body["revisions"]
        latest = revisions[-1] if revisions else None
        if latest and latest.get("digest") == digest:
            latest.update(applied=int(latest.get("applied") or 1) + 1, lastAppliedAt=moment,
                          lastBy=by if by in _ACTORS else "user")
        else:
            number = int(latest.get("revision") or 0) + 1 if latest else 1
            entry: dict[str, Any] = {
                "revision": number, "submittedAt": moment, "by": by if by in _ACTORS else "user", "tool": TOOL,
                "created": bool(created), "shots": int(shots), "languages": list(languages), "digest": digest,
                "applied": 1, "lastAppliedAt": moment, "script": script,
            }
            if restored_from is not None:
                entry["restoredFrom"] = int(restored_from)
            revisions.append(entry)
            del revisions[:-MAX_REVISIONS]
        _save(path, body)
        return summary(revisions[-1])


def list_scripts(root: str | os.PathLike, series_id: str, episode_id: str) -> list[dict[str, Any]]:
    """Every kept revision, newest first, without the scripts."""
    body = _load(history_path(root, series_id, episode_id)) or {"revisions": []}
    return [summary(item) for item in reversed(body["revisions"]) if isinstance(item, dict)]


def read_script(root: str | os.PathLike, series_id: str, episode_id: str, revision: int | None = None) -> dict[str, Any]:
    """One revision with its script (the newest when ``revision`` is None)."""
    body = _load(history_path(root, series_id, episode_id))
    revisions = [item for item in (body or {}).get("revisions") or [] if isinstance(item, dict)]
    if not revisions:
        raise ScriptHistoryError("no_script", "No script was written into this episode")
    if revision is None:
        return dict(revisions[-1])
    found = next((item for item in revisions if item.get("revision") == revision), None)
    if found is None:
        raise ScriptHistoryError("not_found", f"The episode has no script revision {revision}")
    return dict(found)


def download_name(series_id: str, episode_id: str, revision: int) -> str:
    return f"{_segment(series_id)}-{_segment(episode_id)}-script-r{int(revision)}.json"


__all__ = ["MAX_REVISIONS", "SCRIPTS_DIR", "ScriptHistoryError", "download_name", "history_path", "list_scripts",
           "read_script", "record_script", "script_digest", "summary"]
