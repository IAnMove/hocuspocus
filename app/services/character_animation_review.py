"""Approve or reject one animation of a saved character: the one operation behind every door.

A person does it in Characters › Animaciones (the panel edits the kit and stamps ``reviewedBy: person``), an MCP client does it with
``characters.animation.review`` and the Wizard with ``review_character_animation``: both reach ``review_kit_animation`` through
``POST /api/v1/character-kits/animations/review`` with the actor ``agent``, and so does the animation job's ``autoApprove``
(``services/character_animation_job.py``). An agent decides only in «Modo un solo disparo» (``agent_autonomy`` = ``one_shot``,
``services/agent_autonomy.py``); in ``review`` mode this refuses with the way to do it by hand.

Only the review fields change (``reviewState``, ``reviewedBy``, ``reviewNote``, ``reviewedAt``). The sheet and the keyed poses stay, so a
rejected animation keeps its poses for the next try (``pose`` remakes one of them). The animation is saved on the kit as it is now in
the library, as the job saves it: a character edited meanwhile keeps its edits.
"""
from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from services import agent_autonomy
from services.character_animations import MAX_REVIEW_NOTE, REVIEWERS
from services.character_kit_library import CharacterKitRevisionConflict, patch_character_kit, read_character_kit_library

DECISIONS = {"approve": "approved", "reject": "rejected"}
REVIEW_OFF = ("Agent review is off (agent_autonomy is review): a person approves or rejects an animation in Personajes › Animaciones. "
              "Apruébala en Personajes › Animaciones o activa el modo un solo disparo (Ajustes › Servicios).")
_SAVE_TRIES = 4


class AnimationReviewError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def _stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _reviewed(entry: dict[str, Any], state: str, actor: str, note: str) -> dict[str, Any]:
    """The animation with this review; the stale note of an earlier review goes with it."""
    kept = {key: value for key, value in entry.items() if key not in {"reviewState", "reviewedBy", "reviewNote", "reviewedAt"}}
    return {**kept, "reviewState": state, "reviewedBy": actor, "reviewedAt": _stamp(), **({"reviewNote": note} if note else {})}


def _check_request(decision: str, note: str, actor: str, services: Mapping[str, Any] | None) -> str:
    if decision not in DECISIONS:
        raise AnimationReviewError("invalid_decision", "decision is approve or reject")
    if actor not in REVIEWERS:
        raise AnimationReviewError("invalid_actor", f"actor is one of {', '.join(REVIEWERS)}")
    if len(note) > MAX_REVIEW_NOTE:
        raise AnimationReviewError("note_too_long", f"The note is up to {MAX_REVIEW_NOTE} characters")
    if actor == "agent" and not agent_autonomy.is_one_shot(services):
        raise AnimationReviewError("agent_review_off", REVIEW_OFF, 403)
    return DECISIONS[decision]


def _person_decided(entry: dict[str, Any]) -> bool:
    """A review a person gave (also one saved before the reviewer was recorded: only a person could give it then)."""
    return entry.get("reviewState") in DECISIONS.values() and entry.get("reviewedBy", "person") == "person"


def review_kit_animation(workspace_dir: str, kit_id: str, animation_id: str, decision: str, note: str = "", actor: str = "person", *,
                         services: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Approve or reject ``animation_id`` of the kit. ``actor`` is ``person`` or ``agent``; an agent needs ``agent_autonomy`` =
    ``one_shot`` in ``services`` and cannot overturn what a person decided (the owner's word stays)."""
    note = " ".join(str(note or "").split())
    state = _check_request(decision, note, actor, services)
    for _attempt in range(_SAVE_TRIES):
        library = read_character_kit_library(workspace_dir)
        kit = (library.get("kits") or {}).get(kit_id)
        if not kit:
            raise AnimationReviewError("kit_not_found", f"Character Kit {kit_id} is not in this workspace", 404)
        entry = (kit.get("animations") or {}).get(animation_id)
        if not entry:
            raise AnimationReviewError("animation_not_found", f"{kit.get('name') or kit_id} has no {animation_id} animation to review", 404)
        if actor == "agent" and _person_decided(entry):
            raise AnimationReviewError("person_decided", f"A person already {entry['reviewState']} {animation_id}: only a person changes that", 409)
        reviewed = _reviewed(entry, state, actor, note)
        provenance = [*(kit.get("provenance") or []), {"method": "character-animation-review", "animation": animation_id, "decision": decision, "by": actor}]
        changed = {**kit, "animations": {**kit["animations"], animation_id: reviewed}, "updatedAt": _stamp(), "provenance": provenance[-500:]}
        try:
            saved = patch_character_kit(workspace_dir, kit_id, changed, base_revision=int(library["revision"]), make_active=False)
        except CharacterKitRevisionConflict:
            continue  # the library moved on since it was read: read it again
        return {"kitId": kit_id, "animation": animation_id, "reviewState": state, "reviewedBy": actor, "reviewedAt": reviewed["reviewedAt"],
                "reviewNote": reviewed.get("reviewNote", ""), "revision": saved.get("revision")}
    raise AnimationReviewError("save_conflict", "The character changed while it was being reviewed; try again", 409)
