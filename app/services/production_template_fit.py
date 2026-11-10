"""A 3D shot against the card it names, before any GPU work.

``production_quality_gate`` calls this for every ``scene3d`` shot of a plan, the fill shots included. The compiler
(``ui/scripts/production-scene3d.mjs``) only runs after the song, the cast and the models, so what it would throw is
caught here from the shipped catalogue (``world3d_templates.json`` plus the ``stage-*`` cards), once per plan:

- ``unknown_template`` (blocking): ``scene3d.template`` or ``scene3d.world`` is not a shipped card (a personal template
  is not one: the compiler reads the shipped ids only). The closest ids come with it.
- ``cast_role_not_on_card`` (blocking): the shot binds ``subject_1``, ``subject_2``, ``background`` or ``prop`` (a
  ``subject``, or a ``cast`` key) and the card has no slot with that role. A key that is not one of those four names is
  an object id of the template, and a card does not list every id (``required`` holds only the unbound slots), so it
  is left to the compiler; so is a key with ``add: true``, a group, and a shot with its own ``slots`` or a ``document``.
  A ``stage-*`` card is compiled on ``two-shot``, so its roles are that card's, not the stage's marks.
- ``template_format`` (warning): the frame the shot asks for (``width`` and ``height``, else the production's 16:9) is
  not the one the card is drawn for. The compiler adapts the camera, but a card drawn for the frame frames better.
- ``template_repeated`` (warning): one template with one camera in two shots in a row.

``camera_key`` is what a shot does with the camera, for ``looks_samey`` and ``template_repeated``.
"""
from __future__ import annotations

import difflib
import json
from typing import Any, Callable

ROLES = ("subject_1", "subject_2", "background", "prop")
SUGGESTIONS = 3
CLOSE = 0.5               # difflib's ratio a card id needs to be offered as «did you mean»
FRAME = "landscape"       # the montage every production makes is 1920x1080 (production_stage_scenes.scene_document)
ROOM_CAMERA = "two_shot"  # world3d_stage_cards.DEFAULT_CAMERA: a room shot with no roomCamera


def template_id(config: dict) -> str | None:
    """The template a shot plays: a shipped card, or the card a full document was made from."""
    value = config.get("template") or (config.get("document") or {}).get("templateId")
    return str(value) if value else None


def camera_key(config: dict) -> str:
    """What the shot does with the camera, as one comparable string: the room camera, the camera card, the framing, the
    lens and an explicit camera."""
    parts = [config.get("roomCamera") or ROOM_CAMERA, config.get("camera_template"), config.get("frame"), config.get("lens"),
             config.get("camera")]
    return json.dumps(parts, sort_keys=True, default=str)


def consecutive_runs(shots: list[dict], key_of: Callable[[dict], Any]) -> list[tuple[Any, list[str]]]:
    """``(key, shot keys)`` of consecutive native 3D shots with the same ``key_of``; any other shot ends a run."""
    runs: list = []
    for shot in shots:
        config = shot.get("scene3d") if shot.get("kind") == "scene3d" and isinstance(shot.get("scene3d"), dict) else None
        if config is None:
            runs.append(None)
            continue
        key = key_of(config)
        if runs and runs[-1] and runs[-1][0] == key:
            runs[-1][1].append(str(shot.get("key")))
        else:
            runs.append((key, [str(shot.get("key"))]))
    return [run for run in runs if run]


def repeated_templates(shots: list[dict], samey: list[list[str]]) -> list[dict]:
    """``template_repeated``: one template with one camera in two shots in a row, the place aside. A run that
    ``looks_samey`` already reports (same place too, over the limit) is not said twice."""
    found = []
    for (template, camera), keys in consecutive_runs(shots, lambda config: (template_id(config), camera_key(config))):
        if template and len(keys) >= 2 and not any(set(keys) <= set(run) for run in samey):
            found.append({"code": "template_repeated", "template": template, "camera": json.loads(camera), "shots": keys,
                          "hint": "the same template with the same camera in consecutive shots reads as one shot cut in two: "
                                  "change the camera (roomCamera, camera_template or frame) or the template"})
    return found


def fit_problems(spec: dict, shots: list[dict]) -> list[dict]:
    """The blocking checks: a card that does not exist, a role it does not have."""
    uses = _uses(spec, shots)
    if not uses:
        return []
    cards = _catalogue()
    return _unknown(uses, cards) + _role_problems(uses, cards)


def fit_warnings(spec: dict, shots: list[dict]) -> list[dict]:
    """The format warnings, one per template and frame."""
    uses = _uses(spec, shots)
    if not uses:
        return []
    cards = _catalogue()
    found: dict[tuple, list[str]] = {}
    for key, config in uses:
        card = cards.get(config.get("template")) if isinstance(config.get("template"), str) else None
        asked = _frame(config, card) if card else None
        if asked and asked[0] != card.get("format"):
            found.setdefault((config["template"], card.get("format"), *asked), []).append(key)
    return [{"code": "template_format", "template": template, "card_format": drawn, "shot_format": wanted, "shots": keys,
             "hint": _format_hint(wanted, drawn, explicit)} for (template, drawn, wanted, explicit), keys in found.items()]


def _uses(spec: dict, shots: list[dict]) -> list[tuple[str, dict]]:
    """``(shot key, scene3d)`` of the plan's native 3D shots and of its fill, named as ``unknown_camera`` names them."""
    fills = spec.get("fill") if isinstance(spec.get("fill"), list) else []
    rows = [(str(shot.get("key")), shot) for shot in shots] + [(f"fill[{index}]", item) for index, item in enumerate(fills)
                                                               if isinstance(item, dict)]
    return [(label, shot["scene3d"]) for label, shot in rows if shot.get("kind") == "scene3d" and isinstance(shot.get("scene3d"), dict)]


def _catalogue() -> dict[str, dict]:
    from services.world3d_template_catalog import builtin_cards      # cached: the JSON is read once
    return {card["id"]: card for card in builtin_cards()}


def _unknown(uses: list[tuple[str, dict]], cards: dict[str, dict]) -> list[dict]:
    """A template or world no shipped card has. The compiler reads a world as it reads a template, but never a ``stage-*``
    card as one (a stage is a template only)."""
    found: dict[tuple[str, str], list[str]] = {}
    for key, config in uses:
        for field in ("template", "world"):
            name = config.get(field)
            if isinstance(name, str) and name.strip() and not _exists(name, cards, field):
                found.setdefault((field, name), []).append(key)
    return [_unknown_problem(field, name, keys, cards) for (field, name), keys in found.items()]


def _exists(name: str, cards: dict[str, dict], field: str) -> bool:
    return name in cards and (field == "template" or cards[name].get("kind") != "stage")


def _unknown_problem(field: str, name: str, keys: list[str], cards: dict[str, dict]) -> dict:
    quoted, shot_names, sentence = _words()
    pool = [card_id for card_id in cards if _exists(card_id, cards, field)]
    close = difflib.get_close_matches(name, pool, n=SUGGESTIONS, cutoff=CLOSE)
    mean = f" Did you mean {' or '.join(quoted([item]) for item in close)}?" if close else ""
    role = "the template" if field == "template" else "the world (the template whose place the shot plays in)"
    return {"code": "unknown_template", "field": field, "template": name, "shots": keys, "suggestions": close,
            "message": sentence(f"{shot_names(keys)} names {role} \"{name}\", which is not a Video 3D card.{mean} The 3D export "
                                "would fail after the GPU work."),
            "hint": "search the shipped cards (world3d.templates.suggest, world3d.templates.catalog) and copy an id"}


def _role_problems(uses: list[tuple[str, dict]], cards: dict[str, dict]) -> list[dict]:
    found: dict[tuple[str, str], list[str]] = {}
    for key, config in uses:
        template = config.get("template")
        card = cards.get(template) if isinstance(template, str) and "slots" not in config else None
        if card is None:
            continue
        have = _roles(card, cards)
        for role in dict.fromkeys(_asked_roles(config)):
            if role not in have:
                found.setdefault((template, role), []).append(key)
    return [_role_problem(template, role, keys, _roles(cards[template], cards)) for (template, role), keys in found.items()]


def _roles(card: dict, cards: dict[str, dict]) -> list[str]:
    """The roles a cast is bound to. A ``stage-*`` card is compiled on ``two-shot``: its marks are not slots."""
    if card.get("kind") == "stage":
        from services.world3d_stage_documents import BASE
        card = cards.get(BASE) or card
    return list(dict.fromkeys(card.get("roles") or []))


def _asked_roles(config: dict) -> list[str]:
    """The roles the shot binds by name: a ``subject`` is ``subject_1``; a ``cast`` key that is a role name binds that
    role unless the entry adds a new object or is a group (every member added)."""
    asked = ["subject_1"] if isinstance(config.get("subject"), str) else []
    cast = config.get("cast") if isinstance(config.get("cast"), dict) else {}
    for key, entry in cast.items():
        adds = isinstance(entry, dict) and (entry.get("add") or "sources" in entry)
        if key in ROLES and not adds:
            asked.append(key)
    return asked


def _role_problem(template: str, role: str, keys: list[str], have: list[str]) -> dict:
    quoted, shot_names, sentence = _words()
    has = f"only has the roles {quoted(have)}" if have else "has no role to cast"
    return {"code": "cast_role_not_on_card", "template": template, "role": role, "roles": have, "shots": keys,
            "message": sentence(f"{shot_names(keys)} casts \"{role}\", but the template \"{template}\" {has}. The 3D export would "
                                "fail after the GPU work: cast a role the card has, give an extra object an id of its own with "
                                "add: true, or pick a card that has the role."),
            "hint": "world3d.templates.suggest finds a card by how many speakers it holds (speakers: 2 for subject_2)"}


def _frame(config: dict, card: dict) -> tuple[str, bool]:
    """``(portrait or landscape, asked)``: the frame ``width`` and ``height`` ask for (a side left out keeps the card's),
    else the production's own."""
    width, height = config.get("width"), config.get("height")
    if width is None and height is None:
        return FRAME, False
    width = width if _measure(width) else card.get("width", 0)
    height = height if _measure(height) else card.get("height", 0)
    return ("portrait" if height > width else "landscape"), True


def _measure(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _format_hint(wanted: str, drawn: str, explicit: bool) -> str:
    where = "the shot asks for a" if explicit else "the production frame is a 16:9"
    how = "the export adapts its camera" if explicit else "its clip is cropped to fill the frame"
    return (f"{where} {wanted} frame and the card is drawn {drawn}: {how}, but a {wanted} card frames better "
            f"(world3d.templates.suggest with format: {wanted})")


def _words():
    from services.production_quality_gate import _quoted, _sentence, _shot_names     # the gate's own wording
    return _quoted, _shot_names, _sentence
