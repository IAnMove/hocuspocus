"""A plan that would look thin is refused before GPU work; dry_run says why and warns about the rest."""
import asyncio
import json

import pytest
from fastapi import HTTPException

from services.music_production import command_handlers
from services.production_dry_run import dry_run
from services.production_quality_gate import _brought, blocking_problems, gate, plan_warnings, refusal_message

SONG = {"lyrics": "[Verse]\nla luz se queda", "caption": "lullaby", "duration": 40, "bpm": 96}


def card(key, t0, **extra):
    return {"key": key, "kind": "still", "still": "card-base", "t0": t0, **extra}


def h3(key, t0, **extra):
    return {"key": key, "kind": "h3", "t0": t0, "frame": "a lighthouse", "action": "the beam sweeps", **extra}


def pattern_spec():
    """The Ocho luces v2 shape: the title card panned again and again between clips."""
    shots = [card("s00", 0, allow=["still", "dark"])]
    for index, t0 in enumerate((3, 9, 11, 17, 19, 25, 27), start=1):
        shots.append(h3(f"h{index}", t0) if index % 2 else card(f"c{index}", t0, plannedActed2D="a gull flies"))
    shots.append(card("s99", 37, allow=["still", "dark"]))
    return {"title": "Faro", "song": SONG, "style": {}, "shots": shots}


def test_one_picture_panned_across_many_shots_is_refused_but_title_cards_are_not():
    problems = blocking_problems(pattern_spec())
    assert [item["code"] for item in problems] == ["still_reused"]
    assert problems[0]["shots"] == ["c2", "c4", "c6"]
    spec = pattern_spec()
    spec["shots"] = [shot for shot in spec["shots"] if shot["key"] not in ("c4", "c6")]
    assert blocking_problems(spec) == []


def test_too_much_still_runtime_is_refused_at_the_quality_bar():
    shots = [card("a", 0), {**card("b", 10), "still": "other"}, h3("c", 20)]
    problems = blocking_problems({"song": SONG, "shots": shots})
    assert problems == [{"code": "too_static", "ratio": 0.5, "limit": 0.35, "shots": ["a", "b"], "message": problems[0]["message"],
                         "hint": problems[0]["hint"]}]
    assert blocking_problems({"song": SONG, "shots": shots, "quality": "draft"}) == []


def test_a_full_frame_title_over_a_moving_shot_is_refused_but_a_title_card_on_a_still_is_not():
    shots = [card("s00", 0, title={"template": "title-card", "fields": {"title": "Faro"}}),
             h3("h1", 4, title={"template": "title-card", "fields": {"title": "toma 2"}}),
             {"key": "d1", "kind": "scene3d", "t0": 8, "scene3d": {"template": "cine-dolly-in"},
              "title": {"template": "trailer-slam", "fields": {"lines": "toma 3|dolly"}}},
             h3("h2", 12, title={"template": "lower-third-date", "fields": {"date": "04", "caption": "dolly"}}),
             h3("h3", 16, title={"template": "title-card", "fields": {"title": "fin"}}, allow=["title_card"])]
    problems = blocking_problems({"song": SONG, "shots": shots})
    assert [(item["code"], item.get("shots")) for item in problems] == [("title_card_hides_shot", ["h1", "d1"])]


def test_dry_run_reports_blocking_and_the_warnings_that_explain_thin_plans(tmp_path):
    spec = pattern_spec()
    spec["shots"].append({"key": "r1", "kind": "clip", "clip": "h1", "t0": 38})
    spec["shots"].append({"key": "r2", "kind": "clip", "clip": "h1", "t0": 38.5})
    spec["cast"] = [{"id": "hero", "sheet_prompt": "a felt hero"}]
    report = dry_run(spec, root=tmp_path)
    assert [item["code"] for item in report["blocking"]] == ["still_reused"]
    codes = {item["code"]: item for item in report["warnings"]}
    assert codes["ignored_shot_field"]["field"] == "plannedActed2D"
    assert codes["clip_replayed"]["shots"] == ["r1", "r2"]
    assert codes["h3_without_cast"]["shots"] == ["h1", "h3", "h5", "h7"]


def test_boxes_unanimated_rigs_and_one_template_everywhere_are_warned(tmp_path):
    (tmp_path / "boat.glb").write_bytes(b"glb")
    (tmp_path / "boat.meta.json").write_text(json.dumps({"generation": {"model": {"id": "procedural-compose"}}}))
    shots = [{"key": f"d{i}", "kind": "scene3d", "t0": i * 4,
              "scene3d": {"template": "dance-stage", "cast": {"subject_1": "hero", "prop": "/api/v1/file/boat.glb?workspace=w"}}}
             for i in range(5)]
    spec = {"song": SONG, "cast": [{"id": "hero", "sheet_prompt": "x"}], "models": {"hero": {"from": "hero"}}, "shots": shots}
    codes = {item["code"]: item for item in plan_warnings(spec, tmp_path)}
    assert codes["procedural_model"]["model"] == "boat.glb" and len(codes["procedural_model"]["shots"]) == 5
    assert codes["model_not_animated"]["objects"][0] == "d0:subject_1"
    assert codes["template_reused"]["template"] == "dance-stage"
    shots[0]["scene3d"]["cast"]["subject_1"] = {"source": "hero", "clip": "dance_bounce"}
    assert "d0:subject_1" not in {item["code"]: item for item in plan_warnings(spec, tmp_path)}["model_not_animated"]["objects"]


def test_a_copied_structure_or_lyric_look_from_a_sibling_piece_is_warned(tmp_path):
    spec = {**pattern_spec(), "style": {"lyric_template": "social-caption", "lyric_style": {"box": {"kind": "solid"}}}}
    (tmp_path / "piece-1.production.json").write_text(json.dumps({"spec": spec}))
    codes = [item["code"] for item in plan_warnings(spec, tmp_path, "piece-2")]
    assert "same_shot_pattern" in codes and "same_lyric_look" in codes
    assert plan_warnings(spec, tmp_path, "piece-1") == [item for item in plan_warnings(spec, tmp_path, "piece-1")
                                                         if item["code"] not in ("same_shot_pattern", "same_lyric_look")]


def test_run_refuses_a_new_thin_plan_but_resumes_one_already_running(tmp_path, monkeypatch):
    started = []

    class _Thread:
        def __init__(self, target, args, name, daemon):
            self.target = target

        def start(self):
            started.append(self.target)

        def is_alive(self):
            return False

    monkeypatch.setattr("services.music_production.threading.Thread", _Thread)
    monkeypatch.setattr("services.music_production.validate_spec", lambda spec: spec)
    monkeypatch.setattr("services.music_production.require_free_disk", lambda _root: None)
    handlers = command_handlers(lambda _name: str(tmp_path), lambda: str(tmp_path), lambda: "http://127.0.0.1:9", lambda: "token")
    body = {"version": 1, "input": {"workspace": "w", "production_id": "faro", "spec": pattern_spec()}}
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers["production.run"](body))
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "quality_gate"
    assert caught.value.detail["problems"][0]["code"] == "still_reused"
    assert started == []
    (tmp_path / "faro.production.json").write_text(json.dumps({"spec": pattern_spec(), "status": "failed"}))
    assert asyncio.run(handlers["production.run"](body))["result"]["running"] is True
    assert len(started) == 1


def test_a_3d_shot_asking_a_model_for_a_clip_its_rig_will_not_bake_is_refused():
    models = {"lia": {"prompt": "a girl", "rig": "humanoid", "animations": ["idle", "cheer"]},
              "kite": {"prompt": "a kite", "rig": "flying"},
              "ape": {"glb": "pack/ape.glb", "rig": "humanoid", "fallback": "prop"}}

    def shot3d(key, cast):
        return {"key": key, "kind": "scene3d", "t0": 0, "scene3d": {"template": "cine-medium-shot", "cast": cast}}
    shots = [shot3d("a", {"subject_1": {"source": "lia", "clip": "cheer"}}),
             shot3d("b", {"subject_1": {"source": "lia", "clip": "wave"}}),
             shot3d("c", {"subject_1": {"source": "kite", "clip": "Strafe Loop"}}),
             shot3d("d", {"subject_1": {"source": "ape", "clip": "dance_bounce"}}),
             shot3d("e", {"subject_1": {"source": "/api/v1/file/x.glb?workspace=w", "clip": "anything"}}),
             shot3d("f", {"subject_1": {"source": "ape", "clip": "look_around"}})]
    problems = blocking_problems({"song": SONG, "models": models, "shots": shots})
    assert [(item["code"], item["shots"]) for item in problems] == [("clip_not_baked", ["b:subject_1 wave", "f:subject_1 look_around"])], \
        "a humanoid with a fallback still only bakes its animations"


def test_a_glb_played_as_it_is_passes_the_gate_with_the_clips_it_brought(tmp_path):
    import struct

    body = json.dumps({"asset": {"version": "2.0"}, "animations": [{"name": "zelda_armature_zelda_wait_a"}]}).encode()
    body += b" " * (-len(body) % 4)
    (tmp_path / "pack").mkdir()
    (tmp_path / "pack" / "zelda.glb").write_bytes(b"glTF" + struct.pack("<II", 2, 20 + len(body)) + struct.pack("<II", len(body), 0x4E4F534A) + body)
    models = {"zelda": {"glb": "pack/zelda.glb", "rig": "none"}, "ghost": {"prompt": "a ghost", "rig": "none"}}

    def shot3d(key, cast):
        return {"key": key, "kind": "scene3d", "t0": 0, "scene3d": {"template": "cine-medium-shot", "cast": cast}}
    shots = [shot3d("a", {"subject_1": {"source": "zelda", "clip": "zelda_armature_zelda_wait_a"}}),
             shot3d("b", {"subject_1": {"source": "zelda", "clip": "dance_side"}}),
             shot3d("c", {"subject_1": {"source": "ghost", "clip": "hover"}})]
    problems = blocking_problems({"song": SONG, "models": models, "shots": shots}, tmp_path)
    assert [(item["code"], item["shots"]) for item in problems] == [("clip_not_baked", ["b:subject_1 dance_side", "c:subject_1 hover"])]
    assert blocking_problems({"song": SONG, "models": models, "shots": shots[:1]}) == [], "with no workspace at hand the file is trusted"
    assert _brought({"glb": "../zelda.glb", "rig": "none"}, tmp_path) is None
    assert _brought({"glb": "pack/../zelda.glb", "rig": "none"}, tmp_path) is None


def test_two_shots_starting_together_do_not_break_the_gate():
    assert blocking_problems({"song": SONG, "shots": [h3("a", 0), h3("b", 0)]}) == []


def stage(key, template="stage-sala", **more):
    return {"key": key, "kind": "scene3d", "t0": 0, "scene3d": {"template": template, "cast": {"subject_1": "hero"}, **more}}


def test_a_stage_in_its_mold_colours_is_warned_once_per_set_or_template(tmp_path):
    sets = {"office": {"kind": "room", "mold": "despacho", "skin": {"wall_back": {"image": "shelves"}}},
            "plain": {"kind": "room", "mold": "sala", "skin": {"wall_left": {"color": "#112233"}}},
            "bare": {"kind": "room", "mold": "cocina"}}
    shots = [stage("a"), stage("b", roomCamera="ots_a"), stage("c", "stage-plaza"), stage("d", "two-shot", background="office"),
             stage("e", "two-shot", background="plain"), stage("f", "two-shot", background="bare"), stage("g", "two-shot", background="bare"),
             stage("h", "two-shot", background={"room": {"mold": {"id": "sala"}, "skin": {"floor": {"texture": {"asset": "t.png"}}}}})]
    spec = {"song": SONG, "cast": [{"id": "hero", "sheet_prompt": "x"}], "models": {"hero": {"from": "hero"}}, "sets": sets, "shots": shots}
    found = [(item["set"], item["shots"]) for item in plan_warnings(spec, tmp_path) if item["code"] == "stage_unskinned"]
    assert found == [("stage-sala", ["a", "b"]), ("stage-plaza", ["c"]), ("plain", ["e"]), ("bare", ["f", "g"])]
    hint = next(item["hint"] for item in plan_warnings(spec, tmp_path) if item["code"] == "stage_unskinned")
    assert "sets" in hint and "skin" in hint


def test_the_same_template_place_and_camera_in_more_than_four_shots_in_a_row_looks_samey(tmp_path):
    spec = {"song": SONG, "cast": [{"id": "hero", "sheet_prompt": "x"}], "models": {"hero": {"from": "hero"}},
            "shots": [stage(f"s{i}", roomCamera="ots_a") for i in range(5)]}
    samey = [item for item in plan_warnings(spec, tmp_path) if item["code"] == "looks_samey"]
    assert len(samey) == 1 and samey[0]["template"] == "stage-sala" and samey[0]["background"] is None
    assert samey[0]["camera"][0] == "ots_a"
    assert samey[0]["shots"] == ["s0", "s1", "s2", "s3", "s4"] and "roomCamera" in samey[0]["hint"]
    assert not [item for item in plan_warnings(spec, tmp_path) if item["code"] == "template_repeated"], "said once, as looks_samey"
    spec["shots"][2] = h3("cut", 8)
    assert not [item for item in plan_warnings(spec, tmp_path) if item["code"] == "looks_samey"], "a cut away ends the run"
    spec["shots"] = [stage(f"o{i}", "two-shot", background="office") for i in range(4)] + [stage("p", "two-shot", background="park")]
    assert not [item for item in plan_warnings(spec, tmp_path) if item["code"] == "looks_samey"], "four in a row is a scene"
    spec["shots"].append(stage("q", "two-shot", background="park"))
    spec["shots"] += [stage(f"r{i}", "two-shot", background="park") for i in range(4)]
    assert [item["shots"] for item in plan_warnings(spec, tmp_path) if item["code"] == "looks_samey"] == [["p", "q", "r0", "r1", "r2", "r3"]]


def codes_of(items, code):
    return [item for item in items if item["code"] == code]


def test_alternating_cameras_over_one_set_are_not_samey_and_a_camera_change_ends_the_run(tmp_path):
    cameras = [{"roomCamera": ("ots_a", "ots_b")[i % 2]} for i in range(6)]
    spec = {"song": SONG, "shots": [stage(f"s{i}", **more) for i, more in enumerate(cameras)]}
    found = plan_warnings(spec, tmp_path)
    assert not codes_of(found, "looks_samey") and not codes_of(found, "template_repeated")
    still = [stage(f"s{i}") for i in range(3)]
    for key, more in (("frame", {"frame": "wide"}), ("camera_template", {"camera_template": "cine-dolly-in"}), ("lens", {"lens": "85mm"})):
        spec["shots"] = still + [stage(f"t_{key}", **more)] + [stage(f"u{i}", **more) for i in range(3)]
        assert not codes_of(plan_warnings(spec, tmp_path), "looks_samey"), f"{key} is part of the run's camera"
    spec["shots"] = [stage("a"), stage("b", roomCamera="two_shot")]
    assert [item["shots"] for item in codes_of(plan_warnings(spec, tmp_path), "template_repeated")] == [["a", "b"]], "two_shot is the default"


def test_one_template_with_one_camera_in_two_shots_in_a_row_is_repeated_whatever_the_place(tmp_path):
    spec = {"song": SONG, "shots": [stage("a", "two-shot", background="office"), stage("b", "two-shot", background="park"),
                                    stage("c", "two-shot", background="park", roomCamera="ots_a"), h3("cut", 8),
                                    stage("d", "two-shot", background="park", roomCamera="ots_a")]}
    found = codes_of(plan_warnings(spec, tmp_path), "template_repeated")
    assert [(item["template"], item["shots"]) for item in found] == [("two-shot", ["a", "b"])]
    assert found[0]["camera"][0] == "two_shot" and "roomCamera" in found[0]["hint"]
    assert not codes_of(plan_warnings(spec, tmp_path), "looks_samey"), "a warning, and not the samey run"
    assert blocking_problems(spec) == [], "a repeat is only a warning"


def fit(key, template, **config):
    return {"key": key, "kind": "scene3d", "t0": 0, "scene3d": {"template": template, **config}}


def test_an_unknown_template_is_refused_before_any_gpu_work_with_the_closest_ids():
    shots = [fit("a", "speech-portriat", cast={"subject_1": "x.glb"}), fit("b", "speech-portriat", cast={"subject_1": "x.glb"}),
             fit("c", "qqq-zzz", cast={"subject_1": "x.glb"}), fit("d", "speech-portrait", cast={"subject_1": "x.glb"}),
             fit("e", "stage-sala", cast={"subject_1": "x.glb"}), fit("f", "stage-salas", cast={"subject_1": "x.glb"}),
             fit("g", "speech-portrait", world="stage-sala", cast={"subject_1": "x.glb"})]
    spec = {"song": SONG, "shots": shots, "fill": [fit("", "speech-portriat", cast={"subject_1": "x.glb"})]}
    found = {(item["field"], item["template"]): item for item in blocking_problems(spec) if item["code"] == "unknown_template"}
    assert set(found) == {("template", "speech-portriat"), ("template", "qqq-zzz"), ("template", "stage-salas"), ("world", "stage-sala")}
    typo = found[("template", "speech-portriat")]
    assert typo["shots"] == ["a", "b", "fill[0]"] and typo["suggestions"][0] == "speech-portrait"
    assert 'Did you mean "speech-portrait"' in typo["message"] and "after the GPU work" in typo["message"] and typo["hint"]
    assert typo["message"].startswith('Shots "a", "b" and "fill[0]" name the template'), "the verb agrees with the shots"
    assert found[("world", "stage-sala")]["message"].startswith('Shot "g" names the world'), "one shot, one verb"
    assert found[("template", "stage-salas")]["suggestions"][0] == "stage-sala"
    assert found[("template", "qqq-zzz")]["suggestions"] == [] and "Did you mean" not in found[("template", "qqq-zzz")]["message"]
    assert "stage-sala" not in found[("world", "stage-sala")]["suggestions"], "a stage is a template, never a world"


def test_an_unknown_template_is_not_a_thin_check_so_allow_thin_never_skips_it():
    spec = {"song": SONG, "shots": [fit("a", "nope-nope", cast={"subject_1": "x.glb"})]}
    refused, allowed = gate(spec, allow_thin=True)
    assert [item["code"] for item in refused] == ["unknown_template"] and allowed == []
    assert "allow_thin does not skip them" in refusal_message(refused) and '"nope-nope"' in refusal_message(refused)
    assert [item["code"] for item in dry_run(spec)["blocking"]] == ["unknown_template"]


def test_a_cast_role_the_card_does_not_have_is_refused_and_names_the_roles_it_has():
    cast = {"subject_1": "x.glb", "subject_2": "y.glb"}
    spec = {"song": SONG, "shots": [fit("a", "speech-portrait", cast=cast), fit("b", "speech-portrait", cast=cast),
                                    fit("c", "speech-dialogue", cast=cast)]}
    found = codes_of(blocking_problems(spec), "cast_role_not_on_card")
    assert [(item["template"], item["role"], item["shots"], item["roles"]) for item in found] == [
        ("speech-portrait", "subject_2", ["a", "b"], ["subject_1"])]
    assert 'only has the roles "subject_1"' in found[0]["message"] and '"subject_2"' in found[0]["message"]
    assert found[0]["message"].startswith('Shots "a" and "b" cast "subject_2"'), "the verb agrees with the shots"
    assert "add: true" in found[0]["message"]


def test_only_a_role_the_card_proves_missing_is_refused():
    ok = {"subject_1": "x.glb"}
    shots = [fit("obj", "speech-portrait", cast={**ok, "rival": "y.glb"}),
             fit("add", "speech-portrait", cast={**ok, "subject_2": {"source": "y.glb", "add": True}}),
             fit("group", "speech-portrait", cast={**ok, "subject_2": {"sources": ["y.glb", "z.glb"]}}),
             fit("slots", "speech-portrait", slots=[{"sourceUrl": "a.glb"}, {"sourceUrl": "b.glb"}], cast={"subject_2": "y.glb"}),
             fit("stage", "stage-sala", cast={**ok, "subject_2": "y.glb"}),
             fit("document", "speech-portrait", cast=ok)]
    shots[-1]["scene3d"] = {"document": {"slots": []}, "cast": {"subject_2": "y.glb"}}
    assert codes_of(blocking_problems({"song": SONG, "shots": shots}), "cast_role_not_on_card") == []
    bad = [fit("prop", "stage-sala", cast={**ok, "prop": "y.glb"}), fit("subject", "establishing", subject="x.glb"),
           fit("back", "speech-portrait", cast={**ok, "background": "plate.png"})]
    found = {(item["template"], item["role"]): item for item in codes_of(blocking_problems({"song": SONG, "shots": bad}), "cast_role_not_on_card")}
    assert set(found) == {("stage-sala", "prop"), ("establishing", "subject_1"), ("speech-portrait", "background")}
    assert found[("stage-sala", "prop")]["roles"] == ["subject_1", "subject_2", "background"], "a stage binds on two-shot"


def test_a_frame_the_card_is_not_drawn_for_is_a_warning_with_a_hint_not_a_refusal():
    cast = {"subject_1": "x.glb"}
    spec = {"song": SONG, "shots": [fit("a", "speech-portrait", width=720, height=1280, cast=cast),
                                    fit("b", "speech-portrait", height=1600, cast=cast),
                                    fit("c", "speech-portrait", width=1920, height=1080, cast=cast),
                                    fit("d", "topdown-dragon-portals", cast=cast),
                                    fit("e", "topdown-dragon-portals", width=720, height=1280, cast=cast),
                                    fit("f", "topdown-dragon-portals", width=1920, height=1080, cast=cast)]}
    found = {tuple(item["shots"]): item for item in codes_of(plan_warnings(spec), "template_format")}
    assert set(found) == {("a", "b"), ("d",), ("f",)}
    assert (found[("a", "b")]["card_format"], found[("a", "b")]["shot_format"]) == ("landscape", "portrait")
    assert "portrait card frames better" in found[("a", "b")]["hint"] and "format: portrait" in found[("a", "b")]["hint"]
    assert (found[("d",)]["card_format"], found[("d",)]["shot_format"]) == ("portrait", "landscape")
    assert "cropped" in found[("d",)]["hint"], "no width or height: the production frame is 16:9"
    assert "adapts its camera" in found[("f",)]["hint"]
    assert blocking_problems(spec) == [], "the compiler adapts the camera"
