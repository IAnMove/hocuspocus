"""Video 2D music cards as production shots: ``{"kind": "scene2d", "scene2d": {template, cast, background, controls}}``.

A scene2d shot plays one ``music-*`` card of ``scene_templates.json`` (the music originals and the cutout
choreographies); ``cinema-*``, ``space-*`` and the other families stay out (``scene2d_family_not_allowed``), the 3D
library and the narrative shelf cover them. The card brings its own camera, so production cameras do not apply.
Sources follow the scene3d rules: a URL, a spec model or set, a stills name or a workspace file; a cast id plays the
cast member's cutout (its portrait with the background removed, made once per run by ``image.remove_background``).
Without ``scene2d.background`` the shot's ``still`` is the background, else a start frame drawn from its ``frame``
prompt as an empty set. The 2D template compiler (``video2d_compile``) checks the card and builds its document at
1920x1080 and 24 fps, with the song's tempo when the card has a ``bpm`` control and the shot did not set one; the
scene then gets the shot's title, lyric, footer and finish like any other 2D scene.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from services.video2d_catalogs import CATALOGS

FIELDS = frozenset({"template", "cast", "background", "controls"})
FAMILY = "music-"
CAST_LIMIT = 6
# Validation runs before any picture is resolved: every source stands in as this durable URL.
PLACEHOLDER = "/api/v1/file/scene2d-placeholder.png?workspace=scene2d"
WIDTH, HEIGHT, FPS = 1920, 1080, 24           # production scene documents (production_stage_scenes.scene_document)
RECIPE = 1                                    # bump when the compile request changes for the same shot
TRAITS = Path(__file__).resolve().parents[1] / "shared" / "video2d_template_traits.json"
COMPILE = "scenes.template.compile"
CUTOUT = "image.remove_background"
_URLS = ("/api/", "http://", "https://")


class Scene2dError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _prepare(data: dict) -> dict:
    """The 2D template compiler's own check of a card call (aliases, slots, controls, frame), without Node."""
    from services import video2d_compile
    return video2d_compile._prepare_template(data)


def _source(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 2000


def _config(shot: dict) -> dict:
    """The shot's ``scene2d`` object once its fields have the right shapes."""
    config = shot.get("scene2d")
    if not isinstance(config, dict) or not config or set(config) - FIELDS:
        raise Scene2dError("invalid_spec", f"scene2d {shot.get('key')}: give {{template, cast, background, controls}}")
    template = config.get("template")
    if not isinstance(template, str) or not template.strip():
        raise Scene2dError("invalid_spec", f"scene2d {shot.get('key')}: template is the id of a music-* card")
    _check_fields(shot, config)
    return config


def _check_cast(key: Any, cast: Any) -> None:
    if cast is None:
        return
    if not isinstance(cast, dict) or not 0 < len(cast) <= CAST_LIMIT or not all(
            isinstance(role, str) and role and _source(value) for role, value in cast.items()):
        raise Scene2dError("invalid_spec", f"scene2d {key}: cast maps 1-{CAST_LIMIT} card slots (subject_1, subject_2, prop_1...) "
                                           "to a picture (URL, workspace file, stills name, set or cast id)")
    if "background" in cast:
        raise Scene2dError("invalid_spec", f"scene2d {key}: give the background as scene2d.background, not as a cast slot")


def _check_fields(shot: dict, config: dict) -> None:
    key = shot.get("key")
    _check_cast(key, config.get("cast"))
    if "background" in config and not _source(config["background"]):
        raise Scene2dError("invalid_spec", f"scene2d {key}: background is a picture or a seamless video loop")
    controls = config.get("controls")
    if controls is not None and not isinstance(controls, dict):
        raise Scene2dError("invalid_spec", f"scene2d {key}: controls maps the card's control names to values")
    if isinstance(controls, dict) and "duration" in controls:
        raise Scene2dError("invalid_spec", f"scene2d {key}: the shot's cut sets the duration; leave it out of controls")


def _check_shot(shot: dict, config: dict) -> None:
    key = shot.get("key")
    if not (config.get("background") or shot.get("still") or shot.get("frame")):
        raise Scene2dError("invalid_spec", f"scene2d {key} needs a background: scene2d.background, the shot's still, "
                                           "or a frame prompt to draw one")
    if shot.get("camera"):
        raise Scene2dError("invalid_spec", f"scene2d {key} plays its card's own camera: set scene2d.controls instead of camera")
    if shot.get("sing"):
        raise Scene2dError("invalid_spec", f"scene2d {key} does not lip-sync; sing is for H3 shots")


def _family(key: Any, template: str) -> None:
    if not template.startswith(FAMILY):
        raise Scene2dError("scene2d_family_not_allowed",
                           f"scene2d {key}: {template} is not a music card; a scene2d shot plays a music-* card "
                           "(cinema and space shots: use scene3d)")


def card_entry(card: str) -> dict:
    return next((entry for entry in CATALOGS["scenes.templates.catalog"]["entries"] if entry.get("id") == card), {})


def _slots(card: str) -> str:
    return ", ".join(str(slot.get("id")) for slot in card_entry(card).get("slots") or [])


def _explain(key: Any, template: str, error: Exception) -> Scene2dError:
    """A compiler refusal in the spec's words: which slot or control of which card."""
    code, detail = getattr(error, "code", "invalid_spec"), str(error).split(": ", 1)[-1]
    if code == "template_bad_asset":
        message = f"scene2d {key}: {detail} is not a slot of {template} ({_slots(template) or 'see scenes.catalog'})"
    elif code == "template_missing_slot":
        message = f"scene2d {key}: {template} needs {detail} in cast"
    elif code == "template_bad_control":
        message = f"scene2d {key}: control {detail} is unknown to {template} or out of its range"
    else:
        message = f"scene2d {key}: {code}: {detail}"
    return Scene2dError("invalid_spec", message)


def prepare_card(shot: dict, sources: dict[str, str] | None = None) -> dict:
    """The compiler's prepared request for the shot's card (``templateId`` is the card an alias stands for).

    Without ``sources`` every given slot and the background stand in as a placeholder picture."""
    config = _config(shot)
    template = config["template"].strip()
    _family(shot.get("key"), template)
    if sources is None:
        sources = {**{role: PLACEHOLDER for role in config.get("cast") or {}}, "background": PLACEHOLDER}
    from services.video2d_compile import CompileError
    try:
        prepared = _prepare({"templateId": template, "assets": sources, "controls": dict(config.get("controls") or {})})
    except CompileError as error:
        raise _explain(shot.get("key"), template, error) from error
    _family(shot.get("key"), str(prepared.get("templateId") or template))
    return prepared


def validate_scene2d_shot(shot: dict) -> dict:
    """Check a scene2d shot before any GPU work; returns the prepared card request."""
    _check_shot(shot, _config(shot))
    return prepare_card(shot)


def is_scene2d(shot: Any) -> bool:
    return isinstance(shot, dict) and shot.get("kind") == "scene2d" and isinstance(shot.get("scene2d"), dict)


def draws_frame(shot: Any) -> bool:
    """A scene2d shot with no background and no still draws its background from its frame prompt."""
    return is_scene2d(shot) and not shot["scene2d"].get("background") and not shot.get("still") and bool(shot.get("frame"))


def redo_origin(shot: dict) -> str:
    """A redo draws a scene2d shot's background again when it drew one; otherwise it rebuilds the scene."""
    return "frame" if draws_frame(shot) else "scene"


def plate_prompt(spec: dict, window: dict) -> str:
    """The background of a scene2d shot is an empty set: the card puts the cast in it as cutouts."""
    from services.production_models import SET_LEAD, SET_STAGING, scenery_look
    look = scenery_look(str((spec.get("style") or {}).get("image") or ""))
    return " ".join(part for part in (SET_LEAD, f"{str(window.get('frame') or '').strip().rstrip('.')}.", look, SET_STAGING) if part)


def _shots(spec: dict) -> list[dict]:
    shots = spec.get("shots") if isinstance(spec.get("shots"), list) else []
    return [shot for shot in [*shots, *(spec.get("fill") or [])] if is_scene2d(shot)]


def cast_ids(spec: dict) -> list[str]:
    """The cast members a scene2d shot plays by id, in spec order."""
    ids = [entry.get("id") for entry in spec.get("cast") or [] if isinstance(entry, dict)]
    used = {value for shot in _shots(spec) for value in (shot["scene2d"].get("cast") or {}).values()}
    return [cid for cid in ids if cid in used]


def make_cutouts(production: Any, spec: dict) -> None:
    """One cutout per cast member a scene2d shot names: its portrait (else its sheet), background removed, cropped."""
    from services.music_production import ProductionError
    state = production.state
    cutouts = state.setdefault("cast_cutouts", {})
    wanted = cast_ids(spec)
    for cid in wanted:
        source = (state.get("cast_single") or {}).get(cid) or (state.get("cast") or {}).get(cid)
        if not source:
            raise ProductionError("cast_incomplete", f"scene2d: no portrait of {cid} to cut out")
        if (cutouts.get(cid) or {}).get("source") == source:
            continue
        digest = hashlib.sha256(source.encode()).hexdigest()[:12]
        reply = production.mcp(CUTOUT, {"version": 1, "intent_id": f"{production.id}-cutout-{cid}-{digest}",
                                        "input": {"workspace": production.ws, "source": source, "method": "auto", "crop": True}})
        result = reply.get("result") if isinstance(reply.get("result"), dict) else {}
        if not result.get("url"):
            raise ProductionError("scene2d_cutout_failed", f"{cid}: {json.dumps(reply)[:200]}")
        cutouts[cid] = {"source": source, "url": result["url"], "file": result.get("file")}
        production.save()
    if wanted:
        production.log(f"scene2d: cutouts of {', '.join(wanted)}")


def _made(state: dict, kind: str, field: str) -> dict[str, str]:
    """name -> the ``field`` of each spec model or set the run made."""
    return {name: entry[field] for name, entry in (state.get(kind) or {}).items() if isinstance(entry, dict) and entry.get(field)}


def _played_cast(state: dict) -> dict[str, str]:
    """cast id -> its cutout; an animatic made before the cutouts plays the portrait (else the sheet) as it is."""
    singles, cutouts = state.get("cast_single") or {}, state.get("cast_cutouts") or {}
    return {cid: (cutouts.get(cid) or {}).get("url") or singles.get(cid) or sheet for cid, sheet in (state.get("cast") or {}).items()}


def production_media(production: Any, stills: dict | None) -> dict:
    """The names a scene2d source may use, as URLs: spec models and sets, cast members, stills."""
    ws = production.ws
    models = {name: f"/api/v1/file/{quote(file)}?workspace={quote(ws)}" for name, file in _made(production.state, "models", "file").items()}
    return {"workspace": ws, "root": production.root, "models": models, "sets": _made(production.state, "sets", "url"),
            "cast": _played_cast(production.state), "stills": stills or {}}


def source_url(value: str, media: dict) -> str:
    """A URL as it is, then a spec model, a set, a cast member, a stills entry, else a file in the workspace."""
    if value.startswith(_URLS):
        return value
    for kind in ("models", "sets", "cast", "stills"):
        if value in media[kind]:
            return media[kind][value]
    root = media.get("root")
    if root is not None:
        path = (Path(root) / value).resolve()
        if path.is_relative_to(Path(root).resolve()) and path.is_file():
            return f"/api/v1/file/{quote(value)}?workspace={quote(media['workspace'])}"
    raise Scene2dError("invalid_spec", f"scene2d: {value!r} is not a URL, a model, a set, a cast id, a stills name or a workspace file")


def card_sources(shot: dict, media: dict, frame: str | None) -> dict[str, str]:
    """slot -> URL: the cast, then the background (given, the shot's still, or its drawn frame)."""
    config = shot["scene2d"]
    sources = {role: source_url(value, media) for role, value in (config.get("cast") or {}).items()}
    background = config.get("background") or shot.get("still")
    if background:
        sources["background"] = source_url(background, media)
    elif frame:
        sources["background"] = f"/api/v1/file/{quote(frame)}?workspace={quote(media['workspace'])}"
    else:
        raise Scene2dError("scene2d_background_missing", f"scene2d {shot.get('key')}: its background frame was not drawn")
    return sources


def _span(card: str, control: str) -> tuple[float, float] | None:
    spec = (card_entry(card).get("controls") or {}).get(control)
    if isinstance(spec, dict) and isinstance(spec.get("min"), (int, float)) and isinstance(spec.get("max"), (int, float)):
        return float(spec["min"]), float(spec["max"])
    return None


def _clamp(value: float, span: tuple[float, float]) -> float:
    return round(min(max(value, span[0]), span[1]), 3)


def compile_input(shot: dict, sources: dict[str, str], seconds: float, bpm: Any) -> tuple[dict, dict]:
    """The ``scenes.template.compile`` input for the shot, and the prepared request it was checked with.

    The card moves for at most its longest duration: a longer cut holds its last frame (the dry run says so)."""
    prepared = prepare_card(shot, sources)
    card = str(prepared.get("templateId"))
    controls = dict(shot["scene2d"].get("controls") or {})
    tempo = _span(card, "bpm")
    if tempo and "bpm" not in controls and isinstance(bpm, (int, float)) and not isinstance(bpm, bool) and bpm > 0:
        controls["bpm"] = _clamp(float(bpm), tempo)
    data = {"templateId": shot["scene2d"]["template"].strip(), "assets": sources, "controls": controls,
            "width": WIDTH, "height": HEIGHT, "fps": FPS}
    length = _span(card, "duration")
    if length:
        data["duration"] = _clamp(seconds, length)
    return data, prepared


def _media_frame(production: Any, shot: dict) -> str | None:
    return (production.state.get("frames") or {}).get(shot["key"]) if draws_frame(shot) else None


def scene_inputs(state: dict, shot: dict) -> str | None:
    """What a scene2d scene is made from besides its spec (its drawn frame, the cutouts): a re-export key."""
    if not is_scene2d(shot):
        return None
    played = set((shot["scene2d"].get("cast") or {}).values())
    cutouts = {cid: (entry or {}).get("url") for cid, entry in (state.get("cast_cutouts") or {}).items() if cid in played}
    frame = (state.get("frames") or {}).get(shot.get("key")) if draws_frame(shot) else None
    return "scene2d:" + hashlib.sha256(json.dumps([frame, cutouts], sort_keys=True).encode()).hexdigest()[:16]


def scene2d_document(production: Any, shot: dict, seconds: float, score: dict, stills: dict) -> dict:
    """The card compiled for this cut, kept in state by its input so a package or a resume does not compile again."""
    from services.music_production import ProductionError
    try:
        sources = card_sources(shot, production_media(production, stills), _media_frame(production, shot))
        data, prepared = compile_input(shot, sources, seconds, score.get("bpm"))
    except Scene2dError as error:
        raise ProductionError(error.code, str(error)) from error
    fingerprint = hashlib.sha256(json.dumps({"input": data, "recipe": RECIPE}, sort_keys=True).encode()).hexdigest()[:16]
    kept = production.state.setdefault("scene2d", {})
    record = kept.get(shot["key"]) or {}
    if record.get("fingerprint") != fingerprint or not isinstance(record.get("document"), dict):
        reply = production.mcp(COMPILE, {"version": 1, "input": {**data, "full": True}})
        result = reply.get("result") if isinstance(reply.get("result"), dict) else {}
        if not isinstance(result.get("document"), dict):
            raise ProductionError("scene2d_compile_failed", f"{shot['key']}: {json.dumps(reply)[:300]}")
        warnings = [str(item) for item in [*(prepared.get("warnings") or []), *(result.get("warnings") or [])]]
        record = {"fingerprint": fingerprint, "card": prepared.get("templateId"), "document": result["document"], "warnings": warnings}
        kept[shot["key"]] = record
        if warnings:
            production.log(f"scene2d {shot['key']}: {', '.join(warnings)}"[:200])
    document = copy.deepcopy(record["document"])
    document.update(name=shot["key"], duration=seconds)
    return document


def _planned(value: str, spec: dict, root: Any, workspace: str) -> tuple[str, str]:
    """(what a dry run shows, what the compiler checks) for one source before the run makes any picture."""
    if value.startswith(_URLS):
        return value, value
    cast = {entry.get("id") for entry in spec.get("cast") or [] if isinstance(entry, dict)}
    for kind, names in (("model", spec.get("models") or {}), ("set", spec.get("sets") or {}), ("cast", cast)):
        if value in names:
            return f"{kind} {value}" + (": its cutout, made in the run" if kind == "cast" else ""), PLACEHOLDER
    media = {"workspace": workspace, "root": root, "models": {}, "sets": {}, "cast": {}, "stills": spec.get("stills") or {}}
    url = source_url(value, media)
    return url, url


def _planned_sources(shot: dict, spec: dict, root: Any, workspace: str) -> tuple[dict[str, str], dict[str, str]]:
    config, shown, checked = shot["scene2d"], {}, {}
    for role, value in (config.get("cast") or {}).items():
        shown[role], checked[role] = _planned(value, spec, root, workspace)
    background = config.get("background") or shot.get("still")
    if background:
        shown["background"], checked["background"] = _planned(background, spec, root, workspace)
    else:
        shown["background"], checked["background"] = "frame: drawn from the shot's frame prompt", PLACEHOLDER
    return shown, checked


def _card_warnings(key: Any, card: str, warnings: list) -> list[dict]:
    """The compiler's warnings (``cutout_without_alpha:subject_1``) as dry-run rows."""
    rows = []
    for item in warnings:
        code, _, detail = str(item).partition(":")
        rows.append({"code": code, "key": key, "template": card, **({"detail": detail} if detail else {})})
    return rows


def dry_run_report(shot: dict, spec: dict, root: Any, workspace: str, seconds: float) -> tuple[dict, list[dict]]:
    """A scene2d window in a dry run: its card, where each picture comes from, and what the compiler warns."""
    key = shot.get("key")
    try:
        _config(shot)
        shown, checked = _planned_sources(shot, spec, root, workspace)
        prepared = prepare_card(shot, checked)
    except Scene2dError as error:
        code = "scene2d_invalid" if error.code == "invalid_spec" else error.code
        return {"template": shot["scene2d"].get("template")}, [{"code": code, "key": key, "message": str(error)[:240]}]
    card = str(prepared.get("templateId"))
    row = {"template": shot["scene2d"]["template"], "card": card, "sources": shown,
           "warnings": [str(item) for item in prepared.get("warnings") or []]}
    found = _card_warnings(key, card, row["warnings"])
    longest = _span(card, "duration")
    if longest and seconds > longest[1] + 0.05:
        found.append({"code": "scene2d_holds", "key": key, "template": card, "seconds": round(seconds - longest[1], 1), "limit": longest[1],
                      "hint": "the card moves for at most its longest duration and then holds: split the shot or cut sooner"})
    return row, found


def card_traits(card: str) -> dict:
    """The card's derived traits (``app/shared/video2d_template_traits.json``); {} while the file is missing."""
    try:
        traits = json.loads(TRAITS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entry = (traits.get("templates") or {}).get(card) if isinstance(traits, dict) else None
    return entry if isinstance(entry, dict) else {}


def card_of(shot: dict) -> str | None:
    """The card a scene2d shot plays (an alias resolved), or None when the shot does not validate."""
    try:
        return str(prepare_card(shot).get("templateId"))
    except Scene2dError:
        return None
