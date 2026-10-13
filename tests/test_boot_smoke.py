"""scripts/boot_smoke.py without booting anything: lists, seeded config, worktree swap and restore."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
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


def test_server_env_keeps_libraries_and_publication_away_from_the_live_install(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PINOKIO_HOME", "/live/pinokio")
    monkeypatch.setenv("HOCUS_PUBLICATION_ROOT", "/live/publish")
    monkeypatch.setenv("PYTHONPATH", "/somewhere")
    env = boot_smoke.server_env(42080, cpu=True, core=False, scratch=tmp_path)
    assert Path(env["MAESTRO_STYLE_LIBRARY_DIR"]).is_relative_to(tmp_path)
    assert Path(env["HOCUS_TEMPLATE_LIBRARY_DIR"]).is_relative_to(tmp_path)
    assert "HOCUS_PUBLICATION_ROOT" not in env and "PYTHONPATH" not in env
    assert env["HOCUS_GPU_MACHINE_LOCK"] == "0" and env["CUDA_VISIBLE_DEVICES"] == ""


def _args(**values):
    defaults = {"port": None, "cpu": True, "min_free_vram_mb": 3072}
    return argparse.Namespace(**{**defaults, **values})


def test_preflight_refuses_the_main_worktree_whatever_live_says(tmp_path, monkeypatch) -> None:
    main, other = tmp_path / "main", tmp_path / "other"
    with pytest.raises(SmokeError, match="live checkout"):
        boot_smoke._preflight(_args(), main, {main, other})


def test_run_compares_with_the_main_worktree_even_with_live(tmp_path, monkeypatch) -> None:
    main = tmp_path / "main"
    (main / "app").mkdir(parents=True)
    monkeypatch.setattr(boot_smoke, "live_checkout", lambda _worktree: main)
    args = _args(worktree=str(main), live=str(tmp_path / "elsewhere"), scratch=None, core=False, list=None, timeout=1)
    with pytest.raises(SmokeError, match="live checkout"):
        boot_smoke.run(args)
    assert not (tmp_path / "main.boot-smoke").exists()


def test_preflight_refuses_a_worktree_an_earlier_smoke_did_not_put_back(tmp_path) -> None:
    worktree = tmp_path / "worktree"
    (worktree / "app").mkdir(parents=True)
    (worktree / "app" / "launch.py").write_text("", encoding="utf-8")
    (worktree / "app" / "wgp_config.json").write_text(json.dumps(seeded_config(tmp_path / "old-run")), encoding="utf-8")
    assert boot_smoke.unfinished_run(worktree) == str(tmp_path / "old-run")
    with pytest.raises(SmokeError, match="did not put"):
        boot_smoke._preflight(_args(), worktree, {tmp_path / "main"})
    (worktree / "app" / "wgp_config.json").write_text("{}", encoding="utf-8")
    assert boot_smoke.unfinished_run(worktree) is None


def test_restore_puts_back_what_it_can_and_names_the_rest(tmp_path) -> None:
    worktree, scratch = tmp_path / "worktree", tmp_path / "scratch"
    for name in ("settings", "uploads"):
        (worktree / "app" / name).mkdir(parents=True)
    scratch.mkdir()
    state = WorktreeState(worktree, scratch)
    state.swap("app/settings", lambda path: path.mkdir())
    state.swap("app/uploads", lambda path: path.mkdir())
    (scratch / "set-aside" / "app__settings").rename(tmp_path / "lost")  # the original vanished

    notes = state.restore()
    assert notes[0].startswith("NOT restored app/settings") and "set-aside" in notes[0]
    assert notes[1] == "restored app/uploads"
    assert (worktree / "app" / "uploads").is_dir()


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="reads the session of each process in /proc")
def test_stop_ends_the_server_then_what_it_left_in_its_session() -> None:
    code = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(120)\n"
    )
    server = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, start_new_session=True)
    child = int(server.stdout.readline())
    result = boot_smoke.stop(server, wait=20)
    server.stdout.close()
    assert result["pid"] == server.pid and result["signal"] == "SIGTERM"
    assert result["children_stopped"] == [child]
    assert not boot_smoke._running_in(child, server.pid)
    # A process outside the session is never signalled, even when asked by PID.
    assert boot_smoke._signal_in_session(os.getpid(), server.pid, 0) is False
