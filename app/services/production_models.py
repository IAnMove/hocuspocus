"""Textured, rigged 3D models for a production, made once and in one batch before the frames.

``spec.models`` maps a name to ``{from, prompt, rig, animations, seed}``:

- ``from`` is a cast id (its plain portrait is used), a ``stills`` name or a picture URL; an object with no
  picture gives a ``prompt`` instead and gets one from the production's image model.
- A character (``rig: "humanoid"``, the default for a cast id) is first redrawn in a T-pose from its portrait,
  because the humanoid rig needs one; a rigged model's clips follow the song's tempo.
- ``rig`` is ``humanoid``, a procedural profile (prop, vehicle, quadruped, flying, serpentine) or ``none``.
- ``glb`` is a model already in the workspace (a file name): it skips the picture and the mesh and is only rigged.
  ``fallback`` is the procedural profile a humanoid rig falls back to when the body is not one it can rig
  (legs together, arms down, a tail).

``height`` (metres) is the model's real size in a scene; without it every model stands 1.7 m tall. It does not
remake the model.

``spec.sets`` maps a name to ``{prompt, seed}``: a painted set for a scene3d ``background``, drawn with a fixed
recipe (eye-level, an open floor across the lower third, a clear horizon, nobody in it) so the projected floor
has ground to stand on. ``{kind: "diorama", ...}`` is a set built in 3D instead (``production_diorama``).

Every picture (sets included), then every Hunyuan3D mesh, then every rig is submitted together, so each model
loads once. A scene3d ``cast`` entry names a model, and a ``background`` a set, by its name
(``production_scene3d.resolve_media``).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Callable

from services.glb_cleanup import CLEANUP as GLB_CLEANUP
from services.production_control import sleep_until
from services.production_diorama import (
    build as build_diorama, check_diorama, is_built, is_diorama, picture_jobs as diorama_jobs, recipe as diorama_recipe,
)

RIGS = ("humanoid", "prop", "vehicle", "quadruped", "flying", "serpentine", "none")
FIELDS = {"from", "prompt", "glb", "rig", "fallback", "animations", "seed", "height"}
HUMANOID_CLIPS = ["idle", "walk", "dance_bounce", "wave"]
PROFILE_CLIPS = {"prop": ["hover", "bounce", "spin", "wobble"], "vehicle": ["bounce", "wobble"], "quadruped": ["idle", "walk", "run"],
                 "flying": ["hover", "strafe"], "serpentine": ["idle", "wobble"]}
# Pictures for Hunyuan3D are isolated: a busy background gets meshed into the model. The reference portrait
# already carries the look, so a character's T-pose prompt is only the staging.
# The humanoid rig needs legs: a robe or gown down to the ground failed it ("not_humanoid ... hidden by a robe").
CHARACTER_STAGING = ("The same character as the reference, full body, T-pose, front view, arms horizontal, legs slightly apart "
                     "with both legs and feet clearly visible (a long robe, gown or cloak ends above the knees), isolated on a "
                     "plain light grey studio background, nothing else in the picture, no shadow")
OBJECT_STAGING = "single object, three-quarter view, isolated on a plain light grey studio background, nothing else in the picture, no shadow"
# A cast portrait often stands the figure on a base or in its scenery (a diorama style draws little houses under
# it). Hunyuan3D meshes all of that, so a model that is not a humanoid is redrawn alone from its picture too.
# Worded as an edit: told to draw "the same subject alone", the image model kept the base of the reference picture;
# told to keep only the subject and remove the base, it did.
REFERENCE_STAGING = ("Keep only the main character or object from the reference picture: remove the base, stand, pedestal, "
                     "ground and any scenery under or around it. Show it alone and whole, standing directly on a plain light "
                     "grey studio background, three-quarter view, nothing else in the picture, no shadow")
PICTURE_SIZE = "1024x1024"
# A set must leave the cast room and company to nobody: figures painted into it stand where the cast stands
# and stretch across the projected floor. The rule goes first and last, and the look loses its sentences about people.
SET_LEAD = "An EMPTY set with nobody in it, ready for actors to step in:"
SET_STAGING = ("wide eye-level view, a large open EMPTY floor across the foreground and lower third where actors can stand, "
               "the scenery behind it, clear horizon, no people, no figurines, no dolls, no characters, no animals, no text")
RECIPE = 2                      # the picture recipes above; a change remakes pictures, meshes and sets
_PEOPLE = re.compile(r"\b(characters?|figurines?|figures?|people|persons?|actors?|dolls?|toys? figures?|cast)\b", re.IGNORECASE)
SET_SIZE = "1664x928"         # 16:9 on the 32-pixel grid the image models need
MESH_PRESET = "balanced"        # Hunyuan3D 2 Turbo geometry with Paint 2.0 Turbo texture
WAVE = 4                        # model3d_service._MAX_ACTIVE_JOBS
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
        if is_diorama(entry) and isinstance(name, str) and _NAME.match(name):
            why = check_diorama(name, entry, _text)
            if why:
                raise ModelError(why)
        elif not (isinstance(name, str) and _NAME.match(name)) or not isinstance(entry, dict) \
                or set(entry) - {"prompt", "seed"} or not _text(entry.get("prompt")):
            raise ModelError(f"sets.{name}: a lower-case name and {{prompt, seed}}, or a diorama {{kind: \"diorama\", ...}}")


def check_models(spec: dict) -> None:
    check_sets(spec)
    models = spec.get("models")
    if models is None:
        return
    made = [entry for entry in models.values() if not (isinstance(entry, dict) and entry.get("glb"))] if isinstance(models, dict) else []
    if not isinstance(models, dict) or len(made) > 12 or len(models) > 40:
        raise ModelError("spec.models maps up to 40 names to {from, prompt or glb, rig, animations}, at most 12 of them "
                         "made from a picture or a prompt")
    cast = _cast_ids(spec)
    for name, entry in models.items():
        _check_model(name, entry, cast)


def _check_model(name: Any, entry: Any, cast: set) -> None:
    if not (isinstance(name, str) and _NAME.match(name)) or not isinstance(entry, dict) or set(entry) - FIELDS:
        raise ModelError(f"models.{name}: a lower-case name and only {', '.join(sorted(FIELDS))}")
    _check_origin_and_rig(name, entry, cast)
    height = entry.get("height")
    if height is not None and not (isinstance(height, (int, float)) and not isinstance(height, bool) and 0.05 <= height <= 60):
        raise ModelError(f"models.{name}.height is the model's size in metres (0.05-60)")
    clips = entry.get("animations")
    if clips is not None and (not isinstance(clips, list) or not 0 < len(clips) <= 8 or not all(_text(c) for c in clips)):
        raise ModelError(f"models.{name}.animations is a list of 1-8 clip names")


def _check_origin_and_rig(name: str, entry: dict, cast: set) -> None:
    origins = [field for field in ("from", "prompt", "glb") if _text(entry.get(field))]
    if not origins or ("glb" in origins and len(origins) > 1):
        raise ModelError(f"models.{name}: give from (a cast id, stills name or picture URL), a prompt, or a glb in the workspace")
    rig = rig_of(entry, cast)
    if rig not in RIGS:
        raise ModelError(f"models.{name}.rig must be one of {', '.join(RIGS)}")
    if entry.get("fallback") is not None and (rig != "humanoid" or entry["fallback"] not in PROFILE_CLIPS):
        raise ModelError(f"models.{name}.fallback is a procedural profile ({', '.join(PROFILE_CLIPS)}) for a humanoid rig")


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
    made_from = {key: value for key, value in entry.items() if key != "height"}
    return hashlib.sha256(json.dumps([made_from, source, look, bpm, RECIPE], sort_keys=True).encode()).hexdigest()[:16]


def scenery_look(look: str) -> str:
    """The style without its sentences about people, which make an image model populate an empty picture."""
    sentences = re.split(r"(?<=[.;:])\s+", look or "")
    return " ".join(sentence for sentence in sentences if not _PEOPLE.search(sentence)).strip()


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
        fingerprint = _fingerprint(diorama_recipe(entry) if is_diorama(entry) else entry, None, spec)
        kept = made.get(name) or {}
        if kept.get("fingerprint") == fingerprint and (kept.get("url") or is_built(kept)):
            continue
        made[name] = {"fingerprint": fingerprint}
        if is_diorama(entry):
            made[name]["kind"] = "diorama"
            jobs.update(diorama_jobs(production, name, entry, scenery_look(style.get("image", "")), image_choice(entry, style)))
            continue
        prompt = f"{SET_LEAD} {entry['prompt']}. {scenery_look(style.get('image', ''))} {SET_STAGING}"
        jobs[f"set:{name}"] = production.image(f"set-{name}", prompt, None, SET_SIZE, entry.get("seed", 11),
                                               *image_choice(entry, style), production._attempt("set_attempts", name))
    return jobs


def _models_to_make(production: Any, spec: dict, made: dict) -> dict[str, tuple[dict, str | None, str]]:
    """(entry, source picture, rig) for each model that is new or changed; a resume skips the rest."""
    cast, todo = _cast_ids(spec), {}
    for name, entry in (spec.get("models") or {}).items():
        source, rig = _source(production, spec, entry), rig_of(entry, cast)
        # A model meshed straight from its picture before REFERENCE_STAGING is made again.
        restaged = {**entry, "staging": "isolated-2"} if source and rig != "humanoid" else entry
        if entry.get("glb"):
            restaged = {**entry, "glb_bytes": _size(production.root / entry["glb"], name), "cleanup": GLB_CLEANUP}
        fingerprint = _fingerprint(restaged, source, spec)
        kept = made.get(name) or {}
        if kept.get("fingerprint") == fingerprint and kept.get("file") and not kept.get("rig_error"):
            continue
        made[name] = {"fingerprint": fingerprint}
        todo[name] = (entry, source, rig)
    return todo


def _size(path: Any, name: str) -> int:
    if not path.is_file():
        raise ModelError(f"models.{name}.glb: no file {path.name} in the workspace")
    return path.stat().st_size


def _picture_jobs(production: Any, todo: dict, style: dict) -> tuple[dict[str, str], dict[str, str | None]]:
    """Image jobs for every model's picture: a T-pose from a character's portrait, the subject of any other picture
    alone on a plain background, or an object drawn from its prompt."""
    from services.production_image_defaults import image_choice
    look, pictures, jobs = scenery_look(style.get("image", "")), {}, {}
    for name, (entry, source, rig) in todo.items():
        if entry.get("glb"):
            continue
        if rig == "humanoid":
            staged = CHARACTER_STAGING
        elif source:
            staged = REFERENCE_STAGING
        else:
            staged = f"{entry['prompt']}. Style: {look} {OBJECT_STAGING}".replace("Style:  ", "")
        jobs[name] = production.image(f"model-{name}", staged, [source] if source else None, PICTURE_SIZE,
                                      entry.get("seed", 7), *image_choice(entry, style), production._attempt("model_picture_attempts", name))
    return pictures, jobs


def _collect_pictures(production: Any, jobs: dict, made: dict, sets: dict, pictures: dict) -> None:
    for name, file in production.wait(jobs).items():
        is_set = name.startswith("set:")
        set_name, _, part = name[4:].partition(":")
        record = sets[set_name] if is_set else made[name]
        if not file:
            record["error"] = f"picture failed ({production.failures.get(name, 'no output')})"
        elif part:
            record.setdefault("pictures", {})[part] = file
        elif is_set:
            record["url"] = production.upload(file)[1]
        else:
            pictures[name] = production.upload(file)[1]
    for set_name, record in sets.items():
        if record.get("pictures") and not record.get("error"):
            build_diorama(production, set_name, record)
    production.save()


def _rig_request(entry: dict, rig: str, mesh: str, bpm: int) -> dict:
    engine = "humanoid" if rig == "humanoid" else "procedural"
    return {"source": mesh, "engine": engine, "animations": _clips(entry, rig), "animation_bpm": bpm,
            **({} if engine == "humanoid" else {"rig_profile": rig})}


def _in_waves(production: Any, status: str, requests: dict[str, Callable[[], tuple[str | None, str | None]]], sleep) -> dict[str, dict]:
    """Submit at most WAVE jobs at a time: the 3D and rig services refuse a fifth active job ("Too many queued")."""
    done: dict[str, dict] = {}
    names = list(requests)
    for start in range(0, len(names), WAVE):
        done.update(_await(production, status, {name: requests[name]() for name in names[start:start + WAVE]}, sleep=sleep))
    return done


def _meshes_and_rigs(production: Any, spec: dict, todo: dict, pictures: dict, made: dict, sleep) -> None:
    meshes = _in_waves(production, "model3d.status", {
        name: (lambda name=name, picture=picture: _submit(production, "model3d.generate", f"{production.id}-mesh-{name}-{_digest(picture)}",
                                                         {"image_path": picture, "preset": MESH_PRESET}))
        for name, picture in pictures.items()}, sleep)
    bpm = min(180, max(60, int((spec.get("song") or {}).get("bpm") or 120)))
    rigs: dict[str, Callable[[], tuple[str | None, str | None]]] = {}
    for name, record in meshes.items():
        made[name]["picture"] = pictures[name]
        if record.get("status") != "completed" or not record.get("filename"):
            made[name]["error"] = f"mesh {record.get('status')}: {str(record.get('error') or '')[:120]}"
            continue
        made[name].update(mesh=record["filename"], file=record["filename"])
        entry, _source_url, rig = todo[name]
        if rig != "none":
            mesh = record["filename"]
            rigs[name] = _rig_job(production, name, _rig_request(entry, rig, mesh, bpm))
    rigs.update(_glb_rigs(production, todo, made, bpm))
    production.save()
    _land_rigs(production, made, _in_waves(production, "model3d.rig.status", rigs, sleep))
    _fall_back(production, todo, made, [name for name in rigs if made[name].get("rig_error")], bpm, sleep)


def _glb_rigs(production: Any, todo: dict, made: dict, bpm: int) -> dict[str, Callable[[], tuple[str | None, str | None]]]:
    """A model given as a workspace GLB is its own mesh (cleaned of vertex colours that are really normals): only its
    rig is asked for."""
    rigs = {}
    for name, (entry, _source_url, rig) in todo.items():
        if not entry.get("glb"):
            continue
        mesh = _cleaned(production, name, entry["glb"])
        made[name].update(mesh=mesh, file=mesh)
        if rig != "none":
            rigs[name] = _rig_job(production, name, _rig_request(entry, rig, mesh, bpm))
    return rigs


def _rig_job(production: Any, name: str, request: dict) -> Callable[[], tuple[str | None, str | None]]:
    """The rig submission, its intent named after the whole request: the journal refuses an intent used again with
    other parameters, so new animations on the same mesh need their own intent."""
    intent = f"{production.id}-rig-{name}-{_digest(json.dumps(request, sort_keys=True))}"
    return lambda: _submit(production, "model3d.rig", intent, request)


def _cleaned(production: Any, name: str, glb: str) -> str:
    from pathlib import PurePosixPath
    from services.glb_cleanup import clean_glb
    target = str(PurePosixPath(glb).with_suffix(".clean.glb"))
    if clean_glb(production.root / glb, production.root / target):
        production.log(f"model {name}: its vertex colours were normals (rainbow tints); rigging {target} without them")
        return target
    return glb


def _fall_back(production: Any, todo: dict, made: dict, failed: list[str], bpm: int, sleep) -> None:
    """A refused humanoid rig is done again with the model's fallback profile."""
    refused = [name for name in failed if todo[name][0].get("fallback")]
    for name in refused:
        made[name]["rigged_as"] = todo[name][0]["fallback"]
        production.log(f"model {name}: humanoid rig refused ({made[name].pop('rig_error')}), using the {made[name]['rigged_as']} profile")
    fallbacks = {name: _rig_job(production, name, _rig_request({}, made[name]["rigged_as"], made[name]["mesh"], bpm)) for name in refused}
    _land_rigs(production, made, _in_waves(production, "model3d.rig.status", fallbacks, sleep))


def _land_rigs(production: Any, made: dict, records: dict[str, dict]) -> None:
    for name, record in records.items():
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
    for name, entry in (spec.get("models") or {}).items():
        made.setdefault(name, {})["height"] = entry.get("height")
    pictures, jobs = _picture_jobs(production, todo, spec.get("style") or {})
    _collect_pictures(production, {**jobs, **set_jobs}, made, sets, pictures)
    _meshes_and_rigs(production, spec, todo, pictures, made, sleep)
    for name in todo:
        file = made[name].get("file")
        made[name]["clips"] = glb_clip_names(production.root / file) if file else []
        production.log(f"model {name}: " + (made[name].get("error") or made[name].get("rig_error")
                                            or f"{file} ({', '.join(made[name]['clips']) or 'rigid'})"))
    production.save()
    asked = {key[4:].partition(":")[0] for key in set_jobs}
    failed = [name for name in todo if made[name].get("error")] + [f"set {name}" for name in sorted(asked) if sets[name].get("error")]
    if failed:
        raise ModelError(f"models failed: {', '.join(failed)}")
