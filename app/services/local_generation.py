"""The server's own generation tools, called from a worker thread: one picture made, waited for and keyed.

A long job (a character animation) chains the same tools an agent would: ``generation.image``, ``jobs.wait`` and ``studio.key``.
``call`` is ``LocalMcp.call`` (services/local_mcp.py), so the job takes the path an MCP client takes and needs no token. The
helpers read what those tools answer (a finished job may come back as the envelope of a wait that timed out) and wait for a
job through a restart: an interrupted one is resumed once by its intent id.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

# The server admitted a picture but its worker did not start (the GPU is often taken by another job): the request waits in the
# queue for a person to recover it, which nobody is watching for here, so it is discarded and the caller is told to try again.
NOT_STARTED = {"dispatch_uncertain", "admission_recovery_needed"}
NOT_STARTED_MESSAGE = "The server could not start the picture (the GPU may be busy with another job); nothing was made, try again in a moment"
TERMINAL = {"completed", "failed", "cancelled", "discarded", "error"}
FAILED = {"failed", "cancelled", "discarded", "error"}
# A wait that is still open: keep polling. Anything else that is not terminal is a tool error, not another 110s wait.
OPEN = {"", "queued", "running", "pending", "started", "cancelling"}
WAIT_SECONDS = 110


class ToolError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def raise_if_error(reply: dict[str, Any]) -> None:
    if reply.get("_is_error") or reply.get("_rpc_error") or reply.get("_http_error"):
        error = _mapping(reply.get("error"))
        raise ToolError(str(error.get("code") or "tool_error"), str(error.get("message") or reply.get("error") or reply)[:300])


def _job_payload(value: Any) -> dict[str, Any] | None:
    """A live or finished generation job. HTTP error envelopes also have ``status`` (an integer code) and must not win."""
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    if isinstance(status, bool) or isinstance(status, (int, float)):
        return None
    if value.get("job_id") or value.get("output_files") or value.get("timed_out"):
        return value
    text = str(status or "")
    if text and text in TERMINAL | OPEN | {"interrupted"}:
        return value
    return None


def payload_of(reply: dict[str, Any]) -> dict[str, Any]:
    """What a tool answered: the live job, or ``result`` (a keyed file, a wait, a receipt)."""
    # A wait that timed out used to arrive as ``error`` with the live job inside. ``jobs.wait`` now returns that
    # job as the result with ``timed_out``. LocalMcp HTTP errors also put a numeric ``status`` on ``error``; those
    # are failures, not a running generation.
    found = _job_payload(reply.get("error"))
    if found is not None and found.get("job_id"):
        return found
    raise_if_error(reply)
    inner = reply.get("result")
    return _job_payload(inner) or _job_payload(reply) or (inner if isinstance(inner, dict) else reply)


def job_id_of(submitted: dict[str, Any]) -> str:
    raise_if_error(submitted)
    if str(submitted.get("status") or "") == "failed":
        raise ToolError("rejected", str(submitted.get("error") or submitted.get("message") or "the tool refused the request")[:300])
    receipt = _mapping(submitted.get("receipt"))
    nested = _mapping(receipt.get("result")) or receipt
    result = _mapping(submitted.get("result"))
    task = _mapping(nested.get("task")) or _mapping(submitted.get("task")) or _mapping(result.get("task"))
    job = nested.get("job_id") or task.get("job_id") or result.get("job_id") or submitted.get("job_id")
    if not job:
        raise ToolError("no_job", "the tool admitted the request without a job id")
    return str(job)


def files_of(payload: dict[str, Any]) -> list[str]:
    files = [str(item) for item in payload.get("output_files") or [] if item]
    for item in payload.get("outputs") or []:
        if not files and isinstance(item, dict) and (item.get("path") or item.get("canonical_url")):
            files.append(str(item.get("path") or item.get("canonical_url")))
    return files


def file_url(name: str, workspace: str) -> str:
    return f"/api/v1/file/{quote(name.replace(os.sep, '/').lstrip('/'))}?workspace={quote(workspace)}"


class LocalTools:
    """Picture generation and keying for one workspace. ``cancelled`` is asked between waits; ``on_job`` hears the id of the
    generation job now running (None when it ends), so a caller can cancel it."""

    def __init__(self, call: Callable[[str, dict[str, Any]], dict[str, Any]], workspace: str, workspace_root: str, *,
                 cancelled: Callable[[], bool] = lambda: False, on_job: Callable[[str | None], None] = lambda _job: None) -> None:
        self.call, self.workspace, self.root = call, workspace, workspace_root
        self.cancelled, self.on_job = cancelled, on_job

    def _check(self) -> None:
        if self.cancelled():
            raise ToolError("cancelled", "the job was cancelled")

    def _wait(self, job_id: str, intent_id: str) -> dict[str, Any]:
        resumed = False
        while True:
            self._check()
            reply = self.call("jobs.wait", {"version": 1, "input": {"job_id": job_id, "timeout_s": WAIT_SECONDS}})
            error = _mapping(reply.get("error"))
            if (reply.get("_is_error") or reply.get("_http_error")) and not error.get("job_id") and (
                    error.get("status") == 404 or error.get("code") == "not_found"):
                raise ToolError("not_found", f"job {job_id} is not known to the server")
            payload = payload_of(reply)
            status = str(payload.get("status") or "")
            if status in TERMINAL:
                return payload
            if status == "interrupted":
                if resumed:
                    raise ToolError("interrupted", "the generation stopped when the server restarted")
                resumed = True
                raise_if_error(self.call("jobs.resume", {"version": 1, "input": {"intent_id": intent_id}}))
                continue
            if payload.get("timed_out") or status in OPEN:
                continue
            raise ToolError("no_status", "jobs.wait returned no terminal status")

    def image(self, intent_id: str, params: dict[str, Any], output_name: str) -> str:
        """One picture made with ``generation.image``: the workspace file name of the first output."""
        self._check()
        submitted = self.call("generation.image", {"version": 2, "intent_id": intent_id, "input": {
            "workspace": self.workspace, "output_name": output_name, "params": params}})
        try:
            job_id = job_id_of(submitted)
        except ToolError as error:
            if error.code not in NOT_STARTED:
                raise
            self.call("jobs.discard", {"version": 1, "input": {"intent_id": intent_id}})
            raise ToolError(error.code, NOT_STARTED_MESSAGE) from error
        self.on_job(job_id)
        try:
            payload = self._wait(job_id, intent_id)
        finally:
            self.on_job(None)
        if str(payload.get("status") or "") in FAILED:
            raise ToolError(str(payload.get("status")), str(payload.get("error") or payload.get("message") or payload.get("status"))[:300])
        files = files_of(payload)
        if not files:
            raise ToolError("empty_output", "the generation finished without a picture")
        return self.relative(files[0])

    def relative(self, path: str) -> str:
        """A tool's output as a name inside the workspace folder."""
        if path.startswith("/api/") or not os.path.isabs(path):
            return path
        root = os.path.realpath(self.root)
        real = os.path.realpath(path)
        return os.path.relpath(real, root) if real.startswith(root + os.sep) else os.path.basename(path)

    def key(self, intent_id: str, source: str, mode: str) -> str:
        """The picture keyed on its screen colour (``studio.key``, on the CPU): the URL of the keyed file."""
        self._check()
        reply = self.call("studio.key", {"version": 1, "intent_id": intent_id,
                                         "input": {"workspace": self.workspace, "source": source, "mode": mode}})
        payload = payload_of(reply)
        url = payload.get("url") or (file_url(str(payload["file"]), self.workspace) if payload.get("file") else "")
        if not url:
            raise ToolError("key_failed", "studio.key returned no file")
        return str(url)

    def cancel(self, job_id: str) -> None:
        self.call("jobs.cancel", {"version": 1, "input": {"job_id": job_id}})
