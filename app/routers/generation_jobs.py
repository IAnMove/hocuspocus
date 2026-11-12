"""HTTP routes for generation job status, cancel and list.

The handler bodies live in ``services.generation_jobs``. These functions are the
served endpoints, so the route table names this file, and each calls that
handler. The docstrings are the OpenAPI descriptions.
"""
from fastapi import APIRouter

from services.generation_jobs import cancel_job as _cancel_job
from services.generation_jobs import get_status as _get_status
from services.generation_jobs import list_jobs as _list_jobs
from services.generation_recovery import discard_generation_queue as _discard_generation_queue
from services.generation_recovery import get_generation_queue_recovery as _get_generation_queue_recovery
from services.generation_recovery import resume_generation_queue as _resume_generation_queue


def get_status(job_id: str):
    """Get generation job status."""
    return _get_status(job_id)


def cancel_job(job_id: str):
    """Cancel a queued or running generation job."""
    return _cancel_job(job_id)


def list_jobs():
    """List all active/recent jobs for reconnection after browser refresh."""
    return _list_jobs()


def create_generation_jobs_router():
    """Mount the status, cancel and list routes in that order."""
    router = APIRouter()
    router.add_api_route("/api/v1/status/{job_id}", get_status, methods=["GET"])
    router.add_api_route("/api/v1/cancel/{job_id}", cancel_job, methods=["POST"])
    router.add_api_route("/api/v1/jobs", list_jobs, methods=["GET"])
    return router


def get_generation_queue_recovery():
    """Return crash leftovers that are not active in this server process."""
    return _get_generation_queue_recovery()


def resume_generation_queue():
    """Requeue persisted requests in their original submission order.

    An interrupted running request restarts from its beginning: model runtimes
    do not expose a portable mid-diffusion checkpoint.
    """
    return _resume_generation_queue()


def discard_generation_queue():
    """Clear only inactive recovery candidates; never cancel live work."""
    return _discard_generation_queue()


def create_generation_recovery_router():
    """Mount the recovery list, resume and discard routes in that order."""
    router = APIRouter()
    router.add_api_route("/api/v1/jobs/recovery", get_generation_queue_recovery, methods=["GET"])
    router.add_api_route("/api/v1/jobs/recovery/resume", resume_generation_queue, methods=["POST"])
    router.add_api_route("/api/v1/jobs/recovery/discard", discard_generation_queue, methods=["POST"])
    return router
