"""Shared speech admission, native snapshots and inter-client replay without a provider."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routers.image_generation_commands import create_image_generation_commands_router, image_command_handlers
from services.studio_speech_commands import speech_command_catalog
from services.native_generation_operation import NativeGenerationOperation
from services.studio_speech_spec import freeze_studio_speech_spec, studio_speech_schema
from tests.test_image_generation_commands import FakeNative, _command as image_command, _run, _db_counts


def speech_command(intent="speech-test-intent"):
    native = json.loads((Path(__file__).parent / "fixtures/studio_speech_native_request.json").read_text())
    workspace = native.pop("workspace")
    return {"version": 2, "operation": "generation.speech", "intent_id": intent,
            "input": {"workspace": workspace, "params": native}}


def configured_service(native):
    def freeze(command):
        frozen = freeze_studio_speech_spec(command)
        effective = frozen["effective"]["input"]
        return frozen, {**deepcopy(effective["params"]), "workspace": effective["workspace"]}

    def prepare(params):
        native.preflight(params)
        return deepcopy(params), []

    service = native.service()
    service.operations = {"generation.speech": NativeGenerationOperation(
        freeze=freeze, prepare=prepare, catalog=speech_command_catalog())}
    return service


def test_http_then_mcp_replays_same_speech_task_and_native_literal_snapshot(tmp_path):
    native = FakeNative(tmp_path)
    service = configured_service(native)
    app = FastAPI()
    app.include_router(create_image_generation_commands_router(service))
    command = speech_command()
    with TestClient(app) as client:
        first = client.post("/api/v1/generation/commands", json=command,
                            headers={"X-Hocus-UI-Surface": "wizard"})
        assert first.status_code == 200
        catalog = client.get("/api/v1/generation/commands").json()
    names = {operation["name"] for operation in catalog["operations"]}
    assert {"generation.image", "generation.speech", "generation.receipt"} <= names
    mcp_arguments = {key: value for key, value in command.items() if key != "operation"}
    replay = _run(image_command_handlers(service)["generation.speech"](mcp_arguments))
    receipt = first.json()["receipt"]
    assert replay == {"receipt": receipt, "replayed": True}
    assert receipt["operation"] == "generation.speech"
    assert native.prepare_calls == native.preflight_calls == 1
    assert len(native.dispatch_calls) == 1
    entry = native.registry("speech-test").command_admission(command["intent_id"])
    snapshot = entry["effective"]["runtime"]
    assert snapshot["params"]["prompt"] == command["input"]["params"]["prompt"]
    assert snapshot["params"]["_tts_original_prompt"] == command["input"]["params"]["_tts_original_prompt"]
    assert snapshot["params"]["duration_seconds"] == 20
    assert snapshot["provenance"]["capability"] == "generation.speech"
    assert snapshot["provenance"]["actor"] == "wizard"


def test_intent_cannot_cross_image_and_speech_domains(tmp_path):
    native = FakeNative(tmp_path)
    service = configured_service(native)
    _run(service.submit(speech_command()))
    with pytest.raises(HTTPException) as caught:
        _run(service.submit(image_command("speech-test-intent", workspace="speech-test")))
    assert caught.value.status_code == 409
    assert len(native.dispatch_calls) == 1


def test_concurrent_speech_clients_and_deliberate_second_attempt(tmp_path):
    native = FakeNative(tmp_path)
    service = configured_service(native)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _run(service.submit(speech_command())), range(2)))
    assert results[0]["receipt"] == results[1]["receipt"]
    assert sum(not result["replayed"] for result in results) == 1
    assert len(native.dispatch_calls) == 1
    second = _run(service.submit(speech_command("another-deliberate-speech")))
    assert second["receipt"]["taskIds"] != results[0]["receipt"]["taskIds"]
    assert _db_counts(native.registry("speech-test"))["tasks"] == 2


def test_speech_replay_does_not_revalidate_an_unavailable_model(tmp_path):
    native = FakeNative(tmp_path)
    service = configured_service(native)
    first = _run(service.submit(speech_command()))
    native.preflight_error = RuntimeError("Model is now unavailable")
    assert _run(service.submit(speech_command()))["receipt"] == first["receipt"]
    changed = speech_command()
    changed["input"]["params"]["prompt"] += " Changed"
    with pytest.raises(HTTPException) as caught:
        _run(service.submit(changed))
    assert caught.value.status_code == 409
    assert len(native.dispatch_calls) == 1


def test_speech_restart_rebuilds_existing_recovery_without_dispatch(tmp_path):
    first_native = FakeNative(tmp_path)
    first = _run(configured_service(first_native).submit(speech_command()))
    restarted = FakeNative(tmp_path, interrupt_stale=True)
    service = configured_service(restarted)
    service.restore_recovery(["speech-test"])
    assert len(restarted.persist_calls) == 1
    assert restarted.dispatch_calls == []
    record = restarted.persist_calls[0]
    assert record["params"]["_tts_original_prompt"] == speech_command()["input"]["params"]["prompt"]
    assert service.filter_recovery([record]) == [record]
    replay = _run(service.submit(speech_command()))
    assert replay["receipt"] == first["receipt"]
    assert service.receipt("speech-test", "speech-test-intent")["task"]["status"] == "interrupted"


def test_runtime_without_speech_adapter_does_not_adopt_its_recovery(tmp_path):
    _run(configured_service(FakeNative(tmp_path)).submit(speech_command()))
    restarted = FakeNative(tmp_path, interrupt_stale=True)
    restarted.service().restore_recovery(["speech-test"])
    assert restarted.persist_calls == []
    assert restarted.dispatch_calls == []


def test_speech_orphan_and_malformed_command_do_not_block_linked_recovery(tmp_path):
    _run(configured_service(FakeNative(tmp_path)).submit(speech_command()))
    restarted = FakeNative(tmp_path, interrupt_stale=True)
    service = configured_service(restarted)
    service.restore_recovery(["speech-test"])
    linked = restarted.persist_calls[0]
    orphan = deepcopy(linked)
    orphan["provenance"]["command"]["command_id"] = "missing-speech-admission"
    malformed = deepcopy(linked)
    malformed["provenance"]["command"] = "invalid"
    assert service.filter_recovery([orphan, malformed, linked]) == [linked]
    service.discard_recovery([orphan, malformed, linked])
    assert service.receipt("speech-test", "speech-test-intent")["task"]["status"] == "cancelled"


def test_browser_catalog_matches_executable_speech_contract():
    path = Path(__file__).resolve().parents[1] / "ui/src/api/speechCommandCatalog.json"
    projection = json.loads(path.read_text(encoding="utf-8"))
    assert projection == {"version": 2, "operations": [speech_command_catalog()], "studio": studio_speech_schema()}
