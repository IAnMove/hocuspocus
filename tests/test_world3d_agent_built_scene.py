"""An agent builds a Video 3D scene through the shared commands, and what it built opens in the editor as it saw it.

No rendering and no node: the template is personal (a stored document), the models are tiny GLBs in the workspace, and the
editor's shape gate is mirrored by editor_shape_problems (documentValidation.ts)."""
import copy

import jsonschema
import pytest

from services.scene_documents import get_document
from services.world3d_blank_scene import blank_document, blank_template_row, editor_shape_problems, marker_slot
from services.world3d_scene_layout import scene_layout
from services.world3d_scenes import working_scenes
from services.world3d_template_commands import command_catalog, execute_command
from tests.test_world3d_scene_layout import model_glb, workspace_dir

WORKSPACE = "studio"


def call(tmp_path, name, **data):
    arguments = {"version": 1, "input": {"workspace": WORKSPACE, **data}}
    if next(item for item in command_catalog() if item["name"] == name)["mutation"]:
        arguments["intent_id"] = f"{name}-{abs(hash(repr(data)))}"
    jsonschema.validate(arguments, next(item for item in command_catalog() if item["name"] == name)["inputSchema"])
    body = execute_command(name, arguments, workspace_dir(tmp_path))
    assert body["status"] == "completed", body
    return body["result"]


def test_the_blank_document_is_what_the_editor_accepts_and_the_mirror_says_why_it_would_not():
    document = blank_document()
    assert document["slots"] == [] and editor_shape_problems(document) == []
    assert editor_shape_problems(blank_document(width=720, height=1280, fps=24, duration=12, markers=[("hero", "subject_1"), ("moon", "background")])) == []
    broken = {"fps": 25, "light": {"preset": "studio"}, "camera": {"family": "dolly", "eye": [0, 1], "look": [0, 1, 0], "fov": 200},
              "slots": [marker_slot("a", "extra"), marker_slot("a")], "duration": 700, "version": 2}
    problems = editor_shape_problems({**document, **broken})
    for text in ("version 1", "fps must be", "light must be", "camera.eye", "camera.fov", "camera.family", "slots[0]", "unique", "at most 600"):
        assert any(text in problem for problem in problems), (text, problems)
    framed = copy.deepcopy(document)
    framed["camera"]["framing"] = {"targetSlot": "nobody"}
    assert any("targetSlot" in problem for problem in editor_shape_problems(framed))
    assert editor_shape_problems("nope") and editor_shape_problems({})
    with pytest.raises(ValueError, match="fps must be"):
        blank_document(fps=25)


def test_a_blank_stage_instantiates_inspects_patches_and_publishes(tmp_path):
    call(tmp_path, "world3d.templates.user.put", **blank_template_row())
    scene = call(tmp_path, "world3d.scene.instantiate", template_id="user-blank-stage")["scene"]
    assert scene["layout"]["items"] == [] and scene["camera"]["family"] == "fixed" and scene["document"]["templateId"] == "user-blank-stage"
    model_glb(tmp_path, "tower.glb", low=(-1, 0, -1), high=(1, 10, 1))
    patched = call(tmp_path, "world3d.scene.patch", scene_id=scene["sceneId"], base_revision=1, bindings=[
        {"object_id": "tower", "add": True, "source_url": "/api/v1/file/tower.glb?workspace=studio", "fit": {"heightM": 30}}])["scene"]
    assert patched["layout"]["items"][0]["boundsM"]["size"] == pytest.approx([6, 30, 6])
    published = call(tmp_path, "world3d.scene.publish", scene_id=scene["sceneId"])["scene"]
    assert published["editor"] == "video3d" and editor_shape_problems(published["document"]) == []


def test_what_the_agent_built_opens_in_the_editor_as_inspect_showed_it(tmp_path):
    model_glb(tmp_path, "tower.glb", low=(-1, 0, -1), high=(1, 10, 1))                 # 2 x 10 x 2 m in its file
    model_glb(tmp_path, "rock.glb", low=(0, 0, 0), high=(3, 1, 1.5))
    call(tmp_path, "world3d.templates.user.put", **blank_template_row("user-tower-shot", "Tower shot", markers=[("hero", "subject_1")]))
    scene = call(tmp_path, "world3d.scene.instantiate", template_id="user-tower-shot")["scene"]
    scene_id = scene["sceneId"]
    assert scene["pending"] and scene["layout"]["items"][0]["boundsReason"] == "marker"

    camera = {"family": "fixed", "eye": [0, 3, 20], "look": [0, 12, -10], "fov": 50}
    call(tmp_path, "world3d.scene.patch", scene_id=scene_id, base_revision=1, camera=camera, bindings=[
        {"object_id": "hero", "source_url": "/api/v1/file/tower.glb?workspace=studio", "fit": {"heightM": 30}, "position": [0, 0, -10], "grounded": True},
        {"object_id": "rock", "add": True, "source_url": "/api/v1/file/rock.glb?workspace=studio", "fit": {"longestM": 4}, "position": [3, 0, -8], "rotationY": 1.5707963}])
    seen = call(tmp_path, "world3d.scene.inspect", scene_id=scene_id)["scene"]

    assert seen["revision"] == 2 and seen["camera"] == {**camera}
    hero, rock = seen["layout"]["items"]
    assert (hero["id"], hero["role"]) == ("hero", "subject_1") and (rock["id"], rock["role"]) == ("rock", "prop")
    assert hero["boundsM"]["size"] == pytest.approx([6, 30, 6]) and hero["boundsM"]["bottomY"] == 0 and hero["boundsM"]["center"] == pytest.approx([0, 15, -10])
    assert rock["boundsM"]["size"] == pytest.approx([4, 1.3333, 2], abs=1e-3)                  # the longest side of 3 x 1 x 1.5 is 4 m
    # turned a quarter about y at (3, 0, -8): its 4 m length runs along z, its 2 m depth along x
    assert rock["boundsM"]["min"] == pytest.approx([3, 0, -12], abs=1e-3) and rock["boundsM"]["max"] == pytest.approx([5, 1.3333, -8], abs=1e-3)
    assert seen["pending"] == [] and {row["id"] for row in seen["objects"]} == {"hero", "rock"}
    assert editor_shape_problems(seen["document"]) == []

    listed = working_scenes(WORKSPACE, workspace_dir(tmp_path))
    assert [row["sceneId"] for row in listed] == [scene_id] and listed[0]["slots"] == 2 and listed[0]["title"] == "Tower shot"

    published = call(tmp_path, "world3d.scene.publish", scene_id=scene_id)["scene"]
    opened = get_document(WORKSPACE, published["file"], workspace_dir=workspace_dir(tmp_path))
    assert opened["editor"] == "video3d" and published["editor"] == "video3d"
    assert opened["document"] == seen["document"] == published["document"]
    again = scene_layout(opened["document"], WORKSPACE, workspace_dir(tmp_path))
    assert again == {key: seen[key] for key in ("camera", "light", "duration", "size", "layout")}, "the saved file shows the same layout"
    assert working_scenes(WORKSPACE, workspace_dir(tmp_path)) == [], "published: it leaves the Open dialog's working list"
    assert [row["sceneId"] for row in working_scenes(WORKSPACE, workspace_dir(tmp_path), unpublished_only=False)] == [scene_id]


def _preset_light_row(document=None):
    row = blank_template_row("user-preset-light", "Preset light")
    row["document"] = document or {**row["document"], "light": {"preset": "studio"}}
    return row


def _editor_warnings(reply):
    return [text for text in reply["warnings"] if text.startswith("editor_would_refuse: ")]


def test_a_document_the_editor_would_refuse_still_saves_and_publishes_with_a_warning_in_every_reply(tmp_path):
    put = call(tmp_path, "world3d.templates.user.put", **_preset_light_row())
    assert put["template"]["id"] == "user-preset-light" and len(_editor_warnings(put["template"])) == 1
    assert "light must be" in put["template"]["warnings"][0]
    scene = call(tmp_path, "world3d.scene.instantiate", template_id="user-preset-light")["scene"]
    assert len(_editor_warnings(scene)) == 1
    model_glb(tmp_path, "tower.glb")
    patched = call(tmp_path, "world3d.scene.patch", scene_id=scene["sceneId"], base_revision=1, bindings=[
        {"object_id": "tower", "add": True, "source_url": "/api/v1/file/tower.glb?workspace=studio", "fit": {"heightM": 5}}])["scene"]
    assert len(_editor_warnings(patched)) == 1 and patched["layout"]["items"][0]["boundsM"]
    seen = call(tmp_path, "world3d.scene.inspect", scene_id=scene["sceneId"])["scene"]
    assert _editor_warnings(seen) == _editor_warnings(patched), "the warning is not stored: inspect shows it once, not once per patch"
    published = call(tmp_path, "world3d.scene.publish", scene_id=scene["sceneId"])["scene"]
    assert published["editor"] == "video3d" and published["file"] and len(_editor_warnings(published)) == 1
    assert published["document"]["light"] == {"preset": "studio"}, "nothing was repaired or refused"


def test_a_valid_document_carries_no_editor_warning_anywhere(tmp_path):
    put = call(tmp_path, "world3d.templates.user.put", **blank_template_row())
    scene = call(tmp_path, "world3d.scene.instantiate", template_id="user-blank-stage")["scene"]
    model_glb(tmp_path, "tower.glb")
    patched = call(tmp_path, "world3d.scene.patch", scene_id=scene["sceneId"], base_revision=1, bindings=[
        {"object_id": "tower", "add": True, "source_url": "/api/v1/file/tower.glb?workspace=studio"}])["scene"]
    seen = call(tmp_path, "world3d.scene.inspect", scene_id=scene["sceneId"])["scene"]
    published = call(tmp_path, "world3d.scene.publish", scene_id=scene["sceneId"])["scene"]
    assert put["template"]["warnings"] == [] and scene["warnings"] == [] and patched["warnings"] == []
    assert seen["warnings"] == [] and published["warnings"] == []


def test_a_partial_template_is_still_accepted_and_the_warnings_are_capped(tmp_path):
    put = call(tmp_path, "world3d.templates.user.put", id="user-partial", title="Partial", document={"slots": []})
    assert put["status"] == "completed" and put["template"]["warnings"] and all(text.startswith("editor_would_refuse: ") for text in put["template"]["warnings"])
    many = {"slots": [{"id": f"p{index}", "slot": "nope"} for index in range(30)]}
    capped = call(tmp_path, "world3d.templates.user.put", id="user-many", title="Many", document=many)["template"]["warnings"]
    assert len(capped) == 9 and capped[-1].endswith(" more")
    assert editor_shape_problems({**blank_document(), "slots": [{**marker_slot("a"), "clip": {"index": 1.0, "name": "Walk"}}]}) == [], "a whole number written 1.0 is an index"


def test_the_tool_descriptions_name_the_editor_warning():
    tools = {item["name"]: item["description"] for item in command_catalog()}
    for name in ("world3d.scene.inspect", "world3d.scene.patch", "world3d.scene.publish", "world3d.templates.user.put"):
        assert "editor_would_refuse" in tools[name], name
