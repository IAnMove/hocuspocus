"""Cast sheets, start frames and the three-prompt look preview.

``Production`` keeps the methods. ``compose_group``, ``make_frames_sheet`` and
``FRAME_ATTEMPTS`` are read from ``music_production`` at call time: tests patch
those names there.
"""
from __future__ import annotations

from typing import Any

from services.production_image_defaults import default_image_model, image_choice
from services.production_seeds import default_seed, ensure_seed_base, window_seed
from services.production_shot_sources import learn_window, recipe_parts, stale_reasons
from services.production_song_switch import EDIT
from services.production_takes import obsolete_clip


def _host():
    import services.music_production as host
    return host


def attempt_image(production: Any, group: str, key: str) -> int:
    """How many times this image was already submitted, so a resume asks for a fresh job instead of the journal's old answer."""
    counts = production.state.setdefault(group, {})
    if key not in counts:
        counts[key] = 1 if any(line.startswith(("frames:", "cast:")) for line in production.state.get("log") or []) else 0
        return counts[key]
    counts[key] += 1
    return counts[key]


def frame_prompt(production: Any, spec: dict, window: dict) -> str:
    """Start-frame prompt: the look, the shot, and how many distinct subjects the cast references stand for
    (a model given a sheet with several views tends to draw the character several times). A scene2d shot draws an
    empty set: its card puts the cast in it as cutouts."""
    if window.get("kind") == "scene2d":
        from services.production_scene2d import plate_prompt
        return plate_prompt(spec, window)
    style = (spec.get("style") or {}).get("image", "")
    counts = {c["id"]: int(c.get("count", len(c.get("group") or []) or 1)) for c in spec.get("cast") or [] if isinstance(c, dict)}
    subjects = sum(counts.get(c, 1) for c in window.get("cast", []) if c in production.state.get("cast", {}))
    guard = f" Exactly {subjects} distinct {'subject' if subjects == 1 else 'subjects'} in the frame, no duplicated characters." if subjects else ""
    return f"{style} {window['frame']}{guard}".strip()


def _digest(*parts: Any) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _cast_source(entry: dict, style: dict) -> str:
    """What a resume compares to decide the sheet or portrait is still the one this spec asked for."""
    if entry.get("group"):
        return _digest("group", list(entry.get("group") or []))
    return _digest(entry.get("sheet_prompt"), entry.get("single_prompt"), entry.get("seed"),
                   image_choice(entry, style), style.get("image"))


def forget_changed_cast(production: Any, spec: dict) -> set[str]:
    """A cast member whose look changed is drawn again. A member seen for the first time
    (or made before this was recorded) keeps what it has."""
    sources = production.state.setdefault("cast_sources", {})
    cast = production.state.setdefault("cast", {})
    singles = production.state.setdefault("cast_single", {})
    cutouts = production.state.get("cast_cutouts") if isinstance(production.state.get("cast_cutouts"), dict) else {}
    style = spec.get("style") or {}
    dirty: set[str] = set()
    for entry in spec.get("cast") or []:
        if not isinstance(entry, dict):
            continue
        cid = entry.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        current = _cast_source(entry, style)
        known = sources.get(cid)
        sources[cid] = current
        if known is None or known == current:
            continue
        cast.pop(cid, None)
        singles.pop(cid, None)
        cutouts.pop(cid, None)
        dirty.add(cid)
        production.log(f"cast {cid}: the look changed, drawing it again")
    for entry in spec.get("cast") or []:      # a group plate is the members' portraits; remake it when one of them moved
        if not isinstance(entry, dict):
            continue
        cid, members = entry.get("id"), entry.get("group") or []
        if members and cid in cast and any(member in dirty for member in members):
            cast.pop(cid, None)
            dirty.add(cid)
            production.log(f"cast {cid}: a member's look changed, composing the group again")
    pending = dirty | set(production.state.get("cast_dirty") or ())
    if pending:
        production.state["cast_dirty"] = sorted(pending)
    else:
        production.state.pop("cast_dirty", None)
    return dirty


def forget_shots_using_cast(production: Any, windows: list[dict]) -> None:
    """H3 shots that still show a remade character are drawn and shot again."""
    dirty = set(production.state.pop("cast_dirty", ()) or ())
    if not dirty:
        return
    frames, clips = production.state.setdefault("frames", {}), production.state.setdefault("clips", {})
    for window in windows:
        if window.get("kind") != "h3" or not any(cid in dirty for cid in (window.get("cast") or [])):
            continue
        key = window["key"]
        if frames.pop(key, None):
            production.log(f"frame {key}: the cast look changed, drawing it again")
        if isinstance(clips.get(key), dict):
            clips[key].update(obsolete=True, obsolete_by=EDIT)
            production.log(f"clip {key}: the cast look changed, shooting it again")


def cast_sheets(production: Any, spec: dict) -> None:
    host = _host()
    forget_changed_cast(production, spec)
    cast = production.state.setdefault("cast", {})
    settings = spec.get("style") or {}
    style = settings.get("image", "")
    jobs = {c["id"]: production.image("cast-" + c["id"], c["sheet_prompt"] if style in c["sheet_prompt"] else f"{c['sheet_prompt']} {style}".strip(), None, "1536x1024", c.get("seed", default_seed(production, 5)),
                                 *image_choice(c, settings), production._attempt("cast_attempts", c["id"]))
            for c in spec.get("cast") or [] if c["id"] not in cast and not c.get("group")}
    for cid, name in production.wait(jobs).items():
        if name:
            cast[cid] = production.upload(name)[1]
    from services.production_cast_portrait import ensure_portraits, group_sources
    ensure_portraits(production, spec)
    for c in spec.get("cast") or []:      # a group reference: the members' portraits side by side in one picture
        members = c.get("group") or []
        if members and c["id"] not in cast and all(member in cast for member in members):
            out = f"{production.id}-group-{c['id']}.png"
            if host.compose_group(group_sources(production, members), production.root / out):
                cast[c["id"]] = production.upload(out)[1]
    production.log(f"cast: {len(cast)}")
    absent = [c["id"] for c in spec.get("cast") or [] if c["id"] not in cast]
    if absent:
        raise host.ProductionError("cast_incomplete", "no reference sheet for " + ", ".join(f"{cid} ({production.failures.get(cid, 'no output')})" for cid in absent))


def forget_changed_shots(production: Any, spec: dict, windows: list[dict]) -> None:
    """An H3 shot whose spec changed is shot again: a new frame prompt, image model or start-frame size drops its frame
    and its clip, a new action, camera, singing, video look, clip size or an audio window that moved more than 0.3 s
    only its clip (a scene2d background is redrawn the same way). A shot seen for the first time (or made before an
    input was recorded) keeps what it has: see production_shot_sources."""
    sources = production.state.setdefault("h3_sources", {})
    frames, clips = production.state.setdefault("frames", {}), production.state.setdefault("clips", {})
    for window in windows:
        if not _draws_frame(window):
            continue
        key = window["key"]
        frame = _digest(production.frame_prompt(spec, window), window.get("seed"), sorted(window.get("cast") or []))
        clip = _digest(frame, window.get("action"), window.get("camera"), bool(window.get("sing")))
        known = sources.get(key) or {"frame": frame, "clip": clip}
        now = {"frame": frame, "clip": clip, "parts": recipe_parts(spec, window)}
        draw_why, shoot_why = stale_reasons(known, now, window, clips.get(key))
        if draw_why and frames.pop(key, None):
            production.log(f"frame {key}: {draw_why}, drawing it again")
        if shoot_why and isinstance(clips.get(key), dict):
            if not obsolete_clip(clips[key]):
                production.log(f"clip {key}: {shoot_why}, shooting it again")
            clips[key].update(obsolete=True, obsolete_by=EDIT)
        sources[key] = now
        learn_window(clips.get(key), window)


def _draws_frame(window: dict) -> bool:
    from services.production_scene2d import draws_frame
    return window["kind"] == "h3" or draws_frame(window)


def shoot_frames(production: Any, spec: dict, windows: list[dict]) -> None:
    """One start frame per H3 shot, and the background of a scene2d shot that draws one. A missing frame is asked for
    again (new job; a smaller picture after an out-of-memory) up to FRAME_ATTEMPTS times; what still fails is reported
    in ``frame_failures``."""
    host = _host()
    windows = production._unlocked(windows)
    forget_changed_shots(production, spec, windows)
    forget_shots_using_cast(production, windows)
    frames = production.state.setdefault("frames", {})
    failures = production.state.setdefault("frame_failures", {})
    settings = spec.get("style") or {}
    for _round in range(host.FRAME_ATTEMPTS):
        missing = [w for w in windows if _draws_frame(w) and w["key"] not in frames]
        if not missing:
            break
        from services.production_cast_portrait import frame_references
        from services.production_resolution import frame_resolution
        jobs = {}
        for w in missing:
            attempt = production._attempt("frame_attempts", w["key"])
            res = frame_resolution(spec, attempt, failures.get(w["key"], ""))
            refs = frame_references(w, production.state.get("cast") or {}, production.state.get("cast_single") or {})
            jobs[w["key"]] = production.image("frame-" + w["key"], production.frame_prompt(spec, w), refs or None, res, w.get("seed", window_seed(production, 3, int(w.get("i") or 0))) + (attempt or 0),
                                        *image_choice(w, settings), attempt)
        for key, name in production.wait(jobs).items():
            if name:
                frames[key] = name
                failures.pop(key, None)
            else:
                failures[key] = production.failures.get(key, "no output")
                production.log(f"frame {key} failed ({failures[key]})")
        production.save()
    production.log(f"frames: {len(frames)}")
    production.state["frames_sheet"] = host.make_frames_sheet(production.root, frames, f"{production.id}-frames.jpg")
    from services.production_subject_count import note_media
    note_media(production, spec, windows, "frame")
    absent = [w["key"] for w in windows if _draws_frame(w) and w["key"] not in frames]
    if absent:
        raise host.ProductionError("frames_incomplete", "no start frame for " + ", ".join(f"{key} ({failures.get(key, 'no output')})" for key in absent[:6]))


def run_preview(production: Any, request: dict) -> None:
    """Generate three look tests before committing GPU time to a song or clips."""
    from services.production_control import arm, disarm
    from services.production_stage_run import adopt_prepared_identity
    production._cancel = arm(production.ws, production.id)
    adopt_prepared_identity(production)
    ensure_seed_base(production.state)
    production.state.update(status="running", preview_frames={})
    production.save()
    try:
        model = request.get("image_model") or default_image_model()     # the look test uses the model the run will use
        jobs = {str(index): production.image(f"preview-{index}", prompt, None, request.get("resolution", "1280x704"),
                                       (request.get("seeds") or [default_seed(production, offset) for offset in (101, 102, 103)])[index], model,
                                       request.get("image_steps"))
                for index, prompt in enumerate(request["prompts"])}
        production.state["preview_frames"] = {key: production.upload(name)[1] for key, name in production.wait(jobs).items() if name}
        production.state["status"] = "preview_completed" if len(production.state["preview_frames"]) == 3 else "failed"
        production.log(f"preview: {len(production.state['preview_frames'])}/3")
    except Exception as error:
        production.note_stop(error)
    disarm(production.ws, production.id)
    production.state["finished"] = _host().time.time()
    production.save()
