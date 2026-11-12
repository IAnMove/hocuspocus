"""The leg layout a mould knows, for a body whose skirt or dress hides the top of its legs.

The rig reads the legs from the front silhouette: the gap between them, up to the crotch. Under a skirt that gap
ends at the hem, so the rig took the hem for the crotch and put the hips there: a 1.62 m character in a knee-length
skirt got its hips at 0.49 m and its knees at 0.26 m, and every clip (a walk, a sit) bent it at the hem.

A mould (``blob_make.build_body``) built the legs itself and knows where they are: ``hints`` is its layout in the GLB's
metres, ``{leg_top, knee, leg_bottom, leg_d, torso_bottom}``. When the crotch the silhouette found lies well under
where the layout's legs meet the trunk (more than ``SKIRT_GAP`` of the height), the hips go to the leg top and the knees to the layout's knee, and the
surface between the hips and the old crotch (the skirt, and the thighs under it) is marked as a skirt for the weights
(``drape``), so it follows the thighs down to the hem instead of tearing there. A body whose legs the silhouette
already read (trousers, shorts, a bare leg) is left exactly as it was, and a GLB without hints (any model that did
not come out of a mould) never reaches this code.
"""
from __future__ import annotations

SKIRT_GAP = 0.08          # share of the height between the found crotch and the layout's leg top that means a hidden leg


def apply_leg_hints(found: dict, hints: dict | None) -> dict:
    """``detect_landmarks`` output with the legs moved to the mould's layout when a skirt hid them; else unchanged."""
    if not hints or not all(isinstance(hints.get(key), (int, float)) for key in ("leg_top", "knee")):
        return found
    points, height = found["points"], float(found["height"])
    hem, top = float(points["crotch"][1]), float(hints["leg_top"])
    # The gap between the legs ends where the legs meet the trunk: the leg top, or the trunk's bottom when the legs
    # run up into it. A crotch found well under that is a hem.
    meets = min(top, float(hints.get("torso_bottom", top)))
    if meets - hem < SKIRT_GAP * height:
        return found
    placed = {name: [float(value) for value in point] for name, point in points.items()}
    placed["crotch"][1] = top - float(hints.get("leg_d") or 0.05 * height) * 0.5
    for side in ("left", "right"):
        placed[f"{side}_hip"][1] = top
        placed[f"{side}_knee"][1] = float(hints["knee"])
    # Legs that show under the hem: the skirt follows the thighs to the hem. A long robe keeps its own drape.
    robe = dict(found["robe"]) if found.get("robe") else {"hem": hem, "skirt": True}
    return {**found, "points": placed, "robe": robe, "warnings": [*found.get("warnings", []), "legs_from_layout"]}
