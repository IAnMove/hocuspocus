"""Textured, rigged 3D models for a production, made once and in one batch before the frames.

``spec.models`` maps a name to ``{from, prompt, rig, animations, seed}``:

- ``from`` is a cast id (its plain portrait is used), a ``stills`` name or a picture URL; an object with no
  picture gives a ``prompt`` instead and gets one from the production's image model.
- A character (``rig: "humanoid"``, the default for a cast id) is first redrawn in a T-pose from its portrait,
  because the humanoid rig needs one; a rigged model's clips follow the song's tempo.
- ``rig`` is ``humanoid``, a procedural profile (prop, vehicle, quadruped, flying, serpentine) or ``none``.

``spec.sets`` maps a name to ``{prompt, seed}``: a painted set for a scene3d ``background``, drawn with a fixed
recipe (eye-level, an open floor across the lower third, a clear horizon, nobody in it) so the projected floor
has ground to stand on.

Every picture (sets included), then every Hunyuan3D mesh, then every rig is submitted together, so each model
loads once. A scene3d ``cast`` entry names a model, and a ``background`` a set, by its name
(``production_scene3d.resolve_media``).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from services.production_control import sleep_until

RIGS = ("humanoid", "prop", "vehicle", "quadruped", "flying", "serpentine", "none")
FIELDS = {"from", "prompt", "rig", "animations", "seed"}
HUMANOID_CLIPS = ["idle", "walk", "dance_bounce", "wave"]
PROFILE_CLIPS = {"prop": ["hover", "bounce", "spin"], "vehicle": ["bounce", "wobble"], "quadruped": ["idle", "walk", "run"],
                 "flying": ["hover", "strafe"], "serpentine": ["idle", "wobble"]}
CHARACTER_STAGING = "full body, T-pose, front view, arms horizontal, plain light grey background, no shadow"
OBJECT_STAGING = "single object, three-quarter view, plain light grey background, no shadow"
PICTURE_SIZE = "1024x1024"
SET_STAGING = ("wide eye-level view of an empty set, open floor across the lower third, clear horizon, "
               "no people, no animals, no text")
SET_SIZE = "1664x928"         # 16:9 on the 32-pixel grid the image models need
MESH_PRESET = "balanced"        # Hunyuan3D 2 Turbo geometry with Paint 2.0 Turbo texture
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_DONE = ("completed", "failed", "cancelled", "discarded", "error")


class ModelError(ValueError):
    pass


def check_sets(spec: dict) -> None:
    sets = spec.get("sets")
    if sets is None:
        return
    if not isinstance(sets, dict) or len(sets) > 12:
        raise ModelError("spec.sets maps up to 12 names to {prompt, seed}")
    for name, entry in sets.items():
        if not (isinstance(name, str) and _NAME.match(name)) or not isinstance(entry, dict) \
                or set(entry) - {"prompt", "seed"} or not _text(entry.get("prompt")):
            raise ModelError(f"sets.{name}: a lower-case name and {{prompt, seed}}")


def check_models(spec: dict) -> None:
    check_sets(spec)
    models = spec.get("models")
    if models is None:
        return
    if not isinstance(models, dict) or len(models) > 12:
        raise ModelError("spec.models maps up to 12 names to {from or prompt, rig, animations}")
    cast = _cast_ids(spec)
    for name, entry in models.items():
        _check_model(name, entry, cast)


def _check_model(name: Any, entry: Any, cast: set) -> None:
    if not (isinstance(name, str) and _NAME.match(name)) or not isinstance(entry, dict) or set(entry) - FIELDS:
        raise ModelError(f"models.{name}: a lower-case name and only {', '.join(sorted(FIELDS))}")
    if not (_text(entry.get("from")) or _text(entry.get("prompt"))):
        raise ModelError(f"models.{name}: give from (a cast id, stills name or picture URL) or a prompt")
    if rig_of(entry, cast) not in RIGS:
        raise ModelError(f"models.{name}.rig must be one of {', '.join(RIGS)}")
    clips = entry.get("animations")
    if clips is not None and (not isinstance(clips, list) or not 0 < len(clips) <= 8 or not all(_text(c) for c in clips)):
        raise ModelError(f"models.{name}.animations is a list of 1-8 clip names")


def rig_of(entry: dict, cast: set) -> str:
    return entry.get("rig") or ("humanoid" if entry.get("from") in cast else "none")


def _text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value.strip()) <= 2000


def _cast_ids(spec: dict) -> set:
    return {entry.get("id") for entry in spec.get("cast") or [] if isinstance(entry, dict)}


def _source(production: Any, spec: dict, entry: dict) -> str | None:
    """The picture a model starts from: a cast portrait (or sheet), a stills entry or a URL."""
    wanted = entry.get("from")
    if not wanted:
        return None
    for table in (production.state.get("cast_single") or {}, production.state.get("cast") or {}, spec.get("stills") or {}):
        if wanted in table:
            return table[wanted]
    if wanted.startswith(("/api/", "http://", "https://")):
        return wanted
    raise ModelError(f"models: {wanted!r} is not a cast id, a stills name or a picture URL")


def _fingerprint(entry: dict, source: str | None, spec: dict) -> str:
    look = (spec.get("style") or {}).get("image", "")
    bpm = (spec.get("song") or {}).get("bpm")
    return hashlib.sha256(json.dumps([entry, source, look, bpm], sort_keys=True).encode()).hexdigest()[:16]


def _digest(value: str) -> str:
    """Intents follow their input: a retry with a new picture or mesh is a new job, a resume replays the same one."""
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def _clips(entry: dict, rig: str) -> list[str]:
    return list(entry.get("animations") or (HUMANOID_CLIPS if rig == "humanoid" else PROFILE_CLIPS.get(rig, [])))


def _job(reply: dict) -> dict:
    result = reply.get("result") if isinstance(reply.get("result"), dict) else {}
    return result or reply


def _submit(production: Any, operation: str, intent: str, payload: dict) -> tuple[str | None, str | None]:
    """(job id, None), or (None, why it was not admitted): a refusal, a tool error or an uninstalled engine."""
    reply = production.mcp(operation, {"version": 1, "intent_id": intent, "input": {"workspace": production.ws, **payload}})
    job = None if reply.get("status") == "failed" or reply.get("_is_error") else _job(reply).get("job_id")
    if job:
        return job, None
    error = reply.get("error") if isinstance(reply.get("error"), dict) else {"message": reply.get("error") or reply}
    return None, str(error.get("message") or error)[:200]


def _await(production: Any, operation: str, jobs: dict[str, tuple[str | None, str | None]], poll: float = 5,
           sleep=time.sleep) -> dict[str, dict]:
    """Final job record per name; a job that was never admitted is reported failed with the reason."""
    done = {name: {"status": "failed", "error": f"not admitted: {why}"} for name, (job, why) in jobs.items() if not job}
    jobs = {name: job for name, (job, _why) in jobs.items()}
    unknown: dict[str, int] = {}
    while len(done) < len(jobs):
        for name, job in jobs.items():
            if name in done:
                continue
            record = _job(production.mcp(operation, {"version": 1, "input": {"workspace": production.ws, "job_id": job}}))
            if record.get("status") in _DONE:
                done[name] = record
            elif not record.get("status"):     # the queue forgot the job (a restart, or long finished): stop asking
                unknown[name] = unknown.get(name, 0) + 1
                if unknown[name] >= 5:
                    done[name] = {"status": "failed", "error": "job lost"}
        if len(done) < len(jobs):
            sleep_until(getattr(production, "_cancel", None), poll, sleep)
    return done


def _set_jobs(production: Any, spec: dict) -> dict[str, str | None]:
    """Image jobs for the sets that are missing or changed, keyed ``set:<name>``."""
    from services.production_image_defaults import image_choice
    style = spec.get("style") or {}
    made = production.state.setdefault("sets", {})
    jobs = {}
    for name, entry in (spec.get("sets") or {}).items():
        fingerprint = _fingerprint(entry, None, spec)
        if (made.get(name) or {}).get("fingerprint") == fingerprint and made[name].get("url"):
            continue
        made[name] = {"fingerprint": fingerprint}
        prompt = f"{style.get('image', '')}. {entry['prompt']}, {SET_STAGING}".lstrip(". ")
        jobs[f"set:{name}"] = production.image(f"set-{name}", prompt, None, SET_SIZE, entry.get("seed", 11),
                                               *image_choice(entry, style), production._attempt("set_attempts", name))
    return jobs


def _models_to_make(production: Any, spec: dict, made: dict) -> dict[str, tuple[dict, str | None, str]]:
    """(entry, source picture, rig) for each model that is new or changed; a resume skips the rest."""
    cast, todo = _cast_ids(spec), {}
    for name, entry in (spec.get("models") or {}).items():
        source = _source(production, spec, entry)
        fingerprint = _fingerprint(entry, source, spec)
        kept = made.get(name) or {}
        if kept.get("fingerprint") == fingerprint and kept.get("file") and not kept.get("rig_error"):
            continue
        made[name] = {"fingerprint": fingerprint}
        todo[name] = (entry, source, rig_of(entry, cast))
    return todo


def _picture_jobs(production: Any, todo: dict, style: dict) -> tuple[dict[str, str], dict[str, str | None]]:
    """Pictures already there, and image jobs for the rest: a T-pose from the portrait, or the object's prompt."""
    from services.production_image_defaults import image_choice
    look, pictures, jobs = style.get("image", ""), {}, {}
    for name, (entry, source, rig) in todo.items():
        if rig != "humanoid" and source:
            pictures[name] = source
            continue
        staged = f"The same character as the reference, {CHARACTER_STAGING}" if rig == "humanoid" else f"{entry['prompt']}, {OBJECT_STAGING}"
        jobs[name] = production.image(f"model-{name}", f"{look}. {staged}".lstrip(". "), [source] if source else None, PICTURE_SIZE,
                                      entry.get("seed", 7), *image_choice(entry, style), production._attempt("model_picture_attempts", name))
    return pictures, jobs


def _collect_pictures(production: Any, jobs: dict, made: dict, sets: dict, pictures: dict) -> None:
    for name, file in production.wait(jobs).items():
        is_set = name.startswith("set:")
        record = sets[name[4:]] if is_set else made[name]
        if not file:
            record["error"] = f"picture failed ({production.failures.get(name, 'no output')})"
        elif is_set:
            record["url"] = production.upload(file)[1]
        else:
            pictures[name] = production.upload(file)[1]
    production.save()


def _rig_request(entry: dict, rig: str, mesh: str, bpm: int) -> dict:
    engine = "humanoid" if rig == "humanoid" else "procedural"
    return {"source": mesh, "engine": engine, "animations": _clips(entry, rig), "animation_bpm": bpm,
            **({} if engine == "humanoid" else {"rig_profile": rig})}


def _meshes_and_rigs(production: Any, spec: dict, todo: dict, pictures: dict, made: dict, sleep) -> None:
    meshes = _await(production, "model3d.status", sleep=sleep, jobs={
        name: _submit(production, "model3d.generate", f"{production.id}-mesh-{name}-{_digest(picture)}",
                      {"image_path": picture, "preset": MESH_PRESET})
        for name, picture in pictures.items()})
    bpm = min(180, max(60, int((spec.get("song") or {}).get("bpm") or 120)))
    rigs = {}
    for name, record in meshes.items():
        made[name]["picture"] = pictures[name]
        if record.get("status") != "completed" or not record.get("filename"):
            made[name]["error"] = f"mesh {record.get('status')}: {str(record.get('error') or '')[:120]}"
            continue
        made[name].update(mesh=record["filename"], file=record["filename"])
        entry, _source_url, rig = todo[name]
        if rig != "none":
            rigs[name] = _submit(production, "model3d.rig", f"{production.id}-rig-{name}-{_digest(record['filename'])}",
                                 _rig_request(entry, rig, record["filename"], bpm))
    production.save()
    for name, record in _await(production, "model3d.rig.status", rigs, sleep=sleep).items():
        if record.get("status") == "completed" and record.get("filename"):
            made[name]["file"] = record["filename"]
        else:
            # The textured mesh still plays as a rigid model; a named clip on it fails at its 3D shot.
            made[name]["rig_error"] = f"{record.get('status')}: {str(record.get('error') or '')[:160]}"


def make_models(production: Any, spec: dict, *, sleep=time.sleep) -> None:
    from services.series_shot3d import glb_clip_names

    set_jobs = _set_jobs(production, spec)
    if not spec.get("models") and not set_jobs:
        return
    made = production.state.setdefault("models", {})
    sets = production.state.setdefault("sets", {})
    todo = _models_to_make(production, spec, made)
    pictures, jobs = _picture_jobs(production, todo, spec.get("style") or {})
    _collect_pictures(production, {**jobs, **set_jobs}, made, sets, pictures)
    _meshes_and_rigs(production, spec, todo, pictures, made, sleep)
    for name in todo:
        file = made[name].get("file")
        made[name]["clips"] = glb_clip_names(production.root / file) if file else []
        production.log(f"model {name}: " + (made[name].get("error") or made[name].get("rig_error")
                                            or f"{file} ({', '.join(made[name]['clips']) or 'rigid'})"))
    production.save()
    failed = [name for name in todo if made[name].get("error")] + [f"set {name[4:]}" for name in set_jobs if sets[name[4:]].get("error")]
    if failed:
        raise ModelError(f"models failed: {', '.join(failed)}")
