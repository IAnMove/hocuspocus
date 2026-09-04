from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.services.asset_manifest import build_asset_manifest
from app.services.generation_record import (
    ATTEMPT_IDENTITY_POLICY,
    PRODUCTS,
    PROMPT_DISPLAY_MAX,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    STATUSES,
    GenerationRecordError,
    GenerationRecordStore,
    apply_cancel,
    attach_derivative,
    belongs_to_workspace,
    build_generation_record,
    load_generation_record,
    map_manifest_status,
    persist_generation_record,
    project_from_asset_manifest,
    prompt_display_text,
    request_cancel,
    resume_generation_record,
    retry_generation,
    to_asset_manifest_patch,
    transition_status,
    validate_generation_record,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "development" / "generation-record-v1.schema.json"
MODULE_PATH = ROOT / "app" / "services" / "generation_record.py"


def _record(**overrides):
    payload = dict(
        workspace_id="collection-a",
        output_folder="night-shift",
        product="studio",
        prompt_full="A sysadmin choir in the server room",
        model={"provider": "local", "id": "minimax-h3", "version": "1", "configuration": {"seed": 7}},
        location={"filename": "choir.mp4"},
    )
    payload.update(overrides)
    return build_generation_record(**payload)


def test_contract_schema_and_required_fields():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    record = _record(
        generation_id="gen_fixed",
        asset_id="asset_fixed",
        project_id="story-1",
        production_id="production-1",
        cue_id="cue-1",
        candidate_id="candidate-1",
        song_version="2",
        languages={
            "conversation_language": "es",
            "content_language": "es",
            "spoken_language": "es",
            "technical_prompt_language": "en",
        },
    )
    assert record["schema"] == SCHEMA_NAME == schema["properties"]["schema"]["const"]
    assert record["schema_version"] == SCHEMA_VERSION == schema["properties"]["schema_version"]["const"]
    assert set(schema["required"]) <= set(record)
    assert record["product"] in PRODUCTS
    assert record["status"] in STATUSES
    assert "title" not in record
    assert record["generation_id"] == "gen_fixed"
    assert record["asset_id"] == "asset_fixed"
    assert record["workspace_id"] == "collection-a"
    assert record["output_folder"] == "night-shift"
    assert record["location"]["filename"] == "choir.mp4"
    assert record["location"]["sidecar"] == "choir.meta.json"
    assert ATTEMPT_IDENTITY_POLICY == "new_generation_id"


def test_rejects_host_paths_and_missing_workspace():
    with pytest.raises(GenerationRecordError, match="workspace_id"):
        build_generation_record(output_folder="night-shift", prompt_full="x")
    with pytest.raises(GenerationRecordError, match="never a path"):
        build_generation_record(workspace_id="/tmp/outputs", prompt_full="x")
    record = build_generation_record(
        workspace_id="collection-a",
        output_folder="/tmp/outputs/night-shift",
        location={"filename": "/tmp/outputs/choir.mp4", "uri": "/tmp/outputs/choir.mp4"},
    )
    encoded = json.dumps(record)
    assert record["output_folder"] == "night-shift"
    assert record["location"]["filename"] == "choir.mp4"
    assert record["location"]["uri"] == "choir.mp4"
    assert "/tmp" not in encoded
    assert "title" not in record


def test_prompt_display_truncation_and_secret_redaction():
    long_prompt = "α" * (PROMPT_DISPLAY_MAX + 40)
    record = _record(
        prompt_full=long_prompt,
        model={"provider": "local", "id": "h3", "configuration": {
            "api_key": "do-not-save",
            "nested": {"authorization": "Bearer secret"},
            "prompt": "safe",
        }},
    )
    encoded = json.dumps(record)
    assert record["prompt_full"] == long_prompt
    assert len(record["prompt_display"]) <= PROMPT_DISPLAY_MAX
    assert record["prompt_display"].endswith("…")
    assert prompt_display_text(long_prompt) == record["prompt_display"]
    assert "do-not-save" not in encoded
    assert "Bearer secret" not in encoded
    assert record["model"]["configuration"]["prompt"] == "safe"
    assert record["model"]["configuration"]["api_key"] == "[REDACTED]"


def test_identity_is_not_title_or_prompt():
    first = _record(prompt_full="same prompt", location={"filename": "same.mp4"})
    second = _record(prompt_full="same prompt", location={"filename": "same.mp4"})
    assert first["generation_id"] != second["generation_id"]
    assert first["asset_id"] != second["asset_id"]
    resumed = validate_generation_record({**first, "prompt_full": "a different prompt"})
    assert resumed["generation_id"] == first["generation_id"]
    assert resumed["asset_id"] == first["asset_id"]


def test_persistence_round_trip_is_atomic(tmp_path: Path):
    record = _record(generation_id="gen_persist", asset_id="asset_persist", status="queued")
    path = tmp_path / "collection-a" / "gen_persist.json"
    written = persist_generation_record(path, record)
    loaded = load_generation_record(written, workspace_id="collection-a")
    assert loaded["generation_id"] == "gen_persist"
    assert loaded["asset_id"] == "asset_persist"
    assert loaded["status"] == "queued"
    assert loaded["prompt_full"] == record["prompt_full"]
    assert json.loads(written.read_text(encoding="utf-8"))["schema"] == SCHEMA_NAME
    assert not list(path.parent.glob("*.tmp"))


def test_resume_after_simulated_restart_keeps_running(tmp_path: Path):
    store = GenerationRecordStore(tmp_path / "records")
    record = transition_status(
        transition_status(_record(generation_id="gen_live", asset_id="asset_live"), "queued"),
        "running",
    )
    store.persist(record)
    recovered = GenerationRecordStore(tmp_path / "records").resume(
        "gen_live", workspace_id="collection-a",
    )
    assert recovered["status"] == "running"
    assert recovered["generation_id"] == "gen_live"
    assert recovered["asset_id"] == "asset_live"
    assert resume_generation_record(recovered)["status"] != "completed"


def test_cancellation_before_and_during_running():
    planned = request_cancel(_record(status="planned"), reason="user")
    assert planned["status"] == "cancelled"
    assert planned["cancellation"]["requested"] is True
    assert planned["cancellation"]["reason"] == "user"

    queued = request_cancel(transition_status(_record(), "queued"), reason="queue")
    assert queued["status"] == "cancelled"

    running = transition_status(transition_status(_record(), "queued"), "running")
    requested = request_cancel(running, reason="stop")
    assert requested["status"] == "running"
    assert requested["cancellation"]["requested"] is True
    settled = apply_cancel(requested, reason="stop")
    assert settled["status"] == "cancelled"
    assert settled["cancellation"]["requested"] is True
    late = transition_status(requested, "completed")
    assert late["status"] == "cancelled"
    requeued = transition_status(requested, "queued")
    assert requeued["status"] == "cancelled"


def test_cross_workspace_isolation(tmp_path: Path):
    store = GenerationRecordStore(tmp_path / "records")
    record = _record(generation_id="gen_a", asset_id="asset_a", workspace_id="workspace-a")
    path = store.persist(record)
    assert belongs_to_workspace(record, "workspace-a")
    assert not belongs_to_workspace(record, "workspace-b")
    with pytest.raises(GenerationRecordError, match="cross-workspace"):
        load_generation_record(path, workspace_id="workspace-b")
    assert store.list(workspace_id="workspace-b") == []
    assert [item["generation_id"] for item in store.list(workspace_id="workspace-a")] == ["gen_a"]
    cloned = tmp_path / "records" / "workspace-b" / "gen_a.json"
    cloned.parent.mkdir(parents=True)
    cloned.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(GenerationRecordError, match="cross-workspace"):
        load_generation_record(cloned, workspace_id="workspace-b")
    assert store.list(workspace_id="workspace-b") == []


def test_retry_mints_new_generation_id_and_lineage():
    parent = _record(generation_id="gen_parent", asset_id="asset_parent", status="failed")
    child = retry_generation(parent)
    linked = attach_derivative(parent, child)
    assert ATTEMPT_IDENTITY_POLICY == "new_generation_id"
    assert child["generation_id"] != parent["generation_id"]
    assert child["asset_id"] != parent["asset_id"]
    assert child["retry_count"] == 1
    assert child["status"] == "planned"
    assert child["lineage"]["parents"][0]["generation_id"] == "gen_parent"
    assert linked["generation_id"] == "gen_parent"
    assert linked["lineage"]["derivatives"][0]["generation_id"] == child["generation_id"]
    same_bytes = retry_generation(parent, same_artifact=True)
    assert same_bytes["asset_id"] == "asset_parent"
    assert same_bytes["generation_id"] != "gen_parent"


def test_resume_and_retry_do_not_recycle_parent_ids(tmp_path: Path):
    store = GenerationRecordStore(tmp_path)
    parent = transition_status(transition_status(_record(generation_id="gen_r", asset_id="asset_r"), "queued"), "running")
    store.persist(parent)
    resumed = store.resume("gen_r", workspace_id="collection-a")
    assert resumed["generation_id"] == "gen_r"
    assert resumed["asset_id"] == "asset_r"
    child = retry_generation(resumed)
    store.persist(attach_derivative(resumed, child))
    store.persist(child)
    assert store.load("gen_r", workspace_id="collection-a")["generation_id"] == "gen_r"


def test_illegal_transitions_are_rejected():
    completed = transition_status(
        transition_status(transition_status(_record(), "queued"), "running"),
        "completed",
    )
    assert completed["status"] == "completed"
    with pytest.raises(GenerationRecordError, match="Illegal generation transition"):
        transition_status(completed, "running")


def test_project_from_asset_manifest_and_patch_round_trip(tmp_path: Path):
    output = tmp_path / "choir.mp4"
    output.write_bytes(b"video")
    manifest = build_asset_manifest(
        output,
        asset_id="asset_video_1",
        workspace_id="collection-a",
        output_folder="night-shift",
        project={"kind": "story", "id": "story_1"},
        production={"kind": "music_video", "id": "production_1"},
        tool="story_lab",
        capability="generate_story_song",
        actor="wizard",
        status="prepared",
        correlations={"job_id": "job-1", "cue_id": "cue-1", "candidate_id": "candidate-1", "song_version": "2"},
        prompts={"effective": "Metal fantástico", "language": "es"},
        model={"provider": "local", "id": "minimax-h3", "revision": "r1"},
        parameters={"seed": 3, "api_key": "secret"},
        parents=[{"id": "asset_song_1", "kind": "audio", "uri": "song.wav", "role": "soundtrack"}],
        timing={"created_at": 1_700_000_000, "queued_at": 1_700_000_001},
    )
    record = project_from_asset_manifest(manifest)
    assert record["status"] == "planned"
    assert record["generation_id"] == "job-1"
    assert record["asset_id"] == "asset_video_1"
    assert record["product"] == "story_lab"
    assert record["project_id"] == "story_1"
    assert record["cue_id"] == "cue-1"
    assert record["prompt_full"] == "Metal fantástico"
    assert record["languages"]["content_language"] == "es"
    assert record["model"]["configuration"]["api_key"] == "[REDACTED]"
    assert record["lineage"]["parents"][0]["asset_id"] == "asset_song_1"
    patch = to_asset_manifest_patch(record)
    assert patch["execution"]["status"] == "prepared"
    assert patch["asset"]["id"] == "asset_video_1"
    assert patch["origin"]["workspace_id"] == "collection-a"
    assert patch["technical"]["generation_id"] == "job-1"
    assert "secret" not in json.dumps(patch)


def test_manifest_partial_maps_to_result_kind(tmp_path: Path):
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"video")
    with_file = project_from_asset_manifest(build_asset_manifest(
        output, asset_id="asset_partial", workspace_id="ws", status="partial", tool="studio",
    ))
    assert with_file["status"] == "completed"
    assert with_file["result"]["kind"] == "partial"
    failed = project_from_asset_manifest({
        "schema": "hocuspocus.asset-manifest",
        "schema_version": 1,
        "asset": {"id": "asset_empty", "kind": "video", "filename": None},
        "origin": {"tool": "studio", "workspace_id": "ws", "output_folder": "ws"},
        "execution": {"status": "partial", "mode": "real"},
        "generation": {"prompts": {}, "model": {}, "parameters": {}, "inputs": []},
        "timing": {},
        "lineage": {"parents": [], "transformations": []},
    })
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "partial"
    status, _result, error = map_manifest_status("bogus")
    assert status == "failed"
    assert error["code"] == "invalid_status"


def test_module_does_not_import_runtime_engines():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert all("fastapi" not in name for name in imported)
    assert all("wgp" not in name for name in imported)
    assert all("launch" not in name for name in imported)
