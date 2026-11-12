"""A model bound with no clip plays its rest-pose clip (Idle, Stand), so a humanoid is not left in its T bind pose; a model without one is left alone."""
import jsonschema

from services.procedural_3d.glb_clips import glb_clips, idle_clip
from services.world3d_template_commands import command_catalog, execute_command
from tests.test_world3d_scene_layout import WORKSPACE, accessor, mesh, workspace_dir, write_glb
from tests.test_world3d_agent_built_scene import call
from services.world3d_blank_scene import blank_template_row


def glb_with_clips(tmp_path, name, clips):
    folder = tmp_path / WORKSPACE
    folder.mkdir(exist_ok=True)
    document = {"scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}], "meshes": [mesh(0)], "accessors": [accessor([-0.8, 0, -0.1], [0.8, 1.7, 0.1])]}
    if clips is not None:
        document["animations"] = [{"name": clip} if clip else {} for clip in clips]
    return write_glb(folder, document, name)


def test_the_clip_names_are_read_from_the_json_chunk_and_the_rest_pose_is_picked_by_its_name(tmp_path):
    path = glb_with_clips(tmp_path, "a.glb", ["Walk", "Idle_Loop", "Talk"])
    assert glb_clips(path) == ["Walk", "Idle_Loop", "Talk"]
    assert idle_clip(glb_clips(path)) == {"index": 1, "name": "Idle_Loop"}
    assert glb_clips(glb_with_clips(tmp_path, "b.glb", None)) == [] and glb_clips(tmp_path / "missing.glb") == []
    assert glb_clips(glb_with_clips(tmp_path, "c.glb", [None])) == ["clip_0"]
    assert idle_clip(["Walk", "Run"]) is None and idle_clip(["Standing"]) == {"index": 0, "name": "Standing"} and idle_clip(["Understand"]) is None


def test_a_patch_without_clip_plays_idle_and_says_so_while_an_explicit_clip_or_a_clipless_model_is_left_alone(tmp_path):
    call(tmp_path, "world3d.templates.user.put", **blank_template_row())
    scene = call(tmp_path, "world3d.scene.instantiate", template_id="user-blank-stage")["scene"]
    glb_with_clips(tmp_path, "person.glb", ["Walk", "Idle"])
    glb_with_clips(tmp_path, "rock.glb", None)
    glb_with_clips(tmp_path, "walker.glb", ["Walk"])
    patched = call(tmp_path, "world3d.scene.patch", scene_id=scene["sceneId"], base_revision=1, bindings=[
        {"object_id": "person", "add": True, "source_url": "/api/v1/file/person.glb?workspace=studio"},
        {"object_id": "chosen", "add": True, "source_url": "/api/v1/file/person.glb?workspace=studio", "clip": {"index": 0, "name": "Walk"}},
        {"object_id": "rock", "add": True, "source_url": "/api/v1/file/rock.glb?workspace=studio"},
        {"object_id": "walker", "add": True, "source_url": "/api/v1/file/walker.glb?workspace=studio"}])["scene"]
    slots = {slot["id"]: slot for slot in patched["document"]["slots"]}
    assert slots["person"]["clip"] == {"index": 1, "name": "Idle"} and slots["person"]["clipPlayback"] == {"loop": True}
    assert slots["chosen"]["clip"] == {"index": 0, "name": "Walk"}
    assert not slots["rock"].get("clip") and not slots["walker"].get("clip")
    assert any(w.startswith("clip_default: person plays \"Idle\"") for w in patched["warnings"]) and not any("chosen" in w and "clip_default" in w for w in patched["warnings"])
