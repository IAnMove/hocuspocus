"""Plan checks that catch a thin video before any GPU work.

``blocking_problems`` is what ``production.run`` refuses in a new or changed spec: one still image filling
three or more shots that are not marked deliberate (``allow: ["still"]``), more runtime on still images
than the quality allows, and a full-frame title (title-card, trailer-slam) over a moving shot, which hides the
clip it paid for (``allow: ["title_card"]`` keeps a deliberate one), and a 3D shot asking a spec model for a clip its
rig will not bake (the export would fail after every GPU stage). A resume of an unchanged spec is never refused.

``plan_warnings`` is what ``dry_run`` adds: shot fields the runner ignores (a plan that promises what
nothing makes), an H3 clip replayed in several shots, H3 shots without the cast, boxes-and-cones models,
characters that never play a clip, the same 3D template over and over, and a shot pattern or lyric look
copied from another production in the workspace.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from services.production_quality import profile_of

REUSED_STILL = 3
FULL_FRAME_TITLES = ("title-card", "trailer-slam")     # an opaque plate over the whole frame
MOVING = ("h3", "clip", "scene3d", "screen")
REUSED_TEMPLATE = 4
SHOT_FIELDS = {"key", "kind", "line", "span", "t0", "t1", "after", "cast", "sing", "frame", "action", "still", "clip", "image_model",
               "image_steps", "graphic", "scene3d", "desktop", "focus", "zoom", "camera", "title", "allow", "moment", "seed"}


def _shots(spec: dict) -> list[dict]:
    shots = spec.get("shots")
    return [shot for shot in shots if isinstance(shot, dict)] if isinstance(shots, list) else []


def _still_runtime(spec: dict, shots: list[dict]) -> float:
    duration = float((spec.get("song") or {}).get("duration") or 0)
    # Sorted by start only: two shots at one t0 would otherwise compare their dicts and raise.
    timed = sorted(((float(shot["t0"]), shot) for shot in shots if isinstance(shot.get("t0"), (int, float))), key=lambda pair: pair[0])
    if duration <= 0 or len(timed) != len(shots):
        return 0.0
    ends = [start for start, _ in timed[1:]] + [duration]
    still = sum(end - start for (start, shot), end in zip(timed, ends)
                if shot.get("kind") == "still" and "still" not in (shot.get("allow") or ()))
    return still / duration


def refuse_thin_plan(spec: dict, stored: Any, root: Any = None) -> None:
    """production.run: a new or changed spec that would look thin is HTTP 422 quality_gate; a resume never is."""
    if spec == stored:
        return
    problems = blocking_problems(spec, root)
    if problems:
        from fastapi import HTTPException
        summary = "; ".join(f"{item['code']} ({item.get('still') or item.get('ratio')})" for item in problems)
        raise HTTPException(422, {"code": "quality_gate", "message": f"The plan would look thin: {summary}. See problems.",
                                  "problems": problems, "retryable": False})


def blocking_problems(spec: dict, root: Any = None) -> list[dict]:
    shots = _shots(spec)
    problems = []
    uses: dict[str, list[str]] = {}
    for shot in shots:
        if shot.get("kind") == "still" and isinstance(shot.get("still"), str) and "still" not in (shot.get("allow") or ()):
            uses.setdefault(shot["still"], []).append(str(shot.get("key")))
    for name, keys in uses.items():
        if len(keys) >= REUSED_STILL:
            problems.append({"code": "still_reused", "still": name, "shots": keys,
                             "hint": "one picture panned across many shots reads as filler: give each moment its own clip, "
                                     "3D shot or picture, or mark a deliberate repeat with allow: [\"still\"]"})
    ratio = _still_runtime(spec, shots)
    limit = profile_of(spec)["static"]
    if ratio > limit:
        problems.append({"code": "too_static", "ratio": round(ratio, 2), "limit": limit,
                         "hint": "replace still shots with H3 or scene3d shots"})
    problems += _unbaked_clips(spec, shots, root)
    hidden = [str(shot.get("key")) for shot in shots if _covered(shot)]
    if hidden:
        problems.append({"code": "title_card_hides_shot", "shots": hidden,
                         "hint": "title-card and trailer-slam paint an opaque plate over the whole frame, so the clip under "
                                 "it is never seen: use lower-third-date, social-caption, dymo, card, chapter or quote, or "
                                 "mark a deliberate card with allow: [\"title_card\"]"})
    return problems


def _baked(entry: dict, rig: str, root: Any = None) -> list[str] | None:
    """The clips a spec model's rig bakes, or None when the gate cannot tell. A GLB played as it is (rig none) has
    the clips it brought, read from the file when the workspace is known."""
    from services.production_models import HUMANOID_CLIPS, PROFILE_CLIPS
    if rig == "none":
        return _brought(entry, root)
    # A humanoid with a fallback either bakes its animations (the rig takes the body) or stands any of them in
    # with the profile's clips (it does not): a clip outside its animations is baked in neither case.
    return list(entry.get("animations") or (HUMANOID_CLIPS if rig == "humanoid" else PROFILE_CLIPS.get(rig, [])))


def _brought(entry: dict, root: Any) -> list[str] | None:
    """The animations inside a workspace GLB, [] for a generated model with no rig, None when the file is out of reach."""
    if not entry.get("glb"):
        return []
    if root is None:
        return None
    from services.series_shot3d import glb_clip_names
    try:
        return glb_clip_names(Path(root) / entry["glb"])
    except (OSError, ValueError):
        return None


def _unbaked_clips(spec: dict, shots: list[dict], root: Any = None) -> list[dict]:
    """A cast clip its model will not have: «Grepdalf» asked Lia to wave and failed at the last 3D shot."""
    from services.production_models import _cast_ids, rig_of
    from services.production_scene3d import _clip_key, _rig_labels
    models, cast, labels = spec.get("models") or {}, _cast_ids(spec), _rig_labels()
    missing = []
    for shot in shots:
        config = shot.get("scene3d") if shot.get("kind") == "scene3d" and isinstance(shot.get("scene3d"), dict) else {}
        for role, entry in _sources(config):
            model = models.get(entry.get("source")) if isinstance(models, dict) else None
            baked = _baked(model, rig_of(model, cast), root) if isinstance(model, dict) else None
            if baked is None:
                continue
            known = {_clip_key(clip) for clip in baked} | {_clip_key(labels.get(clip, clip)) for clip in baked}
            asked = [entry.get("clip")] + [cue.get("clip") for cue in entry.get("clips") or [] if isinstance(cue, dict)]
            missing += [f"{shot.get('key')}:{role} {clip}" for clip in asked if isinstance(clip, str) and _clip_key(clip) not in known]
    if not missing:
        return []
    return [{"code": "clip_not_baked", "shots": missing,
             "hint": "add the clip to that model's animations, or ask for one it bakes"}]


def _covered(shot: dict) -> bool:
    title = shot.get("title")
    return (shot.get("kind") in MOVING and isinstance(title, dict) and title.get("template") in FULL_FRAME_TITLES
            and "title_card" not in (shot.get("allow") or ()))


def plan_warnings(spec: dict, root: Any = None, production_id: str | None = None) -> list[dict]:
    shots = _shots(spec)
    found = _ignored_fields(shots) + _replayed_clips(shots) + _castless_h3(spec, shots) + _scene3d_warnings(spec, shots, root)
    found += _stage_warnings(spec, shots)
    if root:
        found += _copied_from_siblings(spec, shots, Path(root), production_id)
    return found


def _ignored_fields(shots: list[dict]) -> list[dict]:
    fields: dict[str, list[str]] = {}
    for shot in shots:
        for field in set(shot) - SHOT_FIELDS:
            fields.setdefault(field, []).append(str(shot.get("key")))
    return [{"code": "ignored_shot_field", "field": field, "shots": keys,
             "hint": "the runner does nothing with this field: what it describes will not be on screen"}
            for field, keys in sorted(fields.items())]


def _replayed_clips(shots: list[dict]) -> list[dict]:
    uses: dict[str, list[str]] = {}
    for shot in shots:
        if shot.get("kind") == "clip" and isinstance(shot.get("clip"), str):
            uses.setdefault(shot["clip"], []).append(str(shot.get("key")))
    return [{"code": "clip_replayed", "clip": clip, "shots": keys} for clip, keys in uses.items() if len(keys) >= 2]


def _castless_h3(spec: dict, shots: list[dict]) -> list[dict]:
    h3 = [shot for shot in shots if shot.get("kind") == "h3"]
    empty = [str(shot.get("key")) for shot in h3 if not shot.get("cast")]
    if spec.get("cast") and h3 and len(empty) * 2 > len(h3):
        return [{"code": "h3_without_cast", "shots": empty, "hint": "the characters appear in few H3 shots; give the shots their cast"}]
    return []


def _sources(config: dict) -> list[tuple[str, dict]]:
    entries = []
    if isinstance(config.get("subject"), str):
        entries.append(("subject_1", {"source": config["subject"], "clip": config.get("clip")}))
    for key, value in (config.get("cast") or {}).items():
        entries.append((key, value if isinstance(value, dict) else {"source": value}))
    for slot in (config.get("slots") or []) + ((config.get("document") or {}).get("slots") or []):
        if isinstance(slot, dict) and slot.get("media", "model3d") == "model3d" and slot.get("sourceUrl"):
            entries.append((str(slot.get("id")), {"source": slot["sourceUrl"], "clip": slot.get("clip"), "clips": slot.get("clips")}))
    return entries


def _workspace_file(source: str) -> str | None:
    address = urlparse(source)
    if address.path.startswith("/api/v1/file/"):
        return unquote(address.path.removeprefix("/api/v1/file/"))
    return None if source.startswith(("/", "http")) else source


def _procedural(root: Path, name: str) -> bool:
    meta = root / Path(name).with_suffix(".meta.json")
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return ((data.get("generation") or {}).get("model") or {}).get("id") == "procedural-compose"


def _rigged_models(spec: dict) -> set[str]:
    from services.production_models import rig_of
    cast = {entry.get("id") for entry in spec.get("cast") or [] if isinstance(entry, dict)}
    return {name for name, entry in (spec.get("models") or {}).items() if isinstance(entry, dict) and rig_of(entry, cast) != "none"}


def _scene3d_warnings(spec: dict, shots: list[dict], root: Any) -> list[dict]:
    rigged = _rigged_models(spec)
    templates: dict[str, list[str]] = {}
    boxes: dict[str, list[str]] = {}
    still: list[str] = []
    frozen: dict[str, list[str]] = {}
    for shot in shots:
        config = shot.get("scene3d") if shot.get("kind") == "scene3d" and isinstance(shot.get("scene3d"), dict) else None
        if config is not None:
            _scan_scene3d(str(shot.get("key")), config, root, rigged, templates, boxes, still)
            if _still_template_shot(config):
                frozen.setdefault(str(config.get("template")), []).append(str(shot.get("key")))
    found = [{"code": "procedural_model", "model": name, "shots": keys,
              "hint": "built from boxes; make it with spec.models (textured Hunyuan3D, rigged)"} for name, keys in boxes.items()]
    if still:
        found.append({"code": "model_not_animated", "objects": still, "hint": "give rigged models a clip or clips"})
    found += [{"code": "template_reused", "template": name, "shots": keys} for name, keys in templates.items() if len(keys) > REUSED_TEMPLATE]
    found += [{"code": "template_still", "template": name, "shots": keys,
               "hint": "the template animates nothing: give the cast a clip, add motion or a camera, play it in a world, "
                       "or pick a card whose moves are not empty"} for name, keys in frozen.items()]
    return found


_LIVELY_KEYS = ("motion", "camera", "rhythm", "world", "atmos", "pixelWorld")


def _still_template_shot(config: dict) -> bool:
    """A shipped template whose card is ``still`` with nothing in the shot that moves it: the shot will be a frozen picture."""
    from services.world3d_template_catalog import builtin_card
    card = builtin_card(str(config.get("template") or ""))
    if not card or not card.get("still"):
        return False
    if any(config.get(key) for key in _LIVELY_KEYS):
        return False
    return not any(entry.get("clip") or entry.get("clips") for _role, entry in _sources(config))


def _scan_scene3d(key: str, config: dict, root: Any, rigged: set, templates: dict, boxes: dict, still: list) -> None:
    template = config.get("template") or (config.get("document") or {}).get("templateId")
    if template:
        templates.setdefault(str(template), []).append(key)
    for role, entry in _sources(config):
        source = str(entry.get("source") or "")
        name = _workspace_file(source)
        if root and name and _procedural(Path(root), name):
            boxes.setdefault(name, []).append(key)
        if source in rigged and not entry.get("clip") and not entry.get("clips"):
            still.append(f"{key}:{role}")


SAMEY_RUN = 4


def _scene3d(shot: dict) -> dict | None:
    return shot.get("scene3d") if shot.get("kind") == "scene3d" and isinstance(shot.get("scene3d"), dict) else None


def _stage_skin(config: dict, sets: dict) -> tuple[str | None, dict]:
    """The name and skin of the stage or room a shot plays in: a ``stage-*`` template with no background keeps the mold's
    colours, a ``sets`` room brings the skin it asked for, an inline room its own."""
    from services.production_rooms import has_room, is_room
    from services.world3d_stage_cards import is_stage
    background = config.get("background")
    if isinstance(background, str) and is_room(sets.get(background)):
        return background, sets[background].get("skin") or {}
    if has_room(config):
        room = background["room"]
        return str((room.get("mold") or {}).get("id") or "room"), room.get("skin") or {}
    if background is None and is_stage(config.get("template")):
        return str(config["template"]), {}
    return None, {}


def _colours_only(skin: dict) -> bool:
    return all(isinstance(value, dict) and set(value) <= {"color"} for value in skin.values())


def _stage_runs(shots: list[dict]) -> list[tuple[tuple[str, str], list[str]]]:
    """Consecutive scene3d shots on the same template and background; any other shot ends a run."""
    runs: list = []
    for shot in shots:
        config = _scene3d(shot)
        if config is None:
            runs.append(None)
            continue
        template = str(config.get("template") or (config.get("document") or {}).get("templateId"))
        pair = (template, json.dumps(config.get("background"), sort_keys=True, default=str))
        if runs and runs[-1] and runs[-1][0] == pair:
            runs[-1][1].append(str(shot.get("key")))
        else:
            runs.append((pair, [str(shot.get("key"))]))
    return [run for run in runs if run]


def _stage_warnings(spec: dict, shots: list[dict]) -> list[dict]:
    """A stage or room shown in its mold colours only, once per set or template, and the same template and background
    in more than four shots in a row."""
    sets = spec.get("sets") if isinstance(spec.get("sets"), dict) else {}
    unskinned: dict[str, list[str]] = {}
    for shot in shots:
        config = _scene3d(shot)
        name, skin = _stage_skin(config, sets) if config is not None else (None, {})
        if name is not None and _colours_only(skin):
            unskinned.setdefault(name, []).append(str(shot.get("key")))
    found = [{"code": "stage_unskinned", "set": name, "shots": keys,
              "hint": "the stage shows only its mold colours: add a sets entry of kind room with a skin (an image, a texture "
                      "or a video) and name it as the shot's background"} for name, keys in unskinned.items()]
    found += [{"code": "looks_samey", "template": template, "background": json.loads(background), "shots": keys,
               "hint": "the same template and place in more than four shots in a row: change the camera (roomCamera), "
                       "the template or the place"} for (template, background), keys in _stage_runs(shots) if len(keys) > SAMEY_RUN]
    return found


def _pattern(shots: list[dict]) -> list[str]:
    return [str(shot.get("kind")) for shot in shots]


def _copied_from_siblings(spec: dict, shots: list[dict], root: Path, production_id: str | None) -> list[dict]:
    found = []
    pattern = _pattern(shots)
    style = spec.get("style") or {}
    look = [style.get("lyric_template"), style.get("lyric_style")]
    for path in sorted(root.glob("*.production.json")):
        other = path.name.removesuffix(".production.json")
        if other == production_id:
            continue
        try:
            sibling = (json.loads(path.read_text(encoding="utf-8")).get("spec") or {})
        except (OSError, ValueError):
            continue
        if len(pattern) >= 8 and _pattern(_shots(sibling)) == pattern:
            found.append({"code": "same_shot_pattern", "production": other,
                          "hint": "the same sequence of shot kinds as another piece: vary the structure"})
        sibling_style = sibling.get("style") or {}
        if look[0] and [sibling_style.get("lyric_template"), sibling_style.get("lyric_style")] == look:
            found.append({"code": "same_lyric_look", "production": other, "hint": "give each piece its own lyric treatment"})
    return found
