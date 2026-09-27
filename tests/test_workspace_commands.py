"""Shared commands commit a collection and its retry receipt together."""
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import json
import multiprocessing
import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from services.workspace_registry import WorkspaceRegistry
from services.workspace_commands import MUTATIONS, OPERATIONS, catalog, validate_command
from routers.workspace_collections import create_workspace_collections_router
from routers.wangp_mcp import RequestJournal, create_wangp_mcp_router
from services.wangp_agent_adapters import application_handlers


def create_command(intent="intent-1", **fields):
    return {"version": 1, "operation": "collections.create", "intent_id": intent,
            "input": {"name": "Nightwatch", **fields}}


def _submit(path, command):
    return WorkspaceRegistry(path).execute_command(command)


def test_receipt_and_collection_survive_restart_and_new_intent_is_not_deduplicated(tmp_path):
    path = tmp_path / "registry.json"
    registry = WorkspaceRegistry(path)
    first = registry.execute_command(create_command())
    replay = WorkspaceRegistry(path).execute_command(create_command())
    assert replay == {**first, "replayed": True}
    assert first["commandId"] == "intent-1"
    assert first["status"] == "completed"
    assert first["entities"][0]["version"] == 1
    assert first["taskIds"] == []
    assert registry.command_receipt("intent-1") == first
    repeated_intentionally = registry.execute_command(create_command("intent-2"))
    assert repeated_intentionally["result"]["id"] != first["result"]["id"]
    assert len(registry.list()) == 2
    with pytest.raises(RuntimeError, match="different parameters"):
        registry.execute_command(create_command(name="Another name"))
    stored = json.loads(path.read_text())["commands"]["intent-1"]
    assert stored["original"]["input"] == {"name": "Nightwatch"}
    assert stored["effective"]["input"]["asset_ids"] == []
    assert stored["fingerprint_version"] == 1


def test_effective_defaults_replay_but_null_and_bad_types_do_not(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    first = registry.execute_command(create_command())
    replay = registry.execute_command(create_command(description="", asset_ids=[], project_ids=[], production_ids=[]))
    assert replay["result"] == first["result"]
    for change in ({"name": None}, {"name": 10}, {"name": "   "}, {"asset_ids": ["a", "a"]},
                   {"asset_ids": [True]}, {"project_ids": None}, {"surprise": True}):
        with pytest.raises(ValueError):
            registry.execute_command(create_command("invalid", **change))
    assert registry.command_receipt("invalid") is None
    assert len(registry.list()) == 1


def test_cross_process_retries_commit_exactly_one_entity(tmp_path):
    path = str(tmp_path / "registry.json")
    with ProcessPoolExecutor(max_workers=3, mp_context=multiprocessing.get_context("spawn")) as pool:
        receipts = list(pool.map(_submit, [path] * 6, [create_command()] * 6))
    assert len({receipt["result"]["id"] for receipt in receipts}) == 1
    assert sum(not receipt["replayed"] for receipt in receipts) == 1
    assert len(WorkspaceRegistry(path).list()) == 1


@pytest.mark.parametrize("after_commit", [False, True])
def test_lost_response_or_failure_before_commit_can_retry_without_duplication(tmp_path, after_commit):
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    write = registry._write

    def interrupted(store):
        if after_commit:
            write(store)
        raise ConnectionResetError("Injected lost storage response")

    registry._write = interrupted
    with pytest.raises(ConnectionResetError):
        registry.execute_command(create_command())
    recovered = WorkspaceRegistry(registry.path)
    receipt = recovered.execute_command(create_command())
    assert receipt["replayed"] is after_commit
    assert len(recovered.list()) == 1


def test_updates_require_exact_revision_and_preserve_omitted_memberships(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    first = registry.execute_command(create_command(asset_ids=["asset-real"]), lambda *_: {"id": "asset-real"})
    identity = first["result"]["id"]
    command = {"version": 1, "operation": "collections.update", "intent_id": "edit-1",
               "input": {"workspace_id": identity, "expected_revision": 1, "description": "Updated"}}
    changed = registry.execute_command(command)
    assert changed["result"]["revision"] == 2
    assert changed["result"]["asset_ids"] == ["asset-real"]
    assert registry.execute_command(command)["replayed"] is True
    with pytest.raises(RuntimeError, match="changed since"):
        registry.execute_command({**command, "intent_id": "other-client"})
    with pytest.raises(RuntimeError, match="different parameters"):
        registry.execute_command({**command, "input": {**command["input"], "expected_revision": 2}})
    for revision in [None, True, "2", 2.1, 0]:
        with pytest.raises(ValueError):
            registry.execute_command({**command, "intent_id": "invalid", "input": {**command["input"], "expected_revision": revision}})
    assert registry.get(identity)["revision"] == 2
    assert registry.command_receipt("other-client") is None


def test_reference_validation_precedes_effect_and_replay_uses_historical_receipt(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    source = tmp_path / "source.png"
    source.write_bytes(b"source content is never moved or changed")
    seen = []

    def resolve(kind, identity):
        seen.append((kind, identity))
        if identity == "missing":
            raise HTTPException(404, "Asset not found")
        return {"id": identity}

    with pytest.raises(HTTPException):
        registry.execute_command(create_command(asset_ids=["missing"]), resolve)
    assert registry.command_receipt("intent-1") is None
    assert registry.list() == []
    first = registry.execute_command(create_command(asset_ids=["asset-real"], project_ids=["project-real"], production_ids=["production-real"]), resolve)
    assert set(seen[-3:]) == {("asset_ids", "asset-real"), ("project_ids", "project-real"), ("production_ids", "production-real")}
    registry.delete(first["result"]["id"])
    replay = registry.execute_command(create_command(asset_ids=["asset-real"], project_ids=["project-real"], production_ids=["production-real"]))
    assert replay["replayed"] is True  # Historical result, never recreate deleted data.
    assert registry.list() == []
    assert source.read_bytes() == b"source content is never moved or changed"


def test_published_catalog_only_lists_executable_operations_and_strict_invocations():
    public = catalog()
    assert {entry["name"] for entry in public["operations"]} == set(OPERATIONS)
    assert {entry["name"] for entry in public["operations"] if entry["mutation"]} == MUTATIONS
    for version in [True, "1", None, 2]:
        with pytest.raises(ValueError):
            validate_command({**create_command(), "version": version})
    with pytest.raises(ValueError):
        validate_command({**create_command(), "actor": "admin"})
    assert validate_command({"version": 1, "operation": "collections.list", "input": {}})[1]["input"] == {}
    projection = Path(__file__).resolve().parents[1] / "ui/src/api/workspaceCommandCatalog.json"
    assert json.loads(projection.read_text()) == public


def command_app(path):
    app = FastAPI()
    registry = WorkspaceRegistry(path)
    app.include_router(create_workspace_collections_router(registry=lambda: registry,
                       resolve_reference=lambda _kind, identity: {"id": identity}))
    app.add_api_route("/api/v1/assets", lambda: {"assets": []}, methods=["GET"])
    app.add_api_route("/api/v1/assets/{asset_id}", lambda asset_id: {"id": asset_id}, methods=["GET"])
    app.add_api_route("/api/v1/llm/generate", lambda: {"text": "unused"}, methods=["POST"])
    app.include_router(create_wangp_mcp_router(handlers=application_handlers(app),
                       journal_path=path.with_suffix(".sqlite"), token_getter=lambda: "test-token"))
    return TestClient(app), registry


def mcp_call(client, name, arguments, authorized=True):
    response = client.post("/api/v1/wangp/mcp", headers={"Authorization": "Bearer test-token"} if authorized else {},
                           json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    return response


def test_http_and_mcp_share_effect_receipt_recovery_auth_and_revision_conflicts(tmp_path):
    path = tmp_path / "registry.json"
    client, registry = command_app(path)
    command = create_command(asset_ids=["asset-real"])
    arguments = {key: value for key, value in command.items() if key != "operation"}
    first = client.post("/api/v1/commands", json=command)
    assert first.status_code == 200
    discovered = client.post("/api/v1/wangp/mcp", headers={"Authorization": "Bearer test-token"},
                             json={"jsonrpc": "2.0", "id": 0, "method": "tools/list"}).json()["result"]["tools"]
    assert {tool["name"] for tool in discovered} == set(OPERATIONS) | {"assets", "collections", "organize", "analyze"}
    assert {tool["name"] for tool in discovered[:len(OPERATIONS)]} == set(OPERATIONS)
    assert mcp_call(client, command["operation"], arguments, authorized=False).status_code == 401
    replay = mcp_call(client, command["operation"], arguments).json()["result"]
    assert replay["isError"] is False
    assert replay["structuredContent"] == {**first.json(), "replayed": True}
    assert len(registry.list()) == 1
    # A reconstructed application and an external client can recover with no UI.
    restarted, _ = command_app(path)
    recovered = mcp_call(restarted, "commands.receipt", {"version": 1, "input": {"intent_id": "intent-1"}}).json()["result"]
    assert recovered["structuredContent"] == first.json()
    modified = deepcopy(arguments)
    modified["input"]["name"] = "Conflicting request"
    assert mcp_call(restarted, "collections.create", modified).json()["result"]["isError"] is True
    assert not path.with_suffix(".sqlite").exists()  # No parallel mutation journal.
    assert client.post("/api/v1/commands", json={"version": 1, "operation": "collections.get", "input": {"workspace_id": "missing"}}).status_code == 404
    invalid = create_command("bad", asset_ids=None)
    assert client.post("/api/v1/commands", json=invalid).status_code == 400


def test_legacy_organize_recovers_after_domain_commit_before_transport_finish(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    client, registry = command_app(path)
    arguments = {"request_id": "legacy-1", "params": {"name": "Legacy campaign", "asset_ids": ["asset-real"]}}
    finish = RequestJournal.finish

    def lost_response(*_args):
        raise ConnectionResetError("Injected response lost after collection commit")

    monkeypatch.setattr(RequestJournal, "finish", lost_response)
    with pytest.raises(ConnectionResetError):
        mcp_call(client, "organize", arguments)
    assert len(registry.list()) == 1
    receipt = registry.command_receipt("legacy-1")
    assert receipt["result"]["name"] == "Legacy campaign"
    monkeypatch.setattr(RequestJournal, "finish", finish)
    restarted, _ = command_app(path)
    recovered = mcp_call(restarted, "organize", arguments).json()["result"]
    assert recovered["isError"] is False
    assert json.loads(recovered["content"][0]["text"]) == receipt["result"]
    assert len(registry.list()) == 1
    assert mcp_call(restarted, "organize", arguments).json()["result"] == recovered


def test_legacy_completed_receipts_keep_their_digest_and_unlinked_reservations_stay_uncertain(tmp_path):
    path = tmp_path / "registry.json"
    client, registry = command_app(path)
    journal = RequestJournal(path.with_suffix(".sqlite"))
    params = {"name": "Old campaign", "asset_ids": ["asset-old"]}
    digest = hashlib.sha256(json.dumps(["organize", params], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    journal.reserve("pre-migration", digest)
    journal.finish("pre-migration", {"id": "workspace-old", "revision": 7})
    result = mcp_call(client, "organize", {"request_id": "pre-migration", "params": params}).json()["result"]
    assert json.loads(result["content"][0]["text"]) == {"id": "workspace-old", "revision": 7}
    journal.reserve("uncertain-old", digest)
    uncertain = mcp_call(client, "organize", {"request_id": "uncertain-old", "params": params}).json()["result"]
    assert uncertain["isError"] is True
    assert "already reserved" in uncertain["content"][0]["text"]
    assert registry.list() == []


def test_legacy_opaque_request_ids_remain_valid_for_new_collection_effects(tmp_path):
    client, registry = command_app(tmp_path / "registry.json")
    arguments = {"request_id": "petición 1 · campaña", "params": {"name": "Campaign", "asset_ids": ["asset-real"]}}
    result = mcp_call(client, "organize", arguments).json()["result"]
    assert result["isError"] is False
    assert registry.command_receipt(arguments["request_id"])["result"]["name"] == "Campaign"


def test_mcp_uses_the_supplied_executable_domain_catalog_for_discovery_and_dispatch(tmp_path):
    operation = {"name": "example.inspect", "description": "Read a test domain", "mutation": False,
                 "inputSchema": {"type": "object", "additionalProperties": False,
                                 "properties": {"version": {"const": 1}, "operation": {"const": "example.inspect"},
                                                "input": {"type": "object"}},
                                 "required": ["version", "operation", "input"]}}
    unavailable = {**operation, "name": "example.unavailable"}
    app = FastAPI()
    app.include_router(create_wangp_mcp_router(
        handlers={"example.inspect": lambda arguments: {"observed": arguments["input"]}},
        command_operations=[operation, unavailable], journal_path=tmp_path / "journal.sqlite",
        token_getter=lambda: "test-token"))
    client = TestClient(app)
    discovered = client.post("/api/v1/wangp/mcp", headers={"Authorization": "Bearer test-token"},
                             json={"jsonrpc": "2.0", "id": 0, "method": "tools/list"}).json()["result"]["tools"]
    names = {tool["name"] for tool in discovered}
    assert "example.inspect" in names
    assert "example.unavailable" not in names
    assert "collections.create" not in names
    result = mcp_call(client, "example.inspect", {"version": 1, "input": {"id": "exact-id"}}).json()["result"]
    assert result["structuredContent"] == {"observed": {"id": "exact-id"}}
    assert not (tmp_path / "journal.sqlite").exists()
