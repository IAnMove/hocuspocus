"""Cheap preview: animatic, caption contrast, title cards, dry-run compile, hold after the clip."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services.music_production import Production, ProductionError, command_catalog, command_handlers, status_summary, validate_spec
from services.production_dry_run import dry_run
from services.production_preview import (
    animatic_report, caption_failure, claim_animatic_video, hold_after_clip, measure_caption,
    restore_cut_artifacts, snapshot_cut_artifacts, uncover_titles,
)
from services.production_resume import load_running
from services.production_shot_plan import plan_shots

ROOT = Path(__file__).resolve().parents[1]
RUN = "production.run"


def _song(**extra):
    song = {"lyrics": "one line\ntwo lines", "caption": "pop", "duration": 30, "bpm": 120}
    song.update(extra)
    return song


def _spec(**extra):
    spec = {"title": "Show", "song": _song(), "style": {},
            "shots": [{"key": "s0", "kind": "h3", "line": 0, "frame": "f", "action": "a"}]}
    spec.update(extra)
    return spec


def _pixels(color, size=8):
    from PIL import Image
    image = Image.new("RGB", (size, size), color)
    return image.tobytes(), image.width, image.height


def _band():
    return {"left": 0, "top": 0, "right": 100, "bottom": 100}


def test_black_on_black_fails_and_a_cream_box_passes():
    pixels, width, height = _pixels((0, 0, 0))
    bare = measure_caption(pixels, width, height, [{"id": "lyric", "color": "#000000", "bounds": _band()}])
    failure = caption_failure(bare, "s0")
    assert failure["code"] == "caption_unreadable" and failure["scene"] == "s0" and failure["ratio"] < 3
    boxed = measure_caption(pixels, width, height, [{
        "id": "lyric", "color": "#141210", "bounds": _band(),
        "box": {"color": "#f4efe6", "opacity": 1},
    }])
    assert boxed["ratio"] >= 3 and boxed["against_box"] is True
    assert caption_failure(boxed, "s0") is None


def test_a_faint_box_does_not_hide_black_on_black():
    pixels, width, height = _pixels((0, 0, 0))
    measured = measure_caption(pixels, width, height, [{
        "color": "#000000", "bounds": _band(), "box": {"color": "#f4efe6", "opacity": 0.2},
    }])
    assert caption_failure(measured, "s0")["ratio"] < 3


def test_title_card_on_an_image_validates_and_dry_run_warns():
    shot = {"key": "hero", "kind": "h3", "frame": "f", "action": "a", "line": 0,
            "title": {"template": "title-card", "fields": {"title": "OPEN"}}}
    spec = _spec(shots=[shot])
    assert validate_spec(spec)["shots"][0]["title"]["template"] == "title-card"
    report = dry_run(spec, mcp=lambda *_args: (_ for _ in ()).throw(AssertionError("mcp")))
    assert any(item["code"] == "title_card_on_image" and item["key"] == "hero" for item in report["warnings"])
    screen = _spec(shots=[{"key": "desk", "kind": "screen", "t0": 0, "title": {"template": "title-card", "fields": {"title": "OPEN"}}}])
    assert "title_card_on_image" not in {item["code"] for item in dry_run(screen)["warnings"]}
    end = _spec(shots=[{"key": "end", "kind": "h3", "frame": "f", "action": "a",
                        "title": {"template": "end-card", "fields": {"title": "Bye", "cta": "now"}}}])
    assert "title_card_on_image" not in {item["code"] for item in dry_run(end)["warnings"]}


def test_the_planner_rewrites_a_title_card_on_a_picture(monkeypatch):
    import services.production_shot_plan as plan
    real = plan._card

    def card(*args, **kwargs):
        shot = real(*args, **kwargs)
        shot["title"] = {**shot["title"], "template": "title-card"}
        return shot

    monkeypatch.setattr(plan, "_card", card)
    spec = {"title": "Show", "song": _song(lyrics="[Verse]\nalpha\nbeta"), "style": {}, "stills": {"k": "/api/v1/file/k.png?workspace=preview"}, "shots": "auto"}
    planned = plan_shots(spec)
    pictures = [shot for shot in planned["shots"] if shot.get("kind") in ("h3", "still") and isinstance(shot.get("title"), dict)]
    assert pictures and {shot["title"]["template"] for shot in pictures} == {"lower-third-date"}
    assert uncover_titles([{"key": "desk", "kind": "screen", "title": {"template": "title-card", "fields": {}}}])[0]["title"]["template"] == "title-card"


def test_style_presets_do_not_name_title_card():
    presets = json.loads((ROOT / "app/shared/style_presets.json").read_text(encoding="utf-8"))
    assert "title-card" not in json.dumps(presets)


def test_hold_after_clip_uses_the_h3_bucket_not_eight_seconds():
    window = [{"key": "s0", "kind": "h3", "t0": 0.0, "t1": 30.0}]
    tail = round(30 - 345 / 24, 3)
    assert hold_after_clip(window, 30, []) == [tail]
    assert hold_after_clip(window, 30, [{"kind": "clip", "clip": "s0"}]) == [0.0]
    assert hold_after_clip(window, 30, [{"kind": "h3"}, {"kind": "scene3d"}, {"kind": "screen"}]) == [0.0]
    assert hold_after_clip(window, 30, [{"kind": "still", "still": "k"}]) == [tail]
    assert hold_after_clip(window, 30, [{"kind": "still", "still": "k"}, {"kind": "clip"}]) == [tail]
    assert hold_after_clip([{"key": "k", "kind": "still", "t0": 0.0, "t1": 30.0}], 30, []) == [0.0]


def test_dry_run_puts_hold_on_each_window_and_compiles_without_mcp():
    calls = []

    def mcp(*_args):
        calls.append(_args)
        raise AssertionError("mcp")

    shot = {"key": "s0", "kind": "h3", "line": 0, "frame": "f", "action": "a"}
    report = dry_run(_spec(shots=[shot]), mcp=mcp)
    assert calls == []
    assert report["windows"][0]["hold_after_clip"] > 10
    assert report["motion"]["longest_shot_s"] > 0
    filled = dry_run(_spec(shots=[shot], fill=[{"kind": "still", "still": "k"}]), mcp=mcp)
    assert filled["gaps"] == [] and filled["windows"][0]["hold_after_clip"] > 0
    moving = dry_run(_spec(shots=[shot], fill=[{"kind": "clip", "clip": "s0"}]), mcp=mcp)
    assert moving["windows"][0]["hold_after_clip"] == 0.0
    assert "scene_invalid" not in {item["code"] for item in report["warnings"]}


def test_dry_run_reports_a_title_style_the_editor_would_reject():
    shot = {"key": "s0", "kind": "still", "t0": 0, "still": "k",
            "title": {"template": "lower-third-date", "fields": {"date": "1991", "caption": "hi"}, "style": {"y": 400}}}
    report = dry_run(_spec(title="Short", shots=[shot], song=_song(lyrics="hi", duration=12)))
    invalid = next(item for item in report["warnings"] if item["code"] == "scene_invalid")
    assert invalid["key"] == "s0" and "Text field is out of range" in invalid["message"]
    shot["title"]["style"] = {"notAField": 1}
    unsupported = dry_run(_spec(title="Short", shots=[shot], song=_song(lyrics="hi", duration=12)))
    message = next(item["message"] for item in unsupported["warnings"] if item["code"] == "scene_invalid")
    assert "unsupported fields" in message
    clean = {"key": "s0", "kind": "still", "t0": 0, "still": "k",
             "title": {"template": "lower-third-date", "fields": {"date": "1991", "caption": "hi"}}}
    ok = dry_run(_spec(title="Short", shots=[clean], song=_song(lyrics="hi", duration=12)))
    assert "scene_invalid" not in {item["code"] for item in ok["warnings"]}


def test_animatic_warnings_name_a_cover_a_repeat_and_a_dead_stretch():
    windows = [
        {"key": "a", "kind": "still", "still": "same", "t0": 0.0, "t1": 6.0},
        {"key": "b", "kind": "still", "still": "same", "t0": 6.0, "t1": 12.0,
         "title": {"template": "title-card", "fields": {"title": "OPEN"}}},
    ]
    spec = {"title": "t", "shots": windows, "fill": []}
    codes = {item["code"]: item for item in animatic_report(spec, windows, {"duration": 20, "lines": []}, {})}
    assert codes["title_card_on_image"]["key"] == "b"
    assert codes["image_repeated"]["shots"] == ["a", "b"]
    assert codes["dead_time"]["seconds"] > 10
    frames = [{"key": "s0", "kind": "h3", "t0": 0.0, "t1": 4.0}, {"key": "s1", "kind": "h3", "t0": 4.0, "t1": 8.0}]
    repeated = animatic_report({"shots": frames, "fill": []}, frames, {"duration": 8}, {"frames": {"s0": "one.png", "s1": "one.png"}})
    assert any(item["code"] == "image_repeated" and item["image"] == "one.png" for item in repeated)
    assert not any(item["code"] == "still_reused" for item in repeated)


def test_scenes_stop_on_a_probe_and_on_a_black_frame(tmp_path):
    (tmp_path / "f.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "s.score.json").write_text('{"duration": 8, "beat": 0.5, "lines": [{"t0": 0.2, "t1": 3.0, "text": "hello there"}]}', encoding="utf-8")
    exported = []

    def mcp(tool, arguments):
        if tool == "scenes.video2d.export":
            exported.append(arguments["input"]["document"]["name"])
            return {"receipt": {"commandId": "c"}}
        if tool == "scenes.video2d.export.receipt":
            return {"receipt": {"artifacts": [{"name": "scene.mp4"}]}, "task": {"status": "completed"}}
        raise AssertionError(tool)

    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.edit = lambda doc, ops: doc
    shot = {"key": "s0", "kind": "h3", "i": 0, "t0": 0.0, "t1": 4.0, "frame": "f", "action": "a"}
    production.state = {"score": "s.score.json", "frames": {"s0": "f.png"}, "caption_probe": {"ratio": 1.2, "scene": "s0"}}
    with pytest.raises(ProductionError) as error:
        production.scenes({"style": {}, "shots": []}, [shot])
    assert error.value.code == "caption_unreadable"
    assert "1.2" in str(error.value) and "s0" in str(error.value)
    assert exported == []
    production.state["caption_probe"] = {"ratio": 7, "scene": "s0"}
    production.scenes({"style": {}, "shots": []}, [shot])
    assert exported == ["s0"]


def test_scenes_measure_a_real_frame_and_skip_when_there_is_no_file(tmp_path):
    from PIL import Image
    Image.new("RGB", (16, 16), (0, 0, 0)).save(tmp_path / "f.png")
    (tmp_path / "s.score.json").write_text('{"duration": 8, "beat": 0.5, "lines": [{"t0": 0.2, "t1": 3.0, "text": "hello"}]}', encoding="utf-8")
    exported = []

    def mcp(tool, arguments):
        if tool == "scenes.video2d.export":
            exported.append(tool)
            return {"receipt": {"commandId": "c"}}
        if tool == "scenes.video2d.export.receipt":
            return {"receipt": {"artifacts": [{"name": "scene.mp4"}]}, "task": {"status": "completed"}}
        raise AssertionError(tool)

    shot = {"key": "s0", "kind": "still", "still": "/k.png", "i": 0, "t0": 0.0, "t1": 4.0}
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.edit = lambda doc, ops: doc
    production.state = {"score": "s.score.json", "frames": {"s0": "f.png"}}
    style = {"lyric_style": {"color": "#000000"}}
    with pytest.raises(ProductionError) as error:
        production.scenes({"style": style, "shots": []}, [shot])
    assert error.value.code == "caption_unreadable" and exported == []
    style = {"lyric_style": {"color": "#141210", "box": {"kind": "solid", "color": "#f4efe6", "opacity": 1, "padding": 0.4}}}
    production.scenes({"style": style, "shots": []}, [shot])
    assert exported == ["scenes.video2d.export"]
    production.state = {"score": "s.score.json", "frames": {}}
    exported.clear()
    production.scenes({"style": {"lyric_style": {"color": "#000000"}}, "shots": []}, [shot])
    assert exported == ["scenes.video2d.export"]


def test_animatic_stops_before_clips_and_does_not_look_running(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    called = []
    for name in ("song", "analyze", "cast", "frames", "clips"):
        setattr(production, name, lambda *args, name=name, **kwargs: called.append(name))
    production.animatic = lambda spec, windows: production.state.__setitem__("animatic_video", "preview.mp4")
    production.score = lambda: {"duration": 30, "beat": 0.5, "lines": []}
    production.run(_spec(), through="animatic")
    assert called == ["song", "analyze", "cast", "frames"]
    assert production.state["status"] == "animatic_ready"
    assert production.state.get("final") is None
    assert production.state["animatic_video"] == "preview.mp4"
    assert load_running(production.path) is None
    summary = status_summary(production.state, "ws")
    assert summary["animatic"] == "/api/v1/file/preview.mp4?workspace=ws"
    assert summary["video"] is None


def test_animatic_keeps_a_new_export_off_final_and_leaves_an_old_one(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.score = lambda: {"duration": 8, "beat": 0.5, "lines": []}
    production.scenes = lambda *args, **kwargs: None
    production.montage = lambda spec: production.state.__setitem__("final", "anim.mp4") or production.state.__setitem__("contact_sheet", "sheet.jpg")
    production.animatic({"title": "t", "shots": [], "fill": []}, [])
    assert production.state["animatic_video"] == "anim.mp4"
    assert production.state.get("final") is None
    assert production.state["contact_sheet"] == "sheet.jpg"
    assert "caption_gate" not in production.state
    production.state["final"] = "done.mp4"
    production.montage = lambda spec: None
    production.animatic({"title": "t", "shots": [], "fill": []}, [])
    assert production.state["final"] == "done.mp4"
    assert production.state["animatic_video"] == "anim.mp4"
    production.montage = lambda spec: production.state.__setitem__("final", "anim2.mp4")
    production.animatic({"title": "t", "shots": [], "fill": []}, [])
    assert production.state["final"] == "done.mp4"
    assert production.state["animatic_video"] == "anim2.mp4"


def test_animatic_on_a_completed_run_keeps_the_finished_cut(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    for name in ("song", "analyze", "cast", "frames"):
        setattr(production, name, lambda *args, **kwargs: None)
    production.score = lambda: {"duration": 8, "beat": 0.5, "lines": []}
    production.scenes = lambda *args, **kwargs: None
    production.montage = lambda spec: production.state.__setitem__("final", "anim.mp4")
    production.state.update(status="completed", final="done.mp4")
    production.run(_spec(), through="animatic")
    assert production.state["final"] == "done.mp4"
    assert production.state["animatic_video"] == "anim.mp4"
    assert production.state["status"] == "completed"
    assert production.state["through"] == "animatic"
    summary = status_summary(production.state, "ws")
    assert summary["video"] == "/api/v1/file/done.mp4?workspace=ws"
    assert summary["animatic"] == "/api/v1/file/anim.mp4?workspace=ws"


def test_animatic_failure_on_a_completed_run_keeps_completed_and_final(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    for name in ("song", "analyze", "cast", "frames"):
        setattr(production, name, lambda *args, **kwargs: None)
    production.score = lambda: {"duration": 8, "beat": 0.5, "lines": []}

    def scenes(*_args, **_kwargs):
        production.state.update(status="failed", error="scene_export_failed: s0")

    production.scenes = scenes
    production.montage = lambda spec: production.state.__setitem__("final", "anim.mp4")
    production.state.update(status="completed", final="done.mp4")
    production.run(_spec(), through="animatic")
    assert production.state["final"] == "done.mp4"
    assert production.state["status"] == "completed"
    assert production.state.get("error") is None


def test_animatic_exception_on_a_completed_run_restores_final(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    for name in ("song", "analyze", "cast", "frames"):
        setattr(production, name, lambda *args, **kwargs: None)
    production.score = lambda: {"duration": 8, "beat": 0.5, "lines": []}
    production.scenes = lambda *args, **kwargs: None

    def montage(_spec):
        production.state["final"] = "anim.mp4"
        raise ProductionError("montage_failed", "export job lost")

    production.montage = montage
    production.state.update(status="completed", final="done.mp4")
    production.run(_spec(), through="animatic")
    assert production.state["final"] == "done.mp4"
    assert production.state["animatic_video"] == "anim.mp4"
    assert production.state["status"] == "completed"
    assert production.state.get("error") is None
    assert any("animatic failed" in line for line in production.state["log"])


def test_animatic_exception_on_a_new_run_still_fails(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    for name in ("song", "analyze", "cast", "frames"):
        setattr(production, name, lambda *args, **kwargs: None)
    production.score = lambda: {"duration": 8, "beat": 0.5, "lines": []}
    production.scenes = lambda *args, **kwargs: None
    production.montage = lambda spec: (_ for _ in ()).throw(ProductionError("montage_failed", "export job lost"))
    production.run(_spec(), through="animatic")
    assert production.state["status"] == "failed"
    assert "export job lost" in (production.state.get("error") or "")
    assert production.state.get("final") is None


def _overwrite_cut(production, *, fail=False):
    production.state["final"] = "anim.mp4"
    production.state["montage_file"] = "show.montage.json"
    production.state["contact_sheet"] = "p-contact.jpg"
    (production.root / "show.montage.json").write_text('{"clips":[],"overlays":[]}', encoding="utf-8")
    (production.root / "p-contact.jpg").write_bytes(b"preview-sheet")
    if fail:
        raise ProductionError("montage_failed", "export job lost")


def test_animatic_on_a_completed_run_keeps_the_editable_montage_and_contact_sheet(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    (tmp_path / "show.montage.json").write_text('{"clips":[{"id":"s0"}],"overlays":[{"id":"hand"}]}', encoding="utf-8")
    (tmp_path / "p-contact.jpg").write_bytes(b"finished-sheet")
    production.score = lambda: {"duration": 8, "beat": 0.5, "lines": []}
    production.scenes = lambda *args, **kwargs: None
    production.montage = lambda spec: _overwrite_cut(production)
    production.state.update(status="completed", final="done.mp4",
                            montage_file="show.montage.json", contact_sheet="p-contact.jpg")
    production.animatic({"title": "t", "shots": [], "fill": []}, [])
    assert production.state["final"] == "done.mp4"
    assert production.state["animatic_video"] == "anim.mp4"
    assert production.state["montage_file"] == "show.montage.json"
    assert production.state["contact_sheet"] == "p-contact.jpg"
    assert (tmp_path / "show.montage.json").read_text(encoding="utf-8") == '{"clips":[{"id":"s0"}],"overlays":[{"id":"hand"}]}'
    assert (tmp_path / "p-contact.jpg").read_bytes() == b"finished-sheet"


def test_a_failed_animatic_does_not_keep_preview_bytes_on_a_finished_cut(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    (tmp_path / "show.montage.json").write_text('{"overlays":[{"id":"hand"}]}', encoding="utf-8")
    (tmp_path / "p-contact.jpg").write_bytes(b"finished-sheet")
    production.score = lambda: {"duration": 8, "beat": 0.5, "lines": []}
    production.scenes = lambda *args, **kwargs: None
    production.montage = lambda spec: _overwrite_cut(production, fail=True)
    production.state.update(final="done.mp4", montage_file="show.montage.json", contact_sheet="p-contact.jpg")
    with pytest.raises(ProductionError, match="export job lost"):
        production.animatic({"title": "t", "shots": [], "fill": []}, [])
    assert production.state["montage_file"] == "show.montage.json"
    assert production.state["contact_sheet"] == "p-contact.jpg"
    assert (tmp_path / "show.montage.json").read_text(encoding="utf-8") == '{"overlays":[{"id":"hand"}]}'
    assert (tmp_path / "p-contact.jpg").read_bytes() == b"finished-sheet"


def test_snapshot_skips_missing_cut_files_so_a_first_animatic_keeps_its_sheet(tmp_path):
    state = {"montage_file": "missing.montage.json", "contact_sheet": "sheet.jpg"}
    assert snapshot_cut_artifacts(tmp_path, state) == {}
    (tmp_path / "sheet.jpg").write_bytes(b"preview")
    state["contact_sheet"] = "sheet.jpg"
    kept = snapshot_cut_artifacts(tmp_path, state)
    state["contact_sheet"] = "other.jpg"
    restore_cut_artifacts(tmp_path, state, kept)
    assert state["contact_sheet"] == "sheet.jpg"
    assert (tmp_path / "sheet.jpg").read_bytes() == b"preview"


def test_resume_after_animatic_reuses_frames_and_reaches_clips(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path),
                            mcp=lambda tool, arguments: (_ for _ in ()).throw(AssertionError(tool)))
    called = []
    for name in ("song", "analyze", "cast", "clips", "scenes", "package", "montage"):
        setattr(production, name, lambda *args, name=name, **kwargs: called.append(name))
    production.score = lambda: {"duration": 12, "beat": 0.5, "bpm": 120, "lines": [{"t0": 1, "t1": 3, "text": "hi"}]}
    production.state["frames"] = {"s0": "kept.png"}
    production.state["status"] = "animatic_ready"
    production.run(_spec())
    assert called[:3] == ["song", "analyze", "cast"] and "clips" in called
    assert production.state["frames"] == {"s0": "kept.png"}


def test_an_animatic_still_is_reexported_when_the_clip_arrives(tmp_path):
    score = {"duration": 6.0, "beat": 0.5, "lines": []}
    (tmp_path / "s.score.json").write_text(json.dumps(score), encoding="utf-8")
    exported = []

    def mcp(tool, arguments):
        if tool == "scenes.video2d.export":
            exported.append(arguments["input"]["document"]["name"])
            return {"receipt": {"commandId": "c"}}
        return {"receipt": {"artifacts": [{"name": "scene.mp4"}]}}

    shot = {"key": "s0", "kind": "h3", "i": 0, "t0": 0.0, "t1": 4.0, "frame": "f", "action": "a"}
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.edit = lambda doc, ops: doc
    from services.music_production import scene_fingerprint
    production.state = {"score": "s.score.json", "frames": {"s0": "kept.png"},
                        "clips": {"s0": {"file": "take.mp4", "url": "/api/v1/file/take.mp4?workspace=ws"}},
                        "scenes": {"s0": {"dur": 6.0, "file": "still.mp4", "clip": None,
                                          "fingerprint": scene_fingerprint(shot, {}, {}, score, 0.0, 6.0)}}}
    production.scenes({"style": {}, "shots": [], "fill": []}, [shot])
    assert exported == ["s0"]
    assert production.state["scenes"]["s0"]["clip"] == "take.mp4"


def test_run_logs_a_title_card_and_still_stops_at_frames(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    for name in ("song", "analyze", "cast", "frames", "clips"):
        setattr(production, name, lambda *args, **kwargs: None)
    production.score = lambda: {"duration": 30, "beat": 0.5, "lines": []}
    shot = {"key": "hero", "kind": "h3", "frame": "f", "action": "a", "title": {"template": "title-card", "fields": {"title": "OPEN"}}}
    production.run(_spec(shots=[shot]), through="frames")
    assert production.state["status"] == "frames_ready"
    assert any("title card covers the image on hero" in line for line in production.state["log"])


def test_through_animatic_is_a_stage_and_anything_else_is_rejected(tmp_path, monkeypatch):
    enum = next(item["inputSchema"]["properties"]["input"]["properties"]["through"]["enum"]
                for item in command_catalog() if item["name"] == RUN)
    assert enum == ["all", "frames", "animatic"]
    started = {}

    class FakeThread:
        def __init__(self, target, args, name, daemon):
            started["args"] = args

        def start(self):
            started["started"] = True

        def is_alive(self):
            return False

    monkeypatch.setattr("services.music_production.threading.Thread", FakeThread)
    monkeypatch.setattr("services.music_production.require_free_disk", lambda *_args: None)
    handlers = command_handlers(lambda _ws: str(tmp_path), lambda: str(tmp_path), lambda: "http://127.0.0.1:9", lambda: "token")
    payload = {"version": 1, "input": {"workspace": "ws", "production_id": "preview", "spec": _spec(), "through": "animatic"}}
    result = asyncio.run(handlers[RUN](payload))
    assert result["result"]["running"] is True and started["args"][2] == "animatic" and started["started"] is True
    payload["input"]["through"] = "clips"
    with pytest.raises(Exception) as error:
        asyncio.run(handlers[RUN](payload))
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "invalid_stage"
    state = {"final": "old.mp4"}
    claim_animatic_video(state, "old.mp4")
    assert state == {"final": "old.mp4"}
    claim_animatic_video(state, None)
    assert state["animatic_video"] == "old.mp4" and "final" not in state
    replaced = {"final": "anim.mp4"}
    claim_animatic_video(replaced, "done.mp4")
    assert replaced == {"final": "done.mp4", "animatic_video": "anim.mp4"}
