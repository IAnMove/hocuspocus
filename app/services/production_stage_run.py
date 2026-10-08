"""One production.run. The stage methods stay on Production so a resume calls the same code."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.production_control import Cancelled, arm, checkpoint, disarm
from services.production_disk import release_completed, release_uploads

_IDENTITY_KEYS = ("project", "intent_id", "origin", "format")


def _host():
    import services.music_production as host
    return host


def adopt_prepared_identity(production: Any) -> None:
    """Copy link identity from the stub written before this worker started.

    ``Production`` is constructed before ``bind_producer`` writes
    ``{id}.production.json``. The first ``save()`` would otherwise replace that
    file and drop ``project`` / ``intent_id`` / ``origin``.
    """
    path = getattr(production, "path", None)
    state = getattr(production, "state", None)
    if path is None or not isinstance(state, dict):
        return
    try:
        disk = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if not isinstance(disk, dict):
        return
    for key in _IDENTITY_KEYS:
        if key not in state and key in disk:
            state[key] = disk[key]


def execute_run(production: Any, spec: dict, retake: tuple[str, ...] = (), through: str = "all") -> None:
    host = _host()
    from services.production_shot_review import assert_obsolete_unlocked, assert_retake_unlocked
    assert_retake_unlocked(production, retake)
    assert_obsolete_unlocked(production)
    production._cancel = arm(production.ws, production.id)
    prior_status = production.state.get("status")
    from services.production_preview import keep_completed_cut, remember_completed_cut
    remember_completed_cut(production.state, prior_status, through)
    adopt_prepared_identity(production)
    production.state.update(spec=spec, status="running", started=production.state.get("started") or host.time.time(), through=through)
    from services.production_close import note_resume
    note_resume(production)
    production.save()
    try:
        checkpoint(production._cancel)
        from services.production_preview import log_title_cards
        log_title_cards(production, spec)
        watch = host.StageWatch(production)
        watch.call("song", production.song, spec)
        watch.call("analyze", production.analyze, spec)
        watch.call("cast", production.cast, spec)
        if spec.get("models"):
            from services.production_models import make_models
            watch.call("models", make_models, production, spec)
        windows = host.shot_windows(spec, production.score())
        watch.call("frames", production.frames, spec, windows)
        if through == "frames":
            production.state["status"] = "frames_ready"
            production.log("frames: ready for a clean restart before clips")
            return
        if through == "animatic":
            try:
                production.animatic(spec, windows)
            except Exception as error:
                if isinstance(error, Cancelled) or not keep_completed_cut(production.state, prior_status):
                    raise
                production.log(f"animatic failed: {type(error).__name__}: {error}"[:200])
            if keep_completed_cut(production.state, prior_status):
                production.state.update(status="completed", error=None)
            elif production.state.get("status") != "failed":
                production.state["status"] = "animatic_ready"
                production.log("animatic: ready; a resume continues with clips")
            return
        watch.call("clips", production.clips, spec, windows, retake)
        if any(shot.get("kind") == "scene3d" for shot in [*spec["shots"], *(spec.get("fill") or [])]):
            watch.call("clips", host.export_scene3d_clips, production, spec, windows, retake)
        from services.production_enhance import enhance_clips
        enhance_clips(production, spec)
        watch.call("scenes", production.scenes, spec, windows)
        try:
            production.package(spec, windows)
        except Exception as error:      # the video is made; editability is a bonus that must not fail the run
            production.log(f"package failed: {type(error).__name__}: {error}"[:200])
        watch.call("montage", production.montage, spec)
        production.state["package"] = {**(production.state.get("package") or {}), "montage": production.state.get("montage_file")}
        # A leftover final from a previous completed run is not success: scene
        # export can fail, skip montage, and still leave that filename in state.
        if production.state.get("status") != "failed" and production.state.get("final"):
            production.state.update(status="completed", error=None)
        elif production.state.get("status") != "failed":
            production.state["status"] = "failed"
    except Exception as error:  # the run is resumable; a cancel keeps the files and the spec
        production.note_stop(error)
    finally:
        disarm(production.ws, production.id)
        production.state["finished"] = host.time.time()
        from services.production_close import close_run
        close_run(production, retake)
        release_completed(production.root, production.state, production.id)
        release_uploads(production.uploads, production.state)
        production.save()
