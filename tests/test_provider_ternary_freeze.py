"""Paso 6.a: freeze provider ternaries in ui/src so they cannot grow."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ui" / "src"

MINIMAX_TERNARY = "=== 'minimax' ?"
MAESTRO_WRITER = "writingProvider === 'maestro'"
MAX_MINIMAX_TERNARIES = 30
MAX_MAESTRO_WRITERS = 6


def _count_literal(needle: str) -> int:
    total = 0
    for path in SRC.rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        total += path.read_text(encoding="utf-8").count(needle)
    return total


def test_minimax_ternaries_under_ui_src_do_not_increase() -> None:
    found = _count_literal(MINIMAX_TERNARY)
    assert found <= MAX_MINIMAX_TERNARIES, (
        f"{MINIMAX_TERNARY!r} under ui/src grew to {found}; cap is "
        f"{MAX_MINIMAX_TERNARIES}. Map new cases through provider_profile / "
        "writingProviderFromText instead of adding ternaries."
    )


def test_maestro_writing_provider_comparisons_do_not_increase() -> None:
    found = _count_literal(MAESTRO_WRITER)
    assert found <= MAX_MAESTRO_WRITERS, (
        f"{MAESTRO_WRITER!r} under ui/src grew to {found}; cap is "
        f"{MAX_MAESTRO_WRITERS}. Use the canonical writing-provider mapper."
    )
