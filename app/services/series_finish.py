"""The finish over a Series 2D shot, chosen for the series (``look.finish``) and for one shot (``layout2d.finish``).

Every 2D shot used to get the same paper finish (texture 0.08, grain 0.03, vignette 0.12), and nobody could see or
change it. A finish choice is one of:

- ``"paper"``: that same finish. It is the default: a series and a shot that choose nothing still get it;
- ``"none"``: a clean picture;
- the id of a Video 2D finish in ``app/shared/finish_presets.json`` (``film``, ``noir``, ``oldDoc``...), without its
  letterbox bars;
- ``{"texture": {"kind", "amount"}, "grain": {"amount", "size"}, "vignette": {"amount", "softness"}}``: your own
  amounts of any of the three (``kind`` paper, film-dust or scratches; amounts 0-1, size 0.5-4, softness 0-1).

A shot's own choice wins over the series'. A take's fingerprint (``series_take_inputs``) takes the finish only when
it is not the paper default, so a series that never chose one keeps every digest, and choosing another renders its
2D shots again.
"""
from __future__ import annotations

import copy
from typing import Any

PAPER = {"texture": {"kind": "paper", "amount": 0.08}, "grain": {"amount": 0.03, "size": 1.2},
         "vignette": {"amount": 0.12, "softness": 0.7}, "applyToTexts": False}
DEFAULT = "paper"
NAMED = ("paper", "none")
TEXTURES = ("paper", "film-dust", "scratches")
# Each part's numbers: (key, low, high, default when left out; None when it must be given).
_PARTS: dict[str, tuple[tuple[str, float, float, float | None], ...]] = {
    "texture": (("amount", 0, 1, None),),
    "grain": (("amount", 0, 1, None), ("size", 0.5, 4, 1.2)),
    "vignette": (("amount", 0, 1, None), ("softness", 0, 1, 0.7)),
}


def presets() -> dict[str, dict]:
    from services.video2d_preset_catalog import finish_presets
    return finish_presets()


def _choices_text() -> str:
    return f"paper, none, one of {', '.join(sorted(presets()))} or an object with texture, grain and/or vignette"


def _number(value: Any, key: str, low: float, high: float, default: float | None, where: str) -> float:
    if value is None and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"{where}.{key} must be a number from {low:g} to {high:g}")
    return float(value)


def _part(name: str, value: Any, where: str) -> dict[str, Any]:
    where = f"{where}.{name}"
    keys = (*(("kind",) if name == "texture" else ()), *(key for key, *_ in _PARTS[name]))
    if not isinstance(value, dict) or set(value) - set(keys):
        raise ValueError(f"{where} must be an object with {', '.join(keys)}")
    found: dict[str, Any] = {}
    if name == "texture":
        if value.get("kind") not in TEXTURES:
            raise ValueError(f"{where}.kind must be one of {', '.join(TEXTURES)}")
        found["kind"] = value["kind"]
    for key, low, high, default in _PARTS[name]:
        found[key] = _number(value.get(key), key, low, high, default, where)
    return found


def check_finish(value: Any, where: str = "finish") -> str | dict[str, Any]:
    """The stored form of a finish choice; anything else is refused with what it may be."""
    if isinstance(value, str) and (value in NAMED or value in presets()):
        return value
    if isinstance(value, dict) and value and not set(value) - set(_PARTS):
        return {name: _part(name, value[name], where) for name in _PARTS if name in value}
    raise ValueError(f"{where} must be {_choices_text()}")


def store_look(project: dict[str, Any]) -> None:
    """``look.finish`` checked in place. An empty ``look`` is removed, so a series that never chose one stays as it
    was; other keys of ``look`` are kept as they are."""
    look = project.get("look")
    if look is None:
        project.pop("look", None)
        return
    if not isinstance(look, dict):
        raise ValueError('look must be an object, like {"finish": "none"}')
    look = dict(look)
    if look.get("finish") is None:
        look.pop("finish", None)
    else:
        look["finish"] = check_finish(look["finish"], "look.finish")
    if look:
        project["look"] = look
    else:
        project.pop("look", None)


def series_choice(series: dict[str, Any]) -> str | dict[str, Any]:
    look = series.get("look") if isinstance(series.get("look"), dict) else {}
    return look["finish"] if look.get("finish") is not None else DEFAULT


def choice(series: dict[str, Any], shot: dict[str, Any]) -> str | dict[str, Any]:
    """The shot's own finish, else its series'."""
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    return layout["finish"] if layout.get("finish") is not None else series_choice(series)


def resolve(value: str | dict[str, Any]) -> dict[str, Any] | None:
    """The Video 2D ``finish`` of a stored choice; None for a clean picture."""
    if value == "paper":
        return copy.deepcopy(PAPER)
    if value == "none":
        return None
    if isinstance(value, dict):
        return {**copy.deepcopy(value), "applyToTexts": False}
    found = presets().get(value)
    if found is None:
        raise ValueError(f"unknown finish {value!r}: it must be {_choices_text()}")
    # Never a finish's letterbox: the episode cuts its 2D shots with 3D and video shots that have no bars, and in a
    # vertical frame a 2.39 band would hide three quarters of the picture.
    return {key: copy.deepcopy(part) for key, part in found.items() if key != "letterbox"}


def shot_finish(series: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any] | None:
    return resolve(choice(series, shot))


def fingerprint(series: dict[str, Any], shot: dict[str, Any]) -> Any:
    """What the shot's take depends on: None for the paper default (the digest it always had), else the finish."""
    finish = shot_finish(series, shot)
    if finish == PAPER:
        return None
    return finish if finish is not None else "none"
