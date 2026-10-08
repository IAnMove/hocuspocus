"""Model-free regression tests for generation job state races."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch


_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.abspath(os.path.join(_HERE, "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services.gpu_machine_lock import (  # noqa: E402
    lock_path,
    machine_lock_enabled,
    meta_path,
    read_holder,
    waiting_message,
)
from services.job_lifecycle import (  # noqa: E402
    GENERATED_MEDIA_EXTENSIONS,
    acknowledge_cancel,
    acquire_generation_slot,
    call_with_sticky_interrupt,
    collect_job_outputs,
    finish_job,
    generation_queue_position,
    generation_slot,
    record_job_outputs,
    register_abort_state,
    register_generation_job,
    request_cancel,
    set_job_state_observer,
    snapshot_job,
    try_requeue,
    try_start,
    unregister_abort_state,
    update_job,
)


def _job() -> dict:
    return {"id": "job-1", "status": "queued", "message": "Queued"}


class TestJobLifecycle(unittest.TestCase):
    def tearDown(self):
        set_job_state_observer(None)

    def test_generated_media_extension_contract_is_complete(self):
        self.assertEqual(GENERATED_MEDIA_EXTENSIONS, frozenset({
            ".aac", ".flac", ".gif", ".jpeg", ".jpg", ".m4a", ".mkv",
            ".mov", ".mp3", ".mp4", ".ogg", ".png", ".wav", ".webm",
            ".webp",
        }))

    def test_sticky_interrupt_survives_model_entry_reset(self):
        state = {"abort": False}
        model = type("FakeModel", (), {"_interrupt": False})()
        entered = threading.Event()
        result: list[str] = []

        def reset_then_wait():
            model._interrupt = False
            entered.set()
            deadline = time.time() + 1
            while not model._interrupt and time.time() < deadline:
                time.sleep(0.005)
            return "aborted" if model._interrupt else "timed-out"

        worker = threading.Thread(target=lambda: result.append(
            call_with_sticky_interrupt(
                state,
                model,
                reset_then_wait,
                poll_interval=0.005,
            )
        ))
        worker.start()
        self.assertTrue(entered.wait(timeout=1))
        state["abort"] = True
        worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result, ["aborted"])
        self.assertTrue(model._interrupt)

    def test_pre_cancelled_model_call_is_never_invoked(self):
        state = {"abort": True}
        model = type("FakeModel", (), {"_interrupt": False})()
        callable_ = Mock()
        self.assertIsNone(call_with_sticky_interrupt(
            state, model, callable_, poll_interval=0.005,
        ))
        callable_.assert_not_called()
        self.assertTrue(model._interrupt)

    def test_explicit_outputs_ignore_concurrent_unrelated_files(self):
        with tempfile.TemporaryDirectory() as out_dir:
            own_path = os.path.join(out_dir, "clip-image.png")
            unrelated_path = os.path.join(
                out_dir, "_rerun_audio_other-pipeline.wav",
            )
            for path in (own_path, unrelated_path):
                with open(path, "wb") as handle:
                    handle.write(b"artifact")

            outputs = collect_job_outputs(
                {
                    "artifact_list": [own_path],
                    "file_list": [],
                    "audio_file_list": [],
                },
                out_dir,
                before=set(),
                allow_legacy_fallback=False,
            )

            self.assertEqual(outputs, ["clip-image.png"])

    def test_relative_output_root_prefix_is_not_joined_twice(self):
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as work_dir:
            out_dir = os.path.join(work_dir, "outputs")
            os.makedirs(out_dir)
            rooted_name = os.path.join("outputs", "rooted-image.jpg")
            bare_name = "bare-image.jpg"
            outside_name = os.path.join(work_dir, "outside-image.jpg")
            for path in (
                os.path.join(work_dir, rooted_name),
                os.path.join(out_dir, bare_name),
                outside_name,
            ):
                with open(path, "wb") as handle:
                    handle.write(b"artifact")

            try:
                os.chdir(work_dir)
                outputs = collect_job_outputs(
                    {
                        "artifact_list": [
                            rooted_name,
                            bare_name,
                            outside_name,
                        ],
                    },
                    "outputs",
                    allow_legacy_fallback=False,
                )
            finally:
                os.chdir(original_cwd)

            self.assertEqual(
                outputs,
                ["rooted-image.jpg", "bare-image.jpg"],
            )

    def test_director_job_never_uses_ambiguous_directory_fallback(self):
        with tempfile.TemporaryDirectory() as out_dir:
            with open(os.path.join(out_dir, "unrelated.png"), "wb") as handle:
                handle.write(b"artifact")
            self.assertEqual(
                collect_job_outputs(
                    {"file_list": [], "audio_file_list": []},
                    out_dir,
                    before=set(),
                    allow_legacy_fallback=False,
                ),
                [],
            )

    def test_cancel_queued_prevents_start(self):
        job = _job()
        result = request_cancel(job)
        self.assertTrue(result.changed)
        self.assertFalse(result.was_running)
        self.assertFalse(try_start(job))
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["phase"], "cancelled")
        self.assertIsNotNone(job["finished_at"])

    def test_cancel_waiting_job_is_terminal_immediately(self):
        job = {**_job(), "status": "waiting_resource"}

        result = request_cancel(job)

        self.assertTrue(result.changed)
        self.assertFalse(result.was_running)
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["message"], "Cancelled")
        self.assertIsNotNone(job["finished_at"])

    def test_state_observer_receives_atomic_transition_snapshots(self):
        observed = []
        set_job_state_observer(lambda snapshot: observed.append(dict(snapshot)))
        job = {**_job(), "output_files": []}

        self.assertTrue(try_start(job, phase="loading"))
        self.assertTrue(update_job(job, phase="sampling", step=1))
        record_job_outputs(job, ["clip.mp4"])
        self.assertTrue(finish_job(job, "completed", message="Done"))

        self.assertEqual(
            [snapshot["status"] for snapshot in observed],
            ["running", "running", "running", "completed"],
        )
        self.assertEqual(observed[1]["phase"], "sampling")
        self.assertEqual(observed[2]["output_files"], ["clip.mp4"])
        self.assertEqual(observed[-1]["message"], "Done")
        observed[2]["output_files"].append("observer-only.mp4")
        self.assertEqual(job["output_files"], ["clip.mp4"])

    def test_active_timestamps_exclude_time_spent_queued(self):
        job = {**_job(), "created_at": 10.0, "started_at": None, "finished_at": None}
        with patch("services.job_lifecycle.time.time", side_effect=[25.0, 40.0]):
            self.assertTrue(try_start(job))
            self.assertTrue(finish_job(job, "completed", message="Done"))

        self.assertEqual(job["created_at"], 10.0)
        self.assertEqual(job["started_at"], 25.0)
        self.assertEqual(job["finished_at"], 40.0)
        self.assertEqual(job["finished_at"] - job["started_at"], 15.0)
        self.assertNotEqual(job["finished_at"] - job["created_at"], 15.0)

    def test_cancel_running_signals_abort_and_model_once(self):
        job = _job()
        states: dict = {}
        state = {"abort": False}
        interrupt = Mock()
        self.assertTrue(try_start(job))
        self.assertTrue(register_abort_state(
            job, job["id"], states, state, interrupt_model=interrupt,
        ))

        result = request_cancel(
            job, job_id=job["id"], active_states=states,
        )
        self.assertTrue(result.was_running)
        self.assertTrue(result.abort_signalled)
        self.assertTrue(state["abort"])
        self.assertEqual(job["status"], "cancelling")
        self.assertEqual(job["phase"], "cancelling")
        self.assertEqual(job["message"], "Cancelling…")
        self.assertIsNone(job["finished_at"])
        interrupt.assert_called_once_with()

        # Cancellation is idempotent and cannot signal the model again.
        self.assertFalse(request_cancel(
            job, job_id=job["id"], active_states=states,
        ).changed)
        interrupt.assert_called_once_with()
        unregister_abort_state(job["id"], states, state)
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["message"], "Cancelled")
        self.assertIsNotNone(job["finished_at"])

    def test_finish_and_failure_cannot_overwrite_cancellation(self):
        for terminal in ("completed", "failed"):
            with self.subTest(terminal=terminal):
                job = _job()
                self.assertTrue(try_start(job))
                request_cancel(job)
                self.assertEqual(job["status"], "cancelling")
                self.assertFalse(finish_job(job, terminal, message=terminal))
                self.assertEqual(job["status"], "cancelled")
                self.assertEqual(job["message"], "Cancelled")

    def test_cancel_stays_pending_until_registered_worker_releases(self):
        job = _job()
        states = {}
        state = {"abort": False}
        self.assertTrue(try_start(job))
        self.assertTrue(register_abort_state(job, job["id"], states, state))
        request_cancel(job, job_id=job["id"], active_states=states)

        self.assertFalse(finish_job(job, "failed", error="late"))
        self.assertEqual(job["status"], "cancelling")
        self.assertIsNone(job["finished_at"])

        unregister_abort_state(job["id"], states, state)
        self.assertEqual(job["status"], "cancelled")
        self.assertIsNotNone(job["finished_at"])
        self.assertNotIn("error", job)

    def test_outputs_can_settle_after_cancel_without_changing_terminal_state(self):
        job = _job()
        job["output_files"] = ["clip-1.mp4"]
        self.assertTrue(try_start(job))
        request_cancel(job)

        merged = record_job_outputs(
            job,
            ["clip-1.mp4", "clip-2.mp4"],
            clip_output_files={0: "clip-2.mp4"},
        )
        self.assertEqual(merged, ["clip-1.mp4", "clip-2.mp4"])
        self.assertEqual(job["status"], "cancelling")
        self.assertEqual(job["message"], "Cancelling…")

        snapshot = snapshot_job(job)
        snapshot["output_files"].append("snapshot-only.mp4")
        snapshot["clip_output_files"]["0"] = "snapshot-only.mp4"
        self.assertEqual(
            job["output_files"], ["clip-1.mp4", "clip-2.mp4"],
        )
        self.assertEqual(job["clip_output_files"], {"0": "clip-2.mp4"})

        self.assertTrue(acknowledge_cancel(job))
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["message"], "Cancelled")

    def test_explicit_cancel_acknowledgement_is_guarded_and_idempotent(self):
        untouched = _job()
        self.assertFalse(acknowledge_cancel(untouched))
        self.assertEqual(untouched["status"], "queued")
        completed = {
            **_job(), "status": "completed", "cancel_requested": True,
        }
        self.assertFalse(acknowledge_cancel(completed))
        self.assertEqual(completed["status"], "completed")

        job = _job()
        self.assertTrue(try_start(job))
        request_cancel(job)

        self.assertTrue(acknowledge_cancel(job, detail="Worker released"))
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["phase"], "cancelled")
        self.assertEqual(job["message"], "Cancelled")
        self.assertEqual(job["detail"], "Worker released")
        self.assertIsNotNone(job["finished_at"])
        self.assertFalse(acknowledge_cancel(job))

    def test_cancel_observer_sees_deferred_then_terminal_snapshots(self):
        observed = []
        set_job_state_observer(lambda snapshot: observed.append(dict(snapshot)))
        job = {**_job(), "finished_at": None}

        self.assertTrue(try_start(job))
        request_cancel(job)
        pending = snapshot_job(job)
        self.assertEqual(pending["status"], "cancelling")
        self.assertIsNone(pending["finished_at"])
        self.assertFalse(finish_job(
            job,
            "failed",
            message="Late failure",
            error="must not leak into cancellation",
        ))

        self.assertEqual(
            [snapshot["status"] for snapshot in observed],
            ["running", "cancelling", "cancelled"],
        )
        self.assertIsNone(observed[1]["finished_at"])
        self.assertIsNotNone(observed[2]["finished_at"])
        self.assertEqual(observed[2]["message"], "Cancelled")
        self.assertNotIn("error", observed[2])

    def test_outputs_normalize_live_positional_multiclip_progress(self):
        job = _job()
        job["output_files"] = ["clip-0.mp4"]
        job["clip_output_files"] = [
            "clip-0.mp4", None, "clip-2-old.mp4",
        ]

        merged = record_job_outputs(
            job,
            ["clip-2.mp4", "joined.mp4"],
            clip_output_files={2: "clip-2.mp4"},
            join_output_file="joined.mp4",
        )

        self.assertEqual(merged, ["clip-0.mp4", "clip-2.mp4", "joined.mp4"])
        self.assertEqual(
            job["clip_output_files"],
            {"0": "clip-0.mp4", "2": "clip-2.mp4"},
        )
        self.assertEqual(job["join_output_file"], "joined.mp4")

    def test_completion_wins_before_late_cancel(self):
        job = _job()
        interrupt = Mock()
        self.assertTrue(try_start(job))
        self.assertTrue(finish_job(job, "completed", message="Done"))
        result = request_cancel(job)
        self.assertFalse(result.changed)
        self.assertEqual(job["status"], "completed")
        interrupt.assert_not_called()

    def test_worker_updates_require_a_running_job(self):
        job = _job()
        self.assertFalse(update_job(job, message="Not started"))
        self.assertFalse(try_requeue(job, message="Still queued"))
        self.assertFalse(finish_job(job, "completed", message="Too early"))
        self.assertEqual(job["status"], "queued")

    def test_cancel_between_start_and_abort_registration_refuses_work(self):
        job = _job()
        states: dict = {}
        state = {"abort": False}
        self.assertTrue(try_start(job))
        request_cancel(job)
        self.assertFalse(register_abort_state(
            job, job["id"], states, state, interrupt_model=Mock(),
        ))
        self.assertTrue(state["abort"])
        self.assertNotIn(job["id"], states)

    def test_requeue_after_cancel_is_refused(self):
        job = _job()
        self.assertTrue(try_start(job))
        request_cancel(job)
        self.assertFalse(try_requeue(job, message="Queued again"))
        self.assertFalse(update_job(job, message="Late worker message"))
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(job["message"], "Cancelled")

    def test_queued_job_ignores_a_stale_active_state(self):
        job = _job()
        stale_state = {"abort": False}
        states = {job["id"]: stale_state}
        result = request_cancel(
            job, job_id=job["id"], active_states=states,
        )
        self.assertFalse(result.was_running)
        self.assertFalse(result.abort_signalled)
        self.assertFalse(stale_state["abort"])

    def test_mismatched_state_never_invokes_wan_interrupt(self):
        job = _job()
        states: dict = {}
        registered_state = {"abort": False}
        replacement_state = {"abort": False}
        interrupt = Mock()
        self.assertTrue(try_start(job))
        self.assertTrue(register_abort_state(
            job,
            job["id"],
            states,
            registered_state,
            interrupt_model=interrupt,
        ))
        states[job["id"]] = replacement_state
        try:
            result = request_cancel(
                job, job_id=job["id"], active_states=states,
            )
            self.assertFalse(result.abort_signalled)
            self.assertFalse(registered_state["abort"])
            self.assertFalse(replacement_state["abort"])
            interrupt.assert_not_called()
        finally:
            unregister_abort_state(job["id"], states, registered_state)
            states.pop(job["id"], None)

    def test_non_wan_abort_state_does_not_interrupt_model(self):
        job = _job()
        states: dict = {}
        state = {"abort": False}
        interrupt = Mock()
        self.assertTrue(try_start(job))
        self.assertTrue(register_abort_state(
            job, job["id"], states, state,
        ))
        request_cancel(
            job, job_id=job["id"], active_states=states,
        )
        self.assertTrue(state["abort"])
        interrupt.assert_not_called()
        unregister_abort_state(job["id"], states, state)

    def test_cancelled_waiter_exits_without_acquiring_generation_lock(self):
        generation_lock = threading.Lock()
        generation_lock.acquire()
        job = _job()
        result: list[bool] = []
        waiting = threading.Event()

        def wait_for_slot():
            waiting.set()
            result.append(acquire_generation_slot(
                generation_lock, job, poll_interval=0.01,
            ))

        thread = threading.Thread(target=wait_for_slot)
        thread.start()
        self.assertTrue(waiting.wait(timeout=1))
        time.sleep(0.03)
        request_cancel(job)
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [False])
        generation_lock.release()

    def test_cancelled_orphan_waiter_cannot_block_the_next_job(self):
        generation_lock = threading.Lock()
        orphan = {"id": "worker-failed-before-acquire", "status": "queued"}
        successor = {"id": "next-job", "status": "queued"}
        register_generation_job(generation_lock, orphan)
        register_generation_job(generation_lock, successor)
        request_cancel(orphan)
        result = []

        def next_worker():
            acquired = acquire_generation_slot(generation_lock, successor, poll_interval=0.01)
            result.append(acquired)
            if acquired:
                generation_lock.release()

        worker = threading.Thread(target=next_worker)
        worker.start()
        try:
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive(), "a cancelled waiter with no worker must not retain its FIFO position")
            self.assertEqual(result, [True])
            self.assertIsNone(generation_queue_position(generation_lock, orphan))
            self.assertFalse(generation_lock.locked())
        finally:
            request_cancel(successor)
            worker.join(timeout=1)
            # Also drain an orphan when demonstrating this regression on old code.
            acquire_generation_slot(generation_lock, orphan, poll_interval=0.01)

    def test_generation_slot_is_fifo_by_registration_not_thread_schedule(self):
        generation_lock = threading.Lock()
        generation_lock.acquire()
        jobs = [
            {"id": f"job-{index}", "status": "queued", "message": "Queued"}
            for index in range(1, 4)
        ]
        for expected_position, job in enumerate(jobs, start=1):
            self.assertEqual(
                register_generation_job(generation_lock, job),
                expected_position,
            )
            self.assertEqual(
                generation_queue_position(generation_lock, job),
                expected_position,
            )

        acquisition_order: list[str] = []

        def acquire_and_release(job):
            acquired = acquire_generation_slot(
                generation_lock,
                job,
                poll_interval=0.005,
            )
            if acquired:
                acquisition_order.append(job["id"])
                generation_lock.release()

        # Start in reverse to prove OS thread scheduling cannot change the
        # synchronous API registration order.
        threads = [
            threading.Thread(target=acquire_and_release, args=(job,))
            for job in reversed(jobs)
        ]
        for thread in threads:
            thread.start()
        time.sleep(0.03)
        generation_lock.release()
        for thread in threads:
            thread.join(timeout=1)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(acquisition_order, ["job-1", "job-2", "job-3"])

    def test_finish_cancel_race_has_only_valid_outcomes(self):
        for _ in range(50):
            job = _job()
            states: dict = {}
            state = {"abort": False}
            interrupt = Mock()
            self.assertTrue(try_start(job))
            self.assertTrue(register_abort_state(
                job, job["id"], states, state, interrupt_model=interrupt,
            ))
            barrier = threading.Barrier(3)

            def complete():
                barrier.wait()
                finish_job(job, "completed", message="Done")

            def cancel():
                barrier.wait()
                request_cancel(
                    job, job_id=job["id"], active_states=states,
                )

            finish_thread = threading.Thread(target=complete)
            cancel_thread = threading.Thread(target=cancel)
            finish_thread.start()
            cancel_thread.start()
            barrier.wait()
            finish_thread.join(timeout=1)
            cancel_thread.join(timeout=1)

            if job["status"] == "completed":
                self.assertFalse(state["abort"])
                interrupt.assert_not_called()
                unregister_abort_state(job["id"], states, state)
            else:
                self.assertEqual(job["status"], "cancelling")
                self.assertTrue(state["abort"])
                interrupt.assert_called_once_with()
                unregister_abort_state(job["id"], states, state)
                self.assertEqual(job["status"], "cancelled")


_HOLDER_SCRIPT = r"""
import os
import sys
import threading
import time
sys.path.insert(0, os.environ["HOCUS_APP"])
from services.job_lifecycle import generation_slot
job = {
    "id": os.environ["JOB_ID"],
    "model": os.environ["MODEL"],
    "workspace": "mejoras-lab",
    "status": "queued",
    "phase": "queued",
    "message": "Queued",
}
lock = threading.Lock()
with generation_slot(lock, job, poll_interval=0.02) as acquired:
    if not acquired:
        raise SystemExit(2)
    with open(os.environ["READY"], "w", encoding="utf-8") as handle:
        handle.write("ready")
    deadline = time.time() + 20
    while time.time() < deadline and not os.path.exists(os.environ["RELEASE"]):
        time.sleep(0.02)
"""

_WAITER_SCRIPT = r"""
import os
import sys
import threading
import time
sys.path.insert(0, os.environ["HOCUS_APP"])
from services.job_lifecycle import generation_slot
job = {
    "id": "waiter",
    "model": "qwen",
    "workspace": "mejoras-lab",
    "status": "queued",
    "phase": "queued",
    "message": "Queued",
}
seen = os.environ["SEEN"]

def watch():
    deadline = time.time() + 15
    while time.time() < deadline:
        message = str(job.get("message") or "")
        if message.startswith("waiting for the GPU:"):
            with open(seen, "w", encoding="utf-8") as handle:
                handle.write(message)
            return
        time.sleep(0.02)

threading.Thread(target=watch, daemon=True).start()
lock = threading.Lock()
with generation_slot(lock, job, poll_interval=0.02) as acquired:
    if not acquired:
        raise SystemExit(2)
    if job.get("message") != "Queued":
        raise SystemExit(3)
    with open(os.environ["DONE"], "w", encoding="utf-8") as handle:
        handle.write(job.get("message") or "")
"""


class TestGpuMachineLock(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = self._tmpdir.name
        self._saved = {
            key: os.environ.get(key)
            for key in ("HOCUS_GPU_LOCK_PATH", "HOCUS_GPU_MACHINE_LOCK", "SERVER_PORT")
        }
        self._procs: list[subprocess.Popen[str]] = []
        os.environ["HOCUS_GPU_LOCK_PATH"] = os.path.join(self.root, "gpu.lock")
        os.environ["HOCUS_GPU_MACHINE_LOCK"] = "1"
        os.environ.pop("SERVER_PORT", None)

    def tearDown(self):
        for proc in self._procs:
            if proc.poll() is None:
                proc.kill()
            try:
                proc.communicate(timeout=5)
            except (subprocess.TimeoutExpired, ValueError):
                proc.wait(timeout=5)
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmpdir.cleanup()

    def _env(self, **extra: str) -> dict[str, str]:
        env = os.environ.copy()
        env.pop("HOCUS_MCP_TOKEN", None)
        env["HOCUS_APP"] = _APP_DIR
        env["PYTHONPATH"] = _APP_DIR + os.pathsep + env.get("PYTHONPATH", "")
        env["HOCUS_GPU_LOCK_PATH"] = os.path.join(self.root, "gpu.lock")
        env["HOCUS_GPU_MACHINE_LOCK"] = extra.pop("HOCUS_GPU_MACHINE_LOCK", "1")
        env.update(extra)
        return env

    def _spawn(self, script: str, env: dict[str, str]) -> subprocess.Popen[str]:
        proc = subprocess.Popen(
            [sys.executable, "-c", script],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._procs.append(proc)
        return proc

    def _start_holder(self, *, port: str, job_id: str, model: str) -> subprocess.Popen[str]:
        return self._spawn(_HOLDER_SCRIPT, self._env(
            SERVER_PORT=port,
            JOB_ID=job_id,
            MODEL=model,
            READY=os.path.join(self.root, "ready"),
            RELEASE=os.path.join(self.root, "release"),
        ))

    def _wait_file(self, path: str, timeout: float = 5) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as handle:
                    return handle.read()
            time.sleep(0.02)
        details = []
        for proc in self._procs:
            if proc.poll() is not None:
                stdout, stderr = proc.communicate()
                details.append(f"exit {proc.returncode}\n{stdout}\n{stderr}")
        self.fail(f"timed out waiting for {path}\n" + "\n".join(details))

    def _finish(self, proc: subprocess.Popen[str]) -> None:
        stdout, stderr = proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 0, stderr or stdout)

    def _lock_is_free(self) -> bool:
        import fcntl
        path = lock_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            fcntl.flock(fd, fcntl.LOCK_UN)
            return True
        finally:
            os.close(fd)

    def test_waiting_message_names_the_holder(self):
        text = waiting_message(
            {
                "port": "42042",
                "pid": 99,
                "job_id": "job-7",
                "model": "minimax_h3",
                "since": 1000,
            },
            now=1000 + 180,
        )
        self.assertEqual(
            text,
            "waiting for the GPU: held by :42042 "
            "(pid 99, job job-7, model minimax_h3) for 3 min",
        )
        self.assertEqual(
            waiting_message(None),
            "waiting for the GPU: held by another process",
        )

    def test_disabled_values_take_nothing(self):
        for value in ("0", "false", "no", "off", "FALSE"):
            os.environ["HOCUS_GPU_MACHINE_LOCK"] = value
            self.assertFalse(machine_lock_enabled(), value)
        os.environ.pop("HOCUS_GPU_MACHINE_LOCK", None)
        self.assertTrue(machine_lock_enabled())

    def test_default_lock_path_is_the_user_cache(self):
        os.environ.pop("HOCUS_GPU_LOCK_PATH", None)
        self.assertEqual(lock_path().name, "gpu.lock")
        self.assertEqual(lock_path().parent.name, "hocuspocus")
        self.assertEqual(meta_path().name, "gpu.lock.json")

    def test_second_process_sees_the_holder_and_then_runs(self):
        holder = self._start_holder(port="42042", job_id="job-7", model="minimax_h3")
        self._wait_file(os.path.join(self.root, "ready"))
        record = read_holder()
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["pid"], holder.pid)
        self.assertEqual(record["workspace"], "mejoras-lab")
        seen = os.path.join(self.root, "seen")
        done = os.path.join(self.root, "done")
        waiter = self._spawn(_WAITER_SCRIPT, self._env(SEEN=seen, DONE=done))
        text = self._wait_file(seen)
        self.assertIn(":42042", text)
        self.assertIn(f"pid {holder.pid}", text)
        self.assertIn("job job-7", text)
        self.assertIn("model minimax_h3", text)
        self.assertIn("for 0 min", text)
        with open(os.path.join(self.root, "release"), "w", encoding="utf-8") as handle:
            handle.write("go")
        self._wait_file(done)
        self._finish(holder)
        self._finish(waiter)

    def test_killing_the_holder_releases_the_lock(self):
        holder = self._start_holder(port="42042", job_id="job-7", model="minimax_h3")
        self._wait_file(os.path.join(self.root, "ready"))
        holder.kill()
        holder.wait(timeout=5)
        self.assertIsNone(read_holder())
        os.environ["SERVER_PORT"] = "42021"
        job = {
            "id": "next",
            "model": "qwen",
            "workspace": "mejoras-lab",
            "status": "queued",
            "message": "Queued",
        }
        errors: list[BaseException] = []

        def take_over():
            try:
                with generation_slot(threading.Lock(), job, poll_interval=0.02) as acquired:
                    if acquired is not True:
                        raise AssertionError(acquired)
                    record = read_holder()
                    if record is None or record.get("pid") != os.getpid():
                        raise AssertionError(record)
                    if record.get("port") != "42021" or job.get("message") != "Queued":
                        raise AssertionError((record, job.get("message")))
            except BaseException as exc:  # noqa: BLE001 - reported on the test thread
                errors.append(exc)

        thread = threading.Thread(target=take_over)
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), "the lock stayed held after the holder died")
        self.assertEqual(errors, [])
        self.assertIsNone(read_holder())

    def test_disabled_lock_does_not_wait_or_replace_the_holder(self):
        holder = self._start_holder(port="42042", job_id="job-7", model="minimax_h3")
        self._wait_file(os.path.join(self.root, "ready"))
        os.environ["HOCUS_GPU_MACHINE_LOCK"] = "0"
        job = {"id": "local", "status": "queued", "message": "Queued", "phase": "queued"}
        with generation_slot(threading.Lock(), job, poll_interval=0.02) as acquired:
            self.assertTrue(acquired)
            self.assertEqual(job["message"], "Queued")
            self.assertNotEqual(job.get("phase"), "waiting_gpu")
        record = read_holder()
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["pid"], holder.pid)
        with open(os.path.join(self.root, "release"), "w", encoding="utf-8") as handle:
            handle.write("go")
        self._finish(holder)

    def test_local_queue_does_not_take_the_machine_lock(self):
        process_lock = threading.Lock()
        process_lock.acquire()
        job = {"id": "queued", "status": "queued", "message": "Queued"}
        entered = threading.Event()
        release = threading.Event()

        def worker():
            with generation_slot(process_lock, job, poll_interval=0.01) as acquired:
                self.assertTrue(acquired)
                entered.set()
                release.wait(timeout=2)

        thread = threading.Thread(target=worker)
        thread.start()
        handed = False
        try:
            time.sleep(0.05)
            self.assertFalse(entered.is_set())
            self.assertEqual(job["message"], "Queued")
            self.assertIsNone(read_holder())
            self.assertTrue(self._lock_is_free())
            process_lock.release()
            handed = True
            self.assertTrue(entered.wait(timeout=2))
            record = read_holder()
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record["pid"], os.getpid())
            self.assertEqual(job["message"], "Queued")
            self.assertFalse(self._lock_is_free())
        finally:
            release.set()
            if not handed:
                process_lock.release()
            thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertIsNone(read_holder())
        self.assertFalse(process_lock.locked())

    def test_cancel_while_waiting_releases_the_process_lock(self):
        holder = self._start_holder(port="42042", job_id="job-7", model="minimax_h3")
        self._wait_file(os.path.join(self.root, "ready"))
        process_lock = threading.Lock()
        job = {"id": "cancel-me", "status": "queued", "message": "Queued"}
        result: list[bool] = []

        def worker():
            with generation_slot(process_lock, job, poll_interval=0.02) as acquired:
                result.append(bool(acquired))

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            deadline = time.time() + 2
            while time.time() < deadline and job.get("phase") != "waiting_gpu":
                time.sleep(0.02)
            self.assertEqual(job.get("phase"), "waiting_gpu")
            self.assertTrue(process_lock.locked())
            request_cancel(job)
            thread.join(timeout=2)
        finally:
            with open(os.path.join(self.root, "release"), "w", encoding="utf-8") as handle:
                handle.write("go")
            thread.join(timeout=2)
            self._finish(holder)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [False])
        self.assertFalse(process_lock.locked())
        self.assertEqual(job["status"], "cancelled")

    def test_instance_table_formats_rows_without_stopping_anyone(self):
        import importlib.util
        path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "scripts", "hocus_instances.py",
        ))
        spec = importlib.util.spec_from_file_location("hocus_instances_under_test", path)
        self.assertIsNotNone(spec)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        text = module.format_table([{
            "port": "42021",
            "pid": "10",
            "rss_mib": "3",
            "vram_mib": "0",
            "behind": "2",
            "commit": "abcdef",
            "folder": "/tmp/hocuspocus",
        }])
        self.assertIn("42021", text)
        self.assertIn("abcdef", text)
        self.assertFalse(module._is_instance("bash -c python launch.py", "/tmp/hocuspocus", "bash"))
        self.assertTrue(module._is_instance("python launch.py", "/tmp/hocuspocus", "python"))
        self.assertEqual(module.format_lock(), "lock: free")
        rows = module.collect_instances(vram={})
        self.assertIsInstance(rows, list)
        self.assertIn("port", module.format_table(rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
