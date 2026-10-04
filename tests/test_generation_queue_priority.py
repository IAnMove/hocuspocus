"""Pending GPU queue order: short high-priority work starts before a long job."""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.abspath(os.path.join(_HERE, "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services.job_lifecycle import (  # noqa: E402
    acquire_generation_slot,
    ensure_generation_priority,
    generation_queue_position,
    priority_fields,
    register_generation_job,
    take_submission_priority,
)


def _queued(job_id: str, *, priority: int | None, seconds: float, mode: str) -> dict:
    job = {
        "id": job_id,
        "status": "queued",
        "params": {"generation_mode": mode, "duration_seconds": seconds},
    }
    if priority is not None:
        job["priority"] = priority
    return job


def _start_order(lock: threading.Lock, jobs: list[dict]) -> list[str]:
    """Start waiters behind a held GPU lock and return the acquisition order."""
    started: list[str] = []

    def acquire(job: dict) -> None:
        if acquire_generation_slot(lock, job, poll_interval=0.005):
            started.append(job["id"])
            lock.release()

    threads = [threading.Thread(target=acquire, args=(job,)) for job in jobs]
    for thread in threads:
        thread.start()
    time.sleep(0.03)
    lock.release()
    for thread in threads:
        thread.join(timeout=1)
    if any(thread.is_alive() for thread in threads):
        raise AssertionError(f"queue workers did not finish; started={started}")
    return started


class TestGenerationQueuePriority(unittest.TestCase):
    def test_short_high_priority_starts_after_the_running_job(self):
        """Long low, short high, then medium: the short job is next."""
        lock = threading.Lock()
        lock.acquire()
        long_low = _queued("long-low", priority=1, seconds=30, mode="video")
        short_high = _queued("short-high", priority=10, seconds=1, mode="image")
        medium = _queued("medium", priority=5, seconds=10, mode="video")
        try:
            for job in (long_low, short_high, medium):
                register_generation_job(lock, job)
            self.assertEqual(
                [
                    generation_queue_position(lock, short_high),
                    generation_queue_position(lock, medium),
                    generation_queue_position(lock, long_low),
                ],
                [1, 2, 3],
            )
            started = _start_order(lock, [long_low, short_high, medium])
            self.assertEqual(started[0], "short-high")
            self.assertEqual(started, ["short-high", "medium", "long-low"])
        finally:
            if lock.locked():
                lock.release()

    def test_one_second_still_does_not_wait_behind_a_thirty_second_video(self):
        lock = threading.Lock()
        lock.acquire()
        video = _queued("video-30s", priority=None, seconds=30, mode="video")
        still = {
            "id": "still-1s",
            "status": "queued",
            "params": {"generation_mode": "image"},
        }
        try:
            register_generation_job(lock, video)
            register_generation_job(lock, still)
            self.assertEqual(generation_queue_position(lock, still), 1)
            started = _start_order(lock, [video, still])
            self.assertEqual(started, ["still-1s", "video-30s"])
        finally:
            if lock.locked():
                lock.release()

    def test_higher_priority_long_job_still_runs_before_a_shorter_one(self):
        lock = threading.Lock()
        lock.acquire()
        long_high = _queued("long-high", priority=10, seconds=30, mode="video")
        short_low = _queued("short-low", priority=0, seconds=1, mode="image")
        try:
            register_generation_job(lock, long_high)
            register_generation_job(lock, short_low)
            started = _start_order(lock, [long_high, short_low])
            self.assertEqual(started, ["long-high", "short-low"])
        finally:
            if lock.locked():
                lock.release()

    def test_omitted_priority_keeps_registration_order_without_a_length(self):
        lock = threading.Lock()
        first = {"id": "first", "status": "queued"}
        second = {"id": "second", "status": "queued"}
        self.assertEqual(register_generation_job(lock, first), 1)
        self.assertEqual(register_generation_job(lock, second), 2)
        self.assertEqual(generation_queue_position(lock, first), 1)

    def test_priority_must_be_an_integer(self):
        lock = threading.Lock()
        job = {"id": "bad", "status": "queued", "priority": "high"}
        with self.assertRaises(ValueError):
            register_generation_job(lock, job)
        self.assertIsNone(generation_queue_position(lock, job))
        with self.assertRaises(ValueError):
            ensure_generation_priority({"priority": True})
        ensure_generation_priority({"prompt": "still"})

    def test_submit_accepts_optional_numeric_priority(self):
        command = {
            "version": 1,
            "operation": "generation.image",
            "intent_id": "still-first",
            "input": {"prompt": "one second", "priority": 4},
        }
        self.assertEqual(take_submission_priority(command), 4)
        self.assertNotIn("priority", command["input"])
        self.assertEqual(priority_fields(4), {"priority": 4})
        self.assertEqual(priority_fields(None), {})
        self.assertIsNone(take_submission_priority({"input": {"prompt": "plain"}}))
        with self.assertRaises(ValueError):
            take_submission_priority({"priority": 1.5})


    def test_a_job_waiting_past_the_limit_is_overtaken_only_by_a_higher_priority(self):
        """TTS declares a 20 s cap, so images kept overtaking it; aging stops that."""
        from unittest import mock
        import services.job_lifecycle as lifecycle

        lock = threading.Lock()
        lock.acquire()
        clock = [1000.0]
        speech = _queued("speech", priority=None, seconds=20, mode="speech")
        early_image = _queued("early-image", priority=None, seconds=1, mode="image")
        late_image = _queued("late-image", priority=None, seconds=1, mode="image")
        urgent = _queued("urgent", priority=5, seconds=30, mode="video")
        try:
            with mock.patch.object(lifecycle.time, "monotonic", lambda: clock[0]), \
                    mock.patch.dict(os.environ, {lifecycle.MAX_WAIT_ENV: "300"}):
                register_generation_job(lock, speech)
                register_generation_job(lock, early_image)
                self.assertEqual(generation_queue_position(lock, early_image), 1, "a fresh wait still runs short first")
                clock[0] += 301
                register_generation_job(lock, late_image)
                register_generation_job(lock, urgent)
            self.assertEqual(
                [generation_queue_position(lock, job) for job in (urgent, early_image, speech, late_image)],
                [1, 2, 3, 4],
            )
            with mock.patch.dict(os.environ, {lifecycle.MAX_WAIT_ENV: "0"}):
                self.assertEqual(lifecycle.queue_max_wait_seconds(), 0)
            with mock.patch.dict(os.environ, {lifecycle.MAX_WAIT_ENV: "soon"}):
                self.assertEqual(lifecycle.queue_max_wait_seconds(), lifecycle.DEFAULT_MAX_WAIT_SECONDS)
            self.assertEqual(_start_order(lock, [speech, early_image, late_image, urgent]),
                             ["urgent", "early-image", "speech", "late-image"])
        finally:
            if lock.locked():
                lock.release()


if __name__ == "__main__":
    unittest.main(verbosity=2)
