"""``world3d.templates.suggest`` answers a writer's shot with a few cards and plain reasons, and never writes."""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.wangp_mcp import create_wangp_mcp_router
from routers.world3d_templates import create_world3d_templates_router
from services.world3d_template_catalog import SUGGEST_BEATS, World3DTemplateError, suggest_templates
from services.world3d_template_commands import command_catalog, command_handlers
from services.world3d_template_vocabulary import FORMATS, KINDS

OPERATION = "world3d.templates.suggest"


def client_for(tmp_path):
    root = lambda workspace: str(tmp_path / workspace)
    app = FastAPI()
    app.include_router(create_world3d_templates_router(root))
    app.include_router(create_wangp_mcp_router(handlers=command_handlers(root), command_operations=command_catalog(),
        journal_path=str(tmp_path / "journal.json"), token_getter=lambda: "test-token"))
    return TestClient(app)


def call(client, data, *, mcp=False):
    arguments = {"version": 1, "input": {"workspace": "studio", **data}}
    if mcp:
        response = client.post("/api/v1/mcp", headers={"Authorization": "Bearer test-token"}, json={"jsonrpc": "2.0", "id": 1,
            "method": "tools/call", "params": {"name": OPERATION, "arguments": arguments}})
        assert response.status_code == 200, response.text
        payload = response.json()["result"]
        assert payload.get("isError") is not True, payload
        return payload["structuredContent"]
    response = client.post("/api/v1/world3d/templates/commands", json={"operation": OPERATION, **arguments})
    assert response.status_code == 200, response.text
    return response.json()


def ids(found):
    return [card["id"] for card in found["templates"]]


def test_speakers_place_and_mood_become_filters_and_query_words():
    found = suggest_templates(speakers=2, place="cocina", mood="triste")
    assert found["filters"] == {"use": "dialogue", "subjects": 2}
    assert found["unknown_words"] == [] and found["partial"] is True       # no kitchen is sad: the place leads, partially
    assert found["templates"] and all(card["subjects"] == 2 and "dialogue" in card["uses"] for card in found["templates"])
    assert ids(found)[0] == "stage-cocina" and found["templates"][1]["shot"] == "close"
    assert found["templates"][0]["reason"] == ("two subjects, wide, moves on its own, uses: dialogue, talk, figure; place: cocina; "
                                               "cameras: two_shot, ots_a, ots_b, wide, close_1, close_2, entrance; partial match")
    kitchen = suggest_templates(speakers=2, place="cocina")
    assert kitchen["partial"] is False and ids(kitchen) == ["stage-cocina"]
    one = suggest_templates(speakers=1, line="el presentador habla a cámara")
    assert one["filters"] == {"use": "talk", "subjects": 1} and ids(one)[0] == "speech-presenter"
    assert one["templates"][0]["reason"] == "one subject, close, moves: push, uses: talk, reaction"
    assert len(one["templates"]) == 3


def test_nobody_speaking_asks_an_establishing_shot_and_the_beat_wins():
    plate = suggest_templates(speakers=0, place="bosque")
    assert plate["filters"] == {"use": "establishing"}
    assert all("establishing" in card["uses"] for card in plate["templates"])
    assert plate["templates"][0]["reason"].startswith("no subject, plate") and "place: pixel-forest" in plate["templates"][0]["reason"]
    beat = suggest_templates(speakers=2, beat="reaction")
    assert beat["filters"] == {"use": "reaction", "subjects": 2}
    speed = suggest_templates(beat="speed", line="el coche acelera por la carretera")
    assert speed["filters"] == {"use": "speed"} and all("speed" in card["uses"] for card in speed["templates"])
    look = suggest_templates(kind="look", format="landscape", line="neón")
    assert look["filters"] == {"format": "landscape", "kind": "look"} and ids(look)[0] == "cine-neon-practical"
    assert all(card["kind"] == "look" for card in look["templates"])


def test_reasons_say_motion_place_and_travel_in_plain_words():
    rooftop = suggest_templates(line="two friends talking on a rooftop", speakers=2)
    assert ids(rooftop) == ["stage-azotea", "voxel-talk"] and rooftop["unknown_words"] == ["friends"]
    stage, scene = (card["reason"] for card in rooftop["templates"])
    assert stage.startswith("two subjects, wide, moves on its own, uses: dialogue, talk, figure; place: azotea; cameras: two_shot")
    assert scene.startswith("two subjects, wide, moves: slide, uses: ") and "place: rooftop" in scene
    assert scene.endswith("the subject crosses the set")
    still = suggest_templates(line="dos personajes hablando")
    assert ids(still)[0] == "speech-dialogue" and ", still, " in still["templates"][0]["reason"]
    partial = suggest_templates(line="tense dialogue in a church")
    assert partial["partial"] is True and partial["templates"][0]["reason"].endswith("partial match")


def test_limit_and_bad_inputs(tmp_path):
    assert len(suggest_templates(line="zoom")["templates"]) == 3
    assert len(suggest_templates(line="zoom", limit=8)["templates"]) == 8
    everything = suggest_templates()
    assert len(everything["templates"]) == 3 and everything["filters"] == {} and all(card["score"] == 0 for card in everything["templates"])
    nothing = suggest_templates(line="xyzzy")
    assert nothing["templates"] == [] and nothing["unknown_words"] == ["xyzzy"]
    for bad, code in ((dict(speakers=5), "invalid_speakers"), (dict(speakers="2"), "invalid_speakers"), (dict(beat="party"), "invalid_beat"),
                      (dict(limit=0), "invalid_limit"), (dict(limit=9), "invalid_limit"), (dict(kind="huge"), "invalid_kind"),
                      (dict(format="square"), "invalid_format")):
        with pytest.raises(World3DTemplateError) as refused:
            suggest_templates(**bad)
        assert refused.value.code == code
    workspace = tmp_path / "studio"
    workspace.mkdir()
    document = {"templateId": "two-shot", "width": 1280, "height": 720, "duration": 5, "slots": [
        {"id": "hero", "slot": "subject_1", "media": "image", "sourceUrl": "", "motion": {"to": [2, 0, 0]}}]}
    (workspace / "world3d-user-templates.json").write_text(json.dumps({"templates": [
        {"id": "user-walk", "title": "Mi paseo", "description": "una figura cruza", "document": document}]}), encoding="utf-8")
    mine = suggest_templates(line="mi paseo", workspace_dir=lambda name: str(tmp_path / name), workspace="studio")
    assert ids(mine)[0] == "user-walk" and mine["templates"][0]["reason"].startswith("one subject, unmeasured, moves on its own")


def test_suggest_is_a_read_only_tool_with_the_same_answer_over_http_and_mcp(tmp_path):
    tool = next(item for item in command_catalog() if item["name"] == OPERATION)
    assert tool["mutation"] is False and "reason" in tool["description"] and "never instantiates" in tool["description"]
    fields = tool["inputSchema"]["properties"]["input"]["properties"]
    assert set(fields) == {"workspace", "line", "speakers", "place", "mood", "beat", "format", "kind", "limit"}
    assert fields["speakers"] == {"type": "integer", "minimum": 0, "maximum": 4, "description": fields["speakers"]["description"]}
    assert fields["beat"]["enum"] == list(SUGGEST_BEATS) and fields["format"]["enum"] == list(FORMATS) and fields["kind"]["enum"] == list(KINDS)
    assert fields["limit"] == {"type": "integer", "minimum": 1, "maximum": 8}
    assert tool["inputSchema"]["properties"]["input"]["required"] == ["workspace"]
    assert "intent_id" not in tool["inputSchema"]["properties"]
    client = client_for(tmp_path)
    tools = client.post("/api/v1/mcp", headers={"Authorization": "Bearer test-token"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
    assert OPERATION in {item["name"] for item in tools}
    data = {"line": "dos amigos hablando en una azotea", "speakers": 2, "mood": "tenso", "limit": 2}
    http = call(client, data)
    mcp = call(client, data, mcp=True)
    assert http["operation"] == OPERATION and http["status"] == "completed"
    assert ids(http["result"]) == ids(mcp["result"]) == ["stage-azotea", "voxel-talk"]
    assert http["result"]["unknown_words"] == ["amigos", "tenso"] and http["result"]["filters"] == {"use": "dialogue", "subjects": 2}
    assert http["result"]["templates"][0]["reason"] == mcp["result"]["templates"][0]["reason"]
    assert http["result"]["templates"][0]["match"] == "full" and http["result"]["partial"] is False
    bad = client.post("/api/v1/world3d/templates/commands", json={"operation": OPERATION, "version": 1,
                      "input": {"workspace": "studio", "speakers": 7}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_speakers"
    assert not (tmp_path / "studio").exists()                               # nothing was instantiated or journaled
