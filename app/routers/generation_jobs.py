"""HTTP routes for generation job status, cancel and list.

The handler bodies live in ``services.generation_jobs``. These functions are the
served endpoints, so the route table names this file, and each calls that
handler. The docstrings are the OpenAPI descriptions.
"""
from fastapi import APIRouter

from services.generation_jobs import cancel_job as _cancel_job
from services.generation_jobs import get_status as _get_status
from services.generation_jobs import list_jobs as _list_jobs


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
