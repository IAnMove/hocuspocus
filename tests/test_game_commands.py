"""Game MCP tools call the existing REST routes and reject unknown fields."""
import asyncio
import io
import json

import pytest
from fastapi import HTTPException

from services.game_commands import OPERATIONS, command_catalog, command_handlers


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def harness(replies):
    calls = []

    def opener(request, timeout):
        body = json.loads(request.data) if request.data else None
        calls.append((request.get_method(), request.full_url, body))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Response(json.dumps(reply).encode())

    handlers = command_handlers(lambda: "http://127.0.0.1:9", lambda name: "/tmp/unused", lambda: "/tmp/uploads", opener=opener)
    return handlers, calls


def call(handlers, name, data):
    return asyncio.run(handlers[name]({"version": 1, "input": data}))


def test_every_operation_rejects_unknown_fields_and_states_mutation():
    catalog = command_catalog()
    assert {item["name"] for item in catalog} == set(OPERATIONS)
    for operation in catalog:
        assert type(operation["mutation"]) is bool
        schema = operation["inputSchema"]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["input"]["additionalProperties"] is False
        assert operation["description"].count(".") <= 3


def test_handlers_hit_the_game_routes():
    game = {"id": "bosque", "title": "Bosque", "revision": 2, "style": {}, "assets": []}
    handlers, calls = harness([game, {"problems": [], "items": [], "estimate": {"minutes": 1}}, {"file": "game-exports/bosque-r2.zip"}])
    guide = call(handlers, "game.guide", {"workspace": "lab", "game_id": "bosque"})
    assert guide["result"]["bible"]["id"] == "bosque"
    assert "game.guide" in guide["result"]["guide"]
    listed = call(handlers, "game.assets.from_list", {"workspace": "lab", "game_id": "bosque", "text": "heroe: personaje", "check": True})
    assert listed["result"]["assets"] == []
    exported = call(handlers, "game.export", {"workspace": "lab", "game_id": "bosque"})
    assert exported["result"]["file"].endswith(".zip")
    assert calls[0][:2] == ("GET", "http://127.0.0.1:9/api/v1/games/bosque?workspace=lab")
    assert calls[1][0] == "POST"
    assert calls[1][1] == "http://127.0.0.1:9/api/v1/games/bosque/assets/from-list"
    assert calls[1][2]["check"] is True
    assert calls[1][2]["text"] == "heroe: personaje"
    assert "items" not in calls[1][2]
    assert calls[2][:2] == ("POST", "http://127.0.0.1:9/api/v1/games/bosque/export")
    assert calls[2][2] == {"workspace": "lab"}


def test_reject_posts_the_note_and_unknown_fields_are_422():
    handlers, calls = harness([{"id": "llave", "status": "rejected"}])
    result = call(handlers, "game.asset.reject", {
        "workspace": "lab", "game_id": "bosque", "asset_id": "llave", "attempt_id": "a1", "note": "corte arriba",
    })
    assert result["result"]["status"] == "rejected"
    assert calls[0][:2] == ("POST", "http://127.0.0.1:9/api/v1/games/bosque/assets/llave/reject")
    assert calls[0][2]["note"] == "corte arriba"
    with pytest.raises(HTTPException) as caught:
        call(handlers, "game.get", {"workspace": "lab", "game_id": "bosque", "extra": 1})
    assert caught.value.status_code == 422


def test_produce_status_reads_the_job_once_when_it_is_finished():
    handlers, calls = harness([{"id": "job-1", "status": "completed"}])
    result = call(handlers, "game.produce.status", {"workspace": "lab", "job_id": "job-1", "wait_s": 30})
    assert result["result"]["status"] == "completed"
    assert calls == [("GET", "http://127.0.0.1:9/api/v1/games/produce/jobs/job-1?workspace=lab", None)]
