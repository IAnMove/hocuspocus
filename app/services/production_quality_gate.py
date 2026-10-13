"""Plan checks that catch a thin video before any GPU work.

``blocking_problems`` is what ``production.run`` refuses in a new or changed spec: one still image filling
three or more shots that are not marked deliberate (``allow: ["still"]``), more runtime on still images
than the quality allows, and a full-frame title (title-card, trailer-slam) over a moving shot, which hides the
clip it paid for (``allow: ["title_card"]`` keeps a deliberate one), a 3D shot asking a spec model for a clip its
rig will not bake (the export would fail after every GPU stage), and a ``camera`` that is not a camera preset
(``unknown_camera``; the scene edit would fail after the GPU work). A resume of an unchanged spec is never refused.
Each problem carries a plain ``message`` that names the shots, the pictures, models or cameras and the limit.

The first three only make the video look static (``THIN_CODES``): ``allow_thin: true`` on ``production.run`` (and
its dry run) turns them into warnings and the run goes ahead. A clip or camera that does not exist is always refused.

``plan_warnings`` is what ``dry_run`` adds: shot fields the runner ignores (a plan that promises what
nothing makes), an H3 clip replayed in several shots, H3 shots without the cast, boxes-and-cones models,
characters that never play a clip, the same 3D template over and over, a scene2d card whose derived traits say it
holds the picture (``template_still``), and a shot pattern or lyric look copied from another production in the
workspace.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from services.production_camera import unknown_cameras
from services.production_quality import DEFAULT, PROFILES, profile_of
from services.video2d_catalogs import CATALOGS
from services.video2d_preset_catalog import camera_presets

REUSED_STILL = 3
# an opaque plate over the whole frame: the text templates marked covers in text_templates.json
FULL_FRAME_TITLES = tuple(entry["id"] for entry in CATALOGS["scenes.text.catalog"]["entries"] if entry.get("covers") is True)
MOVING = ("h3", "clip", "scene3d", "scene2d", "screen")
REUSED_TEMPLATE = 4
SHOT_FIELDS = {"key", "kind", "line", "span", "t0", "t1", "after", "cast", "sing", "frame", "action", "still", "clip", "image_model",
               "image_steps", "graphic", "scene3d", "scene2d", "desktop", "focus", "zoom", "camera", "title", "allow", "moment", "seed"}
# What only makes the video look static: allow_thin lets these through as warnings. The other blocking problems
# (a clip a model will not have, a camera that does not exist) would fail after the GPU work, so nothing skips them.
THIN_CODES = ("still_reused", "too_static", "title_card_hides_shot")
ALLOW_THIN = "allow_thin"
LISTED_CLIPS = 12          # a GLB can bring dozens of clips: name the first ones
MOVING_KINDS = "kind h3, scene3d or scene2d"


def _shots(spec: dict) -> list[dict]:
    shots = spec.get("shots")
    return [shot for shot in shots if isinstance(shot, dict)] if isinstance(shots, list) else []


def _quoted(names: list[str]) -> str:
    """'"a"', '"a" and "b"', '"a", "b" and "c"'."""
    items = [f'"{name}"' for name in names]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _shot_names(keys: list[str]) -> str:
    return ("shot " if len(keys) == 1 else "shots ") + _quoted(keys)


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def _number(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _percent(ratio: float) -> str:
    return _number(ratio * 100) + "%"


def _allowed(shot: dict, token: str) -> bool:
    return token in (shot.get("allow") or ())


def _still_time(spec: dict, shots: list[dict]) -> tuple[float, float, list[str]]:
    """Seconds on still images not marked deliberate, the song's seconds and those shots' keys. Nothing is counted
    unless every shot has its own ``t0``."""
    duration = float((spec.get("song") or {}).get("duration") or 0)
    # Sorted by start only: two shots at one t0 would otherwise compare their dicts and raise.
    timed = sorted(((float(shot["t0"]), shot) for shot in shots if isinstance(shot.get("t0"), (int, float))), key=lambda pair: pair[0])
    if duration <= 0 or len(timed) != len(shots):
        return 0.0, duration, []
    ends = [start for start, _ in timed[1:]] + [duration]
    held = [(end - start, shot) for (start, shot), end in zip(timed, ends) if shot.get("kind") == "still" and not _allowed(shot, "still")]
    return sum(seconds for seconds, _ in held), duration, [str(shot.get("key")) for _, shot in held]


def refuse_thin_plan(spec: dict, stored: Any, root: Any = None, *, allow_thin: bool = False) -> list[dict]:
    """production.run: a new or changed spec that would look thin is HTTP 422 quality_gate; a resume never is.

    With ``allow_thin`` the thin checks are returned as warnings instead; a clip or camera that does not exist is
    refused all the same."""
    if spec == stored:
        return []
    refused, allowed = gate(spec, root, allow_thin=allow_thin)
    if refused:
        from fastapi import HTTPException
        raise HTTPException(422, {"code": "quality_gate", "message": refusal_message(refused), "problems": refused,
                                  "retryable": False})
    return allowed


def gate(spec: dict, root: Any = None, *, allow_thin: bool = False) -> tuple[list[dict], list[dict]]:
    """``(refused, allowed)``: what production.run refuses, and the thin checks ``allow_thin`` lets through as
    warnings (each marked ``allowed_by: "allow_thin"``). The dry run and the run both read this."""
    problems = blocking_problems(spec, root)
    if not allow_thin:
        return problems, []
    return ([item for item in problems if item["code"] not in THIN_CODES],
            [{**item, "allowed_by": ALLOW_THIN} for item in problems if item["code"] in THIN_CODES])


def refusal_message(problems: list[dict]) -> str:
    """The 422 message: every problem in plain words, the thin ones apart from the ones nothing can skip."""
    thin = [item["message"] for item in problems if item["code"] in THIN_CODES]
    broken = [item["message"] for item in problems if item["code"] not in THIN_CODES]
    lines = ["Nothing was started: fix the plan and send it again."]
    if thin:
        lines.append("These would make the video look static. Fix them, or send allow_thin: true with the spec to make it "
                     "as planned (they come back as warnings):")
        lines += [f"- {message}" for message in thin]
    if broken:
        lines.append("These would fail after the GPU work, so allow_thin does not skip them:")
        lines += [f"- {message}" for message in broken]
    return "\n".join(lines)


def blocking_problems(spec: dict, root: Any = None) -> list[dict]:
    shots = _shots(spec)
    problems = _reused_stills(shots) + _too_static(spec, shots)
    problems += _unbaked_clips(spec, shots, root)
    problems += [{**item, "message": _camera_message(item)} for item in unknown_cameras(spec)]
    problems += _hidden_by_titles(shots)
    return problems


def _reused_stills(shots: list[dict]) -> list[dict]:
    uses: dict[str, list[str]] = {}
    for shot in shots:
        if shot.get("kind") == "still" and isinstance(shot.get("still"), str) and not _allowed(shot, "still"):
            uses.setdefault(shot["still"], []).append(str(shot.get("key")))
    return [{"code": "still_reused", "still": name, "shots": keys,
             "message": f"{_sentence(_shot_names(keys))} all show the same still picture \"{name}\". Give each one its own "
                        f"picture, turn some of them into moving shots ({MOVING_KINDS}), or add allow: [\"still\"] to the "
                        "ones that repeat it on purpose.",
             "hint": "one picture panned across many shots reads as filler: give each moment its own clip, "
                     "3D shot or picture, or mark a deliberate repeat with allow: [\"still\"]"}
            for name, keys in uses.items() if len(keys) >= REUSED_STILL]


def _too_static(spec: dict, shots: list[dict]) -> list[dict]:
    seconds, duration, keys = _still_time(spec, shots)
    ratio = seconds / duration if duration > 0 else 0.0
    limit = profile_of(spec)["static"]
    if ratio <= limit:
        return []
    quality = spec.get("quality") if spec.get("quality") in PROFILES else DEFAULT
    bar = f"quality \"{quality}\"" + ("" if "quality" in spec else " (the default)")
    return [{"code": "too_static", "ratio": round(ratio, 2), "limit": limit, "shots": keys,
             "message": f"Still pictures fill {_percent(ratio)} of the song ({_number(seconds)} s of {_number(duration)} s, in "
                        f"{_shot_names(keys)}), and {bar} allows at most {_percent(limit)}. Turn some of these shots into "
                        f"moving shots ({MOVING_KINDS}), make them shorter, or add allow: [\"still\"] to the ones that must "
                        "stay still.",
             "hint": "replace still shots with H3 or scene3d shots"}]


def _hidden_by_titles(shots: list[dict]) -> list[dict]:
    hidden = [shot for shot in shots if _covered(shot)]
    if not hidden:
        return []
    templates: dict[str, list[str]] = {}
    for shot in hidden:
        templates.setdefault(shot["title"]["template"], []).append(str(shot.get("key")))
    where = "; ".join(f"\"{template}\" on {_shot_names(keys)}" for template, keys in templates.items())
    head = "A full-frame title hides the moving picture under it" if len(hidden) == 1 else \
        "Full-frame titles hide the moving picture under them"
    return [{"code": "title_card_hides_shot", "shots": [str(shot.get("key")) for shot in hidden],
             "message": f"{head}: {where}. Use a title that leaves the picture visible (lower-third-date, social-caption, "
                        "dymo, card, chapter or quote), or add allow: [\"title_card\"] to a shot that should show only the "
                        "card.",
             "hint": "title-card and trailer-slam paint an opaque plate over the whole frame, so the clip under "
                     "it is never seen: use lower-third-date, social-caption, dymo, card, chapter or quote, or "
                     "mark a deliberate card with allow: [\"title_card\"]"}]


def _camera_message(problem: dict) -> str:
    uses = problem.get("uses") or []
    asked = "; ".join(f"{_shot_names([use['shot']])} asks for the camera \"{use['camera']}\"" for use in uses)
    missing = "That camera does not exist" if len(uses) == 1 else "Those cameras do not exist"
    return (f"{_sentence(asked)}. {missing}, so the scene edit would fail after the GPU work. Use one of: "
            f"{', '.join(camera_presets())}.")


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
            missing += [(str(shot.get("key")), role, str(entry.get("source")), clip, baked)
                        for clip in asked if isinstance(clip, str) and _clip_key(clip) not in known]
    if not missing:
        return []
    return [{"code": "clip_not_baked", "shots": [f"{key}:{role} {clip}" for key, role, _model, clip, _baked in missing],
             "message": _clips_message(missing),
             "hint": "add the clip to that model's animations, or ask for one it bakes"}]


def _clips_message(missing: list[tuple[str, str, str, str, list[str]]]) -> str:
    asked = "; ".join(f"{_shot_names([key])} ({role}) asks model \"{model}\" for the clip \"{clip}\", but {_clip_list(model, baked)}"
                      for key, role, model, clip, baked in missing)
    return (f"{_sentence(asked)}. The 3D export would fail after the GPU work: add the clip to that model's animations in "
            "spec.models, or ask for one it has.")


def _clip_list(model: str, baked: list[str]) -> str:
    if not baked:
        return f"\"{model}\" has no clips"
    more = f" and {len(baked) - LISTED_CLIPS} more" if len(baked) > LISTED_CLIPS else ""
    return f"\"{model}\" only has: {', '.join(baked[:LISTED_CLIPS])}{more}"


def _covered(shot: dict) -> bool:
    title = shot.get("title")
    return (shot.get("kind") in MOVING and isinstance(title, dict) and title.get("template") in FULL_FRAME_TITLES
            and not _allowed(shot, "title_card"))


def plan_warnings(spec: dict, root: Any = None, production_id: str | None = None) -> list[dict]:
    shots = _shots(spec)
    found = _ignored_fields(shots) + _replayed_clips(shots) + _castless_h3(spec, shots) + _scene3d_warnings(spec, shots, root)
    found += _stage_warnings(spec, shots) + _still_cards(shots)
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


def _still_cards(shots: list[dict]) -> list[dict]:
    """A scene2d card whose derived traits say nothing but particles moves for most of the shot."""
    from services.production_scene2d import card_of, card_traits, is_scene2d
    frozen: dict[str, list[str]] = {}
    for shot in shots:
        card = card_of(shot) if is_scene2d(shot) else None
        if card and card_traits(card).get("still") is True:
            frozen.setdefault(card, []).append(str(shot.get("key")))
    return [{"code": "template_still", "template": card, "shots": keys,
             "hint": "this 2D card holds the picture for most of the shot: pick a card whose moves are not empty "
                     "(scenes.templates.suggest), or give it more drift"} for card, keys in frozen.items()]


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
