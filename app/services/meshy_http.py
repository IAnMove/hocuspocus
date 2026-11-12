"""Meshy HTTP plumbing shared by generation, rigging and animation.

One place for what every Meshy call needs: the bearer header, a clear message per
status code, the two kinds of 429, polling a task until it ends, refunding a task
that never started, and downloading a result. It calls ``requests.get/post/delete``
by name (no ``Session``), so a test can fake those three functions.

Meshy deletes API outputs after three days. Download every file as soon as a task
succeeds and never keep a signed URL for later.
"""
from __future__ import annotations

import time
from typing import Any, Callable

import requests

API_ROOT = "https://api.meshy.ai/openapi"
POLL_SECONDS = 3.0
POLL_TIMEOUT_SECONDS = 15 * 60
# Rate limit (20 requests per second): Retry-After says how long. A few waits are enough.
MAX_RATE_LIMIT_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60.0
DEFAULT_RETRY_AFTER_SECONDS = 2.0
# NoMorePendingTasks is the concurrent-task limit of the plan: it has no Retry-After, a running
# task has to finish first. Wait with a growing pause, up to a total.
BUSY_PAUSES = (5.0, 10.0, 20.0, 30.0, 60.0)
BUSY_WAIT_LIMIT_SECONDS = 10 * 60
# Reads (never creations: a lost answer to a POST may hide a task that already costs credits).
READ_RETRIES = 3
SLICE_SECONDS = 1.0

PENDING, IN_PROGRESS, SUCCEEDED = "PENDING", "IN_PROGRESS", "SUCCEEDED"
FAILED_STATES = frozenset({"FAILED", "CANCELED", "CANCELLED"})


class MeshyError(RuntimeError):
    """A Meshy call that failed. ``code`` is a stable machine word, ``reason`` an optional detail."""

    def __init__(self, message: str, status_code: int = 502, *, code: str | None = None, reason: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.reason = reason

    @property
    def fields(self) -> dict[str, str]:
        """``error_code`` and ``error_reason`` for a job record, when the error has them."""
        found = {"error_code": self.code, "error_reason": self.reason}
        return {key: value for key, value in found.items() if value}


def headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def require_key(api_key: str) -> str:
    key = str(api_key or "").strip()
    if not key:
        raise MeshyError("Configure the Meshy API key in Settings → Services first", 400, code="meshy_key_missing")
    return key


def response_message(response: Any) -> str:
    """Meshy's own explanation of an error, whichever field carries it."""
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        for key in ("message", "error"):
            value = payload.get(key)
            if isinstance(value, dict):
                value = value.get("message")
            if value:
                return str(value).strip()
    return str(getattr(response, "text", "") or "").strip()[:300]


def _status_error(response: Any, fallback: str) -> MeshyError:
    status = int(getattr(response, "status_code", 0) or 0) or 502
    message = response_message(response)
    detail = f": {message}" if message else ""
    if status == 401:
        return MeshyError(f"Meshy rejected the API key (401){detail}. Check it in Settings → Services.", status, code="meshy_invalid_key")
    if status == 402:
        return MeshyError(f"Meshy has no credits left for this task (402){detail}. Add credits at meshy.ai.", status, code="meshy_insufficient_credits")
    if status == 404:
        return MeshyError(f"Meshy does not know this task (404){detail}. API results are kept for 3 days.", status, code="meshy_task_not_found")
    if status == 422:
        return MeshyError(f"Meshy could not process the input (422){detail}", status, code="meshy_unprocessable")
    if status == 400:
        return MeshyError(f"Meshy rejected the request (400){detail}", status, code="meshy_bad_request")
    return MeshyError(message or fallback or f"HTTP {status}", status)


def _retry_after(response: Any) -> float:
    raw = (getattr(response, "headers", None) or {}).get("Retry-After")
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER_SECONDS
    return max(0.0, min(seconds, MAX_RETRY_AFTER_SECONDS))


def wait(seconds: float, cancelled: Callable[[], bool] | None) -> bool:
    """Sleep in short slices. True when ``cancelled`` turned true meanwhile."""
    left = float(seconds)
    while left > 0:
        if cancelled and cancelled():
            return True
        step = min(SLICE_SECONDS, left)
        time.sleep(step)
        left -= step
    return bool(cancelled and cancelled())


def cancelled_error() -> MeshyError:
    return MeshyError("Meshy generation cancelled", 499, code="cancelled")


class _Throttle:
    """Counts the waits one call has spent on 429 answers."""

    def __init__(self) -> None:
        self.rate_limited = 0
        self.busy_waited = 0.0
        self.busy_steps = 0

    def pause(self, response: Any) -> float:
        """Seconds to wait before trying again, or raise when the call has waited enough."""
        message = response_message(response)
        if message.startswith("NoMorePendingTasks"):
            if self.busy_waited >= BUSY_WAIT_LIMIT_SECONDS:
                raise MeshyError(
                    "Meshy has too many unfinished tasks for this plan (NoMorePendingTasks). Wait for a task to finish and try again.",
                    429, code="meshy_busy")
            pause = BUSY_PAUSES[min(self.busy_steps, len(BUSY_PAUSES) - 1)]
            self.busy_steps += 1
            self.busy_waited += pause
            return pause
        self.rate_limited += 1
        if self.rate_limited > MAX_RATE_LIMIT_RETRIES:
            raise MeshyError("Meshy rate limit exceeded (429). Try again in a minute.", 429, code="meshy_rate_limited")
        return _retry_after(response)


def call(
    method: str,
    url: str,
    api_key: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: tuple[float, float] = (15, 60),
    cancelled: Callable[[], bool] | None = None,
    fallback: str = "Meshy request failed",
    retry_reads: bool = False,
) -> dict[str, Any]:
    """One Meshy request; returns the JSON object (``{}`` for an empty answer).

    A 429 waits and tries again; other errors raise ``MeshyError`` with Meshy's own message.
    """
    kwargs: dict[str, Any] = {"headers": headers(api_key), "timeout": timeout}
    if body is not None:
        kwargs["json"] = body
    throttle, failures = _Throttle(), 0
    while True:
        try:
            response = getattr(requests, method)(url, **kwargs)
        except requests.RequestException as error:
            failures += 1
            if not retry_reads or failures > READ_RETRIES:
                raise MeshyError(f"Could not reach Meshy: {error}", 502, code="meshy_unreachable") from error
            if wait(2.0 * failures, cancelled):
                raise cancelled_error() from error
            continue
        if getattr(response, "status_code", 200) == 429:
            if wait(throttle.pause(response), cancelled):
                raise cancelled_error()
            continue
        if not response.ok:
            raise _status_error(response, fallback)
        return response.json() if response.content else {}


def task_id(payload: Any) -> str:
    if isinstance(payload, dict):
        result = payload.get("result") or payload.get("id")
        if result:
            return str(result)
    raise MeshyError("Meshy did not return a task id")


def task_facts(payload: dict[str, Any]) -> dict[str, int]:
    """``consumed_credits`` and ``expires_at`` (ms epoch) of a task, when Meshy reports them."""
    facts: dict[str, int] = {}
    for key in ("consumed_credits", "expires_at"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            facts[key] = int(value)
    return facts


def combine_facts(*tasks: dict[str, int]) -> dict[str, int]:
    """Credits add up; the earliest expiry wins."""
    credits = [task["consumed_credits"] for task in tasks if "consumed_credits" in task]
    expiries = [task["expires_at"] for task in tasks if task.get("expires_at")]
    combined: dict[str, int] = {}
    if credits:
        combined["consumed_credits"] = sum(credits)
    if expiries:
        combined["expires_at"] = min(expiries)
    return combined


def delete_task(url: str, api_key: str) -> bool:
    """Delete a task. A PENDING one is refunded; a running one answers 409 and goes on. Never raises."""
    try:
        response = requests.delete(url, headers=headers(api_key), timeout=(15, 30))
    except requests.RequestException:
        return False
    return bool(getattr(response, "ok", False))


def _failure(payload: dict[str, Any], status: str) -> MeshyError:
    error = payload.get("task_error") or {}
    message = str(error.get("message") or "").strip() if isinstance(error, dict) else str(error)
    return MeshyError(message or f"Meshy {status.lower()}", 502, reason=status.lower())


def poll_task(
    url: str,
    api_key: str,
    *,
    cancelled: Callable[[], bool] | None = None,
    on_progress: Callable[[float], None] | None = None,
    timeout_s: float = POLL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Poll ``url`` until the task ends; returns the SUCCEEDED payload.

    A cancel while the task is still PENDING deletes it, which refunds its credits. A task that is
    already running cannot be deleted, so polling just stops and Meshy finishes it on its own.
    """
    started, status = time.time(), None
    while True:
        if cancelled and cancelled():
            if status in (None, PENDING):
                delete_task(url, api_key)
            raise cancelled_error()
        payload = call("get", url, api_key, cancelled=cancelled, fallback="Meshy status request failed", retry_reads=True)
        status = str(payload.get("status") or "").upper()
        if status == SUCCEEDED:
            return payload
        if status in FAILED_STATES:
            raise _failure(payload, status)
        if on_progress and isinstance(payload.get("progress"), (int, float)):
            on_progress(max(0.0, min(100.0, float(payload["progress"]))))
        if time.time() - started > timeout_s:
            raise MeshyError("Meshy timed out waiting for the result")
        wait(POLL_SECONDS, cancelled)


def download(url: str, *, timeout: tuple[float, float] = (15, 180)) -> bytes:
    """The bytes behind a result URL (a signed link that stops working after three days)."""
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
    except Exception as error:
        raise MeshyError(f"Meshy download failed: {error}", 502, code="meshy_download_failed") from error
    return response.content
