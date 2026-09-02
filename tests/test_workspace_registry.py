from app.services.workspace_registry import WORKSPACE_SCHEMA, WorkspaceRegistry


def test_workspace_registry_groups_ids_without_creating_output_folders(tmp_path):
    path = tmp_path / "_hocuspocus" / "workspaces-v1.json"
    registry = WorkspaceRegistry(path)

    created = registry.create({
        "name": "Nightly release", "project_ids": ["project-1", "project-1"],
        "asset_ids": ["asset-1"], "production_ids": ["production-1"],
    })

    assert created["schema"] == WORKSPACE_SCHEMA
    assert created["project_ids"] == ["project-1"]
    assert path.is_file()
    assert sorted(item.name for item in tmp_path.iterdir()) == ["_hocuspocus"]


def test_workspace_registry_updates_optimistically_and_deletes(tmp_path):
    registry = WorkspaceRegistry(tmp_path / "registry.json")
    created = registry.create({"name": "Comic"})
    changed = registry.update(created["id"], {
        "expected_revision": 1, "description": "Pages and renders", "asset_ids": ["asset-2"],
    })

    assert changed["revision"] == 2
    assert changed["description"] == "Pages and renders"
    try:
        registry.update(created["id"], {"expected_revision": 1, "name": "Stale"})
    except RuntimeError:
        pass
    else:
        raise AssertionError("stale workspace update was accepted")
    try:
        registry.update(created["id"], {"expected_revision": "invalid", "name": "Bad"})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid expected_revision was accepted")
    assert registry.delete(created["id"]) is True
    assert registry.get(created["id"]) is None
