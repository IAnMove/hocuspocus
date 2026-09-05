"""Normalize gallery/editor media references that include workspace query strings."""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse


def parse_media_ref(value: str, workspace: str | None = None) -> tuple[str, str | None]:
    """Split a UI media URL into a filesystem path/filename and workspace.

    Gallery URLs look like ``/api/v1/file/clip.mp4?workspace=default``. Treating
    the query as part of the filename makes the file lookup fail.
    """
    chosen = str(workspace).strip() if workspace else None
    raw = unquote(str(value or "").strip())
    if not raw:
        return "", chosen

    if "://" in raw or raw.startswith("/") or "?" in raw or "#" in raw:
        parsed = urlparse(raw)
        path = (parsed.path or raw.split("?", 1)[0].split("#", 1)[0]).strip()
        query = parsed.query
    else:
        path, _, query = raw.partition("?")
        path = path.split("#", 1)[0].strip()

    if query and not chosen:
        names = parse_qs(query, keep_blank_values=False).get("workspace") or []
        if names and str(names[0]).strip():
            chosen = str(names[0]).strip()
    return path, chosen
