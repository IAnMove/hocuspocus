"""Which running work keeps a workspace folder from being deleted.

Deleting a workspace removes its folder, and a worker that still holds the folder
(through ``_workspace_dir()``, which creates it again on demand) would scatter its
files into a new, empty one. Each family of long jobs therefore registers a probe
here: ``probe(workspace, workspace_dir)`` returns the jobs of that family that are
alive right now. The delete route asks :func:`blocking` and refuses while it is not
empty.

Rules every probe follows (the review criteria, each with a test):

* Alive means a live claim, thread or in-memory record of THIS process, or a record
  the owning service has reconciled. A checkpoint on disk that says ``running`` but
  has no worker is a lie left by a crash; it must not block deletes for ever.
* Only the positive :data:`ACTIVE_STATUSES` block, never "anything not terminal".
* A job carries the workspace it writes into, and the registry drops the jobs of
  other workspaces, so one running job does not freeze every other folder. A job that
  does not say which workspace it belongs to blocks all of them (fail closed).
* A probe uses the ``workspace_dir`` it is given. It never calls ``workspace_dir(name)``
  itself, which would create the folder.

This module is standard library only. It lives in ``services`` so probes can sit next
to the state they read; the router layer (``routers/workspace_busy_probes.py``) says
which probes each server registers. Nothing here imports a router.
"""
from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

log = logging.getLogger(__name__)

ACTIVE_STATUSES = frozenset({"created", "queued", "waiting", "waiting_resource", "running", "cancelling"})
CODE = "workspace_busy"
PROBE_ERROR = "probe_error"
_SHOWN = 6

Probe = Callable[[str, str], Iterable[Mapping[str, Any]]]

_lock = threading.RLock()
_probes: dict[str, Probe] = {}


def is_active(status: object) -> bool:
    """Whether a job status means the job can still write into its workspace."""
    return str(status or "").strip().lower() in ACTIVE_STATUSES


def claimed(claims: Iterable[str], records: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The jobs whose id is in a live claim set, with the workspace and status of their stored record.

    A claim is taken before a worker thread starts and released in its ``finally``, so it is the
    liveness proof for the planners; the record (a persisted checkpoint cached in memory, often
    with whatever status the crashed process wrote) is only used to say which workspace the job
    writes into. A claim with no record has no workspace and so blocks every workspace.
    """
    found = []
    for job_id in sorted(claims):
        record = records.get(job_id) or {}
        status = record.get("status")
        found.append({
            "jobId": job_id,
            "status": status if is_active(status) else "running",
            "workspace": record.get("workspace"),
        })
    return found


def register(kind: str, probe: Probe) -> None:
    """Set the probe for ``kind``. The last one wins.

    A router factory that owns a service instance registers a closure over it, and tests
    build those factories again and again; replacing is what lets them. The set of kinds a
    server ends up with is pinned by tests, which is what catches a kind registered twice by
    mistake or one that went missing.
    """
    name = str(kind or "").strip()
    if not name or not callable(probe):
        raise ValueError("A workspace busy probe needs a kind and a callable")
    with _lock:
        _probes[name] = probe


def unregister(kind: str) -> None:
    with _lock:
        _probes.pop(str(kind or "").strip(), None)


def registered() -> tuple[str, ...]:
    """The registered kinds, sorted."""
    with _lock:
        return tuple(sorted(_probes))


def reset() -> None:
    """Forget every probe. Tests only."""
    with _lock:
        _probes.clear()


@contextlib.contextmanager
def isolated() -> Iterator[None]:
    """Run with an empty table and put the previous one back afterwards. Tests only."""
    with _lock:
        saved = dict(_probes)
        _probes.clear()
    try:
        yield
    finally:
        with _lock:
            _probes.clear()
            _probes.update(saved)


def _entry(kind: str, job: Mapping[str, Any]) -> dict[str, str]:
    job_id = job.get("jobId") or job.get("job_id") or job.get("id") or ""
    workspace = job.get("workspace")
    return {
        "kind": kind,
        "jobId": str(job_id),
        "status": str(job.get("status") or "").strip().lower() or "running",
        "workspace": str(workspace).strip() if workspace is not None else "",
    }


def blocking(workspace: str, workspace_dir: str) -> list[dict[str, str]]:
    """The live jobs that keep ``workspace`` from being deleted, in registration order.

    A probe that raises is reported as a ``probe_error`` entry instead of being skipped:
    when the registry cannot tell whether work is running, the delete is refused.
    """
    with _lock:
        probes = list(_probes.items())
    found: list[dict[str, str]] = []
    for kind, probe in probes:
        try:
            jobs = [_entry(kind, job) for job in (probe(workspace, workspace_dir) or ())]
        except Exception as error:  # a probe is third-party code to the registry
            log.warning("workspace busy probe %r failed: %s", kind, error)
            found.append({"kind": kind, "jobId": "", "status": PROBE_ERROR, "workspace": workspace})
            continue
        found.extend(job for job in jobs if job["workspace"] in ("", workspace))
    return found


def _describe(item: Mapping[str, str]) -> str:
    if item["status"] == PROBE_ERROR:
        return f"{item['kind']} (could not be checked)"
    label = f"{item['kind']} {item['jobId']}" if item["jobId"] else item["kind"]
    return f"{label} ({item['status']})"


def message(workspace: str, items: list[dict[str, str]]) -> str:
    """The sentence the delete route returns as ``detail``: it names the kind and job id of each blocker."""
    shown = ", ".join(_describe(item) for item in items[:_SHOWN])
    more = f" and {len(items) - _SHOWN} more" if len(items) > _SHOWN else ""
    return (
        f"Cannot delete workspace '{workspace}' while work is still running in it: {shown}{more}. "
        "Cancel it or wait for it to finish, then delete the workspace again."
    )


def refusal(workspace: str, items: list[dict[str, str]]) -> dict[str, Any]:
    """The body of the 409: ``detail`` stays a string (the UI shows it as is); ``blocking`` is for agents."""
    return {"detail": message(workspace, items), "code": CODE, "blocking": items}
