"""The browser and agents start, follow, cancel and resume the server episode render over HTTP."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.series_native_render import create_series_native_render_router
from services.series_native_render import NativeRenderError


class Fake:
    def __init__(self):
        self.calls = []

    def start(self, workspace, series_id, episode_id, *, shot_ids=None, approve=False, language=None, changed=False):
        self.calls.append(("start", workspace, series_id, episode_id, shot_ids, approve) + (("changed",) if changed else ()))
        return {"jobId": "native-1", "status": "queued", "items": [{"shotId": "s01", "lines": {"b": {"cues": [1, 2], "filename": "x.wav"}}}]}

    def status(self, workspace, job_id):
        raise NativeRenderError("not_found", "Render job not found", 404)

    def jobs(self, workspace):
        return []


def test_routes_bind_the_loop_and_hide_cue_arrays():
    service, loops = Fake(), []
    app = FastAPI()
    app.include_router(create_series_native_render_router(service, loops.append))
    client = TestClient(app)
    started = client.post("/api/v1/series/uv/episodes/ep1/native-render", json={"workspace": "cast", "approve": True})
    assert started.status_code == 200, started.text
    assert started.json()["items"][0]["lines"]["b"] == {"filename": "x.wav", "cueCount": 2}
    assert service.calls == [("start", "cast", "uv", "ep1", None, True)] and loops
    client.post("/api/v1/series/uv/episodes/ep1/native-render", json={"workspace": "cast", "changed": True})
    assert service.calls[-1] == ("start", "cast", "uv", "ep1", None, False, "changed"), "only the shots that need a render"
    missing = client.get("/api/v1/series/native-render/jobs/nope", params={"workspace": "cast"})
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "not_found"
    assert client.get("/api/v1/series/native-render/recovery", params={"workspace": "cast"}).json() == {"jobs": []}
