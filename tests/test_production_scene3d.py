"""Native 3D clip admission, resume, retake and failure propagation."""
from pathlib import Path

import pytest

from services.production_scene3d import compile_document, export_scene3d_clips, validate_scene3d_shot


def shot(**config):
    return {"key": "hero", "kind": "scene3d", "t0": 0,
            "scene3d": {"template": "product-orbit", "subject": "/api/v1/file/tree.glb?workspace=test", **config}}


class Production:
    ws = "test"
    id = "movie"

    def __init__(self, root, fail=False):
        self.root, self.state, self.calls, self.fail = root, {}, [], fail

    def score(self):
        return {"duration": 6, "beat": .5, "lines": []}

    def save(self):
        pass

    def log(self, line):
        self.state.setdefault("log", []).append(line)

    def mcp(self, operation, args):
        self.calls.append((operation, args))
        if operation == "scenes.world3d.export":
            name = f"world-{len(self.calls)}.mp4"
            (self.root / name).write_bytes(b"native-export-test")
            self.state["latest"] = name
            return {"receipt": {"commandId": args["intent_id"]}}
        assert operation == "scenes.world3d.export.receipt"
        if self.fail:
            return {"receipt": {"status": "failed"}, "task": {"status": "failed"}}
        return {"receipt": {"artifacts": [{"name": self.state["latest"]}]}}


def compiler(shot, duration):
    return {"version": 1, "slots": [{"sourceUrl": shot["scene3d"]["subject"]}], "duration": duration}


def render(production, windows=None, retake=()):
    windows = windows or [shot()]
    export_scene3d_clips(production, {"shots": windows}, windows, retake, compiler=compiler, sleep=lambda _: None)


def test_export_is_a_native_clip_covers_the_cut_and_resumes_without_work(tmp_path):
    production = Production(tmp_path)
    render(production)
    request = production.calls[0][1]
    assert request["input"]["document"]["duration"] == 6
    assert request["input"]["workspace"] == "test"
    assert production.state["clips"]["hero"]["url"].endswith("?workspace=test")
    assert production.state["clips"]["hero"]["qa"]["method"] == "native-world3d"
    render(production)
    assert len(production.calls) == 2


def test_locked_shot_without_a_clip_is_still_exported(tmp_path):
    """Lock means do not regenerate. The first world3d clip must still land.

    scenes() now exports a locked shot that has no scene file. If this
    stage skips a locked scene3d key that never got a clip, scene_ops
    raises and production.run fails.
    """
    from services.production_shot_review import record_decision

    production = Production(tmp_path)
    record_decision(tmp_path, "movie", "hero", locked=True)
    render(production)
    clip = production.state["clips"]["hero"]
    assert clip["file"]
    assert (tmp_path / clip["file"]).is_file()
    assert any(operation == "scenes.world3d.export" for operation, _ in production.calls)


def test_locked_shot_survives_a_fingerprint_change_and_refuses_an_explicit_retake(tmp_path):
    from services.music_production import ProductionError
    from services.production_shot_review import record_decision

    production = Production(tmp_path)
    render(production)
    kept = dict(production.state["clips"]["hero"])
    before = len(production.calls)
    record_decision(tmp_path, "movie", "hero", locked=True)
    render(production, [shot(motion={"to": [2, 0, 0]})])
    assert production.state["clips"]["hero"] == kept
    assert len(production.calls) == before
    with pytest.raises(ProductionError) as caught:
        render(production, [shot(motion={"to": [2, 0, 0]})], ("hero",))
    assert caught.value.code == "shot_locked"
    assert production.state["clips"]["hero"] == kept
    assert production.state.get("scene3d_revisions", {}).get("hero") is None
    assert len(production.calls) == before


def test_changed_motion_and_one_explicit_retake_refresh_only_that_clip(tmp_path):
    production = Production(tmp_path)
    render(production)
    first = production.state["clips"]["hero"]["file"]
    render(production, [shot(motion={"to": [2, 0, 0]})])
    second = production.state["clips"]["hero"]["file"]
    assert second != first
    render(production, [shot(motion={"to": [2, 0, 0]})], ("hero",))
    third = production.state["clips"]["hero"]["file"]
    assert third != second
    before = len(production.calls)
    render(production, [shot(motion={"to": [2, 0, 0]})])
    assert len(production.calls) == before


def test_failed_export_retries_once_then_raises_without_still_fallback(tmp_path):
    production = Production(tmp_path, fail=True)
    with pytest.raises(ValueError, match="scene3d_export_failed"):
        render(production)
    assert [op for op, _ in production.calls].count("scenes.world3d.export") == 2
    assert not production.state["clips"]
    assert not production.state.get("held")


def test_resume_after_exhausted_retries_starts_a_fresh_cycle(tmp_path):
    production = Production(tmp_path, fail=True)
    with pytest.raises(ValueError, match="scene3d_export_failed"):
        render(production)
    first = [args["intent_id"] for op, args in production.calls if op == "scenes.world3d.export"]
    production.fail = False
    render(production)
    second = [args["intent_id"] for op, args in production.calls if op == "scenes.world3d.export"][2:]
    assert len(second) == 1
    assert second[0] not in first
    assert production.state["clips"]["hero"]["file"]
    assert production.state["world3d_exports"]["hero"]["cycle"] == 1


def test_failed_retake_keeps_the_last_native_clip(tmp_path):
    production = Production(tmp_path)
    render(production)
    kept = dict(production.state["clips"]["hero"])
    production.fail = True
    with pytest.raises(ValueError, match="scene3d_export_failed"):
        render(production, retake=("hero",))
    assert production.state["clips"]["hero"] == kept
    assert (tmp_path / kept["file"]).is_file()


@pytest.mark.parametrize("config", [{}, {"template": "hero-push", "document": {}}, {"unknown": 1}])
def test_rejects_missing_or_ambiguous_native_scene(config):
    with pytest.raises(ValueError):
        validate_scene3d_shot({"scene3d": config})


@pytest.mark.parametrize("config", [{"renderLook": "cel"}, {"renderLook": "toon", "toon": {"steps": 6}},
                                    {"toon": {"ink": "black"}}, {"toon": {"width": 2}}])
def test_refuses_unknown_render_looks_and_bad_toon_settings(config):
    with pytest.raises(ValueError, match="renderLook|toon"):
        validate_scene3d_shot(shot(**config))
    with pytest.raises(ValueError, match="renderLook|toon"):
        validate_scene3d_shot({"scene3d": {"document": {"slots": [], **config}}})


def test_render_looks_match_the_editor():
    import re
    from services.world3d_look import RENDER_LOOKS
    source = (Path(__file__).resolve().parents[1] / "ui/src/features/scene3d/types.ts").read_text(encoding="utf-8")
    declared = re.search(r"SCENE3D_RENDER_LOOKS = \[([^\]]*)\] as const", source).group(1)
    assert tuple(re.findall(r"'([a-z0-9]+)'", declared)) == RENDER_LOOKS


def test_does_not_claim_rigid_models_sing():
    with pytest.raises(ValueError, match="lip-sync"):
        validate_scene3d_shot({**shot(), "sing": True})


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "ui/node_modules/tsx/dist/loader.mjs").is_file(), reason="UI dependencies not installed in Python-only CI")
def test_real_native_template_compiler_keeps_model_camera_atmosphere_and_motion():
    doc = compile_document(shot(renderLook="n64", rhythm={"bpm": 120, "offset": 24, "lightPulse": .3}, motion={"to": [3, 0, 0], "turnTo": 6.283}, atmos={"timeOfDay": "dawn"},
                                camera={"family": "orbit", "orbitRadius": 5}), 6)
    assert doc["renderLook"] == "n64"
    assert doc["templateId"] == "product-orbit"
    assert doc["duration"] == 6
    assert [slot["slot"] for slot in doc["slots"]] == ["subject_1", "background"]
    subject = next(slot for slot in doc["slots"] if slot["slot"] == "subject_1")
    assert subject["media"] == "model3d" and subject["clip"] is None
    assert subject["motion"]["turnTo"] == 6.283
    assert doc["camera"]["orbitRadius"] == 5
    assert doc["atmos"]["timeOfDay"] == "dawn"
    assert doc["rhythm"]["bpm"] == 120 and doc["rhythm"]["offset"] == 24


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "ui/node_modules/tsx/dist/loader.mjs").is_file(), reason="UI dependencies not installed in Python-only CI")
def test_real_native_template_compiler_keeps_the_toon_look():
    doc = compile_document(shot(renderLook="toon", toon={"steps": 2, "outline": 4.5, "ink": "#203040"}), 6)
    assert doc["renderLook"] == "toon"
    assert doc["toon"] == {"steps": 2, "outline": 4.5, "ink": "#203040"}

@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "ui/node_modules/tsx/dist/loader.mjs").is_file(), reason="UI dependencies not installed in Python-only CI")
def test_a_subject_glb_replaces_an_anime_cutout_and_keeps_the_shake():
    doc = compile_document(shot(template="anime-impact-frame"), 3)
    subject = next(slot for slot in doc["slots"] if slot["id"] == "subject")
    assert subject["media"] == "model3d" and subject["sourceUrl"].endswith("tree.glb?workspace=test")
    assert doc["camera"]["shake"][0]["start"] == 1.25
    assert doc["screenBackdrop"]["sfx"][0]["kind"] == "speedlines"
    cutout = compile_document(shot(template="anime-impact-frame", subject="/api/v1/file/hero.png?workspace=test"), 3)
    assert next(slot for slot in cutout["slots"] if slot["id"] == "subject")["media"] == "image"


def test_uncertain_admission_resumes_with_the_exact_same_intent(tmp_path):
    production = Production(tmp_path)
    native = production.mcp
    uncertain = []

    def transport(operation, args):
        if operation == "scenes.world3d.export" and not uncertain:
            uncertain.append(args["intent_id"])
            raise ConnectionError("reply lost")
        return native(operation, args)

    production.mcp = transport
    with pytest.raises(ConnectionError):
        render(production)
    render(production)
    assert production.calls[0][1]["intent_id"] == uncertain[0]
    assert production.state["world3d_exports"]["hero"]["attempt"] == 1


@pytest.mark.parametrize("look", [None, "n64"])
def test_scene3d_spec_enters_runner_and_montage_as_video_not_image(tmp_path, monkeypatch, look):
    from services import music_production as runner
    from services.production_dry_run import dry_run

    spec = runner.validate_spec({"title": "3D", "song": {"lyrics": "hello", "caption": "synth", "duration": 60, "bpm": 120},
                                "style": {}, "shots": [shot(**({"renderLook": look} if look else {})) | {"key": f"s{index}", "t0": index * 6} for index in range(10)]})
    assert 'scene3d' in runner.SPEC_SCHEMA['properties']['shots']['anyOf'][1]['items']['properties']['kind']['enum']
    report = dry_run(spec)
    assert report['h3_frames'] == 0
    assert not any(warning['code'] == 'few_clips' for warning in report['warnings'])
    production = runner.Production('test', 'movie', workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    ops = production.scene_ops(shot(), 0, 6, 6, {"lines": []}, {'hero': {'url': '/api/v1/file/3d.mp4?workspace=test'}}, {}, {})
    assert ops[0]['type'] == 'video'
    assert not any(op.get('type') == 'image' for op in ops)
    with pytest.raises(runner.ProductionError, match='clip missing'):
        production.scene_ops(shot(), 0, 6, 6, {"lines": []}, {}, {}, {})
    stages = []
    for name in ('song', 'analyze', 'cast', 'frames', 'clips', 'scenes', 'package'):
        setattr(production, name, lambda *_, stage=name: stages.append(stage))
    production.score = lambda: {"duration": 60, "lines": []}
    production.montage = lambda *_: production.state.update(final='movie.mp4')
    monkeypatch.setattr(runner, 'export_scene3d_clips', lambda *_: stages.append('world3d'))
    production.run(spec)
    assert production.state['status'] == 'completed'
    assert stages.index('clips') < stages.index('world3d') < stages.index('scenes')


def test_silicon_grid_shots_pass_dry_run():
    from services import music_production as runner
    from services.production_dry_run import dry_run

    shots = []
    for index, template in enumerate(('atmos-silicon-grid-wide', 'atmos-silicon-grid-low')):
        shots.append({
            'key': f'grid{index}',
            'kind': 'scene3d',
            't0': index * 6,
            'scene3d': {'template': template, 'subject': '/api/v1/file/hero.glb?workspace=test'},
        })
    spec = runner.validate_spec({
        'title': 'Silicon grid',
        'song': {'lyrics': 'neon', 'caption': 'grid', 'duration': 12, 'bpm': 120},
        'style': {},
        'shots': shots,
    })
    report = dry_run(spec)
    assert report['dry_run'] is True
    assert report['h3_frames'] == 0


def test_silicon_circuit_shots_pass_dry_run():
    from services import music_production as runner
    from services.production_dry_run import dry_run

    shots = []
    for index, template in enumerate(('atmos-silicon-circuit-wide', 'atmos-silicon-circuit-low')):
        shots.append({
            'key': f'circuit{index}',
            'kind': 'scene3d',
            't0': index * 6,
            'scene3d': {'template': template, 'subject': '/api/v1/file/hero.glb?workspace=test'},
        })
    spec = runner.validate_spec({
        'title': 'Silicon circuit',
        'song': {'lyrics': 'trace', 'caption': 'board', 'duration': 12, 'bpm': 120},
        'style': {},
        'shots': shots,
    })
    report = dry_run(spec)
    assert report['dry_run'] is True
    assert report['h3_frames'] == 0


def test_silicon_mainframe_shots_pass_dry_run():
    from services import music_production as runner
    from services.production_dry_run import dry_run

    shots = []
    for index, template in enumerate(('atmos-silicon-mainframe-wide', 'atmos-silicon-mainframe-low')):
        shots.append({
            'key': f'mainframe{index}',
            'kind': 'scene3d',
            't0': index * 6,
            'scene3d': {'template': template, 'subject': '/api/v1/file/hero.glb?workspace=test'},
        })
    spec = runner.validate_spec({
        'title': 'Silicon mainframe',
        'song': {'lyrics': 'hall', 'caption': 'screens', 'duration': 12, 'bpm': 120},
        'style': {},
        'shots': shots,
    })
    report = dry_run(spec)
    assert report['dry_run'] is True
    assert report['h3_frames'] == 0


def test_native_fill_covers_an_h3_tail_and_arbitrary_shot_keys_are_safe(tmp_path):
    production = Production(tmp_path)
    production.state['clips'] = {'opening': {'file': 'h3.mp4'}}
    windows = [{'key': 'opening', 'kind': 'h3', 't0': 0, 't1': 1}]
    spec = {'shots': windows, 'fill': [shot()]}
    export_scene3d_clips(production, spec, windows, compiler=compiler, sleep=lambda _: None)
    assert production.calls[0][1]['input']['document']['duration'] == pytest.approx(.833, abs=.001)
    assert 'opening_fill0' in production.state['clips']
    render(production, [shot() | {'key': 'long key / ☀' * 40}])
    intent = production.calls[-2][1]['intent_id']
    assert len(intent) <= 160 and intent.isascii() and ' ' not in intent


def test_many_native_cuts_stay_within_one_frame_of_continuous_audio():
    from services.production_windows import segments

    windows = [shot() | {'key': f's{i}', 't0': i * 1.009} for i in range(100)]
    cuts = segments(windows, {'duration': 100.9}, lambda _: False, [])
    elapsed_frames = 0
    for index, (_, start, end) in enumerate(cuts):
        # Simulate the actual CFR montage; later mouths must not accumulate
        # rounding error against an uninterrupted song.
        assert elapsed_frames / 24 == pytest.approx(start)
        assert abs(elapsed_frames / 24 - windows[index]['t0']) <= .5 / 24
        elapsed_frames += round(round(end - start, 3) * 24)
    assert abs(elapsed_frames / 24 - 100.9) <= .5 / 24


def test_native_export_and_wrapping_scene_share_fractional_cut_lengths(tmp_path):
    from services import music_production as runner

    production = Production(tmp_path)
    production.score = lambda: {'duration': 36.567, 'beat': .5, 'lines': []}
    windows = [shot() | {'key': f's{i}', 't0': round(i * 6.092492, 3)} for i in range(6)]
    render(production, windows)
    cuts = runner.segments(windows, production.score(), lambda _: True, [])
    wrapped_frames = []
    for window, start, end in cuts:
        duration = production.state['clips'][window['key']]['world3d_document']['duration']
        assert duration == round(end - start, 3)
        wrapped_frames.append(round(duration * 24))
    assert wrapped_frames == [146, 146, 147, 146, 146, 147]
    assert sum(wrapped_frames) == round(production.score()['duration'] * 24)


def test_mixed_native_cuts_share_the_grid_and_existing_2d_cuts_stay_unchanged():
    from services.production_frame_clock import align_native_cuts

    first = ({'key': 'still', 'kind': 'still'}, 0, 1.009)
    second = (shot(), 1.009, 2.018)
    cuts = align_native_cuts([first, second])
    assert cuts[0][2] == cuts[1][1]
    assert round((cuts[0][2] - cuts[0][1]) * 24) + round((cuts[1][2] - cuts[1][1]) * 24) == 48
    legacy = [first, ({'key': 'clip', 'kind': 'clip'}, 1.009, 2.018)]
    assert align_native_cuts(legacy) == legacy


# ---------------------------------------------------------------- template + cast + painted set
from services.production_scene3d import resolve_media  # noqa: E402

NODE = pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "ui/node_modules/tsx/dist/loader.mjs").is_file(),
                          reason="UI dependencies not installed in Python-only CI")


def cast_shot(**config):
    return {"key": "set", "kind": "scene3d", "t0": 0, "scene3d": {"template": "dance-stage", **config}}


def glb(path, clips):
    """A .glb that only carries animation names, enough for the clip lookup."""
    import json
    import struct
    body = json.dumps({"asset": {"version": "2.0"}, "animations": [{"name": name} for name in clips]}).encode()
    body += b" " * (-len(body) % 4)
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 20 + len(body)) + struct.pack("<I4s", len(body), b"JSON") + body)


def test_a_template_takes_a_cast_and_a_background_instead_of_a_document():
    validate_scene3d_shot(cast_shot(cast={"subject_1": "hero.glb"}, background="fair", floor="backdrop"))
    validate_scene3d_shot(cast_shot(cast={"subject_1": {"source": "hero.glb", "clip": "dance", "scale": 1.2}},
                                    background={"source": "fair", "surface": "environment"}))


@pytest.mark.parametrize("config", [
    {"cast": {}}, {"cast": {"subject_1": {"clip": "dance"}}}, {"cast": {"subject_1": {"source": "a.glb", "colour": 1}}},
    {"cast": {"subject_1": "a.glb"}, "background": {"source": "fair", "surface": "sky"}},
    {"cast": {"subject_1": "a.glb"}, "floor": "lava"}, {"background": "fair"},
])
def test_rejects_a_cast_or_set_it_cannot_bind(config):
    with pytest.raises(ValueError):
        validate_scene3d_shot(cast_shot(**config))


def test_names_become_urls_and_clip_names_their_index(tmp_path):
    glb(tmp_path / "hero.glb", ["idle", "dance"])
    config = {"template": "dance-stage", "background": "fair",
              "cast": {"subject_1": {"source": "hero.glb", "clip": "dance",
                                     "clips": [{"clip": "idle", "start": 0}, {"clip": {"index": 1, "name": "dance"}, "start": 2}]}}}
    resolved = resolve_media(config, stills={"fair": "/api/v1/uploads/fair.png"}, root=tmp_path, workspace="my ws")
    hero = resolved["cast"]["subject_1"]
    assert resolved["background"] == {"source": "/api/v1/uploads/fair.png"}
    assert hero["source"] == "/api/v1/file/hero.glb?workspace=my%20ws"
    assert hero["clip"] == {"index": 1, "name": "dance"}
    assert [cue["clip"] for cue in hero["clips"]] == [{"index": 0, "name": "idle"}, {"index": 1, "name": "dance"}]
    assert config["cast"]["subject_1"]["source"] == "hero.glb"  # the spec itself is left alone


def test_unknown_names_and_clips_fail_before_any_export(tmp_path):
    glb(tmp_path / "hero.glb", ["idle"])
    with pytest.raises(ValueError, match="not a URL, a stills name or a file"):
        resolve_media({"template": "dance-stage", "background": "nowhere"}, stills={}, root=tmp_path, workspace="w")
    with pytest.raises(ValueError, match=r"no clip 'dance' in its model \(clips: idle\)"):
        resolve_media({"template": "dance-stage", "cast": {"subject_1": {"source": "hero.glb", "clip": "dance"}}},
                      stills={}, root=tmp_path, workspace="w")
    with pytest.raises(ValueError, match="not a URL"):
        resolve_media({"template": "dance-stage", "cast": {"subject_1": "../outside.glb"}}, stills={}, root=tmp_path, workspace="w")


def test_a_spec_that_already_gives_urls_keeps_its_fingerprint(tmp_path):
    production = Production(tmp_path)
    render(production)
    before = production.state["clips"]["hero"]["fingerprint"]
    config = shot()["scene3d"]
    assert resolve_media(config, stills={}, root=tmp_path, workspace="test") == config
    render(production)
    assert production.state["clips"]["hero"]["fingerprint"] == before
    assert len(production.calls) == 2


def test_the_export_compiles_the_resolved_set(tmp_path):
    seen = []

    def compile_set(shot, duration):
        seen.append(shot["scene3d"])
        return {"version": 1, "slots": [], "duration": duration}

    production = Production(tmp_path)
    window = cast_shot(cast={"subject_1": "/api/v1/file/hero.glb?workspace=test"}, background="fair")
    spec = {"shots": [window], "stills": {"fair": "/api/v1/uploads/fair.png"}}
    export_scene3d_clips(production, spec, [window], (), compiler=compile_set, sleep=lambda _: None)
    assert seen[0]["background"] == {"source": "/api/v1/uploads/fair.png"}
    assert window["scene3d"]["background"] == "fair"


@NODE
def test_real_compiler_binds_cast_and_background_and_projects_the_floor():
    doc = compile_document(cast_shot(cast={"subject_1": "/api/v1/file/hero.glb?workspace=t"},
                                     background="/api/v1/file/fair.png?workspace=t"), 4)
    slots = {slot["slot"]: slot for slot in doc["slots"]}
    assert slots["subject_1"]["sourceUrl"].endswith("hero.glb?workspace=t") and slots["subject_1"]["media"] == "model3d"
    assert slots["background"]["sourceUrl"].endswith("fair.png?workspace=t") and slots["background"]["media"] == "image"
    assert doc["environment"]["floorStyle"] == "backdrop"
    flat = compile_document(cast_shot(cast={"subject_1": "/api/v1/file/hero.glb?workspace=t"},
                                      background="/api/v1/file/fair.png?workspace=t", floor="none"), 4)
    assert flat["environment"]["floorStyle"] == "none"


@NODE
def test_real_compiler_keeps_a_floor_the_template_chose_and_skips_an_environment_plate():
    mirror = compile_document(cast_shot(template="cine-reflections", cast={"subject_1": "/api/v1/file/h.glb?workspace=t"},
                                        background="/api/v1/file/f.png?workspace=t"), 4)
    assert mirror["environment"]["floorStyle"] == "mirror"
    plate = compile_document(cast_shot(template="reflective-stage", cast={"subject_1": "/api/v1/file/h.glb?workspace=t"},
                                       background="/api/v1/file/f.png?workspace=t"), 4)
    assert (plate.get("environment") or {}).get("floorStyle") != "backdrop"
    assert any(slot["slot"] == "background" and slot["sourceUrl"].endswith("f.png?workspace=t") for slot in plate["slots"])


@NODE
def test_real_compiler_binds_by_object_id_refuses_ambiguous_or_missing_roles_and_adds_props():
    pictures = {"hero": "/api/v1/file/hero.png?workspace=t", "near-prop": "/api/v1/file/lamp.png?workspace=t"}
    doc = compile_document(cast_shot(template="dark-still-two-distances", cast=pictures), 4)
    by_id = {slot["id"]: slot for slot in doc["slots"]}
    assert by_id["hero"]["sourceUrl"] == pictures["hero"] and by_id["near-prop"]["sourceUrl"] == pictures["near-prop"]
    assert by_id["exterior-video"]["sourceUrl"] == ""  # untouched template objects stay
    with pytest.raises(ValueError, match="cast_role_ambiguous:prop"):
        compile_document(cast_shot(template="dark-still-two-distances", cast={"prop": "/api/v1/file/x.png?workspace=t"}), 4)
    with pytest.raises(ValueError, match="cast_slot_missing:subject_2"):
        compile_document(cast_shot(cast={"subject_2": "/api/v1/file/x.glb?workspace=t"}), 4)
    added = compile_document(cast_shot(cast={"subject_1": "/api/v1/file/h.glb?workspace=t",
                                             "boat": {"source": "/api/v1/file/boat.glb?workspace=t", "add": True,
                                                      "position": [2, 0, 0]}}), 4)
    boat = next(slot for slot in added["slots"] if slot["id"] == "boat")
    assert boat["slot"] == "prop" and boat["media"] == "model3d" and boat["position"] == [2, 0, 0]
    with pytest.raises(ValueError, match="background_slot_missing"):
        compile_document(cast_shot(template="speech-portrait", cast={"subject_1": "/api/v1/file/h.glb?workspace=t"},
                                   background="/api/v1/file/f.png?workspace=t"), 4)
