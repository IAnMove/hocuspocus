"""Native and legacy H3 release when the generation queue allows it.

``_cancel_h3_idle_release`` and ``_release_h3_when_queue_allows`` keep the
idle timer on ``_h3_idle_release``. That timer used to be a module global
rebound with ``global``. The lock on the holder is the one RLock launch
exports as ``_h3_idle_release_lock``. The legacy release and the Wan
interrupt moved without a body edit. The full server calls ``bind`` once,
where these functions used to be defined.
"""
import threading

from services import minimax_h3_service

# Injected by bind(); None until the full server binds them.
_active_gen_states = None
_is_legacy_h3_model = None
_is_minimax_h3_model = None
_pending_gpu_jobs = None
wgp = None


def bind(**names):
    """Take the full server's objects these functions use."""
    global _active_gen_states, _is_legacy_h3_model, _is_minimax_h3_model, _pending_gpu_jobs, wgp
    _active_gen_states = names["_active_gen_states"]
    _is_legacy_h3_model = names["_is_legacy_h3_model"]
    _is_minimax_h3_model = names["_is_minimax_h3_model"]
    _pending_gpu_jobs = names["_pending_gpu_jobs"]
    wgp = names["wgp"]


class H3IdleRelease:
    """The one idle-release timer and the lock that guards it."""

    def __init__(self) -> None:
        self.timer = None
        self.lock = threading.RLock()


_h3_idle_release = H3IdleRelease()
_H3_IDLE_RELEASE_SECONDS = 10.0


def _cancel_h3_idle_release() -> None:
    """Prevent a delayed native-model release from racing newly queued work."""
    with _h3_idle_release.lock:
        timer = _h3_idle_release.timer
        _h3_idle_release.timer = None
        if timer is not None:
            timer.cancel()

def _release_h3_when_queue_allows(job_id: str) -> None:
    """Keep native H3 warm for its queue, then release WGP-owned memory."""
    pending = _pending_gpu_jobs(exclude_job_id=job_id)
    h3_pending = any(
        _is_minimax_h3_model(candidate.get("params", {}).get("model_type"))
        and not _is_legacy_h3_model(candidate.get("params", {}).get("model_type"))
        for candidate in pending
    )
    if h3_pending:
        _cancel_h3_idle_release()
        print("[MiniMax H3] Keeping runtime warm for a queued H3 job.")
        return

    _cancel_h3_idle_release()
    if pending:
        print("[MiniMax H3] Releasing native runtime for a queued non-H3 GPU job.")
        wgp.release_model()
        return

    print(
        f"[MiniMax H3] Queue idle; releasing native runtime in "
        f"{int(_H3_IDLE_RELEASE_SECONDS)}s unless another job arrives."
    )

    def _release_if_still_idle() -> None:
        with _h3_idle_release.lock:
            _h3_idle_release.timer = None
            if _pending_gpu_jobs(exclude_job_id=job_id) or _active_gen_states:
                return
            if not _is_minimax_h3_model(getattr(wgp, "transformer_type", None)):
                return
            wgp.release_model()
            print("[MiniMax H3] Native WGP runtime released after idle grace period.")

    with _h3_idle_release.lock:
        timer = threading.Timer(_H3_IDLE_RELEASE_SECONDS, _release_if_still_idle)
        timer.daemon = True
        _h3_idle_release.timer = timer
        timer.start()

def _release_legacy_h3_when_queue_allows(job_id: str) -> None:
    """Keep the isolated ConvRot runtime only for adjacent Legacy jobs."""
    pending = _pending_gpu_jobs(exclude_job_id=job_id)
    legacy_pending = any(
        _is_legacy_h3_model(candidate.get("params", {}).get("model_type"))
        for candidate in pending
    )
    if legacy_pending:
        minimax_h3_service.cancel_idle_shutdown()
        print("[H3 Legacy] Keeping ConvRot runtime warm for a queued Legacy job.")
        return

    if pending:
        print("[H3 Legacy] Releasing ConvRot runtime for a queued non-Legacy GPU job.")
        minimax_h3_service.stop_runtime()
        return

    print(
        f"[H3 Legacy] Queue idle; releasing ConvRot runtime in "
        f"{int(minimax_h3_service.DEFAULT_IDLE_SHUTDOWN_SECONDS)}s."
    )
    minimax_h3_service.schedule_idle_shutdown(
        minimax_h3_service.DEFAULT_IDLE_SHUTDOWN_SECONDS,
        lambda: any(
            _is_legacy_h3_model(candidate.get("params", {}).get("model_type"))
            for candidate in _pending_gpu_jobs(exclude_job_id=job_id)
        ),
    )

def _interrupt_wan_model() -> None:
    """Interrupt only the Wan run bound to the active lifecycle state."""
    model = wgp.wan_model
    if model is not None and hasattr(model, "_interrupt"):
        model._interrupt = True
