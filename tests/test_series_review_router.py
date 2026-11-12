"""The staged review over HTTP and MCP: what the Series Lab UI and an agent use to read and answer the user's review."""
import asyncio
import io
import json
import threading
import urllib.error
import urllib.parse

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routers.series_review import create_series_review_router
from services.series_commands import OPERATIONS, command_catalog, command_handlers
from services.series_library import read_series_library, write_series_library
from services.mcp_profiles import SERIES_TOOLS

NOW = "2026-10-06T10:00:00Z"


def _library(root):
    shots = [{"id": f"s0{index}", "order": index, "sceneId": "scene_1", "productionMethod": "animation_2d",
              "visibleCharacterIds": ["ines"], "locationId": "deck", "framing": "medium", "camera": "static",
              "dialogueBeats": [{"id": f"s0{index}_b0", "characterId": "ines", "text": f"Línea {index}"}],
              "attempts": [{"id": f"a{index}", "status": "completed", "outputAssetIds": [f"asset_a{index}"], "reviewStage": "preview"}]
              if index == 2 else []} for index in (1, 2, 3)]
    series = {"id": "mp", "title": "Más allá", "allowedProductionMethods": ["animation_2d"],
              "characters": [{"id": "ines", "name": "Inés"}], "locations": [{"id": "deck", "name": "Cubierta"}],
              "assets": {"asset_a2": {"id": "asset_a2", "kind": "video", "uri": "assets/mp/a2.mp4", "ownerType": "attempt", "ownerId": "a2"}},
              "episodesById": {"ep1": {"id": "ep1", "title": "La confesión", "shots": shots,
                                       "script": [{"id": "scene_1", "order": 1, "locationId": "deck"}]}}}
    write_series_library(str(root), {"schema": "series-library", "version": 1, "workspaceId": "plus", "seriesOrder": ["mp"],
                                     "seriesById": {"mp": series}}, "plus")


def _app(root):
    lock = threading.RLock()
    app = FastAPI()
    app.include_router(create_series_review_router(
        resolve_workspace=lambda value: str(value or "plus"), lock=lock,
        read_library=lambda workspace: read_series_library(str(root), workspace),
        write_library=lambda workspace, value: write_series_library(str(root), value, workspace), iso_now=lambda: NOW))
    return TestClient(app)


def test_the_ui_sets_a_mode_decides_shots_and_the_state_survives_a_reload(tmp_path):
    _library(tmp_path)
    client = _app(tmp_path)
    path = "/api/v1/series/mp/episodes/ep1/review"
    saved = client.post(path, json={"workspace": "plus", "baseRevision": 1, "mode": "preview", "shots": [
        {"shotId": "s01", "plan": "approved"},
        {"shotId": "s02", "plan": "approved", "preview": "changes", "note": {"text": "Inés debe mirar al mar"}}]})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["revision"] == 2 and body["review"]["mode"] == "preview"
    assert body["review"]["shots"]["s02"]["preview"] == "changes" and body["review"]["shots"]["s02"]["previewAttemptId"] == "a2"
    assert body["noteIds"]["s02"].startswith("note_")
    assert body["summary"]["nextStep"] == {"kind": "approve_plan", "count": 1}
    stored = read_series_library(str(tmp_path), "plus")["seriesById"]["mp"]["episodesById"]["ep1"]["review"]
    assert stored == body["review"], "what the UI gets back is what is stored"
    report = client.get(path, params={"workspace": "plus"}).json()
    assert [(shot["shotId"], shot["step"]) for shot in report["shots"]] == [("s01", "render_previews"), ("s02", "changes"),
                                                                            ("s03", "approve_plan")]
    assert report["shots"][1]["notes"][0]["text"] == "Inés debe mirar al mar"
    stale = client.post(path, json={"workspace": "plus", "baseRevision": 1, "shots": [{"shotId": "s03", "plan": "approved"}]})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "series_conflict"
    refused = client.post(path, json={"workspace": "plus", "shots": [{"shotId": "s03", "preview": "approved"}]})
    assert refused.status_code == 400 and "render its preview first" in refused.json()["detail"]["message"]
    missing = client.post("/api/v1/series/mp/episodes/nope/review", json={"workspace": "plus", "mode": "plan"})
    assert missing.status_code == 404


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _mcp(tmp_path):
    client = _app(tmp_path)
    calls = []

    def opener(request, timeout):
        url = urllib.parse.urlsplit(request.full_url)
        target = url.path + (f"?{url.query}" if url.query else "")
        calls.append((request.get_method(), url.path))
        response = client.request(request.get_method(), target, content=request.data, headers=dict(request.headers))
        if response.status_code >= 400:
            raise urllib.error.HTTPError(request.full_url, response.status_code, "error", {}, io.BytesIO(response.content))
        return _Response(response.content)

    handlers = command_handlers(lambda: "http://127.0.0.1:9", lambda _name: str(tmp_path), lambda: str(tmp_path / "uploads"),
                                opener=opener)
    return handlers, calls


def _call(handlers, name, data, **envelope):
    return asyncio.run(handlers[name]({"version": 1, "input": data, **envelope}))["result"]


def test_an_agent_reads_the_notes_answers_them_and_a_retry_replays(tmp_path):
    _library(tmp_path)
    handlers, calls = _mcp(tmp_path)
    where = {"workspace": "plus", "series_id": "mp", "episode_id": "ep1"}
    set_mode = _call(handlers, "series.episode.review.set", {**where, "mode": "plan", "shots": [
        {"shot_id": "s01", "plan": "changes", "note": {"text": "Más cerca de la cámara"}}]})
    assert set_mode["mode"] == "plan" and set_mode["shots"]["s01"]["plan"] == "changes"
    review = _call(handlers, "series.episode.review.get", where)["review"]
    request = next(shot for shot in review["shots"] if shot["shotId"] == "s01")
    assert request["notes"][0]["text"] == "Más cerca de la cámara" and request["step"] == "changes"
    answer = {**where, "shot_id": "s01", "plan": "pending", "note": {"text": "Hecho: plano medio corto", "by": "agent"}}
    first = _call(handlers, "series.shot.review.set", answer, intent_id="answer-s01")
    posts = len([call for call in calls if call[0] == "POST"])
    again = _call(handlers, "series.shot.review.set", answer, intent_id="answer-s01")
    assert again == {**first, "replayed": True}
    assert len([call for call in calls if call[0] == "POST"]) == posts, "a retried intent does not write again"
    notes = first["shots"]["s01"]["notes"]
    assert [(note["by"], note["text"]) for note in notes] == [("user", "Más cerca de la cámara"), ("agent", "Hecho: plano medio corto")]
    with pytest.raises(HTTPException) as conflict:
        _call(handlers, "series.shot.review.set", {**answer, "plan": "approved"}, intent_id="answer-s01")
    assert conflict.value.status_code == 409 and conflict.value.detail["code"] == "intent_conflict"
    with pytest.raises(HTTPException) as refused:
        _call(handlers, "series.shot.review.set", {**where, "shot_id": "nope", "plan": "approved"})
    assert refused.value.status_code == 404 and refused.value.detail["code"] == "not_found"


def test_the_review_tools_are_catalogued_with_intent_ids_and_in_the_series_profile():
    catalog = {operation["name"]: operation for operation in command_catalog()}
    for name in ("series.episode.review.get", "series.episode.review.set", "series.shot.review.set"):
        assert name in OPERATIONS and name in SERIES_TOOLS
    assert catalog["series.episode.review.get"]["mutation"] is False
    assert "intent_id" in catalog["series.shot.review.set"]["inputSchema"]["properties"]
    assert "intent_id" not in catalog["series.episode.review.get"]["inputSchema"]["properties"]
    assert "force" in OPERATIONS["series.assembly.start"][0]
    note = OPERATIONS["series.shot.review.set"][0]["note"]
    assert note["required"] == ["text"] and note["properties"]["by"]["enum"] == ["user", "agent"]


def test_each_decision_and_note_says_who_made_it(tmp_path):
    """A person in Series Lab is ``user``; an agent's MCP call reaches the route through a loopback that declares it."""
    from services.agent_activity import ActorHeaderMiddleware
    _library(tmp_path)
    client = _app(tmp_path)
    client.app.add_middleware(ActorHeaderMiddleware)
    path = "/api/v1/series/mp/episodes/ep1/review"
    mine = client.post(path, json={"workspace": "plus", "mode": "preview", "shots": [{"shotId": "s01", "plan": "approved"}]})
    assert mine.json()["review"]["shots"]["s01"]["planBy"] == "user"
    agent = client.post(path, headers={"X-Hocus-Actor": "agent"}, json={"workspace": "plus", "shots": [
        {"shotId": "s02", "plan": "approved", "preview": "changes", "note": {"text": "Más luz en la cara"}}]})
    shot = agent.json()["review"]["shots"]["s02"]
    assert (shot["planBy"], shot["previewBy"], shot["notes"][0]["by"]) == ("agent", "agent", "agent")
    wizard = client.post(path, headers={"X-Hocus-UI-Surface": "wizard"}, json={"workspace": "plus", "shots": [
        {"shotId": "s03", "plan": "changes", "note": {"text": "Otro encuadre", "by": "user"}}]})
    shot = wizard.json()["review"]["shots"]["s03"]
    assert shot["planBy"] == "wizard" and shot["notes"][0]["by"] == "user", "a note's own author wins"
    stored = read_series_library(str(tmp_path), "plus")["seriesById"]["mp"]["episodesById"]["ep1"]["review"]["shots"]
    assert stored["s02"]["previewBy"] == "agent", "the decider survives normalization"
