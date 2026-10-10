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
    assert set(pictures) == {"model-hero", "model-kite", "model-boat"}
    assert pictures["model-hero"]["refs"] == ["/api/v1/uploads/hero-single.png"]
    boat = pictures["model-boat"]
    assert boat["refs"] == ["/api/v1/uploads/boat.png"] and "remove the base, stand, pedestal" in boat["prompt"], \
        "a picture with a base or scenery would be meshed with it: the subject is redrawn alone"
    hero, kite = pictures["model-hero"]["prompt"], pictures["model-kite"]["prompt"]
    assert "T-pose" in hero and "isolated" in hero and "felt puppets" not in hero, "the portrait carries the look; the prompt is the staging"
    assert "both legs and feet clearly visible" in hero, "the humanoid rig refuses a figure whose robe hides its legs"
    assert pictures["model-kite"]["refs"] is None and kite.startswith("a paper kite") and "felt puppets" in kite and kite.endswith("no shadow")
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
    assert waited == [["boat", "hero", "kite", "set:harbour"]]
    painted = next(image for image in production.images if image["key"] == "set-harbour")
    assert painted["res"] == "1664x928" and "large open EMPTY floor" in painted["prompt"]
    assert painted["prompt"].startswith("An EMPTY set with nobody in it") and "a night harbour" in painted["prompt"]
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


def test_a_refused_mesh_says_why(tmp_path):
    """An engine that is not installed answers with a tool error; the model's error carries its message."""
    production = Production(tmp_path)
    plain = production.mcp

    def refusing(operation, args):
        if operation == "model3d.generate":
            production.calls.append((operation, args))
            return {"_is_error": True, "error": {"code": "failed", "message": "Optional engine: install 3D Generation (Hunyuan3D)"}}
        return plain(operation, args)

    production.mcp = refusing
    with pytest.raises(ModelError, match="models failed"):
        make_models(production, SPEC, sleep=lambda _: None)
    assert "not admitted: Optional engine: install 3D Generation (Hunyuan3D)" in production.state["models"]["hero"]["error"]


def test_meshes_go_in_waves_the_3d_service_accepts(tmp_path):
    """model3d_service refuses a fifth active job; six models are submitted four, then two."""
    models = {f"thing{i}": {"from": "boat-pic"} for i in range(6)}
    production = Production(tmp_path)
    active, peak = [], []
    plain = production.mcp

    def counting(operation, args):
        if operation == "model3d.generate":
            active.append(args["intent_id"])
            peak.append(len(active))
        if operation == "model3d.status":
            reply = plain(operation, args)
            intent = args["input"]["job_id"].split(":", 1)[1]
            if intent in active:
                active.remove(intent)
            return reply
        return plain(operation, args)

    production.mcp = counting
    make_models(production, {**SPEC, "models": models}, sleep=lambda _: None)
    assert max(peak) == 4 and all(production.state["models"][name]["file"] for name in models)


def test_the_scenery_look_drops_the_sentences_about_people():
    from services.production_models import scenery_look
    look = ("Toy diorama of painted wood and felt; characters are vinyl figurines with rounded faces; warm lanterns. "
            "No text.")
    assert scenery_look(look) == "Toy diorama of painted wood and felt; warm lanterns. No text."


DIORAMA = {"kind": "diorama", "prompt": "a village square on a summer night", "seed": 5,
           "houses": ["a pale yellow house with a green door", "a terracotta townhouse with blue shutters"],
           "ground": "worn terracotta floor tiles", "sky": "a deep blue night with a big moon"}


def painting(production):
    """Real pictures: a diorama set's pieces are built from them."""
    from PIL import Image

    def wait(jobs):
        for name in jobs:
            Image.new("RGB", (48, 64), (200, 110, 60)).save(production.root / f"{name}.png")
        return {name: f"{name}.png" for name in jobs}
    production.wait = wait


def test_a_diorama_set_draws_facades_a_ground_and_a_sky_and_builds_its_pieces(tmp_path):
    production = Production(tmp_path)
    painting(production)
    spec = {"style": {"image": "felt puppets, two figurines dancing"}, "sets": {"plaza": DIORAMA}}
    check_models(spec)
    make_models(production, spec, sleep=lambda _: None)
    drawn = {image["key"]: image for image in production.images}
    assert sorted(drawn) == ["set-plaza-ground", "set-plaza-house-1", "set-plaza-house-2", "set-plaza-sky"]
    assert drawn["set-plaza-house-1"]["res"] == "768x1024" and "wall fills the entire picture" in drawn["set-plaza-house-1"]["prompt"]
    assert "a pale yellow house" in drawn["set-plaza-house-1"]["prompt"] and "figurines" not in drawn["set-plaza-house-1"]["prompt"]
    assert "seamless tileable" in drawn["set-plaza-ground"]["prompt"] and drawn["set-plaza-sky"]["res"] == "1664x928"
    for part in ("ground", "sky"):
        prompt = drawn[f"set-plaza-{part}"]["prompt"]
        assert "felt puppets" not in prompt and "village square" not in prompt, "no look and no place: they paint a scene"
    made = production.state["sets"]["plaza"]
    assert [house["height"] for house in made["houses"]] == [7.5, 9.0] and made["houses"][0]["width"] == 5.625
    assert made["houses"][0]["source"] == "/api/v1/file/set-piece-plaza-house-1.glb?workspace=w"
    assert (tmp_path / "set-piece-plaza-ground.glb").is_file() and made["ground"]["size"] == 80.0
    resolved = resolve_media({"template": "dance-stage", "background": {"source": "plaza", "layout": "open"}},
                             stills={}, root=tmp_path, workspace="w", sets=production.state["sets"])
    assert resolved["background"] == {"source": made["sky"], "houses": made["houses"], "ground": made["ground"], "layout": "open"}
    calls = len(production.images)
    make_models(production, spec, sleep=lambda _: None)
    assert len(production.images) == calls, "a built set is not drawn again"
    for bad in ({**DIORAMA, "houses": ["one"]}, {**DIORAMA, "sky": ""}, {**DIORAMA, "size": 3}):
        with pytest.raises(ModelError):
            check_models({"sets": {"plaza": bad}})


def test_a_models_height_sizes_its_cast_entries_without_remaking_it(tmp_path):
    production = Production(tmp_path)
    spec = {**SPEC, "models": {**SPEC["models"], "boat": {**SPEC["models"]["boat"], "height": 1.1}}}
    make_models(production, spec, sleep=lambda _: None)
    calls = len(production.calls)

    def scale(**entry):
        resolved = resolve_media({"template": "dance-stage", "cast": {"prop": {"source": "boat", **entry}}},
                                 stills=SPEC["stills"], root=tmp_path, workspace="w", models=production.state["models"])
        return resolved["cast"]["prop"].get("scale")
    assert scale() == round(1.1 / 1.7, 4) and scale(scale=2) == 2
    make_models(production, {**spec, "models": {**spec["models"], "boat": {**spec["models"]["boat"], "height": 3.4}}}, sleep=lambda _: None)
    assert len(production.calls) == calls and scale() == 2.0, "a new height resizes the model, it does not remake it"
    with pytest.raises(ModelError):
        check_models({**SPEC, "models": {"boat": {"from": "boat-pic", "height": "tall"}}})


def test_a_model_meshed_straight_from_its_picture_is_made_again_and_the_others_are_kept(tmp_path):
    from services.production_models import _fingerprint
    production = Production(tmp_path)
    make_models(production, SPEC, sleep=lambda _: None)
    boat = SPEC["models"]["boat"]
    production.state["models"]["boat"]["fingerprint"] = _fingerprint(boat, "/api/v1/uploads/boat.png", SPEC)   # made the old way
    before = len(production.images)
    make_models(production, SPEC, sleep=lambda _: None)
    assert [image["key"] for image in production.images[before:]] == ["model-boat"]


def test_a_glb_in_the_workspace_is_only_rigged_and_a_refused_humanoid_falls_back_to_a_profile(tmp_path):
    (tmp_path / "pack").mkdir()
    for name in ("ape", "parrot"):
        (tmp_path / "pack" / f"{name}.glb").write_bytes(b"glb " + name.encode())
    spec = {"song": {"bpm": 100}, "style": {}, "models": {
        "ape": {"glb": "pack/ape.glb", "rig": "humanoid", "fallback": "prop", "animations": ["idle", "dance_bounce"], "height": 1.9},
        "parrot": {"glb": "pack/parrot.glb", "rig": "flying"}}}
    check_models(spec)
    production = Production(tmp_path)
    plain = production.mcp

    def mcp(operation, args):
        if operation == "model3d.rig.status":
            rig = next(a for o, a in production.calls if o == "model3d.rig" and a["intent_id"] == args["input"]["job_id"].split(":", 1)[1])["input"]
            if rig["engine"] == "humanoid":
                production.calls.append((operation, args))
                return {"status": "failed", "result": {"status": "failed", "error": "not_humanoid: no gap between the legs"}}
        return plain(operation, args)
    production.mcp = mcp
    make_models(production, spec, sleep=lambda _: None)
    assert production.images == [] and submitted(production, "model3d.generate") == [], "a workspace GLB needs no picture and no mesh"
    rigs = submitted(production, "model3d.rig")
    assert [(rig["source"], rig["engine"], rig.get("rig_profile")) for rig in rigs] == [
        ("pack/ape.glb", "humanoid", None), ("pack/parrot.glb", "procedural", "flying"), ("pack/ape.glb", "procedural", "prop")]
    ape = production.state["models"]["ape"]
    assert ape["rigged_as"] == "prop" and "rig_error" not in ape and ape["clips"] == ["hover", "bounce", "spin", "wobble"]
    assert any("humanoid rig refused" in line for line in production.state["log"])
    resolved = resolve_media({"template": "dance-stage", "cast": {"subject_1": {"source": "ape", "clip": "dance_bounce"},
                                                                  "subject_2": {"source": "ape", "clip": "idle"}}},
                             stills={}, root=tmp_path, workspace="w", models=production.state["models"])
    assert resolved["cast"]["subject_1"]["clip"] == {"index": 3, "name": "wobble"}, "a dance stands in as the profile's wobble"
    assert resolved["cast"]["subject_2"]["clip"] == {"index": 0, "name": "hover"} and resolved["cast"]["subject_1"]["scale"] == round(1.9 / 1.7, 4)
    calls = len(production.calls)
    make_models(production, spec, sleep=lambda _: None)
    assert len(production.calls) == calls, "an unchanged GLB is not rigged again"
    for bad in ({"glb": "pack/none.glb"}, {"glb": "pack/ape.glb", "prompt": "an ape"}, {"glb": "pack/ape.glb", "rig": "prop", "fallback": "prop"}):
        with pytest.raises(ModelError):
            check_models({"models": {"x": bad}}) if "none" not in bad.get("glb", "") else make_models(Production(tmp_path), {"style": {}, "models": {"x": bad}}, sleep=lambda _: None)


def test_up_to_twelve_models_are_made_and_up_to_forty_counting_glbs(tmp_path):
    glbs = {f"g{n}": {"glb": f"pack/g{n}.glb", "rig": "prop"} for n in range(28)}
    made = {f"m{n}": {"prompt": "a lamp"} for n in range(12)}
    check_models({"models": {**glbs, **made}})
    for too_many in ({**made, "m12": {"prompt": "a lamp"}}, {**glbs, **made, "g28": {"glb": "pack/x.glb"}}):
        with pytest.raises(ModelError):
            check_models({"models": too_many})


def test_new_animations_on_the_same_mesh_get_their_own_rig_intent(tmp_path):
    """The journal refuses an intent used again with other parameters: re-rigging K. Rool with new clips failed."""
    (tmp_path / "pack").mkdir()
    (tmp_path / "pack" / "king.glb").write_bytes(b"glb king")
    production = Production(tmp_path)
    spec = {"song": {"bpm": 100}, "style": {}, "models": {"king": {"glb": "pack/king.glb", "rig": "humanoid", "animations": ["idle"]}}}
    make_models(production, spec, sleep=lambda _: None)
    spec["models"]["king"]["animations"] = ["idle", "dance_bounce"]
    make_models(production, spec, sleep=lambda _: None)
    intents = [args["intent_id"] for op, args in production.calls if op == "model3d.rig"]
    assert len(intents) == 2 and intents[0] != intents[1]


def test_a_cleaned_copy_is_named_by_the_originals_content_and_the_clean_up(tmp_path, monkeypatch):
    from services import production_models

    (tmp_path / "pack").mkdir()
    (tmp_path / "pack" / "ape.glb").write_bytes(b"glb one")
    written = []

    def fake_clean(source, target, *, standing=False):
        written.append((str(target), standing))
        return ["its vertex colours were normals (rainbow tints)"]

    monkeypatch.setattr("services.glb_cleanup.clean_glb", fake_clean)
    production = Production(tmp_path)
    first = production_models._cleaned(production, "ape", "pack/ape.glb", standing=True)
    assert first.startswith("pack/ape.clean-") and first.endswith(".glb") and written[-1] == (str(tmp_path / first), True)
    assert production_models._cleaned(production, "ape", "pack/ape.glb", standing=True) == first, "the same content keeps its name"
    assert production_models._cleaned(production, "ape", "pack/ape.glb", standing=False) != first, "a different clean-up is another file"
    (tmp_path / "pack" / "ape.glb").write_bytes(b"glb two")
    assert production_models._cleaned(production, "ape", "pack/ape.glb", standing=True) != first, "new content is another file"
    assert "rainbow" in production.state["log"][-1]
    monkeypatch.setattr("services.glb_cleanup.clean_glb", lambda source, target, *, standing=False: [])
    assert production_models._cleaned(production, "ape", "pack/ape.glb", standing=True) == "pack/ape.glb", "a clean model is rigged as it is"


def test_a_humanoid_rig_that_was_lost_falls_back_for_now_and_is_asked_for_again_next_run(tmp_path):
    (tmp_path / "pack").mkdir()
    (tmp_path / "pack" / "ape.glb").write_bytes(b"glb ape")
    spec = {"song": {"bpm": 100}, "style": {}, "models": {
        "ape": {"glb": "pack/ape.glb", "rig": "humanoid", "fallback": "prop", "animations": ["idle", "dance_bounce"], "height": 1.9}}}
    production = Production(tmp_path)
    plain, lost = production.mcp, [True]

    def mcp(operation, args):
        if operation == "model3d.rig.status" and lost[0]:
            rig = next(a for o, a in production.calls if o == "model3d.rig" and a["intent_id"] == args["input"]["job_id"].split(":", 1)[1])["input"]
            if rig["engine"] == "humanoid":
                production.calls.append((operation, args))
                return {"status": "failed", "result": {"status": "failed", "error": "not admitted: Too many queued"}}
        return plain(operation, args)
    production.mcp = mcp
    make_models(production, spec, sleep=lambda _: None)
    ape = production.state["models"]["ape"]
    assert ape["rigged_as"] == "prop" and ape["file"] and ape["clips"] == ["hover", "bounce", "spin", "wobble"], "the video gets made"
    assert "not admitted" in ape["rig_error"] and any("asks for it again" in line for line in production.state["log"])
    lost[0] = False
    make_models(production, spec, sleep=lambda _: None)
    engines = [rig["engine"] for rig in submitted(production, "model3d.rig")]
    assert engines == ["humanoid", "procedural", "humanoid"], "the next run asks for the humanoid rig again"
    assert "rig_error" not in production.state["models"]["ape"] and "rigged_as" not in production.state["models"]["ape"]


PARALLAX = {"kind": "parallax", "prompt": "the ruins of a forest temple at dusk", "seed": 3,
            "far": "mountains and a castle silhouette under a violet sunset sky", "mid": "broken stone arches and tall pines",
            "near": "ferns and a mossy branch", "ground": "mossy flagstones"}


def test_a_parallax_set_draws_its_far_view_layers_and_ground_and_keys_the_layers(tmp_path):
    production = Production(tmp_path)
    painting(production)
    spec = {"style": {"image": "Painted fantasy world; characters are tiny felt heroes with button eyes; soft light."}, "sets": {"temple": PARALLAX}}
    check_models(spec)
    make_models(production, spec, sleep=lambda _: None)
    drawn = {image["key"]: image for image in production.images}
    assert sorted(drawn) == ["set-temple-far", "set-temple-ground", "set-temple-mid", "set-temple-near"]
    assert "chroma-key green" in drawn["set-temple-mid"]["prompt"] and "open space in the middle" in drawn["set-temple-mid"]["prompt"]
    assert "chroma-key green" in drawn["set-temple-near"]["prompt"] and "edges" in drawn["set-temple-near"]["prompt"]
    assert "chroma-key" not in drawn["set-temple-far"]["prompt"] and "forest temple" in drawn["set-temple-far"]["prompt"]
    assert "Painted fantasy world" in drawn["set-temple-mid"]["prompt"] and "heroes" not in drawn["set-temple-mid"]["prompt"], "the look, not the cast"
    assert "seamless tileable" in drawn["set-temple-ground"]["prompt"] and drawn["set-temple-mid"]["res"] == "1664x928"
    made = production.state["sets"]["temple"]
    assert made["kind"] == "parallax" and made["key"] == "#00ff00" and made["sky"].endswith("far.png")
    assert [layer["depth"] for layer in made["layers"]] == ["mid", "near"] and made["layers"][0]["source"].endswith("mid.png")
    assert (tmp_path / "set-piece-temple-ground.glb").is_file() and made["ground"]["size"] == 80.0
    resolved = resolve_media({"template": "dance-stage", "background": "temple"}, stills={}, root=tmp_path, workspace="w", sets=production.state["sets"])
    assert resolved["background"] == {"source": made["sky"], "layers": made["layers"], "key": "#00ff00", "ground": made["ground"]}
    calls = len(production.images)
    make_models(production, spec, sleep=lambda _: None)
    assert len(production.images) == calls, "a built set is not drawn again"
    for bad in ({**PARALLAX, "mid": ""}, {k: v for k, v in PARALLAX.items() if k != "ground"}, {**PARALLAX, "roof": "tiles"}):
        with pytest.raises(ModelError, match="sets.temple"):
            check_models({"style": {}, "sets": {"temple": bad}})
