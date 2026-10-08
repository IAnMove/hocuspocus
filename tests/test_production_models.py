"""Production 3D models: portrait -> T-pose picture -> textured mesh -> rig, in batches, resumable."""
import json
import struct

import pytest

from services.production_models import ModelError, check_models, make_models
from services.production_scene3d import resolve_media

SPEC = {"song": {"bpm": 96}, "style": {"image": "felt puppets"},
        "cast": [{"id": "hero", "sheet_prompt": "a felt hero"}],
        "stills": {"boat-pic": "/api/v1/uploads/boat.png"},
        "models": {"hero": {"from": "hero", "animations": ["idle", "dance_bounce"]},
                   "boat": {"from": "boat-pic", "rig": "vehicle"},
                   "kite": {"prompt": "a paper kite"}}}


def glb(path, clips):
    body = json.dumps({"asset": {"version": "2.0"}, "animations": [{"name": name} for name in clips]}).encode()
    body += b" " * (-len(body) % 4)
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 20 + len(body)) + struct.pack("<I4s", len(body), b"JSON") + body)


class Production:
    ws, id, failures = "w", "piece", {}

    def __init__(self, root, broken=()):
        self.root, self.broken, self.calls, self.images = root, set(broken), [], []
        self.state = {"cast_single": {"hero": "/api/v1/uploads/hero-single.png"}}

    def save(self):
        pass

    def log(self, line):
        self.state.setdefault("log", []).append(line)

    def _attempt(self, group, key):
        counts = self.state.setdefault(group, {})
        counts[key] = counts.get(key, 0) + 1
        return counts[key] - 1

    def image(self, key, prompt, refs, res, seed, model=None, steps=None, attempt=0):
        self.images.append({"key": key, "prompt": prompt, "refs": refs, "res": res, "model": model, "attempt": attempt})
        return f"job-{key}-{attempt}"

    def wait(self, jobs):
        names = {}
        for name, job in jobs.items():
            (self.root / f"{name}.png").write_bytes(b"png")
            names[name] = f"{name}.png"
        return names

    def upload(self, name):
        return str(self.root / name), f"/api/v1/uploads/{name}"

    def mcp(self, operation, args):
        self.calls.append((operation, args))
        data = args["input"]
        if operation in ("model3d.generate", "model3d.rig"):
            return {"version": 1, "status": "accepted", "result": {"job_id": f"{operation}:{args['intent_id']}"}}
        job = data["job_id"]
        kind, intent = job.split(":", 1)
        name = intent.split("-")[2]
        if kind == "model3d.generate":
            if name in self.broken:
                return {"status": "failed", "result": {"status": "failed", "error": "out of memory"}}
            (self.root / f"{name}-mesh.glb").write_bytes(b"glb")
            return {"status": "completed", "result": {"status": "completed", "filename": f"{name}-mesh.glb"}}
        rig = next(a for o, a in self.calls if o == "model3d.rig" and a["intent_id"] == intent)["input"]
        glb(self.root / f"{name}-rigged.glb", rig["animations"])
        return {"status": "completed", "result": {"status": "completed", "filename": f"{name}-rigged.glb"}}


def submitted(production, operation):
    return [args["input"] for op, args in production.calls if op == operation]


def test_spec_models_are_checked():
    check_models(SPEC)
    for bad in ({"Hero": {"from": "hero"}}, {"hero": {}}, {"hero": {"from": "hero", "rig": "robot"}},
                {"hero": {"from": "hero", "animations": []}}, {"hero": {"from": "hero", "colour": "red"}}):
        with pytest.raises(ModelError):
            check_models({**SPEC, "models": bad})


def test_characters_get_a_t_pose_from_their_portrait_then_a_mesh_and_a_tempo_rig(tmp_path):
    production = Production(tmp_path)
    make_models(production, SPEC, sleep=lambda _: None)
    pictures = {image["key"]: image for image in production.images}
    assert set(pictures) == {"model-hero", "model-kite"}        # the boat already has its picture
    assert pictures["model-hero"]["refs"] == ["/api/v1/uploads/hero-single.png"]
    assert "T-pose" in pictures["model-hero"]["prompt"] and pictures["model-hero"]["prompt"].startswith("felt puppets")
    assert pictures["model-kite"]["refs"] is None and "a paper kite" in pictures["model-kite"]["prompt"]
    meshes = {item["image_path"]: item for item in submitted(production, "model3d.generate")}
    assert set(meshes) == {"/api/v1/uploads/hero.png", "/api/v1/uploads/boat.png", "/api/v1/uploads/kite.png"}
    assert all(item["preset"] == "balanced" for item in meshes.values())
    rigs = {item["source"]: item for item in submitted(production, "model3d.rig")}
    assert rigs["hero-mesh.glb"]["engine"] == "humanoid" and rigs["hero-mesh.glb"]["animation_bpm"] == 96
    assert rigs["hero-mesh.glb"]["animations"] == ["idle", "dance_bounce"]
    assert rigs["boat-mesh.glb"] == {**rigs["boat-mesh.glb"], "engine": "procedural", "rig_profile": "vehicle"}
    assert "kite-mesh.glb" not in rigs                           # an object without a rig stays rigid
    models = production.state["models"]
    assert models["hero"]["file"] == "hero-rigged.glb" and models["hero"]["clips"] == ["idle", "dance_bounce"]
    assert models["kite"]["file"] == "kite-mesh.glb" and models["kite"]["clips"] == []


def test_a_resume_does_nothing_and_a_changed_model_is_remade_alone(tmp_path):
    production = Production(tmp_path)
    make_models(production, SPEC, sleep=lambda _: None)
    calls = len(production.calls)
    make_models(production, SPEC, sleep=lambda _: None)
    assert len(production.calls) == calls
    changed = {**SPEC, "models": {**SPEC["models"], "boat": {"from": "boat-pic", "rig": "vehicle", "animations": ["wobble"]}}}
    make_models(production, changed, sleep=lambda _: None)
    assert [item["source"] for item in submitted(production, "model3d.rig")][-1] == "boat-mesh.glb"
    assert len(submitted(production, "model3d.generate")) == 4


def test_a_failed_mesh_stops_the_run_and_is_retried_on_resume(tmp_path):
    production = Production(tmp_path, broken={"kite"})
    with pytest.raises(ModelError, match="models failed: kite"):
        make_models(production, SPEC, sleep=lambda _: None)
    assert "out of memory" in production.state["models"]["kite"]["error"]
    assert production.state["models"]["hero"]["file"] == "hero-rigged.glb"
    production.broken.clear()
    make_models(production, SPEC, sleep=lambda _: None)
    assert production.state["models"]["kite"]["file"] == "kite-mesh.glb"
    assert [image["attempt"] for image in production.images if image["key"] == "model-kite"] == [0, 1]


def test_a_scene3d_cast_names_a_model_and_its_clips(tmp_path):
    production = Production(tmp_path)
    make_models(production, SPEC, sleep=lambda _: None)
    resolved = resolve_media({"template": "dance-stage", "cast": {"subject_1": {"source": "hero", "clip": "dance_bounce"}}},
                             stills=SPEC["stills"], root=tmp_path, workspace="w", models=production.state["models"])
    hero = resolved["cast"]["subject_1"]
    assert hero["source"] == "/api/v1/file/hero-rigged.glb?workspace=w"
    assert hero["clip"] == {"index": 1, "name": "dance_bounce"}


def test_sets_are_painted_in_the_same_batch_with_the_floor_recipe_and_named_as_backgrounds(tmp_path):
    spec = {**SPEC, "sets": {"harbour": {"prompt": "a night harbour with a stone pier"}}}
    production = Production(tmp_path)
    waited = []
    plain_wait = production.wait
    production.wait = lambda jobs: waited.append(sorted(jobs)) or plain_wait(jobs)
    make_models(production, spec, sleep=lambda _: None)
    assert waited == [["hero", "kite", "set:harbour"]]
    painted = next(image for image in production.images if image["key"] == "set-harbour")
    assert painted["res"] == "1664x928" and "open floor across the lower third" in painted["prompt"]
    assert painted["prompt"].startswith("felt puppets. a night harbour")
    url = production.state["sets"]["harbour"]["url"]
    resolved = resolve_media({"template": "dance-stage", "background": "harbour"}, stills={}, root=tmp_path, workspace="w",
                             sets=production.state["sets"])
    assert resolved["background"] == {"source": url}
    calls = len(production.images)
    make_models(production, spec, sleep=lambda _: None)
    assert len(production.images) == calls, "an unchanged set is not painted again"


def test_a_spec_with_only_sets_runs_the_stage_and_bad_sets_are_refused(tmp_path):
    production = Production(tmp_path)
    make_models(production, {"style": {}, "sets": {"roof": {"prompt": "a moonlit rooftop"}}}, sleep=lambda _: None)
    assert production.state["sets"]["roof"]["url"].endswith("roof.png") and production.calls == []
    for bad in ({"Roof": {"prompt": "x"}}, {"roof": {}}, {"roof": {"prompt": "x", "size": 3}}):
        with pytest.raises(ModelError):
            check_models({"sets": bad})
