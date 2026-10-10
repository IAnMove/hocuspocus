"""Parallax sets for a production: painted layers stood at depths, so a moving camera sees the place shift.

``spec.sets`` maps a name to ``{kind: "parallax", prompt, far, mid, near, ground, seed}``:

- ``far`` describes the distance and the sky in one picture ("mountains and a castle under a sunset sky"): it
  wraps the scene as the environment, behind everything.
- ``mid`` describes what stands at middle distance ("ruined arches and tall pines"): drawn on a flat chroma-key
  green, keyed out, and stood as a cutout some metres behind the cast.
- ``near`` (optional) describes foreground pieces at the sides ("branches and ferns at the edges"): drawn on the
  key and stood between the camera and the cast, where a lateral move slides it fastest.
- ``ground`` describes the floor ("mossy flagstones"), drawn as a seamless tile like a diorama's.
- ``prompt`` is the place, added to the layers so they belong together.

A scene3d ``background`` naming the set puts the far picture in the sky, the ground under the cast and the cutout
layers across the camera's line of sight (``ui/src/features/scene3d/parallaxSet.ts``); a near layer is left out
of a shot whose camera would cross it.
"""
from __future__ import annotations

from typing import Any

from services.production_diorama import GROUND_SIZE, GROUND_STAGING

LAYER_SIZE = "1664x928"
KEY = "#00ff00"
KEY_STAGING = ("drawn on a perfectly flat, uniform, solid bright chroma-key green background (#00FF00) that fills every part of "
               "the picture not covered by the subject: no gradient, no shadows or glow on the background, no sky, no ground, "
               "no people, nothing in sharp focus behind the subject")
FAR_STAGING = ("A wide painted view of the distance only, filling the whole picture: the sky above and the far scenery along "
               "the bottom third, no ground nearby, no objects in the foreground, no people")
MID_STAGING = "Wide shot, the pieces standing side by side across the whole width with open space in the middle"
NEAR_STAGING = "Wide shot, the pieces at the left and right edges and along the bottom, the middle of the picture empty"
FIELDS = {"kind", "prompt", "far", "mid", "near", "ground", "seed"}
DEPTHS = ("mid", "near")
RECIPE = 1      # the picture recipe above; a change draws every parallax set again


def is_parallax(entry: Any) -> bool:
    return isinstance(entry, dict) and entry.get("kind") == "parallax"


def check_parallax(name: str, entry: dict, text) -> str | None:
    """Why the entry is not a parallax set, or None."""
    if set(entry) - FIELDS:
        return f"sets.{name}: a parallax set takes only {', '.join(sorted(FIELDS))}"
    if not all(text(entry.get(field)) for field in ("prompt", "far", "mid", "ground")):
        return f"sets.{name}: a parallax set needs a prompt (the place), a far view, a mid layer and a ground"
    if "near" in entry and not text(entry["near"]):
        return f"sets.{name}.near describes the foreground pieces"
    return None


def recipe(entry: dict) -> dict:
    """What a parallax set's fingerprint covers: the entry and the picture recipe."""
    return {**entry, "recipe": RECIPE}


def is_built(record: dict) -> bool:
    return bool(record.get("layers") and record.get("sky"))


def picture_jobs(production: Any, name: str, entry: dict, look: str, choice: tuple) -> dict[str, str | None]:
    """Image jobs for the set's far view, layers and ground, keyed ``set:<name>:<part>``."""
    seed = entry.get("seed", 11)
    attempt = production._attempt("set_attempts", name)
    place = entry["prompt"].rstrip(". ")
    parts = {"far": (f"{entry['far'].rstrip('. ')}, in {place}. {look} {FAR_STAGING}", LAYER_SIZE),
             "mid": (f"{entry['mid'].rstrip('. ')}, in {place}, {KEY_STAGING}. {look} {MID_STAGING}", LAYER_SIZE)}
    if entry.get("near"):
        parts["near"] = (f"{entry['near'].rstrip('. ')}, in {place}, {KEY_STAGING}. {look} {NEAR_STAGING}", LAYER_SIZE)
    parts["ground"] = (f"A seamless tileable texture seen from straight above: {entry['ground'].rstrip('. ')}. {GROUND_STAGING}", GROUND_SIZE)
    return {f"set:{name}:{part}": production.image(f"set-{name}-{part}", prompt, None, size, seed + index, *choice, attempt)
            for index, (part, (prompt, size)) in enumerate(parts.items())}


def build(production: Any, name: str, record: dict) -> None:
    """The set's pieces from its pictures: the far view and the layers go to uploads, the ground becomes a slab."""
    from services.diorama_set import build_ground

    pictures = record.pop("pictures", {})
    ground = f"set-{production.id}-{name}-ground.glb"
    try:
        record["ground"] = {"source": f"/api/v1/file/{ground}?workspace={production.ws}",
                            **build_ground(production.root / ground, production.root / pictures["ground"])}
        record["layers"] = [{"source": production.upload(pictures[depth])[1], "depth": depth} for depth in DEPTHS if depth in pictures]
        record["sky"] = production.upload(pictures["far"])[1]
    except (OSError, ValueError, KeyError) as error:
        record["error"] = f"parallax build failed: {error}"
        return
    record["key"] = KEY
    production.log(f"set {name}: parallax of {len(record['layers'])} layers")
