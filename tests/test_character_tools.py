"""The browser keys a pose and checks a voice through the same handlers as MCP."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.character_tools import create_character_tools_router


def test_routes_wrap_the_body_in_the_command_envelope():
    seen = []

    async def handler(envelope):
        seen.append(envelope)
        return {"version": 1, "status": "completed", "result": {"ok": True}}

    app = FastAPI()
    app.include_router(create_character_tools_router(studio_key=handler, speech_qa=handler))
    client = TestClient(app)
    keyed = client.post("/api/v1/studio/key", json={"workspace": "cast", "source": "a.png", "mode": "magenta", "intent_id": "key-a"})
    assert keyed.status_code == 200 and keyed.json()["result"] == {"ok": True}
    checked = client.post("/api/v1/qa/speech", json={"workspace": "cast", "file": "take.wav", "text": "Hola."})
    assert checked.status_code == 200
    assert seen == [
        {"version": 1, "input": {"workspace": "cast", "source": "a.png", "mode": "magenta"}, "intent_id": "key-a"},
        {"version": 1, "input": {"workspace": "cast", "file": "take.wav", "text": "Hola."}},
    ]
    assert client.post("/api/v1/qa/speech", json=["not", "an", "object"]).status_code == 422
