"""Video 2D music cards as production shots: validation, sources, frames, cutouts, scene document, dry run and gate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import production_scene2d as scene2d
from services.music_production import SPEC_SCHEMA, Production, ProductionError, shot_windows, validate_spec
from services.production_dry_run import dry_run
from services.production_quality_gate import blocking_problems, plan_warnings
from services.video2d_edit import edit

NODE = pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "ui/node_modules/tsx/dist/cli.mjs").is_file(),
                          reason="UI dependencies not installed in Python-only CI")
SUBJECT, PLATE = "/api/v1/file/lia.png?workspace=ws", "/api/v1/file/plaza.png?workspace=ws"


def shot(template="music-pinball", key="s1", **fields):
    config = {"template": template, "cast": {"subject_1": SUBJECT}, "background": PLATE}
    config.update(fields.pop("scene2d", {}))
    return {"key": key, "kind": "scene2d", "t0": 0, "scene2d": config, **fields}


def spec(*shots, **extra):
    return {"title": "2D", "song": {"lyrics": "one\ntwo\nthree", "caption": "synth pop", "duration": 30, "bpm": 100},
            "style": {}, "shots": list(shots), **extra}


def refused(item) -> ProductionError:
    with pytest.raises(ProductionError) as caught:
        validate_spec(spec(item))
    return caught.value


def test_a_music_card_validates_and_the_schema_lists_the_kind():
    validate_spec(spec(shot()))
    kinds = SPEC_SCHEMA["properties"]["shots"]["anyOf"][1]["items"]["properties"]["kind"]["enum"]
    assert "scene2d" in kinds and "scene2d" in SPEC_SCHEMA["properties"]["shots"]["anyOf"][1]["items"]["properties"]


def test_an_unknown_card_is_refused_by_the_compilers_own_check():
    error = refused(shot("music-nope"))
    assert error.code == "invalid_spec" and "template_unknown" in str(error)


@pytest.mark.parametrize("template", ["cinema-tracking", "space-broadside", "city-postcard"])
def test_a_card_of_another_family_is_refused(template):
    error = refused(shot(template))
    assert error.code == "scene2d_family_not_allowed" and template in str(error)


@pytest.mark.parametrize("template, cast", [("music-satellite-swarm", {"subject_1": SUBJECT, "prop_1": SUBJECT}),
                                            ("music-ricochet-pass", {"subject_1": SUBJECT, "prop_1": SUBJECT})])
def test_an_alias_of_a_music_card_is_accepted(template, cast):
    validate_spec(spec(shot(template, scene2d={"cast": cast})))


def test_an_alias_of_another_family_is_refused_after_the_compiler_resolves_it(monkeypatch):
    real = scene2d._prepare
    monkeypatch.setattr(scene2d, "_prepare", lambda data, workspace_dir=None: {**real({**data, "templateId": "music-pinball"}), "templateId": "cinema-tracking"})
    error = refused(shot("music-parallax"))
    assert error.code == "scene2d_family_not_allowed" and "cinema-tracking" in str(error)


def test_an_unknown_slot_names_the_cards_slots():
    error = refused(shot(scene2d={"cast": {"hero_x": SUBJECT}}))
    assert "hero_x is not a slot of music-pinball (subject_1, background, prop_1)" in str(error)


def test_a_missing_slot_is_named():
    assert "music-high-five needs subject_2" in str(refused(shot("music-high-five")))


@pytest.mark.parametrize("controls, words", [({"bpm": 999}, "control bpm"), ({"nope": 1}, "control nope"),
                                             ({"duration": 4}, "cut sets the duration")])
def test_bad_controls_are_refused(controls, words):
    assert words in str(refused(shot(scene2d={"controls": controls})))


@pytest.mark.parametrize("change, words", [
    ({"camera": "camera-push-in"}, "own camera"),
    ({"sing": True}, "does not lip-sync"),
    ({"scene2d": {"background": None}}, "needs a background"),
    ({"scene2d": {"cast": {"background": PLATE}}}, "as scene2d.background"),
    ({"scene2d": {"extra": 1}}, "give {template, cast, background, controls}"),
])
def test_shot_fields_a_card_cannot_honour_are_refused(change, words):
    item = shot(**{key: value for key, value in change.items() if key != "scene2d"})
    item["scene2d"] = {key: value for key, value in {**item["scene2d"], **change.get("scene2d", {})}.items() if value is not None}
    assert words in str(refused(item))


def test_a_still_or_a_frame_prompt_is_a_background():
    bare = {"template": "music-pinball", "cast": {"subject_1": SUBJECT}}
    with_still, with_frame = {**shot(still="keyart"), "scene2d": bare}, {**shot(key="s2"), "scene2d": bare, "frame": "a plaza"}
    validate_spec(spec(with_still, with_frame, stills={"keyart": PLATE}))
    assert scene2d.draws_frame(with_frame) and not scene2d.draws_frame(with_still)
    assert not scene2d.draws_frame(shot(frame="a plaza")) and not scene2d.draws_frame({"kind": "h3", "frame": "x"})


def test_a_fill_shot_is_checked_too():
    with pytest.raises(ProductionError):
        validate_spec(spec(shot(), fill=[shot("cinema-reveal", key="f")]))


class Run:
    """A production the scene2d code drives: state, a workspace folder and a scripted MCP."""
    ws, id = "ws", "p"

    def __init__(self, root: Path, replies=None):
        self.root, self.state, self.calls, self.replies, self.lines = root, {}, [], replies or {}, []

    def mcp(self, tool, arguments):
        self.calls.append((tool, arguments))
        reply = self.replies.get(tool)
        return reply(arguments) if callable(reply) else reply or {}

    def save(self):
        pass

    def log(self, line):
        self.lines.append(line)


def card_document(arguments):
    data = arguments["input"]
    layers = [{"id": slot, "name": slot, "type": "image", "source": source, "visible": True, "z": index,
               "transform": {"x": 50, "y": 50, "scale": 1, "rotation": 0, "opacity": 1}}
              for index, (slot, source) in enumerate(sorted(data["assets"].items()))]
    document = {"version": 1, "name": "card", "width": 1920, "height": 1080, "fps": 24, "duration": data.get("duration", 4),
                "layers": layers, "texts": [], "narrative": {"templateId": data["templateId"]}}
    return {"result": {"document": document, "warnings": []}}


def test_the_scene_starts_from_the_compiled_card_with_resolved_sources_and_the_song_tempo(tmp_path):
    (tmp_path / "plaza.png").write_bytes(b"png")
    run = Run(tmp_path, {scene2d.COMPILE: card_document})
    run.state = {"cast": {"lia": "/api/v1/uploads/sheet.png"}, "cast_cutouts": {"lia": {"source": "x", "url": "/api/v1/file/lia-cut.png?workspace=ws"}}}
    item = shot(scene2d={"cast": {"subject_1": "lia"}, "background": "plaza.png", "controls": {"intensity": 0.9}})
    document = scene2d.scene2d_document(run, item, 1.6, {"bpm": 96}, {})
    [(tool, arguments)] = run.calls
    data = arguments["input"]
    assert tool == "scenes.template.compile" and data["full"] is True
    assert data["assets"] == {"subject_1": "/api/v1/file/lia-cut.png?workspace=ws", "background": "/api/v1/file/plaza.png?workspace=ws"}
    assert data["controls"] == {"intensity": 0.9, "bpm": 96.0} and (data["width"], data["height"], data["fps"]) == (1920, 1080, 24)
    assert data["duration"] == 3.0, "a cut shorter than the card's shortest move compiles at that and is trimmed"
    assert document["name"] == "s1" and document["duration"] == 1.6 and len(document["layers"]) == 2
    scene2d.scene2d_document(run, item, 1.6, {"bpm": 96}, {})
    assert len(run.calls) == 1, "a package or a resume does not compile the same card again"
    scene2d.scene2d_document(run, {**item, "scene2d": {**item["scene2d"], "controls": {"bpm": 140}}}, 20, {"bpm": 96}, {})
    assert run.calls[-1][1]["input"]["controls"] == {"bpm": 140} and run.calls[-1][1]["input"]["duration"] == 12.0


def test_a_drawn_frame_is_the_background_and_a_missing_one_stops_the_scene(tmp_path):
    run = Run(tmp_path, {scene2d.COMPILE: card_document})
    item = {**shot(), "scene2d": {"template": "music-pinball", "cast": {"subject_1": SUBJECT}}, "frame": "an empty plaza"}
    with pytest.raises(ProductionError) as caught:
        scene2d.scene2d_document(run, item, 4, {}, {})
    assert caught.value.code == "scene2d_background_missing"
    run.state["frames"] = {"s1": "p-frame-s1.png"}
    scene2d.scene2d_document(run, item, 4, {}, {})
    assert run.calls[-1][1]["input"]["assets"]["background"] == "/api/v1/file/p-frame-s1.png?workspace=ws"
    before = scene2d.scene_inputs(run.state, item)
    run.state["frames"]["s1"] = "p-frame-s1-r1.png"
    assert scene2d.scene_inputs(run.state, item) != before, "a redrawn background exports the scene again"


def test_a_remade_set_or_model_changes_the_reexport_key():
    item = shot(scene2d={"cast": {"subject_1": "lia"}, "background": "alley"})
    state = {"cast_cutouts": {"lia": {"url": "/api/v1/file/lia-cut.png?workspace=ws"}},
             "sets": {"alley": {"url": "/api/v1/file/alley-v1.png?workspace=ws"},
                      "other": {"url": "/api/v1/file/other.png?workspace=ws"}},
             "models": {"hero": {"file": "hero-v1.glb"}}}
    before = scene2d.scene_inputs(state, item)
    state["sets"]["other"]["url"] = "/api/v1/file/other-v2.png?workspace=ws"
    assert scene2d.scene_inputs(state, item) == before, "a set the shot does not name stays out of the key"
    state["sets"]["alley"]["url"] = "/api/v1/file/alley-v2.png?workspace=ws"
    assert scene2d.scene_inputs(state, item) != before, "a remade background set exports the scene again"
    modeled = shot(scene2d={"cast": {"subject_1": "hero"}, "background": PLATE})
    first = scene2d.scene_inputs({"models": {"hero": {"file": "hero-v1.glb"}}}, modeled)
    second = scene2d.scene_inputs({"models": {"hero": {"file": "hero-v2.glb"}}}, modeled)
    assert first != second, "a remade model used as a cast source exports the scene again"


def test_a_failed_compile_stops_the_scene_with_its_reply(tmp_path):
    run = Run(tmp_path, {scene2d.COMPILE: {"_is_error": True, "error": {"code": "template_bad_asset"}}})
    with pytest.raises(ProductionError) as caught:
        scene2d.scene2d_document(run, shot(), 4, {}, {})
    assert caught.value.code == "scene2d_compile_failed" and "template_bad_asset" in str(caught.value)


def test_unknown_names_fail_before_any_compile(tmp_path):
    run = Run(tmp_path, {scene2d.COMPILE: card_document})
    with pytest.raises(ProductionError, match="not a URL"):
        scene2d.scene2d_document(run, shot(scene2d={"background": "nowhere.png"}), 4, {}, {})
    assert run.calls == []


def test_cast_members_are_cut_out_once_and_a_refusal_stops_the_run(tmp_path):
    reply = {"result": {"file": "lia-cut.png", "url": "/api/v1/file/lia-cut.png?workspace=ws"}}
    run = Run(tmp_path, {scene2d.CUTOUT: reply})
    run.state = {"cast": {"lia": "/api/v1/uploads/sheet.png", "bo": "/api/v1/uploads/bo.png"}, "cast_single": {"lia": "/api/v1/uploads/lia.png"}}
    plan = spec(shot(scene2d={"cast": {"subject_1": "lia"}}), cast=[{"id": "lia", "sheet_prompt": "x"}, {"id": "bo", "sheet_prompt": "y"}])
    assert scene2d.cast_ids(plan) == ["lia"]
    scene2d.make_cutouts(run, plan)
    scene2d.make_cutouts(run, plan)
    [(tool, arguments)] = run.calls
    assert tool == "image.remove_background" and arguments["input"] == {"workspace": "ws", "source": "/api/v1/uploads/lia.png",
                                                                       "method": "auto", "crop": True}
    assert run.state["cast_cutouts"]["lia"]["url"] == "/api/v1/file/lia-cut.png?workspace=ws"
    assert scene2d.production_media(run, {})["cast"] == {"lia": "/api/v1/file/lia-cut.png?workspace=ws", "bo": "/api/v1/uploads/bo.png"}
    failing = Run(tmp_path, {scene2d.CUTOUT: {"_is_error": True, "error": {"code": "invalid_image"}}})
    failing.state = {"cast": {"lia": "/api/v1/uploads/sheet.png"}}
    with pytest.raises(ProductionError) as caught:
        scene2d.make_cutouts(failing, plan)
    assert caught.value.code == "scene2d_cutout_failed"


def _image_run(tmp_path):
    calls = []

    def mcp(tool, arguments):
        if tool == "generation.image":
            calls.append(arguments)
            return {"receipt": {"result": {"job_id": f"job{len(calls)}"}}}
        return {}

    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.wait = lambda jobs, poll=6: {key: f"{key}.png" for key in jobs}
    return production, calls


def test_the_frames_stage_draws_an_empty_set_for_a_scene2d_shot_that_needs_one(tmp_path):
    production, calls = _image_run(tmp_path)
    plan = {"style": {"image": "Anime look. Two characters smile."}, "cast": []}
    drawn = {**shot(key="d"), "scene2d": {"template": "music-pinball", "cast": {"subject_1": SUBJECT}}, "frame": "a neon rooftop"}
    production.frames(plan, [drawn, shot(key="given", frame="ignored")])
    assert production.state["frames"] == {"d": "d.png"} and len(calls) == 1
    prompt = calls[0]["input"]["params"]["prompt"]
    assert "a neon rooftop" in prompt and "nobody" in prompt and "characters smile" not in prompt and "image_refs" not in calls[0]["input"]["params"]


def test_the_scene_is_the_card_plus_the_shots_title_and_finish(tmp_path):
    from services.production_stage_scenes import scene_document
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=lambda tool, arguments: (
        card_document(arguments) if tool == scene2d.COMPILE else {"result": edit(arguments)["result"]}))
    item = shot(title={"template": "lower-third-date", "fields": {"date": "1999", "caption": "rooftop"}})
    document = scene_document(production, item, 2, 6, {"lines": [], "bpm": 120}, {}, {"finish": {"preset": "warmCinema"}}, {})
    assert [layer["id"] for layer in document["layers"]] == ["background", "subject_1"], "no production camera or picture layer"
    assert document["texts"] and document["finish"] and document["duration"] == 4


@NODE
def test_a_real_compile_of_one_scene2d_shot_is_a_2d_scene_document(tmp_path):
    from services.production_stage_scenes import scene_document
    from services.video2d_compile import execute

    def mcp(tool, arguments):
        if tool == scene2d.COMPILE:
            return execute({**arguments, "operation": tool})
        return {"result": edit(arguments)["result"]}

    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    item = shot(title={"template": "chorus-banner", "fields": {"line": "Hocus pocus"}})
    document = scene_document(production, item, 10, 15, {"lines": [], "bpm": 110}, {}, {}, {})
    ids = {layer["id"] for layer in document["layers"]}
    assert {"background", "subject_1"} <= ids and document["duration"] == 5 and document["width"] == 1920 and document["fps"] == 24
    assert document["narrative"]["templateId"] == "music-pinball" and document["narrative"]["controls"]["bpm"] == 110
    moving = next(layer for layer in document["layers"] if layer["id"] == "subject_1")
    assert moving["source"] == SUBJECT and len(moving["animation"]["keyframes"]) > 2
    assert document["texts"] and production.state["scene2d"]["s1"]["card"] == "music-pinball"


def test_the_dry_run_shows_the_card_its_sources_and_the_compilers_warnings(tmp_path, monkeypatch):
    real = scene2d._prepare
    # The compiler's real warning shape: a structured row, not text (a dry run once showed its code as "{'code'").
    alpha = {"code": "cutout_without_alpha", "slot": "subject_1", "message": "subject_1 has no transparent pixel"}
    monkeypatch.setattr(scene2d, "_prepare", lambda data, workspace_dir=None: {**real(data, workspace_dir), "warnings": [alpha]})
    (tmp_path / "plaza.png").write_bytes(b"png")
    cast = {**shot(), "scene2d": {"template": "music-pinball", "cast": {"subject_1": "lia"}, "background": "plaza.png"}}
    broken = {**shot(key="s2"), "t0": 6, "scene2d": {"template": "music-pinball", "cast": {"subject_1": SUBJECT}, "background": "missing.png"}}
    drawn = {**shot(key="s3"), "t0": 10, "frame": "a sky",
             "scene2d": {"template": "music-satellite-swarm", "cast": {"subject_1": "keyart", "prop_1": SUBJECT}}}
    report = dry_run(spec(cast, broken, drawn, cast=[{"id": "lia", "sheet_prompt": "x"}], stills={"keyart": PLATE}), root=tmp_path, workspace="ws")
    first, second, third = (row["scene2d"] for row in report["windows"])
    assert first["card"] == "music-pinball" and first["sources"] == {"subject_1": "cast lia: its cutout, made in the run",
                                                                    "background": "/api/v1/file/plaza.png?workspace=ws"}
    assert second == {"template": "music-pinball"}
    assert third["sources"]["subject_1"] == PLATE and third["sources"]["background"].startswith("frame")
    codes = [(item["code"], item.get("key")) for item in report["warnings"]]
    assert ("cutout_without_alpha", "s1") in codes and ("scene2d_invalid", "s2") in codes
    assert next(item for item in report["warnings"] if item["code"] == "cutout_without_alpha")["detail"] == "subject_1"
    assert ("scene2d_holds", "s3") in codes, "the last cut runs 20 s, past the card's longest move"
    assert not any(item["code"] == "few_clips" for item in report["warnings"]), "a scene2d shot is a moving shot"


def test_the_gate_warns_template_still_from_the_derived_traits(tmp_path, monkeypatch):
    traits = tmp_path / "traits.json"
    monkeypatch.setattr(scene2d, "TRAITS", traits)
    plan = spec(shot(), shot("music-trampoline", key="s2"), shot("music-orbit-duel", key="bad"))
    assert not any(item["code"] == "template_still" for item in plan_warnings(plan)), "no traits file, no warning"
    traits.write_text(json.dumps({"version": 1, "templates": {"music-pinball": {"still": True, "holdShare": 0.8},
                                                              "music-trampoline": {"still": False},
                                                              "music-orbit-duel": {"still": True}}}))
    [warning] = [item for item in plan_warnings(plan) if item["code"] == "template_still"]
    assert warning["template"] == "music-pinball" and warning["shots"] == ["s1"]


def test_a_full_frame_title_over_a_scene2d_shot_hides_it():
    item = shot(title={"template": "title-card", "fields": {"title": "Hocus"}})
    assert any(problem["code"] == "title_card_hides_shot" for problem in blocking_problems(spec(item)))
    assert not any(item["code"] == "ignored_shot_field" for item in plan_warnings(spec(shot())))


def test_scene2d_cuts_sit_on_the_frame_clock_and_a_redo_redraws_only_a_drawn_background():
    from services.production_frame_clock import align_native_cuts
    assert align_native_cuts([(shot(), 0.0, 1.01), (shot(key="b"), 1.01, 2.0)]) == [(shot(), 0.0, 1.0), (shot(key="b"), 1.0, 2.0)]
    assert scene2d.redo_origin(shot()) == "scene"
    assert scene2d.redo_origin({**shot(), "scene2d": {"template": "music-pinball"}, "frame": "a plaza"}) == "frame"


def test_a_scene2d_fill_is_a_pad_template_and_two_cards_are_two_shots():
    from services.production_shot_plan import _pad_template
    from services.production_treatment import _signature
    fill = {"kind": "scene2d", "scene2d": {"template": "music-pinball", "cast": {"subject_1": SUBJECT}, "background": PLATE}}
    assert _pad_template({"fill": [fill]}, {}, []) == fill
    assert _signature(shot()) != _signature(shot("music-trampoline"))


def test_a_scene2d_shot_refuses_a_camera_override(tmp_path):
    from services.production_shot_edit import ShotEditError, update_shot
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=lambda *_: {})
    with pytest.raises(ShotEditError, match="own camera"):
        update_shot(production, spec(shot()), "s1", camera="camera-push-in")


def test_a_frame_redo_of_a_scene2d_shot_exports_its_scene_with_the_new_background(monkeypatch):
    from services import production_shot_commands as commands
    drawn = {**shot(), "scene2d": {"template": "music-pinball", "cast": {"subject_1": SUBJECT}}, "frame": "a plaza", "t0": 0}
    exported, framed = [], []

    class Stub:
        def score(self):
            return {"duration": 8, "beat": 0.5, "lines": []}

        def frames(self, plan, windows):
            framed.extend(window["frame"] for window in windows)

    monkeypatch.setattr(commands, "_export_scene", lambda production, plan, key: exported.append(key))
    commands._shoot_frame(Stub(), spec(drawn), "s1", "a plaza at dawn")
    commands._shoot_frame(Stub(), spec({**drawn, "kind": "h3", "action": "waves"}), "s1", None)
    assert framed == ["a plaza at dawn", "a plaza"] and exported == ["s1"], "an H3 frame waits for its clip"


def test_a_malformed_scene2d_is_a_dry_run_warning_not_a_crash():
    item = {**shot(), "scene2d": {"template": "music-pinball", "cast": ["lia"], "controls": [1]}}
    report = dry_run(spec(item))
    assert report["windows"][0]["scene2d"] == {"template": "music-pinball"}
    assert [warning["code"] for warning in report["warnings"] if warning["code"].startswith("scene2d")] == ["scene2d_invalid"]
    assert scene2d.card_of(item) is None


@pytest.mark.parametrize("item, mode", [(shot(), "scene"), ({**shot(), "scene2d": {"template": "music-pinball"}, "frame": "a plaza"}, "frame")])
def test_the_shared_view_regenerates_a_scene2d_shot_from_its_drawn_background_or_its_scene(tmp_path, item, mode):
    from services.production_shot_actions import perform
    (tmp_path / "clip1.production.json").write_text(json.dumps({"status": "completed", "spec": {"title": "Clip", "shots": [item]}}))
    (tmp_path / "clip1.shots.json").write_text(json.dumps({"revision": 3, "shots": [{"key": "s1", "clip": "s1.mp4"}]}))
    result = perform(str(tmp_path), "film", "clip1", "s1", {"action": "regenerate", "expected_revision": 3})
    assert result["regeneration"]["body"]["from"] == mode


def test_the_run_cuts_the_played_cast_out_after_the_clips_and_before_the_scenes(tmp_path, monkeypatch):
    plan = validate_spec(spec(shot(scene2d={"cast": {"subject_1": "lia"}}), cast=[{"id": "lia", "sheet_prompt": "a singer"}]))
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=lambda *_: {})
    stages = []
    for name in ("song", "analyze", "cast", "frames", "clips", "scenes", "package"):
        setattr(production, name, lambda *_, stage=name: stages.append(stage))
    production.score = lambda: {"duration": 30, "lines": []}
    production.montage = lambda *_: production.state.update(final="p.mp4")
    monkeypatch.setattr(scene2d, "make_cutouts", lambda *_: stages.append("cutouts"))
    production.run(plan)
    assert production.state["status"] == "completed"
    assert stages.index("clips") < stages.index("cutouts") < stages.index("scenes")
    stages.clear()
    production.run(validate_spec(spec(shot())))
    assert "cutouts" not in stages, "no cast id played, nothing to cut out"


def test_a_shot_edit_rebuilds_the_card_scene_and_records_what_a_resume_compares(tmp_path):
    from services.production_shot_edit import reexport_shot
    from services.production_stage_scenes import export_scenes
    (tmp_path / "score.json").write_text(json.dumps({"duration": 8, "bpm": 120, "beat": 0.5, "lines": []}))
    drawn = {**shot(), "scene2d": {"template": "music-pinball", "cast": {"subject_1": SUBJECT}}, "frame": "a plaza"}
    plan = spec(drawn)
    replies = {
        scene2d.COMPILE: card_document,
        "scenes.video2d.edit": lambda arguments: {"result": edit(arguments)["result"]},
        "scenes.video2d.validate": lambda arguments: {"result": {"warnings": []}},
        "scenes.document.save": lambda arguments: {"result": {"name": "p-s1.scene.json"}},
        "scenes.video2d.export": lambda arguments: {"receipt": {"commandId": "export-s1"}},
        "scenes.video2d.export.receipt": lambda arguments: {"receipt": {"artifacts": [{"name": "p-s1.mp4"}]}},
        "montages.get": lambda arguments: {"result": {"revision": 1, "montage": {"revision": 1, "clips": [{"id": "s1", "source": "old.mp4"}]}}},
        "montages.save": lambda arguments: {"result": {"file": "p.montage.json", "revision": 2}},
    }
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path),
                            mcp=lambda tool, arguments: replies[tool](arguments))
    production.state.update(spec=plan, score="score.json", status="completed", frames={"s1": "p-frame-s1.png"}, montage_file="p.montage.json")
    reexport_shot(production, plan, "s1")
    record = production.state["scenes"]["s1"]
    assert record["clip"] == scene2d.scene_inputs(production.state, drawn) and record["file"] == "p-s1.mp4"
    assert production.state["scene2d"]["s1"]["document"]["layers"][0]["source"] == "/api/v1/file/p-frame-s1.png?workspace=ws"
    calls = []
    replies["scenes.video2d.export"] = lambda arguments: calls.append(arguments) or {"receipt": {"commandId": "again"}}
    export_scenes(production, plan, shot_windows(plan, production.score()))
    assert calls == [], "the scene the edit exported is the one a resume would make"


def test_a_leftover_h3_clip_does_not_skip_a_new_cutout_on_resume(tmp_path):
    """An h3 take on the same key is not what a scene2d resume compares: a new cutout must export again."""
    from services.production_shot_edit import reexport_shot
    from services.production_stage_scenes import export_scenes
    (tmp_path / "score.json").write_text(json.dumps({"duration": 8, "bpm": 120, "beat": 0.5, "lines": []}))
    item = shot(scene2d={"cast": {"subject_1": "lia"}, "background": PLATE})
    plan = spec(item, cast=[{"id": "lia", "sheet_prompt": "a singer"}])
    replies = {
        scene2d.COMPILE: card_document,
        "scenes.video2d.edit": lambda arguments: {"result": edit(arguments)["result"]},
        "scenes.video2d.validate": lambda arguments: {"result": {"warnings": []}},
        "scenes.document.save": lambda arguments: {"result": {"name": "p-s1.scene.json"}},
        "scenes.video2d.export": lambda arguments: {"receipt": {"commandId": "export-s1"}},
        "scenes.video2d.export.receipt": lambda arguments: {"receipt": {"artifacts": [{"name": "p-s1.mp4"}]}},
        "montages.get": lambda arguments: {"result": {"revision": 1, "montage": {"revision": 1, "clips": [{"id": "s1", "source": "old.mp4"}]}}},
        "montages.save": lambda arguments: {"result": {"file": "p.montage.json", "revision": 2}},
    }
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path),
                            mcp=lambda tool, arguments: replies[tool](arguments))
    production.state.update(
        spec=plan, score="score.json", status="completed", montage_file="p.montage.json",
        clips={"s1": {"file": "old-h3.mp4", "url": "/api/v1/file/old-h3.mp4?workspace=ws"}},
        cast={"lia": "/api/v1/uploads/sheet.png"},
        cast_cutouts={"lia": {"source": "x", "url": "/api/v1/file/lia-cut.png?workspace=ws"}},
    )
    reexport_shot(production, plan, "s1")
    token = scene2d.scene_inputs(production.state, item)
    assert production.state["scenes"]["s1"]["clip"] == token and token != "old-h3.mp4"
    production.state["cast_cutouts"]["lia"]["url"] = "/api/v1/file/lia-cut-b.png?workspace=ws"
    calls = []
    replies["scenes.video2d.export"] = lambda arguments: calls.append(arguments) or {"receipt": {"commandId": "again"}}
    export_scenes(production, plan, shot_windows(plan, production.score()))
    assert calls, "a new cutout must export again; an h3 leftover must not be the resume key"


def test_a_resume_exports_again_when_the_named_set_was_remade(tmp_path):
    from services.production_stage_scenes import export_scenes
    (tmp_path / "score.json").write_text(json.dumps({"duration": 8, "bpm": 120, "beat": 0.5, "lines": []}))
    item = shot(scene2d={"cast": {"subject_1": SUBJECT}, "background": "alley"})
    plan = spec(item)
    calls = []
    replies = {
        scene2d.COMPILE: card_document,
        "scenes.video2d.edit": lambda arguments: {"result": edit(arguments)["result"]},
        "scenes.video2d.validate": lambda arguments: {"result": {"warnings": []}},
        "scenes.document.save": lambda arguments: {"result": {"name": "p-s1.scene.json"}},
        "scenes.video2d.export": lambda arguments: calls.append("export") or {"receipt": {"commandId": f"export-{len(calls)}"}},
        "scenes.video2d.export.receipt": lambda arguments: {"receipt": {"artifacts": [{"name": "p-s1.mp4"}]}},
    }
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path),
                            mcp=lambda tool, arguments: replies[tool](arguments))
    production.state.update(spec=plan, score="score.json", status="completed",
                            sets={"alley": {"url": "/api/v1/file/alley-v1.png?workspace=ws"}})
    windows = shot_windows(plan, production.score())
    export_scenes(production, plan, windows)
    assert calls == ["export"]
    calls.clear()
    export_scenes(production, plan, windows)
    assert calls == [], "the same set does not export again"
    production.state["sets"]["alley"]["url"] = "/api/v1/file/alley-v2.png?workspace=ws"
    export_scenes(production, plan, windows)
    assert calls == ["export"], "a remade set exports the scene again"


def test_the_dry_run_reads_the_runs_own_pictures_for_the_alpha_check(tmp_path):
    from PIL import Image
    Image.new("RGB", (8, 8), (200, 40, 40)).save(tmp_path / "boxed.png")      # a picture with no transparent pixel
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(tmp_path / "cut.png")
    boxed = {**shot(), "scene2d": {"template": "music-pinball", "cast": {"subject_1": "boxed.png"}, "background": PLATE}}
    clean = {**shot(key="s2"), "t0": 6, "scene2d": {"template": "music-pinball", "cast": {"subject_1": "cut.png"}, "background": PLATE}}
    report = dry_run(spec(boxed, clean), root=tmp_path, workspace="ws")
    alpha = [(item["key"], item.get("detail")) for item in report["warnings"] if item["code"] == "cutout_without_alpha"]
    assert alpha == [("s1", "subject_1")], "the workspace picture is read from the run's folder, not ./outputs"


@pytest.mark.parametrize("value", ["/examples/creative/singer.png", "data:image/png;base64,iVBORw0KGgo="])
def test_example_media_and_inline_pictures_are_sources_as_they_are(value):
    media = {"workspace": "ws", "root": None, "models": {}, "sets": {}, "cast": {}, "stills": {}}
    assert scene2d.source_url(value, media) == value
