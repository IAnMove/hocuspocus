"""scripts/boot_smoke.py without booting anything: lists, seeded config, worktree swap and restore."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import boot_smoke
from scripts.boot_smoke import Check, SmokeError, WorktreeState, parse_list, seeded_config


def test_smoke_lists_parse(tmp_path) -> None:
    listing = tmp_path / "slice.txt"
    listing.write_text(
        "# comment\n\nGET /api/v1/series\nget /api/v1/x 404\nPOST /api/v1/y 200,409 {\"name\": \"a #1\"}\n",
        encoding="utf-8",
    )
    assert parse_list(listing) == [
        Check("GET", "/api/v1/series"),
        Check("GET", "/api/v1/x", (404,)),
        Check("POST", "/api/v1/y", (200, 409), {"name": "a #1"}),
    ]
    listing.write_text("GET api/v1/no-slash\n", encoding="utf-8")
    with pytest.raises(SmokeError, match="slice.txt:1"):
        parse_list(listing)


def test_committed_smoke_lists_parse() -> None:
    for path in sorted(boot_smoke.SMOKE_LISTS.glob("*.txt")):
        if path.name.endswith(".known-duplicates.txt"):
            assert boot_smoke.known_duplicates(path.name.split(".")[0])
            continue
        assert parse_list(path), path.name


def test_seeded_config_keeps_everything_in_the_scratch_folder(tmp_path) -> None:
    config = seeded_config(tmp_path)
    for key in ("save_path", "image_save_path", "audio_save_path", "loras_root"):
        assert Path(config[key]).is_relative_to(tmp_path)
    assert config["checkpoints_paths"] == [str(tmp_path / "ckpts")]
    assert config["services"]["auto_performance"] is False
    assert config["services"]["auto_performance_applied"] is True
    assert boot_smoke.MARKER in config
    json.dumps(config)


def test_worktree_swap_restores_by_renames(tmp_path) -> None:
    worktree = tmp_path / "worktree"
    scratch = tmp_path / "scratch"
    (worktree / "app" / "settings").mkdir(parents=True)
    (worktree / "app" / "settings" / "mine.json").write_text("{}", encoding="utf-8")
    scratch.mkdir()
    state = WorktreeState(worktree, scratch)

    state.swap("app/settings", lambda path: path.symlink_to(scratch, target_is_directory=True))
    state.swap("app/wgp_config.json", lambda path: path.write_text("{}", encoding="utf-8"))
    assert (worktree / "app" / "settings").is_symlink()
    assert (worktree / "app" / "wgp_config.json").is_file()

    assert state.restore() == ["restored app/settings"]
    assert (worktree / "app" / "settings" / "mine.json").is_file()
    assert not (worktree / "app" / "settings").is_symlink()
    assert not (worktree / "app" / "wgp_config.json").exists()
    assert (scratch / "worktree-state" / "app__wgp_config.json").is_file()


def test_openapi_paths_drop_converters() -> None:
    assert boot_smoke._openapi_path("/api/v1/file/{filename:path}") == "/api/v1/file/{filename}"
    assert boot_smoke._openapi_path("/api/v1/series/{series_id}") == "/api/v1/series/{series_id}"
