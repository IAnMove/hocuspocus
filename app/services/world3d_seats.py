"""Where a person sits on a piece of furniture, and where the top of a table is, from the furniture's own GLB.

``seat_surface`` finds the sitting surface of a model object, in this order:

1. ``surface: {part}`` (a part name or index of ``glb_parts``) or ``surface: {point: [x, y, z]}`` (scene metres);
2. a part named like a seat (``seat``, ``mattress``, ``cushion``, ``asiento``, ``colchon``...);
3. the flat upward faces of the mesh (``world3d_mesh_solid.flat_tops``) at a sittable height (0.1-1.2 m), at least
   ``HIPS_M`` wide both ways and open above for a body: the one with the most open area wins (a chair's seat, not its
   backrest's top edge; a bed's cover, not the frame under it);
4. without a readable mesh, the top of the part boxes, or the whole box top when it is sittable (a stool, a crate).

A one-mesh model whose seat is not its box top was found from its faces only: ``guessed`` is true and the caller warns
``seat_surface_guessed``. Geometry standing above the seat along one edge is the backrest; the sitter faces away from it
(``front``). A headboard across the short end of a bed is not a backrest: a bed is sat on along its long side.
``table_top`` is the highest flat face wide enough to put things on (``TOP_M``). All sizes are in the GLB's own units;
``factor`` turns them into metres.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from services.world3d_mesh_solid import Mesh, flat_tops

HIPS_M = 0.18                 # a seat narrower than this either way does not hold hips
SEAT_RANGE_M = (0.1, 1.2)     # a seat's height above the furniture's foot, in metres
CLEAR_M = 0.25                # room above a seat for the body
TOP_M = 0.3                   # a table top is at least this wide both ways
BACK_M = 0.12                 # geometry this far above the seat is a backrest (or arms, a headboard)
_SEAT_WORDS = re.compile(r"seat|mattress|cushion|asiento|colch[oó]n|coj[ií]n|saddle|sill[ií]n|futon|banco", re.IGNORECASE)
_TOP_WORDS = re.compile(r"(^|[^a-z])top($|[^a-z])|tabletop|tablero|encimera|desktop|countertop", re.IGNORECASE)


@dataclass
class Surface:
    y: float                                  # native height of the top
    low: list                                 # native [x, z]
    high: list
    how: str                                  # what found it: part, faces, box, point
    guessed: bool = False
    part: int | None = None
    name: str | None = None
    front: list | None = None                 # native unit [x, z] the sitter faces (away from a backrest), None: no backrest
    extra: dict = field(default_factory=dict)

    @property
    def center(self) -> list:
        return [(self.low[0] + self.high[0]) / 2, (self.low[1] + self.high[1]) / 2]

    @property
    def size(self) -> list:
        return [self.high[0] - self.low[0], self.high[1] - self.low[1]]


def seat_surface(box: dict, factor: float, mesh: Mesh | None, parts: list[dict], surface=None) -> Surface | None:
    """The sitting surface of a model whose native box is ``box`` and whose renderer factor is ``factor``."""
    found = _chosen_part(box, mesh, parts, surface, _SEAT_WORDS) if surface is None or "part" in (surface or {}) else None
    if found is None and surface is None:
        found = _from_faces(box, factor, mesh, parts) if mesh is not None else _from_boxes(box, factor, parts)
    if found is not None:
        found.front = _front(found, factor, mesh, box)
    return found


def table_top(box: dict, factor: float, mesh: Mesh | None, parts: list[dict]) -> Surface | None:
    """The top a person sits at (a table, a desk, a bar): a part named like a top, else the highest face wide enough."""
    named = _chosen_part(box, mesh, parts, None, _TOP_WORDS)
    if named is not None:
        return named
    if mesh is None:
        top = max(parts, key=lambda part: part["max"][1], default=None)
        return _box_surface(top, "box") if top else None
    wide = [item for item in flat_tops(mesh) if min(_size(item)) * factor >= TOP_M]
    if not wide:
        return None
    item = wide[0]
    return Surface(item["y"], item["low"], item["high"], "faces", part=item["parts"][0] if len(item["parts"]) == 1 else None)


def _size(item: dict) -> list:
    return [item["high"][0] - item["low"][0], item["high"][1] - item["low"][1]]


def _chosen_part(box: dict, mesh: Mesh | None, parts: list[dict], surface, words) -> Surface | None:
    """``surface.part`` (a name or index) or the first part whose name matches ``words``: the top of its faces, or of its box."""
    wanted = (surface or {}).get("part")
    for part in parts:
        named = part.get("name") or ""
        if wanted is not None and wanted not in (part["index"], named):
            continue
        if wanted is None and not words.search(named):
            continue
        tops = flat_tops(mesh, {part["index"]}) if mesh is not None else []
        if tops:
            best = max(tops, key=lambda item: item["area"])
            return Surface(best["y"], best["low"], best["high"], "part", part=part["index"], name=part.get("name"))
        return _box_surface(part, "part")
    return None


def _box_surface(part: dict, how: str) -> Surface:
    return Surface(part["max"][1], [part["min"][0], part["min"][2]], [part["max"][0], part["max"][2]], how,
                   part=part.get("index"), name=part.get("name"))


def _from_faces(box: dict, factor: float, mesh: Mesh, parts: list[dict]) -> Surface | None:
    """The flat face with the most open area at a sittable height."""
    floor = box["min"][1]
    best, best_area = None, 0.0
    for item in flat_tops(mesh):
        height = (item["y"] - floor) * factor
        if not SEAT_RANGE_M[0] <= height <= SEAT_RANGE_M[1] or min(_size(item)) * factor < HIPS_M:
            continue
        area = item["area"] * _open_share(mesh, item, factor) * factor * factor
        if area > best_area:
            best, best_area = item, area
    if best is None or best_area < HIPS_M * HIPS_M:
        return None
    on_box_top = abs(best["y"] - box["max"][1]) * factor < 0.01
    single = len(parts) <= 1
    return Surface(best["y"], best["low"], best["high"], "faces", guessed=single and not on_box_top,
                   part=best["parts"][0] if len(best["parts"]) == 1 else None)


def _open_share(mesh: Mesh, item: dict, factor: float) -> float:
    """The share of a 5 x 5 grid over the face's footprint that lies on the face and has room above it for a body."""
    from services.world3d_mesh_solid import _hits
    xs = np.linspace(item["low"][0], item["high"][0], 7)[1:-1]
    zs = np.linspace(item["low"][1], item["high"][1], 7)[1:-1]
    lift = 0.004 / factor
    on, open_ = 0, 0
    for x in xs:
        for z in zs:
            origin = np.array([x, item["y"] + lift, z])
            below, _ = _hits(mesh, origin, np.array([0.0, -1.0, 0.0]))
            if not len(below) or below.min() > 3 * lift + 0.012:
                continue
            on += 1
            above, _ = _hits(mesh, origin, np.array([0.0, 1.0, 0.0]))
            open_ += int(not len(above) or above.min() * factor >= CLEAR_M)
    return open_ / on if on else 0.0


def _from_boxes(box: dict, factor: float, parts: list[dict]) -> Surface | None:
    """No mesh to read: the widest part top at a sittable height that is not the tallest part, or the whole box top."""
    floor, tallest = box["min"][1], max((part["max"][1] for part in parts), default=box["max"][1])
    tops = [part for part in parts if SEAT_RANGE_M[0] <= (part["max"][1] - floor) * factor <= SEAT_RANGE_M[1]
            and min(part["max"][0] - part["min"][0], part["max"][2] - part["min"][2]) * factor >= HIPS_M
            and (len(parts) == 1 or part["max"][1] < tallest - BACK_M / factor)]
    if not tops:
        return None
    chosen = max(tops, key=lambda part: (part["max"][0] - part["min"][0]) * (part["max"][2] - part["min"][2]))
    return _box_surface(chosen, "box")


def _front(seat: Surface, factor: float, mesh: Mesh | None, box: dict) -> list | None:
    """Away from what stands above the seat along one edge (a backrest), snapped to the nearest axis; None without one."""
    if mesh is None:
        return None
    points = mesh.triangles.reshape(-1, 3)
    margin = 0.06 / factor
    near = ((points[:, 0] >= seat.low[0] - margin) & (points[:, 0] <= seat.high[0] + margin)
            & (points[:, 2] >= seat.low[1] - margin) & (points[:, 2] <= seat.high[1] + margin)
            & (points[:, 1] >= seat.y + BACK_M / factor))
    if not near.any():
        return None
    above = points[near]
    centre = np.array(seat.center)
    lean = np.array([above[:, 0].mean(), above[:, 2].mean()]) - centre
    axis = int(np.argmax(np.abs(lean) / np.maximum(np.array(seat.size), 1e-9)))
    if abs(lean[axis]) < 0.2 * seat.size[axis]:
        return None                                            # arms on both sides, or something in the middle
    along = seat.size[1 - axis]
    if seat.size[axis] > 1.25 * along:
        return None                                            # a headboard across a bed's short end
    front = [0.0, 0.0]
    front[axis] = -1.0 if lean[axis] > 0 else 1.0
    return front
