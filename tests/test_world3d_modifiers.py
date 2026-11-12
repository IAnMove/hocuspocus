"""Named lights, grades, lenses and camera cards: one table for the production compiler and world3d.scene.patch."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

from fastapi import HTTPException
import jsonschema
import pytest

from services.production_scene3d import LIGHTS, compile_document, validate_scene3d_shot
from services.world3d_grades import GRADE_FX_PREFIX, GRADE_NAMES, apply_grade, grade_cues
from services.world3d_modifiers import (
    LENS_FOV_RANGE, LENS_NAMES, LIGHT_NAMES, apply_camera_template, apply_lens, apply_light, card_kind, check_camera_template,
    light_object, modifier_tables, named_light, tinted,
)
from services.world3d_scenes import World3DSceneError, patch_scene
from services.world3d_template_catalog import World3DTemplateError
from services.world3d_template_commands import command_catalog, execute_command

ROOT = Path(__file__).resolve().parents[1]
LOADER = ROOT / "ui/node_modules/tsx/dist/loader.mjs"
NODE = pytest.mark.skipif(not LOADER.is_file(), reason="UI dependencies not installed in Python-only CI")
TECHNIQUES = {item["id"]: item for item in json.loads((ROOT / "ui/src/features/scene3d/cinematicTechniques.json").read_text(encoding="utf-8"))}
FX_KINDS = {item["id"] for item in json.loads((ROOT / "app/shared/scene_effects.json").read_text(encoding="utf-8"))}
CONTRACT_LIGHTS = ("noon", "golden", "overcast", "night", "neon", "stage", "campfire", "rembrandt", "butterfly", "split", "low_key",
                   "high_key", "candle", "backlight", "window", "moonlight", "under", "hard", "soft", "dusk", "dawn")
CONTRACT_GRADES = ("natural", "teal_orange", "bleach", "noir", "sepia", "flashback", "dream", "giallo", "cold", "warm", "vhs", "film")
CONTRACT_LENSES = ("14mm", "24mm", "35mm", "50mm", "85mm", "135mm", "200mm")
HERO = {"subject_1": "/api/v1/file/a.glb?workspace=t"}
# The same calls, in the same order, that the TypeScript twin runs in test_python_and_typescript_apply_the_same_modifiers.
MIRROR_SCRIPT = """
import { readFileSync } from 'node:fs'
const m = await import(process.argv[1])
const { document, steps } = JSON.parse(readFileSync(0, 'utf8'))
const apply = { light: m.applyNamedLight, lens: m.applyLens, grade: m.applyGrade }
for (const [kind, name] of steps) apply[kind](document, name)
process.stdout.write(JSON.stringify({ document, tables: m.MODIFIERS }))
"""


def cast_shot(**config):
    return {"key": "cast", "kind": "scene3d", "t0": 0, "scene3d": {"template": "cine-dolly-in", **config}}


def document(**extra):
    return {"version": 1, "units": "meters", "up": "y", "duration": 4, "width": 1280, "height": 720, "fps": 24, "templateId": "two-shot",
            "slots": [], "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0]},
            "light": {"kind": "directional", "direction": [-0.35, -1, -0.25], "intensity": 1.15, "color": "#fff4e5"},
            "sfx": [{"id": "template-lines", "kind": "speedlines", "start": 0, "end": 2}], **extra}


def framed_document(**extra):
    camera = {"family": "follow", "fov": 48, "eye": [0, 2, 5], "look": [0, 1, 0],
              "framing": {"targetSlot": "subject_1", "anchor": "head", "from": [0, 0.04, 2.55], "to": [0, 0.02, 2.15], "fovFrom": 48, "fovTo": 30}}
    subject = {"id": "subject_1", "slot": "subject_1", "media": "model3d", "sourceUrl": "", "position": [0, 0, 0], "rotationY": 0, "scale": 1, "clip": None}
    return document(camera=camera, slots=[subject], **extra)


def scene_file(tmp_path, scene_id, doc):
    workspace_dir = lambda name: str(tmp_path / name)
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{scene_id}.json").write_text(json.dumps({"revision": 1, "templateId": doc["templateId"], "document": doc, "warnings": []}),
                                             encoding="utf-8")
    return workspace_dir


def finite(values):
    return all(isinstance(value, (int, float)) and math.isfinite(value) for value in values)


def test_named_lights_cover_the_contract_resolve_to_finite_numbers_and_match_their_technique():
    assert set(LIGHT_NAMES) == set(CONTRACT_LIGHTS) and LIGHTS is LIGHT_NAMES
    for name in LIGHT_NAMES:
        light = named_light(name)
        assert light["kind"] == "directional" and len(light["direction"]) == 3 and finite(light["direction"])
        assert finite([light["intensity"], light["ambient"]]) and light["intensity"] > 0 and 0 <= light["ambient"] <= 4
        assert len(light["color"]) == 7 and light["color"].startswith("#")
        source = modifier_tables()["lights"][name].get("source")
        if source:
            authored = TECHNIQUES[source]["light"]
            assert (light["direction"], light["intensity"], light["color"]) == (authored["direction"], authored["intensity"], authored["color"]), name
    doc = document(lighting={"environment": {"source": "hdri", "asset": "/sky.hdr", "intensity": 2, "rotation": 90, "background": "set", "blur": 0}})
    apply_light(doc, "candle")
    assert doc["light"] == {"kind": "directional", "direction": [0.35, -0.22, -0.55], "intensity": 1.25, "color": "#ff9a45"}
    assert doc["lighting"]["environment"]["intensity"] == 0.08 and doc["lighting"]["environment"]["asset"] == "/sky.hdr", "only the ambient share changes"
    bare = document()
    apply_light(bare, "dawn")
    assert bare["lighting"]["environment"] == {"source": "room", "rotation": 0, "background": "set", "blur": 0, "intensity": 0.45}
    for bad in ("torch", "", None, 3):
        with pytest.raises(ValueError, match="unknown_light"):
            named_light(bad)


def test_a_light_object_is_checked_and_normalized():
    assert light_object({"direction": [1, -1, 0], "intensity": 2, "color": "#FFAA00"}) == \
        {"kind": "directional", "direction": [1.0, -1.0, 0.0], "intensity": 2.0, "color": "#ffaa00"}
    for bad in ({"direction": [1, -1], "intensity": 2, "color": "#ffaa00"}, {"direction": [1, -1, 0], "intensity": 11, "color": "#ffaa00"},
                {"direction": [1, -1, 0], "intensity": 1, "color": "amber"}, {"kind": "point", "direction": [1, -1, 0], "intensity": 1, "color": "#ffaa00"},
                {"direction": [1, -1, 0], "intensity": 1, "color": "#ffaa00", "shadow": True}, "noon", []):
        with pytest.raises(ValueError, match="light"):
            light_object(bad)


def test_every_grade_expands_to_a_look_a_gel_and_grade_effects_that_a_later_grade_replaces():
    assert set(GRADE_NAMES) == set(CONTRACT_GRADES)
    for name in GRADE_NAMES:
        doc = document()
        apply_grade(doc, name)
        assert doc["look"]["toneMapping"] in ("aces", "agx", "neutral") and -4 <= doc["look"]["exposure"] <= 4, name
        assert doc["sfx"][0] == {"id": "template-lines", "kind": "speedlines", "start": 0, "end": 2}, "the template's effects stay"
        graded = doc["sfx"][1:]
        assert all(cue["id"] == f"{GRADE_FX_PREFIX}{cue['kind']}" and cue["kind"] in FX_KINDS and (cue["start"], cue["end"]) == (0, 4)
                   and 0.1 <= cue["intensity"] <= 2 for cue in graded), name
        assert graded == grade_cues(name, 4)
    kinds = lambda name: [cue["kind"] for cue in grade_cues(name, 4)]
    assert kinds("flashback") == ["vignette", "film_grain"] and kinds("dream") == ["light_rays"] and kinds("noir") == ["vignette"]
    assert kinds("vhs") == ["vhs", "scanline"] and kinds("film") == ["film_grain"] and kinds("natural") == []
    doc = document()
    apply_grade(doc, "flashback")
    apply_grade(doc, "film")
    assert [cue["id"] for cue in doc["sfx"]] == ["template-lines", "grade-film_grain"], "a later grade replaces the earlier one's effects"
    with pytest.raises(ValueError, match="unknown_grade"):
        apply_grade(doc, "pastel")


def test_a_grade_tints_the_ungraded_lamp_and_natural_takes_the_gel_off():
    doc = document()
    apply_grade(doc, "cold")
    assert doc["light"]["color"] == tinted("#fff4e5", "#7ea2ff") == "#7e9be5" and doc["light"]["untinted"] == "#fff4e5"
    apply_grade(doc, "warm")
    assert doc["light"]["color"] == tinted("#fff4e5", "#ffbf70"), "the second grade tints the lamp, not the first tint"
    apply_grade(doc, "natural")
    assert doc["light"] == document()["light"], "no gel: the lamp is back to its own colour"
    apply_light(doc, "noon")
    apply_grade(doc, "sepia")
    assert doc["light"]["untinted"] == "#fffaf0", "a named light starts from a clean lamp"
    assert tinted("#ffffff", "#7ea2ff") == "#7ea2ff" and tinted("#fff", "#7ea2ff") == "#7ea2ff" and tinted("#808080", "#808080") == "#404040"
    assert tinted("blue", "#ffffff") == "blue", "an unreadable colour is kept"


def test_lenses_take_the_technique_fov_and_scale_a_framing_zoom_within_bounds():
    assert set(LENS_NAMES) == set(CONTRACT_LENSES)
    for name, lens in modifier_tables()["lenses"].items():
        assert lens["fov"] == TECHNIQUES[lens["source"]]["fov"], name
    doc = framed_document()
    apply_lens(doc, "135mm")
    assert doc["camera"]["fov"] == 18 and doc["camera"]["framing"]["fovFrom"] == 18 and doc["camera"]["framing"]["fovTo"] == 11.25
    assert doc["camera"]["framing"]["from"] == [0, 0.04, 2.55], "the move itself is untouched"
    long = framed_document()
    apply_lens(long, "200mm")
    assert long["camera"]["framing"]["fovTo"] == LENS_FOV_RANGE[0], "a zoom tighter than the parser allows is held at the bound"
    plain = document()
    apply_lens(plain, "14mm")
    assert plain["camera"]["fov"] == 96 and "framing" not in plain["camera"]
    with pytest.raises(ValueError, match="unknown_lens"):
        apply_lens(plain, "500mm")


def test_camera_cards_are_the_camera_families_and_other_kinds_are_refused():
    assert card_kind({"family": "framing"}) == "camera" and card_kind({"family": "lighting"}) is None
    assert card_kind({"kind": "look", "family": "framing"}) == "look", "a card's own kind wins once the catalog carries it"
    assert check_camera_template("cine-crane-up")["id"] == "cine-crane-up"
    for other in ("cine-rembrandt", "dance-orbit", "cine-teal-orange"):
        with pytest.raises(ValueError, match="invalid_camera_template"):
            check_camera_template(other)
    with pytest.raises(World3DTemplateError, match="unknown_template"):
        check_camera_template("nowhere")


def test_apply_camera_template_copies_the_camera_and_warns_on_a_format_mismatch():
    technique = framed_document()
    doc = document()
    assert apply_camera_template(doc, technique) == []
    assert doc["camera"] == technique["camera"] and doc["camera"] is not technique["camera"]
    assert doc["duration"] == 4 and doc["sfx"] == document()["sfx"], "the shot keeps its duration and its own effects"
    tall = document(width=720, height=1280)
    assert apply_camera_template(tall, technique) == ["camera_template_format: the camera was authored landscape and the scene is portrait; "
                                                      "apply the frame format again in the editor"]


def test_production_validation_accepts_the_new_keys_and_rejects_unknown_names():
    validate_scene3d_shot(cast_shot(cast=HERO, grade="noir", lens="85mm", light="rembrandt", camera_template="cine-crane-up"))
    validate_scene3d_shot(cast_shot(cast=HERO, light="dawn"))
    for config, message in (({"grade": "pastel"}, "scene3d.grade"), ({"lens": "500mm"}, "scene3d.lens"), ({"light": "torch"}, "scene3d.light"),
                            ({"camera_template": "cine-rembrandt"}, "invalid_camera_template"), ({"camera_template": "nowhere"}, "unknown_template"),
                            ({"camera_template": ""}, "scene3d.camera_template"), ({"camera_template": 3}, "scene3d.camera_template"),
                            ({"grading": "noir"}, "supported overrides")):
        with pytest.raises(ValueError, match=message):
            validate_scene3d_shot(cast_shot(cast=HERO, **config))


def test_the_patch_tool_documents_the_modifiers():
    patch = next(item for item in command_catalog() if item["name"] == "world3d.scene.patch")
    fields = patch["inputSchema"]["properties"]["input"]["properties"]
    assert fields["light"]["anyOf"][0]["enum"] == list(LIGHT_NAMES) and fields["grade"]["enum"] == list(GRADE_NAMES)
    assert fields["lens"]["enum"] == list(LENS_NAMES) and fields["camera_template"]["type"] == "string"
    assert "invalid_camera_template" in fields["camera_template"]["description"]


def test_patch_fields_light_lens_and_grade_over_execute_command(tmp_path):
    root = scene_file(tmp_path, "w3d-00000000m0d1", framed_document())
    schema = next(item for item in command_catalog() if item["name"] == "world3d.scene.patch")["inputSchema"]

    def patch(intent, changes, revision):
        arguments = {"version": 1, "intent_id": intent, "input": {"workspace": "studio", "scene_id": "w3d-00000000m0d1", "base_revision": revision, **changes}}
        jsonschema.validate(arguments, schema)
        return execute_command("world3d.scene.patch", arguments, root)["result"]["scene"]

    scene = patch("graded", {"light": "candle", "lens": "85mm", "grade": "flashback"}, 1)
    doc = scene["document"]
    assert doc["light"]["untinted"] == "#ff9a45" and doc["light"]["color"] == tinted("#ff9a45", "#e7d7c4"), "the grade tints the named light"
    assert doc["lighting"]["environment"]["intensity"] == 0.08
    assert doc["camera"]["fov"] == 28 and doc["camera"]["framing"]["fovTo"] == 17.5
    assert doc["look"] == {"toneMapping": "agx", "exposure": -0.3}
    assert [cue["id"] for cue in doc["sfx"]] == ["template-lines", "grade-vignette", "grade-film_grain"]
    assert {"grade", "lens", "camera_template", "light"} <= set(scene["editable"])
    again = patch("regraded", {"grade": "film", "screenFx": [{"id": "shot-flash", "kind": "impact_flash", "start": 1, "end": 1.2}]}, 2)["document"]
    assert [cue["id"] for cue in again["sfx"]] == ["template-lines", "shot-flash", "grade-film_grain"], "shot-* and grade-* effects replace their own kind only"
    assert again["light"]["color"] == "#ff9a45" and "untinted" not in again["light"], "film has no gel: the candle is back"
    lamp = {"direction": [0, -1, 0], "intensity": 2, "color": "#FFFFFF"}
    assert patch("relit", {"light": lamp}, 3)["document"]["light"] == {"kind": "directional", "direction": [0.0, -1.0, 0.0], "intensity": 2.0, "color": "#ffffff"}
    for changes, code in (({"light": "torch"}, "invalid_light"), ({"light": {"direction": [0, -1, 0]}}, "invalid_light"), ({"lens": "500mm"}, "invalid_lens"),
                          ({"grade": "pastel"}, "invalid_grade")):
        with pytest.raises(HTTPException) as caught:
            execute_command("world3d.scene.patch", {"version": 1, "intent_id": f"bad-{code}-{len(str(changes))}",
                                                    "input": {"workspace": "studio", "scene_id": "w3d-00000000m0d1", "base_revision": 4, **changes}}, root)
        assert caught.value.detail["code"] == code


@NODE
def test_patch_takes_a_camera_card_and_refuses_the_other_kinds(tmp_path):
    workspace_dir = scene_file(tmp_path, "w3d-00000000cam1", document(slots=[
        {"id": "hero", "slot": "subject_1", "media": "model3d", "sourceUrl": "/api/v1/file/a.glb?workspace=studio", "position": [0, 0, 0], "rotationY": 0, "scale": 1, "clip": None}]))
    viewed = patch_scene("studio", "w3d-00000000cam1", workspace_dir, {"camera_template": "cine-crane-up", "lens": "35mm"}, 1)
    camera = viewed["document"]["camera"]
    assert camera["family"] == "follow" and camera["framing"]["anchor"] == TECHNIQUES["cine-crane-up"]["anchor"] and camera["fov"] == 54
    assert camera["framing"]["targetSlot"] == "hero", "the framing follows this scene's subject"
    assert viewed["warnings"] == [] and viewed["document"]["duration"] == 4 and viewed["document"]["templateId"] == "two-shot"
    merged = patch_scene("studio", "w3d-00000000cam1", workspace_dir, {"camera_template": "cine-low-angle", "camera": {"fov": 33}}, 2)["document"]["camera"]
    assert merged["fov"] == 33 and merged["framing"]["anchor"] == TECHNIQUES["cine-low-angle"]["anchor"], "camera fields patched alongside win"
    with pytest.raises(World3DSceneError) as caught:
        patch_scene("studio", "w3d-00000000cam1", workspace_dir, {"camera_template": "cine-rembrandt"}, 3)
    assert caught.value.code == "invalid_camera_template"
    with pytest.raises(World3DTemplateError, match="unknown_template"):
        patch_scene("studio", "w3d-00000000cam1", workspace_dir, {"camera_template": "nowhere"}, 3)
    tall = scene_file(tmp_path / "tall", "w3d-00000000cam2", framed_document(width=720, height=1280))
    assert patch_scene("studio", "w3d-00000000cam2", tall, {"camera_template": "cine-crane-up"}, 1)["warnings"][0].startswith("camera_template_format")


@NODE
def test_real_compiler_lights_by_the_new_names_and_grades_over_the_template_effects():
    lit = compile_document(cast_shot(cast=HERO, light="rembrandt"), 4)
    authored = TECHNIQUES["cine-rembrandt"]["light"]
    assert lit["light"] == {"kind": "directional", "direction": authored["direction"], "intensity": authored["intensity"], "color": authored["color"]}
    assert lit["lighting"]["environment"]["intensity"] == 0.15
    graded = compile_document(cast_shot(template="cine-film-grain", cast=HERO, light="window", grade="noir"), 4)
    assert graded["look"] == {"toneMapping": "neutral", "exposure": -1.0}
    assert graded["light"]["color"] == tinted("#fff1d4", "#b9c4d6") and graded["light"]["untinted"] == "#fff1d4"
    assert [(cue["id"], cue["kind"], cue["end"]) for cue in graded["sfx"]] == [("cine-film-grain-fx-0", "film_grain", 6), ("grade-vignette", "vignette", 4)], \
        "the template's own effect keeps its authored length, the grade's covers the cut"
    assert graded["sfx"][1]["intensity"] == 1.2 and graded["sfx"][1]["size"] > 0, "the parser fills the cue's preset fields"
    with pytest.raises(ValueError, match="scene3d.grade"):
        compile_document(cast_shot(cast=HERO, grade="pastel"), 4)


@NODE
def test_real_compiler_sets_the_lens_and_keeps_the_zoom_and_the_frame():
    plain = compile_document(cast_shot(template="cine-slow-zoom-in", cast=HERO), 4)["camera"]
    tele = compile_document(cast_shot(template="cine-slow-zoom-in", cast=HERO, lens="85mm", frame="close"), 4)["camera"]
    assert (plain["fov"], plain["framing"]["fovFrom"], plain["framing"]["fovTo"]) == (48, 48, 30)
    assert (tele["fov"], tele["framing"]["fovFrom"], tele["framing"]["fovTo"]) == (28, 28, 17.5)
    assert tele["framing"]["from"][2] == plain["framing"]["from"][2] * 0.6, "frame and lens both apply"


@NODE
def test_real_compiler_takes_a_camera_card_onto_any_shot_and_keeps_its_cast_and_place():
    plain = compile_document(cast_shot(template="dance-orbit", cast=HERO), 4)
    craned = compile_document(cast_shot(template="dance-orbit", cast=HERO, camera_template="cine-crane-up"), 4)
    crane = compile_document(cast_shot(template="cine-crane-up", cast=HERO), 4)["camera"]
    assert craned["camera"]["family"] == "follow" and craned["camera"]["framing"]["from"] == crane["framing"]["from"]
    assert craned["camera"]["framing"]["targetSlot"] in [slot["id"] for slot in craned["slots"]]
    assert craned.get("dressing") == plain.get("dressing") and [slot["id"] for slot in craned["slots"]] == [slot["id"] for slot in plain["slots"]]
    assert craned["duration"] == 4 and craned["templateId"] == "dance-orbit"
    close = compile_document(cast_shot(template="dance-orbit", cast=HERO, camera_template="cine-crane-up", frame="close", lens="50mm"), 4)["camera"]
    assert close["framing"]["from"][2] == crane["framing"]["from"][2] * 0.6 and close["fov"] == 40, "frame and lens apply after the card"
    with pytest.raises(ValueError, match="invalid_camera_template"):
        compile_document(cast_shot(template="dance-orbit", cast=HERO, camera_template="cine-rembrandt"), 4)
    with pytest.raises(ValueError, match="unknown_template"):
        compile_document(cast_shot(template="dance-orbit", cast=HERO, camera_template="nowhere"), 4)


@NODE
def test_real_compiler_adapts_the_camera_to_a_portrait_shot():
    wide = compile_document(cast_shot(cast=HERO), 4)
    tall = compile_document(cast_shot(cast=HERO, width=1080, height=1920), 4)
    assert (tall["width"], tall["height"], tall["camera"]["frameFormat"]) == (1080, 1920, "portrait")
    assert tall["camera"]["fov"] > wide["camera"]["fov"] and "frameFormat" not in wide["camera"]
    craned = compile_document(cast_shot(cast=HERO, camera_template="cine-crane-up", width=1080, height=1920), 4)["camera"]
    assert craned["frameFormat"] == "portrait" and craned["framing"]["anchor"] == TECHNIQUES["cine-crane-up"]["anchor"]


@NODE
def test_python_and_typescript_apply_the_same_modifiers():
    steps = [["light", "candle"], ["lens", "135mm"], ["grade", "flashback"], ["grade", "cold"]]
    module = (ROOT / "ui/src/features/scene3d/modifiers.ts").as_uri()
    result = subprocess.run([shutil.which("node"), "--import", str(LOADER), "--input-type=module", "-e", MIRROR_SCRIPT, module],
                            input=json.dumps({"document": framed_document(), "steps": steps}), capture_output=True, text=True,
                            cwd=ROOT / "ui", timeout=120, check=False)
    assert result.returncode == 0, result.stderr
    mirrored = json.loads(result.stdout)
    assert mirrored["tables"] == modifier_tables()
    doc = framed_document()
    for kind, name in steps:
        {"light": apply_light, "lens": apply_lens, "grade": apply_grade}[kind](doc, name)
    assert mirrored["document"] == doc
    assert doc["light"]["color"] == tinted("#ff9a45", "#7ea2ff") and doc["camera"]["framing"]["fovTo"] == 11.25


def test_grade_cues_are_deep_copies_of_the_table():
    table = deepcopy(modifier_tables())
    doc = document()
    apply_grade(doc, "flashback")
    doc["sfx"][1]["intensity"] = 9
    doc["look"]["exposure"] = 9
    assert modifier_tables() == table
