"""Production JSON on disk: one atomic replace, and log lines coalesced.

``log`` updates memory immediately and rewrites the file at most once every
two seconds. A status save still writes at once, so ``wait_for_status`` sees
the new status. The file is always a complete JSON object (write temp, then
replace); a skipped log does not leave a partial file.
"""
from __future__ import annotations

import json
import time
from typing import Any

SAVE_EVERY_S = 2.0


def save(production: Any, *, force: bool = False) -> None:
    """Write ``production.state``. Log bursts inside ``SAVE_EVERY_S`` coalesce."""
    now = time.monotonic()
    last = getattr(production, "_saved_at", None)
    coalescing = getattr(production, "_log_debounce", False)
    if coalescing and not force and last is not None and now - last < SAVE_EVERY_S:
        production._save_dirty = True
        production._log_debounce = False
        return
    _write(production)
    production._saved_at = now
    production._save_dirty = False
    production._log_debounce = False


def log(production: Any, line: str) -> None:
    production.state.setdefault("log", []).append(line[:200])
    production.state["log"] = production.state["log"][-60:]
    production._log_debounce = True
    production.save()


def note_stop(production: Any, error: BaseException) -> None:
    """A cooperative cancel stays resumable. Anything else is a failed run with its reason."""
    from services.production_control import Cancelled

    if isinstance(error, Cancelled):
        production.state.update(status="cancelled", error=None)
        return
    production.state.update(status="failed", error=f"{type(error).__name__}: {error}"[:300])


def failure_reason(status: dict) -> str:
    """One short line for the log and production.status: an OOM, the job error, or what the status said."""
    if status.get("oom_info"):
        return "out of GPU memory"
    error = status.get("error")
    if isinstance(error, dict):
        error = error.get("message") or error.get("text") or json.dumps(error)
    text = str(error or status.get("message") or status.get("status") or "no output")
    return " ".join(text.split())[:120]


def note_held(state: dict, key: str, hold: bool = True) -> None:
    """Record or clear a shot whose scene plays its start frame instead of a clip."""
    if hold:
        held = state.setdefault("held", [])
        if key not in held:
            held.append(key)
        return
    held = state.get("held")
    if held and key in held:
        held.remove(key)


def _write(production: Any) -> None:
    tmp = production.path.with_suffix(".tmp")
    tmp.write_text(json.dumps(production.state, ensure_ascii=False))
    tmp.replace(production.path)
