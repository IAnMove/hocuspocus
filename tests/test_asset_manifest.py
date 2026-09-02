from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.asset_manifest import (
    SCHEMA_NAME,
    AssetManifestError,
    adapt_legacy_sidecar,
    build_asset_manifest,
    infer_asset_kind,
    publish_generation_sidecar,
    publish_generation_sidecar_best_effort,
    read_asset_manifest,
    write_asset_manifest,
)
from app.services.generation_provenance import (
    provenance_from_manifest,
    resolve_generation_location,
)


def test_manifest_records_identity_provenance_prompts_model_and_timing(tmp_path: Path):
    output = tmp_path / "sysadmin.mp4"
    output.write_bytes(b"video")
    manifest = build_asset_manifest(
        output,
        asset_id="asset_video_1",
        workspace_id="night-shift",
        project={"kind": "story", "id": "story_1", "version": 3},
        production={"kind": "music_video", "id": "production_1"},
        tool="story-music-video",
        capability="start_director_production",
        actor="wizard",
        correlations={
            "command_id": "command_1", "workflow_id": "workflow_1",
            "run_id": "run_1", "task_id": "task_1", "job_id": "job_1",
            "pipeline_id": "pipeline_1",
        },
        prompts={
            "original": "Haz un videoclip", "effective": "Metal fantástico de 1981",
            "language": "es",
        },
        model={"provider": "local", "id": "minimax-h3"},
        parameters={"seed": 42, "duration_seconds": 5},
        inputs=[{"id": "asset_song_1", "kind": "audio", "uri": "song.wav", "role": "soundtrack"}],
        timing={
            "created_at": 1_700_000_000, "queued_at": 1_700_000_001,
            "started_at": 1_700_000_003, "completed_at": 1_700_000_008,
        },
    )

    assert manifest["asset"] == {
        "id": "asset_video_1", "kind": "video", "filename": "sysadmin.mp4",
        "uri": "sysadmin.mp4",
        "media": {"size_bytes": 5, "mime_type": "video/mp4", "extension": ".mp4"},
    }
    assert manifest["origin"]["project"]["id"] == "story_1"
    assert manifest["execution"]["pipeline_id"] == "pipeline_1"
    assert manifest["generation"]["inputs"][0]["id"] == "asset_song_1"
    assert manifest["timing"]["queue_ms"] == 2_000
    assert manifest["timing"]["inference_ms"] == 5_000
    assert manifest["timing"]["total_ms"] == 8_000


def test_manifest_redacts_secrets_recursively_and_never_writes_absolute_path(tmp_path: Path):
    output = tmp_path / "voice.wav"
    output.write_bytes(b"wave")
    manifest = build_asset_manifest(
        output,
        tool="studio-audio",
        parameters={
            "api_key": "do-not-save", "nested": {"authorization": "Bearer secret"},
            "prompt": "safe", "max_new_tokens": 1200, "token_budget": 4096,
        },
        technical={"access_token": "do-not-save-either"},
    )
    encoded = json.dumps(manifest)

    assert "do-not-save" not in encoded
    assert "Bearer secret" not in encoded
    assert str(tmp_path) not in encoded
    assert manifest["generation"]["parameters"]["prompt"] == "safe"
    assert manifest["generation"]["parameters"]["max_new_tokens"] == 1200
    assert manifest["generation"]["parameters"]["token_budget"] == 4096


def test_atomic_round_trip_preserves_legacy_fields_and_asset_id(tmp_path: Path):
    output = tmp_path / "still.png"
    output.write_bytes(b"png")
    manifest = build_asset_manifest(output, asset_id="asset_still", tool="studio-image")
    sidecar = write_asset_manifest(
        output, manifest, legacy_fields={"params": {"prompt": "a tower"}, "job_id": "legacy-job"},
    )

    raw = json.loads(sidecar.read_text(encoding="utf-8"))
    loaded = read_asset_manifest(output)
    assert raw["params"]["prompt"] == "a tower"
    assert loaded is not None
    assert loaded["asset"]["id"] == "asset_still"
    assert "params" not in loaded
    assert not list(tmp_path.glob("*.tmp"))


def test_legacy_sidecar_is_adapted_without_being_rewritten(tmp_path: Path):
    output = tmp_path / "legacy.wav"
    output.write_bytes(b"audio")
    legacy = {
        "job_id": "old-job", "generation_mode": "audio", "generation_time": 2.5,
        "created_at": 1_700_000_010,
        "params": {
            "prompt": "himno de guardia", "model_type": "ace_step_v1_5_xl_sft_lm_4b",
            "provider": "local", "seed": 7,
        },
    }
    sidecar = output.with_suffix(".meta.json")
    original = json.dumps(legacy)
    sidecar.write_text(original, encoding="utf-8")

    adapted = read_asset_manifest(output, workspace_id="legacy")
    adapted_again = read_asset_manifest(output, workspace_id="legacy")
    assert adapted is not None
    assert adapted_again is not None
    assert adapted["asset"]["id"] == adapted_again["asset"]["id"]
    assert adapted["asset"]["id"].startswith("asset_legacy_")
    assert adapted["asset"]["kind"] == "audio"
    assert adapted["origin"]["workspace_id"] == "legacy"
    assert adapted["execution"]["job_id"] == "old-job"
    assert adapted["generation"]["prompts"]["effective"] == "himno de guardia"
    assert adapted["timing"]["inference_ms"] == 2_500
    assert sidecar.read_text(encoding="utf-8") == original


def test_invalid_status_is_rejected(tmp_path: Path):
    with pytest.raises(AssetManifestError, match="status"):
        build_asset_manifest(tmp_path / "bad.mp4", status="mysterious")


def test_writer_refuses_to_change_an_existing_asset_identity(tmp_path: Path):
    output = tmp_path / "same.mp4"
    output.write_bytes(b"video")
    write_asset_manifest(
        output, build_asset_manifest(output, asset_id="asset_original", tool="studio-video"),
    )

    with pytest.raises(AssetManifestError, match="asset identity"):
        write_asset_manifest(
            output, build_asset_manifest(output, asset_id="asset_other", tool="studio-video"),
        )


def test_explicit_legacy_adapter_marks_origin(tmp_path: Path):
    manifest = adapt_legacy_sidecar(
        tmp_path / "old.glb", {"params": {"generation_mode": "3d"}},
    )
    assert manifest["asset"]["kind"] == "model3d"
    assert manifest["technical"]["legacy_sidecar"] is True


def test_scene_documents_are_classified_as_scenes():
    assert infer_asset_kind("episode.scene.json") == "scene"


@pytest.mark.parametrize(
    ("legacy", "expected_pipeline_id"),
    [
        ({"director_pipeline_id": "pipe-top"}, "pipe-top"),
        ({"params": {"director_pipeline_id": "pipe-params"}}, "pipe-params"),
        ({"params": {"_director_pipeline_id": "pipe-private"}}, "pipe-private"),
        (
            {
                "pipeline_id": "pipe-canonical",
                "director_pipeline_id": "pipe-director",
            },
            "pipe-canonical",
        ),
    ],
)
def test_legacy_director_sidecar_preserves_pipeline_identity(
    tmp_path: Path,
    legacy: dict,
    expected_pipeline_id: str,
):
    output = tmp_path / "director.mp4"
    output.write_bytes(b"video")

    manifest = adapt_legacy_sidecar(output, legacy)

    assert manifest["execution"]["pipeline_id"] == expected_pipeline_id


def test_generate_publish_writes_canonical_manifest_and_keeps_gallery_keys(tmp_path: Path):
    first = tmp_path / "choir.mp4"
    second = tmp_path / "choir-take-2.mp4"
    first.write_bytes(b"video-a")
    second.write_bytes(b"video-b")
    sidecar = {
        "params": {"prompt": "un coro en la sala de servidores", "model_type": "minimax_h3", "api_key": "secret"},
        "generation_mode": "video",
        "job_id": "job-sim-1",
        "task_id": "task-1",
        "simulated": True,
        "created_at": 1_700_000_100,
    }

    published = publish_generation_sidecar(
        first, sidecar, workspace_id="night-shift", tool="studio",
    )
    raw = json.loads(published.read_text(encoding="utf-8"))
    loaded = read_asset_manifest(first, workspace_id="night-shift")

    assert raw["schema"] == SCHEMA_NAME
    assert raw["params"]["prompt"] == "un coro en la sala de servidores"
    assert raw["job_id"] == "job-sim-1"
    assert "secret" not in published.read_text(encoding="utf-8")
    assert str(tmp_path) not in published.read_text(encoding="utf-8")
    assert loaded is not None
    assert loaded["asset"]["kind"] == "video"
    assert loaded["asset"]["id"].startswith("asset_")
    assert loaded["origin"]["tool"] == "studio"
    assert loaded["origin"]["actor"] == "unknown"
    assert loaded["origin"].get("capability") in (None, "")
    assert loaded["origin"].get("project") is None
    assert loaded["origin"]["workspace_id"] == "night-shift"
    assert loaded["execution"]["mode"] == "simulate"
    assert loaded["execution"]["job_id"] == "job-sim-1"
    assert loaded["technical"]["published_on_generate"] is True
    assert "legacy_sidecar" not in loaded["technical"]

    retry = publish_generation_sidecar(first, sidecar, workspace_id="night-shift", tool="studio")
    other = publish_generation_sidecar(second, sidecar, workspace_id="night-shift", tool="studio")
    assert json.loads(retry.read_text(encoding="utf-8"))["asset"]["id"] == raw["asset"]["id"]
    assert json.loads(other.read_text(encoding="utf-8"))["asset"]["id"] != raw["asset"]["id"]


def test_studio_publish_does_not_invent_user_actor(tmp_path: Path):
    output = tmp_path / "studio.mp4"
    output.write_bytes(b"video")
    publish_generation_sidecar(
        output,
        {"params": {"prompt": "direct studio", "generation_mode": "video"}, "job_id": "studio-1"},
        workspace_id="lab",
        tool="studio",
    )
    loaded = read_asset_manifest(output, workspace_id="lab")
    assert loaded is not None
    assert loaded["origin"]["tool"] == "studio"
    assert loaded["origin"]["actor"] == "unknown"
    assert loaded["origin"].get("capability") in (None, "")
    assert loaded["execution"].get("command_id") in (None, "")
    assert loaded["execution"].get("workflow_id") in (None, "")


def test_director_pipeline_id_attributes_origin_to_director(tmp_path: Path):
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"video")
    publish_generation_sidecar(
        output,
        {
            "params": {
                "prompt": "directed clip",
                "generation_mode": "video",
                "_director_pipeline_id": "pipe-22",
            },
            "job_id": "job-dir",
        },
        workspace_id="lab",
        tool="studio",
    )
    loaded = read_asset_manifest(output, workspace_id="lab")
    assert loaded is not None
    assert loaded["origin"]["tool"] == "director"
    assert loaded["origin"]["actor"] == "unknown"
    assert loaded["origin"].get("project") is None
    assert loaded["origin"].get("production") is None
    assert loaded["execution"]["pipeline_id"] == "pipe-22"


def test_explicit_actor_and_capability_are_preserved(tmp_path: Path):
    output = tmp_path / "wizard.mp4"
    output.write_bytes(b"video")
    publish_generation_sidecar(
        output,
        {"params": {"prompt": "from wizard"}, "actor": "wizard", "capability": "start_generation"},
        workspace_id="lab",
        actor="wizard",
        capability="start_generation",
    )
    loaded = read_asset_manifest(output, workspace_id="lab")
    assert loaded is not None
    assert loaded["origin"]["actor"] == "wizard"
    assert loaded["origin"]["capability"] == "start_generation"


def test_non_finite_metadata_is_normalized_to_valid_json(tmp_path: Path):
    manifest = build_asset_manifest(
        tmp_path / "valid.png", tool="studio-image",
        parameters={"guidance": float("nan"), "strength": float("inf")},
    )
    encoded = json.dumps(manifest, allow_nan=False)
    assert "NaN" not in encoded
    assert manifest["generation"]["parameters"]["guidance"] is None


def test_legacy_workspace_kwarg_is_also_recorded_as_output_folder(tmp_path: Path):
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"video")
    publish_generation_sidecar(
        output,
        {"params": {"prompt": "compat"}, "job_id": "job-1"},
        workspace_id="night-shift",
        tool="studio",
    )
    loaded = read_asset_manifest(output, workspace_id="night-shift")
    assert loaded is not None
    assert loaded["origin"]["workspace_id"] == "night-shift"
    assert loaded["origin"]["output_folder"] == "night-shift"


def test_collection_id_is_distinct_from_output_folder(tmp_path: Path):
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"video")
    publish_generation_sidecar(
        output,
        {"params": {"prompt": "split location", "provider": "local", "model_type": "minimax_h3"}},
        workspace_id="ws_collection_1",
        output_folder="night-shift",
        tool="studio",
        actor="wizard",
        capability="start_generation",
    )
    loaded = read_asset_manifest(output)
    assert loaded is not None
    assert loaded["origin"]["workspace_id"] == "ws_collection_1"
    assert loaded["origin"]["output_folder"] == "night-shift"
    assert loaded["origin"]["actor"] == "wizard"
    assert loaded["generation"]["model"]["provider"] == "local"
    assert loaded["generation"]["model"]["id"] == "minimax_h3"
    proven = provenance_from_manifest(loaded)
    assert proven["actor"] == "wizard"
    assert proven["tool"] == "studio"
    assert proven["provider"] == "local"
    assert proven["model_id"] == "minimax_h3"
    assert proven["workspace_id"] == "ws_collection_1"
    assert proven["output_folder"] == "night-shift"


def test_output_folder_alone_does_not_invent_a_workspace_collection(tmp_path: Path):
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"video")
    location = resolve_generation_location(output_folder="uploads")
    assert location == {"workspace_id": None, "output_folder": "uploads"}
    publish_generation_sidecar(
        output, {"params": {"prompt": "folder only"}}, output_folder="uploads", tool="studio",
    )
    loaded = read_asset_manifest(output)
    assert loaded is not None
    assert loaded["origin"].get("workspace_id") in (None, "")
    assert loaded["origin"]["output_folder"] == "uploads"


def test_sidecar_best_effort_does_not_raise_or_delete_media(tmp_path: Path, monkeypatch):
    output = tmp_path / "keep-me.mp4"
    output.write_bytes(b"video")

    def boom(*_args, **_kwargs):
        raise AssetManifestError("disk full while writing sidecar")

    monkeypatch.setattr(
        "app.services.asset_manifest.write_asset_manifest", boom,
    )
    assert publish_generation_sidecar_best_effort(
        output, {"params": {"prompt": "keep"}}, workspace_id="lab", tool="studio",
    ) is None
    assert output.read_bytes() == b"video"
    assert not (tmp_path / "keep-me.meta.json").is_file()
