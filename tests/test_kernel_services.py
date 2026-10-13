"""The shared kernel services (``app/services/kernel``), with no WanGP and no server.

Each service takes its engine as an argument, so a test hands it a plain
object. The full server is exercised by ``tests/characterization``.
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
from types import SimpleNamespace

import pytest

from services.kernel import paths as kernel_paths
from services.kernel.config import ConfigStore
from services.kernel.paths import PathPolicy, safe_join


def _engine(tmp_path, **config) -> SimpleNamespace:
    return SimpleNamespace(
        server_config=dict(config),
        server_config_filename=str(tmp_path / "wgp_config.json"),
    )


def _symlink_or_skip(link, target) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")


# --- config ---------------------------------------------------------------


def test_config_store_reads_the_live_mapping_of_its_engine(tmp_path) -> None:
    engine = _engine(tmp_path, save_path="outputs")
    store = ConfigStore(lambda: engine)
    assert store.wgp is engine
    assert store.server_config is engine.server_config
    engine.server_config["added"] = 1
    assert store.server_config["added"] == 1


def test_config_save_writes_json_with_owner_only_permissions(tmp_path) -> None:
    engine = _engine(tmp_path, save_path="outputs", services={"active_workspace": "film"})
    ConfigStore(lambda: engine).save()
    target = tmp_path / "wgp_config.json"
    assert json.loads(target.read_text(encoding="utf-8")) == engine.server_config
    assert target.read_text(encoding="utf-8").startswith('{\n    "save_path"')
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert [item.name for item in tmp_path.iterdir()] == ["wgp_config.json"]


def test_config_save_keeps_the_old_file_when_the_swap_fails(tmp_path, monkeypatch) -> None:
    engine = _engine(tmp_path, save_path="new")
    target = tmp_path / "wgp_config.json"
    target.write_text('{"save_path": "old"}', encoding="utf-8")

    def refuse(_source, _destination):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError, match="disk full"):
        ConfigStore(lambda: engine).save()
    monkeypatch.undo()
    assert json.loads(target.read_text(encoding="utf-8")) == {"save_path": "old"}
    assert [item.name for item in tmp_path.iterdir()] == ["wgp_config.json"]


def test_config_save_replaces_the_previous_contents_whole(tmp_path) -> None:
    engine = _engine(tmp_path, a=1, b=2)
    store = ConfigStore(lambda: engine)
    store.save()
    del engine.server_config["b"]
    store.save()
    assert json.loads((tmp_path / "wgp_config.json").read_text(encoding="utf-8")) == {"a": 1}


# --- paths ----------------------------------------------------------------


def test_safe_join_keeps_a_name_inside_its_base(tmp_path) -> None:
    (tmp_path / "sub").mkdir()
    assert safe_join(str(tmp_path), "sub", "clip.mp4") == os.path.realpath(tmp_path / "sub" / "clip.mp4")
    assert safe_join(str(tmp_path)) == os.path.realpath(tmp_path)


@pytest.mark.parametrize("parts", [
    ("..", "outside.png"),
    ("sub", "..", "..", "outside.png"),
    ("/etc/passwd",),
    ("sub/../../x",),
])
def test_safe_join_refuses_traversal_and_absolute_names(tmp_path, parts) -> None:
    (tmp_path / "base").mkdir()
    assert safe_join(str(tmp_path / "base"), *parts) is None


def test_safe_join_compares_whole_path_components_not_prefixes(tmp_path) -> None:
    (tmp_path / "base").mkdir()
    (tmp_path / "base-evil").mkdir()
    assert safe_join(str(tmp_path / "base"), "..", "base-evil", "x") is None


def test_safe_join_refuses_a_symlink_that_leaves_the_base(tmp_path) -> None:
    base = tmp_path / "base"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    _symlink_or_skip(base / "link", outside)
    assert safe_join(str(base), "link", "x.png") is None


def test_safe_join_answers_none_for_a_nul_byte(tmp_path) -> None:
    assert safe_join(str(tmp_path), "bad\x00name") is None


def test_path_policy_safe_join_is_the_module_function(tmp_path) -> None:
    policy = PathPolicy()
    assert policy.safe_join(str(tmp_path), "a", "b") == safe_join(str(tmp_path), "a", "b")
    assert policy.safe_join(str(tmp_path), "..", "b") is None


@pytest.mark.parametrize("name", [
    None, 7, "", "   ", "a\x00b", "a\\b", "/abs.png", "../x.png", "./x.png", "a//b.png", "a/./b.png", "a/../b.png", "a/",
])
def test_output_move_path_refuses_anything_but_plain_relative_components(tmp_path, name) -> None:
    assert PathPolicy().resolve_output_move_path(str(tmp_path), name) is None


def test_output_move_path_accepts_a_contained_name_and_not_the_base_itself(tmp_path) -> None:
    (tmp_path / "sub").mkdir()
    policy = PathPolicy()
    assert policy.resolve_output_move_path(str(tmp_path), " clip.mp4 ") == os.path.realpath(tmp_path / "clip.mp4")
    assert policy.resolve_output_move_path(str(tmp_path), "sub/clip.mp4") == os.path.realpath(tmp_path / "sub" / "clip.mp4")


def test_output_move_path_refuses_a_symlinked_folder_that_leaves_the_base(tmp_path) -> None:
    base = tmp_path / "base"
    outside = tmp_path / "outside"
    base.mkdir()
    outside.mkdir()
    _symlink_or_skip(base / "link", outside)
    assert PathPolicy().resolve_output_move_path(str(base), "link/clip.mp4") is None


def _measure_concurrency(monkeypatch, name: str, call) -> int:
    running = 0
    peak = 0

    async def fake(*_args, **_kwargs):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return 0

    monkeypatch.setattr(kernel_paths, name, fake)

    async def run():
        await asyncio.gather(*(call() for _ in range(9)))

    asyncio.run(run())
    return peak


def test_uploads_ingest_four_at_a_time(monkeypatch) -> None:
    policy = PathPolicy()
    peak = _measure_concurrency(
        monkeypatch, "stream_upload_file", lambda: policy.stream_upload(object(), "x", max_bytes=1),
    )
    assert peak == 4


def test_uploads_transcode_two_at_a_time(monkeypatch) -> None:
    policy = PathPolicy()
    peak = _measure_concurrency(
        monkeypatch, "transcode_upload", lambda: policy.transcode_upload("a", "b", is_video=True),
    )
    assert peak == 2


def test_upload_streaming_passes_the_size_cap_and_returns_the_byte_count(monkeypatch) -> None:
    seen = {}

    async def fake(upload, destination, *, max_bytes):
        seen.update(upload=upload, destination=destination, max_bytes=max_bytes)
        return 42

    monkeypatch.setattr(kernel_paths, "stream_upload_file", fake)
    marker = object()
    assert asyncio.run(PathPolicy().stream_upload(marker, "dest.wav", max_bytes=9)) == 42
    assert seen == {"upload": marker, "destination": "dest.wav", "max_bytes": 9}
