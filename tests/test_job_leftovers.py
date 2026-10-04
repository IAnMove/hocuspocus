"""Leftover generation queue over MCP, without a GPU and without a second queue."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routers.image_generation_commands import image_command_catalog, image_command_handlers
from routers.wangp_mcp import create_wangp_mcp_router
from services.durable_generation_queue import DurableGenerationQueue
from services.image_generation_commands import ImageGenerationCommands
from services.job_leftovers import (
    JobLeftovers,
    command_catalog,
    command_handlers,
    content_fingerprint,
)


def _payload(prompt: str) -> dict:
    return {
        "generation_mode": "image",
        "model_type": "test-model",
        "prompt": prompt,
        "seed": 7,
    }


def _empty_commands(service: JobLeftovers) -> ImageGenerationCommands:
    class EmptyRegistry:
        def command_admission(self, _intent_id):
            return None

        def get(self, _task_id):
            return None

    commands = ImageGenerationCommands(
        registry=lambda _workspace: EmptyRegistry(),
        prepare=lambda _request: None,
        preflight=lambda _params: None,
        make_job=lambda *_args, **_kwargs: {},
        task_fields=lambda _job: {},
        dispatch=lambda _job: None,
        persist_recovery=lambda _job: None,
        active_job_ids=lambda: [],
    )
    commands.leftover_receipt_lookup = lambda workspace, intent_id: service.receipt_for(workspace, intent_id)
    return commands


def _status_handler(service: JobLeftovers):
    def status(job_id: str):
        live = service.jobs.get(job_id)
        if isinstance(live, dict):
            return {"job_id": job_id, "status": live.get("status"), "output_files": []}
        found = service.status_for(job_id)
        if found is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return found

    return status


def _generate_handler(service: JobLeftovers):
    async def generate(request):
        body = await request.json()
        workspace = body.pop("workspace", None) or "lab"
        provenance = body.pop("provenance", None)
        intent_id = ""
        if isinstance(provenance, dict) and isinstance(provenance.get("command"), dict):
            command_id = provenance["command"].get("command_id")
            if isinstance(command_id, str):
                intent_id = command_id
        if not intent_id:
            raise HTTPException(status_code=422, detail="intent_id is required")
        return service.enqueue(
            body, workspace=str(workspace), intent_id=intent_id,
            provenance=provenance if isinstance(provenance, dict) else None,
        )

    return generate


def _client(service: JobLeftovers, journal) -> TestClient:
    receipt = [item for item in image_command_catalog() if item["name"] == "generation.receipt"]
    app = FastAPI()
    app.include_router(create_wangp_mcp_router(
        handlers={
            "status": _status_handler(service),
            "generate": _generate_handler(service),
            "generation.receipt": image_command_handlers(_empty_commands(service))["generation.receipt"],
            **command_handlers(service),
        },
        command_operations=[*receipt, *command_catalog()],
        journal_path=journal,
        token_getter=lambda: "test-token",
    ))
    return TestClient(app)


def _mcp(client: TestClient, name: str, arguments: dict, request_id: int) -> dict:
    response = client.post(
        "/api/v1/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={
            "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    parsed = json.loads(result["content"][0]["text"])
    parsed["_is_error"] = result["isError"]
    return parsed


def test_restarted_leftovers_resume_once_and_duplicate_submit_returns_the_same_id(tmp_path):
    path = tmp_path / "outputs" / ".maestro_generation_queue.json"
    calls: list[str] = []

    def start(job):
        calls.append(job["id"])
        job["status"] = "completed"
        job["message"] = "Done"
        DurableGenerationQueue(str(path)).remove(job["id"])

    first = JobLeftovers(queue=DurableGenerationQueue(str(path)), jobs={}, start=start)
    prompts = ("alpha coast", "beta harbor", "gamma ridge")
    intents = ("intent-alpha", "intent-beta", "intent-gamma")
    with _client(first, tmp_path / "journal-a.sqlite") as live:
        created = []
        for number, (intent, prompt) in enumerate(zip(intents, prompts), start=1):
            body = _mcp(live, "generate", {
                "request_id": intent,
                "params": {**_payload(prompt), "workspace": "lab"},
            }, number)
            assert body["_is_error"] is False
            assert body["intent_id"] == intent
            created.append(body)
        listed = live.post(
            "/api/v1/mcp",
            headers={"Authorization": "Bearer test-token"},
            json={"jsonrpc": "2.0", "id": 10, "method": "tools/list"},
        ).json()["result"]["tools"]
        names = {tool["name"] for tool in listed}
        assert {"jobs.leftovers", "jobs.resume", "jobs.discard", "generation.receipt", "status"} <= names

    stored = DurableGenerationQueue(str(path)).list()
    assert [record["id"] for record in stored] == [item["job_id"] for item in created]
    stored[0]["status"] = "running"
    DurableGenerationQueue(str(path)).upsert(stored[0])

    restarted = first.reloaded()
    assert restarted.jobs == {}
    assert restarted.queue.path == first.queue.path
    with _client(restarted, tmp_path / "journal-b.sqlite") as recovered:
        statuses = []
        for number, item in enumerate(created, start=20):
            status = _mcp(recovered, "status", {"job_id": item["job_id"]}, number)
            assert status["_is_error"] is False
            assert "not found" not in json.dumps(status).lower()
            assert status["status"] in {"leftover", "interrupted"}
            statuses.append(status["status"])
            receipt = _mcp(recovered, "generation.receipt", {
                "version": 1,
                "input": {"workspace": "lab", "intent_id": item["intent_id"]},
            }, number + 10)
            assert receipt["_is_error"] is False
            assert receipt["status"] == status["status"]
            assert receipt["task"]["status"] == status["status"]
            assert receipt["receipt"]["result"]["job_id"] == item["job_id"]
        assert statuses == ["interrupted", "leftover", "leftover"]

        leftovers = _mcp(recovered, "jobs.leftovers", {"version": 1}, 40)
        assert [job["job_id"] for job in leftovers["result"]["jobs"]] == [item["job_id"] for item in created]
        assert leftovers["result"]["jobs"][1]["intent_id"] == "intent-beta"
        # MCP generate stamps image_mode before admission. The fingerprint is that content.
        assert leftovers["result"]["jobs"][1]["fingerprint"] == content_fingerprint(
            {**_payload(prompts[1]), "image_mode": 1}, "lab",
        )

        duplicate = _mcp(recovered, "generate", {
            "request_id": "intent-beta-again",
            "params": {**_payload(prompts[1]), "workspace": "lab"},
        }, 41)
        assert duplicate["_is_error"] is False
        assert duplicate["code"] == "duplicate_leftover"
        assert duplicate["job_id"] == created[1]["job_id"]
        assert duplicate["intent_id"] == "intent-beta"
        assert [record["id"] for record in restarted.queue.list()] == [item["job_id"] for item in created]

        for number, item in enumerate(created, start=50):
            resumed = _mcp(recovered, "jobs.resume", {"version": 1, "intent_id": item["intent_id"]}, number)
            assert resumed["_is_error"] is False
            assert resumed["result"]["started"] is True
            assert resumed["result"]["job_id"] == item["job_id"]
            assert resumed["result"]["status"] == "completed"
        assert calls == [item["job_id"] for item in created]

        for number, item in enumerate(created, start=60):
            again = _mcp(recovered, "jobs.resume", {"version": 1, "intent_id": item["intent_id"]}, number)
            assert again["result"]["started"] is False
            assert again["result"]["job_id"] == item["job_id"]
        assert calls == [item["job_id"] for item in created]
        assert restarted.queue.list() == []
        assert [restarted.jobs[item["job_id"]]["status"] for item in created] == ["completed", "completed", "completed"]


def test_resume_does_not_start_a_second_job_when_that_leftover_is_already_running(tmp_path):
    calls: list[str] = []
    path = tmp_path / "queue.json"

    def start(job):
        calls.append(job["id"])
        job["status"] = "running"

    service = JobLeftovers(queue=DurableGenerationQueue(str(path)), jobs={}, start=start)
    created = service.enqueue(_payload("once"), workspace="lab", intent_id="keep")
    restarted = service.reloaded()
    restarted.jobs[created["job_id"]] = {
        "id": created["job_id"],
        "status": "running",
        "workspace": "lab",
        "params": _payload("once"),
        "provenance": {"command": {"command_id": "keep"}},
    }

    result = command_handlers(restarted)["jobs.resume"]({"version": 1, "intent_id": "keep"})

    assert result["result"]["started"] is False
    assert result["result"]["job_id"] == created["job_id"]
    assert result["result"]["status"] == "running"
    assert calls == []
    assert len(restarted.queue.list()) == 1


def test_discard_removes_one_leftover_and_leaves_a_running_job(tmp_path):
    path = tmp_path / "queue.json"
    service = JobLeftovers(queue=DurableGenerationQueue(str(path)), jobs={})
    first = service.enqueue(_payload("drop-me"), workspace="lab", intent_id="drop")
    second = service.enqueue(_payload("keep-me"), workspace="lab", intent_id="keep", previous_status="running")
    restarted = service.reloaded()
    restarted.jobs[second["job_id"]] = {
        "id": second["job_id"],
        "status": "running",
        "workspace": "lab",
        "provenance": {"command": {"command_id": "keep"}},
    }
    handlers = command_handlers(restarted)

    dropped = handlers["jobs.discard"]({"version": 1, "intent_id": "drop"})
    kept = handlers["jobs.discard"]({"version": 1, "intent_id": "keep"})

    assert dropped["result"]["discarded"] is True
    assert dropped["result"]["job_id"] == first["job_id"]
    assert kept["result"]["discarded"] is False
    assert kept["result"]["job_id"] == second["job_id"]
    assert [record["id"] for record in restarted.queue.list()] == [second["job_id"]]
    with pytest.raises(HTTPException) as missing:
        handlers["jobs.resume"]({"version": 1, "intent_id": "drop"})
    assert missing.value.detail["code"] == "leftover_not_found"
    assert "not found" not in json.dumps(missing.value.detail).lower()


def test_submit_and_status_do_not_run_the_recovery_projection(tmp_path):
    def explode(_records):
        raise HTTPException(status_code=503, detail={"code": "storage_unavailable"})

    path = tmp_path / "queue.json"
    created = JobLeftovers(queue=DurableGenerationQueue(str(path)), jobs={}).enqueue(
        _payload("harbor"), workspace="lab", intent_id="intent-beta",
    )
    recovered = JobLeftovers(
        queue=DurableGenerationQueue(str(path)), jobs={}, prepare=explode,
    )

    status = recovered.status_for(created["job_id"])
    assert status is not None
    assert status["job_id"] == created["job_id"]
    assert recovered.receipt_for("lab", "intent-beta")["receipt"]["result"]["job_id"] == created["job_id"]
    duplicate = recovered.duplicate_for_submit(_payload("harbor"), "lab")
    assert duplicate is not None
    assert duplicate["code"] == "duplicate_leftover"
    assert duplicate["job_id"] == created["job_id"]
    with pytest.raises(HTTPException) as error:
        recovered.list_response()
    assert error.value.status_code == 503


def test_planned_h3_leftover_still_matches_the_original_submit(tmp_path):
    original = _payload("long harbor")
    planned = {
        **original,
        "h3_window_prompts": ["one", "two"],
        "h3_window_plan": {"windows": 2},
        "h3_window_plan_signature": "sig",
        "minimax_h3_window_storyboard": True,
    }
    assert content_fingerprint(original, "lab") == content_fingerprint(planned, "lab")

    path = tmp_path / "queue.json"
    created = JobLeftovers(queue=DurableGenerationQueue(str(path)), jobs={}).enqueue(
        original, workspace="lab", intent_id="intent-h3",
    )
    stored = DurableGenerationQueue(str(path)).list()[0]
    stored["params"] = planned
    DurableGenerationQueue(str(path)).upsert(stored)

    recovered = JobLeftovers(queue=DurableGenerationQueue(str(path)), jobs={})
    duplicate = recovered.duplicate_for_submit(original, "lab")
    assert duplicate is not None
    assert duplicate["job_id"] == created["job_id"]


def test_jobs_commands_take_input_like_every_other_command(tmp_path):
    service = JobLeftovers(queue=DurableGenerationQueue(str(tmp_path / "queue.json")), jobs={})
    first = service.enqueue(_payload("first"), workspace="lab", intent_id="first")
    handlers = command_handlers(service.reloaded())
    listed = handlers["jobs.leftovers"]({"version": 1, "input": {}})
    assert [item["intent_id"] for item in listed["result"]["jobs"]] == ["first"]
    dropped = handlers["jobs.discard"]({"version": 1, "input": {"intent_id": "first"}})
    assert dropped["result"]["job_id"] == first["job_id"]
    for bad in ({"version": 1, "intent_id": "first", "input": {"intent_id": "first"}},
                {"version": 1, "input": {"intent_id": "first", "extra": 1}}):
        with pytest.raises(HTTPException) as error:
            handlers["jobs.resume"](bad)
        assert error.value.detail["code"] == "invalid_command"
    with pytest.raises(HTTPException):
        handlers["jobs.leftovers"]({"version": 1, "input": {"job": 1}})
