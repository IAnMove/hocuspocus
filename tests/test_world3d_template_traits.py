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
    CARD_KEYS, World3DTemplateError, builtin_card, builtin_cards, document_traits, page_templates, search_report,
    search_templates,
)
from services.world3d_template_commands import command_catalog, command_handlers, execute_command
from services.world3d_template_vocabulary import FORMATS, GROUPS, KINDS, MOVES, QUERY_STOP, SHOT_SIZES, USES, duplicated_words, expand

ROOT = Path(__file__).resolve().parents[1]
SONG = {"lyrics": "[Verse]\nla luz se queda", "caption": "lullaby", "duration": 40, "bpm": 96}
MOVING_PARTS = {"camera", "subjects", "props", "screens", "effects", "backdrop", "texts"}
TAVERN = "diálogo tenso en una taberna"
CHURCH = "diálogo tenso en una iglesia"


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
        assert card["kind"] in KINDS and isinstance(card["travel"], bool), card["id"]
        assert card["place"] is None or isinstance(card["place"], str)
        assert card["preview"] is None and (card["reference"] is None or card["reference"].startswith("http"))
    for key in ("titleEs", "titleEn"):
        repeated = [title for title, count in Counter(card[key] for card in cards).items() if count > 1]
        assert repeated == [], key
    assert sum(1 for card in cards if card["still"]) > 100            # the still looks are told apart from the moving shots
    assert sum(1 for card in cards if "dialogue" in card["uses"]) >= 20
    assert sum(1 for card in cards if card["travel"]) >= 20
    assert any(card["notesEn"] for card in cards if card["id"] == "car-chase")


def test_known_shots_read_as_a_director_would():
    close = builtin_card("face-closeup")
    assert close["shot"] == "close" and "push" in close["moves"] and {"talk", "reaction"} <= set(close["uses"])
    dolly = builtin_card("cine-dolly-zoom")
    assert {"push", "zoom"} <= set(dolly["moves"]) and dolly["moving"] == ["camera"] and dolly["kind"] == "camera"
    orbit = builtin_card("dance-orbit")
    assert orbit["moves"] == ["orbit"] and "music" in orbit["uses"] and "backdrop" in orbit["moving"]
    two = builtin_card("speech-dialogue")
    assert two["subjects"] == 2 and two["still"] is True and "dialogue" in two["uses"]
    anime = builtin_card("anime-impact-frame")
    assert anime["authoredFor"] == "cutout" and "shake" in anime["moves"] and {"action", "impact"} <= set(anime["uses"]) and anime["floor"] == "none"
    plate = builtin_card("pixel-moon-lake")
    assert plate["shot"] == "plate" and plate["subjects"] == 0 and "plate" in plate["uses"] and "backdrop" in plate["moving"]
    crane = builtin_card("crane-reveal")
    assert "rise" in crane["moves"] and "reveal" in crane["uses"]
    assert builtin_card("establishing")["shot"] == "far"
    assert builtin_card("two-shot")["uses"] == ["dialogue", "figure"]
    chase = builtin_card("car-chase")
    assert "speed" in chase["uses"] and "dialogue" not in chase["uses"] and chase["travel"] is True and chase["place"] == "chase-street"
    assert builtin_card("cine-rembrandt")["kind"] == "look" and builtin_card("anime-eyecatch")["kind"] == "transition"
    assert builtin_card("cine-rain")["place"] == "chase-street" and builtin_card("speech-portrait")["place"] is None
    assert builtin_card("nope") is None


def test_vocabulary_words_belong_to_one_group_and_reach_the_traits():
    assert duplicated_words() == set()
    assert all(group for group in GROUPS)
    assert not any(word in QUERY_STOP for group in GROUPS for word in group)
    assert "dialogue" in expand("dialogo") and "close" in expand("primer") and "orbit" in expand("alrededor")
    assert expand("xyzzy") == frozenset({"xyzzy"})
    for name in ("close", "medium", "wide", "far", "plate", *MOVES, *USES, *KINDS, *FORMATS):
        assert name in expand(name)
    assert {"speed", "impact"} <= set(USES)
    assert {"over", "under", "through", "across", "onto"} <= QUERY_STOP
    # Places a director tells apart are separate groups; emotions, walking, sitting, entering, crowds reach their marks.
    assert expand("cocina").isdisjoint(expand("iglesia")) and expand("hospital").isdisjoint(expand("dormitorio"))
    assert "reaction" in expand("triste") and "reaction" in expand("miedo") and "dragon" not in expand("miedo")
    assert "travel" in expand("camina") and "seated" in expand("sentado") and "crowd" in expand("publico")
    assert "entrance" in expand("entra") and "push" not in expand("entra")
    assert "pov" in expand("subjetivo") and "cowboy" in expand("americano") and "phone" in expand("llamada")
    assert "flashback" in expand("sueno") and "impact" in expand("golpe") and "action" not in expand("golpe")
    assert "speed" in expand("rapido") and "drive" in expand("coche")


@pytest.mark.parametrize("query, expected", [
    ("diálogo", "duo-diagonal"),                    # ties speech-dialogue; the moving card leads (contract §4)
    ("dos personajes hablando", "speech-dialogue"),
    ("primer plano reacción", "cine-reaction-shot"),
    ("plano general", "cine-long-shot"),
    ("persecución", "cine-car-chasing"),            # ties night-rain-pursuit; the shorter id leads
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


def test_ties_break_by_motion_then_base_template_then_shorter_id():
    duet = search_templates("diálogo", limit=3)
    assert duet[0]["score"] == duet[1]["score"] and ids(duet[:2]) == ["duo-diagonal", "speech-dialogue"]
    assert duet[0]["still"] is False and duet[1]["still"] is True
    chase = search_templates("persecución", limit=3)
    assert chase[0]["score"] == chase[1]["score"] and ids(chase[:2]) == ["cine-car-chasing", "night-rain-pursuit"]
    assert chase[0]["still"] is False and chase[1]["still"] is False and len(chase[0]["id"]) < len(chase[1]["id"])
    zoom = search_templates("zoom rápido", limit=3)
    assert ids(zoom[:2]) == ["cine-rapid-zoom-in", "cine-rapid-zoom-out"] and zoom[0]["score"] > zoom[1]["score"]
    assert ids(search_templates("", limit=3)) == ids(builtin_cards()[:3])      # no query keeps catalogue order


def test_a_literal_word_outranks_its_synonyms_and_stop_words_are_ignored():
    hits = search_templates("lluvia", limit=8)
    assert hits[0]["id"] == "cine-rain" and hits[0]["score"] > hits[1]["score"]
    assert ids(search_templates("un plano de diálogo en la escena", limit=3)) == ids(search_templates("diálogo", limit=3))
    assert ids(search_templates("escenas", limit=3)) == ids(search_templates("escena", limit=3))
    assert ids(search_templates("drone shot over the sea", limit=2)) == ids(search_templates("drone sea", limit=2))


def test_unknown_words_never_count_and_half_of_the_known_ones_is_enough(tmp_path):
    tavern = search_report(TAVERN, limit=5)
    assert tavern["unknown_words"] == ["tenso"] and tavern["partial"] is False
    assert ids(tavern["templates"])[0] == "cafe-duet" and "stage-bar" in ids(tavern["templates"])   # bar dialogues: both known words
    church = search_report(CHURCH, limit=5)
    assert church["unknown_words"] == ["tenso"] and church["partial"] is True
    assert church["templates"] and all(card["match"] == "partial" for card in church["templates"])
    assert "duo-diagonal" in ids(church["templates"]) and "speech-dialogue" in ids(church["templates"])
    assert search_report("primer plano llorando")["partial"] is False     # one of two is enough: crying is a reaction word
    cheering = search_report("crowd cheering church", limit=8)
    assert cheering["partial"] is True and cheering["unknown_words"] == []
    assert "group-audience" in ids(cheering["templates"]) and "atmos-temple-low" not in ids(cheering["templates"])  # 1 of 3 is not half
    assert search_report("xyzzy xyzzy plugh") == {"templates": [], "unknown_words": ["xyzzy", "plugh"], "partial": False}
    page = page_templates(CHURCH)
    assert page["partial"] is True and page["unknown_words"] == ["tenso"] and page["total"] >= len(church["templates"])
    assert page_templates("dolly zoom")["unknown_words"] == [] and page_templates("")["unknown_words"] == []
    root = lambda workspace: str(tmp_path / workspace)
    reply = execute_command("world3d.scene.apply_query", {"version": 1, "intent_id": "church",
                            "input": {"workspace": "studio", "query": CHURCH}}, root)
    assert reply["status"] == "needs_choice" and reply["result"]["scene"] is None
    assert reply["result"]["candidates"][0]["match"] == "partial" and reply["result"]["unknown_words"] == ["tenso"]
    assert not (tmp_path / "studio" / "world3d-edits").exists()
    missing = execute_command("world3d.scene.apply_query", {"version": 1, "intent_id": "nothing",
                              "input": {"workspace": "studio", "query": "xyzzy plugh"}}, root)
    assert missing["status"] == "not_found" and missing["result"]["unknown_words"] == ["xyzzy", "plugh"]
    listed = execute_command("world3d.templates.list", {"version": 1, "input": {"workspace": "studio", "query": CHURCH}}, root)
    assert listed["result"]["partial"] is True and listed["result"]["unknown_words"] == ["tenso"]
    catalog = execute_command("world3d.templates.catalog", {"version": 1, "input": {"workspace": "studio", "query": "dolly zoom"}}, root)
    assert catalog["result"]["partial"] is False and catalog["result"]["templates"][0]["match"] == "full"
    assert catalog["result"]["unknown_words"] == []


def test_a_short_literal_word_scores_as_a_line_word():
    narrator = search_templates("narrador en off", limit=8)
    assert "talk" in narrator[0]["uses"] and "anime-face-off" not in ids(narrator)
    assert search_templates("anime face off", limit=1)[0]["id"] == "anime-face-off"
    assert ids(search_templates("pov", limit=2)) == ["cine-pov", "cine-object-pov"]
    assert search_templates("pov", limit=1)[0]["score"] == 2
    assert ids(search_templates("two shot", limit=1)) == ["two-shot"]       # the whole title still wins


def test_trait_filters_narrow_the_library_and_reject_bad_values():
    close_push = search_templates("", shot="close", move="push", limit=24)
    assert close_push and all(card["shot"] == "close" and "push" in card["moves"] for card in close_push)
    duets = page_templates("", use="dialogue", subjects=2, format="landscape")
    assert duets["total"] and all(card["subjects"] >= 2 and "dialogue" in card["uses"] and card["format"] == "landscape" for card in duets["templates"])
    assert page_templates("", shot="plate")["total"] == sum(1 for card in builtin_cards() if card["shot"] == "plate")
    anime = page_templates("", category="anime")
    assert anime["total"] == 9 and all("anime" in card["tags"] for card in anime["templates"])
    assert ids(search_templates("baile", category="music", limit=3))[0] == "dance-orbit"
    looks = page_templates("", kind="look")
    assert looks["total"] == sum(1 for card in builtin_cards() if card["kind"] == "look") > 100
    street = page_templates("", place="Chase-Street")
    assert street["total"] and all(card["place"] == "chase-street" for card in street["templates"])
    assert page_templates("", place="nowhere")["total"] == 0
    walkers = page_templates("", travel=True)
    assert walkers["total"] == sum(1 for card in builtin_cards() if card["travel"]) and all(card["travel"] for card in walkers["templates"])
    assert page_templates("", travel=False)["total"] + walkers["total"] == len(builtin_cards())
    for name, value in (("shot", "huge"), ("use", "party"), ("move", "fly"), ("format", "square"), ("subjects", 5), ("subjects", "2"),
                        ("kind", "huge"), ("travel", "yes"), ("place", 3)):
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
    assert reply.json()["result"]["unknown_words"] == []
    kinds = client.post("/api/v1/world3d/templates/commands", json={"operation": "world3d.templates.catalog", "version": 1,
                        "input": {"workspace": "studio", "query": "lluvia", "kind": "look", "travel": False, "limit": 4}})
    assert kinds.status_code == 200 and all(card["kind"] == "look" and card["travel"] is False for card in kinds.json()["result"]["templates"])
    tools = {tool["name"]: tool for tool in command_catalog()}
    for name in ("world3d.templates.list", "world3d.templates.catalog", "world3d.scene.apply_query"):
        fields = tools[name]["inputSchema"]["properties"]["input"]["properties"]
        assert {"shot", "use", "move", "subjects", "format", "kind", "place", "travel"} <= set(fields)
        assert fields["use"]["enum"] == list(USES) and fields["kind"]["enum"] == list(KINDS) and fields["travel"] == {"type": "boolean"}
    description = tools["world3d.templates.list"]["description"]
    assert "still" in description and "unknown_words" in description and "kind" in description and "travel" in description
    assert "partial" in tools["world3d.scene.apply_query"]["description"] and "unknown_words" in tools["world3d.scene.apply_query"]["description"]
    assert tools["world3d.templates.suggest"]["mutation"] is False
    bad = client.post("/api/v1/world3d/templates/commands", json={"operation": "world3d.templates.list", "version": 1,
                      "input": {"workspace": "studio", "shot": "huge"}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_shot"
    assert set(command_handlers(root)) >= {"world3d.templates.list", "world3d.scene.apply_query", "world3d.templates.suggest"}


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
        {"id": "user-walk", "title": "Mi paseo", "description": "una figura zigzaguea", "document": document}]}), encoding="utf-8")
    traits = document_traits(document)
    assert traits == {"subjects": 1, "props": 0, "screens": 1, "authoredFor": "cutout", "floor": "mirror",
                      "moving": ["subjects", "screens", "texts"], "still": None, "travel": True}
    mine = search_templates("mi paseo", workspace_dir=lambda name: str(tmp_path / name), workspace="studio", limit=3)
    assert mine[0]["id"] == "user-walk" and mine[0]["shot"] is None and mine[0]["moves"] == [] and mine[0]["uses"] == []
    assert mine[0]["moving"] == ["subjects", "screens", "texts"] and mine[0]["format"] == "portrait"
    assert mine[0]["kind"] == "scene" and mine[0]["travel"] is True and mine[0]["place"] is None and mine[0]["cameras"] == []
    assert ids(search_templates("", workspace_dir=lambda name: str(tmp_path / name), workspace="studio", shot="plate", limit=24)) == ids(
        search_templates("", shot="plate", limit=24))
    # A personal card makes its own words known to the workspace, and nowhere else.
    report = search_report("paseo zigzaguea", workspace_dir=lambda name: str(tmp_path / name), workspace="studio")
    assert report["unknown_words"] == [] and ids(report["templates"])[0] == "user-walk"
    assert search_report("paseo zigzaguea")["unknown_words"] == ["zigzaguea"]


def test_the_planner_refuses_a_partial_match_and_names_the_unknown_words():
    brief = {"tema": "x", "publico": "y", "duracion": "20 seconds", "musica": "pop", "estilo": "anime", "protagonista": "z",
             "cta": "c", "limites": "l", "lyrics": "[Verse]\nla la"}
    with pytest.raises(PlanError) as refused:
        plan_brief({**brief, "toma": CHURCH})
    assert refused.value.code == "unknown_template" and str(refused.value).endswith("(unknown words: tenso)")
    with pytest.raises(PlanError) as nothing:
        plan_brief({**brief, "toma": "xyzzy plugh"})
    assert nothing.value.code == "unknown_template" and "(unknown words: xyzzy, plugh)" in str(nothing.value)
    with pytest.raises(PlanError) as tied:
        plan_brief({**brief, "toma": "girar alrededor"})
    assert tied.value.code == "ambiguous_template" and "unknown" not in str(tied.value)
    assert plan_brief({**brief, "toma": TAVERN})["world3d_template"] == "cafe-duet"


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
