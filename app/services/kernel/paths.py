"""Path containment and upload slots shared by both servers and by services."""
from __future__ import annotations

import asyncio
import os

from services.upload_stream import stream_upload_file, transcode_upload


def safe_join(base: str, *parts: str) -> str | None:
    """Join `parts` under `base` and return the absolute path only if it
    stays inside `base`. Returns None on traversal attempts (`..`, absolute
    paths, symlinks escaping the base, etc.). Use for any endpoint that
    accepts a user-supplied filename."""
    try:
        base_real = os.path.realpath(base)
        joined = os.path.realpath(os.path.join(base_real, *parts))
        # commonpath compares path components rather than string prefixes.
        # normcase preserves correct behaviour on case-insensitive Windows
        # filesystems and ValueError handles paths on different drives.
        base_cmp = os.path.normcase(base_real)
        joined_cmp = os.path.normcase(joined)
        if os.path.commonpath((base_cmp, joined_cmp)) != base_cmp:
            return None
        return joined
    except (ValueError, OSError):
        return None


class PathPolicy:
    """Path containment and the bounded upload slots, one set per server.

    Uploads are deliberately bounded independently from GPU/model lanes.  A
    handful of concurrent clients may ingest at once, while only two ffmpeg
    workers can compete for CPU, disk and decoder resources.  Waiting on these
    semaphores is cancellable and never holds a global application lock.
    """

    def __init__(self) -> None:
        self.ingest_slots = asyncio.Semaphore(4)
        self.transcode_slots = asyncio.Semaphore(2)

    def safe_join(self, base: str, *parts: str) -> str | None:
        """Join `parts` under `base`; None when the result would leave `base`."""
        return safe_join(base, *parts)

    def resolve_output_move_path(self, base: str, relative_name: str) -> str | None:
        """Resolve one output path for a cross-workspace move.

        The move endpoint accepts a path parameter, so it needs a stricter
        contract than a generic join: only explicit relative components using
        URL separators are accepted. Both source and destination are then
        resolved through ``safe_join`` so existing symlinks cannot escape their
        workspace.
        """
        if not isinstance(relative_name, str):
            return None
        value = relative_name.strip()
        if not value or "\x00" in value or "\\" in value:
            return None
        drive, _tail = os.path.splitdrive(value)
        if drive or os.path.isabs(value):
            return None
        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            return None
        resolved = self.safe_join(base, *parts)
        if not resolved or resolved == os.path.realpath(base):
            return None
        return resolved

    async def stream_upload(self, upload, destination: str, *, max_bytes: int) -> int:
        async with self.ingest_slots:
            return await stream_upload_file(
                upload,
                destination,
                max_bytes=max_bytes,
            )

    async def transcode_upload(self, source: str, destination: str, *, is_video: bool) -> None:
        async with self.transcode_slots:
            await transcode_upload(source, destination, is_video=is_video)
