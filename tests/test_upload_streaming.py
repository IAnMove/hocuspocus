"""Regression tests for bounded, atomic HTTP upload ingestion."""

from __future__ import annotations

import asyncio
import hashlib
import threading

import pytest

from app.services import upload_stream
from app.services.upload_stream import (
    UploadTooLargeError,
    stream_upload_file,
    transcode_upload,
)


class FakeUpload:
    def __init__(self, chunks: list[bytes], *, cancel_on_read: int | None = None):
        self.chunks = list(chunks)
        self.cancel_on_read = cancel_on_read
        self.read_count = 0
        self.read_sizes: list[int] = []
        self.closed = False

    async def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        if self.cancel_on_read == self.read_count:
            raise asyncio.CancelledError()
        self.read_count += 1
        return self.chunks.pop(0) if self.chunks else b""

    async def close(self) -> None:
        self.closed = True


def run(coro):
    return asyncio.run(coro)


def test_upload_is_copied_in_chunks_and_hash_is_preserved(tmp_path):
    payload = b"maestro-upload" * 37
    upload = FakeUpload([payload[:31], payload[31:]])
    destination = tmp_path / "uploads" / "asset.bin"

    written = run(
        stream_upload_file(
            upload,
            destination,
            max_bytes=len(payload),
            chunk_size=31,
        )
    )

    assert written == len(payload)
    assert destination.read_bytes() == payload
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == hashlib.sha256(payload).hexdigest()
    assert not (tmp_path / "uploads" / "asset.bin.partial").exists()
    assert upload.read_sizes == [31, 31, 31]
    assert upload.closed


def test_upload_over_limit_cleans_partial_and_never_publishes_destination(tmp_path):
    upload = FakeUpload([b"1234", b"5678"])
    destination = tmp_path / "uploads" / "too-large.bin"

    with pytest.raises(UploadTooLargeError):
        run(
            stream_upload_file(
                upload,
                destination,
                max_bytes=5,
                chunk_size=4,
            )
        )

    assert not destination.exists()
    assert not (tmp_path / "uploads" / "too-large.bin.partial").exists()
    assert upload.closed


def test_cancelled_upload_cleans_partial_file(tmp_path):
    upload = FakeUpload([b"first"], cancel_on_read=1)
    destination = tmp_path / "uploads" / "cancelled.bin"

    with pytest.raises(asyncio.CancelledError):
        run(
            stream_upload_file(
                upload,
                destination,
                max_bytes=1024,
                chunk_size=5,
            )
        )

    assert not destination.exists()
    assert not (tmp_path / "uploads" / "cancelled.bin.partial").exists()
    assert upload.closed


def test_transcode_cancellation_waits_until_worker_releases_files(monkeypatch, tmp_path):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_transcode(source, destination, *, is_video):
        del source, destination, is_video
        started.set()
        release.wait(timeout=5)
        finished.set()

    monkeypatch.setattr(upload_stream, "_transcode_sync", blocking_transcode)

    async def exercise_cancellation():
        task = asyncio.create_task(
            transcode_upload(
                tmp_path / "source.mp3",
                tmp_path / "destination.wav",
                is_video=False,
            )
        )
        release_timer: threading.Timer | None = None
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert started.is_set()
            release_timer = threading.Timer(0.2, release.set)
            release_timer.start()
            cancelled_at = asyncio.get_running_loop().time()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            elapsed = asyncio.get_running_loop().time() - cancelled_at
            assert elapsed >= 0.15, "cleanup returned while ffmpeg still owned the files"
            assert finished.is_set()
        finally:
            release.set()
            if release_timer is not None:
                release_timer.join(timeout=1)

    run(exercise_cancellation())


def test_cancellation_during_atomic_publish_removes_the_new_final(monkeypatch, tmp_path):
    original_replace = upload_stream.os.replace
    rename_started = threading.Event()
    release_rename = threading.Event()

    def blocking_replace(source, destination):
        rename_started.set()
        release_rename.wait(timeout=5)
        original_replace(source, destination)

    monkeypatch.setattr(upload_stream.os, "replace", blocking_replace)
    destination = tmp_path / "uploads" / "cancelled-at-publish.bin"
    upload = FakeUpload([b"complete payload"])

    async def exercise_cancellation():
        task = asyncio.create_task(
            stream_upload_file(upload, destination, max_bytes=1024)
        )
        for _ in range(100):
            if rename_started.is_set():
                break
            await asyncio.sleep(0.01)
        assert rename_started.is_set()
        task.cancel()
        release_rename.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        run(exercise_cancellation())
    finally:
        release_rename.set()

    assert not destination.exists()
    assert not destination.with_name(f"{destination.name}.partial").exists()


def test_colliding_upload_cannot_truncate_an_existing_partial(tmp_path):
    destination = tmp_path / "uploads" / "collision.bin"
    destination.parent.mkdir(parents=True)
    partial = destination.with_name(f"{destination.name}.partial")
    partial.write_bytes(b"owned by another upload")
    upload = FakeUpload([b"second writer"])

    with pytest.raises(FileExistsError):
        run(stream_upload_file(upload, destination, max_bytes=1024))

    assert partial.read_bytes() == b"owned by another upload"
    assert not destination.exists()
    assert upload.closed
