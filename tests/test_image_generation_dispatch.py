"""The worker dispatch behind every generation command (generation.image, speech, music, sfx, video).

The kernel split moved ``register_generation_job`` out of the full server's module globals while this dispatch still asked its runtime
dictionary for it, so every admission failed with ``dispatch_uncertain`` and no command could start a job. The dispatch now imports it."""
import threading
from unittest.mock import MagicMock

from services.image_generation_runtime import create_image_generation_commands


def _runtime(started):
    return {
        "_task_registry": MagicMock(), "generate": MagicMock(), "_new_generation_job": MagicMock(), "_generation_task_fields": MagicMock(),
        "_durable_generation_queue": MagicMock(), "_jobs": {}, "wgp": MagicMock(), "_gen_lock": threading.Lock(),
        "_run_generation_with_preparation": lambda job_id: started.append(job_id), "_cancel_h3_idle_release": lambda: None,
        "_active_gen_states": ("queued", "running"),
    }


def test_the_dispatch_registers_the_job_and_starts_its_worker_with_only_what_the_server_still_provides():
    started, runtime = [], None
    runtime = _runtime(started)
    service = create_image_generation_commands(runtime)
    job = {"id": "job-1", "workspace": "default", "task_id": "task-1", "params": {}}
    service.dispatch(job)
    for thread in threading.enumerate():
        if thread.name == "command-generation-job-1":
            thread.join(5)
    assert started == ["job-1"] and runtime["_jobs"]["job-1"] is job
    assert "_generation_queue_token" in job, "the job took its place on the single GPU queue before its worker started"
