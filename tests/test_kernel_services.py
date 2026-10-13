"""The shared kernel services (``app/services/kernel``), with no WanGP and no server.

Each service takes its engine as an argument, so a test hands it a plain
object. The full server is exercised by ``tests/characterization``.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import stat
import subprocess
import sys
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services import execution_mode, job_lifecycle, resource_scheduler
from services.kernel import paths as kernel_paths
from services.kernel.config import ConfigStore
from services import director_pipeline, task_manager
from services.kernel.context import RuntimeContext, build_context
from services.kernel.jobs import GenerationQueue
from services.kernel.paths import PathPolicy, safe_join
from services.kernel.tasks import CanonicalTasks
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


# --- the generation queue --------------------------------------------------

H3_LEGACY = "minimax_h3_legacy"
H3_NATIVE = "minimax_h3_native"


class _Hooks:
    """What the server hands the queue: the H3 predicates, the H3 cancel and the task publisher."""

    def __init__(self) -> None:
        self.cancelled_legacy = 0
        self.published: list[dict] = []
        self.publisher_result = None
        self.publisher_error: Exception | None = None
        self.publisher_present = True

    def is_legacy(self, model_type) -> bool:
        return str(model_type or "").strip() == H3_LEGACY

    def is_minimax(self, model_type) -> bool:
        return str(model_type or "").startswith("minimax_h3")

    def cancel_legacy(self) -> None:
        self.cancelled_legacy += 1

    def lookup(self):
        return self.publish if self.publisher_present else None

    def publish(self, job: dict):
        self.published.append(job)
        if self.publisher_error is not None:
            raise self.publisher_error
        return self.publisher_result


@pytest.fixture
def empty_fifo():
    """The coordinator's GPU-0 lock is shared by the process, and so is the FIFO behind it."""
    def clear() -> None:
        lock = resource_scheduler.coordinator.shared_lock(resource_scheduler.local_gpu_lane(0))
        with job_lifecycle._generation_queue_condition:
            job_lifecycle._generation_queues.pop(id(lock), None)

    clear()
    yield
    clear()


@pytest.fixture
def queue_parts(tmp_path, empty_fifo):
    engine = _engine(tmp_path, save_path=str(tmp_path / "outputs"))
    engine.get_model_def = lambda model_type: {"name": f"Name of {model_type}"} if model_type == "known_model" else None
    (tmp_path / "outputs").mkdir()
    config = ConfigStore(lambda: engine)
    workspaces = WorkspaceService(config)
    hooks = _Hooks()
    queue = GenerationQueue(
        config,
        workspaces,
        is_legacy_h3_model=hooks.is_legacy,
        is_minimax_h3_model=hooks.is_minimax,
        cancel_legacy_h3=hooks.cancel_legacy,
        task_publisher=hooks.lookup,
    )
    return SimpleNamespace(queue=queue, hooks=hooks, engine=engine, workspaces=workspaces, tmp_path=tmp_path)


def test_a_queue_owns_its_state_and_shares_the_coordinators_gpu_lock(queue_parts, tmp_path) -> None:
    queue = queue_parts.queue
    lane = resource_scheduler.local_gpu_lane(0)
    assert queue.registry == {} and queue.active_states == {}
    assert queue.local_gpu_lane == lane
    assert queue.gen_lock is resource_scheduler.coordinator.shared_lock(lane)
    assert queue.durable_queue.path == os.path.join(
        os.path.realpath(tmp_path / "outputs"), ".maestro_generation_queue.json",
    )
    assert not queue.recovery_lock.locked()
    other = GenerationQueue(
        queue._config, queue._workspaces,
        is_legacy_h3_model=queue._is_legacy_h3_model, is_minimax_h3_model=queue._is_minimax_h3_model,
        cancel_legacy_h3=queue._cancel_legacy_h3, task_publisher=queue._task_publisher,
    )
    assert other.registry is not queue.registry and other.active_states is not queue.active_states
    assert other.recovery_lock is not queue.recovery_lock


def test_building_a_queue_creates_no_file_and_no_thread(tmp_path, empty_fifo) -> None:
    engine = _engine(tmp_path, save_path=str(tmp_path / "fresh"))
    before = threading.active_count()
    config = ConfigStore(lambda: engine)
    GenerationQueue(
        config, WorkspaceService(config),
        is_legacy_h3_model=lambda _m: False, is_minimax_h3_model=lambda _m: False,
        cancel_legacy_h3=lambda: None, task_publisher=lambda: None,
    )
    assert not (tmp_path / "fresh").exists()
    assert threading.active_count() == before


def _params(**extra) -> dict:
    return {"model_type": "known_model", "prompt": "a prompt", **extra}


def test_new_job_freezes_the_request_and_reserves_its_place_in_the_fifo(queue_parts) -> None:
    queue = queue_parts.queue
    params = _params(nested={"a": [1]})
    job = queue.new_job(params, "default", job_id="j1", created_at=1700000000.0)
    params["nested"]["a"].append(2)
    assert job["params"]["nested"] == {"a": [1]}
    assert job["params"]["_execution_mode"] == execution_mode.policy().mode
    assert (job["id"], job["task_id"], job["root_task_id"]) == ("j1", "task-generation-j1", "task-generation-j1")
    assert (job["status"], job["message"], job["created_at"], job["recovered"]) == ("queued", "Queued", 1700000000.0, False)
    assert job["out_dir"] == os.path.realpath(queue_parts.tmp_path / "outputs")
    assert job["workspace"] == "default" and job["output_files"] == [] and job["acquired_resources"] == []
    assert job_lifecycle.generation_queue_position(queue.gen_lock, job) == 1
    assert "j1" not in queue.registry, "new_job does not add the job to the registry; its caller does"


def test_new_job_invents_an_id_and_stamps_the_time(queue_parts) -> None:
    job = queue_parts.queue.new_job(_params(), "default")
    assert len(job["id"]) == 8 and job["task_id"] == f"task-generation-{job['id']}"
    assert job["created_at"] > 0


def test_new_job_names_the_root_task_after_the_pipeline_that_owns_it(queue_parts) -> None:
    queue = queue_parts.queue
    series = queue.new_job(_params(_director_pipeline_id="series:abc"), "default", job_id="s1", reserve_generation=False)
    director = queue.new_job(_params(_director_pipeline_id="pipe-9"), "default", job_id="d1", reserve_generation=False)
    plain = queue.new_job(_params(), "default", job_id="p1", reserve_generation=False)
    assert series["root_task_id"] == "task-series-render-abc"
    assert director["root_task_id"] == "task-director-pipe-9"
    assert plain["root_task_id"] == "task-generation-p1"


def test_new_job_marks_a_recovered_job_and_can_skip_the_fifo(queue_parts) -> None:
    queue = queue_parts.queue
    job = queue.new_job(_params(), "default", job_id="r1", recovered=True, reserve_generation=False,
                        provenance={"origin": "recovery"})
    assert (job["recovered"], job["message"], job["provenance"]) == (True, "Recovered · queued", {"origin": "recovery"})
    assert job_lifecycle.generation_queue_position(queue.gen_lock, job) is None


def test_new_job_refuses_an_invalid_workspace_before_anything_is_reserved(queue_parts) -> None:
    with pytest.raises(HTTPException) as caught:
        queue_parts.queue.new_job(_params(), "../x", job_id="bad", reserve_generation=True)
    assert caught.value.status_code == 400
    assert job_lifecycle._generation_queues == {} or all(
        not entries for entries in job_lifecycle._generation_queues.values()
    )


def test_new_job_follows_the_execution_mode_policy(queue_parts, monkeypatch) -> None:
    queue = queue_parts.queue
    monkeypatch.setattr(execution_mode, "POLICY", SimpleNamespace(mode="simulate", workspace="sandbox"))
    with pytest.raises(execution_mode.ExecutionModeError, match="isolated to workspace 'sandbox'"):
        queue.new_job(_params(), "default", job_id="x", reserve_generation=False)
    monkeypatch.setattr(execution_mode, "POLICY", SimpleNamespace(mode="plan", workspace="default"))
    with pytest.raises(execution_mode.ExecutionModeError, match="Plan mode stops before queue submission"):
        queue.new_job(_params(), "default", job_id="x", reserve_generation=False)
    monkeypatch.setattr(execution_mode, "POLICY", SimpleNamespace(mode="simulate", workspace="default"))
    job = queue.new_job(_params(), "default", job_id="y", reserve_generation=False)
    assert job["params"]["_execution_mode"] == "simulate"


def test_new_job_publishes_through_the_publisher_found_at_call_time(queue_parts) -> None:
    hooks = queue_parts.hooks
    hooks.publisher_present = False
    first = queue_parts.queue.new_job(_params(), "default", job_id="a", reserve_generation=False)
    assert hooks.published == [] and first["task_id"] == "task-generation-a"
    hooks.publisher_present = True
    hooks.publisher_result = {"id": "task-published", "root_id": "task-root"}
    second = queue_parts.queue.new_job(_params(), "default", job_id="b", reserve_generation=False)
    assert hooks.published == [second]
    assert (second["task_id"], second["root_task_id"]) == ("task-published", "task-root")


def test_new_job_keeps_its_ids_when_the_publisher_answers_nothing_or_fails(queue_parts, capsys) -> None:
    hooks = queue_parts.hooks
    nothing = queue_parts.queue.new_job(_params(), "default", job_id="a", reserve_generation=False)
    assert (nothing["task_id"], nothing["root_task_id"]) == ("task-generation-a", "task-generation-a")
    hooks.publisher_error = RuntimeError("registry offline")
    failed = queue_parts.queue.new_job(_params(), "default", job_id="b", reserve_generation=False)
    assert failed["task_id"] == "task-generation-b"
    assert "[Task registry] Could not publish generation b: registry offline" in capsys.readouterr().out


def test_new_job_can_skip_publishing(queue_parts) -> None:
    queue_parts.queue.new_job(_params(), "default", job_id="a", reserve_generation=False, publish_task=False)
    assert queue_parts.hooks.published == []


def test_new_job_applies_the_h3_dialogue_duration_only_to_h3_models(queue_parts) -> None:
    queue = queue_parts.queue
    plain = queue.new_job(_params(), "default", job_id="p", reserve_generation=False)
    assert "_h3_dialogue_duration_contract" not in plain["params"]
    h3 = queue.new_job({"model_type": H3_NATIVE, "prompt": "hola"}, "default", job_id="h", reserve_generation=False)
    assert h3["params"]["model_type"] == H3_NATIVE and h3["status"] == "queued"


def _manual(job_id="m1", **extra) -> dict:
    return {"id": job_id, "workspace": "default", "status": "queued", **extra}


def test_register_manual_job_fills_the_defaults_and_publishes(queue_parts) -> None:
    queue, hooks = queue_parts.queue, queue_parts.hooks
    hooks.publisher_result = {"id": "task-m", "root_id": "task-m-root"}
    job = _manual(params={"prompt": "x"})
    assert queue.register_manual_job(job) is job
    assert queue.registry["m1"] is job
    assert job["params"] == {"prompt": "x", "_execution_mode": execution_mode.policy().mode,
                             "model_type": "post_processing", "generation_mode": "video"}
    assert (job["acquired_resources"], job["started_at"], job["finished_at"]) == ([], None, None)
    assert (job["task_id"], job["root_task_id"]) == ("task-m", "task-m-root")
    assert hooks.published == [job]
    assert job_lifecycle.generation_queue_position(queue.gen_lock, job) == 1


def test_register_manual_job_keeps_what_the_caller_set(queue_parts) -> None:
    job = _manual("m2", params={"model_type": "known_model", "generation_mode": "image"},
                  task_id="mine", root_task_id="my-root", started_at=5)
    queue_parts.queue.register_manual_job(job)
    assert (job["task_id"], job["root_task_id"], job["started_at"]) == ("mine", "my-root", 5)
    assert job["params"]["model_type"] == "known_model" and job["params"]["generation_mode"] == "image"


def test_register_manual_job_without_an_id_registers_nothing(queue_parts) -> None:
    with pytest.raises(ValueError, match="requires an id"):
        queue_parts.queue.register_manual_job({"params": {}})
    assert queue_parts.queue.registry == {}


def test_register_manual_job_uses_the_active_workspace_for_the_mode_check(queue_parts, monkeypatch) -> None:
    monkeypatch.setattr(execution_mode, "POLICY", SimpleNamespace(mode="simulate", workspace="sandbox"))
    queue_parts.engine.server_config["services"] = {"active_workspace": "sandbox"}
    queue_parts.queue.register_manual_job({"id": "m3"})
    assert "m3" in queue_parts.queue.registry
    queue_parts.engine.server_config["services"] = {"active_workspace": "other"}
    with pytest.raises(execution_mode.ExecutionModeError):
        queue_parts.queue.register_manual_job({"id": "m4"})
    assert "m4" not in queue_parts.queue.registry


def test_register_manual_job_survives_a_failing_publisher(queue_parts, capsys) -> None:
    queue_parts.hooks.publisher_error = RuntimeError("boom")
    job = _manual("m5", params={})
    queue_parts.queue.register_manual_job(job)
    assert queue_parts.queue.registry["m5"] is job
    assert "[Task registry] Could not publish manual job m5: boom" in capsys.readouterr().out


def test_job_acceptance_names_the_tasks_and_the_public_details(queue_parts) -> None:
    job = {"task_id": "t", "params": {"model_type": "known_model", "prompt": "p"}}
    accepted = queue_parts.queue.job_acceptance(job)
    assert accepted["task_id"] == "t" and accepted["root_task_id"] == "t"
    assert accepted["generation_details"]["model_name"] == "Name of known_model"
    assert queue_parts.queue.job_acceptance({"task_id": "t", "root_task_id": "r"})["root_task_id"] == "r"
    assert queue_parts.queue.job_acceptance({})["generation_details"] == {}


def test_public_details_keep_private_paths_out_and_bound_the_prompt(queue_parts) -> None:
    details = queue_parts.queue.public_details({
        "model_type": "known_model", "generation_mode": "video", "_execution_mode": "simulate",
        "prompt": "p\x00ix", "alt_prompt": " style ", "_initiator": "mcp\x00", "seed": 0, "resolution": "",
        "activated_loras": ["/secret/dir/a.safetensors", "C:\\x\\b.safetensors", " "],
        "start_image": "/private/frame.png",
    })
    assert details["prompt"] == "style\n\npix" and details["initiator"] == "mcp"
    assert details["loras"] == ["a.safetensors", "b.safetensors"] and details["lora_count"] == 2
    assert details["simulated"] is True and details["seed"] == 0 and "resolution" not in details
    assert "start_image" not in details and "/secret" not in json.dumps(details)
    assert len(queue_parts.queue.public_details({"model_type": "known_model", "prompt": "x" * 40_000})["prompt"]) == 32_000


def test_public_details_fall_back_to_the_label_or_the_model_type(queue_parts) -> None:
    queue = queue_parts.queue
    assert queue.public_details({"model_type": "post_processing"})["model_name"] == "Post-processing"
    assert queue.public_details({"model_type": "unheard_of"})["model_name"] == "unheard_of"
    assert queue.public_details("not a dict") == {} and queue.public_details({"model_type": " "}) == {}


def test_public_details_survive_an_engine_that_cannot_describe_the_model(queue_parts) -> None:
    def broken(_model_type):
        raise RuntimeError("catalog offline")

    queue_parts.engine.get_model_def = broken
    assert queue_parts.queue.public_details({"model_type": "known_model"})["model_name"] == "known_model"


def test_public_details_report_the_h3_cache_flag(queue_parts) -> None:
    queue = queue_parts.queue
    assert queue.public_details({"model_type": H3_NATIVE})["cache"] is False
    cached = queue.public_details({"model_type": "known_model", "skip_steps_cache_type": "tea"})
    assert (cached["cache"], cached["cache_type"]) == (True, "tea")


def test_only_ordinary_studio_generations_are_durable() -> None:
    durable = GenerationQueue.is_durable_job
    assert durable({"params": {"model_type": "m"}}) is True
    assert durable({"params": {"model_type": "m", "_director_pipeline_id": "p"}}) is False
    assert durable({"params": {"model_type": "m", "_non_durable_tool": True}}) is False
    assert durable({"params": {}}) is False and durable({}) is False and durable({"params": "x"}) is False


def test_persist_and_remove_use_the_durable_queue_file(queue_parts) -> None:
    queue = queue_parts.queue
    job = queue.new_job(_params(), "default", job_id="d1", created_at=12.5, reserve_generation=False,
                        provenance={"from": "test"})
    queue.persist_job(job)
    saved = queue.durable_queue.list()
    assert [(item["id"], item["status"], item["created_at"], item["workspace"], item["provenance"]) for item in saved] == [
        ("d1", "queued", 12.5, "default", {"from": "test"}),
    ]
    assert saved[0]["params"]["prompt"] == "a prompt"
    queue.remove_persisted_job(job)
    assert queue.durable_queue.list() == []


def test_persist_skips_what_is_not_durable_and_never_raises(queue_parts, capsys) -> None:
    queue = queue_parts.queue
    queue.persist_job({"id": "n", "params": {"model_type": "m", "_non_durable_tool": True}})
    assert queue.durable_queue.list() == []

    def refuse(_record):
        raise OSError("read-only disk")

    queue.durable_queue.upsert = refuse
    queue.persist_job({"id": "e", "params": {"model_type": "m"}})
    assert "[Queue recovery] Could not persist job e: read-only disk" in capsys.readouterr().out
    queue.durable_queue.remove = lambda _id: (_ for _ in ()).throw(OSError("busy"))
    queue.remove_persisted_job({"id": "e", "params": {"model_type": "m"}})
    assert "[Queue recovery] Could not remove job e: busy" in capsys.readouterr().out


def test_pending_gpu_jobs_are_the_queued_and_running_ones_that_name_a_model(queue_parts) -> None:
    queue = queue_parts.queue
    registry = queue.registry
    registry["q"] = {"status": "queued", "params": {"model_type": "m"}}
    registry["r"] = {"status": "running", "params": {"model_type": "m"}}
    registry["done"] = {"status": "completed", "params": {"model_type": "m"}}
    registry["audio"] = {"status": "running", "params": {}}
    registry["bare"] = {"status": "queued"}
    assert [job for job in queue.pending_gpu_jobs()] == [registry["q"], registry["r"]]
    assert queue.pending_gpu_jobs(exclude_job_id="q") == [registry["r"]]


def test_cancel_answers_missing_for_a_job_it_does_not_hold(queue_parts) -> None:
    assert queue_parts.queue.cancel("nope") == {"status": "missing", "was_running": False}


def test_cancel_settles_a_queued_job_and_forgets_its_durable_record(queue_parts) -> None:
    queue = queue_parts.queue
    job = queue.new_job(_params(), "default", job_id="c1")
    queue.registry["c1"] = job
    queue.persist_job(job)
    assert queue.cancel("c1") == {"status": "cancelled", "was_running": False}
    assert queue.durable_queue.list() == []
    assert queue_parts.hooks.cancelled_legacy == 0
    assert queue.cancel("c1") == {"status": "cancelled", "was_running": False}


def test_cancel_signals_the_abort_state_of_a_running_job(queue_parts) -> None:
    queue = queue_parts.queue
    job = queue.new_job(_params(), "default", job_id="c2", reserve_generation=False)
    queue.registry["c2"] = job
    assert job_lifecycle.try_start(job)
    state: dict = {}
    assert job_lifecycle.register_abort_state(job, "c2", queue.active_states, state)
    assert queue.cancel("c2") == {"status": "cancelling", "was_running": True}
    assert state["abort"] is True
    job_lifecycle.unregister_abort_state("c2", queue.active_states, state)
    assert queue.active_states == {} and job["status"] == "cancelled"
    assert queue_parts.hooks.cancelled_legacy == 0


def test_cancelling_a_running_legacy_h3_job_stops_the_isolated_runtime(queue_parts) -> None:
    queue = queue_parts.queue
    job = queue.new_job({"model_type": H3_LEGACY, "prompt": "x"}, "default", job_id="c3", reserve_generation=False)
    queue.registry["c3"] = job
    assert job_lifecycle.try_start(job)
    state: dict = {}
    job_lifecycle.register_abort_state(job, "c3", queue.active_states, state)
    queue.cancel("c3")
    assert queue_parts.hooks.cancelled_legacy == 1
    job_lifecycle.unregister_abort_state("c3", queue.active_states, state)


def _held(lock) -> bool:
    """The GPU lock is a semaphore: it is held when it cannot be taken without waiting."""
    if lock.acquire(blocking=False):
        lock.release()
        return False
    return True


@pytest.fixture
def adopted(monkeypatch):
    """Record what the slot hands the coordinator instead of running the engine hand-off."""
    seen: list[dict] = []

    @contextmanager
    def adopt_acquired(lane, *, task_id, description=""):
        seen.append({"lane": lane, "task_id": task_id, "description": description})
        yield lane

    monkeypatch.setattr(resource_scheduler.coordinator, "adopt_acquired", adopt_acquired)
    return seen


def test_slot_takes_the_gpu_in_turn_and_names_the_owner_by_engine(queue_parts, adopted) -> None:
    queue = queue_parts.queue
    wgp_job = {"id": "w", "params": {"model_type": "known_model"}}
    with queue.slot(wgp_job) as acquired:
        assert acquired is True and _held(queue.gen_lock)
    assert not _held(queue.gen_lock)
    legacy = {"id": "h", "params": {"model_type": H3_LEGACY}, "task_id": "task-h"}
    with queue.slot(legacy):
        pass
    with queue.slot({"id": "n", "params": {}}):
        pass
    with queue.slot({"id": "x", "params": {}}, description="custom"):
        pass
    assert [(item["task_id"], item["description"]) for item in adopted] == [
        ("w", resource_scheduler.gpu_engine_description(
            resource_scheduler.GPU_ENGINE_WGP, "HocusPocus Lab WGP generation · known_model")),
        ("task-h", resource_scheduler.gpu_engine_description(
            resource_scheduler.GPU_ENGINE_H3_LEGACY, "HocusPocus Lab H3 Legacy generation")),
        ("n", "HocusPocus Lab GPU generation"),
        ("x", "custom"),
    ]
    assert all(item["lane"] == queue.local_gpu_lane for item in adopted)


def test_slot_yields_false_for_a_job_cancelled_while_it_waited(queue_parts, adopted) -> None:
    queue = queue_parts.queue
    job = {"id": "gone", "params": {"model_type": "known_model"}, "cancel_requested": True}
    with queue.slot(job) as acquired:
        assert acquired is False
    assert adopted == [] and not _held(queue.gen_lock)
    assert job_lifecycle.generation_queue_position(queue.gen_lock, job) is None


# --- canonical tasks --------------------------------------------------------


@pytest.fixture
def tasks(tmp_path):
    workspaces, engine = _workspaces(tmp_path, services={"active_workspace": "film"})
    yield CanonicalTasks(workspaces), workspaces, engine
    for folder in (tmp_path / "outputs", tmp_path / "outputs" / "film", tmp_path / "outputs" / "other"):
        task_manager.forget_task_registry(os.path.realpath(folder))


def test_the_task_registry_of_the_active_workspace_is_the_one_for_its_folder(tasks) -> None:
    canonical, workspaces, _engine_ = tasks
    registry = canonical.for_workspace()
    assert registry is task_manager.get_task_registry(workspaces.workspace_dir("film"))
    assert canonical.for_workspace(None) is registry
    assert canonical.for_workspace("film") is registry


def test_a_named_workspace_has_its_own_task_registry(tasks) -> None:
    canonical, workspaces, _engine_ = tasks
    other = canonical.for_workspace("other")
    assert other is task_manager.get_task_registry(workspaces.workspace_dir("other"))
    assert other is not canonical.for_workspace("film")
    assert canonical.for_workspace("default") is task_manager.get_task_registry(workspaces.workspace_dir("default"))


def test_the_task_registry_follows_the_active_workspace_when_it_changes(tasks) -> None:
    canonical, _workspaces_, engine = tasks
    film = canonical.for_workspace()
    engine.server_config["services"]["active_workspace"] = "other"
    assert canonical.for_workspace() is not film
    assert canonical.for_workspace() is canonical.for_workspace("other")


def test_the_task_registry_refuses_an_invalid_workspace_name(tasks) -> None:
    canonical, _workspaces_, _engine_ = tasks
    with pytest.raises(HTTPException) as caught:
        canonical.for_workspace("../x")
    assert caught.value.status_code == 400


class _Adapter:
    def list(self, workspace):
        return []

    def snapshot(self, workspace, task_id):
        return None

    def cancel(self, workspace, task_id):
        return None


def test_adapters_register_once_per_kind_and_come_back_in_order(tasks) -> None:
    canonical = tasks[0]
    assert canonical.adapters() == {} and canonical.adapter_for("series") is None
    series, story = _Adapter(), _Adapter()
    canonical.register_adapter("series", series)
    canonical.register_adapter("story", story)
    assert canonical.adapter_for("series") is series
    assert list(canonical.adapters()) == ["series", "story"]
    with pytest.raises(ValueError, match="already registered for 'series'"):
        canonical.register_adapter("series", _Adapter())
    assert canonical.adapter_for("series") is series


@pytest.mark.parametrize("kind", ["", "  ", None, 3])
def test_an_adapter_needs_a_kind(tasks, kind) -> None:
    with pytest.raises(ValueError, match="needs a kind"):
        tasks[0].register_adapter(kind, _Adapter())


def test_the_adapter_list_is_a_copy(tasks) -> None:
    canonical = tasks[0]
    canonical.register_adapter("series", _Adapter())
    canonical.adapters().clear()
    assert list(canonical.adapters()) == ["series"]


# --- the context -------------------------------------------------------------


def _context(tmp_path, **config):
    engine = _engine(tmp_path, save_path=str(tmp_path / "outputs"), **config)
    hooks = _Hooks()
    ctx = build_context(
        profile="full",
        wgp_provider=lambda: engine,
        is_legacy_h3_model=hooks.is_legacy,
        is_minimax_h3_model=hooks.is_minimax,
        cancel_legacy_h3=hooks.cancel_legacy,
        task_publisher=hooks.lookup,
    )
    return ctx, engine, hooks


def test_build_context_wires_the_services_to_each_other(tmp_path, empty_fifo) -> None:
    ctx, engine, _hooks_ = _context(tmp_path, services={"active_workspace": "film"})
    assert isinstance(ctx, RuntimeContext) and ctx.profile == "full"
    assert ctx.config.wgp is engine and ctx.config.server_config is engine.server_config
    assert ctx.workspaces.active() == "film"
    assert ctx.scheduler is resource_scheduler.coordinator
    # One workspace service behind the others: a job built through the context lands in its folder.
    job = ctx.jobs.new_job({"model_type": "m"}, "default", job_id="w1", reserve_generation=False)
    assert job["out_dir"] == os.path.realpath(tmp_path / "outputs")
    assert ctx.tasks.for_workspace() is task_manager.get_task_registry(ctx.workspaces.workspace_dir("film"))
    assert ctx.jobs.durable_queue.path.startswith(os.path.realpath(tmp_path / "outputs"))
    task_manager.forget_task_registry(ctx.workspaces.workspace_dir("film"))


def test_the_context_is_frozen_but_its_shared_state_is_live(tmp_path, empty_fifo) -> None:
    ctx, _engine_, _hooks_ = _context(tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.jobs = None
    registry = ctx.jobs.registry
    registry["a"] = {"status": "queued"}
    assert ctx.jobs.registry is registry and ctx.jobs.registry["a"]["status"] == "queued"


def test_two_contexts_do_not_share_job_state(tmp_path, empty_fifo) -> None:
    first, _e1, _h1 = _context(tmp_path)
    second, _e2, _h2 = _context(tmp_path)
    assert first.jobs.registry is not second.jobs.registry
    assert first.jobs.active_states is not second.jobs.active_states
    assert first.jobs.recovery_lock is not second.jobs.recovery_lock
    assert first.jobs.durable_queue is not second.jobs.durable_queue
    assert first.scheduler is second.scheduler


def test_the_context_names_the_profile_it_was_built_for(tmp_path, empty_fifo) -> None:
    engine = _engine(tmp_path, save_path=str(tmp_path / "outputs"))
    core = build_context(
        profile="core", wgp_provider=lambda: engine, is_legacy_h3_model=lambda _m: False,
        is_minimax_h3_model=lambda _m: False, cancel_legacy_h3=lambda: None, task_publisher=lambda: None,
    )
    assert core.profile == "core"


def test_importing_the_kernel_starts_nothing_and_does_not_touch_wgp(tmp_path) -> None:
    """Import time creates no thread, no file and no engine: the server builds the context once WanGP is bound."""
    app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
    probe = (
        "import os, sys, threading\n"
        f"sys.path.insert(0, {app!r})\n"
        "before = threading.active_count()\n"
        "import services.kernel.config, services.kernel.paths, services.kernel.workspaces, "
        "services.kernel.jobs, services.kernel.tasks, services.kernel.context\n"
        "print(threading.active_count() - before, 'wgp' in sys.modules, "
        "'torch' in sys.modules, sorted(os.listdir('.')))\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", probe], cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "0 False False []"


# --- the Director pipeline gets its hardware probe from the server ---------------------------


@pytest.fixture
def pipeline_wiring(monkeypatch, tmp_path):
    for name in ("_jobs", "_run_generation", "_cancel_generation", "_wgp", "_gen_lock", "_active_gen_states",
                 "_pipeline_state_observer", "_get_cached_hardware"):
        monkeypatch.setattr(director_pipeline, name, None)
    engine = SimpleNamespace(server_config={"save_path": str(tmp_path)})

    def wire(**kwargs):
        director_pipeline.init({}, lambda _job_id: None, engine, **kwargs)

    return wire


def test_the_director_reads_the_hardware_the_server_cached(pipeline_wiring) -> None:
    probe = {"gpu_vram_gb": 24.0, "cuda_available": True}
    pipeline_wiring(get_cached_hardware=lambda: probe)
    snapshot = director_pipeline._director_hardware_snapshot()
    assert snapshot == probe and snapshot is not probe


def test_the_director_probes_the_hardware_itself_when_none_was_wired(pipeline_wiring, monkeypatch) -> None:
    from services import hardware_detect

    monkeypatch.setattr(hardware_detect, "detect_hardware", lambda: {"gpu_vram_gb": 8.0})
    pipeline_wiring()
    assert director_pipeline._director_hardware_snapshot() == {"gpu_vram_gb": 8.0}


def test_the_director_falls_back_when_the_cached_probe_fails(pipeline_wiring, monkeypatch) -> None:
    from services import hardware_detect

    def broken():
        raise RuntimeError("probe failed")

    pipeline_wiring(get_cached_hardware=broken)
    monkeypatch.setattr(hardware_detect, "detect_hardware", lambda: {"gpu_vram_gb": 6.0})
    assert director_pipeline._director_hardware_snapshot() == {"gpu_vram_gb": 6.0}
    monkeypatch.setattr(hardware_detect, "detect_hardware", broken)
    assert director_pipeline._director_hardware_snapshot() == {"gpu_vram_gb": 0.0}
