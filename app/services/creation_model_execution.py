"""Run optional creation models under the native job's existing GPU lease."""
import inspect
import os
import secrets
import time

from services import creation_model_service as service, safe_download
from services.job_lifecycle import (
    finish_job, is_cancel_requested, mark_producing, record_job_outputs, update_job,
)


def run_creation_job(st, *, engine, publish):
    job, params = st.job, dict(st.raw_params)
    if int(params.get("seed", -1)) < 0:
        params["seed"] = secrets.randbelow(2**31)
    if getattr(engine, "wan_model", None) is not None or getattr(engine, "offloadobj", None) is not None:
        engine.release_model()

    def progress(message, value, step=0, total=0):
        if step > 0:
            mark_producing(job)
        update_job(job, message=message, progress=value, step=step, total_steps=total, phase="Generating")

    if is_cancel_requested(job):
        return False
    # A test double may replace generate and reject this callback.
    generate_kwargs = {}
    if "on_produce" in inspect.signature(service.generate).parameters:
        generate_kwargs["on_produce"] = lambda: mark_producing(job)
    with safe_download.cancellable_downloads(lambda: is_cancel_requested(job)):
        outputs = service.generate(
            params, st.job_id, job["out_dir"], progress, lambda: is_cancel_requested(job),
            **generate_kwargs,
        )
    if is_cancel_requested(job):
        return False
    record_job_outputs(job, [os.path.basename(path) for path in outputs])
    mode = "image" if params["model_type"].startswith("flux3_") else "audio"
    for path in outputs:
        prefix = f"{params['model_type']}_{st.job_id}_"
        repeat_index = int(os.path.basename(path)[len(prefix):].split("_", 1)[0])
        output_params = {**params, "seed": params["seed"] + repeat_index}
        publish(job, path, {"params": output_params, "generation_mode": mode,
                "job_id": st.job_id, "task_id": job.get("task_id"),
                "root_task_id": job.get("root_task_id") or job.get("task_id"),
                "output_filename": os.path.basename(path), "created_at": time.time(),
                "generation_time": round(time.time() - st.start_time, 2)})
    if not st.finalize:
        return update_job(job, progress=99, phase="Finalizing", message="Finalizing...")
    return finish_job(job, "completed", progress=100, step=0, total_steps=0, phase="", message="Done")
