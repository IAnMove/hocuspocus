"""Turn the names a Studio MiniMax H3 manifest carries into real files.

A picture picked from the library arrives as the bare file name of a workspace
output; an uploaded one arrives as a path the server already knows. The
manifest check opens every ``path`` as given, so a bare name was searched for in
the server's working directory and reported as "file was not found".

This runs before that check. A name or URL that points into the uploads folder
or the request's workspace becomes the absolute file; anything else is left as
it was, so the check still reports it by name.
"""

from __future__ import annotations

from typing import Any

from services.library_media_paths import resolve_library_name

# A reference names its media in ``path``; a video may also carry its own
# soundtrack in ``audio_path``.
_PATH_KEYS = ("path", "audio_path")


def resolve_h3_reference_paths(
    manifest: Any, workspace: str, *, uploads_dir: str, workspace_dir: str,
) -> Any:
    """Return ``manifest`` with every library name or upload URL resolved to its file."""
    if not isinstance(manifest, list):
        return manifest
    resolved: list[Any] = []
    for entry in manifest:
        if not isinstance(entry, dict):
            resolved.append(entry)
            continue
        item = dict(entry)
        for key in _PATH_KEYS:
            if key in item:
                item[key] = resolve_library_name(
                    item[key], workspace, uploads_dir=uploads_dir, workspace_dir=workspace_dir,
                )
        resolved.append(item)
    return resolved
