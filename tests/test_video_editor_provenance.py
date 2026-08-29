from __future__ import annotations

import json
from pathlib import Path

from app.services.video_editor import build_source_provenance_manifest


def test_source_manifest_embeds_scene_prompt_audio_and_model_without_local_path(tmp_path: Path):
    source = tmp_path / "scene-shot.mp4"
    source.write_bytes(b"video")
    sidecar = source.with_suffix(".meta.json")
    sidecar.write_text(json.dumps({
        "generation_mode": "video",
        "tool": "scene-animator-3d",
        "params": {
            "prompt": "Luma hears a soup signal",
            "model_type": "scene-compositor",
            "audio_tracks": [{"source": "luma-line.wav", "model": "qwen3_tts_voicedesign"}],
            "scene": {"name": "The signal", "layers": [{"id": "luma"}]},
            "scene_recipe": {"version": 1, "shots": []},
        },
    }), encoding="utf-8")

    manifest = build_source_provenance_manifest([{
        "name": "Opening shot",
        "source": "scene-shot.mp4",
        "resolved_path": str(source),
    }])

    entry = manifest["clips"][0]
    assert manifest["version"] == 1
    assert entry["sidecar_status"] == "embedded"
    assert entry["resolved_filename"] == "scene-shot.mp4"
    assert entry["metadata"]["params"]["prompt"] == "Luma hears a soup signal"
    assert entry["metadata"]["params"]["audio_tracks"][0]["model"] == "qwen3_tts_voicedesign"
    assert str(tmp_path) not in json.dumps(manifest)


def test_source_manifest_records_missing_and_unreadable_sidecars_without_failing(tmp_path: Path):
    missing = tmp_path / "legacy.mp4"
    broken = tmp_path / "broken.mp4"
    broken.with_suffix(".meta.json").write_text("{not-json", encoding="utf-8")

    manifest = build_source_provenance_manifest([
        {"source": "legacy.mp4", "resolved_path": str(missing)},
        {"source": "broken.mp4", "resolved_path": str(broken)},
    ])

    assert [entry["sidecar_status"] for entry in manifest["clips"]] == ["missing", "unreadable"]


def test_source_manifest_drops_nested_manifest_from_an_assembled_source(tmp_path: Path):
    source = tmp_path / "earlier-master.mp4"
    source.with_suffix(".meta.json").write_text(json.dumps({
        "params": {
            "video_editor": {
                "version": 2,
                "clips": [{"source": "shot.mp4"}],
                "source_manifest": {"version": 1, "clips": [{"metadata": {"huge": True}}]},
            },
            "source": "video_editor",
        },
    }), encoding="utf-8")

    manifest = build_source_provenance_manifest([{
        "source": "earlier-master.mp4",
        "resolved_path": str(source),
    }])

    editor = manifest["clips"][0]["metadata"]["params"]["video_editor"]
    assert editor["clips"] == [{"source": "shot.mp4"}]
    assert "source_manifest" not in editor
