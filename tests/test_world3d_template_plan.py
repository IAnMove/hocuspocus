"""``world3d.templates.plan`` chooses the cards of a whole list of shots in one call, with variety, and never writes."""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.wangp_mcp import create_wangp_mcp_router
from routers.world3d_templates import create_world3d_templates_router
from services.mcp_profiles import SERIES_TOOLS
from services.production_scene3d import CONFIG_KEYS, validate_scene3d_shot
from services.production_template_fit import camera_key, fit_problems, fit_warnings, repeated_templates
from services.series_shot3d import normalize_scene3d
from services.world3d_stage_cards import DEFAULT_CAMERA, stage_card
from services.world3d_template_catalog import World3DTemplateError, builtin_cards, search_report, suggest_templates
from services.world3d_template_commands import command_catalog, command_handlers
from services.world3d_template_compact import COMPACT_KEYS, compact_card
from services.world3d_template_places import read_place, stage_camera_shots
from services.world3d_template_plan import plan_templates
from services.world3d_template_vocabulary import GROUPS, PLACE_ANCHORS, PLACE_GROUPS

OPERATION = "world3d.templates.plan"
TWELVE = ["a woman walks along a beach at dawn", "two friends argue in a kitchen", "the hero runs across a rooftop",
          "a spaceship leaves the planet", "close up of a sad face", "a car drives through the tunnel",
          "an ancient castle at night", "two soldiers talk in the forest", "a dance on a stage",
          "a product orbit on a pedestal", "the city skyline at sunset", "a boy cries at the church"]


def shots_of(texts, **each):
    return [{"key": f"s{index + 1}", "text": text, **each} for index, text in enumerate(texts)]


def primaries(result):
    return [entry["primary"] for entry in result["plan"]]


def ids_of(result):
    return [primary["id"] for primary in primaries(result)]


def client_for(tmp_path):
    root = lambda workspace: str(tmp_path / workspace)
    app = FastAPI()
    app.include_router(create_world3d_templates_router(root))
    app.include_router(create_wangp_mcp_router(handlers=command_handlers(root), command_operations=command_catalog(),
        journal_path=str(tmp_path / "journal.json"), token_getter=lambda: "test-token"))
    return TestClient(app)


def call(client, operation, data, *, mcp=False):
    arguments = {"version": 1, "input": {"workspace": "studio", **data}}
    if mcp:
        response = client.post("/api/v1/mcp", headers={"Authorization": "Bearer test-token"}, json={"jsonrpc": "2.0", "id": 1,
            "method": "tools/call", "params": {"name": operation, "arguments": arguments}})
        assert response.status_code == 200, response.text
        payload = response.json()["result"]
        assert payload.get("isError") is not True, payload
        return payload["structuredContent"]
    response = client.post("/api/v1/world3d/templates/commands", json={"operation": operation, **arguments})
    assert response.status_code == 200, response.text
    return response.json()


def test_a_twelve_shot_plan_has_no_consecutive_repeat_and_no_template_more_than_twice():
    for seed in range(4):
        result = plan_templates({"shots": shots_of(TWELVE), "seed": seed})
        ids = ids_of(result)
        assert len(ids) == 12 and all(ids)
        assert all(first != second for first, second in zip(ids, ids[1:])), ids
        assert max(ids.count(name) for name in ids) <= 2, ids
        assert result["summary"]["templates_used"] == len(set(ids)) and result["summary"]["repeats"] == 12 - len(set(ids))
        formats = {name: sum(1 for primary in primaries(result) if primary["format"] == name) for name in ("landscape", "portrait")}
        assert result["summary"]["formats"] == {name: count for name, count in formats.items() if count}
        assert all(entry["primary"]["id"] not in [alt["id"] for alt in entry["alternates"]] for entry in result["plan"])
        assert all(len(entry["alternates"]) == 2 for entry in result["plan"])


def test_the_shot_size_and_the_camera_move_alternate_when_the_neighbour_has_the_same():
    result = plan_templates({"shots": shots_of([""] * 10, speakers=1), "seed": 3})
    sizes = [primary["shot"] for primary in primaries(result)]
    assert sum(1 for first, second in zip(sizes, sizes[1:]) if first == second) <= 2, sizes
    asked = plan_templates({"shots": [{"key": "a", "text": "", "speakers": 2, "shot": "close"},
                                      {"key": "b", "text": "", "speakers": 2, "shot": "wide"}]})
    assert [primary["shot"] for primary in primaries(asked)] == ["close", "wide"]


def test_shots_at_one_place_keep_the_stage_and_change_the_camera():
    shots = [{"key": "k1", "text": "two friends argue in a kitchen at night", "speakers": 2},
             {"key": "k2", "text": "the cook answers coldly in the kitchen", "speakers": 1},
             {"key": "k3", "text": "they argue over dinner in the kitchen", "speakers": 2},
             {"key": "k4", "text": "las dos discuten en la cocina", "speakers": 2}]
    result = plan_templates({"shots": shots})
    fragments = [primary["scene3d"] for primary in primaries(result)]
    assert {fragment["template"] for fragment in fragments} == {"stage-cocina"}
    cameras = [fragment["roomCamera"] for fragment in fragments]
    assert all(first != second for first, second in zip(cameras, cameras[1:])), cameras
    assert set(cameras) <= set(stage_card("stage-cocina")["cameras"])
    keys = [camera_key(fragment) for fragment in fragments]
    assert all(first != second for first, second in zip(keys, keys[1:]))
    assert repeated_templates([{"key": entry["key"], "kind": "scene3d", "scene3d": entry["primary"]["scene3d"]} for entry in result["plan"]], []) == []
    shown = {primary["shot"] for primary in primaries(result)}
    assert shown == {stage_camera_shots("stage-cocina")[camera] for camera in cameras} and len(shown) >= 2


def test_shots_at_one_scene_place_play_their_cards_in_the_same_world():
    shots = [{"key": "d1", "text": "two travellers talk in the desert at sunset", "speakers": 2},
             {"key": "d2", "text": "close on her tired face in the desert", "speakers": 1, "shot": "close"},
             {"key": "d3", "text": "wide shot of the dunes", "speakers": 0, "shot": "wide"},
             {"key": "d4", "text": "they argue in the desert", "speakers": 2}]
    result = plan_templates({"shots": shots})
    fragments = [primary["scene3d"] for primary in primaries(result)]
    worlds = {fragment["world"] for fragment in fragments if "world" in fragment}
    assert len(worlds) == 1 and next(iter(worlds)).startswith("atmos-desert")
    assert all("roomCamera" not in fragment for fragment in fragments)
    cards = {card["id"]: card for card in builtin_cards()}
    for fragment in fragments:
        assert cards[fragment["template"]].get("place") == "atmos-desert" or fragment.get("world") in worlds
    assert "dialogue" in cards[fragments[0]["template"]]["uses"] and cards[fragments[0]["template"]]["subjects"] >= 2
    assert not any(cards[world]["kind"] == "stage" for world in worlds)
    assert len({fragment["template"] for fragment in fragments}) == 4


def test_a_place_word_outweighs_the_free_words_of_a_long_line():
    long_line = "they argue over dinner in the kitchen late at night while the rain beats on the window"
    assert suggest_templates(line=long_line, speakers=2)["templates"] == []       # one query: no card has half of the words
    for line in (long_line, "two friends argue in a kitchen at night", "dos amigos discuten en una cocina de noche"):
        result = plan_templates({"shots": [{"key": "a", "text": line, "speakers": 2}]})
        assert ids_of(result) == ["stage-cocina"] and result["plan"][0]["warnings"] == []
    nowhere = plan_templates({"shots": [{"key": "a", "text": "two friends argue", "speakers": 2, "place": "cocina"}]})
    assert ids_of(nowhere) == ["stage-cocina"]
    desert = plan_templates({"shots": [{"key": "a", "text": "two travellers talk in the desert", "speakers": 2}]})
    fragment = desert["plan"][0]["primary"]["scene3d"]
    assert fragment["world"].startswith("atmos-desert") and "dialogue" in next(
        card for card in builtin_cards() if card["id"] == fragment["template"])["uses"]
    assert read_place("en la cocina", "")[0] == read_place("in the kitchen", "")[0] != ""
    assert read_place("two friends", "")[0] == "" and read_place("at night, at noon, at sunset", "")[0] == ""
    assert read_place("el bar de siempre", "")[1] == ("bar",) and read_place("the show goes on", "")[0] == ""
    assert read_place("two friends", "the attic") == ("attic", ("attic",))     # a place the vocabulary does not group is its own
    assert read_place("in the kitchen", "the attic")[0] == "attic"            # the shot's own place field wins over the line


def test_the_same_input_and_seed_give_the_same_plan_and_another_seed_another_valid_one():
    shots = shots_of([""] * 8, speakers=2)
    first = plan_templates({"shots": shots, "seed": 5})
    assert plan_templates({"shots": shots, "seed": 5}) == first
    other = plan_templates({"shots": shots, "seed": 6})
    assert ids_of(other) != ids_of(first)
    for result in (first, other):
        ids = ids_of(result)
        assert all(a != b for a, b in zip(ids, ids[1:])) and max(ids.count(name) for name in ids) <= 2
    unseeded = plan_templates({"shots": shots})
    assert unseeded == plan_templates({"shots": shots, "seed": 0})


def test_no_word_shots_break_ties_by_variety_not_by_catalogue_order():
    catalogue_order = [card["id"] for card in search_report("", limit=3, use="dialogue", subjects=2)["templates"]]
    assert catalogue_order == ["speech-dialogue", "two-shot", "over-shoulder"]
    firsts = {ids_of(plan_templates({"shots": shots_of([""], speakers=2), "seed": seed}))[0] for seed in range(8)}
    assert len(firsts) >= 4 and firsts != set(catalogue_order)
    nothing = plan_templates({"shots": shots_of(["", "", ""]), "seed": 2})
    assert len(set(ids_of(nothing))) == 3


def test_avoid_is_never_taken_not_even_as_an_alternate():
    shots = shots_of(["two friends argue in a kitchen", "two friends talk on a rooftop"], speakers=2)
    plain = plan_templates({"shots": shots})
    banned = sorted({card["id"] for entry in plain["plan"] for card in [entry["primary"], *entry["alternates"]]})
    result = plan_templates({"shots": shots, "avoid": banned})
    seen = {card["id"] for entry in result["plan"] for card in [entry["primary"], *entry["alternates"]] if card}
    assert seen.isdisjoint(banned) and all(entry["primary"] for entry in result["plan"])
    everything = plan_templates({"shots": shots_of(["kitchen"]), "avoid": [card["id"] for card in builtin_cards()]})
    assert len(builtin_cards()) < 1000
    assert everything["plan"][0]["primary"] is None and everything["plan"][0]["warnings"][0].startswith("no_card")


def test_a_still_card_is_never_the_primary_while_another_card_fits():
    cards = {card["id"]: card for card in builtin_cards()}
    for seed in range(3):
        result = plan_templates({"shots": shots_of(TWELVE, speakers=1), "seed": seed})
        assert not any(cards[name].get("still") for name in ids_of(result))


def test_portrait_takes_portrait_cards_and_falls_back_to_adapted_landscape_ones():
    shots = [{"key": "a", "text": "two friends argue", "speakers": 2}, {"key": "b", "text": "she answers", "speakers": 1},
             {"key": "c", "text": "a lonely road", "speakers": 0}, {"key": "d", "text": "", "speakers": 2}]
    result = plan_templates({"shots": shots, "format": "portrait"})
    entries = primaries(result)
    assert all(entry and entry["scene3d"]["width"] == 1080 and entry["scene3d"]["height"] == 1920 for entry in entries)
    assert all("adapted" not in entry and entry["format"] == "portrait" for entry in entries), entries
    # A place with a landscape stage and no portrait card still falls back to that stage, reframed.
    kitchen = primaries(plan_templates({"shots": [{"key": "k", "text": "two friends argue in the kitchen", "speakers": 2}],
                                        "format": "portrait"}))[0]
    assert kitchen["id"] == "stage-cocina" and kitchen["adapted"] is True and kitchen["format"] == "landscape"
    assert "portrait" in kitchen["note"] and len(kitchen["note"].splitlines()) == 1
    assert kitchen["scene3d"]["width"] == 1080 and kitchen["scene3d"]["height"] == 1920
    landscape = plan_templates({"shots": shots, "format": "landscape"})
    assert all("width" not in entry["scene3d"] and "adapted" not in entry and entry["format"] == "landscape" for entry in primaries(landscape))
    none = plan_templates({"shots": shots})
    assert all("width" not in entry["scene3d"] and "adapted" not in entry and entry["format"] == "landscape"
               for entry in primaries(none))


def test_a_vertical_dialogue_plan_takes_the_cards_drawn_for_nine_by_sixteen():
    cards = {card["id"]: card for card in builtin_cards()}
    for seed in range(3):
        dialogue = plan_templates({"shots": shots_of([""] * 12, speakers=2), "format": "portrait", "seed": seed})
        ids = ids_of(dialogue)
        assert all(name.startswith("vertical-dialogue-") for name in ids), ids
        assert all(cards[name]["format"] == "portrait" and "dialogue" in cards[name]["uses"] and cards[name]["subjects"] == 2
                   and not cards[name]["still"] for name in ids)
        assert all("adapted" not in entry for entry in primaries(dialogue)) and max(ids.count(name) for name in ids) <= 2
        assert dialogue["summary"]["formats"] == {"portrait": 12}
        talk = plan_templates({"shots": shots_of(["she answers"] * 6, speakers=1), "format": "portrait", "seed": seed})
        assert all(entry["format"] == "portrait" and "adapted" not in entry for entry in primaries(talk))
    lines = plan_templates({"shots": shots_of(["two friends argue", "they keep talking", "he answers back"], speakers=2),
                            "format": "portrait"})
    assert all(name.startswith("vertical-dialogue-") for name in ids_of(lines))
    desert = plan_templates({"shots": shots_of(["two travellers talk in the desert", "they keep talking in the desert"], speakers=2),
                             "format": "portrait"})
    assert all(entry["id"].startswith("vertical-") and entry["scene3d"]["world"].startswith("atmos-desert")
               for entry in primaries(desert))


def test_the_vertical_cards_answer_vertical_words_and_leave_plain_dialogue_to_the_landscape_ones():
    for query in ("diálogo vertical", "dos personas hablando en vertical", "portrait dialogue", "conversación vertical"):
        top = search_report(query, limit=8)["templates"]
        assert top and all(card["id"].startswith("vertical-dialogue-") and card["match"] == "full" for card in top[:4]), (query, top)
    for query in ("contraplano vertical", "over the shoulder portrait"):
        assert {card["id"] for card in search_report(query, limit=2)["templates"]} == {"vertical-dialogue-ots-a", "vertical-dialogue-ots-b"}
    for query in ("habla a cámara en vertical", "talking to camera vertical"):
        assert all(card["id"].startswith("vertical-") for card in search_report(query, limit=5)["templates"]), query
    # Without a vertical word the landscape cards lead as before; the vertical ones follow at a lower score.
    plain = search_report("diálogo", limit=8)["templates"]
    assert [card["id"] for card in plain[:3]] == ["duo-diagonal", "speech-dialogue", "two-shot"]
    assert not any(card["id"].startswith("vertical-") for card in plain[:5])
    assert all(card["score"] < plain[0]["score"] for card in plain if card["id"].startswith("vertical-"))


def test_a_plan_without_a_format_is_for_the_production_frame_and_takes_landscape_cards():
    for seed in range(3):
        for speakers in (0, 1, 2):
            for texts in (TWELVE, [""] * 12):
                result = plan_templates({"shots": shots_of(texts, speakers=speakers), "seed": seed})
                assert result["summary"]["formats"] == {"landscape": 12}, (speakers, seed, ids_of(result))
                assert all(item["format"] == "landscape" for entry in result["plan"] for item in entry["alternates"])


def test_a_compact_card_is_under_four_hundred_bytes_for_every_card():
    sizes = []
    for card in builtin_cards():
        short = compact_card(card)
        assert tuple(short) == COMPACT_KEYS
        sizes.append(len(json.dumps(short, ensure_ascii=False).encode("utf-8")))
    assert max(sizes) < 400, max(sizes)
    full = len(json.dumps(search_report("zoom", limit=1)["templates"][0]).encode("utf-8"))
    assert sum(sizes) / len(sizes) < full / 3
    entry = plan_templates({"shots": shots_of(["two friends argue in a kitchen"], speakers=2)})["plan"][0]["primary"]
    assert len(json.dumps(entry).encode("utf-8")) < 520 and tuple(entry)[:6] == COMPACT_KEYS


def test_plan_fragments_pass_the_fit_gate_for_primaries_and_alternates():
    cards = {card["id"]: card for card in builtin_cards()}
    texts = [*TWELVE, "they argue over dinner in the kitchen", "two travellers talk in the desert", "she answers", "wide of the dunes"]
    for frame in (None, "portrait"):
        for seed in (0, 1):
            speakers = [2 if index % 3 == 0 else 1 if index % 3 == 1 else 0 for index in range(len(texts))]
            shots = [{"key": f"s{i}", "text": text, "speakers": who} for i, (text, who) in enumerate(zip(texts, speakers))]
            result = plan_templates({"shots": shots, **({"format": frame} if frame else {}), "seed": seed})
            for rank in range(3):
                production = []
                for entry, who in zip(result["plan"], speakers):
                    option = ([entry["primary"], *entry["alternates"]] + [entry["primary"]] * 3)[rank]
                    cast = {role: "model.glb" for role in ("subject_1", "subject_2")[:min(who, 2)]}
                    scene3d = {**option["scene3d"], **({"cast": cast} if cast else {})}      # nobody speaks: nobody is cast
                    assert set(scene3d) <= CONFIG_KEYS
                    production.append({"key": entry["key"], "kind": "scene3d", "scene3d": scene3d})
                problems = fit_problems({}, production)
                assert [item for item in problems if item["code"] in ("unknown_template", "cast_role_not_on_card")] == [], problems
                assert problems == []
                for shot in production:
                    template = shot["scene3d"]["template"]
                    assert template in cards
                    assert "world" not in shot["scene3d"] or cards[shot["scene3d"]["world"]]["kind"] != "stage"
                    if rank == 0 and shot["scene3d"].get("cast"):
                        validate_scene3d_shot(shot)
                        assert normalize_scene3d({"template": template, "cast": [], "roomCamera": shot["scene3d"].get("roomCamera")} if shot["scene3d"].get("roomCamera") else {"template": template, "cast": []})
                warnings = fit_warnings({}, production)
                assert all(item["code"] == "template_format" for item in warnings)
                if frame == "portrait" and rank == 0:
                    adapted = {entry["key"] for entry in result["plan"] if entry["primary"].get("adapted")}
                    flagged = {key for item in warnings for key in item["shots"]}
                    assert flagged == adapted


def test_the_plan_over_http_and_mcp_is_read_only_and_the_series_profile_has_the_tools(tmp_path):
    tool = next(item for item in command_catalog() if item["name"] == OPERATION)
    assert tool["mutation"] is False and "ONE call" in tool["description"] and "never instantiates" in tool["description"]
    fields = tool["inputSchema"]["properties"]["input"]["properties"]
    assert set(fields) == {"workspace", "shots", "format", "avoid", "per_shot", "seed", "language"}
    assert set(fields["shots"]["items"]["properties"]) == {"key", "text", "speakers", "subjects", "place", "shot", "moving"}
    assert tool["inputSchema"]["properties"]["input"]["required"] == ["workspace", "shots"] and "intent_id" not in tool["inputSchema"]["properties"]
    assert {OPERATION, "world3d.templates.catalog", "world3d.templates.suggest", "world3d.templates.list"} <= SERIES_TOOLS
    client = client_for(tmp_path)
    tools = client.post("/api/v1/mcp", headers={"Authorization": "Bearer test-token"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
    assert OPERATION in {item["name"] for item in tools}
    data = {"shots": shots_of(["two friends argue in a kitchen", "she looks out of the window"], speakers=2), "seed": 2}
    http, mcp = call(client, OPERATION, data), call(client, OPERATION, data, mcp=True)
    assert http["operation"] == OPERATION and http["status"] == "completed"
    assert http["result"]["plan"] == mcp["result"]["plan"] == plan_templates(data)["plan"]
    assert set(http["result"]) == {"status", "plan", "summary"}
    for bad, code in (({"shots": []}, "invalid_shots"), ({"shots": [{"key": "a"}, {"key": "a"}]}, "invalid_shot_key"),
                      ({"shots": [{"key": "a", "speakers": 9}]}, "invalid_speakers"), ({"shots": [{"key": "a", "subjects": 3}]}, "invalid_subjects"),
                      ({"shots": [{"key": "a", "shot": "huge"}]}, "invalid_shot"), ({"shots": [{"key": "a", "moving": "yes"}]}, "invalid_moving"),
                      ({"shots": [{"key": "a"}], "format": "square"}, "invalid_format"), ({"shots": [{"key": "a"}], "per_shot": 4}, "invalid_per_shot"),
                      ({"shots": [{"key": "a"}], "seed": -1}, "invalid_seed"), ({"shots": [{"key": "a"}], "avoid": "x"}, "invalid_avoid"),
                      ({"shots": [{"key": "a"}], "language": "fr"}, "invalid_language"), ({"shots": [{"key": "a", "text": "x" * 401}]}, "invalid_text")):
        reply = client.post("/api/v1/world3d/templates/commands", json={"operation": OPERATION, "version": 1, "input": {"workspace": "studio", **bad}})
        assert reply.status_code == 422 and reply.json()["detail"]["code"] == code, (bad, reply.text)
        with pytest.raises(World3DTemplateError):
            plan_templates(bad)
    assert not (tmp_path / "studio").exists()


def test_per_shot_and_language_shape_the_reply():
    one = plan_templates({"shots": shots_of(["a kitchen"], speakers=2), "per_shot": 1})
    assert one["plan"][0]["alternates"] == []
    es = plan_templates({"shots": shots_of(["la cocina"], speakers=2), "per_shot": 2, "language": "es"})
    assert len(es["plan"][0]["alternates"]) == 1 and es["plan"][0]["primary"]["title"] == stage_card("stage-cocina")["titleEs"]
    en = plan_templates({"shots": shots_of(["la cocina"], speakers=2), "per_shot": 1})
    assert en["plan"][0]["primary"]["title"] == stage_card("stage-cocina")["titleEn"]


def test_compact_shortens_suggest_and_catalog_and_the_default_is_unchanged(tmp_path):
    client = client_for(tmp_path)
    full = call(client, "world3d.templates.suggest", {"line": "dos amigos hablando en una azotea", "speakers": 2, "limit": 2})["result"]
    short = call(client, "world3d.templates.suggest", {"line": "dos amigos hablando en una azotea", "speakers": 2, "limit": 2, "compact": True})["result"]
    assert [card["id"] for card in short["templates"]] == [card["id"] for card in full["templates"]]
    assert all(tuple(card) == COMPACT_KEYS for card in short["templates"]) and "reason" in full["templates"][0]
    assert short["unknown_words"] == full["unknown_words"] and short["filters"] == full["filters"]
    assert len(json.dumps(short["templates"])) < len(json.dumps(full["templates"])) / 3
    catalog = call(client, "world3d.templates.catalog", {"query": "cocina", "limit": 3, "compact": True, "language": "es"}, mcp=True)["result"]
    assert catalog["templates"][0]["id"] == "stage-cocina" and tuple(catalog["templates"][0]) == COMPACT_KEYS
    assert catalog["templates"][0]["title"] == stage_card("stage-cocina")["titleEs"]
    default = call(client, "world3d.templates.catalog", {"query": "cocina", "limit": 3})["result"]
    assert "lineEs" in default["templates"][0] and call(client, "world3d.templates.catalog", {"query": "cocina", "limit": 3, "compact": False})["result"] == default
    bad = client.post("/api/v1/world3d/templates/commands", json={"operation": "world3d.templates.suggest", "version": 1,
                      "input": {"workspace": "studio", "compact": "yes"}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_compact"


def test_the_place_words_are_one_group_each_and_leave_out_times_and_looks():
    assert len(PLACE_GROUPS) == len(PLACE_ANCHORS)
    for anchor in PLACE_ANCHORS:
        assert sum(1 for group in GROUPS if anchor in group) == 1
    for word in ("night", "noon", "sunset", "dawn", "summer", "interior", "pixel", "anime", "show", "ride", "convoy", "two"):
        assert read_place(f"a {word} again", "")[0] == "", word
    for word in ("kitchen", "cocina", "rooftop", "desert", "bar", "church", "corridor", "sala", "wagon"):
        assert read_place(f"in the {word}", "")[0] != "", word


def test_a_stage_camera_shows_the_shot_size_the_card_measured_from_its_default_camera():
    for card in builtin_cards():
        if card.get("kind") == "stage":
            sizes = stage_camera_shots(card["id"])
            assert set(sizes) == set(card["cameras"]) and sizes[DEFAULT_CAMERA] == card["shot"]
    assert stage_camera_shots("two-shot") == {}
