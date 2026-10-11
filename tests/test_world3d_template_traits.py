"""Every Video 3D card tells an agent what the shot does, and the search understands both languages' intent words."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.world3d_templates import create_world3d_templates_router
from services.production_plan import PlanError, plan_brief
from services.production_quality_gate import plan_warnings
from services.world3d_template_catalog import (
    CARD_KEYS, World3DTemplateError, builtin_card, builtin_cards, document_traits, page_templates, search_templates,
)
from services.world3d_template_commands import command_catalog, command_handlers, execute_command
from services.world3d_template_vocabulary import FORMATS, GROUPS, MOVES, SHOT_SIZES, USES, duplicated_words, expand

ROOT = Path(__file__).resolve().parents[1]
SONG = {"lyrics": "[Verse]\nla luz se queda", "caption": "lullaby", "duration": 40, "bpm": 96}
MOVING_PARTS = {"camera", "subjects", "props", "screens", "effects", "backdrop", "texts"}


def ids(cards):
    return [card["id"] for card in cards]


def test_every_card_carries_the_derived_traits_and_no_title_is_shared():
    cards = builtin_cards()
    for card in cards:
        assert card["shot"] in SHOT_SIZES
        assert set(card["moves"]) <= set(MOVES)
        assert set(card["moving"]) <= MOVING_PARTS
        assert card["still"] == (card["moving"] == [])
        assert set(card["uses"]) <= set(USES) and card["uses"], card["id"]
        assert card["authoredFor"] in ("model", "cutout", "mixed", "none")
        assert card["subjects"] == sum(1 for role in card["roles"] if role in ("subject_1", "subject_2"))
        assert (card["shot"] == "plate") == (card["distance"] is None)
        assert isinstance(card["notesEs"], str) and isinstance(card["notesEn"], str)
        assert not card["lineEs"].endswith("...") and not card["lineEn"].endswith("...")
    for key in ("titleEs", "titleEn"):
        repeated = [title for title, count in Counter(card[key] for card in cards).items() if count > 1]
        assert repeated == [], key
    assert sum(1 for card in cards if card["still"]) > 100            # the still looks are told apart from the moving shots
    assert sum(1 for card in cards if "dialogue" in card["uses"]) >= 20
    assert any(card["notesEn"] for card in cards if card["id"] == "car-chase")


def test_known_shots_read_as_a_director_would():
    close = builtin_card("face-closeup")
    assert close["shot"] == "close" and "push" in close["moves"] and {"talk", "reaction"} <= set(close["uses"])
    dolly = builtin_card("cine-dolly-zoom")
    assert {"push", "zoom"} <= set(dolly["moves"]) and dolly["moving"] == ["camera"]
    orbit = builtin_card("dance-orbit")
    assert orbit["moves"] == ["orbit"] and "music" in orbit["uses"] and "backdrop" in orbit["moving"]
    two = builtin_card("speech-dialogue")
    assert two["subjects"] == 2 and two["still"] is True and "dialogue" in two["uses"]
    anime = builtin_card("anime-impact-frame")
    assert anime["authoredFor"] == "cutout" and "shake" in anime["moves"] and "action" in anime["uses"] and anime["floor"] == "none"
    plate = builtin_card("pixel-moon-lake")
    assert plate["shot"] == "plate" and plate["subjects"] == 0 and "plate" in plate["uses"] and "backdrop" in plate["moving"]
    crane = builtin_card("crane-reveal")
    assert "rise" in crane["moves"] and "reveal" in crane["uses"]
    assert builtin_card("establishing")["shot"] == "far"
    assert builtin_card("two-shot")["uses"] == ["dialogue", "figure"]
    assert builtin_card("nope") is None


def test_vocabulary_words_belong_to_one_group_and_reach_the_traits():
    assert duplicated_words() == set()
    assert all(group for group in GROUPS)
    assert "dialogue" in expand("dialogo") and "close" in expand("primer") and "orbit" in expand("alrededor")
    assert expand("xyzzy") == frozenset({"xyzzy"})
    for name in ("close", "medium", "wide", "far", "plate", *MOVES, *USES, *FORMATS):
        assert name in expand(name)


@pytest.mark.parametrize("query, expected", [
    ("diálogo", "speech-dialogue"),
    ("dos personajes hablando", "speech-dialogue"),
    ("primer plano reacción", "cine-reaction-shot"),
    ("plano general", "cine-long-shot"),
    ("persecución", "night-rain-pursuit"),
    ("nieve", "cine-snow"),
    ("humo", "cine-smoke"),
    ("plano de dos", "two-shot"),
    ("dolly zoom", "cine-dolly-zoom"),
    ("órbita", "pixel-orbit"),
])
def test_intent_words_in_either_language_find_the_shot(query, expected):
    hits = search_templates(query, limit=8)
    assert hits and hits[0]["match"] == "full"
    assert hits[0]["id"] == expected, ids(hits)


def test_a_literal_word_outranks_its_synonyms_and_stop_words_are_ignored():
    hits = search_templates("lluvia", limit=8)
    assert hits[0]["id"] == "cine-rain" and hits[0]["score"] > hits[1]["score"]
    assert ids(search_templates("un plano de diálogo en la escena", limit=3)) == ids(search_templates("diálogo", limit=3))
    assert ids(search_templates("escenas", limit=3)) == ids(search_templates("escena", limit=3))


def test_a_query_nobody_fully_matches_returns_partial_cards_and_applies_nothing(tmp_path):
    partial = search_templates("diálogo tenso en una taberna", limit=5)
    assert partial and all(card["match"] == "partial" for card in partial)
    assert "cafe-duet" in ids(partial)
    page = page_templates("diálogo tenso en una taberna")
    assert page["partial"] is True and page["total"] >= len(partial)
    assert search_templates("xyzzy nothing here", limit=5) == []
    assert page_templates("dolly zoom")["partial"] is False and page_templates("")["partial"] is False
    root = lambda workspace: str(tmp_path / workspace)
    reply = execute_command("world3d.scene.apply_query", {"version": 1, "intent_id": "tavern",
                            "input": {"workspace": "studio", "query": "diálogo tenso en una taberna"}}, root)
    assert reply["status"] == "needs_choice" and reply["result"]["scene"] is None
    assert reply["result"]["candidates"][0]["match"] == "partial"
    assert not (tmp_path / "studio" / "world3d-edits").exists()
    listed = execute_command("world3d.templates.list", {"version": 1, "input": {"workspace": "studio", "query": "diálogo tenso en una taberna"}}, root)
    assert listed["result"]["partial"] is True
    catalog = execute_command("world3d.templates.catalog", {"version": 1, "input": {"workspace": "studio", "query": "dolly zoom"}}, root)
    assert catalog["result"]["partial"] is False and catalog["result"]["templates"][0]["match"] == "full"


def test_trait_filters_narrow_the_library_and_reject_bad_values():
    close_push = search_templates("", shot="close", move="push", limit=24)
    assert close_push and all(card["shot"] == "close" and "push" in card["moves"] for card in close_push)
    duets = page_templates("", use="dialogue", subjects=2, format="landscape")
    assert duets["total"] and all(card["subjects"] >= 2 and "dialogue" in card["uses"] and card["format"] == "landscape" for card in duets["templates"])
    assert page_templates("", shot="plate")["total"] == sum(1 for card in builtin_cards() if card["shot"] == "plate")
    anime = page_templates("", category="anime")
    assert anime["total"] == 9 and all("anime" in card["tags"] for card in anime["templates"])
    assert ids(search_templates("baile", category="music", limit=3))[0] == "dance-orbit"
    for name, value in (("shot", "huge"), ("use", "party"), ("move", "fly"), ("format", "square"), ("subjects", 5), ("subjects", "2")):
        with pytest.raises(World3DTemplateError) as bad:
            search_templates("", **{name: value})
        assert bad.value.code == f"invalid_{name}"


def test_the_tools_describe_the_traits_and_take_the_filters_over_http(tmp_path):
    root = lambda workspace: str(tmp_path / workspace)
    app = FastAPI()
    app.include_router(create_world3d_templates_router(root))
    client = TestClient(app)
    reply = client.post("/api/v1/world3d/templates/commands", json={"operation": "world3d.templates.list", "version": 1,
                        "input": {"workspace": "studio", "use": "reaction", "shot": "close", "limit": 4}})
    assert reply.status_code == 200, reply.text
    cards = reply.json()["result"]["templates"]
    assert cards and all("reaction" in card["uses"] and card["shot"] == "close" for card in cards)
    assert set(CARD_KEYS) | {"score", "match"} == set(cards[0])
    tools = {tool["name"]: tool for tool in command_catalog()}
    for name in ("world3d.templates.list", "world3d.templates.catalog", "world3d.scene.apply_query"):
        fields = tools[name]["inputSchema"]["properties"]["input"]["properties"]
        assert {"shot", "use", "move", "subjects", "format"} <= set(fields)
        assert fields["use"]["enum"] == list(USES)
    assert "still" in tools["world3d.templates.list"]["description"] and "partial" in tools["world3d.scene.apply_query"]["description"]
    bad = client.post("/api/v1/world3d/templates/commands", json={"operation": "world3d.templates.list", "version": 1,
                      "input": {"workspace": "studio", "shot": "huge"}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_shot"
    assert set(command_handlers(root)) >= {"world3d.templates.list", "world3d.scene.apply_query"}


def test_a_personal_template_reports_what_its_document_shows(tmp_path):
    workspace = tmp_path / "studio"
    workspace.mkdir()
    document = {"templateId": "two-shot", "width": 720, "height": 1280, "duration": 5, "slots": [
        {"id": "hero", "slot": "subject_1", "media": "image", "sourceUrl": "", "clip": None, "position": [0, 0, 0], "rotationY": 0, "scale": 1,
         "motion": {"to": [2, 0, 0]}},
        {"id": "tv", "slot": "prop", "media": "screen", "sourceUrl": "", "clip": None, "position": [0, 0, 0], "rotationY": 0, "scale": 1,
         "screen": {"media": "video", "sourceUrl": "/api/v1/file/loop.mp4?workspace=studio"}},
    ], "texts": [{"id": "t", "text": "hi"}], "environment": {"reflectiveFloor": True}}
    (workspace / "world3d-user-templates.json").write_text(json.dumps({"templates": [
        {"id": "user-walk", "title": "Mi paseo", "description": "una figura cruza", "document": document}]}), encoding="utf-8")
    traits = document_traits(document)
    assert traits == {"subjects": 1, "props": 0, "screens": 1, "authoredFor": "cutout", "floor": "mirror",
                      "moving": ["subjects", "screens", "texts"], "still": None}
    mine = search_templates("mi paseo", workspace_dir=lambda name: str(tmp_path / name), workspace="studio", limit=3)
    assert mine[0]["id"] == "user-walk" and mine[0]["shot"] is None and mine[0]["moves"] == [] and mine[0]["uses"] == []
    assert mine[0]["moving"] == ["subjects", "screens", "texts"] and mine[0]["format"] == "portrait"
    assert ids(search_templates("", workspace_dir=lambda name: str(tmp_path / name), workspace="studio", shot="plate", limit=24)) == ids(
        search_templates("", shot="plate", limit=24))


def test_the_planner_refuses_a_partial_match_instead_of_inventing_a_shot():
    brief = {"tema": "x", "publico": "y", "duracion": "20 seconds", "musica": "pop", "estilo": "anime", "protagonista": "z",
             "cta": "c", "limites": "l", "lyrics": "[Verse]\nla la", "toma": "diálogo tenso en una taberna"}
    with pytest.raises(PlanError) as refused:
        plan_brief(brief)
    assert refused.value.code == "unknown_template"


def test_a_still_template_with_nothing_moving_is_warned_once_per_template(tmp_path):
    def shot(key, **scene3d):
        return {"key": key, "kind": "scene3d", "t0": 0, "scene3d": {"template": "speech-dialogue", "cast": {"subject_1": "hero"}, **scene3d}}
    spec = {"song": SONG, "cast": [{"id": "hero", "sheet_prompt": "x"}], "models": {"hero": {"from": "hero"}},
            "shots": [shot("a"), shot("b"), shot("c", cast={"subject_1": {"source": "hero", "clip": "talk"}}),
                      shot("d", camera={"family": "orbit"}), shot("e", world="atmos-reef-wide"),
                      {"key": "f", "kind": "scene3d", "t0": 0, "scene3d": {"template": "dance-orbit", "cast": {"subject_1": "hero"}}}]}
    codes = {item["code"]: item for item in plan_warnings(spec, tmp_path)}
    assert codes["template_still"]["template"] == "speech-dialogue" and codes["template_still"]["shots"] == ["a", "b"]
    assert "clip" in codes["template_still"]["hint"]
    assert builtin_card("dance-orbit")["still"] is False
