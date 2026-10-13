"""Workspaces: list, create, switch, delete (launch "Workspaces" section)."""
from __future__ import annotations

import json
import os
import stat
import sys

import pytest

from tests.characterization import media


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


def test_wizard_persistence_round_trip(server, golden) -> None:
    server.check(golden, "wizard conversation empty", "GET", "/api/v1/wizard/conversations")
    server.check(golden, "wizard workflows empty", "GET", "/api/v1/wizard/workflows")
    server.check(
        golden, "wizard conversation invalid workspace", "GET", "/api/v1/wizard/conversations",
        params={"workspace": "../escape"},
    )
    server.check(
        golden, "wizard workflows invalid workspace", "GET", "/api/v1/wizard/workflows",
        params={"workspace": "../escape"},
    )
    server.check(golden, "wizard conversation save", "PUT", "/api/v1/wizard/conversations", json={
        "workspace": "default",
        "baseRevision": 0,
        "conversation": {
            "version": 1,
            "revision": 0,
            "messages": [{"id": "msg-1", "role": "user", "text": "Hola", "createdAt": 1}],
        },
    })
    server.check(golden, "wizard conversation loaded", "GET", "/api/v1/wizard/conversations")
    server.check(golden, "wizard workflows save", "PUT", "/api/v1/wizard/workflows", json={
        "workspace": "default",
        "baseRevision": 0,
        "collection": {"version": 1, "revision": 0, "workflows": []},
    })
    server.check(golden, "wizard workflows loaded", "GET", "/api/v1/wizard/workflows")


def test_workspace_names_are_validated(server, golden) -> None:
    server.check(golden, "create without name", "POST", "/api/v1/workspaces", json={})
    server.check(golden, "create with a path", "POST", "/api/v1/workspaces", json={"name": "../escape"})
    server.check(golden, "create with a space", "POST", "/api/v1/workspaces", json={"name": "two words"})
    server.check(golden, "set active invalid", "PUT", "/api/v1/workspaces/active", json={"name": "a/b"})
    server.check(golden, "delete default", "DELETE", "/api/v1/workspaces/default")
    server.check(golden, "delete missing", "DELETE", "/api/v1/workspaces/never-made")
    server.check(golden, "outputs of an invalid workspace", "GET", "/api/v1/outputs", params={"workspace": "..."})


def test_workspace_listing_counts_visible_files_and_skips_private_folders(server, golden) -> None:
    """``file_count`` counts the non-hidden files directly inside a folder; ``_`` and ``.`` folders are not workspaces."""
    (server.outputs / "golden-a").mkdir()
    (server.outputs / "golden-b").mkdir()
    (server.outputs / "_private").mkdir()
    (server.outputs / ".cache").mkdir()
    (server.outputs / "one.txt").write_text("1", encoding="utf-8")
    (server.outputs / ".hidden.txt").write_text("h", encoding="utf-8")
    (server.outputs / "golden-a" / "a.txt").write_text("a", encoding="utf-8")
    (server.outputs / "golden-a" / "b.txt").write_text("b", encoding="utf-8")
    (server.outputs / "golden-a" / "nested").mkdir()
    (server.outputs / "golden-a" / "nested" / "deep.txt").write_text("d", encoding="utf-8")
    (server.outputs / "_private" / "p.txt").write_text("p", encoding="utf-8")
    server.check(golden, "listing counts files", "GET", "/api/v1/workspaces")


def test_switching_the_workspace_saves_the_config_file_atomically(server, golden) -> None:
    """The switch is written to ``wgp.server_config_filename`` with owner-only permissions and no temporary file left."""
    config_file = server.root / "wgp_config.json"
    response = server.client.put("/api/v1/workspaces/active", json={"name": "golden-saved"})
    assert response.status_code == 200
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["services"]["active_workspace"] == "golden-saved"
    assert saved["save_path"] == str(server.outputs)
    if os.name == "posix":
        assert stat.S_IMODE(config_file.stat().st_mode) == 0o600
    assert [item.name for item in server.root.iterdir() if item.name.endswith(".tmp")] == []
    assert server.wgp.server_config["services"]["active_workspace"] == "golden-saved"
    assert os.path.realpath(server.wgp.save_path) == os.path.realpath(server.outputs / "golden-saved")
    assert os.path.realpath(server.wgp.image_save_path) == os.path.realpath(server.outputs / "golden-saved")
    server.check(golden, "listing after the switch", "GET", "/api/v1/workspaces")


def test_switching_the_workspace_while_a_generation_runs_defers_the_save_path(server, monkeypatch) -> None:
    """With a worker registered in the shared abort-state dictionary the config is saved and ``wgp.save_path`` waits."""
    launch = sys.modules["_launch_runtime"]
    before = server.wgp.save_path
    monkeypatch.setitem(launch._active_gen_states, "golden-busy", {"abort": False})
    response = server.client.put("/api/v1/workspaces/active", json={"name": "golden-deferred"})
    assert response.status_code == 200
    assert server.wgp.server_config["services"]["active_workspace"] == "golden-deferred"
    assert json.loads((server.root / "wgp_config.json").read_text(encoding="utf-8"))["services"]["active_workspace"] == "golden-deferred"
    assert server.wgp.save_path == before


def test_audio_adopt_resolves_media_in_the_workspace_and_in_uploads(server, golden) -> None:
    """``/api/v1/audio/adopt`` goes through the request media path policy (workspace, uploads, traversal)."""
    media.sound(server.outputs / "golden_song.wav")
    media.sound(server.outputs / "golden-w" / "golden_other.wav")
    media.sound(server.root / "uploads" / "audio" / "golden_upload.wav")
    media.sound(server.root / "golden_outside.wav")
    media.image(server.outputs / "golden_picture.png")
    adopt = "/api/v1/audio/adopt"
    server.check(golden, "adopt a workspace song", "POST", adopt, json={"audio_path": "golden_song.wav"})
    server.check(golden, "adopt from another workspace", "POST", adopt, json={"audio_path": "golden_other.wav", "workspace": "golden-w"})
    server.check(golden, "adopt an upload by url", "POST", adopt, json={"audio_path": "/api/v1/uploads/audio/golden_upload.wav"})
    server.check(golden, "adopt an upload by path", "POST", adopt, json={"audio_path": "uploads/audio/golden_upload.wav"})
    server.check(golden, "adopt a missing file", "POST", adopt, json={"audio_path": "golden_missing.wav"})
    server.check(golden, "adopt a traversal", "POST", adopt, json={"audio_path": "../golden_outside.wav"})
    server.check(golden, "adopt an absolute path outside", "POST", adopt, json={"audio_path": str(server.root / "golden_outside.wav")})
    server.check(golden, "adopt a picture as audio", "POST", adopt, json={"audio_path": "golden_picture.png"})
    server.check(golden, "adopt in an invalid workspace", "POST", adopt, json={"audio_path": "golden_song.wav", "workspace": "../x"})
