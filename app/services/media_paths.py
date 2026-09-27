"""Workspace-confined resolution for user-supplied media paths."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from urllib.parse import parse_qsl, unquote, urlsplit


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


def _canonical_media_path(value: str, uploads_root: str, workspace_root: str, workspace_name: str | None):
    """Resolve the declared API root, without same-name fallback across roots."""
    if any(ord(char) <= 32 or char in "\\#" for char in value) or re.search(r"%(?![0-9a-fA-F]{2})", value):
        raise MediaPathNotAllowed("Invalid canonical media reference")
    parsed = urlsplit(value)
    upload_prefix, file_prefix = "/api/v1/uploads/", "/api/v1/file/"
    if parsed.path.startswith(upload_prefix):
        if parsed.query:
            raise MediaPathNotAllowed("Upload references cannot contain query parameters")
        root, relative = uploads_root, parsed.path[len(upload_prefix):]
    elif parsed.path.startswith(file_prefix):
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if len(query) != 1 or query[0] != ("workspace", workspace_name):
            raise MediaPathNotAllowed("The reference workspace does not match its declared root")
        root, relative = workspace_root, parsed.path[len(file_prefix):]
    else:
        raise MediaPathNotAllowed("Unsupported canonical media root")
    try:
        relative = unquote(relative, errors="strict")
    except UnicodeDecodeError as error:
        raise MediaPathNotAllowed("Invalid canonical media reference") from error
    if (any(ord(char) < 32 or ord(char) == 127 or char == "\\" for char in relative)
            or any(part in {"", ".", ".."} for part in relative.split("/"))):
        raise MediaPathNotAllowed("Media path is not allowed")
    return os.path.join(root, relative), root


def resolve_permitted_media_path(
    value: str,
    *,
    uploads_root: str,
    workspace_root: str,
    kinds: Iterable[str] = ("audio", "video"),
    workspace_name: str | None = None,
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
    if raw.startswith("/api/"):
        canonical, declared_root = _canonical_media_path(raw, roots[0], roots[1], workspace_name)
        # A canonical file may not follow a symlink into the other allowed root.
        roots = (declared_root,)
        raw_candidates = (canonical,)
    elif os.path.isabs(raw) or os.path.splitdrive(raw)[0]:
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


def resolve_voice_ref_paths(
    refs: Iterable[str],
    *,
    uploads_root: str,
    workspace_root: str,
) -> list[str]:
    """Resolve SeedVC voice refs to real files under uploads or the workspace.

    Upload-audio stores files in uploads/audio/; the UI must send that
    subfolder (or an absolute path). Bare filenames only match a workspace
    file or a file sitting directly in uploads/. Unresolvable entries are
    dropped so a stale ref cannot crash generation.
    """
    resolved: list[str] = []
    for value in refs:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            continue
        try:
            resolved.append(
                resolve_permitted_media_path(
                    value,
                    uploads_root=uploads_root,
                    workspace_root=workspace_root,
                    kinds=("audio", "video"),
                )
            )
        except (MediaPathNotAllowed, FileNotFoundError, ValueError):
            continue
    return resolved


def resolve_story_cover_audio(
    filename: str,
    *,
    uploads_audio_root: str,
    uploads_root: str,
    workspace_root: str,
) -> str:
    """Resolve a Story cover reference from uploads/audio or the workspace.

    Cover jobs used to look only in uploads/audio/. The shared picker can also
    bind a catalog track that already lives in the workspace, so fall back to
    the confined resolver when that basename is not an upload.
    """
    name = os.path.basename(str(filename or "").strip())
    if not name or "\x00" in name:
        raise FileNotFoundError("Permitted media file was not found")

    audio_root = os.path.realpath(os.path.abspath(uploads_audio_root))
    uploaded = os.path.realpath(os.path.abspath(os.path.join(audio_root, name)))
    if (
        _is_contained(uploaded, audio_root)
        and uploaded != audio_root
        and os.path.splitext(uploaded)[1].lower() in _KIND_EXTENSIONS["audio"]
        and os.path.isfile(uploaded)
    ):
        return uploaded

    return resolve_permitted_media_path(
        name,
        uploads_root=uploads_root,
        workspace_root=workspace_root,
        kinds=("audio",),
    )
