from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import subprocess

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "story_director_audio_flow",
    _ROOT / "scripts/graphs/story_director_audio_flow.py",
)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

ArchitectureGraphError = _MODULE.ArchitectureGraphError
BACKEND_ROUTE_FUNCS = _MODULE.BACKEND_ROUTE_FUNCS
build_graph = _MODULE.build_graph
extract_backend_graph = _MODULE.extract_backend_graph
git_metadata = _MODULE._git_metadata


def _write_backend_fixture(root: Path, source: str, *, routes: list[str] | None = None) -> None:
    (root / "app").mkdir(parents=True)
    (root / "tests/fixtures").mkdir(parents=True)
    (root / "app/_launch_runtime.py").write_text(source, encoding="utf-8")
    endpoints = routes or list(BACKEND_ROUTE_FUNCS)
    payload = {
        "version": 1,
        "routes": [
            {
                "method": "GET" if endpoint == "serve_file" else "POST",
                "path": f"/api/v1/test/{endpoint}",
                "endpoint": endpoint,
            }
            for endpoint in endpoints
        ],
    }
    (root / "tests/fixtures/route_table.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _backend_source() -> str:
    return """
def _resolve_request_media_path(value):
    return resolve_permitted_media_path(value)

def _publish_audio_analysis_job(job):
    return job

def _stream_upload(value):
    return value

def _transcode_upload(value):
    return value

def _safe_join(root, name):
    return root / name

def _resolve_output_file(root, name):
    return _safe_join(root, name)

def adopt_audio(request):
    _resolve_request_media_path(request)
    _resolve_request_media_path(request)

def upload_audio(file):
    _stream_upload(file)
    _transcode_upload(file)

def trim_uploaded_audio(request):
    _resolve_request_media_path(request)

def start_audio_analysis_job(request):
    resource_scheduler.local_gpu_lane(0)
    _publish_audio_analysis_job(request)

def serve_file(filename):
    _resolve_output_file(filename, filename)
"""


def test_backend_graph_preserves_static_multiplicity_and_evidence(tmp_path: Path) -> None:
    _write_backend_fixture(tmp_path, _backend_source())

    graph = extract_backend_graph(tmp_path)
    edge = next(
        edge
        for edge in graph["edges"]
        if edge["source"] == "route.adopt_audio"
        and edge["target"] == "svc.resolve_request_path"
    )

    assert edge["weight"] == 2
    assert len(edge["evidence"]) == 2
    assert all(not Path(item["file"]).is_absolute() for item in edge["evidence"])
    assert any(node["id"] == "svc.resolve_permitted_path" for node in graph["nodes"])


def test_backend_graph_fails_closed_when_a_required_route_is_missing(tmp_path: Path) -> None:
    _write_backend_fixture(tmp_path, _backend_source(), routes=list(BACKEND_ROUTE_FUNCS[:-1]))

    with pytest.raises(ArchitectureGraphError, match="missing required endpoint"):
        extract_backend_graph(tmp_path)


def test_backend_graph_fails_closed_on_python_syntax_error(tmp_path: Path) -> None:
    _write_backend_fixture(tmp_path, "def adopt_audio(:\n")

    with pytest.raises(ArchitectureGraphError, match="Cannot parse"):
        extract_backend_graph(tmp_path)


def test_backend_only_build_does_not_require_ui_or_node(tmp_path: Path) -> None:
    _write_backend_fixture(tmp_path, _backend_source())

    graph = build_graph(tmp_path, backend_only=True)

    assert graph["meta"]["schema_version"] == 1
    assert graph["meta"]["source_commit"] is None
    assert graph["meta"]["dirty"] is True


def test_backend_graph_does_not_emit_unlinked_wrapper_edges(tmp_path: Path) -> None:
    source = _backend_source().replace("_resolve_request_media_path(request)", "request")
    _write_backend_fixture(tmp_path, source)

    graph = extract_backend_graph(tmp_path)

    assert not any(
        edge["source"] == "svc.resolve_request_path"
        for edge in graph["edges"]
    )


def test_git_status_failure_is_dirty_and_never_claims_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.py"
    source.write_text("pass\n", encoding="utf-8")

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, "abc123\n", "")
        return subprocess.CompletedProcess(command, 1, "", "status unavailable")

    monkeypatch.setattr(_MODULE.subprocess, "run", fake_run)
    commit, dirty, warnings = git_metadata(tmp_path, [source])

    assert commit == "abc123"
    assert dirty is True
    assert any("git status failed" in warning for warning in warnings)


def test_missing_git_metadata_is_dirty_and_has_null_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.py"
    source.write_text("pass\n", encoding="utf-8")

    def unavailable(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        raise OSError("git unavailable")

    monkeypatch.setattr(_MODULE.subprocess, "run", unavailable)
    commit, dirty, warnings = git_metadata(tmp_path, [source])

    assert commit is None
    assert dirty is True
    assert any("dirty is unknown" in warning for warning in warnings)


def test_backend_graph_is_deterministic_and_hashes_scoped_sources() -> None:
    first = build_graph(Path(__file__).resolve().parents[1], backend_only=True)
    second = build_graph(Path(__file__).resolve().parents[1], backend_only=True)

    assert first == second
    assert first["meta"]["schema_version"] == 1
    assert len(first["meta"]["source_hash"]) == 64
    assert first["meta"]["source_commit"]
    assert first["meta"]["generated_by"] == "scripts/graphs/story_director_audio_flow.py"
    assert set(first) == {"nodes", "edges", "meta"}


def test_backend_graph_contains_no_absolute_paths_or_unverified_annotations() -> None:
    graph = build_graph(Path(__file__).resolve().parents[1], backend_only=True)

    for record in [*graph["nodes"], *graph["edges"]]:
        for item in record["evidence"]:
            assert not Path(item["file"]).is_absolute()
    assert all("highlight" not in edge for edge in graph["edges"])
