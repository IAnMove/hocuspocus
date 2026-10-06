"""Simulated batch production: order, dependencies, failure, cancel, and resume."""
import copy
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.game_generators import REGISTRY
from services.game_generators.base import AttemptResult
from services.game_jobs import GameJobStore
from services.game_library import create_game, read_library, write_library
from services.game_list import EXAMPLE_LIST, commit_list, parse_lines
from services.game_produce import GameProduce, ProduceDeps, ProduceError, archive_raw_outputs, build_produce
from services.game_tools import GameToolError
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


def _only_job_id(tmp_path):
    jobs = GameJobStore(str(tmp_path)).list()
    assert len(jobs) == 1
    return jobs[0]["jobId"]


def _ok(_ctx=None):
    return AttemptResult(files={}, metrics={}, warnings=[], provenance={"steps": []})


class Blocking:
    """Holds the first asset until the test lets it go, so a job stays active."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def estimate(self, _game, _asset):
        return {"image": 1}

    def run(self, _ctx):
        self.entered.set()
        self.release.wait(5)
        return _ok()


class Scripted:
    """Runs ``action(ctx, calls)`` for each asset; ``action`` returns the result or raises."""

    def __init__(self, action):
        self.action = action
        self.calls = []

    def estimate(self, _game, _asset):
        return {"image": 1}

    def run(self, ctx):
        self.calls.append(ctx.asset["id"])
        return self.action(ctx, self.calls)


def _client(tmp_path, *, inline=True):
    service = build_produce(
        call=lambda _tool, _args: {"result": {}},
        app_url=lambda: "http://127.0.0.1:9",
        token=lambda: "",
        workspace_dir=lambda _name: str(tmp_path),
        lock=threading.RLock(),
        inline=inline,
        loopback=lambda _tool, _args: {},
    )
    app = FastAPI()
    app.include_router(create_game_produce_router(
        service, call=service.deps.call, bind_loop=lambda _loop: None, read_game=service.deps.read_game,
    ))
    return service, TestClient(app)


def _finish(service, blocking):
    blocking.release.set()
    for thread in list(service._threads.values()):
        if thread is not threading.current_thread():
            thread.join(timeout=5)


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
    generator = Generator(calls, cancel=("first", lambda: holder["service"].cancel("lab", _only_job_id(tmp_path))))
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


def test_resume_requeues_steps_lost_when_the_server_shut_down(tmp_path, monkeypatch):
    calls = []

    class Quiet:
        def estimate(self, _game, _asset):
            return {"image": 1}

        def run(self, ctx):
            calls.append(ctx.asset["id"])
            return AttemptResult(files={}, metrics={"attemptIds": [ctx.attempt_id]}, warnings=[], provenance={"steps": []})

    store = Store([_asset("first", "item", "review"), _asset("second", "item"), _asset("third", "item")])
    service = _service(tmp_path, store, Quiet(), monkeypatch)
    service._store("lab").save({
        "jobId": "game-produce-abcd1234",
        "workspace": "lab",
        "gameId": "bosque",
        "status": "completed",
        "message": "Completed with failed assets",
        "createdAt": 1,
        "steps": [
            {"assetId": "first", "kind": "item", "status": "done", "attemptId": "aaa", "error": None},
            {"assetId": "second", "kind": "item", "status": "failed", "attemptId": "bbb", "error": "CancelledError: "},
            {"assetId": "third", "kind": "item", "status": "failed", "attemptId": "ccc", "error": "RuntimeError: Executor shutdown has been called"},
            {"assetId": "bad", "kind": "item", "status": "failed", "attemptId": "ddd", "error": "GameToolError: missing_generator"},
        ],
    })
    finished = service.resume("lab", "game-produce-abcd1234")
    assert calls == ["second", "third"]
    assert [step["status"] for step in finished["steps"]] == ["done", "done", "done", "failed"]
    assert finished["steps"][0]["attemptId"] == "aaa"
    assert finished["steps"][1]["attemptId"] == "bbb"


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


def test_each_candidate_keeps_its_own_files_and_metrics(tmp_path, monkeypatch):
    def pair(ctx, _calls):
        ids = [f"{ctx.attempt_id}-a1", f"{ctx.attempt_id}-a2"]
        candidates = [
            {"id": ids[0], "files": {"image": "a1.png"}, "metrics": {"score": 1}},
            {"id": ids[1], "files": {"image": "a2.png"}, "metrics": {"score": 2}},
        ]
        metrics = {"attemptIds": ids, "candidates": candidates, "score": 1}
        return AttemptResult(files=candidates[0]["files"], metrics=metrics, warnings=[], provenance={"steps": []})

    store = Store([_asset("moneda", "item")])
    service = _service(tmp_path, store, Scripted(pair), monkeypatch)
    job = service.start("lab", "bosque", candidates=2)
    attempt = job["steps"][0]["attemptId"]
    stored = store.game["assets"][0]["attempts"]
    assert [(item["id"], item["files"], item["metrics"]) for item in stored] == [
        (f"{attempt}-a1", {"image": "a1.png"}, {"score": 1}),
        (f"{attempt}-a2", {"image": "a2.png"}, {"score": 2}),
    ]
    assert {item["status"] for item in stored} == {"ok"}


def test_resume_refuses_while_another_job_for_the_game_runs(tmp_path, monkeypatch):
    store = Store([_asset("first", "item"), _asset("second", "item")])
    blocking = Blocking()
    service = _service(tmp_path, store, blocking, monkeypatch, inline=False)
    service._store("lab").save({
        "jobId": "game-produce-old00001", "workspace": "lab", "gameId": "bosque", "status": "interrupted", "createdAt": 1,
        "steps": [{"assetId": "second", "kind": "item", "status": "queued", "attemptId": "old"}],
    })
    service.start("lab", "bosque")
    assert blocking.entered.wait(5)
    try:
        with pytest.raises(ProduceError) as raised:
            service.resume("lab", "game-produce-old00001")
        assert (raised.value.code, raised.value.status) == ("already_running", 409)
        assert service.status("lab", "game-produce-old00001")["status"] == "interrupted"
    finally:
        _finish(service, blocking)


def test_resume_skips_an_asset_a_newer_batch_already_finished(tmp_path, monkeypatch):
    calls = []
    store = Store([_asset("first", "item", "review")])
    service = _service(tmp_path, store, Generator(calls), monkeypatch)
    service._store("lab").save({
        "jobId": "game-produce-old00002", "workspace": "lab", "gameId": "bosque", "status": "interrupted", "createdAt": 1,
        "steps": [{"assetId": "first", "kind": "item", "status": "queued", "attemptId": "old"}],
    })
    finished = service.resume("lab", "game-produce-old00002")
    assert calls == []
    assert (finished["steps"][0]["status"], finished["steps"][0]["reason"]) == ("skipped", "not_open")
    assert store.game["assets"][0]["status"] == "review"
    assert "attempts" not in store.game["assets"][0]


def test_cancel_inside_the_tool_wait_keeps_the_step_for_resume(tmp_path, monkeypatch):
    holder: dict = {}

    def cancel_once(ctx, calls):
        if len(calls) == 1:
            holder["service"].cancel("lab", _only_job_id(tmp_path))
            if ctx.cancelled():  # what game_tools._wait_job does on its next poll
                raise GameToolError("cancelled", "the attempt was cancelled")
        return _ok()

    store = Store([_asset("only", "item")])
    generator = Scripted(cancel_once)
    service = _service(tmp_path, store, generator, monkeypatch)
    holder["service"] = service
    job = service.start("lab", "bosque")
    assert job["status"] == "cancelled"
    assert job["message"] == "Cancelled; resume to continue"
    assert job["steps"][0]["status"] == "queued"
    assert "attempts" not in store.game["assets"][0]
    assert store.game["assets"][0]["status"] == "pending"
    finished = service.resume("lab", job["jobId"])
    assert finished["status"] == "completed"
    assert finished["steps"][0]["status"] == "done"
    assert generator.calls == ["only", "only"]
    assert [item["id"] for item in store.game["assets"][0]["attempts"]] == [job["steps"][0]["attemptId"]]


def test_a_failed_library_write_fails_the_step_and_the_batch_goes_on(tmp_path, monkeypatch):
    store = Store([_asset("gone", "item"), _asset("tail", "item")])

    def vanish(ctx, _calls):
        if ctx.asset["id"] == "gone":  # someone deletes the asset while it generates
            store.game["assets"] = [item for item in store.game["assets"] if item["id"] != "gone"]
        return _ok()

    service = _service(tmp_path, store, Scripted(vanish), monkeypatch)
    job = service.start("lab", "bosque")
    assert [step["status"] for step in job["steps"]] == ["failed", "done"]
    assert job["steps"][0]["error"].startswith("AssertionError: gone")
    assert (job["status"], job["message"]) == ("completed", "Completed with failed assets")


def test_a_worker_crash_never_leaves_the_job_running(tmp_path, monkeypatch):
    store = Store([_asset("first", "item"), _asset("second", "item")])
    service = _service(tmp_path, store, Generator([]), monkeypatch)

    def disk_full(_job, step):
        step["status"] = "running"
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(service, "_one", disk_full)
    job = service.start("lab", "bosque")
    assert job["status"] == "failed"
    assert "No space left on device" in job["error"]
    assert [step["status"] for step in job["steps"]] == ["failed", "queued"]
    assert service.status("lab", job["jobId"])["status"] == "failed"

    def shutdown(_ctx, _calls):
        raise RuntimeError("Executor shutdown has been called")

    shut = Store([_asset("first", "item")])
    service = _service(tmp_path / "shut", shut, Scripted(shutdown), monkeypatch)
    job = service.start("lab", "bosque")
    assert job["status"] == "interrupted"
    assert job["steps"][0]["status"] == "queued"
    assert shut.game["assets"][0]["status"] == "pending"


def test_two_starts_at_once_admit_one_job(tmp_path, monkeypatch):
    store = Store([_asset("first", "item")])
    blocking = Blocking()
    service = _service(tmp_path, store, blocking, monkeypatch, inline=False)
    barrier = threading.Barrier(2, timeout=0.5)
    listed = service.jobs

    def jobs(workspace):
        try:  # without the admit lock both callers meet here and both see an idle game
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return listed(workspace)

    service.jobs = jobs
    outcomes = []

    def start():
        try:
            outcomes.append(service.start("lab", "bosque")["status"])
        except ProduceError as error:
            outcomes.append(error.code)

    callers = [threading.Thread(target=start) for _ in range(2)]
    try:
        for caller in callers:
            caller.start()
        for caller in callers:
            caller.join(timeout=5)
        assert outcomes.count("already_running") == 1
        assert len(GameJobStore(str(tmp_path)).list()) == 1
    finally:
        _finish(service, blocking)


def test_resume_requeues_a_step_once_its_dependency_is_approved(tmp_path, monkeypatch):
    calls = []
    store = Store([_asset("heroe", "character", "review"), _asset("heroe-idle", "animation", depends=["heroe"])])
    service = _service(tmp_path, store, Generator(calls), monkeypatch)
    job = service.start("lab", "bosque", asset_ids=["heroe-idle"])
    assert (job["steps"][0]["status"], job["steps"][0]["reason"]) == ("skipped", "waiting_dependency")
    still = service.resume("lab", job["jobId"])
    assert still["steps"][0]["status"] == "skipped"
    assert calls == []
    store.game["assets"][0]["status"] = "approved"
    finished = service.resume("lab", job["jobId"])
    assert finished["steps"][0]["status"] == "done"
    assert calls == ["heroe-idle"]


def test_router_blank_job_id_is_404_and_a_busy_style_sheet_writes_nothing(tmp_path, monkeypatch):
    library, _game = create_game({}, {"id": "bosque", "title": "Bosque"}, now=NOW)
    write_library(tmp_path, library, now=NOW)
    commit_list(str(tmp_path), "bosque", parse_lines("objeto moneda: oro"), False, now=NOW)
    blocking = Blocking()
    monkeypatch.setitem(REGISTRY, "item", blocking)
    service, client = _client(tmp_path, inline=False)
    assert client.get("/api/v1/games/produce/jobs/%20%20", params={"workspace": "lab"}).status_code == 404
    assert client.post("/api/v1/games/produce/jobs/%20/cancel", json={"workspace": "lab"}).status_code == 404
    assert client.post("/api/v1/games/produce/jobs/%20/resume", json={"workspace": "lab"}).status_code == 404
    service.start("lab", "bosque")
    assert blocking.entered.wait(5)
    try:
        response = client.post("/api/v1/games/bosque/style/sheet", json={"workspace": "lab"})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "already_running"
        assert [asset["id"] for asset in read_library(tmp_path)["games"][0]["assets"]] == ["moneda"]
    finally:
        _finish(service, blocking)


def test_from_list_check_reports_a_bad_json_spec_instead_of_failing(tmp_path):
    library, _game = create_game({}, {"id": "bosque", "title": "Bosque"}, now=NOW)
    write_library(tmp_path, library, now=NOW)
    _service_unused, client = _client(tmp_path)
    response = client.post("/api/v1/games/bosque/assets/from-list", json={"workspace": "lab", "check": True, "items": [
        {"kind": "item", "id": "a", "spec": "x"},
        {"kind": "item", "id": "b", "spec": [1]},
        {"kind": "item", "id": "c", "spec": {}, "candidates": "many"},
    ]})
    assert response.status_code == 200
    assert [(item["line"], item["code"]) for item in response.json()["problems"]] == [
        (1, "invalid_spec"), (2, "invalid_spec"), (3, "invalid_spec"),
    ]
