"""world3d.scene.fix_placement writes the placement check's own positions as one patch: the same operation for MCP, the Wizard and the editor."""
import jsonschema

from services import world3d_template_commands as commands
from services.mcp_profiles import SERIES_TOOLS
from services.world3d_scene_placement import placement_fixes


def issue(id_, position, code="sinks_into_support"):
    return {"code": code, "id": id_, "detail": "x", "fix": {"position": position}}


ITEMS = [{"id": "lying", "position": [0.0, 0.41, -0.5]}, {"id": "seated", "position": [0.6, 0.2, 1.0]}, {"id": "still", "position": [2.0, 0.0, 0.0]}]
ISSUES = [issue("lying", [0.0, 0.55, -0.5]), issue("seated", [0.6, 0.2, 0.8], "overhangs_support"), issue("seated", [0.6, 0.3, 1.0]), {"code": "cropped", "id": "still", "detail": "x"}]


def test_every_object_with_a_position_fix_gets_one_position_with_all_its_fixes_added_up():
    fixes = placement_fixes(ISSUES, ITEMS)
    assert fixes == {"lying": [0.0, 0.55, -0.5], "seated": [0.6, 0.3, 0.8]}
    assert placement_fixes(ISSUES, ITEMS, only=["lying"]) == {"lying": [0.0, 0.55, -0.5]}
    assert placement_fixes([], ITEMS) == {}


def run(monkeypatch, data, scene):
    calls = []
    monkeypatch.setattr(commands, "inspect_scene", lambda workspace, scene_id, workspace_dir: scene)
    monkeypatch.setattr(commands, "patch_scene", lambda workspace, scene_id, workspace_dir, body, revision: calls.append((body, revision)) or {"revision": revision + 1, "layout": {"placement": []}})
    return commands._fix_placement({"workspace": "w", "scene_id": "s", **data}, "dir"), calls


def test_the_operation_writes_the_fixes_in_one_patch_and_returns_the_new_revision(monkeypatch):
    result, calls = run(monkeypatch, {"base_revision": 4}, {"revision": 4, "layout": {"items": ITEMS, "placement": ISSUES}})
    assert calls == [({"bindings": [{"object_id": "lying", "position": [0.0, 0.55, -0.5]}, {"object_id": "seated", "position": [0.6, 0.3, 0.8]}]}, 4)]
    assert result["scene"]["revision"] == 5 and [item["object_id"] for item in result["fixed"]] == ["lying", "seated"]


def test_only_limits_the_objects_and_a_clean_scene_is_returned_unchanged(monkeypatch):
    result, calls = run(monkeypatch, {"base_revision": 4, "only": ["seated"]}, {"revision": 4, "layout": {"items": ITEMS, "placement": ISSUES}})
    assert [binding["object_id"] for binding in calls[0][0]["bindings"]] == ["seated"] and result["fixed"][0]["position"] == [0.6, 0.3, 0.8]
    clean, calls = run(monkeypatch, {"base_revision": 4}, {"revision": 4, "layout": {"items": ITEMS, "placement": [{"code": "cropped", "id": "still", "detail": "x"}]}})
    assert calls == [] and clean["fixed"] == [] and clean["scene"]["revision"] == 4


def test_the_operation_is_a_mutation_in_the_catalog_and_its_input_is_validated():
    entry = next(item for item in commands.command_catalog() if item["name"] == "world3d.scene.fix_placement")
    assert entry["mutation"] is True and "intent_id" in entry["inputSchema"]["properties"]
    assert "world3d.scene.fix_placement" in SERIES_TOOLS, "a Series agent reaches it like patch and inspect"
    good = {"version": 1, "intent_id": "fix-1", "input": {"workspace": "w", "scene_id": "scene-1", "base_revision": 2, "only": ["lying"]}}
    jsonschema.validate(good, entry["inputSchema"])
    bad = {**good, "input": {"workspace": "w", "scene_id": "scene-1"}}
    try:
        jsonschema.validate(bad, entry["inputSchema"])
    except jsonschema.ValidationError:
        return
    raise AssertionError("base_revision is required")
