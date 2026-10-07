"""Shared types for one game-asset generation attempt."""
from __future__ import annotations

import re

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


def workspace_root(ctx: GenContext) -> Path:
    """The workspace folder. Attempt files are stored relative to it."""
    return Path(ctx.workspace_dir(ctx.workspace))


def attempt_dir(ctx: GenContext) -> Path:
    """``<workspace>/game/<gameId>/<assetId>/<attemptId>/``."""
    return workspace_root(ctx) / "game" / str(ctx.game["id"]) / str(ctx.asset["id"]) / str(ctx.attempt_id)


def relative(ctx: GenContext, path: Path) -> str:
    """``path`` relative to the workspace, as the attempt ``files`` store it (POSIX on every OS)."""
    return Path(path).relative_to(workspace_root(ctx)).as_posix()


def spec_seed(asset: dict) -> int:
    """``spec.seed`` as given (``0`` is a valid seed), else ``1``."""
    value = (asset.get("spec") or {}).get("seed")
    if value is None or isinstance(value, bool):
        return 1
    return int(value)


def seed_for_step(asset: dict, step: str) -> int:
    """``spec_seed``, plus ``N - 1`` for a candidate step that ends in ``-aN``."""
    match = re.search(r"-a(\d+)$", str(step))
    return spec_seed(asset) + (int(match.group(1)) - 1 if match else 0)


def candidate_dirs(ctx: GenContext, count: int) -> list[tuple[str, Path]]:
    """One ``(id, folder)`` per candidate.

    A single candidate keeps ``ctx.attempt_id`` and ``attempt_dir``. Several
    candidates are ``<attemptId>-a<i>`` in ``attempt_dir / a<i>``, so a second
    production never reuses the ids or folders of the first.
    """
    count = max(1, int(count))
    folder = attempt_dir(ctx)
    if count == 1:
        return [(str(ctx.attempt_id), folder)]
    return [(f"{ctx.attempt_id}-a{index}", folder / f"a{index}") for index in range(1, count + 1)]


def candidate_result(written: list[dict], warnings: list, steps: list) -> AttemptResult:
    """Fold ``{"id", "files", "metrics"}`` candidates into one result.

    ``files`` and ``metrics`` describe the first candidate. Several candidates
    also list every one under ``metrics["candidates"]``. ``warnings`` apply to
    every candidate; a candidate's own ``warnings`` stay with that candidate.
    """
    first = written[0]
    metrics = {**first["metrics"], "attemptIds": [item["id"] for item in written]}
    if len(written) == 1:
        own = list(first.get("warnings") or [])
        return AttemptResult(files=dict(first["files"]), metrics=metrics, warnings=_unique([*warnings, *own]), provenance={"steps": list(steps)})
    metrics["candidates"] = [
        {"id": item["id"], "files": dict(item["files"]), "metrics": dict(item["metrics"]), "warnings": list(item.get("warnings") or [])}
        for item in written
    ]
    return AttemptResult(files=dict(first["files"]), metrics=metrics, warnings=list(warnings), provenance={"steps": list(steps)})


def _unique(items: list) -> list:
    """Order-preserving de-duplication; dict warnings are compared by value."""
    seen: list = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen
