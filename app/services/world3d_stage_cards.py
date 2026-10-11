"""One Video 3D card per mold: ``stage-<mold>`` is the mold staged on ``two-shot`` with its default skin.

Every field is read from the mold (its marks, cameras and blocks), never written per card. The document behind a
card is built by ``world3d_stage_documents``; the traits here measure the camera that document opens with.
"""
from __future__ import annotations

import math
from functools import lru_cache

from services.set_molds import catalog

PREFIX = "stage-"
DEFAULT_CAMERA = "two_shot"
FIGURE = 1.7                                              # a model stands this tall (templateTraits MODEL_HEIGHT)
HEAD = 1.1                                                # the mold cameras look at a mark's face at this height
SHOT_FRACTIONS = (("close", 0.5), ("medium", 1.1), ("wide", 3.5))
SEATING_BLOCKS = ("audience", "bench")
SUBJECT_ROLES = ("subject_1", "subject_2")
BLOCK_WORDS = {
    "counter": ("mostrador", "a counter"), "bench": ("bancos", "benches"), "desk": ("mesa", "a desk"), "step": ("escalones", "steps"),
    "landing": ("rellano", "a landing"), "jamb": ("jambas", "door jambs"), "platform": ("tarima", "a platform"),
    "audience": ("público", "audience seats"), "seat": ("asientos", "seats"), "dashboard": ("salpicadero", "a dashboard"),
    "parapet": ("pretil", "a parapet"), "stairhead": ("caseta", "a stairhead"), "fountain": ("fuente", "a fountain"), "rock": ("roca", "a rock"),
}


def is_stage(template_id) -> bool:
    return isinstance(template_id, str) and template_id.startswith(PREFIX)


def mold_of(template_id: str) -> str:
    return template_id[len(PREFIX):]


def title(mold: dict, language: str) -> str:
    """A mold title is ``{es, en}``; a plain string serves both languages."""
    value = mold.get("title")
    if isinstance(value, dict):
        return str(value.get(language) or value.get("es") or value.get("en") or mold["id"])
    return str(value or mold["id"])


def speaking_marks(mold: dict) -> list[dict]:
    """Where someone stands or sits to speak: every mark but the entrance."""
    return [mark for mark in mold["marks"] if mark["id"] != "entrance"]


def measure(camera: dict, mark: dict) -> tuple[str, float]:
    """The shot size and distance from a camera to a mark's face, with the fractions ``templateTraits.ts`` uses."""
    eye, look = camera["position"], camera["lookAt"]
    forward = [b - a for a, b in zip(eye, look)]
    span = math.sqrt(sum(n * n for n in forward)) or 1
    target = [mark["position"][0], mark["position"][1] + HEAD, mark["position"][2]]
    depth = max(0.3, sum((t - e) * f for t, e, f in zip(target, eye, forward)) / span)
    fraction = 2 * depth * math.tan(math.radians(camera["fov"]) / 2) / FIGURE
    shot = next((size for size, limit in SHOT_FRACTIONS if fraction < limit), "far")
    return shot, round(depth, 1)


def trait_words(mold: dict) -> list[str]:
    """Search words a director tells apart: seated speakers, an entrance, a place that holds a crowd."""
    marks = speaking_marks(mold)
    words = []
    if any(mark["pose"] == "sit" for mark in marks):
        words.append("seated")
    if any(mark["id"] == "entrance" for mark in mold["marks"]):
        words.append("entrance")
    if any(block["kind"] in SEATING_BLOCKS for block in mold["blocks"]) or len(marks) >= 4:
        words.append("crowd")
    return words


def _furniture(mold: dict, language: str) -> str:
    kinds = list(dict.fromkeys(block["kind"] for block in mold["blocks"]))
    return ", ".join(BLOCK_WORDS.get(kind, (kind, kind))[0 if language == "es" else 1] for kind in kinds)


SHOT_WORDS = {"close": ("primer plano", "close-up"), "medium": ("plano medio", "medium shot"), "wide": ("plano general", "wide shot"),
              "far": ("plano lejano", "far shot")}


def _people(marks: list[dict], language: str) -> str:
    seated = sum(1 for mark in marks if mark["pose"] == "sit")
    if language == "es":
        how = "sentadas" if seated == len(marks) else "de pie" if not seated else f"{seated} sentada{'s' if seated > 1 else ''}"
        return f"{len(marks)} marcas, {how}"
    how = "seated" if seated == len(marks) else "standing" if not seated else f"{seated} seated"
    return f"{len(marks)} marks, {how}"


def line(mold: dict, language: str, shot: str) -> str:
    """What the stage is, who fits and how it is covered, from the mold alone."""
    es = language == "es"
    marks = speaking_marks(mold)
    entrance = any(mark["id"] == "entrance" for mark in mold["marks"])
    cameras = ", ".join(camera["id"] for camera in mold["cameras"])
    furniture = _furniture(mold, language)
    kind = "exterior" if mold["kind"] == "exterior" else "interior"
    if es:
        shape = kind + (f" con {furniture}" if furniture else " sin muebles")
        return (f"{title(mold, 'es')}: {shape}; {_people(marks, 'es')}{', con entrada' if entrance else ''}; "
                f"{SHOT_WORDS[shot][0]} desde {DEFAULT_CAMERA}. Cámaras: {cameras}.")
    shape = kind + (f" with {furniture}" if furniture else " with no furniture")
    return (f"{title(mold, 'en')}: {shape}; {_people(marks, 'en')}{', with an entrance' if entrance else ''}; "
            f"{SHOT_WORDS[shot][1]} from {DEFAULT_CAMERA}. Cameras: {cameras}.")


def card(mold: dict) -> dict:
    marks = speaking_marks(mold)
    cameras = {camera["id"]: camera for camera in mold["cameras"]}
    shot, distance = measure(cameras[DEFAULT_CAMERA], marks[0])
    subjects = min(len(SUBJECT_ROLES), len(marks))
    roles = [*SUBJECT_ROLES[:subjects], *["prop"] * (len(marks) - subjects)]
    moving = ["effects"] if mold.get("ambient", True) else []
    uses = [use for use, fits in (("dialogue", len(marks) >= 2 and shot != "far"), ("talk", subjects >= 1 and "close_1" in cameras),
                                  ("figure", subjects >= 1 and "wide" in cameras)) if fits]
    return {
        "id": PREFIX + mold["id"], "titleEs": title(mold, "es"), "titleEn": title(mold, "en"), "category": "cinema", "family": "stage",
        "variantOf": None, "format": "landscape", "width": 1280, "height": 720, "duration": 6, "playbackSpeed": 1, "dressing": None,
        "setting": mold["kind"], "lineEs": line(mold, "es", shot), "lineEn": line(mold, "en", shot), "notesEs": "", "notesEn": "",
        "preview": None, "reference": None, "roles": roles,
        "required": [{"id": role, "role": role, "media": "model3d"} for role in SUBJECT_ROLES[:subjects]],
        "dependencies": [], "tags": ["stage"], "shot": shot, "distance": distance, "moves": [], "moving": moving, "still": not moving,
        "subjects": subjects, "props": len(marks) - subjects, "screens": 0, "authoredFor": "model", "floor": "tiles", "uses": uses,
        "source": "builtin", "kind": "stage", "place": mold["id"], "cameras": list(cameras), "travel": False, "traitWords": trait_words(mold),
    }


@lru_cache(maxsize=1)
def stage_cards() -> tuple[dict, ...]:
    return tuple(card(mold) for mold in catalog())


def stage_card(template_id: str) -> dict | None:
    return next((item for item in stage_cards() if item["id"] == template_id), None)
