"""Use one kept take, or retouch one shot, and re-export only that scene."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.music_production import Production, segments
from services.production_shot_edit import ShotEditError, update_shot, use_take
from services.production_shot_review import record_decision


def _score() -> dict:
    return {"duration": 20, "bpm": 120, "beat": 0.5, "recall": 0.8, "lines": [
        {"t0": 1.0, "t1": 3.0, "text": "hello night"},
        {"t0": 10.0, "t1": 12.0, "text": "cold street"},
    ]}


def _spec(**shot_extra) -> dict:
    return {
        "title": "Night bus",
        "song": {"lyrics": "hello night", "caption": "night", "duration": 20, "bpm": 120},
        "style": {"lyric_style": {"color": "#111111"}},
        "shots": [
            {"key": "s0", "kind": "h3", "line": 0, "frame": "a face", "action": "sings", "seed": 1, **shot_extra},
            {"key": "s1", "kind": "h3", "line": 1, "frame": "a street", "action": "walks", "seed": 2},
        ],
    }


def _build(tmp_path: Path):
    root = tmp_path / "film"
    uploads = tmp_path / "uploads"
    root.mkdir()
    uploads.mkdir()
    (root / "take-a.mp4").write_bytes(b"take-a")
    (root / "take-b.mp4").write_bytes(b"take-b")
    (root / "score.json").write_text(json.dumps(_score()), encoding="utf-8")
    spec = _spec()
    state = {
        "status": "completed",
        "spec": spec,
        "score": "score.json",
        "montage_file": "show.montage.json",
        "clips": {
            "s0": {"file": "take-a.mp4", "qa": {"verdict": "ok", "best_r": 0.4}, "url": "/api/v1/uploads/old.mp4"},
            "s1": {"file": "take-a.mp4", "qa": {"verdict": "ok"}, "url": "/api/v1/uploads/old-s1.mp4"},
        },
        "takes": {"s0": [
            {"file": "take-a.mp4", "verdict": "ok", "r": 0.4},
            {"file": "take-b.mp4", "verdict": "ok", "r": 0.82},
        ]},
        "scenes": {"s1": {"file": "old-s1.mp4", "intent": "export-s1"}},
        "scene_docs": {},
    }
    (root / "show.production.json").write_text(json.dumps(state), encoding="utf-8")
    saved: list[dict] = []
    edits: list[list] = []

    def mcp(tool: str, arguments: dict) -> dict:
        if tool == "scenes.video2d.edit":
            edits.append(arguments["input"]["operations"])
            return {"result": {"document": arguments["input"]["document"]}}
        if tool == "scenes.video2d.validate":
            return {"result": {"warnings": []}}
        if tool == "scenes.document.save":
            return {"result": {"name": "show-s0-abc.scene.json"}}
        if tool == "scenes.video2d.export":
            return {"receipt": {"commandId": "export-s0"}}
        if tool == "scenes.video2d.export.receipt":
            return {"receipt": {"artifacts": [{"name": "show-s0.mp4"}]}}
        if tool == "montages.get":
            return {"result": {"revision": 4, "montage": {"revision": 4, "clips": [
                {"id": "s0", "source": "/api/v1/file/old-s0.mp4?workspace=film", "origin": {"kind": "scene2d", "scene": "old.scene.json"}},
                {"id": "s1", "source": "/api/v1/file/old-s1.mp4?workspace=film", "origin": {"kind": "scene2d", "scene": "old-s1.scene.json"}},
            ]}}}
        if tool == "montages.save":
            saved.append(arguments["input"])
            return {"result": {"file": "show.montage.json", "revision": 5}}
        raise AssertionError(tool)

    production = Production("film", "show", workspace_dir=lambda _name: str(root), uploads_dir=lambda: str(uploads), mcp=mcp)
    return production, spec, root, saved, edits


def test_use_take_replaces_one_montage_clip_and_keeps_the_rest(tmp_path: Path):
    production, spec, root, saved, _edits = _build(tmp_path)
    result = use_take(production, spec, "s0", "take-b.mp4")
    assert result["shot"] == "s0"
    assert result["clip"] == "take-b.mp4"
    assert result["video"] == "show-s0.mp4"
    assert production.state["clips"]["s0"]["file"] == "take-b.mp4"
    assert production.state["clips"]["s1"]["file"] == "take-a.mp4"
    assert (root / "take-a.mp4").read_bytes() == b"take-a"
    assert (root / "take-b.mp4").read_bytes() == b"take-b"
    assert production.state["scenes"]["s1"]["file"] == "old-s1.mp4"
    assert len(saved) == 1
    body = saved[0]
    assert body["expected_revision"] == 4
    clips = {clip["id"]: clip for clip in body["montage"]["clips"]}
    assert clips["s0"]["origin"] == {"kind": "scene2d", "scene": "old.scene.json"}
    assert clips["s0"]["source"] == "/api/v1/file/show-s0.mp4?workspace=film"
    assert clips["s1"]["source"] == "/api/v1/file/old-s1.mp4?workspace=film"
    manifest = json.loads((root / "show.shots.json").read_text(encoding="utf-8"))
    by_key = {row["key"]: row for row in manifest["shots"]}
    assert by_key["s0"]["clip"] == "take-b.mp4"


def test_use_take_exports_the_chosen_scene_once(tmp_path: Path):
    production, spec, _root, _saved, _edits = _build(tmp_path)
    calls: list[str] = []
    inner = production.mcp

    def counting(tool: str, arguments: dict) -> dict:
        calls.append(tool)
        return inner(tool, arguments)

    production.mcp = counting
    use_take(production, spec, "s0", "take-b.mp4")
    assert calls.count("scenes.video2d.export") == 1


def test_missing_take_is_a_stable_error_and_does_not_swap_the_clip(tmp_path: Path):
    production, spec, root, saved, _edits = _build(tmp_path)
    with pytest.raises(ShotEditError) as caught:
        use_take(production, spec, "s0", "take-missing.mp4")
    assert caught.value.code == "take_not_found"
    assert production.state["clips"]["s0"]["file"] == "take-a.mp4"
    assert saved == []
    (root / "ghost.mp4").write_bytes(b"nope")
    production.state["takes"]["s0"].append({"file": "ghost.mp4", "r": 0.1})
    (root / "ghost.mp4").unlink()
    with pytest.raises(ShotEditError) as missing_file:
        use_take(production, spec, "s0", "ghost.mp4")
    assert missing_file.value.code == "take_not_found"
    with pytest.raises(ShotEditError) as escaped:
        use_take(production, spec, "s0", "../take-b.mp4")
    assert escaped.value.code == "take_not_found"
    before = production.state["clips"]["s0"]["file"]
    with pytest.raises(ShotEditError) as unknown:
        use_take(production, spec, "nope", "take-b.mp4")
    assert unknown.value.code == "shot_not_found"
    assert production.state["clips"]["s0"]["file"] == before


def _fail_scene_export(production):
    inner = production.mcp

    def failing(tool: str, arguments: dict) -> dict:
        if tool == "scenes.video2d.export.receipt":
            return {"receipt": {"status": "failed"}}
        return inner(tool, arguments)

    production.mcp = failing


def _disk_state(root: Path) -> dict:
    return json.loads((root / "show.production.json").read_text(encoding="utf-8"))


def test_failed_use_take_does_not_keep_the_new_clip_or_clear_the_scene(tmp_path: Path):
    """export_scene used to save clips=new-take and scenes[shot].file=None before the
    export finished. A 422 then left the montage on the old scene and the JSON swapped."""
    production, spec, root, saved, _edits = _build(tmp_path)
    production.state["scenes"]["s0"] = {"file": "old-s0.mp4", "intent": "export-old"}
    production.save()
    _fail_scene_export(production)
    with pytest.raises(ShotEditError) as caught:
        use_take(production, spec, "s0", "take-b.mp4")
    assert caught.value.code == "scene_export_failed"
    assert production.state["clips"]["s0"]["file"] == "take-a.mp4"
    assert production.state["scenes"]["s0"]["file"] == "old-s0.mp4"
    assert production.state["clips"]["s1"]["file"] == "take-a.mp4"
    assert saved == []
    disk = _disk_state(root)
    assert disk["clips"]["s0"]["file"] == "take-a.mp4"
    assert disk["scenes"]["s0"]["file"] == "old-s0.mp4"


def test_failed_update_does_not_keep_overrides_or_clear_the_scene(tmp_path: Path):
    production, spec, root, saved, _edits = _build(tmp_path)
    production.state["scenes"]["s0"] = {"file": "old-s0.mp4", "intent": "export-old"}
    production.save()
    _fail_scene_export(production)
    with pytest.raises(ShotEditError) as caught:
        update_shot(production, spec, "s0", camera="camera-orbit", lyric_style={"color": "#ABCDEF"})
    assert caught.value.code == "scene_export_failed"
    assert "overrides" not in spec["shots"][0]
    assert production.state["scenes"]["s0"]["file"] == "old-s0.mp4"
    assert production.state["clips"]["s0"]["file"] == "take-a.mp4"
    assert saved == []
    disk = _disk_state(root)
    assert disk["scenes"]["s0"]["file"] == "old-s0.mp4"
    assert "overrides" not in (disk.get("spec") or {}).get("shots", [{}])[0]


def test_rejected_montage_save_does_not_keep_the_new_clip(tmp_path: Path):
    production, spec, root, saved, _edits = _build(tmp_path)
    inner = production.mcp

    def reject(tool: str, arguments: dict) -> dict:
        if tool == "montages.save":
            return {"error": {"code": "revision_conflict"}}
        return inner(tool, arguments)

    production.mcp = reject
    with pytest.raises(ShotEditError) as caught:
        use_take(production, spec, "s0", "take-b.mp4")
    assert caught.value.code == "montage_failed"
    assert production.state["clips"]["s0"]["file"] == "take-a.mp4"
    assert saved == []
    assert _disk_state(root)["clips"]["s0"]["file"] == "take-a.mp4"


def test_update_stores_overrides_and_reexports_only_that_scene(tmp_path: Path):
    production, spec, _root, saved, edits = _build(tmp_path)
    calls: list[str] = []
    inner = production.mcp

    def counting(tool: str, arguments: dict) -> dict:
        calls.append(tool)
        return inner(tool, arguments)

    production.mcp = counting
    result = update_shot(
        production, spec, "s0",
        lyric_style={"color": "#ABCDEF"},
        camera="camera-orbit",
        title={"template": "lower-third-date", "fields": {"date": "MAY", "caption": "NIGHT"}},
    )
    assert result["overrides"]["camera"] == "camera-orbit"
    assert spec["shots"][0]["overrides"]["lyric_style"] == {"color": "#ABCDEF"}
    blob = json.dumps(edits)
    assert "#ABCDEF" in blob
    assert "#111111" not in blob
    assert "camera-orbit" in blob
    assert calls.count("scenes.video2d.export") == 1
    assert len(saved) == 1
    clips = {clip["id"]: clip for clip in saved[0]["montage"]["clips"]}
    assert clips["s1"]["source"] == "/api/v1/file/old-s1.mp4?workspace=film"
    with pytest.raises(ShotEditError) as empty:
        update_shot(production, spec, "s0")
    assert empty.value.code == "empty_update"


def test_scenes_keep_a_locked_shot_in_the_cut(tmp_path: Path):
    production, spec, root, _saved, _edits = _build(tmp_path)
    record_decision(root, "show", "s0", locked=True)
    windows = [
        {**spec["shots"][0], "kind": "h3", "t0": 0.0, "t1": 4.0},
        {**spec["shots"][1], "kind": "h3", "t0": 10.0, "t1": 12.0},
    ]
    production.state.setdefault("scenes", {})["s0"] = {
        "file": "keep-s0.mp4", "dur": 1.0, "clip": "other.mp4", "fingerprint": "stale",
    }
    calls: list[str] = []
    inner = production.mcp

    def counting(tool: str, arguments: dict) -> dict:
        calls.append(tool)
        return inner(tool, arguments)

    production.mcp = counting
    expected = [
        [shot["key"], start, end]
        for shot, start, end in segments(windows, production.score(), lambda key: key in production.state["clips"], [])
    ]
    production.scenes(spec, windows)
    assert production.state["segments"] == expected
    assert [row[0] for row in production.state["segments"]] == ["s0", "s1"]
    assert production.state["scenes"]["s0"]["file"] == "keep-s0.mp4"
    assert production.state["scenes"]["s0"]["fingerprint"] == "stale"
    assert calls.count("scenes.video2d.export") == 1
