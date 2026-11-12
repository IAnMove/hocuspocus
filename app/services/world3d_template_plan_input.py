"""The request of ``world3d.templates.plan`` read into plain values, or refused with the code of the field.

``{shots: [{key, text, speakers?, subjects?, place?, shot?, moving?}], format?, avoid?, per_shot?, seed?, language?}``.
``speakers`` says who talks as ``world3d.templates.suggest`` does (0 an establishing shot, 1 a talk shot, 2 or more a
dialogue); ``subjects`` is how many subject slots the cast needs (0 to 2) and defaults to what the speakers imply.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.world3d_template_catalog import World3DTemplateError
from services.world3d_template_places import read_place
from services.world3d_template_vocabulary import FORMATS, SHOT_SIZES

MAX_SHOTS = 60
MAX_TEXT = 400
MAX_AVOID = 1000          # the library has about 830 cards
DEFAULT_PER_SHOT = 3
MAX_SEED = 2 ** 31 - 1


@dataclass(frozen=True)
class Need:
    """One shot as a writer asks for it, with the place and the filters it implies."""
    key: str
    text: str
    use: str | None
    subjects: int | None
    shot: str | None
    moving: bool | None
    place_key: str
    place_words: tuple[str, ...]

    @property
    def query(self) -> str:
        return " ".join((self.text, *self.place_words)).strip()


@dataclass(frozen=True)
class Request:
    needs: tuple[Need, ...]
    format: str | None
    avoid: frozenset[str]
    per_shot: int
    seed: int
    language: str


def _whole(value, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise World3DTemplateError(f"invalid_{name}", f"{name} must be an integer from {low} to {high}")
    return value


def _text(value, name: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise World3DTemplateError(f"invalid_{name}", f"{name} must be text of at most {limit} characters")
    return value.strip()


def _one_of(value, allowed: tuple[str, ...], name: str) -> str | None:
    if value in (None, ""):
        return None
    if value not in allowed:
        raise World3DTemplateError(f"invalid_{name}", f"{name} must be one of {', '.join(allowed)}")
    return value


def _use_and_subjects(shot: dict) -> tuple[str | None, int | None]:
    speakers = shot.get("speakers")
    use = None
    if speakers is not None:
        use = "establishing" if _whole(speakers, "speakers", 0, 4) == 0 else "talk" if speakers == 1 else "dialogue"
    subjects = shot.get("subjects")
    if subjects is not None:
        return use, _whole(subjects, "subjects", 0, 2)
    return use, min(speakers, 2) if speakers else None


def _need(shot, seen: set[str]) -> Need:
    if not isinstance(shot, dict):
        raise World3DTemplateError("invalid_shots", "each shot must be an object with a key and a text")
    key = shot.get("key")
    if not isinstance(key, str) or not key.strip() or len(key) > 80 or key in seen:
        raise World3DTemplateError("invalid_shot_key", "each shot needs its own key of at most 80 characters")
    seen.add(key)
    text, place = _text(shot.get("text"), "text", MAX_TEXT), _text(shot.get("place"), "place", 120)
    moving = shot.get("moving")
    if moving is not None and not isinstance(moving, bool):
        raise World3DTemplateError("invalid_moving", "moving must be true or false: whether the shot should move")
    use, subjects = _use_and_subjects(shot)
    place_key, place_words = read_place(text, place)
    return Need(key, text, use, subjects, _one_of(shot.get("shot"), SHOT_SIZES, "shot"), moving, place_key, place_words)


def _avoid(value) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, list) or len(value) > MAX_AVOID or not all(isinstance(item, str) for item in value):
        raise World3DTemplateError("invalid_avoid", f"avoid must be a list of at most {MAX_AVOID} template ids")
    return frozenset(value)


def read_request(data: dict) -> Request:
    shots = data.get("shots")
    if not isinstance(shots, list) or not 1 <= len(shots) <= MAX_SHOTS:
        raise World3DTemplateError("invalid_shots", f"shots must be a list of 1 to {MAX_SHOTS} shots")
    seen: set[str] = set()
    language = data.get("language") or "en"
    if language not in ("es", "en"):
        raise World3DTemplateError("invalid_language", "language must be es or en")
    per_shot = data.get("per_shot")
    seed = data.get("seed")
    return Request(
        needs=tuple(_need(shot, seen) for shot in shots), format=_one_of(data.get("format"), FORMATS, "format"),
        avoid=_avoid(data.get("avoid")), per_shot=DEFAULT_PER_SHOT if per_shot is None else _whole(per_shot, "per_shot", 1, 3),
        seed=0 if seed is None else _whole(seed, "seed", 0, MAX_SEED), language=language)
