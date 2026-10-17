"""MCP tool that puts a Video 2D card on a Series shot as a new take (``series.shot.card.apply``).

A thin projection of ``POST /api/v1/series/{series}/episodes/{episode}/shots/{shot}/card`` (routers/series_shot_card.py), the route the
Wizard's ``apply_series_shot_card`` posts to: one operation behind both doors. Like the other series tools it is merged into
services/series_commands.py through ``OPERATIONS`` and ``RUNNERS``.
"""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

_ID = {"type": "string", "minLength": 1, "maxLength": 160}
_SHOT = {"anyOf": [{"type": "string", "minLength": 1, "maxLength": 160}, {"type": "integer", "minimum": 1, "maximum": 999}]}
_WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 120}
_CAST = {"type": "array", "maxItems": 6, "items": {"type": "object", "additionalProperties": False, "required": ["characterId"], "properties": {
    "slot": {"type": "string", "maxLength": 40}, "characterId": _ID,
    "animation": {"anyOf": [{"type": "string", "maxLength": 64}, {"type": "object"}]}, "poseId": {"type": "string", "maxLength": 160}}}}

OPERATIONS: dict[str, tuple[dict[str, Any], list[str], bool, str]] = {
    "series.shot.card.apply": (
        {"workspace": _WORKSPACE, "series_id": _ID, "episode_id": _ID, "shot": _SHOT, "card": {"type": "string", "minLength": 1, "maxLength": 120},
         "controls": {"type": "object"}, "cast": _CAST, "assets": {"type": "object", "additionalProperties": {"type": "string"}},
         "language": {"type": "string", "maxLength": 40}, "approve": {"type": "boolean"}},
        ["workspace", "series_id", "episode_id", "shot", "card"], True,
        "Put a Video 2D card on one 2D shot as a NEW TAKE (a candidate), in one call: it replaces scenes.template.compile, editing, "
        "export, series.asset.import and series.take.approve. card is any id of scenes.templates.catalog (walk-cycle-sheet, "
        "walk-two-pose, walk-toward-camera, walk-follow-back, walk-behind-foreground, character-reaction...). cast binds the card's "
        "character slots (subject_1...) to series characters {slot, characterId, animation?, poseId?}; without cast the shot's own "
        "people fill them. The sheet cards play the character's APPROVED animation sheet (walk by default for the walk cards; "
        "character-reaction needs animation: wave, angry...); a pending or rejected sheet is refused. The other cards draw its pose "
        "picture (poseId, else the shot's pose). The shot's location plate is the background; assets {slot: workspace file or URL} "
        "fills foreground and props. controls are the card's own; the length follows the shot. The shot's spoken lines must be "
        "recorded first (series.shot.voice). The scene is saved as <series>-<episode>-<shot>-card-<card>.scene.json and opens in "
        "Video 2D; applying again replaces it. approve true approves the take, only when the owner turned on the one-shot mode "
        "(agent_autonomy = one_shot); otherwise a person approves it in Series Lab, and a take a person approved is never replaced. "
        "Example, a walk-in for shot 3: {shot: 3, card: \"walk-cycle-sheet\", cast: [{slot: \"subject_1\", characterId: \"gloria\", "
        "animation: \"walk\"}]}. Returns status completed (take: attemptId, approved, bindings, scene) or exporting: call again with "
        "the same input to finish.",
    ),
}


def _apply(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    path = (f"/api/v1/series/{quote(str(data['series_id']), safe='')}/episodes/{quote(str(data['episode_id']), safe='')}"
            f"/shots/{quote(str(data['shot']), safe='')}/card")
    body = {key: data[key] for key in ("workspace", "card", "controls", "cast", "assets", "language", "approve") if key in data}
    return request("POST", path, body=body)


RUNNERS: dict[str, Callable[..., Any]] = {"series.shot.card.apply": _apply}
