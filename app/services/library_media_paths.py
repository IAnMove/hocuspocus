"""Open the files a library pick names in a Studio generate request.

A picture, clip or sound chosen from the library reaches the server as the bare
file name of a workspace output. WanGP joins a bare name to the server's working
directory and, when nothing is there, drops the field without a word: the guide
video or the start image simply never arrives. Only the models that opt in to
``wangp_1272`` had their names resolved first.

``resolve_library_names`` runs for every model. A bare name that is in the
uploads folder or in the request's workspace becomes the absolute file. A path,
a URL or a name found nowhere is left exactly as it came, so what worked before
still works and nothing is substituted from another workspace.
"""

from __future__ import annotations

from typing import Any

from services.wangp_submission import resolve_wangp_media

# Fields that hold one name, or a list of them.
_MEDIA_FIELDS = (
    "image_start", "image_end", "image_refs",
    "video_guide", "video_guide2", "video_mask",
    "audio_guide", "audio_guide2", "audio_guide3",
    "audio_guide4", "audio_guide5", "audio_guide6",
)
# Fields that hold one list of names for each clip.
_PER_CLIP_FIELDS = ("per_clip_keyframes",)


def is_bare_name(value: Any) -> bool:
    """A file name with no folder, drive or scheme: what the library hands over."""
    if not isinstance(value, str) or not value.strip():
        return False
    return not any(mark in value for mark in ("/", "\\", ":", "\x00"))


def resolve_library_name(value: Any, workspace: str, *, uploads_dir: str, workspace_dir: str) -> Any:
    """The absolute file for a name or URL in the uploads or this workspace, else ``value`` as it was."""
    if not isinstance(value, str) or not value.strip():
        return value
    try:
        return resolve_wangp_media(
            value.strip(), workspace, uploads_dir=uploads_dir, workspace_dir=workspace_dir,
        )
    except ValueError:
        # Not in the uploads or this workspace (an absolute path elsewhere, a
        # missing or ambiguous name): whoever opens the file decides what to say.
        return value


def _resolve_bare(value: Any, workspace: str, roots: dict[str, str]) -> Any:
    if not is_bare_name(value):
        return value
    return resolve_library_name(value, workspace, **roots)


def _resolve_field(value: Any, workspace: str, roots: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [_resolve_bare(item, workspace, roots) for item in value]
    return _resolve_bare(value, workspace, roots)


def resolve_library_names(body: dict, workspace: str, *, uploads_dir: str, workspace_dir: str) -> None:
    """Rewrite the bare names in ``body``'s media fields to the files they stand for."""
    roots = {"uploads_dir": uploads_dir, "workspace_dir": workspace_dir}
    for field in _MEDIA_FIELDS:
        if field in body:
            body[field] = _resolve_field(body[field], workspace, roots)
    for field in _PER_CLIP_FIELDS:
        clips = body.get(field)
        if isinstance(clips, list):
            body[field] = [_resolve_field(names, workspace, roots) for names in clips]
