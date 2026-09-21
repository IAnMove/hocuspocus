"""Wizard/MCP corpus: published operations, refusals, replay identity, unpublished tools.

Simulated admissions use the same FastAPI/MCP handlers as the Studio command
tests. A live catalog probe is read-only and never enqueues GPU work.
"""
from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.image_generation_commands import (
    create_image_generation_commands_router,
    image_command_catalog,
    image_command_handlers,
)
from routers.studio_music_commands import music_command_catalog
from routers.studio_sfx_commands import sfx_command_catalog
from routers.studio_speech_commands import speech_command_catalog
from routers.tools_upscale_commands import tools_upscale_command_catalog
from routers.wangp_mcp import create_wangp_mcp_router
from services.native_generation_operation import NativeGenerationOperation
from services.studio_music_spec import freeze_studio_music_spec
from services.studio_sfx_spec import freeze_studio_sfx_spec
from services.studio_speech_spec import freeze_studio_speech_spec
from services.tools_upscale_spec import freeze_tools_upscale_spec
from tests.test_image_generation_commands import FakeNative, _command, _db_counts, _mcp_call, _run
from tests.test_studio_music_commands import music_command
from tests.test_studio_speech_commands import speech_command
from tests.test_tools_command_runtime import command as upscale_command

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "tests/fixtures/wizard_mcp_corpus.json"
EVIDENCE = ROOT / "outputs/wizard-mcp-corpus-20260911"
LIVE_API = os.environ.get("HOCUS_WIZARD_MCP_LIVE_API", "http://127.0.0.1:42005")


def load_corpus():
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def _attach(service, name, freeze_spec, catalog, *, use_defaults=True):
    def freeze(command):
        frozen = freeze_spec(command)
        payload = frozen["effective"]["input"]
        params = deepcopy(payload.get("params", payload))
        workspace = payload.get("workspace") or params.get("workspace")
        return frozen, {**params, "workspace": workspace}

    service.operations[name] = NativeGenerationOperation(
        freeze=freeze,
        prepare=lambda params: (deepcopy(params), []),
        catalog=catalog,
        use_generation_defaults=use_defaults,
    )


def published_service(native):
    service = native.service()
    _attach(service, "generation.speech", freeze_studio_speech_spec, speech_command_catalog())
    _attach(service, "generation.music", freeze_studio_music_spec, music_command_catalog())
    _attach(service, "generation.sfx", freeze_studio_sfx_spec, sfx_command_catalog())
    _attach(
        service, "tools.upscale", freeze_tools_upscale_spec, tools_upscale_command_catalog(),
        use_defaults=False,
    )
    return service


def published_catalog(service):
    return image_command_catalog(adapter.catalog for adapter in service.operations.values())


def corpus_client(native, tmp_path):
    service = published_service(native)
    catalog = published_catalog(service)
    app = FastAPI()
    app.include_router(create_image_generation_commands_router(service))
    app.include_router(create_wangp_mcp_router(
        handlers=image_command_handlers(service),
        command_operations=catalog,
        journal_path=Path(tmp_path) / "mcp-journal.sqlite",
        token_getter=lambda: "test-token",
    ))
    return TestClient(app), service, catalog


def sfx_command(intent="sfx-corpus-intent"):
    return {
        "version": 2,
        "operation": "generation.sfx",
        "intent_id": intent,
        "input": {
            "workspace": "workspace-a",
            "params": {
                "model_type": "mmaudio_v2",
                "prompt": "  Rain against glass.\n  ",
                "duration_seconds": 3,
                "seed": 42,
            },
        },
    }


def command_for(operation, intent):
    builders = {
        "generation.image": lambda: _command(intent),
        "generation.speech": lambda: {**speech_command(intent), "input": {
            **speech_command(intent)["input"], "workspace": "workspace-a",
        }},
        "generation.music": lambda: {**music_command(intent), "input": {
            **music_command(intent)["input"], "workspace": "workspace-a",
        }},
        "generation.sfx": lambda: sfx_command(intent),
        "tools.upscale": lambda: {
            **upscale_command(intent),
            "input": {**upscale_command(intent)["input"], "workspace": "workspace-a"},
        },
    }
    return builders[operation]()


def mcp_args(command):
    return {key: value for key, value in command.items() if key != "operation"}


def write_evidence(name, payload):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def test_corpus_fixture_covers_required_kinds_and_languages():
    corpus = load_corpus()
    kinds = {case["kind"] for case in corpus["cases"]}
    langs = {case["lang"] for case in corpus["cases"]}
    assert kinds >= {"intent", "negation", "ambiguous", "workspace_change", "retry", "compound", "unpublished", "error_recovery"}
    assert langs == {"en", "es"}
    assert corpus["expect_actions_not_prose"] is True
    assert "generation.model3d" in corpus["unpublished_operations"]
    assert "generation.model3d" not in corpus["published_operations"]
    write_evidence("corpus-index.json", {
        "id": corpus["id"],
        "cases": [case["id"] for case in corpus["cases"]],
        "published_operations": corpus["published_operations"],
        "unpublished_operations": corpus["unpublished_operations"],
    })


def test_http_catalog_and_mcp_list_only_published_operations(tmp_path):
    corpus = load_corpus()
    native = FakeNative(tmp_path)
    client, _service, catalog = corpus_client(native, tmp_path)
    http = client.get("/api/v1/generation/commands")
    assert http.status_code == 200
    names = [entry["name"] for entry in http.json()["operations"]]
    assert names == [entry["name"] for entry in catalog]
    assert set(corpus["published_operations"]) <= set(names)
    assert "generation.model3d" not in names
    listed = client.post(
        "/api/v1/wangp/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    ).json()["result"]["tools"]
    tool_names = [tool["name"] for tool in listed]
    for operation in corpus["published_operations"]:
        assert operation in tool_names
    assert "generation.model3d" not in tool_names
    image = next(tool for tool in listed if tool["name"] == "generation.image")
    assert "operation" not in image["inputSchema"]["properties"]
    write_evidence("catalog-simulated.json", {
        "http": names,
        "mcp": tool_names,
        "unpublished_absent": "generation.model3d" not in tool_names,
    })


def test_refusal_invalid_command_creates_no_task(tmp_path):
    corpus = load_corpus()
    case = next(item for item in corpus["cases"] if item["id"] == "en-invalid-extra-field")
    native = FakeNative(tmp_path)
    client, service, _catalog = corpus_client(native, tmp_path)
    command = command_for("generation.image", "corpus-invalid")
    command["input"][case["expect"]["invalid_extra_field"]] = "wizard"
    response = client.post("/api/v1/generation/commands", json=command)
    assert response.status_code == case["expect"]["http_status"]
    assert response.json()["detail"]["code"] == "invalid_command"
    assert native.dispatch_calls == []
    assert _db_counts(service.registry("workspace-a"))["tasks"] == 0


def test_unpublished_tool_does_not_promise_success_or_create_a_task(tmp_path):
    native = FakeNative(tmp_path)
    client, service, _catalog = corpus_client(native, tmp_path)
    payload = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {
            "name": "generation.model3d",
            "arguments": {
                "version": 2,
                "intent_id": "corpus-video",
                "input": {"workspace": "workspace-a", "params": {"prompt": "a clip"}},
            },
        },
    }
    mcp = client.post("/api/v1/wangp/mcp", headers={"Authorization": "Bearer test-token"}, json=payload)
    assert mcp.status_code == 200
    result = mcp.json()["result"]
    assert result["isError"] is True
    assert native.dispatch_calls == []
    assert _db_counts(service.registry("workspace-a"))["tasks"] == 0
    http = client.post("/api/v1/generation/commands", json={
        "version": 2,
        "operation": "generation.model3d",
        "intent_id": "corpus-video-http",
        "input": {"workspace": "workspace-a", "params": {"model_type": "pi_flux2", "prompt": "a clip"}},
    })
    assert http.status_code == 422
    assert native.dispatch_calls == []
    write_evidence("unpublished-video.json", {
        "mcp_is_error": True,
        "http_status": http.status_code,
        "tasks": _db_counts(service.registry("workspace-a"))["tasks"],
    })


def test_timeout_replay_and_two_clients_share_one_id(tmp_path):
    native = FakeNative(tmp_path)
    client, service, _catalog = corpus_client(native, tmp_path)
    command = command_for("generation.image", "corpus-timeout")
    first = client.post("/api/v1/generation/commands", json=command)
    assert first.status_code == 200
    receipt = first.json()["receipt"]
    assert first.json()["replayed"] is False
    assert receipt["status"] == "queued"
    job_id = receipt["result"]["job_id"]
    task_ids = receipt["taskIds"]
    replay = client.post("/api/v1/generation/commands", json=command)
    assert replay.json()["replayed"] is True
    assert replay.json()["receipt"]["result"]["job_id"] == job_id
    mcp = _mcp_call(client, "generation.image", mcp_args(command), request_id=4).json()["result"]
    assert mcp["isError"] is False
    assert mcp["structuredContent"]["receipt"]["result"]["job_id"] == job_id
    assert mcp["structuredContent"]["receipt"]["taskIds"] == task_ids
    recovered = _mcp_call(
        client, "generation.receipt",
        {"version": 1, "input": {"workspace": "workspace-a", "intent_id": "corpus-timeout"}},
        request_id=5,
    ).json()["result"]
    assert recovered["structuredContent"]["receipt"]["result"]["job_id"] == job_id
    assert len(native.dispatch_calls) == 1
    assert _db_counts(service.registry("workspace-a"))["tasks"] == 1
    write_evidence("replay-same-id.json", {
        "job_id": job_id,
        "task_ids": task_ids,
        "http_replayed": True,
        "mcp_same_id": True,
        "dispatch_calls": 1,
    })


def test_concurrent_clients_admit_once_per_intent(tmp_path):
    native = FakeNative(tmp_path)
    _client, service, _catalog = corpus_client(native, tmp_path)
    command = command_for("generation.image", "corpus-race")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: _run(service.submit(deepcopy(command))), range(4)))
    ids = {result["receipt"]["result"]["job_id"] for result in results}
    assert len(ids) == 1
    assert sum(not result["replayed"] for result in results) == 1
    assert len(native.dispatch_calls) == 1


def test_published_modalities_admit_and_replay(tmp_path):
    native = FakeNative(tmp_path)
    client, service, _catalog = corpus_client(native, tmp_path)
    corpus = load_corpus()
    for case in corpus["cases"]:
        expect = case["expect"]
        if case["surface"] == "wizard" or not expect.get("creates_task"):
            continue
        operation = expect["operation"]
        if operation == "generation.receipt":
            continue
        command = command_for(operation, f"corpus-{case['id']}")
        http = client.post(
            "/api/v1/generation/commands", json=command,
            headers={"X-Hocus-UI-Surface": "wizard"},
        )
        assert http.status_code == 200, (case["id"], http.text)
        body = http.json()
        assert body["receipt"]["status"] == "queued"
        assert body["receipt"]["operation"] == operation
        mcp = _mcp_call(client, operation, mcp_args(command), request_id=hash(case["id"]) % 10_000 + 20)
        result = mcp.json()["result"]
        assert result["isError"] is False, case["id"]
        assert result["structuredContent"]["receipt"]["result"]["job_id"] == body["receipt"]["result"]["job_id"]
        if expect.get("replay_same_id") or expect.get("two_clients_same_id"):
            assert result["structuredContent"]["replayed"] is True
    counts = _db_counts(service.registry("workspace-a"))
    assert counts["tasks"] >= 1
    assert counts["tasks"] == counts["task_command_admissions"]


def test_receipt_in_another_workspace_is_not_the_same_job(tmp_path):
    native = FakeNative(tmp_path)
    client, service, _catalog = corpus_client(native, tmp_path)
    command = command_for("generation.image", "corpus-workspace")
    admitted = client.post("/api/v1/generation/commands", json=command)
    assert admitted.status_code == 200
    missing = client.get(
        "/api/v1/generation/commands/receipt",
        params={"workspace": "corpus-b", "intent_id": "corpus-workspace"},
    )
    assert missing.status_code == 404
    mcp = _mcp_call(
        client, "generation.receipt",
        {"version": 1, "input": {"workspace": "corpus-b", "intent_id": "corpus-workspace"}},
        request_id=44,
    ).json()["result"]
    assert mcp["isError"] is True
    assert _db_counts(service.registry("workspace-a"))["tasks"] == 1
    assert _db_counts(service.registry("corpus-b"))["tasks"] == 0


def test_changed_content_under_the_same_intent_conflicts(tmp_path):
    native = FakeNative(tmp_path)
    client, _service, _catalog = corpus_client(native, tmp_path)
    command = command_for("generation.image", "corpus-conflict")
    assert client.post("/api/v1/generation/commands", json=command).status_code == 200
    changed = deepcopy(command)
    changed["input"]["prompt"] = "a different literal"
    conflict = client.post("/api/v1/generation/commands", json=changed)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "intent_conflict"
    assert len(native.dispatch_calls) == 1


def _live_json(path, method="GET", body=None, headers=None, timeout=2.5):
    request = Request(
        LIVE_API.rstrip("/") + path,
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode()) if raw else {}
    except HTTPError as error:
        raw = error.read()
        try:
            payload = json.loads(raw.decode()) if raw else {}
        except json.JSONDecodeError:
            payload = {"detail": raw.decode("utf-8", "replace")[:300]}
        return error.code, payload
    except (URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None, None


def test_live_catalog_probe_is_read_only_and_separate_from_mock():
    corpus = load_corpus()
    status, catalog = _live_json("/api/v1/generation/commands")
    models_status, models = _live_json("/api/v1/models")
    mcp_status, mcp = _live_json("/api/v1/settings/mcp")
    unauthorized, _payload = _live_json(
        "/api/v1/wangp/mcp",
        method="POST",
        body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    downloaded = []
    if models_status == 200 and isinstance(models, dict):
        downloaded = [
            item.get("model_type")
            for item in models.get("models") or []
            if item.get("is_downloaded")
        ]
    live = {
        "api": LIVE_API,
        "catalog_status": status,
        "operations": [entry.get("name") for entry in (catalog or {}).get("operations") or []] if status == 200 else [],
        "mcp_settings_status": mcp_status,
        "mcp_enabled": bool((mcp or {}).get("enabled")) if mcp_status == 200 else False,
        "mcp_token_absent": mcp_status == 200 and "token" not in (mcp or {}),
        "mcp_unauthorized_without_bearer": unauthorized,
        "downloaded_models": downloaded,
        "real_generation": "PENDING",
        "reason": "Shared runtime already has installed models; H17 does not enqueue GPU jobs on it.",
    }
    write_evidence("live-probe.json", live)
    write_evidence("matrix.json", {
        "states": ["designed", "implemented", "simulated", "real_executed", "pending"],
        "rows": corpus["matrix"],
        "failures": corpus["failures"],
        "live": {
            "catalog": status == 200,
            "generation": "PENDING",
        },
    })
    if status is None:
        write_evidence("real-circuit.json", {
            "status": "PENDING",
            "reason": f"No live API at {LIVE_API}; mock coverage remains the authority for this cut.",
        })
        return
    assert status == 200
    assert set(corpus["published_operations"]) <= set(live["operations"])
    assert "generation.model3d" not in live["operations"]
    assert unauthorized in {401, 403, 503}
    assert "token" not in (mcp or {})
    write_evidence("real-circuit.json", {
        "status": "PARTIAL",
        "read_only_catalog": True,
        "generation": "PENDING",
        "downloaded_models_sample": downloaded[:8],
        "note": "Discovery against the already-running API. No generation POST.",
    })
