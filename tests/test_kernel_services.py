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
from fastapi import HTTPException

from services.kernel import paths as kernel_paths
from services.kernel.config import ConfigStore
from services.kernel.paths import PathPolicy, safe_join
from services.kernel.workspaces import WorkspaceService


def _engine(tmp_path, **config) -> SimpleNamespace:
    return SimpleNamespace(
        server_config=dict(config),
        server_config_filename=str(tmp_path / "wgp_config.json"),
    )


def _workspaces(tmp_path, **config) -> tuple[WorkspaceService, SimpleNamespace]:
    """A workspace service over a fake engine whose outputs folder is ``tmp_path/outputs``."""
    engine = _engine(tmp_path, save_path=str(tmp_path / "outputs"), **config)
    engine.save_path = engine.server_config["save_path"]
    engine.image_save_path = engine.server_config["save_path"]
    (tmp_path / "outputs").mkdir()
    return WorkspaceService(ConfigStore(lambda: engine)), engine


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


# --- workspaces -----------------------------------------------------------


def test_active_workspace_is_read_from_the_live_config_each_time(tmp_path) -> None:
    workspaces, engine = _workspaces(tmp_path)
    assert workspaces.active() == "default"
    engine.server_config["services"] = {"active_workspace": "film"}
    assert workspaces.active() == "film"
    engine.server_config["services"] = {}
    assert workspaces.active() == "default"


def test_workspace_dir_is_the_outputs_folder_for_default_and_a_created_subfolder_otherwise(tmp_path) -> None:
    workspaces, _engine_ = _workspaces(tmp_path)
    outputs = os.path.realpath(tmp_path / "outputs")
    assert workspaces.workspace_dir("default") == outputs
    assert workspaces.workspace_dir() == outputs
    made = workspaces.workspace_dir("film-2")
    assert made == os.path.join(outputs, "film-2") and os.path.isdir(made)


def test_workspace_dir_without_a_name_follows_the_active_workspace(tmp_path) -> None:
    workspaces, engine = _workspaces(tmp_path, services={"active_workspace": "film"})
    assert workspaces.workspace_dir() == os.path.join(os.path.realpath(tmp_path / "outputs"), "film")
    engine.server_config["services"]["active_workspace"] = "default"
    assert workspaces.workspace_dir() == os.path.realpath(tmp_path / "outputs")


@pytest.mark.parametrize("name", ["", " ", "a b", "a/b", "../x", "..", ".hidden", "-lead", "_lead", "a\\b", "x\x00", 7, ["default"]])
def test_workspace_dir_refuses_a_name_that_is_not_a_plain_workspace_name(tmp_path, name) -> None:
    workspaces, _engine_ = _workspaces(tmp_path)
    with pytest.raises(HTTPException) as caught:
        workspaces.workspace_dir(name)
    assert caught.value.status_code == 400
    assert caught.value.detail == (
        "Invalid workspace name. Use letters, numbers, hyphens, underscores, without spaces or path separators."
    )
    assert [item.name for item in (tmp_path / "outputs").iterdir()] == []


def test_workspace_dir_refuses_a_workspace_that_is_a_link_out_of_the_outputs(tmp_path) -> None:
    workspaces, _engine_ = _workspaces(tmp_path)
    (tmp_path / "elsewhere").mkdir()
    _symlink_or_skip(tmp_path / "outputs" / "film", tmp_path / "elsewhere")
    with pytest.raises(HTTPException) as caught:
        workspaces.workspace_dir("film")
    assert (caught.value.status_code, caught.value.detail) == (400, "Invalid workspace path.")


def test_workspace_dir_reads_the_base_from_the_config_not_from_the_save_path(tmp_path) -> None:
    workspaces, engine = _workspaces(tmp_path)
    engine.save_path = str(tmp_path / "outputs" / "film")
    assert workspaces.workspace_dir("default") == os.path.realpath(tmp_path / "outputs")


def test_workspace_listing_counts_visible_files_and_skips_private_folders(tmp_path) -> None:
    workspaces, engine = _workspaces(tmp_path)
    outputs = tmp_path / "outputs"
    for name in ("b-film", "a-film", "_private", ".cache"):
        (outputs / name).mkdir()
    (outputs / "one.txt").write_text("1", encoding="utf-8")
    (outputs / ".hidden").write_text("h", encoding="utf-8")
    (outputs / "a-film" / "x.txt").write_text("x", encoding="utf-8")
    (outputs / "a-film" / "nested").mkdir()
    (outputs / "_private" / "p.txt").write_text("p", encoding="utf-8")
    base = engine.server_config["save_path"]
    assert workspaces.list() == [
        {"name": "default", "path": base, "file_count": 1},
        {"name": "a-film", "path": os.path.join(base, "a-film"), "file_count": 1},
        {"name": "b-film", "path": os.path.join(base, "b-film"), "file_count": 0},
    ]


def test_workspace_listing_before_the_outputs_folder_exists(tmp_path) -> None:
    workspaces, engine = _workspaces(tmp_path)
    engine.server_config["save_path"] = str(tmp_path / "not-yet")
    assert workspaces.list() == [{"name": "default", "path": str(tmp_path / "not-yet"), "file_count": 0}]


def test_file_count_is_zero_for_a_folder_that_cannot_be_read(tmp_path) -> None:
    assert WorkspaceService.file_count(str(tmp_path / "missing")) == 0


def test_persist_active_saves_the_config_and_points_wgp_at_the_workspace(tmp_path) -> None:
    workspaces, engine = _workspaces(tmp_path)
    folder = workspaces.persist_active("film")
    assert folder == os.path.join(os.path.realpath(tmp_path / "outputs"), "film")
    assert engine.save_path == folder and engine.image_save_path == folder
    assert engine.server_config["services"] == {"active_workspace": "film"}
    saved = json.loads((tmp_path / "wgp_config.json").read_text(encoding="utf-8"))
    assert saved["services"] == {"active_workspace": "film"}


def test_persist_active_can_leave_the_save_paths_alone_while_a_generation_runs(tmp_path) -> None:
    workspaces, engine = _workspaces(tmp_path, services={"active_workspace": "default", "kept": 1})
    before = engine.save_path
    folder = workspaces.persist_active("film", apply_save_paths=False)
    assert engine.save_path == before and engine.image_save_path == before
    assert folder == os.path.join(os.path.realpath(tmp_path / "outputs"), "film")
    assert engine.server_config["services"] == {"active_workspace": "film", "kept": 1}
    assert json.loads((tmp_path / "wgp_config.json").read_text(encoding="utf-8"))["services"]["active_workspace"] == "film"


def test_persist_active_refuses_an_invalid_name_after_saving_it(tmp_path) -> None:
    """The switch writes the name before it resolves the folder, as the code it came from did."""
    workspaces, engine = _workspaces(tmp_path)
    with pytest.raises(HTTPException):
        workspaces.persist_active("../x")
    assert engine.server_config["services"]["active_workspace"] == "../x"


# --- request media paths --------------------------------------------------


def _policy(tmp_path) -> tuple[PathPolicy, WorkspaceService]:
    workspaces, _engine_ = _workspaces(tmp_path)
    return PathPolicy(workspaces), workspaces


def test_request_media_path_resolves_a_file_in_the_workspace_or_in_uploads(tmp_path, monkeypatch) -> None:
    policy, workspaces = _policy(tmp_path)
    monkeypatch.chdir(tmp_path)
    song = tmp_path / "outputs" / "song.wav"
    song.write_bytes(b"x")
    (tmp_path / "uploads" / "audio").mkdir(parents=True)
    upload = tmp_path / "uploads" / "audio" / "voice.wav"
    upload.write_bytes(b"x")
    assert policy.resolve_request_media_path("song.wav") == os.path.realpath(song)
    assert policy.resolve_request_media_path(str(song)) == os.path.realpath(song)
    assert policy.resolve_request_media_path("/api/v1/uploads/audio/voice.wav") == os.path.realpath(upload)
    assert policy.resolve_request_media_path("/api/v1/file/song.wav?workspace=default") == os.path.realpath(song)
    other = workspaces.workspace_dir("film")
    (tmp_path / "outputs" / "film" / "take.mp4").write_bytes(b"x")
    assert policy.resolve_request_media_path("take.mp4", workspace="film") == os.path.join(other, "take.mp4")


def test_request_media_path_answers_400_and_404_without_the_host_path(tmp_path, monkeypatch) -> None:
    policy, _workspaces_ = _policy(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outside.wav").write_bytes(b"x")
    (tmp_path / "outputs" / "picture.png").write_bytes(b"x")
    for value in ("../outside.wav", str(tmp_path / "outside.wav"), "picture.png", ""):
        with pytest.raises(HTTPException) as caught:
            policy.resolve_request_media_path(value)
        assert (caught.value.status_code, caught.value.detail) == (400, "Media path is not allowed")
        assert str(tmp_path) not in str(caught.value.detail)
    with pytest.raises(HTTPException) as caught:
        policy.resolve_request_media_path("missing.wav")
    assert (caught.value.status_code, caught.value.detail) == (404, "Media file not found")


def test_request_media_path_checks_the_workspace_name_first(tmp_path, monkeypatch) -> None:
    policy, _workspaces_ = _policy(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(HTTPException) as caught:
        policy.resolve_request_media_path("song.wav", workspace="../x")
    assert caught.value.status_code == 400 and "Invalid workspace name" in caught.value.detail


def test_request_media_path_only_admits_the_kinds_asked_for(tmp_path, monkeypatch) -> None:
    policy, _workspaces_ = _policy(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "outputs" / "clip.mp4").write_bytes(b"x")
    assert policy.resolve_request_media_path("clip.mp4").endswith("clip.mp4")
    with pytest.raises(HTTPException) as caught:
        policy.resolve_request_media_path("clip.mp4", kinds=("audio",))
    assert caught.value.status_code == 400


def test_story_cover_reference_is_found_in_uploads_audio_or_the_workspace(tmp_path, monkeypatch) -> None:
    policy, _workspaces_ = _policy(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "uploads" / "audio").mkdir(parents=True)
    (tmp_path / "uploads" / "audio" / "ref.wav").write_bytes(b"x")
    (tmp_path / "outputs" / "cover.wav").write_bytes(b"x")
    assert policy.story_cover_reference_path("ref.wav", "default") == os.path.realpath(tmp_path / "uploads" / "audio" / "ref.wav")
    assert policy.story_cover_reference_path("cover.wav", "default") == os.path.realpath(tmp_path / "outputs" / "cover.wav")
    assert policy.story_cover_reference_path("missing.wav", "default") is None
    assert policy.story_cover_reference_path("../x.wav", "default") is None
