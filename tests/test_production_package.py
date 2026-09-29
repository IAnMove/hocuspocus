"""A finished production can be opened and retouched shot by shot: scene documents, montage origins, manifest."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException

from services.music_production import Production, command_handlers, status_summary
from services.production_disk import kept_names, release_completed
from services.production_package import (attach_origins, clip_replacements, contrast_warnings, doc_digest, durable_document, editable_summary,
                                         lyric_for, manifest_rows, workspace_url)
from services.video2d_edit import edit


def test_documents_point_at_workspace_files_not_the_temporary_uploads():
    clips = {"a": {"file": "a take.mp4", "url": "/api/v1/uploads/tmp1.mp4"}, "b": {"file": None, "url": "/api/v1/uploads/tmp2.mp4"}}
    swap = clip_replacements(clips, "my ws")
    assert swap == {"/api/v1/uploads/tmp1.mp4": "/api/v1/file/a%20take.mp4?workspace=my%20ws"}
    document = {"layers": [{"id": "bg", "source": "/api/v1/uploads/tmp1.mp4"}, {"id": "x", "source": "/examples/hero.png"}]}
    durable = durable_document(document, swap)
    assert durable["layers"][0]["source"] == workspace_url("a take.mp4", "my ws") and durable["layers"][1]["source"] == "/examples/hero.png"
    assert document["layers"][0]["source"] == "/api/v1/uploads/tmp1.mp4"        # the original is untouched
    assert doc_digest(document) == doc_digest(json.loads(json.dumps(document))) != doc_digest(durable)


def test_montage_clips_get_their_shot_scene_and_lyric():
    montage = {"clips": [{"id": "intro", "name": "intro"}, {"id": "other", "name": "other"}]}
    docs = {"intro": {"scene": "p-intro-1.scene.json", "lyric": "Hush / the lights", "note": "slow push in · seed 11"}}
    assert attach_origins(montage, docs, "voices") == 2
    assert montage["clips"][0]["origin"] == {"kind": "scene2d", "productionId": "voices", "shotId": "intro", "scene": "p-intro-1.scene.json",
                                              "note": "slow push in · seed 11"}
    assert montage["clips"][0]["lyric"] == "Hush / the lights" and "origin" not in montage["clips"][1]
    assert attach_origins(montage, docs, "voices") == 0                          # idempotent


def test_lyric_for_lists_the_lines_that_sound_in_the_shot():
    lines = [{"t0": 1, "t1": 3, "text": "a"}, {"t0": 5, "t1": 7, "text": "b"}, {"t0": 8, "t1": 9, "text": "c"}]
    assert lyric_for(lines, 2, 6) == "a / b" and lyric_for(lines, 3, 5) == "" and lyric_for(lines, 0, 100) == "a / b / c"


def _state():
    return {"clips": {"a": {"file": "a2.mp4", "qa": {"verdict": "ok", "best_r": 0.4}, "url": "/u/a2.mp4"}}, "frames": {"a": "a.png"},
            "scenes": {"a": {"file": "a-scene.mp4"}},
            "takes": {"a": [{"file": "a1.mp4", "take": 1, "verdict": "retake", "r": 0.1, "drive": "mix"},
                            {"file": "a2.mp4", "take": 2, "verdict": "ok", "r": 0.4, "drive": "vocals"}]}}


def test_the_manifest_lists_every_take_and_where_to_open_the_shot():
    shot = {"key": "a", "kind": "h3", "sing": True, "frame": "wide", "action": "sings", "seed": 12, "cast": ["hero"]}
    rows = manifest_rows(_state(), {}, [(shot, 0.0, 4.0)], {"lines": [{"t0": 1, "t1": 2, "text": "hello"}]}, {"a": {"scene": "s.scene.json", "warnings": []}})
    row = rows[0]
    assert row["lyric"] == "hello" and row["sung"] is True and row["scene_doc"] == "s.scene.json" and row["scene_video"] == "a-scene.mp4"
    assert [take["file"] for take in row["takes"]] == ["a1.mp4", "a2.mp4"] and row["takes"][1]["r"] == 0.4
    assert row["clip"] == "a2.mp4" and row["start_frame"] == "a.png" and row["seed"] == 12


def test_a_completed_run_keeps_every_take_for_editing(tmp_path):
    for name in ("a1.mp4", "a2.mp4", "gone.mp4", "p-slice-a-0.wav"):
        (tmp_path / name).write_bytes(b"x")
    state = {**_state(), "status": "completed", "discarded": ["a1.mp4", "gone.mp4"], "final": "v.mp4", "song": {"file": "s.wav"}}
    assert {"a1.mp4", "a2.mp4"} <= kept_names(state)
    release_completed(tmp_path, state, "p")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["a1.mp4", "a2.mp4"]        # the loser that is no take and the slice went


def _production(tmp_path, calls, validate=None):
    (tmp_path / "s.score.json").write_text(json.dumps({"duration": 12.0, "beat": 0.5, "lines": [{"t0": 1.0, "t1": 3.0, "text": "hello there"}]}))

    def mcp(tool, arguments):
        calls.append((tool, arguments))
        if tool == "scenes.video2d.edit":
            return edit(arguments)
        if tool == "scenes.document.save":
            return {"result": {"name": f"{arguments['input']['name']}-{len(calls)}.scene.json"}}
        if tool == "scenes.video2d.validate":
            return {"result": {"warnings": validate or []}}
        return {}

    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.state.update(score="s.score.json", song={"file": "s.wav"}, clips={"a": {"file": "a.mp4", "qa": {"verdict": "ok"}, "url": "/api/v1/uploads/t.mp4"}},
                            takes={"a": [{"file": "a.mp4", "take": 1, "verdict": "ok", "r": None}]}, scenes={"a": {"file": "scene-a.mp4", "dur": 6.0}})
    return production


SPEC = {"title": "Song", "song": {"lyrics": "hello there", "caption": "pop", "duration": 12, "bpm": 120}, "style": {},
        "shots": [{"key": "a", "kind": "h3", "line": 0, "frame": "wide", "action": "moves", "seed": 5}]}


def test_package_saves_a_durable_scene_document_and_a_manifest_per_shot(tmp_path):
    calls: list = []
    production = _production(tmp_path, calls, validate=[{"code": "text_low_contrast", "path": "texts[0]"}, {"code": "other"}])
    windows = [{"key": "a", "kind": "h3", "line": 0, "frame": "wide", "action": "moves", "seed": 5, "i": 0, "t0": 0.75, "t1": 3.2}]
    production.package(SPEC, windows)
    save = next(arguments for tool, arguments in calls if tool == "scenes.document.save")
    document = save["input"]["document"]
    assert save["input"]["workspace"] == "ws" and save["input"]["name"] == "p-a"
    assert any(layer["source"] == "/api/v1/file/a.mp4?workspace=ws" for layer in document["layers"])
    assert any(text["text"].lower().startswith("hello") for text in document["texts"])
    saved = production.state["scene_docs"]["a"]
    assert saved["scene"].startswith("p-a-") and saved["lyric"] == "hello there" and saved["warnings"] == [{"code": "text_low_contrast", "path": "texts[0]"}]
    manifest = json.loads((tmp_path / "p.shots.json").read_text())
    assert manifest["production_id"] == "p" and manifest["shots"][0]["scene_doc"] == saved["scene"] and manifest["shots"][0]["takes"][0]["file"] == "a.mp4"
    assert editable_summary(production.state) == {"montage": None, "manifest": "p.shots.json", "scene_docs": 1, "warnings": 1}
    assert status_summary(production.state, "ws")["editable"]["manifest"] == "p.shots.json"
    before = len(calls)
    production.package(SPEC, windows)
    assert not any(tool == "scenes.document.save" for tool, _ in calls[before:])       # unchanged documents are not saved again


def test_one_failing_shot_does_not_stop_the_package(tmp_path):
    calls: list = []
    production = _production(tmp_path, calls)
    real = production.mcp
    production.mcp = lambda tool, arguments: {} if tool == "scenes.document.save" else real(tool, arguments)
    production.package(SPEC, [{"key": "a", "kind": "h3", "line": 0, "frame": "f", "action": "a", "i": 0, "t0": 0.75, "t1": 3.2}])
    assert "a" not in production.state["scene_docs"] and (tmp_path / "p.shots.json").exists()
    assert any(line.startswith("package a:") for line in production.state["log"])


def test_repackage_gives_an_old_production_scene_documents_and_montage_origins(tmp_path):
    calls: list = []
    production = _production(tmp_path, calls)
    production.state.update(status="completed", final="v.mp4", montage_file="song.montage.json", error="URLError: an old failure")
    real = production.mcp

    def mcp(tool, arguments):
        if tool.startswith("montages."):
            calls.append((tool, arguments))
        if tool == "montages.get":
            return {"result": {"revision": 3, "montage": {"clips": [{"id": "a", "name": "a"}]}}}
        if tool == "montages.save":
            return {"result": {"file": "song.montage.json"}}
        return real(tool, arguments)

    production.mcp = mcp
    production.repackage({**SPEC, "shots": [{"key": "a", "kind": "h3", "line": 0, "frame": "wide", "action": "moves"}]})
    save = next(arguments for tool, arguments in calls if tool == "montages.save")
    clip = save["input"]["montage"]["clips"][0]
    assert save["input"]["expected_revision"] == 3 and clip["origin"]["shotId"] == "a" and clip["origin"]["scene"].startswith("p-a-")
    assert production.state["status"] == "completed" and production.state["error"] is None
    assert not any(tool in ("scenes.video2d.export", "generate", "montages.export") for tool, _ in calls)      # no GPU, no render


def test_the_run_handler_packages_only_a_finished_production(tmp_path, monkeypatch):
    (tmp_path / "busy.production.json").write_text(json.dumps({"status": "running", "spec": SPEC}))
    handlers = command_handlers(lambda _ws: str(tmp_path), lambda: str(tmp_path), lambda: "http://x", lambda: "t")
    with pytest.raises(HTTPException) as error:
        asyncio.run(handlers["production.run"]({"version": 1, "input": {"workspace": "w", "production_id": "busy", "package": True}}))
    assert error.value.detail["code"] == "not_finished"


def test_contrast_warnings_keep_only_what_a_viewer_would_notice():
    mcp = lambda tool, arguments: {"result": {"warnings": [{"code": "text_low_contrast", "path": "texts[1]"}, {"code": "empty_timespan"}]}}
    assert contrast_warnings(mcp, {}) == [{"code": "text_low_contrast", "path": "texts[1]"}]
    assert contrast_warnings(lambda tool, arguments: 1 / 0, {}) == []
