"""Resume of an H3 shot: what a changed input redoes, and what an upgrade must not redo.

A production keeps ``h3_sources`` (two hashes), the clip's audio window and the scene record. A spec edited between two
runs redraws exactly the frame, shoots exactly the clip and exports exactly the scene that depend on the edit, each
with a new job id (the journal answers a repeated one with the old job). A production made before an input was
recorded, resumed with the same spec, makes nothing again.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from services.music_production import Production, scene_fingerprint, segments
from services.production_shot_sources import changed_parts, moved_since_shot, recipe_parts, stale_reasons

SCORE = {"duration": 12.0, "beat": 0.5, "lines": [], "vocals_file": None}


def _legacy(*parts):
    """The digest ``forget_changed_shots`` kept before the recipe parts (development at 844565b83)."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _shot(**extra):
    shot = {"key": "a", "kind": "h3", "i": 0, "frame": "wide shot", "action": "waves", "camera": "camera-dolly",
            "cast": [], "t0": 1.0, "t1": 4.0}
    shot.update(extra)
    return shot


class _Run:
    """A production whose image, H3 and scene jobs are recorded; each job finishes with a file named after it."""

    def __init__(self, tmp_path, monkeypatch):
        self.sent: list[tuple[str, dict]] = []
        (tmp_path / "s.score.json").write_text(json.dumps(SCORE))
        self.production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=self._mcp)
        self.production.upload = lambda name: (f"/up/{name}", f"/api/v1/uploads/{name}")
        self.production.edit = lambda doc, ops: doc
        self.production.wait = lambda jobs, poll=6: {key: f"{job}.png" if job.startswith("img") else f"{job}.mp4" for key, job in jobs.items()}
        self.production.state.update(score="s.score.json", song={"file": "song.wav"})
        monkeypatch.setattr("services.production_stage_clips.subprocess.run", lambda args, **_kwargs: None)
        monkeypatch.setattr("services.production_clip_qa.clip_qa", lambda *args: {"verdict": "ok", "best_r": 0.7})

    def _mcp(self, tool, arguments):
        self.sent.append((tool, arguments))
        job = len(self.sent)
        if tool == "generation.image":
            return {"receipt": {"result": {"job_id": f"img{job}"}}}
        if tool == "generate":
            return {"job_id": f"vid{job}"}
        if tool == "scenes.video2d.export":
            return {"receipt": {"commandId": f"c{job}"}}
        return {"receipt": {"artifacts": [{"name": f"scene{job}.mp4"}]}}

    def calls(self, tool: str) -> list[dict]:
        return [arguments for name, arguments in self.sent if name == tool]

    def restart(self) -> None:
        """What a server restart does to the saved state: everything goes through JSON."""
        saved = json.loads(json.dumps(self.production.state))
        self.production.state.clear()
        self.production.state.update(saved)

    def stages(self, spec: dict, windows: list[dict]) -> None:
        self.production.cast(spec)
        self.production.frames(spec, windows)
        self.production.clips(spec, windows, pause=0)
        self.production.scenes(spec, windows)


def _spec(**extra):
    spec = {"style": {"image": "look", "video": "painterly", "image_model": "qwen_image_21", "image_steps": 40}, "cast": [], "shots": []}
    spec.update(extra)
    return spec


def test_a_production_made_before_the_recipe_parts_makes_nothing_again_with_the_same_spec(tmp_path, monkeypatch):
    run = _Run(tmp_path, monkeypatch)
    production = run.production
    spec = _spec(cast=[{"id": "hero", "sheet_prompt": "a singer"}])
    windows = [_shot(cast=["hero"]), {"key": "b", "kind": "still", "still": "/k.png", "i": 1, "t0": 4.0, "t1": 8.0}]
    # What development recorded for this production: two hashes and no parts, a clip with no window, no cast_sources.
    production.state.update(cast={"hero": "/u/sheet.png"}, cast_single={"hero": "/u/portrait.png"})
    frame = _legacy(production.frame_prompt(spec, windows[0]), None, ["hero"])
    clip = _legacy(frame, "waves", "camera-dolly", False)
    shots = segments(windows, SCORE, lambda key: key == "a", [])
    prior = {key: {"dur": round(end - start, 3), "file": f"old-{key}.mp4", "clip": "old-a.mp4" if key == "a" else None,
                   "fingerprint": scene_fingerprint(shot, {"image": "look", "video": "painterly", "image_model": "qwen_image_21",
                                                           "image_steps": 40}, {}, SCORE, start, end)} for shot, start, end in shots
             for key in [shot["key"]]}
    production.state.update(
        frames={"a": "old-a.png"}, h3_sources={"a": {"frame": frame, "clip": clip}},
        clips={"a": {"file": "old-a.mp4", "url": "/u/old-a.mp4", "qa": {"verdict": "ok"}, "model": "minimax_h3_fused_turbo", "steps": 4}},
        scenes=prior,
    )
    run.stages(spec, windows)
    assert [(tool, arguments.get("intent_id")) for tool, arguments in run.sent if tool in ("generation.image", "generate", "scenes.video2d.export")] == []
    assert production.state["frames"] == {"a": "old-a.png"} and production.state["clips"]["a"]["file"] == "old-a.mp4"
    assert "obsolete" not in production.state["clips"]["a"]
    # The pass learned the parts, so the next edit is seen.
    assert production.state["h3_sources"]["a"]["parts"]["video_look"] == "painterly"
    assert production.state["clips"]["a"]["window"] == [1.0, 4.0]


def test_a_changed_image_model_redraws_the_frame_and_shoots_the_clip_with_new_jobs(tmp_path, monkeypatch):
    run = _Run(tmp_path, monkeypatch)
    spec, windows = _spec(), [_shot()]
    run.stages(spec, windows)
    first = run.production.state["clips"]["a"]["file"]
    first_intent = run.calls("generation.image")[0]["intent_id"]
    assert len(run.calls("generation.image")) == 1 and len(run.calls("generate")) == 1
    run.restart()
    run.stages(spec, windows)
    assert len(run.calls("generation.image")) == 1 and len(run.calls("generate")) == 1, "the same spec makes nothing again"
    run.restart()
    changed = {**spec, "style": {**spec["style"], "image_model": "flux2_klein_9b", "image_steps": 4}}
    run.stages(changed, windows)
    drawn = run.calls("generation.image")
    assert len(drawn) == 2 and drawn[1]["input"]["params"]["model_type"] == "flux2_klein_9b"
    assert drawn[1]["intent_id"] != first_intent, "the journal would answer the old intent with the old picture"
    assert len(run.calls("generate")) == 2 and run.production.state["clips"]["a"]["file"] != first
    assert run.production.state["frames"]["a"] != "img1.png"


def test_steps_alone_redraw_the_frame_and_one_shots_own_model_redraws_only_that_shot(tmp_path, monkeypatch):
    run = _Run(tmp_path, monkeypatch)
    spec, windows = _spec(), [_shot(), _shot(key="b", i=1, t0=5.0, t1=8.0, frame="close shot")]
    run.stages(spec, windows)
    assert len(run.calls("generation.image")) == 2
    run.restart()
    run.stages({**spec, "style": {**spec["style"], "image_steps": 20}}, windows)
    assert len(run.calls("generation.image")) == 4 and len(run.calls("generate")) == 4
    run.restart()
    run.stages({**spec, "style": {**spec["style"], "image_steps": 20}}, [{**windows[0], "image_model": "flux2_klein_9b"}, windows[1]])
    drawn = run.calls("generation.image")
    assert len(drawn) == 5 and drawn[4]["input"]["params"]["model_type"] == "flux2_klein_9b"
    assert len(run.calls("generate")) == 5, "only shot a is shot again"


def test_a_changed_video_look_shoots_the_clip_again_and_keeps_the_frame(tmp_path, monkeypatch):
    run = _Run(tmp_path, monkeypatch)
    spec, windows = _spec(), [_shot()]
    run.stages(spec, windows)
    first, first_file = run.calls("generate")[0], run.production.state["clips"]["a"]["file"]
    run.restart()
    run.stages({**spec, "style": {**spec["style"], "video": "handheld documentary"}}, windows)
    assert len(run.calls("generation.image")) == 1, "the start frame is still the same picture"
    shot_again = run.calls("generate")
    assert len(shot_again) == 2 and "handheld documentary" in shot_again[1]["params"]["prompt"]
    assert shot_again[1]["request_id"] != first["request_id"]
    assert run.production.state["clips"]["a"]["file"] != first_file
    assert len(run.calls("scenes.video2d.export")) == 2, "the new clip is exported again"


def test_a_changed_clip_size_shoots_the_clip_again_and_a_frame_size_redraws_the_frame(tmp_path, monkeypatch):
    run = _Run(tmp_path, monkeypatch)
    spec, windows = _spec(), [_shot()]
    run.stages(spec, windows)
    run.restart()
    run.stages({**spec, "resolution": {"clips": "1024x576"}}, windows)
    assert len(run.calls("generation.image")) == 1 and len(run.calls("generate")) == 2
    assert run.calls("generate")[1]["params"]["resolution"] == "1024x576"
    run.restart()
    run.stages({**spec, "resolution": {"clips": "1024x576", "frames": "1536x1024"}}, windows)
    assert len(run.calls("generation.image")) == 2 and run.calls("generation.image")[1]["input"]["params"]["resolution"] == "1536x1024"
    assert len(run.calls("generate")) == 3


def test_naming_the_default_size_is_not_a_change(tmp_path, monkeypatch):
    run = _Run(tmp_path, monkeypatch)
    spec, windows = _spec(), [_shot()]
    run.stages(spec, windows)
    run.restart()
    run.stages({**spec, "resolution": {"frames": "1280x704", "clips": "1280x704"}}, windows)
    assert len(run.calls("generation.image")) == 1 and len(run.calls("generate")) == 1
    assert "obsolete" not in run.production.state["clips"]["a"]


def test_a_moved_audio_window_shoots_the_clip_again_with_a_new_job(tmp_path, monkeypatch):
    run = _Run(tmp_path, monkeypatch)
    spec = _spec()
    run.stages(spec, [_shot()])
    assert run.production.state["clips"]["a"]["window"] == [1.0, 4.0]
    assert run.production.state["takes"]["a"][0]["window"] == [1.0, 4.0]
    run.restart()
    run.stages(spec, [_shot(t0=5.0, t1=8.0)])
    assert len(run.calls("generation.image")) == 1 and len(run.calls("generate")) == 2
    assert run.production.state["clips"]["a"]["window"] == [5.0, 8.0]


def test_small_moves_of_the_window_add_up_until_the_clip_is_shot_again(tmp_path, monkeypatch):
    """The recorded window is the one the clip was shot against, so 0.3 s four times is a 1.2 s move."""
    run = _Run(tmp_path, monkeypatch)
    spec = _spec()
    run.stages(spec, [_shot()])
    steps = []
    for index in range(1, 5):
        run.restart()
        shifted = _shot(t0=1.0 + 0.3 * index, t1=4.0 + 0.3 * index)
        run.production.frames(spec, [shifted])
        steps.append(bool(run.production.state["clips"]["a"].get("obsolete")))
        assert run.production.state["clips"]["a"]["window"] == [1.0, 4.0], "never refreshed by a resume"
    assert steps == [False, True, True, True]


def test_a_clip_made_before_its_window_was_recorded_learns_it_and_sees_later_moves(tmp_path, monkeypatch):
    run = _Run(tmp_path, monkeypatch)
    spec, shot = _spec(), _shot()
    run.production.state.update(frames={"a": "a.png"}, clips={"a": {"file": "a.mp4", "url": "/u/a.mp4"}})
    run.production.frames(spec, [shot])
    assert run.production.state["clips"]["a"]["window"] == [1.0, 4.0] and "obsolete" not in run.production.state["clips"]["a"]
    run.production.frames(spec, [{**shot, "t0": 6.0, "t1": 9.0}])
    assert run.production.state["clips"]["a"]["obsolete"] is True
    assert run.sent == []


def test_a_song_switch_that_does_not_move_the_window_keeps_an_edit_flag(tmp_path, monkeypatch):
    """The resume that saw the edit already stored the new inputs, so the flag on the clip is the only trace of it:
    ``production.song.use`` clears the flags of clips whose window it did not move, but not one an edit set."""
    from services.production_song_switch import mark_moved_clips
    run = _Run(tmp_path, monkeypatch)
    spec, windows = _spec(), [_shot()]
    run.stages(spec, windows)
    edited = {**spec, "style": {**spec["style"], "video": "handheld documentary"}}
    run.restart()
    run.production.frames(edited, windows)          # the run stops here (a frame failed, a cancel) before the clips
    assert run.production.state["clips"]["a"]["obsolete"] is True
    assert mark_moved_clips(run.production.state, {"a": (1.0, 4.0)}, {"a": (1.1, 4.1)}) == []
    run.restart()
    run.stages(edited, windows)
    assert len(run.calls("generate")) == 2, "the clip is shot with the new look"
    state = run.production.state
    from services.production_stage_frames import forget_shots_using_cast
    state["cast_dirty"] = ["hero"]
    forget_shots_using_cast(run.production, [_shot(cast=["hero"])])
    mark_moved_clips(state, {"a": (1.0, 4.0)}, {"a": (1.0, 4.0)})
    assert state["clips"]["a"]["obsolete"] is True, "nor one a cast redraw set"
    state["clips"]["a"] = {**state["clips"]["a"], "obsolete": True, "obsolete_by": None}      # a song switch's flag
    mark_moved_clips(state, {"a": (1.0, 4.0)}, {"a": (1.0, 4.0)})
    assert "obsolete" not in state["clips"]["a"], "a song-switch flag is still cleared when the windows did not move"


def test_a_scene2d_plate_follows_the_image_but_not_the_video_look(tmp_path, monkeypatch):
    run = _Run(tmp_path, monkeypatch)
    spec = _spec()
    plate = {"key": "p", "kind": "scene2d", "i": 0, "frame": "an empty alley", "scene2d": {"template": "music-pinball"}, "t0": 1.0, "t1": 4.0}
    run.production.frames(spec, [plate])
    run.restart()
    run.production.frames({**spec, "style": {**spec["style"], "video": "something else"}}, [plate])
    assert len(run.calls("generation.image")) == 1
    run.restart()
    run.production.frames({**spec, "style": {**spec["style"], "image_model": "flux2_klein_9b", "image_steps": 4}}, [plate])
    assert len(run.calls("generation.image")) == 2


def test_the_recorded_parts_survive_a_json_round_trip(tmp_path, monkeypatch):
    spec, shot = _spec(), _shot()
    parts = recipe_parts(spec, shot)
    assert parts == {"image": ["qwen_image_21", 40], "frame_size": "1280x704", "video_look": "painterly", "clip_size": "1280x704"}
    assert changed_parts({"parts": json.loads(json.dumps(parts))}, recipe_parts(spec, shot)) == []
    assert changed_parts({"frame": "x"}, parts) == [], "a record with no parts learns them"
    assert changed_parts({"parts": {"video_look": "old"}}, parts) == ["video_look"], "a part that was never held is not a change"
    assert set(recipe_parts(spec, {"kind": "scene2d"})) == {"image", "frame_size"}


def test_a_window_that_was_not_timed_never_counts_as_moved():
    assert moved_since_shot({"window": [1.0, 4.0]}, {"kind": "h3"}) is False
    assert moved_since_shot({"file": "a.mp4"}, _shot(t0=9.0, t1=12.0)) is False
    assert moved_since_shot({"window": [1.0, 4.0]}, _shot(t0=1.3, t1=4.3)) is False
    assert moved_since_shot({"window": [1.0, 4.0]}, _shot(t0=1.31, t1=4.0)) is True
    reasons = stale_reasons({"frame": "f", "clip": "c"}, {"frame": "f", "clip": "c", "parts": {}}, _shot(), {"window": [0.0, 3.0]})
    assert reasons == (None, "its audio window moved")


def test_the_recipe_parts_do_not_change_the_legacy_digests(tmp_path, monkeypatch):
    run, spec = _Run(tmp_path, monkeypatch), _spec()
    windows = [_shot()]
    run.production.frames(spec, windows)
    record = run.production.state["h3_sources"]["a"]
    frame = _legacy(run.production.frame_prompt(spec, windows[0]), None, [])
    assert record["frame"] == frame and record["clip"] == _legacy(frame, "waves", "camera-dolly", False)


SAVED = Path(__file__).resolve().parent / "fixtures" / "production_saved_by_development_844565b83.json"
_GPU = ("generation.image", "generate", "image.remove_background")


class _Saved:
    """The production development 844565b83 saved (two H3 shots with cast; scene2d cards on a URL background, on a set,
    on a drawn plate and one with a leftover H3 take; a still), resumed by ``production.run`` on this code."""

    def __init__(self, tmp_path, monkeypatch):
        from PIL import Image
        saved = json.loads(SAVED.read_text(encoding="utf-8"))
        for name in saved["files"]:
            Image.new("RGB", (16, 16), (90, 40, 20)).save(tmp_path / name) if name.endswith(".png") else (tmp_path / name).write_bytes(b"\0" * 64)
        (tmp_path / "s.score.json").write_text(json.dumps(saved["score"]))
        (tmp_path / "p.montage.json").write_text(json.dumps(saved["montage"]))
        (tmp_path / "p.production.json").write_text(json.dumps(saved["state"]))
        self.raw, self.root, self.sent = saved["spec"], tmp_path, []
        for module in ("services.production_stage_clips", "services.production_stage_scenes"):
            monkeypatch.setattr(f"{module}.subprocess.run", lambda args, **_kwargs: None)
        monkeypatch.setattr("services.production_clip_qa.clip_qa", lambda *args: {"verdict": "ok", "best_r": 0.7})
        monkeypatch.setattr("services.music_production.make_frames_sheet", lambda root, frames, name: name)
        monkeypatch.setattr("services.music_production.time.sleep", lambda _seconds: None)

    def _mcp(self, tool, arguments):
        self.sent.append((tool, arguments))
        data, n = arguments.get("input") or {}, len(self.sent)
        if tool == "scenes.video2d.export":
            return {"receipt": {"commandId": f"exp{n}"}}
        if tool == "scenes.video2d.export.receipt":
            (self.root / f"{data['intent_id']}.mp4").write_bytes(b"\0")
            return {"receipt": {"status": "completed", "artifacts": [{"name": f"{data['intent_id']}.mp4"}]}, "task": {"status": "completed"}}
        if tool in ("scenes.video2d.edit", "montages.get"):
            return {"result": {"document": data.get("document"), "revision": 1}}
        if tool == "montages.save":
            return {"result": {"file": data.get("file"), "revision": 2}}
        if tool == "montages.export":
            return {"result": {"job": {"job_id": "m1"}}}
        if tool == "montages.export.status":
            return {"result": {"job": {"status": "completed", "filename": "final.mp4"}}}
        if tool in _GPU:
            raise AssertionError(f"a resume with the same spec sent {tool}")
        return {"result": {}}

    def resume(self) -> list[str]:
        from services.music_production import validate_spec
        production = Production("ws", "p", workspace_dir=lambda _: str(self.root), uploads_dir=lambda: str(self.root), mcp=self._mcp)
        production.subject_detector, production.frame_times = None, lambda path: None
        self.sent.clear()
        production.run(validate_spec(self.raw))
        self.state = production.state
        return sorted(arguments["input"]["document"]["name"] for tool, arguments in self.sent if tool == "scenes.video2d.export")


def test_a_production_saved_by_development_resumes_without_a_new_picture_clip_or_cutout(tmp_path, monkeypatch):
    """Upgrade guard on a state written by development's own code, not built by hand. Only the two documented CPU
    re-exports happen once: the card that names a set (its key now holds the set) and the card that still carries a
    leftover H3 take (its key is now what the card is made of). A second resume exports nothing."""
    run = _Saved(tmp_path, monkeypatch)
    exported = run.resume()
    state = run.state
    assert state["status"] == "completed", state.get("error")
    assert exported == ["c2", "lf"]
    assert [tool for tool, _arguments in run.sent if tool in (*_GPU, "scenes.template.compile")] == []
    assert state["frames"] == {"h1": "dev-img11.png", "h2": "dev-img12.png", "c3": "dev-img13.png"}
    assert {key: clip["file"] for key, clip in state["clips"].items()} == {"h1": "dev-vid17.mp4", "h2": "dev-vid18.mp4", "lf": "old-h3-lf.mp4"}
    assert not any(clip.get("obsolete") for clip in state["clips"].values())
    assert set(state["h3_sources"]["h1"]["parts"]) == {"image", "frame_size", "video_look", "clip_size"}
    assert set(state["h3_sources"]["c3"]["parts"]) == {"image", "frame_size"}
    assert state["clips"]["h1"]["window"] == [0.75, 3.7] and set(state["cast_sources"]) == {"hero", "pal"}
    assert {key: scene.get("tempo") for key, scene in state["scenes"].items() if key.startswith(("c", "lf"))} == \
        {"c1": 120.0, "c2": 120.0, "c3": 120.0, "lf": 120.0}
    assert run.resume() == [] and state["status"] == "completed"
