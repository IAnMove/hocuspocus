"""The pose guides of a walk animation: what an animation job (``services/character_animation_job.py``) sends with each pose of a walk.

A catalog entry with ``"guide": "walk"`` (the walks of ``app/shared/character_animations.json``) is made pose by pose with a second
picture after the character's own: the pose drawn by ``services/walk_guides.py`` from the camera of the sheet's direction, at the
phase of the cycle the pose is (``phase_of``). The prompt starts by saying what each picture is (``guide.text`` of the catalog, for
the guide's ``style``), so the model takes the character from picture 1 and the pose and the direction from picture 2.

A walk pose is then measured: how wide the legs of the keyed figure are against how wide the guide's are at that phase
(``leg_spread``/``expected_spread``). A pose drawn in the wrong direction (a back view that turned three-quarter) or at the wrong
moment of the step (a passing pose drawn as a full stride) is far off and is drawn again with another seed, ``guide.tries`` times in
all; the closest one stays when none is within ``guide.tolerance``. A custom animation, an idle and an expression have no guide.

The guide is a file of the workspace (``<kit>-<animation>-<pose>-guide-<job>.png``), and the take records it with the measures, so
what the model was shown can be opened again.
"""
from __future__ import annotations

import os
from typing import Any

from PIL import Image

from services.character_animation_directions import contract_of
from services.character_animations import catalog
from services.walk_guides import TURN, expected_spread, guide_image, leg_spread, parse_size, phase_of


def spec() -> dict[str, Any]:
    return catalog().get("guide") or {}


def guide_for(definition: dict[str, Any], pose_id: str, *, workspace_root: str, name: str) -> dict[str, Any] | None:
    """The guide of one pose of ``definition``, written as ``name`` in the workspace once; None for an animation without a guide."""
    if definition.get("custom") or definition.get("guide") != "walk":
        return None
    direction = contract_of(definition["id"], definition).get("dir")
    ids = [pose["id"] for pose in definition["poses"]]
    if direction not in TURN or pose_id not in ids:
        return None
    phase = phase_of(ids.index(pose_id), len(ids))
    style = spec().get("style") or "skeleton"
    path = os.path.join(workspace_root, name)
    if not os.path.isfile(path):
        guide_image(direction, phase, parse_size(definition["resolution"]), style).save(path)
    return {"file": name, "direction": direction, "phase": round(phase, 4), "style": style, "expected": round(expected_spread(direction, phase), 3)}


def guided_prompt(prompt: str, guide: dict[str, Any] | None, extra: int) -> str:
    """The prompt of a pose with a guide: first what picture 1, picture 2 and any other pictures are."""
    if not guide:
        return prompt
    words = spec().get("text", {}).get(guide["style"], "")
    others = f" {spec().get('extra', '')}" if extra else ""
    return f"{words}{others} {prompt}".strip()


def gait_of(guide: dict[str, Any], keyed_path: str) -> dict[str, Any]:
    """How a keyed walk pose compares with its guide: the legs' width (share of the figure's height) drawn and expected."""
    with Image.open(keyed_path) as opened:
        measured = leg_spread(opened.convert("RGBA"), int(catalog()["sheet"]["alphaFloor"]))
    tolerance = float(spec().get("tolerance", 0.18))
    return {"expected": guide["expected"], "measured": round(measured, 3), "ok": abs(measured - guide["expected"]) <= tolerance}


def tries(guide: dict[str, Any] | None) -> int:
    """How many seeds a pose may take: one without a guide."""
    return max(1, int(spec().get("tries", 3))) if guide else 1


__all__ = ["gait_of", "guide_for", "guided_prompt", "spec", "tries"]
