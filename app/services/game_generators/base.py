"""Shared types for one game-asset generation attempt."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


@dataclass
class GenContext:
    """One attempt. ``call`` is ``LocalMcp.call``. ``loopback`` is MCP over HTTP.

    ``steps`` collects provenance while the tools run. It is not part of the
    saved attempt until the generator copies it into ``AttemptResult``.
    """

    workspace: str
    game: dict
    asset: dict
    attempt_id: str
    call: Callable[[str, dict], dict]
    loopback: Callable[[str, dict], dict]
    workspace_dir: Callable[[str], str]
    cancelled: Callable[[], bool]
    log: Callable[[str], None]
    steps: list = field(default_factory=list)


@dataclass
class AttemptResult:
    files: dict
    metrics: dict
    warnings: list
    provenance: dict


class Generator(Protocol):
    kind: str

    def estimate(self, game: dict, asset: dict) -> dict[str, int]:
        """Step counts by tool family, for example ``{"image": 3}``."""

    def run(self, ctx: GenContext) -> AttemptResult:
        """Produce the attempt and write its files under ``attempt_dir``."""


def attempt_dir(ctx: GenContext) -> Path:
    """``<workspace>/game/<gameId>/<assetId>/<attemptId>/``."""
    root = Path(ctx.workspace_dir(ctx.workspace))
    return root / "game" / str(ctx.game["id"]) / str(ctx.asset["id"]) / str(ctx.attempt_id)


def candidate_dirs(ctx: GenContext, count: int) -> list[tuple[str, Path]]:
    """One directory per candidate. A single candidate keeps ``ctx.attempt_id``."""
    count = max(1, int(count))
    if count == 1:
        return [(str(ctx.attempt_id), attempt_dir(ctx))]
    parent = attempt_dir(ctx).parent
    return [(f"a{index}", parent / f"a{index}") for index in range(1, count + 1)]
