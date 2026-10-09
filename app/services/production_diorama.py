"""Diorama sets for a production: house blocks wearing generated facades on a tiled ground, under a painted sky.

``spec.sets`` maps a name to ``{kind: "diorama", prompt, houses, ground, sky, seed}``:

- ``houses`` lists 2-8 facade descriptions ("a pale yellow two-storey house with a green door"). Each is drawn
  straight on, filling the picture, and becomes a box of that facade 6-10 m tall (``diorama_set.build_house``).
- ``ground`` describes the floor ("worn terracotta tiles"), drawn as a seamless top-down tile.
- ``sky`` describes the sky ("a deep blue summer night with a big moon"), drawn with nothing else in it.
- ``prompt`` is the place, added to every picture so the pieces belong together.

A scene3d ``background`` naming the set stands the houses in a ring around the action, outside where the camera
and the cast go, on the ground, with the sky behind (``ui/src/features/scene3d/dioramaSet.ts``); ``layout: "open"``
leaves the back of the ring empty so the ground meets the sky.
"""
from __future__ import annotations

from typing import Any

FACADE_SIZE = "768x1024"
GROUND_SIZE = "1024x1024"
SKY_SIZE = "1664x928"
HEIGHTS = (7.5, 9.0, 6.5, 10.0, 8.0, 7.0, 9.5, 6.0)    # metres, by house; a varied roofline
FACADE_STAGING = ("flat frontal elevation of the front facade, straight-on orthographic view, the facade fills the whole "
                  "picture edge to edge, no sky, no ground, no street, no people, nothing in front of it")
GROUND_STAGING = "seamless tileable top-down texture, flat even lighting, no objects, no shadows, no people"
SKY_STAGING = "only the sky, seen from the ground looking up a little, no buildings, no ground, no trees, no people"
FIELDS = {"kind", "prompt", "houses", "ground", "sky", "seed"}


def is_diorama(entry: Any) -> bool:
    return isinstance(entry, dict) and entry.get("kind") == "diorama"


def check_diorama(name: str, entry: dict, text) -> str | None:
    """Why the entry is not a diorama set, or None."""
    houses = entry.get("houses")
    if set(entry) - FIELDS:
        return f"sets.{name}: a diorama takes only {', '.join(sorted(FIELDS))}"
    if not isinstance(houses, list) or not 2 <= len(houses) <= 8 or not all(text(house) for house in houses):
        return f"sets.{name}.houses lists 2-8 facade descriptions"
    if not all(text(entry.get(field)) for field in ("prompt", "ground", "sky")):
        return f"sets.{name}: a diorama needs a prompt (the place), a ground and a sky"
    return None


def is_built(record: dict) -> bool:
    return bool(record.get("houses") and record.get("sky"))


def picture_jobs(production: Any, name: str, entry: dict, look: str, choice: tuple) -> dict[str, str | None]:
    """Image jobs for the set's facades, ground and sky, keyed ``set:<name>:<part>``."""
    seed = entry.get("seed", 11)
    attempt = production._attempt("set_attempts", name)
    place = entry["prompt"].rstrip(". ")
    parts = {f"house-{index + 1}": (f"The front of {house.rstrip('. ')}, in {place}. {look} {FACADE_STAGING}", FACADE_SIZE)
             for index, house in enumerate(entry["houses"])}
    parts["ground"] = (f"{entry['ground'].rstrip('. ')}, the floor of {place}. {look} {GROUND_STAGING}", GROUND_SIZE)
    parts["sky"] = (f"{entry['sky'].rstrip('. ')}, the sky over {place}. {look} {SKY_STAGING}", SKY_SIZE)
    return {f"set:{name}:{part}": production.image(f"set-{name}-{part}", prompt, None, size, seed + index, *choice, attempt)
            for index, (part, (prompt, size)) in enumerate(parts.items())}


def build(production: Any, name: str, record: dict) -> None:
    """The set's GLBs from its pictures; the sky goes to uploads like a painted set."""
    from services.diorama_set import build_ground, build_house

    pictures = record.pop("pictures", {})
    stem = f"set-{production.id}-{name}"
    houses = []
    try:
        for index in range(len([part for part in pictures if part.startswith("house-")])):
            file = f"{stem}-house-{index + 1}.glb"
            size = build_house(production.root / file, production.root / pictures[f"house-{index + 1}"], HEIGHTS[index % len(HEIGHTS)])
            houses.append({"source": _url(production, file), **size})
        ground = f"{stem}-ground.glb"
        record["ground"] = {"source": _url(production, ground), **build_ground(production.root / ground, production.root / pictures["ground"])}
    except (OSError, ValueError, KeyError) as error:
        record["error"] = f"diorama build failed: {error}"
        return
    record.update(houses=houses, sky=production.upload(pictures["sky"])[1])
    production.log(f"set {name}: diorama of {len(houses)} houses")


def _url(production: Any, file: str) -> str:
    return f"/api/v1/file/{file}?workspace={production.ws}"
