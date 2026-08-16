import asyncio
import json
import subprocess
import sys
import threading
from pathlib import Path

import httpx
from fastapi import FastAPI

from routers.series_assembly import create_series_assembly_router


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "docs/series-lab/series-assembly.openapi.json"


def _contract_projection(value):
    """Ignore Pydantic's presentation metadata while comparing the contract."""
    if isinstance(value, dict):
        return {
            key: _contract_projection(item)
            for key, item in value.items()
            if key not in {"title", "description", "default", "required"}
        }
    if isinstance(value, list):
        return [_contract_projection(item) for item in value]
    return value


def _app(tmp_path):
    router = create_series_assembly_router(
        resolve_workspace=lambda value: str(value or "default"),
        workspace_dir=lambda _workspace: str(tmp_path),
        list_workspaces=lambda: [{"name": "default"}],
        library_lock=threading.RLock(),
        read_library=lambda _workspace: {},
        write_library=lambda _workspace, value: value,
        find_series=lambda _library, _series_id: {},
        asset_local_path=lambda _workspace, _asset: "",
        available_filename=lambda _directory, name: name,
        concatenate_clips=lambda _paths, _output: True,
        iso_now=lambda: "2026-08-12T00:00:00Z",
    )
    app = FastAPI()
    app.include_router(router)
    return app


def test_invalid_assembly_start_payload_is_structured_422(tmp_path):
    async def request_invalid_payload():
        transport = httpx.ASGITransport(app=_app(tmp_path))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/v1/series/series-1/episodes/episode-1/assembly/start",
                json={"workspace": 42},
            )

    response = asyncio.run(request_invalid_payload())

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0]["loc"][-1] == "workspace"
    assert detail[0]["type"] == "string_type"


def test_openapi_fixture_matches_series_assembly_operations_and_schemas(tmp_path):
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    actual = _app(tmp_path).openapi()

    for path, fixture_path in fixture["paths"].items():
        assert path in actual["paths"]
        for method, fixture_operation in fixture_path.items():
            actual_operation = actual["paths"][path][method]
            assert actual_operation["operationId"] == fixture_operation["operationId"]
            assert actual_operation.get("parameters") == fixture_operation.get("parameters")
            assert actual_operation.get("requestBody") == fixture_operation.get("requestBody")
            for status in ("200", "422"):
                assert actual_operation["responses"][status] == fixture_operation["responses"][status]

    for name in ("SeriesAssemblyStartRequest", "SeriesAssemblyJobResponse"):
        expected = fixture["components"]["schemas"][name]
        observed = actual["components"]["schemas"][name]
        assert set(observed["properties"]) == set(expected["properties"])
        assert set(observed.get("required", [])) == set(expected.get("required", []))
        assert observed.get("additionalProperties", False) == expected.get("additionalProperties", False)
        assert _contract_projection(observed) == _contract_projection(expected)
    assert actual["components"]["schemas"]["SeriesAssemblyJobResponse"]["properties"]["status"]["enum"] == [
        "queued", "running", "completed", "failed",
    ]


def test_generated_typescript_contract_detector_is_current():
    result = subprocess.run(
        [sys.executable, "scripts/check_series_assembly_contract.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
