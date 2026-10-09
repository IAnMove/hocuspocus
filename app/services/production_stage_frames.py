"""Cast sheets, start frames and the three-prompt look preview.

``Production`` keeps the methods. ``compose_group``, ``make_frames_sheet`` and
``FRAME_ATTEMPTS`` are read from ``music_production`` at call time: tests patch
those names there.
"""
from __future__ import annotations

from typing import Any

from services.production_image_defaults import default_image_model, image_choice


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
    (a model given a sheet with several views tends to draw the character several times)."""
    style = (spec.get("style") or {}).get("image", "")
    counts = {c["id"]: int(c.get("count", len(c.get("group") or []) or 1)) for c in spec.get("cast") or [] if isinstance(c, dict)}
    subjects = sum(counts.get(c, 1) for c in window.get("cast", []) if c in production.state.get("cast", {}))
    guard = f" Exactly {subjects} distinct {'subject' if subjects == 1 else 'subjects'} in the frame, no duplicated characters." if subjects else ""
    return f"{style} {window['frame']}{guard}".strip()


def cast_sheets(production: Any, spec: dict) -> None:
    host = _host()
    cast = production.state.setdefault("cast", {})
    settings = spec.get("style") or {}
    style = settings.get("image", "")
    jobs = {c["id"]: production.image("cast-" + c["id"], c["sheet_prompt"] if style in c["sheet_prompt"] else f"{c['sheet_prompt']} {style}".strip(), None, "1536x1024", c.get("seed", 5),
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
    """An H3 shot whose spec changed is shot again: a new frame prompt drops its frame and its clip, a new action,
    camera or singing only its clip. A shot seen for the first time (or made before this was recorded) keeps what
    it has."""
    import hashlib
    import json

    def digest(*parts: Any) -> str:
        return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]

    sources = production.state.setdefault("h3_sources", {})
    frames, clips = production.state.setdefault("frames", {}), production.state.setdefault("clips", {})
    for window in windows:
        if window["kind"] != "h3":
            continue
        key = window["key"]
        frame = digest(production.frame_prompt(spec, window), window.get("seed"), sorted(window.get("cast") or []))
        clip = digest(frame, window.get("action"), window.get("camera"), bool(window.get("sing")))
        known = sources.get(key) or {"frame": frame, "clip": clip}
        if known["frame"] != frame and frames.pop(key, None):
            production.log(f"frame {key}: the shot's picture changed, drawing it again")
        if known["clip"] != clip and isinstance(clips.get(key), dict):
            clips[key]["obsolete"] = True
            production.log(f"clip {key}: the shot changed, shooting it again")
        sources[key] = {"frame": frame, "clip": clip}


def shoot_frames(production: Any, spec: dict, windows: list[dict]) -> None:
    """One start frame per H3 shot. A missing frame is asked for again (new job; a smaller picture after an
    out-of-memory) up to FRAME_ATTEMPTS times; what still fails is reported in ``frame_failures``."""
    host = _host()
    windows = production._unlocked(windows)
    forget_changed_shots(production, spec, windows)
    frames = production.state.setdefault("frames", {})
    failures = production.state.setdefault("frame_failures", {})
    settings = spec.get("style") or {}
    for _round in range(host.FRAME_ATTEMPTS):
        missing = [w for w in windows if w["kind"] == "h3" and w["key"] not in frames]
        if not missing:
            break
        from services.production_cast_portrait import frame_references
        from services.production_resolution import frame_resolution
        jobs = {}
        for w in missing:
            attempt = production._attempt("frame_attempts", w["key"])
            res = frame_resolution(spec, attempt, failures.get(w["key"], ""))
            refs = frame_references(w, production.state.get("cast") or {}, production.state.get("cast_single") or {})
            jobs[w["key"]] = production.image("frame-" + w["key"], production.frame_prompt(spec, w), refs or None, res, w.get("seed", 3) + (attempt or 0),
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
    absent = [w["key"] for w in windows if w["kind"] == "h3" and w["key"] not in frames]
    if absent:
        raise host.ProductionError("frames_incomplete", "no start frame for " + ", ".join(f"{key} ({failures.get(key, 'no output')})" for key in absent[:6]))


def run_preview(production: Any, request: dict) -> None:
    """Generate three look tests before committing GPU time to a song or clips."""
    from services.production_control import arm, disarm
    from services.production_stage_run import adopt_prepared_identity
    production._cancel = arm(production.ws, production.id)
    adopt_prepared_identity(production)
    production.state.update(status="running", preview_frames={})
    production.save()
    try:
        model = request.get("image_model") or default_image_model()     # the look test uses the model the run will use
        jobs = {str(index): production.image(f"preview-{index}", prompt, None, request.get("resolution", "1280x704"),
                                       (request.get("seeds") or [101, 102, 103])[index], model,
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
