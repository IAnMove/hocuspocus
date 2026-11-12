"""Why WanGP skipped a task.

``wgp.validate_task`` answers ``None`` for a task it refuses and says why only through ``gr.Info`` (its
``validate_settings`` calls it for every complaint, and for a few harmless hints too). A ``gr.Info`` call outside a
browser session just logs, so the worker never knew the reason. This module taps ``gr.Info`` once, forwarding every
call to the original, and records what the validating thread says while a recorder is open. Other threads are never
recorded. The last notice before the ``None`` is the complaint (hints come first, ``return None`` follows the error).
"""
from __future__ import annotations

import contextlib
import threading

_recorder = threading.local()
_install_lock = threading.Lock()


def _install_tap(gr) -> None:
    """Wrap ``gr.Info`` once; a second call, or a fake without ``Info``, changes nothing."""
    with _install_lock:
        original = getattr(gr, "Info", None)
        if original is None or getattr(original, "_validation_notice_tap", False):
            return

        def tapped(message=None, *args, **kwargs):
            sink = getattr(_recorder, "sink", None)
            if sink is not None and message is not None:
                sink.append(str(message))
            return original(message, *args, **kwargs)

        tapped._validation_notice_tap = True
        gr.Info = tapped


@contextlib.contextmanager
def recorded_notices(wgp):
    """Yield the list that collects what ``gr.Info`` says on this thread inside the block."""
    notices: list[str] = []
    gr = getattr(wgp, "gr", None)
    if gr is None:
        yield notices
        return
    _install_tap(gr)
    previous = getattr(_recorder, "sink", None)
    _recorder.sink = notices
    try:
        yield notices
    finally:
        _recorder.sink = previous


def skip_reason(notices: list[str]) -> str:
    """WanGP's reason for one skipped task; a refusal that printed instead of notifying has none to give."""
    for notice in reversed(notices):
        if notice.strip():
            return notice.strip()
    return ""


def all_skipped_error(reasons: list[str]) -> str:
    """The job error when every task was skipped: the reason itself for one task, a short list for several."""
    given = list(dict.fromkeys(reason for reason in reasons if reason))
    if len(reasons) == 1:
        return given[0] if given else "WanGP rejected the task settings during validation (it gave no reason)."
    detail = "; ".join(given) if given else "it gave no reason"
    return f"WanGP skipped all {len(reasons)} tasks during validation: {detail}"
