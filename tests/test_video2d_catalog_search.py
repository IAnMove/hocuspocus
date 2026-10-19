"""scenes.catalog finds Video 2D entries by a writer's words, and every entry says what it does in ES and EN.

The phrases are the review's (REVISION_PLANTILLAS_2D_2026-10-11, annex A): before, ``q`` was a substring of the id and
only «clones» and «handheld» found anything.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.production_quality_gate import FULL_FRAME_TITLES
from services.template_search import match, score
from services.video2d_catalogs import CATALOGS, LINES, LYRIC_LOOKS_CATALOG, CatalogError, query_catalog
from services.world3d_template_vocabulary import expand

SHARED = Path(__file__).resolve().parents[1] / "app" / "shared"

PHRASES = [
    ("plano general de la ciudad", "cinema-establishing"),
    ("establishing shot", "cinema-establishing"),
    ("primer plano", "cinema-closeup"),
    ("close-up of the singer", "cinema-closeup"),
    ("entrada del héroe", "cinema-hero"),
    ("persecución espacial", "space-chase"),
    ("explosión de una nave", "space-broadside"),
    ("producto girando", "music-product"),
    ("rebota como una bola de pinball", "music-pinball"),
    ("choca esos cinco", "music-high-five"),
    ("documental histórico con fecha", "documentary-history"),
    ("trailer teaser", "trailer-slam"),
    ("rótulo con el nombre", "lower-third-date"),
    ("título de capítulo", "chapter"),
    ("cita", "quote"),
    ("paneo a la derecha", "camera-pan-right"),
    ("cámara en mano", "camera-handheld"),
    ("look de cine cálido", "warmCinema"),
    ("neón nocturno", "nightNeon"),
]


def _search(query: str, **extra) -> dict:
    return query_catalog({"q": query, **extra})["result"]


@pytest.mark.parametrize(("phrase", "wanted"), PHRASES)
def test_a_writer_phrase_finds_the_entry_first(phrase, wanted):
    found = _search(phrase)
    assert found["matches"][0]["id"] == wanted, [item["id"] for item in found["matches"][:4]]
    kind = found["matches"][0]["kind"]
    assert next(row for row in found["kinds"] if row["kind"] == kind)["count"] >= 1
    within = _search(phrase, kind=kind)
    assert within["entries"][0]["id"] == wanted and within["entries"][0]["score"] == found["matches"][0]["score"]


def test_merged_and_retired_cards_lead_to_what_replaced_them():
    """space-explosion is space-broadside with outcome explode; the retired cards point at texts and lyric looks."""
    assert _search("explosión de una nave")["matches"][0]["id"] == "space-broadside"
    lyric = _search("lyric video vertical para tiktok")
    assert lyric["matches"][0]["kind"] == "lyric_looks" and lyric["partial"] is True
    assert not any(item["id"] in {"trailer-teaser", "lyric-vertical", "space-explosion"} for item in _search("trailer explosión lyric")["matches"])


def test_words_no_entry_knows_come_back_and_do_not_count():
    docking = _search("la nave atraca en la estación")
    assert docking["unknown_words"] == [] and docking["matches"][0]["id"] == "space-docking"
    sailing = _search("la nave zarpa de la estación")
    assert sailing["unknown_words"] == ["zarpa"]
    assert "space-docking" in [item["id"] for item in sailing["matches"][:2]]
    assert _search("rótulo con el nombre")["unknown_words"] == ["nombre"]
    nothing = _search("zzyzx quux")
    assert nothing["matches"] == [] and nothing["unknown_words"] == ["zzyzx", "quux"]
    assert all(row["count"] == 0 for row in nothing["kinds"])


def test_words_match_whole_words_not_pieces_of_ids():
    orbit = [item["id"] for item in _search("órbita")["matches"][:3]]
    assert {"space-orbit", "music-orbit"} <= set(orbit)
    assert "music-satellite-swarm" not in [item["id"] for item in _search("warm")["matches"]], "s-warm is not warm"
    assert [item["id"] for item in _search("doc", kind="finish")["entries"]] == ["oldDoc"]
    assert "space-docking" not in [item["id"] for item in _search("doc")["matches"]]


def test_a_kind_page_is_ranked_with_scores_and_without_q_keeps_its_order():
    page = _search("pan right", kind="motion")
    assert page["entries"][0]["id"] == "camera-pan-right" and page["partial"] is False and page["unknown_words"] == []
    plain = query_catalog({"kind": "motion"})["result"]
    assert [item["id"] for item in plain["entries"]] == [entry["id"] for entry in CATALOGS["scenes.motion.catalog"]["entries"]]
    assert "score" not in plain["entries"][0] and "unknown_words" not in plain


def test_an_id_in_several_kinds_returns_every_match():
    cruise = query_catalog({"id": "space-cruise"})["result"]
    assert [item["kind"] for item in cruise["matches"]] == ["templates", "motion"]
    rain = query_catalog({"id": "rain"})["result"]
    assert [item["kind"] for item in rain["matches"]] == ["atmospheres", "effects"]
    one = query_catalog({"id": "space-cruise", "kind": "motion"})["result"]
    assert one["kind"] == "motion" and one["entry"]["id"] == "space-cruise"
    single = query_catalog({"id": "camera-dolly"})["result"]
    assert single["kind"] == "motion" and single["entry"]["kind"] == "camera"
    with pytest.raises(CatalogError) as missing:
        query_catalog({"id": "camera-orbit"})
    assert missing.value.code == "catalog_unknown_id"


def test_lyric_looks_are_a_kind_with_their_lines():
    looks = json.loads((SHARED / "lyric_looks.json").read_text(encoding="utf-8"))["looks"]
    page = query_catalog({"kind": "lyric_looks"})["result"]
    assert [item["id"] for item in page["entries"]] == [look["id"] for look in looks] and page["total"] == 13
    cinema = page["entries"][0]
    assert cinema["name"] == "Cinema subtitle" and cinema["titleEs"] == "Subtítulo de cine" and "Warm cinema" in cinema["lineEn"]
    assert _search("subtítulo de cine", kind="lyric_looks")["entries"][0]["id"] == "cinema"
    assert query_catalog({"id": "neon"})["result"]["kind"] == "lyric_looks"


def test_every_text_motion_finish_and_lyric_entry_has_one_honest_line_in_each_language():
    sources = {"text": CATALOGS["scenes.text.catalog"], "motion": CATALOGS["scenes.motion.catalog"],
               "finish": CATALOGS["scenes.finish.catalog"], "lyric_looks": LYRIC_LOOKS_CATALOG}
    for kind, data in sources.items():
        ids = [entry["id"] for entry in data["entries"]]
        assert sorted(LINES[kind]) == sorted(ids), kind
        for identity in ids:
            copy = LINES[kind][identity]
            assert set(copy) == {"titleEs", "titleEn", "lineEs", "lineEn"} and all(value.strip() for value in copy.values())
            assert copy["lineEs"] != copy["lineEn"], f"{kind} {identity}"
        rows = query_catalog({"kind": kind})["result"]["entries"]
        assert all(row["name"] == LINES[kind][row["id"]]["titleEn"] and row["description"] for row in rows), kind
    assert not any(row["name"].startswith("templates.") for row in query_catalog({"kind": "text"})["result"]["entries"])
    assert "not an orbit" in LINES["motion"]["orbit-sweep"]["lineEn"]


def test_title_card_and_trailer_slam_say_they_cover_the_frame():
    covering = [entry["id"] for entry in CATALOGS["scenes.text.catalog"]["entries"] if entry.get("covers")]
    assert covering == ["title-card", "trailer-slam"] and list(FULL_FRAME_TITLES) == covering
    rows = {row["id"]: row for row in query_catalog({"kind": "text"})["result"]["entries"]}
    for identity in covering:
        assert rows[identity]["covers"] is True
        assert rows[identity]["lineEs"].startswith("Tapa todo el plano") and rows[identity]["lineEn"].startswith("Covers the whole frame")
    assert "covers" not in rows["lower-third-date"]


def test_the_review_lines_say_what_the_compiled_scene_does():
    """The cards the review found dishonest now do what their line says, and the merged and retired ones are gone."""
    intents = {entry["id"]: entry["visualIntent"] for entry in CATALOGS["scenes.templates.catalog"]["entries"]}
    assert "entra en el plano" in intents["cinema-hero"]
    assert "se alternan al ritmo" in intents["music-duet"]
    assert "contraste" not in intents["music-pulse"] and "sweep" in intents["music-pulse"]
    assert "movimiento lento" in intents["documentary-history"]
    assert "No hay gaviotas" in intents["city-postcard"]
    assert not {"music-stage", "music-chorus", "trailer-teaser", "lyric-vertical"} & set(intents)


def test_a_literal_word_outranks_its_synonym_and_score_is_unchanged():
    literal = match(["persecucion"], title="Persecución espacial", description="", tags=[], synonyms=expand)
    synonym = match(["persecucion"], title="Space chase", description="", tags=[], synonyms=expand)
    assert literal == (["persecucion"], 6) and synonym == (["persecucion"], 3)
    assert match(["persecucion"], title="Space chase", description="", tags=[]) == ([], 0), "no synonyms unless asked"
    assert score("escena", title="Escena estilo PS1", description="", tags=[]) == 3
