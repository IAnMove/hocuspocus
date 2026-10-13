"""Workspaces: list, create, switch, delete (launch "Workspaces" section)."""
from __future__ import annotations


def test_workspaces_lifecycle(server, golden) -> None:
    server.check(golden, "list fresh", "GET", "/api/v1/workspaces")
    server.check(golden, "create", "POST", "/api/v1/workspaces", json={"name": "golden-a"})
    server.check(golden, "create again", "POST", "/api/v1/workspaces", json={"name": "golden-a"})
    server.check(golden, "create second", "POST", "/api/v1/workspaces", json={"name": "golden_b"})
    server.check(golden, "list after create", "GET", "/api/v1/workspaces")
    server.check(golden, "set active", "PUT", "/api/v1/workspaces/active", json={"name": "golden-a"})
    server.check(golden, "list after set active", "GET", "/api/v1/workspaces")
    server.check(golden, "set active back", "PUT", "/api/v1/workspaces/active", json={"name": "default"})
    server.check(golden, "delete", "DELETE", "/api/v1/workspaces/golden_b")
    server.check(golden, "list after delete", "GET", "/api/v1/workspaces")


def test_workspace_names_are_validated(server, golden) -> None:
    server.check(golden, "create without name", "POST", "/api/v1/workspaces", json={})
    server.check(golden, "create with a path", "POST", "/api/v1/workspaces", json={"name": "../escape"})
    server.check(golden, "create with a space", "POST", "/api/v1/workspaces", json={"name": "two words"})
    server.check(golden, "set active invalid", "PUT", "/api/v1/workspaces/active", json={"name": "a/b"})
    server.check(golden, "delete default", "DELETE", "/api/v1/workspaces/default")
    server.check(golden, "delete missing", "DELETE", "/api/v1/workspaces/never-made")
    server.check(golden, "outputs of an invalid workspace", "GET", "/api/v1/outputs", params={"workspace": "..."})
