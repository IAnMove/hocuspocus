"""scenes.catalog template rows carry derived traits, ES/EN copy, aliases, twins and review status, and filter by trait.

The contract is docs/development/VIDEO2D_TEMPLATE_MODEL.md: 48 cards (41 and the seven walk and reaction cards), nine merged ids that compile to a surviving card
with a preset, two retired ids, and traits derived by ui/scripts/export-video2d-traits.mjs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.video2d_catalog import create_video2d_catalog_router
from services import video2d_template_cards as cards
from services.video2d_catalogs import CATALOGS, LINES, CatalogError, query_catalog

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "development" / "VIDEO2D_TEMPLATE_MODEL.md"
NARRATIVE = ROOT / "ui" / "src" / "lib" / "sceneNarrative.ts"
ENTRIES = CATALOGS["scenes.templates.catalog"]["entries"]
LISTED = [entry["id"] for entry in ENTRIES if entry["id"] not in cards.ALIASES and entry["id"] not in cards.RETIRED]


def _rows(**query) -> list[dict]:
    return query_catalog({"kind": "templates", **query})["result"]["entries"]


def test_the_catalog_lists_the_surviving_cards_only():
    rows = _rows()
    assert [row["id"] for row in rows] == LISTED
    assert len(LISTED) == 48
    assert not {row["id"] for row in rows} & (set(cards.ALIASES) | set(cards.RETIRED))
    counts = {row["kind"]: row["count"] for row in query_catalog({})["result"]["kinds"]}
    assert counts["templates"] == 48


def test_every_card_has_derived_traits_and_one_line_in_each_language():
    assert set(cards.TRAITS) == {entry["id"] for entry in ENTRIES}, "regenerate: node --import tsx scripts/export-video2d-traits.mjs"
    assert sorted(LINES["templates"]) == sorted(LISTED)
    for identity in LISTED:
        traits = cards.TRAITS[identity]
        assert tuple(traits) == cards.TRAIT_KEYS, identity
        assert set(traits["moves"]) <= set(cards.MOVES) and set(traits["moving"]) <= set(cards.MOVING)
        assert set(traits["uses"]) <= set(cards.USES) and traits["travel"] in cards.TRAVEL
        assert traits["background"] in cards.BACKGROUNDS and traits["format"] in cards.FORMATS
        assert 0 <= traits["holdShare"] <= 1 and traits["still"] is (traits["holdShare"] > cards.STILL_SHARE)
        copy = LINES["templates"][identity]
        assert set(copy) == set(cards.LINE_KEYS) and all(value.strip() for value in copy.values())
        assert copy["lineEs"] != copy["lineEn"] and len(copy["lineEs"]) <= 260 and len(copy["lineEn"]) <= 260


def test_a_template_row_carries_copy_traits_status_aliases_twins_and_the_still_warning():
    rows = {row["id"]: row for row in _rows()}
    pulse = rows["music-pulse"]
    assert pulse["name"] == "Music pulse" and pulse["titleEs"] == "Pulso musical"
    assert pulse["description"] == LINES["templates"]["music-pulse"]["lineEn"]
    assert pulse["family"] == "music" and pulse["reviewStatus"] in ("candidate", "approved")
    assert {key: pulse[key] for key in cards.TRAIT_KEYS} == cards.TRAITS["music-pulse"]
    assert {alias["id"]: alias["preset"] for alias in pulse["aliases"]} == {
        "music-stage": {"camera": "sweep"},
        "music-finale": {"camera": "open", "atmosphere": "confetti"},
        "music-chorus": {"camera": "beat", "atmosphere": "confetti"},
    }
    assert rows["cinema-establishing"]["twins"] == ["place-establishing", "high-angle-isolation"]
    assert not any("twins" in row for row in rows.values() if row["family"] != "cinema")
    for identity, row in rows.items():
        still = cards.TRAITS[identity]["holdShare"] > cards.STILL_SHARE
        assert (row.get("warnings") == ["template_still"]) is still, identity
        assert "controls" not in row and "slots" not in row, "summaries stay short"


def test_detail_and_id_entries_keep_the_json_and_add_the_card_fields():
    detailed = _rows(detail=True)
    assert all("controls" in entry and "moves" in entry and "titleEn" in entry for entry in detailed)
    one = query_catalog({"id": "music-orbit"})["result"]
    assert one["kind"] == "templates" and one["entry"]["slots"] and one["entry"]["aliases"][0]["id"] == "music-satellite-swarm"


def test_aliases_follow_the_contract_table_and_answer_with_their_card():
    table = re.findall(r"^\| `([a-z0-9-]+)` \| `([a-z0-9-]+)` \| `(\{.*?\})`[^|]*\|", CONTRACT.read_text(encoding="utf-8"), re.MULTILINE)
    assert {alias: (card, json.loads(preset)) for alias, card, preset in table} == cards.ALIASES
    for alias, (card, preset) in cards.ALIASES.items():
        found = query_catalog({"id": alias})["result"]
        assert found["kind"] == "templates" and found["entry"]["id"] == card
        assert found["alias"]["id"] == alias and found["alias"]["card"] == card and found["alias"]["preset"] == preset
    assert query_catalog({"id": "music-stage", "kind": "templates"})["result"]["entry"]["id"] == "music-pulse"


def test_a_retired_id_says_what_to_use_instead():
    teaser = query_catalog({"id": "trailer-teaser"})["result"]
    assert teaser["retired"] is True and "entry" not in teaser
    assert {item["id"] for item in teaser["use_instead"]} == {"title-card", "trailer-slam"}
    text_ids = {entry["id"] for entry in CATALOGS["scenes.text.catalog"]["entries"]}
    assert {item["id"] for item in teaser["use_instead"]} <= text_ids
    lyric = query_catalog({"id": "lyric-vertical", "kind": "templates"})["result"]
    assert lyric["retired"] is True and {"operation": "scenes.lyrics.import"} in lyric["use_instead"]
    assert "scenes.lyrics.import" in lyric["message"]


def test_twins_are_real_narrative_shots():
    narrative = NARRATIVE.read_text(encoding="utf-8")
    for card, twins in cards.TWINS.items():
        assert card in LISTED and card.startswith("cinema-")
        for twin in twins:
            assert f"id: '{twin}'" in narrative, twin


@pytest.mark.parametrize(("name", "value", "key"), [("use", "dance", "uses"), ("move", "orbit", "moves"), ("use", "space", "uses")])
def test_a_trait_filter_keeps_the_cards_that_have_it(name, value, key):
    rows = _rows(**{name: value})
    assert rows and all(value in row[key] for row in rows)
    assert {row["id"] for row in rows} == {identity for identity in LISTED if value in cards.TRAITS[identity][key]}


def test_subjects_is_at_least_and_format_is_exact_and_filters_join_q_and_family():
    two = _rows(subjects=2)
    assert two and all(row["subjects"] >= 2 for row in two)
    assert len(_rows(subjects=0)) == 48
    assert len(_rows(format="landscape")) == 48 and _rows(format="portrait") == []
    bouncing = query_catalog({"kind": "templates", "q": "rebota", "use": "dance", "family": "music"})["result"]
    assert bouncing["entries"] and all("dance" in row["uses"] and row["family"] == "music" for row in bouncing["entries"])
    counted = {row["kind"]: row["count"] for row in query_catalog({"use": "space"})["result"]["kinds"]}
    assert counted["templates"] == len(_rows(use="space"))
    assert counted["fonts"] == len(CATALOGS["scenes.fonts.catalog"]["entries"]), "trait filters narrow templates only"


@pytest.mark.parametrize("query", [
    {"kind": "fonts", "use": "dance"}, {"kind": "templates", "use": "fly"}, {"kind": "templates", "move": "zoom"},
    {"kind": "templates", "subjects": 3}, {"kind": "templates", "subjects": "2"}, {"kind": "templates", "format": "square"},
])
def test_a_bad_filter_fails_with_a_stable_code(query):
    with pytest.raises(CatalogError) as caught:
        query_catalog(query)
    assert caught.value.code == "catalog_bad_envelope"


def test_http_catalog_takes_the_trait_filters():
    app = FastAPI()
    app.include_router(create_video2d_catalog_router())
    client = TestClient(app)
    reply = client.get("/api/v1/scenes/catalog", params={"kind": "templates", "move": "spin", "subjects": 1})
    assert reply.status_code == 200
    rows = reply.json()["result"]["entries"]
    assert rows and all("spin" in row["moves"] and row["subjects"] >= 1 for row in rows)
    assert client.get("/api/v1/scenes/catalog", params={"kind": "templates", "use": "nope"}).status_code == 422


def test_2d_words_mean_one_thing_and_override_the_3d_groups():
    assert cards.duplicated_2d_words() == set()
    assert "fall" in cards.expand2d("vacio") and "plate" not in cards.expand2d("vacio")
    assert "cannon" in cards.expand2d("canon") and "canyon" not in cards.expand2d("canon")
    assert "music" in cards.expand2d("concierto"), "a word the 2D groups do not list keeps its 3D synonyms"
    assert query_catalog({"kind": "templates", "q": "cae al vacío"})["result"]["entries"][0]["id"] == "music-infinite-fall"


WALK_CARDS = ["walk-follow-back", "walk-toward-camera", "walk-behind-foreground", "walk-shadow-first", "walk-two-pose", "walk-cycle-sheet"]


def test_the_walk_cards_are_found_by_walking_words_and_are_not_dances():
    assert sorted(row["id"] for row in _rows(use="walk")) == sorted(WALK_CARDS)
    assert not {row["id"] for row in _rows(use="dance")} & set(WALK_CARDS)
    for words in ("camina de espaldas", "caminar hacia cámara", "walk toward camera", "pasos tras un mostrador"):
        found = [row["id"] for row in _rows(q=words)]
        assert set(found) & set(WALK_CARDS), words
    assert cards.traits_of("walk-follow-back")["uses"] == ["walk"]
    assert "entrance" in cards.traits_of("walk-behind-foreground")["uses"]


def test_the_reaction_card_is_found_by_gesture_and_expression_words_and_is_not_a_dance():
    assert [row["id"] for row in _rows(use="reaction")] == ["character-reaction"]
    assert "dance" not in cards.traits_of("character-reaction")["uses"]
    for words in ("un personaje se enfada", "saluda con la mano", "angry anime expression", "cara de sorpresa", "wave hello"):
        assert "character-reaction" in [row["id"] for row in _rows(q=words)], words
    assert "walk" not in cards.traits_of("character-reaction")["uses"]
