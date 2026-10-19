"""How much an agent (an MCP client, the Wizard) may decide on its own: the ``agent_autonomy`` setting of the services config.

* ``review`` (the default): a person approves what an agent makes, in the app. An agent cannot approve or reject.
* ``one_shot`` («Modo un solo disparo»): the agent approves what a person normally approves, so one request can go from the idea to a
  finished piece. Every approval it gives is stamped ``reviewedBy: agent`` with its note, so the owner can audit and revert it.

One reader for every door: the settings route stores the value through ``normalize``, and the services that gate an agent's decision
(``services/character_animation_review.py``, the animation job's ``autoApprove``) read it through ``autonomy_of``. Pure functions on
the services dict, so they import nothing from the launch module.
"""
from __future__ import annotations

from typing import Any, Mapping

KEY = "agent_autonomy"
REVIEW = "review"
ONE_SHOT = "one_shot"
MODES = (REVIEW, ONE_SHOT)
DEFAULT = REVIEW


def normalize(value: Any) -> str:
    """A stored or submitted value as a mode; anything that is not exactly ``one_shot`` is the safe default, ``review``."""
    return ONE_SHOT if isinstance(value, str) and value.strip().lower() == ONE_SHOT else DEFAULT


def autonomy_of(services: Mapping[str, Any] | None) -> str:
    """The mode the services config says (``review`` when it says nothing, or something that is not a mode)."""
    return normalize((services or {}).get(KEY, DEFAULT))


def is_one_shot(services: Mapping[str, Any] | None) -> bool:
    return autonomy_of(services) == ONE_SHOT
