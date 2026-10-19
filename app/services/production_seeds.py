"""Default seeds for a production: its own random base plus a fixed offset per stage.

A seed the spec writes is used as written. Without one, every stage used the same numbers in every
production, so two productions started from the same noise. The base is drawn once when a production first
runs and is kept in its record, so a resumed run asks for the same jobs (intent ids carry the seed).
Records that ran before the base existed keep base 0, the numbers they were made with.
"""
from __future__ import annotations

import secrets
from typing import Any

SEED_SPAN = 2**31 - 2**20      # leaves room for the largest stage offset below 2**31


def ensure_seed_base(state: dict) -> int:
    """Draw this production's base once; call it before the run marks itself started."""
    base = state.get("seed_base")
    if not isinstance(base, int):
        base = 0 if state.get("started") else 1 + secrets.randbelow(SEED_SPAN - 1)
        state["seed_base"] = base
    return base


def window_seed(production: Any, offset: int, index: int) -> int:
    """A stage seed for one shot window: its own in a new production. A record from before the base keeps
    the one seed all its windows shared."""
    base = default_seed(production, 0)
    return base + offset + (1009 * index if base else 0)


def default_seed(production: Any, offset: int) -> int:
    """The seed a stage uses when the spec gives none."""
    state = getattr(production, "state", None)
    base = state.get("seed_base") if isinstance(state, dict) else None
    return (base if isinstance(base, int) else 0) + offset
