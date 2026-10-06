"""Simulated batch production: order, dependencies, failure, cancel, and resume."""
import copy
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.game_generators import REGISTRY
from services.game_generators.base import AttemptResult
from services.game_jobs import GameJobStore
from services.game_library import create_game, read_library, write_library
from services.game_list import EXAMPLE_LIST
from services.game_produce import GameProduce, ProduceDeps, archive_raw_outputs, build_produce
from routers.game_produce import create_game_produce_router

NOW = "2026-10-06T12:00:00Z"


class Store:
    def __init__(self, assets):
        self.game = {"id": "bosque", "assets": assets}

    def read_game(self, _workspace, _game_id):
        return copy.deepcopy(self.game)

    def write_attempt(self, _workspace, _game_id, asset_id, attempt, status):
        for asset in self.game["assets"]:
            if asset["id"] == asset_id:
                if attempt:
                    asset.setdefault("attempts", []).append(attempt)
                asset["status"] = status
                return
        raise AssertionError(asset_id)


class Generator:
    def __init__(self, calls, fail=(), cancel=None):
        self.calls = calls
        self.fail = set(fail)
        self.cancel = cancel

    def estimate(self, _game, _asset):
        return {"image": 1}

    def run(self, ctx):
        self.calls.append(ctx.asset["id"])
        if self.cancel and ctx.asset["id"] == self.cancel[0]:
            self.cancel[1]()
        if ctx.asset["id"] in self.fail:
            raise RuntimeError("boom")
        if ctx.asset["id"] == "second" and self.calls.count("second") == 1:
            raise SystemExit
        return AttemptResult(files={}, metrics={"attemptIds": [ctx.attempt_id]}, warnings=[], provenance={"steps": []})


def _asset(asset_id, kind, status="pending", depends=None, locked=False):
    return {
        "id": asset_id, "kind": kind, "status": status, "locked": locked,
        "dependsOn": list(depends or []), "spec": {}, "candidates": 1,
    }


def _service(tmp_path, store, generator, monkeypatch, *, inline=True):
    deps = ProduceDeps(
        call=lambda _tool, _args: {"result": {}},
        loopback=lambda _tool, _args: {},
        workspace_dir=lambda _name: str(tmp_path),
        read_game=store.read_game,
        write_attempt=store.write_attempt,
        inline=inline,
    )
    for kind in ("character", "item", "tile", "tileset", "animation", "sfx", "background"):
        monkeypatch.setitem(REGISTRY, kind, generator)
    return GameProduce(deps)


def _ids(job):
    return [step["assetId"] for step in job["steps"]]


def test_order_dependency_failure_and_rerender(tmp_path, monkeypatch):
    calls = []
    store = Store([
        _asset("salto", "sfx"),
        _asset("heroe-idle", "animation", depends=["heroe"]),
        _asset("hierba", "tile"),
        _asset("heroe", "character"),
    ])
    generator = Generator(calls, fail=())
    service = _service(tmp_path, store, generator, monkeypatch)
    job = service.start("lab", "bosque")
    assert _ids(job) == ["heroe", "hierba", "heroe-idle", "salto"]
    assert [step["status"] for step in job["steps"]] == ["done", "done", "skipped", "done"]
    assert job["steps"][2]["reason"] == "waiting_dependency"
    assert calls == ["heroe", "hierba", "salto"]
    assert {asset["id"]: asset["status"] for asset in store.game["assets"]}["heroe"] == "review"

    calls.clear()
    failing = Store([_asset("good", "item"), _asset("bad", "item"), _asset("tail", "item")])
    service = _service(tmp_path, failing, Generator(calls, fail={"bad"}), monkeypatch)
    job = service.start("lab", "bosque")
    assert calls == ["good", "bad", "tail"]
    assert [step["status"] for step in job["steps"]] == ["done", "failed", "done"]
    assert job["status"] == "completed"
    assert {asset["id"]: asset["status"] for asset in failing.game["assets"]} == {
        "good": "review", "bad": "pending", "tail": "review",
    }

    calls.clear()
    mixed = Store([
        _asset("open", "item", "pending"),
        _asset("old", "item", "stale"),
        _asset("held", "item", "stale", locked=True),
        _asset("done", "item", "approved"),
    ])
    service = _service(tmp_path, mixed, Generator(calls), monkeypatch)
    assert _ids(service.start("lab", "bosque")) == ["open"]
    calls.clear()
    again = Store([
        _asset("open", "item", "pending"),
        _asset("old", "item", "stale"),
        _asset("held", "item", "stale", locked=True),
        _asset("done", "item", "approved"),
    ])
    service = _service(tmp_path, again, Generator(calls), monkeypatch)
    assert _ids(service.start("lab", "bosque", rerender=True)) == ["open", "old"]
    assert "held" not in calls and "done" not in calls


def test_cancel_between_steps(tmp_path, monkeypatch):
    calls = []
    store = Store([_asset("first", "item"), _asset("second", "item")])
    holder: dict = {}
    generator = Generator(calls, cancel=("first", lambda: holder["service"].cancel("lab", holder["service"]._active_job)))
    service = _service(tmp_path, store, generator, monkeypatch)
    holder["service"] = service
    job = service.start("lab", "bosque")
    assert calls == ["first"]
    assert job["status"] == "cancelled"
    assert [step["status"] for step in job["steps"]] == ["done", "queued"]


def test_resume_after_the_worker_dies_does_not_repeat_finished_work(tmp_path, monkeypatch):
    calls = []
    store = Store([_asset("first", "item"), _asset("second", "item")])
    service = _service(tmp_path, store, Generator(calls), monkeypatch, inline=False)
    job = service.start("lab", "bosque")
    service._threads[job["jobId"]].join(timeout=5)
    interrupted = service.status("lab", job["jobId"])
    assert interrupted["status"] == "interrupted"
    assert calls.count("first") == 1
    service.resume("lab", job["jobId"])
    service._threads[job["jobId"]].join(timeout=5)
    finished = service.status("lab", job["jobId"])
    assert finished["status"] == "completed"
    assert calls.count("first") == 1
    assert calls.count("second") == 2
    assert store.game["assets"][0]["attempts"][0]["id"] == finished["steps"][0]["attemptId"]


def test_raw_outputs_move_after_success_without_taking_a_longer_id(tmp_path):
    (tmp_path / "hero-still.png").write_bytes(b"a")
    (tmp_path / "hero-idle-still.png").write_bytes(b"b")
    game = {"id": "bosque", "assets": [_asset("hero", "item"), _asset("hero-idle", "item", "approved")]}
    moved = archive_raw_outputs(str(tmp_path), game, "hero", "attempt")
    assert moved == ["hero-still.png"]
    assert (tmp_path / "game" / "bosque" / "hero" / "attempt" / "raw" / "hero-still.png").is_file()
    assert (tmp_path / "hero-idle-still.png").is_file()


def test_job_store_round_trip(tmp_path):
    store = GameJobStore(str(tmp_path))
    store.save({"jobId": "game-produce-abcd1234", "status": "queued", "createdAt": 1})
    assert store.load("game-produce-abcd1234")["kind"] == "produce"
    assert store.recoverable()
    assert store.discard("game-produce-abcd1234") is True
    assert store.load("game-produce-abcd1234") is None


def test_from_list_check_returns_an_estimate_without_writing(tmp_path):
    library, _game = create_game({}, {"id": "bosque", "title": "Bosque"}, now=NOW)
    write_library(tmp_path, library, now=NOW)
    service = build_produce(
        call=lambda _tool, _args: {"result": {}},
        app_url=lambda: "http://127.0.0.1:9",
        token=lambda: "",
        workspace_dir=lambda _name: str(tmp_path),
        lock=threading.RLock(),
        inline=True,
        loopback=lambda _tool, _args: {},
    )
    app = FastAPI()
    app.include_router(create_game_produce_router(
        service, call=service.deps.call, bind_loop=lambda _loop: None, read_game=service.deps.read_game,
    ))
    client = TestClient(app)
    checked = client.post("/api/v1/games/bosque/assets/from-list", json={
        "workspace": "lab", "text": EXAMPLE_LIST, "check": True,
    })
    assert checked.status_code == 200
    body = checked.json()
    assert len(body["items"]) == 18
    assert body["problems"] == []
    assert body["estimate"]["source"] == "trial"
    assert body["estimate"]["minutes"] > 0
    assert "assets" not in body
    assert read_library(tmp_path)["games"][0]["assets"] == []
    rejected = client.post("/api/v1/games/bosque/assets/from-list", json={
        "workspace": "lab", "text": "nope cosa: nada", "check": False,
    })
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["problems"][0]["code"] == "unknown_kind"
    assert read_library(tmp_path)["games"][0]["assets"] == []
    written = client.post("/api/v1/games/bosque/assets/from-list", json={
        "workspace": "lab", "text": "objeto moneda: oro", "check": False,
    })
    assert written.status_code == 200
    assert [asset["id"] for asset in read_library(tmp_path)["games"][0]["assets"]] == ["moneda"]


def test_style_sheet_produces_only_the_four_samples(tmp_path, monkeypatch):
    library, _game = create_game({}, {"id": "bosque", "title": "Bosque"}, now=NOW)
    write_library(tmp_path, library, now=NOW)
    calls = []
    monkeypatch.setitem(REGISTRY, "character", Generator(calls))
    monkeypatch.setitem(REGISTRY, "item", Generator(calls))
    monkeypatch.setitem(REGISTRY, "tile", Generator(calls))
    monkeypatch.setitem(REGISTRY, "background", Generator(calls))
    service = build_produce(
        call=lambda _tool, _args: {"result": {}},
        app_url=lambda: "http://127.0.0.1:9",
        token=lambda: "",
        workspace_dir=lambda _name: str(tmp_path),
        lock=threading.RLock(),
        inline=True,
        loopback=lambda _tool, _args: {},
    )
    app = FastAPI()
    app.include_router(create_game_produce_router(
        service, call=service.deps.call, bind_loop=lambda _loop: None, read_game=service.deps.read_game,
    ))
    client = TestClient(app)
    response = client.post("/api/v1/games/bosque/style/sheet", json={"workspace": "lab"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert _ids(body) == [
        "style-sample-character", "style-sample-item", "style-sample-tile", "style-sample-background",
    ]
    assert calls == _ids(body)
    stored = {asset["id"]: asset["status"] for asset in read_library(tmp_path)["games"][0]["assets"]}
    assert set(stored) == set(calls)
    assert set(stored.values()) == {"review"}
