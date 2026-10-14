"""Central lifecycle query used before deleting Series Lab entities.

Jobs are durable checkpoints, so deletion guards must consult the on-disk job
stores instead of relying on process-local worker sets. Workspace delete uses
the same scan: a mid-run delete would wipe the library and let the worker
recreate an empty folder. Output media is never removed by this module.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from services.series_jobs import KINDS, SeriesJobStore


ACTIVE_SERIES_JOB_STATUSES = frozenset({"queued", "running", "cancelling"})
SERIES_JOB_KINDS = ("planning", "render", "assembly", "native", "produce")
PUBLIC_JOB_KEYS = (
    "jobId",
    "kind",
    "status",
    "stage",
    "seriesId",
    "episodeId",
    "message",
)


class ActiveSeriesJobsError(RuntimeError):
    """Raised when a destructive Series action would orphan active work."""

    def __init__(self, jobs: list[dict[str, Any]], *, episode_id: str | None):
        self.jobs = copy.deepcopy(jobs)
        self.episode_id = episode_id
        target = "episode" if episode_id is not None else "series"
        job_ids = ", ".join(str(job["jobId"]) for job in jobs)
        super().__init__(f"Cancel or wait for active {target} jobs before deleting: {job_ids}")

    def detail(self) -> dict[str, Any]:
        return {
            "code": "series_jobs_active",
            "message": str(self),
            "activeJobs": copy.deepcopy(self.jobs),
        }


def list_active_series_jobs(
    workspace_dir: str,
    workspace: str,
    series_id: str,
    *,
    episode_id: str | None = None,
    kinds: Iterable[str] = SERIES_JOB_KINDS,
) -> list[dict[str, Any]]:
    """Return durable active jobs scoped to one Series or one episode."""

    requested_kinds = _kinds(kinds)
    matches: dict[tuple[str, str], dict[str, Any]] = {}
    for kind in requested_kinds:
        for raw_job in SeriesJobStore(workspace_dir, kind).list():
            if str(raw_job.get("workspace") or "") != workspace:
                continue
            if str(raw_job.get("seriesId") or "") != series_id:
                continue
            if episode_id is not None and str(raw_job.get("episodeId") or "") != episode_id:
                continue
            public = _public_job(kind, raw_job)
            if public:
                matches[(kind, public["jobId"])] = public
    return sorted(matches.values(), key=lambda job: (str(job["kind"]), str(job["jobId"])))


def list_active_workspace_series_jobs(workspace_dir: str) -> list[dict[str, Any]]:
    """Return every durable active job stored in this workspace folder."""

    matches: dict[tuple[str, str], dict[str, Any]] = {}
    for kind in sorted(KINDS):
        for raw_job in SeriesJobStore(workspace_dir, kind).list():
            public = _public_job(kind, raw_job)
            if public:
                matches[(kind, public["jobId"])] = public
    return sorted(matches.values(), key=lambda job: (str(job["kind"]), str(job["jobId"])))


def require_no_active_series_jobs(
    workspace_dir: str,
    workspace: str,
    series_id: str,
    *,
    episode_id: str | None = None,
) -> None:
    jobs = list_active_series_jobs(
        workspace_dir,
        workspace,
        series_id,
        episode_id=episode_id,
    )
    if jobs:
        raise ActiveSeriesJobsError(jobs, episode_id=episode_id)


def require_no_active_workspace_series_jobs(workspace_dir: str) -> None:
    jobs = list_active_workspace_series_jobs(workspace_dir)
    if jobs:
        raise ActiveSeriesJobsError(jobs, episode_id=None)


def _kinds(kinds: Iterable[str]) -> tuple[str, ...]:
    requested = tuple(dict.fromkeys(str(kind) for kind in kinds))
    unsupported = [kind for kind in requested if kind not in KINDS]
    if unsupported:
        raise ValueError(f"Unsupported Series Lab job kind: {unsupported[0]}")
    return requested


def _public_job(kind: str, raw_job: dict[str, Any]) -> dict[str, Any] | None:
    status = str(raw_job.get("status") or "").strip().lower()
    if status not in ACTIVE_SERIES_JOB_STATUSES:
        return None
    job_id = str(raw_job.get("jobId") or "").strip()
    if not job_id:
        return None
    public_job = {key: copy.deepcopy(raw_job.get(key)) for key in PUBLIC_JOB_KEYS}
    public_job["jobId"] = job_id
    public_job["kind"] = kind
    public_job["status"] = status
    return public_job
