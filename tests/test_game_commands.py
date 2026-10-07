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


def routed(tmp_path):
    """Handlers wired to the real game routers on a temp workspace; returns (handlers, assets())."""
    import threading
    import urllib.error
    import urllib.parse

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.game_library import create_game_library_router
    from routers.game_produce import create_game_produce_router
    from services.game_library import read_library
    from services.game_produce import build_produce

    lock = threading.RLock()
    service = build_produce(call=lambda _tool, _args: {"result": {}}, app_url=lambda: "", token=lambda: "",
                            workspace_dir=lambda _name: str(tmp_path), lock=lock, inline=True, loopback=lambda _tool, _args: {})
    app = FastAPI()
    app.include_router(create_game_produce_router(service, call=service.deps.call, bind_loop=lambda _loop: None,
                                                  read_game=service.deps.read_game))
    app.include_router(create_game_library_router(workspace_dir=lambda _name: str(tmp_path), lock=lock))
    client = TestClient(app)

    def opener(request, timeout):
        parts = urllib.parse.urlsplit(request.full_url)
        reply = client.request(request.get_method(), parts.path + (f"?{parts.query}" if parts.query else ""),
                               content=request.data, headers=dict(request.header_items()))
        if reply.status_code >= 400:
            raise urllib.error.HTTPError(request.full_url, reply.status_code, "error", {}, io.BytesIO(reply.content))
        return Response(reply.content)

    handlers = command_handlers(lambda: "http://127.0.0.1:9", lambda name: str(tmp_path), lambda: str(tmp_path), opener=opener)
    call(handlers, "game.create", {"workspace": "lab", "game": {"id": "bosque", "title": "Bosque"}})
    call(handlers, "game.assets.from_list", {"workspace": "lab", "game_id": "bosque", "text": "objeto moneda: oro\nobjeto llave: llave"})
    return handlers, lambda: {asset["id"]: asset for asset in read_library(str(tmp_path))["games"][0]["assets"]}


def failure(handlers, name, data, **envelope):
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers[name]({"version": 1, "input": data, **envelope}))
    return caught.value.status_code, caught.value.detail


def test_catalog_and_handlers_cover_the_same_tools():
    from services.game_commands import _RUNNERS

    handlers, _calls = harness([])
    assert set(_RUNNERS) == set(OPERATIONS) == set(handlers)


def test_a_list_in_the_wrong_field_is_refused_instead_of_wiping_the_game(tmp_path):
    handlers, assets = routed(tmp_path)
    base = {"workspace": "lab", "game_id": "bosque", "replace": True}
    status, detail = failure(handlers, "game.assets.from_list", {**base, "format": "json", "text": '[{"kind": "item", "id": "gema"}]'})
    assert (status, detail["code"]) == (422, "invalid_list")
    status, detail = failure(handlers, "game.assets.from_list", base)
    assert (status, detail["code"]) == (422, "invalid_list")
    status, _detail = failure(handlers, "game.assets.from_list", {**base, "text": "objeto gema: gema", "items": [{"kind": "item", "id": "gema"}]})
    assert status == 422
    assert set(assets()) == {"moneda", "llave"}
    written = call(handlers, "game.assets.from_list", {"workspace": "lab", "game_id": "bosque",
                                                       "items": [{"kind": "item", "id": "gema", "spec": {"seed": 7}}]})
    assert written["result"]["problems"] == []
    assert assets()["gema"]["spec"]["seed"] == 7


def test_string_booleans_are_refused_before_the_route(tmp_path):
    handlers, assets = routed(tmp_path)
    status, detail = failure(handlers, "game.asset.lock", {"workspace": "lab", "game_id": "bosque", "asset_id": "moneda", "locked": "false"})
    assert status == 422
    assert detail["problems"][0]["field"] == "input/locked"
    assert assets()["moneda"]["locked"] is False
    status, _detail = failure(handlers, "game.assets.from_list", {"workspace": "lab", "game_id": "bosque", "text": "objeto gema: gema", "replace": "false"})
    assert status == 422
    assert set(assets()) == {"moneda", "llave"}


def test_schema_refuses_static_route_ids_unknown_kinds_and_envelope_extras():
    handlers, calls = harness([])
    status, detail = failure(handlers, "game.get", {"workspace": "lab", "game_id": "presets"})
    assert (status, detail["problems"][0]["field"]) == (422, "input/game_id")
    status, detail = failure(handlers, "game.produce", {"workspace": "lab", "game_id": "bosque", "kinds": ["objeto"]})
    assert (status, detail["problems"][0]["field"]) == (422, "input/kinds/0")
    status, _detail = failure(handlers, "game.produce.status", {"workspace": "lab", "job_id": ".."})
    assert status == 422
    status, _detail = failure(handlers, "game.list", {"workspace": "lab"}, intent_id="retry-1")
    assert status == 422
    assert calls == []


def test_errors_keep_the_route_code_problems_and_retry_hint(tmp_path):
    import urllib.error

    handlers, _assets = routed(tmp_path)
    status, detail = failure(handlers, "game.create", {"workspace": "lab", "game": {"id": "bosque", "title": "Otro"}})
    assert (status, detail["code"], detail["retryable"]) == (409, "game_exists", False)
    status, detail = failure(handlers, "game.update", {"workspace": "lab", "game_id": "bosque", "patch": {"title": "B"}, "base_revision": 0})
    assert (status, detail["code"], detail["retryable"]) == (409, "revision_conflict", True)
    fields = [{"loc": ["body", "patch"], "msg": "Input should be a valid dictionary", "type": "dict_type"}]
    rejected = urllib.error.HTTPError("http://x", 422, "error", {}, io.BytesIO(json.dumps({"detail": fields}).encode()))
    handlers, _calls = harness([rejected, urllib.error.URLError(ConnectionRefusedError(111, "refused"))])
    status, detail = failure(handlers, "game.list", {"workspace": "lab"})
    assert status == 422
    assert detail["problems"] == [{"field": "body/patch", "message": "Input should be a valid dictionary"}]
    status, detail = failure(handlers, "game.list", {"workspace": "lab"})
    assert (status, detail["code"], detail["retryable"]) == (502, "server_unavailable", True)
