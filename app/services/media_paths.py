"""Workspace-confined resolution for user-supplied media paths."""

from __future__ import annotations

import os
from collections.abc import Iterable


class MediaPathNotAllowed(ValueError):
    """Raised when a supplied media path escapes its permitted roots."""


_KIND_EXTENSIONS = {
    "audio": {
        ".aac", ".aif", ".aiff", ".flac", ".m4a", ".mp3", ".ogg",
        ".opus", ".wav", ".wma",
    },
    "video": {
        ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg",
        ".webm", ".wmv",
    },
}


def _is_contained(path: str, root: str) -> bool:
    path_cmp = os.path.normcase(path)
    root_cmp = os.path.normcase(root)
    try:
        return os.path.commonpath((path_cmp, root_cmp)) == root_cmp
    except (TypeError, ValueError, OSError):
        return False


def resolve_permitted_media_path(
    value: str,
    *,
    uploads_root: str,
    workspace_root: str,
    kinds: Iterable[str] = ("audio", "video"),
) -> str:
    """Resolve a media path contained in uploads or one workspace.

    Absolute paths are retained for backwards compatibility with upload API
    responses, but are accepted only after realpath/commonpath confinement.
    Relative values are tried from the process directory and both allowed
    roots. Existing symlinks are resolved before the boundary check.
    """
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise MediaPathNotAllowed("Media path is not allowed")

    roots = tuple(dict.fromkeys(
        os.path.realpath(os.path.abspath(root))
        for root in (uploads_root, workspace_root)
        if isinstance(root, str) and root
    ))
    if len(roots) != 2:
        raise MediaPathNotAllowed("Media roots are not available")

    raw = value.strip()
    if os.path.isabs(raw) or os.path.splitdrive(raw)[0]:
        raw_candidates = (raw,)
    else:
        raw_candidates = (raw, *(os.path.join(root, raw) for root in roots))

    candidates: list[str] = []
    try:
        for candidate in raw_candidates:
            resolved = os.path.realpath(os.path.abspath(candidate))
            if resolved not in candidates:
                candidates.append(resolved)
    except (OSError, ValueError):
        raise MediaPathNotAllowed("Media path is not allowed") from None

    allowed = [
        candidate
        for candidate in candidates
        if any(_is_contained(candidate, root) and candidate != root for root in roots)
    ]
    if not allowed:
        raise MediaPathNotAllowed("Media path is not allowed")

    requested_kinds = tuple(dict.fromkeys(str(kind).lower() for kind in kinds))
    allowed_extensions = set()
    for kind in requested_kinds:
        extensions = _KIND_EXTENSIONS.get(kind)
        if extensions is None:
            raise ValueError(f"Unsupported media kind: {kind}")
        allowed_extensions.update(extensions)

    matching_kind = [
        candidate
        for candidate in allowed
        if os.path.splitext(candidate)[1].lower() in allowed_extensions
    ]
    if not matching_kind:
        raise MediaPathNotAllowed("Media type is not allowed")

    for candidate in matching_kind:
        if os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError("Permitted media file was not found")

