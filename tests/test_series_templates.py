"""Series templates: a cast, locations, canon and a 2D pilot to start from, in Spanish or English."""
from __future__ import annotations

import copy
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.series_library import create_series_library_router
from services.series_commands import command_catalog
from services.series_shot_plan import build_shot_spec, normalize_layout2d
from services.series_templates import SeriesTemplateError, build_series, list_templates


def test_every_template_builds_a_valid_series_in_both_languages():
    cards = list_templates("en")
    assert {card["id"] for card in cards} >= {"cutout-satire", "explainer", "office-sitcom"}
    for card in cards:
        for language, spoken in (("es", "Español de España"), ("en", "English")):
            series = build_series(card["id"], "cast", language=language)
            assert series["spokenLanguage"] == spoken and series["template"] == {"id": card["id"], "language": language}
            assert "animation_2d" in series["allowedProductionMethods"]
            (episode,) = series["episodesById"].values()
            assert series["seasons"][0]["episodeOrder"] == [episode["id"]]
            characters = {item["id"] for item in series["characters"]}
            locations = {item["id"] for item in series["locations"]}
            scenes = {scene["id"] for scene in episode["script"]}
            for shot in episode["shots"]:
                assert shot["productionMethod"] == "animation_2d" and shot["sceneId"] in scenes and shot["locationId"] in locations
                assert set(shot["visibleCharacterIds"]) <= characters
                assert all(beat["characterId"] in characters and isinstance(beat["text"], str) and beat["text"] for beat in shot["dialogueBeats"])
                assert normalize_layout2d(shot["layout2d"]) == shot["layout2d"], "the 2D plan survives normalization"
            assert episode["shots"][0]["layout2d"]["card"]["kind"] == "title" and episode["shots"][-1]["layout2d"]["card"]["kind"] == "end"


def test_texts_follow_the_language_and_the_title_can_be_chosen():
    spanish = build_series("cutout-satire", "cast", language="es", title="Valle Inquietante")
    english = build_series("cutout-satire", "cast", language="en")
    assert spanish["title"] == "Valle Inquietante" and english["title"] == "Cutout satire"
    assert next(item for item in spanish["characters"] if item["id"] == "rival")["name"] == "Don Pío"
    assert next(item for item in english["characters"] if item["id"] == "rival")["name"] == "Mr Pike"
    assert spanish["canon"]["immutableRules"][0]["status"] == "approved"
    assert spanish["id"] != build_series("cutout-satire", "cast", language="es")["id"], "each series gets its own id"
    with pytest.raises(SeriesTemplateError) as unknown:
        build_series("nope", "cast")
    assert unknown.value.status == 404


def test_a_template_pilot_shot_plans_into_a_2d_scene():
    series = build_series("office-sitcom", "cast", language="en")
    (episode,) = series["episodesById"].values()
    shot = episode["shots"][1]
    recorded = {"b1": {"filename": "b1.wav", "duration": 2.0, "cues": [], "driver": "phoneme"}}
    spec = build_shot_spec(series, episode, shot, workspace="cast", recorded=recorded, first_of_scene=True)
    assert spec["framing"] == "wide" and spec["lines"][0]["text"].startswith("Team!")
    assert spec["cast"] == [], "the template cast has no Character Kits yet; the server render refuses it (missing_kits)"
    title = build_shot_spec(series, episode, episode["shots"][0], workspace="cast", recorded={})
    assert title["framing"] == "title" and title["cast"] == [] and [text["text"] for text in title["texts"]][:1] == ["MONDAY"]


def test_the_routes_list_and_create_and_mcp_offers_them(monkeypatch):
    import routers.series_library as module
    library = {"seriesById": {}, "seriesOrder": []}

    def write(_workspace, value):
        snapshot = copy.deepcopy(value)
        library.clear()
        library.update(snapshot)
        return copy.deepcopy(snapshot)

    # The router reads module globals that the running app also uses: bind them only for this test.
    for name, value in {"_resolve_workspace": lambda value: value or "default", "_library_lock": threading.RLock(),
                        "_read_library": lambda _workspace: library, "_write_library": write,
                        "_project_or_404": lambda current, series_id: current["seriesById"][series_id]}.items():
        monkeypatch.setattr(module, name, value, raising=False)
    app = FastAPI()
    app.include_router(create_series_library_router())
    client = TestClient(app)
    listed = client.get("/api/v1/series/templates", params={"language": "es"})
    assert listed.status_code == 200 and listed.json()["templates"][0]["title"] == "Sátira de recortables"
    created = client.post("/api/v1/series/templates/explainer", json={"workspace": "cast", "language": "en"})
    assert created.status_code == 200, created.text
    assert library["seriesOrder"] == [created.json()["id"]] and created.json()["spokenLanguage"] == "English"
    assert client.post("/api/v1/series/templates/nope", json={"workspace": "cast"}).status_code == 404
    names = {item["name"]: item["mutation"] for item in command_catalog()}
    assert names["series.templates"] is False and names["series.create_from_template"] is True
