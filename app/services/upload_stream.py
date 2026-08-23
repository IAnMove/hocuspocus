"""Bounded, atomic file ingest helpers for HTTP uploads.

The multipart parser already spools request bodies when appropriate, but an
endpoint must still avoid calling ``UploadFile.read()`` without a size.  This
module keeps the application-side copy bounded and makes the destination
visible only after the complete upload has been flushed and synced.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar


DEFAULT_UPLOAD_CHUNK_BYTES = 1024 * 1024
_T = TypeVar("_T")


class UploadTooLargeError(ValueError):
    """Raised when an upload exceeds its endpoint's authoritative byte cap."""


class UploadTranscodeError(RuntimeError):
    """Raised when ffmpeg cannot transcode an uploaded media file."""

    def __init__(self, message: str, *, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


async def _close_upload(upload: Any) -> None:
    close = getattr(upload, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


def _fsync_directory(directory: str) -> None:
    """Best-effort directory sync after an atomic rename.

    POSIX filesystems need the directory entry synced for the rename to be
    durable after a sudden power loss.  Windows does not support opening a
    directory this way, so the file fsync plus atomic replace remains the
    portable guarantee there.
    """

    if os.name == "nt":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


async def _run_thread_cancellation_safe(
    function: Callable[..., _T],
    /,
    *args: Any,
    **kwargs: Any,
) -> _T:
    """Run blocking work without abandoning it on coroutine cancellation.

    Python cannot stop an already-running OS thread.  Short asynchronous polls
    keep the event loop responsive while the worker runs.  We still propagate
    ``CancelledError``, but only after the blocking operation has settled, so
    callers can safely close or remove its files.
    """

    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["result"] = function(*args, **kwargs)
        except BaseException as error:
            outcome["error"] = error

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    cancelled: asyncio.CancelledError | None = None
    while worker.is_alive():
        try:
            # Polling also works in runtimes where a thread-safe selector wakeup
            # is delayed; the 10 ms interval is negligible beside disk fsync or
            # ffmpeg and keeps the event loop free for other requests.
            await asyncio.sleep(0.01)
        except asyncio.CancelledError as error:
            # A cancellation request must not let the caller remove files that
            # the blocking worker still owns.
            cancelled = error
    if cancelled is not None:
        raise cancelled
    error = outcome.get("error")
    if error is not None:
        raise error
    return outcome.get("result")


def _flush_and_sync(target: Any) -> None:
    target.flush()
    os.fsync(target.fileno())


async def stream_upload_file(
    upload: Any,
    destination: str | os.PathLike[str],
    *,
    max_bytes: int,
    chunk_size: int = DEFAULT_UPLOAD_CHUNK_BYTES,
) -> int:
    """Copy an ``UploadFile``-like object to ``destination`` atomically.

    ``read(chunk_size)`` is used for every read, and the accumulated byte
    count is checked before each chunk is written.  The temporary ``.partial``
    file is removed for every failure path, including ``CancelledError``.
    The final file is exposed only after flush, file fsync, close and
    ``os.replace``.
    """

    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    final_path = Path(destination)
    partial_path = Path(f"{final_path}.partial")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    partial_owned = False

    try:
        if final_path.exists():
            raise FileExistsError(f"Upload destination already exists: {final_path}")
        # Exclusive creation prevents a second writer from truncating an
        # in-flight upload that happened to resolve to the same destination.
        with partial_path.open("xb") as target:
            partial_owned = True
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise TypeError("UploadFile.read() must return bytes")
                chunk_view = memoryview(chunk)
                next_total = total + len(chunk_view)
                if next_total > max_bytes:
                    raise UploadTooLargeError(
                        f"File too large (max {max_bytes} bytes)"
                    )
                # Each synchronous write is bounded to ``chunk_size``.  The
                # potentially long flush/fsync step below runs off-loop.
                target.write(chunk_view)
                total = next_total
            await _run_thread_cancellation_safe(_flush_and_sync, target)
        await _run_thread_cancellation_safe(os.replace, partial_path, final_path)
        await _run_thread_cancellation_safe(_fsync_directory, str(final_path.parent))
        return total
    except BaseException:
        partial_exists = partial_path.exists()
        if partial_owned:
            try:
                partial_path.unlink(missing_ok=True)
            except OSError:
                pass
        # Cancellation can arrive while the atomic rename is executing.  The
        # worker is allowed to settle before cancellation propagates, so detect
        # that commit point and remove the newly-owned final file as well.
        if partial_owned and not partial_exists and final_path.exists():
            try:
                final_path.unlink()
            except OSError:
                pass
        raise
    finally:
        # FastAPI normally closes UploadFile instances after request parsing,
        # but closing here also covers direct callers and cancellation paths.
        try:
            await _close_upload(upload)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A close failure must not mask a size, IO or cancellation error.
            pass


def _transcode_sync(source: str, destination: str, *, is_video: bool) -> None:
    import ffmpeg

    output_kwargs: dict[str, Any] = {"acodec": "pcm_s16le"}
    if is_video:
        output_kwargs["vn"] = None
    try:
        (
            ffmpeg.input(source)
            .output(destination, **output_kwargs)
            .overwrite_output()
            .run(quiet=True)
        )
    except ffmpeg.Error as err:
        stderr = getattr(err, "stderr", b"") or b""
        if isinstance(stderr, (bytes, bytearray)):
            stderr = stderr.decode("utf-8", errors="ignore")
        raise UploadTranscodeError(
            "ffmpeg could not transcode the upload",
            stderr=str(stderr).strip()[:300],
        ) from err


async def transcode_upload(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    is_video: bool,
) -> None:
    """Run ffmpeg off the event loop and wait for it before cancellation cleanup."""

    await _run_thread_cancellation_safe(
        _transcode_sync,
        str(source),
        str(destination),
        is_video=is_video,
    )
