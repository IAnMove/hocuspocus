"""Cast sheets, start frames, and the three-prompt look test."""
from __future__ import annotations

from typing import Any

from services.production_control import arm, disarm

FRAME_ATTEMPTS = 2                                       # start-frame rounds per run
FRAME_RESOLUTIONS = ("1280x704", "1152x640", "1024x576")   # after an out-of-memory the next attempt is smaller


def _host():
    import services.music_production as host
    return host


def image(production: Any, key: str, prompt: str, refs: list[str] | None, res: str, seed: int,
          model: str = "flux2_klein_9b", steps: int | None = None, attempt: int = 0) -> str | None:
    params = {"prompt": prompt, "model_type": model, "resolution": res, "seed": seed, "guidance_scale": 1,
              "num_inference_steps": steps or (40 if model.startswith("qwen_image_21") else 4)}
    if refs:
        params.update(image_refs=refs, video_prompt_type="I")
    r = production.mcp("generation.image", {"version": 2, "intent_id": f"{production.id}-{key}-{seed}" + (f"-r{attempt}" if attempt else ""),
                                             "input": {"workspace": production.ws, "params": params}})       # the journal answers a repeated intent with the old (maybe failed) job
    return ((r.get("receipt") or {}).get("result") or {}).get("job_id")


def attempt(production: Any, group: str, key: str) -> int:
    """How many times this image was already submitted, so a resume asks for a fresh job instead of the journal's old answer."""
    counts = production.state.setdefault(group, {})
    if key not in counts:
        counts[key] = 1 if any(line.startswith(("frames:", "cast:")) for line in production.state.get("log") or []) else 0
        return counts[key]
    counts[key] += 1
    return counts[key]


def frame_prompt(production: Any, spec: dict, w: dict) -> str:
    """Start-frame prompt: the look, the shot, and how many distinct subjects the cast references stand for
    (a model given a sheet with several views tends to draw the character several times)."""
    style = (spec.get("style") or {}).get("image", "")
    counts = {c["id"]: int(c.get("count", len(c.get("group") or []) or 1)) for c in spec.get("cast") or [] if isinstance(c, dict)}
    subjects = sum(counts.get(c, 1) for c in w.get("cast", []) if c in production.state.get("cast", {}))
    guard = f" Exactly {subjects} distinct {'subject' if subjects == 1 else 'subjects'} in the frame, no duplicated characters." if subjects else ""
    return f"{style} {w['frame']}{guard}".strip()


def _member_jobs(production: Any, spec: dict) -> dict:
    cast = production.state.setdefault("cast", {})
    settings = spec.get("style") or {}
    style = settings.get("image", "")
    jobs = {}
    for member in spec.get("cast") or []:
        if member["id"] in cast or member.get("group"):
            continue
        prompt = member["sheet_prompt"] if style in member["sheet_prompt"] else f"{member['sheet_prompt']} {style}".strip()
        jobs[member["id"]] = production.image(
            "cast-" + member["id"], prompt, None, "1536x1024", member.get("seed", 5),
            member.get("image_model", settings.get("image_model", "flux2_klein_9b")),
            member.get("image_steps", settings.get("image_steps")),
            production._attempt("cast_attempts", member["id"]))
    return jobs


def _land_members(production: Any, jobs: dict) -> None:
    cast = production.state.setdefault("cast", {})
    for cid, name in production.wait(jobs).items():
        if name:
            cast[cid] = production.upload(name)[1]


def _land_groups(production: Any, spec: dict) -> None:
    from services.production_cast_portrait import group_sources
    cast = production.state.setdefault("cast", {})
    for member in spec.get("cast") or []:
        members = member.get("group") or []
        if not members or member["id"] in cast or not all(one in cast for one in members):
            continue
        out = f"{production.id}-group-{member['id']}.png"
        if _host().compose_group(group_sources(production, members), production.root / out):
            cast[member["id"]] = production.upload(out)[1]


def cast(production: Any, spec: dict) -> None:
    from services.production_cast_portrait import ensure_portraits
    _land_members(production, _member_jobs(production, spec))
    ensure_portraits(production, spec)
    _land_groups(production, spec)
    cast_state = production.state.get("cast") or {}
    production.log(f"cast: {len(cast_state)}")
    absent = [member["id"] for member in spec.get("cast") or [] if member["id"] not in cast_state]
    if absent:
        from services.music_production import ProductionError
        detail = ", ".join(f"{cid} ({production.failures.get(cid, 'no output')})" for cid in absent)
        raise ProductionError("cast_incomplete", "no reference sheet for " + detail)


def _frame_jobs(production: Any, spec: dict, missing: list, frames: dict, failures: dict) -> dict:
    from services.production_cast_portrait import frame_references
    settings = spec.get("style") or {}
    resolutions = _host().FRAME_RESOLUTIONS
    jobs = {}
    for shot in missing:
        taken = production._attempt("frame_attempts", shot["key"])
        res = resolutions[min(taken, len(resolutions) - 1)] if "memory" in failures.get(shot["key"], "") else resolutions[0]
        refs = frame_references(shot, production.state.get("cast") or {}, production.state.get("cast_single") or {})
        jobs[shot["key"]] = production.image(
            "frame-" + shot["key"], production.frame_prompt(spec, shot), refs or None, res,
            shot.get("seed", 3) + (taken or 0),
            shot.get("image_model", settings.get("image_model", "flux2_klein_9b")),
            shot.get("image_steps", settings.get("image_steps")), taken)
    return jobs


def _land_frames(production: Any, jobs: dict, frames: dict, failures: dict) -> None:
    for key, name in production.wait(jobs).items():
        if name:
            frames[key] = name
            failures.pop(key, None)
            continue
        failures[key] = production.failures.get(key, "no output")
        production.log(f"frame {key} failed ({failures[key]})")
    production.save()


def frames(production: Any, spec: dict, windows: list[dict]) -> None:
    """One start frame per H3 shot. A missing frame is asked for again (new job; a smaller picture after an
    out-of-memory) up to FRAME_ATTEMPTS times; what still fails is reported in ``frame_failures``."""
    frames_state = production.state.setdefault("frames", {})
    failures = production.state.setdefault("frame_failures", {})
    for _round in range(_host().FRAME_ATTEMPTS):
        missing = [shot for shot in windows if shot["kind"] == "h3" and shot["key"] not in frames_state]
        if not missing:
            break
        jobs = _frame_jobs(production, spec, missing, frames_state, failures)
        _land_frames(production, jobs, frames_state, failures)
    production.log(f"frames: {len(frames_state)}")
    production.state["frames_sheet"] = _host().make_frames_sheet(production.root, frames_state, f"{production.id}-frames.jpg")
    from services.production_subject_count import note_media
    note_media(production, spec, windows, "frame")
    absent = [shot["key"] for shot in windows if shot["kind"] == "h3" and shot["key"] not in frames_state]
    if absent:
        from services.music_production import ProductionError
        detail = ", ".join(f"{key} ({failures.get(key, 'no output')})" for key in absent[:6])
        raise ProductionError("frames_incomplete", "no start frame for " + detail)


def preview(production: Any, request: dict) -> None:
    """Generate three look tests before committing GPU time to a song or clips."""
    production._cancel = arm(production.ws, production.id)
    production.state.update(status="running", preview_frames={})
    production.save()
    try:
        model = request.get("image_model", "flux2_klein_9b")
        seeds = request.get("seeds") or [101, 102, 103]
        jobs = {}
        for index, prompt in enumerate(request["prompts"]):
            jobs[str(index)] = production.image(
                f"preview-{index}", prompt, None, request.get("resolution", "1280x704"),
                seeds[index], model, request.get("image_steps"))
        production.state["preview_frames"] = {key: production.upload(name)[1] for key, name in production.wait(jobs).items() if name}
        production.state["status"] = "preview_completed" if len(production.state["preview_frames"]) == 3 else "failed"
        production.log(f"preview: {len(production.state['preview_frames'])}/3")
    except Exception as error:
        production.note_stop(error)
    disarm(production.ws, production.id)
    production.state["finished"] = _host().time.time()
    production.save()
