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
    assert len(doc["slots"]) == 1 and doc["slots"][0]["media"] == "model3d"
    assert doc["slots"][0]["clip"] is None
    assert doc["slots"][0]["motion"]["turnTo"] == 6.283
    assert doc["camera"]["orbitRadius"] == 5
    assert doc["atmos"]["timeOfDay"] == "dawn"
    assert doc["rhythm"]["bpm"] == 120 and doc["rhythm"]["offset"] == 24


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
