"""scenes.templates.suggest ranks the music cards for a shot as a writer describes it (contract, MCP section).

The battery lives in ``tests/fixtures/video2d_template_queries.json``: ``{"input", "expect", "why"}`` per entry, Spanish
and English writer phrases with the card that must come first.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from services import video2d_template_cards as cards
from services.video2d_catalogs import (
    CATALOGS, SUGGEST_OPERATION, CatalogError, execute_query, query_handlers, query_operations, suggest_templates,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "video2d_template_queries.json"
BATTERY = json.loads(FIXTURE.read_text(encoding="utf-8"))
MUSIC = {entry["id"] for entry in CATALOGS["scenes.templates.catalog"]["entries"] if entry["family"] == "music"}


def _suggest(**data) -> dict:
    return suggest_templates(data)["result"]


@pytest.mark.parametrize("case", BATTERY, ids=[case["input"]["line"] for case in BATTERY])
def test_a_writer_phrase_suggests_its_card_first(case):
    found = _suggest(**case["input"])
    ids = [row["id"] for row in found["templates"]]
    assert ids and ids[0] == case["expect"], (ids, found["unknown_words"], case["why"])


def test_the_battery_has_both_languages_and_every_card_is_a_playable_music_card():
    assert len(BATTERY) >= 12
    lines = [case["input"]["line"] for case in BATTERY]
    assert any(" the " in f" {line} " for line in lines) and any(" el " in f" {line} " or " la " in f" {line} " for line in lines)
    for case in BATTERY:
        for row in _suggest(**case["input"], limit=8)["templates"]:
            assert row["id"] in MUSIC and cards.listed(row["id"]), row["id"]


def test_each_card_says_why_and_carries_what_a_shot_needs():
    found = _suggest(line="la cantante rebota al ritmo en el escenario")
    assert len(found["templates"]) == cards.SUGGEST_LIMIT and found["partial"] is False and found["unknown_words"] == []
    row = found["templates"][0]
    assert row["match"] == "full" and row["score"] > 0
    assert row["reason"].startswith("one subject") and "moves: " in row["reason"] and "uses: " in row["reason"]
    assert {slot["id"] for slot in row["slots"]} and "duration" in row["controls"]
    assert set(cards.TRAIT_KEYS) <= set(row) and row["titleEs"] and row["lineEn"]


def test_speakers_beat_and_limit_narrow_the_cards():
    one = _suggest(speakers=1, limit=8)
    assert one["filters"] == {"subjects": 1} and all(row["subjects"] == 1 for row in one["templates"])
    two = _suggest(line="dos figuras", speakers=3, limit=8)
    assert two["filters"] == {"subjects": 2} and two["templates"] and all(row["subjects"] >= 2 for row in two["templates"])
    exits = _suggest(beat="transition", limit=8)
    assert exits["filters"] == {"use": "transition"} and exits["templates"]
    assert all("transition" in row["uses"] for row in exits["templates"])
    assert len(_suggest(limit=8)["templates"]) == 8
    assert _suggest(beat="documentary")["templates"] == [], "no music card is a documentary"


def test_no_words_list_moving_cards_before_still_ones():
    rows = _suggest(limit=8)["templates"]
    stills = [row["still"] for row in rows]
    assert stills == sorted(stills)


def test_a_portrait_request_keeps_the_landscape_cards_and_says_so():
    found = _suggest(line="rebota al ritmo", format="portrait")
    assert found["templates"] and "format" not in found["filters"]
    assert "landscape" in found["notes"][0] and "percent" in found["notes"][0]
    landscape = _suggest(line="rebota al ritmo", format="landscape")
    assert landscape["filters"] == {"format": "landscape"} and "notes" not in landscape


def test_unknown_words_are_listed_and_do_not_count():
    found = _suggest(line="la figura rebota zzyzx", mood="melancólico")
    assert found["unknown_words"] == ["zzyzx", "melancolico"]
    assert found["templates"] and found["partial"] is False


@pytest.mark.parametrize("data", [
    {"line": 3}, {"line": "x" * 401}, {"speakers": 5}, {"speakers": True}, {"beat": "chase"}, {"format": "square"},
    {"limit": 0}, {"limit": 9}, {"place": "cocina"},
])
def test_bad_input_fails_with_a_stable_code(data):
    with pytest.raises(CatalogError) as caught:
        suggest_templates(data)
    assert caught.value.code == "catalog_bad_envelope"


def test_suggest_is_a_read_only_mcp_operation_next_to_the_catalog():
    operations = {operation["name"]: operation for operation in query_operations()}
    assert list(operations) == ["scenes.catalog", SUGGEST_OPERATION]
    suggest = operations[SUGGEST_OPERATION]
    assert suggest["mutation"] is False
    fields = suggest["inputSchema"]["properties"]["input"]["properties"]
    assert set(fields) == {"line", "speakers", "mood", "beat", "format", "limit"}
    assert fields["beat"]["enum"] == list(cards.USES) and fields["limit"]["maximum"] == cards.SUGGEST_MAX_LIMIT
    catalog_fields = operations["scenes.catalog"]["inputSchema"]["properties"]["input"]["properties"]
    assert {"use", "move", "subjects", "format"} <= set(catalog_fields)
    reply = execute_query({"version": 1, "operation": SUGGEST_OPERATION, "input": {"line": "pinball"}})
    assert reply["status"] == "completed" and reply["operation"] == SUGGEST_OPERATION
    assert reply["result"]["templates"][0]["id"] == "music-pinball"
    handlers = query_handlers()
    assert set(handlers) == {"scenes.catalog", SUGGEST_OPERATION}
    answered = asyncio.run(handlers[SUGGEST_OPERATION]({"version": 1, "input": {"line": "trampolín", "limit": 1}}))
    assert len(answered["result"]["templates"]) == 1
    with pytest.raises(HTTPException) as refused:
        asyncio.run(handlers[SUGGEST_OPERATION]({"version": 1, "input": {"limit": 99}}))
    assert refused.value.status_code == 422 and refused.value.detail["code"] == "catalog_bad_envelope"
