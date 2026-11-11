"""Does a person in a Video 3D scene really sit on the seat, at the table, with no limb through the furniture?

Judged from the character's JOINTS at the pose it holds in the middle of the shot (``world3d_contact_poses``), against
the triangles of every piece of furniture, never from bind-pose boxes. ``world3d.scene.inspect`` and every patch reply
carry ``layout.contacts`` (one row per rigged character) and a warning for each problem; nothing is refused. Each
warning ends with the fix in numbers and field names to paste into ``world3d.scene.patch`` bindings, and the row's
``fix`` holds the same as bindings:

- ``seated_without_seat``: the hips are held low (a seated clip) and nothing is under them;
- ``floats_above_seat`` / ``sunk_into_seat``: the hips are that far over or into the seat under them;
- ``seat_height_unusual``: the seat is too high or too low for the sitter's legs (the feet leave the floor, or the knees
  come up to the chest);
- ``limb_through_object``: a limb (thigh, shin, forearm...) runs that deep inside a piece of furniture;
- ``inside_object``: a person standing still is inside a piece of furniture;
- ``at_height_unusual``, ``at_out_of_reach``, ``at_not_in_front``: the table of ``rest.at`` is not between the seated hips
  and chest, too far for the forearms, or not in front;
- ``furniture_size_unusual``: a seat or a table someone uses is still drawn 1.7 m tall (every model is 1.7 m x scale
  until it is sized).

``collide: false`` exempts a person from the limb and inside checks.
"""
from __future__ import annotations

import logging

import numpy as np

from services.world3d_contact_poses import Person, Piece, measure_scene
from services.world3d_rest_place import CLIP_NAME, HIP_ABOVE_SEAT, _edge_distance
from services.world3d_seats import table_top

LOG = logging.getLogger(__name__)
CONTACTS_DOC = ("layout.contacts: one row per rigged character, judged from its joints at the pose it holds mid-shot against the furniture's "
                "real faces: {id, pose seated|standing, hipsM, seat? {object, part, topM, gapM}, at? {object, topM, rangeM [lowest, highest], "
                "edgeM}, through? [{limb, object, part, depthM, at}], issues?, fix? [bindings to paste into world3d.scene.patch]}. Warnings: "
                "seated_without_seat, floats_above_seat, sunk_into_seat, seat_height_unusual, limb_through_object, inside_object, "
                "at_height_unusual, at_out_of_reach, at_not_in_front, furniture_size_unusual; each ends with the fix in numbers.")
MAX_PEOPLE = 8
TOLERANCE_M = 0.05            # hips this close to where the seat puts them are on it
THROUGH_M = 0.03              # a limb this deep in furniture goes through it
_CORE = ("back", "neck")       # the body itself, not a limb
REACH = 0.6                   # arm lengths from the seated chest to the table's edge that the forearms still rest on
MAX_WARNINGS = 12
_KIND_HEIGHTS = (("chair", 0.9), ("silla", 0.9), ("table", 0.75), ("mesa", 0.75), ("desk", 0.75), ("escritorio", 0.75), ("bed", 0.55),
                 ("cama", 0.55), ("sofa", 0.85), ("stool", 0.46), ("taburete", 0.46), ("bench", 0.45), ("banco", 0.45))


def scene_contacts(document: dict, workspace: str | None, workspace_dir) -> dict:
    """``{contacts, warnings}``; never raises."""
    if not workspace or workspace_dir is None:
        return {"contacts": [], "warnings": []}
    try:
        seconds = float(document.get("duration") or 0) / 2
        people, pieces, drawn = measure_scene(document, workspace, workspace_dir, seconds)
        report = _Report(pieces, drawn)
        for person in people[:MAX_PEOPLE]:
            report.check(person)
        report.tables(people[:MAX_PEOPLE])
        for row in report.rows:
            row.pop("seatTooHigh", None)
        return {"contacts": report.rows, "warnings": report.warnings[:MAX_WARNINGS]}
    except Exception:  # noqa: BLE001 - a contact check never fails an inspect
        LOG.exception("world3d contact check failed")
        return {"contacts": [], "warnings": []}


class _Report:
    def __init__(self, pieces: list[Piece], drawn: dict) -> None:
        self.pieces = {piece.id: piece for piece in pieces}
        self.drawn = drawn
        self.rows: list[dict] = []
        self.warnings: list[str] = []
        self.sized: set[str] = set()

    def warn(self, row: dict, line: str, *fixes: dict) -> None:
        self.warnings.append(line)
        row.setdefault("issues", []).append(line.split(":", 1)[0])
        for fix in fixes:
            if fix not in row.setdefault("fix", []):
                row["fix"].append(fix)

    def check(self, person: Person) -> None:
        # A sitter resolved by rest is seated even when its thighs slope down to the floor (a seat too high for its legs).
        seated = person.seated() or (isinstance(person.slot.get("rest"), dict) and (person.slot.get("clip") or {}).get("name") == CLIP_NAME)
        row = {"id": person.id, "pose": "seated" if seated else "standing", "hipsM": _rounded(person.joints["Hips"])}
        self.rows.append(row)
        rest = person.slot.get("rest") if isinstance(person.slot.get("rest"), dict) else {}
        for name, use in ((rest.get("on"), "on"), (rest.get("at"), "at")):
            if name in self.drawn:
                self._size(row, name, use)
        if seated:
            self._seat(row, person, rest)
        if person.slot.get("collide") is not False:
            self._through(row, person, seated)

    # ------------------------------------------------------------------------------------------------------------ seat

    def _seat(self, row: dict, person: Person, rest: dict) -> None:
        under = self._under(person)
        if under is None:
            self.warn(row, f"seated_without_seat: {person.id} is held seated (hips {person.hips_height:.2f} m above the floor) with nothing "
                           f"under the hips; add a seat and sit on it: {{object_id: \"seat_{person.id}\", add: true, furniture: {{kind: \"chair\"}}}} "
                           f"then {person.id}: rest {{pose: \"sit\", on: \"seat_{person.id}\"}}",
                      {"object_id": f"seat_{person.id}", "add": True, "furniture": {"kind": "chair"}},
                      {"object_id": person.id, "rest": {"pose": "sit", "on": f"seat_{person.id}"}})
            return
        piece, top, part = under
        gap = float(person.joints["Hips"][1] - top - HIP_ABOVE_SEAT * person.size["leg"])
        row["seat"] = {"object": piece.id, "part": piece.part_name(part), "topM": round(top - person.floor, 3), "gapM": round(gap, 3)}
        sit = {"object_id": person.id, "rest": {"pose": "sit", "on": piece.id, **({"at": rest["at"]} if rest.get("at") else {})}}
        if gap > TOLERANCE_M:
            self.warn(row, f"floats_above_seat: {person.id}'s hips are {gap:.2f} m above {piece.id} ({piece.part_name(part)}); give {person.id} "
                           f"rest {{pose: \"sit\", on: \"{piece.id}\"}}", sit)
        elif gap < -TOLERANCE_M:
            self.warn(row, f"sunk_into_seat: {person.id}'s hips are {-gap:.2f} m into {piece.id} ({piece.part_name(part)}); give {person.id} "
                           f"rest {{pose: \"sit\", on: \"{piece.id}\"}}", sit)
        if piece.id not in self.sized:
            self._seat_height(row, person, piece, top - person.floor)

    def _under(self, person: Person):
        """``(piece, seat top y, part)`` right under the hips, or None."""
        from services.world3d_mesh_solid import _hits
        hips = person.joints["Hips"]
        best = None
        for piece in self.pieces.values():
            depth, part = piece.depth(np.array([hips]))
            if depth[0] > 0:
                top = self._top_over(piece, hips)
                if best is None or top > best[1]:
                    best = (piece, top, int(part[0]))
                continue
            native = piece.frame.to_native([hips])[0]
            distances, owners = _hits(piece.mesh, native, np.array([0.0, -1.0, 0.0]))
            if not len(distances):
                continue
            top = float(hips[1] - distances.min() * piece.frame.factor)
            if top - person.floor > 0.08 and (best is None or top > best[1]):
                best = (piece, top, int(owners[distances.argmin()]))
        return best

    @staticmethod
    def _top_over(piece: Piece, point: np.ndarray) -> float:
        """The scene y of the first face above a point inside a piece (where its solid ends upward)."""
        from services.world3d_mesh_solid import _hits
        native = piece.frame.to_native([point])[0]
        distances, _ = _hits(piece.mesh, native, np.array([0.0, 1.0, 0.0]))
        return float(point[1] + (distances.min() if len(distances) else 0.0) * piece.frame.factor)

    def _seat_height(self, row: dict, person: Person, piece: Piece, seat: float) -> None:
        """The thighs slope a little toward the knees with the shins upright: the seat that gives that, against this one."""
        size, rest, factor = person.size, person.rest, person.frame.factor
        knee = float((rest["LeftLeg"][1] + rest["RightLeg"][1]) / 2 - person.body.box_low) * factor
        drop = float(rest["Hips"][1] - (rest["LeftUpLeg"][1] + rest["RightUpLeg"][1]) / 2) * factor
        flesh = HIP_ABOVE_SEAT * size["leg"]
        lowest, best, highest = (knee + share * size["thigh"] - flesh + drop for share in (-0.3, 0.1, 0.45))
        if lowest <= seat <= highest:
            return
        what = "the feet leave the floor" if seat > highest else "the knees come up toward the chest"
        row.setdefault("seatTooHigh", []).append(piece.id)
        fix = _resize(piece, best, seat, "seat")
        self.warn(row, f"seat_height_unusual: {piece.id}'s seat is {seat:.2f} m high and {person.id}'s knees are {knee:.2f} m high, so {what}; "
                       f"a seat for {person.id} is {best:.2f} m: give {piece.id} {_text(fix)}", {"object_id": piece.id, **fix})

    # ---------------------------------------------------------------------------------------------------------- limbs

    def _through(self, row: dict, person: Person, seated: bool) -> None:
        """Limbs (and, standing, the body) that run inside a piece of furniture or cross its faces."""
        found = self._limb_hits(person)
        # A body inside a piece is one warning (inside_object), not one per limb as well.
        inside = {piece.id for depth, label, piece, *_rest in found if not seated and label in _CORE and depth >= THROUGH_M}
        seen = set()
        for depth, label, piece, part, point, out in sorted(found, key=lambda item: -item[0]):
            key = ("body", piece.id) if piece.id in inside else (label, piece.id)
            if key in seen or len(seen) >= 4:
                continue
            seen.add(key)
            row.setdefault("through", []).append({"limb": label, "object": piece.id, "part": piece.part_name(part), "depthM": round(depth, 3),
                                                  "at": _rounded(point)})
            if piece.id in row.get("seatTooHigh", ()) and label.endswith("thigh"):
                continue                                         # the seat's height is the cause, and it has its warning
            self._through_warning(row, person, seated, (label, piece, part, depth, out))

    def _limb_hits(self, person: Person) -> list[tuple]:
        found = []
        for piece in self.pieces.values():
            for label, start, end in person.segments():
                hit = _limb_hit(piece, start, end)
                if hit is not None:
                    found.append((hit[0], label, piece, *hit[1:]))
        return found

    def _through_warning(self, row: dict, person: Person, seated: bool, hit: tuple) -> None:
        label, piece, part, depth, out = hit
        seats = {name: item.slot for name, item in self.pieces.items()}
        text, fix = _standing_fix(person, piece) if not seated else _seated_fix(person, piece, depth, out, seats)
        where = f"{piece.id} ({piece.part_name(part)})"
        if not seated and label in _CORE and depth >= THROUGH_M:
            self.warn(row, f"inside_object: {person.id} stands inside {where}, its {label} {depth:.2f} m deep; {text}", *([fix] if fix else []))
            return
        how = f"goes {depth:.2f} m inside" if depth >= THROUGH_M else "passes right through"
        self.warn(row, f"limb_through_object: {person.id}'s {label} {how} {where}; {text}, or give {person.id} collide: false", *([fix] if fix else []))

    # ---------------------------------------------------------------------------------------------------------- tables

    def tables(self, people: list[Person]) -> None:
        """``rest.at``: the top between the seated hips and chest, in front, within forearm reach; one height for everyone at it."""
        groups: dict[str, list] = {}
        for person in people:
            name = (person.slot.get("rest") or {}).get("at")
            row = next(item for item in self.rows if item["id"] == person.id)
            if name in self.pieces and row["pose"] == "seated":
                groups.setdefault(name, []).append((person, row))
        for name, members in groups.items():
            self._table(self.pieces[name], members)

    def _table(self, piece: Piece, members: list) -> None:
        top = table_top(piece.box, piece.frame.factor, piece.mesh, piece.parts)
        if top is None:
            return
        corners = piece.frame.to_world([[top.low[0], top.y, top.low[1]], [top.high[0], top.y, top.low[1]],
                                        [top.high[0], top.y, top.high[1]], [top.low[0], top.y, top.high[1]]])
        top_y, floor = float(corners[:, 1].mean()), piece.floor_y()
        spans = [_span(person) for person, _row in members]
        low, high = max(span[0] for span in spans), min(span[2] for span in spans)
        common = min(max(float(np.mean([span[1] for span in spans])), low), high) if low <= high else float(np.mean([span[1] for span in spans]))
        for (person, row), (lowest, _ideal, highest) in zip(members, spans):
            row["at"] = {"object": piece.id, "topM": round(top_y - floor, 3), "rangeM": [round(lowest - floor, 3), round(highest - floor, 3)]}
            if piece.id not in self.sized and not lowest <= top_y <= highest:
                fix = _resize(piece, common - floor, top_y - floor, "height")
                self.warn(row, f"at_height_unusual: {piece.id}'s top is {top_y - floor:.2f} m high; seated, {person.id}'s hips are at "
                               f"{person.joints['Hips'][1] - floor:.2f} m and chest at {person.joints['Spine2'][1] - floor:.2f} m, so a table "
                               f"for {'everyone at it' if len(members) > 1 else person.id} is {common - floor:.2f} m: give {piece.id} {_text(fix)}",
                          {"object_id": piece.id, **fix})
            self._reach(row, person, piece, corners)

    def _reach(self, row: dict, person: Person, piece: Piece, corners: np.ndarray) -> None:
        chest = person.joints["Spine2"]
        edge = _edge_distance(corners, chest, person.forward)
        seat = (person.slot.get("rest") or {}).get("on")
        if edge is None:
            turn = {"beside": {"object": piece.id, "facing": "object"}}
            self.warn(row, f"at_not_in_front: {piece.id} is not in front of {person.id}; turn the seat toward it: give {seat} {_text(turn)}",
                      {"object_id": seat, **turn})
            return
        row["at"]["edgeM"] = round(edge, 3)
        reach, wanted = REACH * person.size["arm"], 0.3 * person.size["arm"]
        if edge <= reach:
            return
        near = self.pieces.get(seat)
        beside = (near.slot.get("beside") if near else None) or {}
        gap = beside.get("gap", 0.0) - (edge - wanted) if beside.get("object") == piece.id else None
        binding = {**beside, "gap": round(gap, 2)} if gap is not None else {"object": piece.id, "facing": "object", "gap": 0.0}
        self.warn(row, f"at_out_of_reach: {person.id}'s chest is {edge:.2f} m from {piece.id}'s edge and the forearms reach "
                       f"{reach:.2f} m; give {seat} {_text({'beside': binding})}", {"object_id": seat, "beside": binding})

    # ------------------------------------------------------------------------------------------------------------ size

    def _size(self, row: dict, name: str, use: str) -> None:
        height, scale = self.drawn[name]
        if name in self.sized or abs(height - 1.7) > 0.01 or abs(scale - 1) > 1e-6:
            return
        self.sized.add(name)
        piece = self.pieces.get(name)
        named = " ".join(str(piece.slot.get(key) or "") for key in ("id", "sourceUrl")).lower() if piece else name.lower()
        wanted = next((value for word, value in _KIND_HEIGHTS if word in named), 0.75 if use == "at" else 0.9)
        self.warn(row, f"furniture_size_unusual: {name} is drawn 1.70 m tall (every model is 1.7 m x scale until it is sized); a "
                       f"{'table' if use == 'at' else 'seat'} like it is about {wanted:g} m: give {name} height {wanted:g}, then read the "
                       f"seat and table warnings again", {"object_id": name, "height": wanted})


def _limb_hit(piece: Piece, start: np.ndarray, end: np.ndarray):
    """``(depth m, part, point, way out)`` of a limb inside a piece or right through it, or None."""
    points = start + (end - start) * np.linspace(0.0, 1.0, 9)[:, None]
    depth, parts, exits = piece.depth_exits(points)
    crossed = piece.crossed(start, end)
    deepest = int(np.argmax(depth))
    if depth[deepest] < THROUGH_M and not len(crossed):
        return None
    if depth[deepest] > 0:
        return float(depth[deepest]), int(parts[deepest]), points[deepest], exits[deepest]
    return 0.0, int(crossed[0]), (start + end) / 2, np.zeros(3)


def _standing_fix(person: Person, piece: Piece) -> tuple[str, dict | None]:
    """Step the person out of the piece's footprint, away from its middle."""
    corners = piece.frame.to_world([[x, piece.box["min"][1], z] for x in (piece.box["min"][0], piece.box["max"][0])
                                    for z in (piece.box["min"][2], piece.box["max"][2])])[:, [0, 2]]
    centre, here = corners.mean(axis=0), person.joints["Hips"][[0, 2]]
    away = here - centre
    away = away / np.linalg.norm(away) if np.linalg.norm(away) > 1e-6 else np.array([0.0, 1.0])
    distance = float(((corners - centre) @ away).max() - (here - centre) @ away) + 0.3      # its far edge plus a body
    position = [float(value) for value in person.slot.get("position") or [0, 0, 0]]
    moved = [round(float(position[0] + away[0] * distance), 3), position[1], round(float(position[2] + away[1] * distance), 3)]
    return f"move {person.id} {distance:.2f} m out of it: position {_js(moved)}", {"object_id": person.id, "position": moved}


def _seated_fix(person: Person, piece: Piece, depth: float, out: np.ndarray, seats: dict) -> tuple[str, dict | None]:
    """A sitter's limb in a table or another piece: raise or lower its top when the way out is up or down, else move it away."""
    rest = person.slot.get("rest") if isinstance(person.slot.get("rest"), dict) else {}
    if piece.id == rest.get("on"):
        return f"move {person.id} or {piece.id} apart (rest re-places the sitter; a beside gap moves a chair)", None
    gap = _gap_fix(rest, piece, depth, seats)
    if gap is not None:
        return gap
    if not out.any():
        return f"move {person.id} or {piece.id} apart (rest re-places the sitter; a beside gap moves a chair)", None
    top = float(piece.frame.to_world([[0.0, piece.box["max"][1], 0.0]])[0][1]) - piece.floor_y()
    wanted = top + (depth + 0.05) * (-1 if out[1] > 0 else 1)
    if abs(out[1]) > 0.7 and abs(piece.floor_y() - person.floor) < 0.05 and wanted >= 0.2:
        fix = _resize(piece, wanted, top, "height")       # a table top in the knees or the forearms: its height
        return f"{'lower' if out[1] > 0 else 'raise'} {piece.id} to {wanted:.2f} m: give {piece.id} {_text(fix)}", {"object_id": piece.id, **fix}
    position = [float(value) for value in piece.slot.get("position") or [0, 0, 0]]
    step = -out * (depth + 0.05)
    moved = [round(float(position[axis] + step[axis]), 3) for axis in range(3)]
    return f"move {piece.id} {depth + 0.05:.2f} m away: position {_js(moved)}", {"object_id": piece.id, "position": moved}


def _gap_fix(rest: dict, piece: Piece, depth: float, seats: dict) -> tuple[str, dict] | None:
    """The sitter's seat stands beside this piece and follows it: open the gap between them instead."""
    near = (seats.get(rest.get("on")) or {}).get("beside") or {}
    if near.get("object") != piece.id:
        return None
    binding = {"beside": {**near, "gap": round(float(near.get("gap", 0.0)) + max(depth, 0.05) + 0.05, 2)}}
    return f"move {rest['on']} back from {piece.id}: give {rest['on']} {_text(binding)}", {"object_id": rest["on"], **binding}


def _span(person: Person) -> tuple[float, float, float]:
    """Scene heights a table top may have for this sitter: a little over the hips, about the elbows, the chest."""
    hips, shoulders = float(person.joints["Hips"][1]), float((person.joints["LeftArm"][1] + person.joints["RightArm"][1]) / 2)
    reach = shoulders - hips
    return hips + 0.15 * reach, hips + 0.4 * reach, max(float(person.joints["Spine2"][1]), hips + 0.55 * reach)


def _resize(piece: Piece, wanted: float, current: float, key: str) -> dict:
    """The binding that brings a height (a seat, a top) to ``wanted`` metres: the furniture's own size, else ``height``."""
    furniture = piece.slot.get("furniture") if isinstance(piece.slot.get("furniture"), dict) else None
    if furniture:
        given = {name: furniture[name] for name in ("kind", "width", "depth", "color") if name in furniture}
        return {"furniture": {**given, ("seat" if key == "seat" and "seat" in furniture else "height"): round(wanted, 2)}}
    return {"height": round(piece.drawn_height() * wanted / max(current, 1e-3), 2)}


def _text(binding: dict) -> str:
    """A binding as the warnings write it: ``height 0.75``, ``beside {object: "table", gap: -0.1}``."""
    return ", ".join(f"{key} {_js(value)}" for key, value in binding.items())


def _js(value) -> str:
    if isinstance(value, dict):
        return "{" + ", ".join(f"{key}: {_js(item)}" for key, item in value.items()) + "}"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _rounded(point) -> list:
    return [round(float(value), 3) for value in point]
