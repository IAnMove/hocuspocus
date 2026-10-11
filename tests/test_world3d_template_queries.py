"""A script writer's phrases, in Spanish and English, find the right Video 3D card or say honestly what is missing.

The battery lives in ``tests/fixtures/world3d_template_queries.json``: ``{"query", "expect", "why"}`` per entry, where
``expect`` is one of ``{"id": x}`` (first card), ``{"any_of": [..]}`` (first card among a tie), ``{"use": u}`` or
``{"kind": k}`` (the first card carries it), ``{"partial": true}``, ``{"unknown": [words]}`` or ``{"none": true}``.
``why`` names the future pack that should take a query over when the library has no good card yet."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.world3d_template_catalog import search_report
from services.world3d_template_vocabulary import KINDS, USES

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "world3d_template_queries.json"
ENTRIES = json.loads(FIXTURE.read_text(encoding="utf-8"))
EXPECTATIONS = ("id", "any_of", "use", "kind", "partial", "unknown", "none")


def _problem(expect: dict, report: dict) -> str | None:
    """What the reply got wrong, or None."""
    cards = report["templates"]
    top = cards[0] if cards else None
    if "none" in expect:
        return None if not cards else "cards came back"
    if "unknown" in expect:
        return None if report["unknown_words"] == expect["unknown"] else f"unknown_words {report['unknown_words']}"
    if "partial" in expect:
        return None if cards and report["partial"] is expect["partial"] else f"partial {report['partial']}"
    if top is None:
        return "no cards"
    if "id" in expect:
        return None if top["id"] == expect["id"] else f"first {top['id']}"
    if "any_of" in expect:
        return None if top["id"] in expect["any_of"] else f"first {top['id']}"
    if "use" in expect:
        return None if expect["use"] in top["uses"] else f"first {top['id']} uses {top['uses']}"
    if "kind" in expect:
        return None if top["kind"] == expect["kind"] else f"first {top['id']} kind {top['kind']}"
    return f"unreadable expectation {expect}"


def test_the_battery_is_well_formed():
    assert len(ENTRIES) >= 100
    assert len({entry["query"] for entry in ENTRIES}) == len(ENTRIES)
    for entry in ENTRIES:
        assert set(entry) == {"query", "expect", "why"}, entry
        assert entry["query"].strip() and entry["why"].strip()
        keys = [key for key in EXPECTATIONS if key in entry["expect"]]
        assert len(keys) == 1 and set(entry["expect"]) == set(keys), entry
        if "use" in entry["expect"]:
            assert entry["expect"]["use"] in USES
        if "kind" in entry["expect"]:
            assert entry["expect"]["kind"] in KINDS


@pytest.mark.parametrize("entry", ENTRIES, ids=[entry["query"] for entry in ENTRIES])
def test_a_writers_phrase_finds_the_shot_or_says_what_is_missing(entry):
    report = search_report(entry["query"], limit=3)
    problem = _problem(entry["expect"], report)
    top = [f"{card['id']} ({card['score']}, {card['match']})" for card in report["templates"]]
    assert problem is None, (f"{entry['query']!r} expected {entry['expect']} because {entry['why']}; got {problem}; "
                             f"top three {top}; unknown {report['unknown_words']}")
