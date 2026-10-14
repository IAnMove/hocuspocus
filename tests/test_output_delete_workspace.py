"""Gallery delete must remove the file from the listed workspace, not the active one."""

from __future__ import annotations

import ast
import copy
import os
import sys
import types
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.kernel.paths import PathPolicy


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "app" / "services" / "output_ops.py"


def load_functions(names: list[str], namespace: dict) -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    selected = []
    for name in names:
        node = copy.deepcopy(next(
            item
            for item in tree.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == name
        ))
        node.decorator_list = []
        selected.append(node)
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(SOURCE), "exec"), namespace)


def delete_namespace(active: Path, film: Path) -> dict:
    namespace = {
        "os": os,
        "HTTPException": HTTPException,
        "_workspace_dir": lambda workspace=None: str(film if workspace == "film" else active),
        "_load_favorites": lambda: set(),
        "_save_favorites": lambda _favorites: None,
        "_safe_join": PathPolicy().safe_join,
    }
    load_functions(["delete_output"], namespace)
    return namespace


def install_delete_stubs(monkeypatch) -> None:
    win = types.ModuleType("services.win_safe_files")
    win.favorites_lock = __import__("threading").RLock()

    def safe_delete(path):
        os.remove(path)
        return {"deleted": True}

    win.safe_delete = safe_delete
    monkeypatch.setitem(sys.modules, "services.win_safe_files", win)
    search = types.ModuleType("services.search_index")
    search.get_search_index = lambda: types.SimpleNamespace(remove_file=lambda _name: None)
    monkeypatch.setitem(sys.modules, "services.search_index", search)


def test_delete_output_uses_the_listed_workspace_not_the_active_one(tmp_path, monkeypatch):
    active = tmp_path / "ads"
    film = tmp_path / "film"
    active.mkdir()
    film.mkdir()
    (active / "hero.png").write_bytes(b"ads-hero")
    (film / "hero.png").write_bytes(b"film-hero")
    (film / "hero.meta.json").write_text("{}", encoding="utf-8")
    install_delete_stubs(monkeypatch)
    namespace = delete_namespace(active, film)

    result = namespace["delete_output"]("hero.png", workspace="film")

    assert result == {"deleted": "hero.png"}
    assert not (film / "hero.png").exists()
    assert (active / "hero.png").read_bytes() == b"ads-hero"


def test_delete_output_without_workspace_still_uses_the_active_folder(tmp_path, monkeypatch):
    active = tmp_path / "ads"
    film = tmp_path / "film"
    active.mkdir()
    film.mkdir()
    (active / "hero.png").write_bytes(b"ads-hero")
    (film / "hero.png").write_bytes(b"film-hero")
    install_delete_stubs(monkeypatch)
    namespace = delete_namespace(active, film)

    result = namespace["delete_output"]("hero.png")

    assert result == {"deleted": "hero.png"}
    assert not (active / "hero.png").exists()
    assert (film / "hero.png").read_bytes() == b"film-hero"


@pytest.mark.parametrize("name", ["../outside.png", "/tmp/outside.png"])
def test_delete_output_rejects_traversal(tmp_path, monkeypatch, name):
    active = tmp_path / "ads"
    film = tmp_path / "film"
    active.mkdir()
    film.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"keep")
    install_delete_stubs(monkeypatch)
    namespace = delete_namespace(active, film)

    result = namespace["delete_output"](name, workspace="film")

    assert result == {"deleted": name}
    assert outside.read_bytes() == b"keep"


# --- DELETE /api/v1/workspaces/{name} with running work ---------------------------------
#
# Every family of long jobs registers a probe with services.workspace_busy, and the delete
# route refuses while one of them has a live job in THAT workspace. The tests below seed the
# real registry or store of each family (never a fake probe), delete workspace "film" and
# then workspace "other".

@pytest.fixture(autouse=True)
def _workspace_busy_table_per_test():
    """Each test of this file starts with an empty probe table and puts the previous one back."""
    from services import workspace_busy

    with workspace_busy.isolated():
        yield


LEGACY_GENERATION_TEXT = "A generation is queued or running. Wait for it to finish before deleting a workspace."


def _workspace_client(tmp_path, *, profile=None, jobs=None):
    """The real workspace router over two folders: ``film`` (with a clip) and ``other``."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.workspace_outputs import create_workspace_router

    for name in ("film", "other"):
        (tmp_path / name).mkdir(exist_ok=True)
        (tmp_path / name / "clip.mp4").write_bytes(b"clip")
    app = FastAPI()
    app.include_router(create_workspace_router(
        list_workspaces=lambda: [{"name": "film"}, {"name": "other"}],
        get_active_workspace=lambda: "default",
        persist_active=lambda name, apply_save_paths=True: str(tmp_path / name),
        workspace_dir=lambda name: str(tmp_path / name),
        generation_idle=lambda: True,
        jobs=jobs,
        safe_join=PathPolicy().safe_join,
        save_path=lambda: str(tmp_path),
        busy_profile=profile,
    ))
    return TestClient(app)


def _assert_refuses_film_then_allows_it(client, tmp_path, kind, release):
    """A job of ``kind`` runs in ``film``: its delete is refused, ``other`` still goes, and ``film`` goes once released."""
    refused = client.delete("/api/v1/workspaces/film")
    kept = (tmp_path / "film" / "clip.mp4").is_file()
    other = client.delete("/api/v1/workspaces/other")
    release()
    deleted = client.delete("/api/v1/workspaces/film")

    assert refused.status_code == 409, refused.text
    body = refused.json()
    assert isinstance(body["detail"], str), "the UI shows detail as text, so it must stay a string"
    assert kind in body["detail"] and "film" in body["detail"]
    assert body["code"] == "workspace_busy"
    assert [item["kind"] for item in body["blocking"]] == [kind]
    assert body["blocking"][0]["workspace"] in ("film", "")
    assert kept, "a refused delete leaves the folder alone"
    assert other.status_code == 200, "a job in film must not block deleting another workspace"
    assert not (tmp_path / "other").exists()
    assert deleted.status_code == 200, deleted.text
    assert not (tmp_path / "film").exists()


def _put_editor_job(job_id, workspace, status):
    """An editor job straight into the registry (``_register_video_editor_job`` would also publish it to whatever
    Activity publisher an earlier test bound)."""
    from routers import video_editor

    with video_editor._video_editor_jobs_lock:
        video_editor._video_editor_jobs[job_id] = {"job_id": job_id, "workspace": workspace, "status": status}


def _seed_video_editor(_tmp_path):
    from routers.video_editor import reset_video_editor_jobs

    reset_video_editor_jobs()
    _put_editor_job("export-film", "film", "running")
    return reset_video_editor_jobs


def _seed_minimax_music(_tmp_path):
    from services import story_music_jobs as music

    def reset():
        with music._minimax_music_jobs_lock:
            music._minimax_music_jobs.clear()

    reset()
    with music._minimax_music_jobs_lock:
        music._minimax_music_jobs["minimax-music-aaaaaaaaaaaa"] = {
            "jobId": "minimax-music-aaaaaaaaaaaa", "workspace": "film", "status": "queued",
        }
    return reset


def _seed_minimax_image(_tmp_path):
    from routers import comics

    def reset():
        with comics._minimax_image_jobs_lock:
            comics._minimax_image_jobs.clear()

    reset()
    with comics._minimax_image_jobs_lock:
        comics._minimax_image_jobs["minimax-image-1"] = {
            "jobId": "minimax-image-1", "workspace": "film", "status": "waiting_resource",
        }
    return reset


def _seed_job_table(module, job_id, record):
    """Put one job in a service's ``_jobs`` table (under its lock); returns the function that empties it."""

    def reset():
        with module._lock:
            module._jobs.clear()
            module._processes.clear()

    reset()
    with module._lock:
        module._jobs[job_id] = record
    return reset


def _seed_rig(_tmp_path):
    from services import rig_service

    return _seed_job_table(rig_service, "rig-1", {"workspace": "film", "status": "running", "engine": "procedural"})


def _seed_model3d(_tmp_path):
    from services import model3d_service

    return _seed_job_table(model3d_service, "model3d-1", {"workspace": "film", "status": "queued", "model_id": "m"})


def _seed_claimed_planner(module, jobs_name, claims_name, lock_name, job_id):
    """A planner running in ``film``: its record is in the job table and its id is in the claim set."""

    def reset():
        with getattr(module, lock_name):
            getattr(module, jobs_name).clear()
            getattr(module, claims_name).clear()

    reset()
    with getattr(module, lock_name):
        getattr(module, jobs_name)[job_id] = {"jobId": job_id, "workspace": "film", "status": "running"}
        getattr(module, claims_name).add(job_id)
    return reset


def _seed_story_plan(_tmp_path):
    from services import story_lab_jobs

    return _seed_claimed_planner(
        story_lab_jobs, "_story_plan_jobs", "_story_plan_active_jobs", "_story_plan_jobs_lock", "story-plan-aaaaaaaaaaaa",
    )


def _seed_comic_plan(_tmp_path):
    from services import director_comic_jobs

    return _seed_claimed_planner(
        director_comic_jobs, "_comic_plan_jobs", "_comic_plan_active_jobs", "_comic_plan_jobs_lock", "comic-plan-job-aaaaaaaaaaaa",
    )


def _director_plan_claims(*, folder, claim=True):
    """A Director v2 planning checkpoint in ``folder``; claimed by a worker unless ``claim`` is false."""
    from services import director_plan_jobs as plans

    def reset():
        with plans._STORE_LOCK:
            plans._ACTIVE_JOB_IDS.clear()

    reset()
    job = plans.DirectorPlanJobStore(str(folder)).create({"clips": []}, workspace=folder.name, skill_type="music_video", total=3)
    if claim:
        assert plans.claim_director_plan_job(job["jobId"])
    return reset


def _seed_director_plan(tmp_path):
    return _director_plan_claims(folder=tmp_path / "film")


def _game_produce_service(tmp_path):
    """A real GameProduce behind the real router factory, which is what registers the busy probe."""
    from routers.game_produce import create_game_produce_router
    from services.game_produce import GameProduce, ProduceDeps

    deps = ProduceDeps(
        call=lambda _tool, _args: {}, loopback=lambda _tool, _args: {},
        workspace_dir=lambda name: str(tmp_path / name),
        read_game=lambda _workspace, _game: {}, write_attempt=lambda *_args, **_kwargs: None,
    )
    service = GameProduce(deps)
    create_game_produce_router(service, call=deps.call, bind_loop=lambda _loop: None, read_game=deps.read_game)
    return service


def _save_game_job(tmp_path, job_id="game-produce-aaaaaaaa", status="running"):
    from services.game_jobs import GameJobStore

    GameJobStore(str(tmp_path / "film")).save({"jobId": job_id, "workspace": "film", "gameId": "g", "status": status, "steps": []})


def _seed_game_produce(tmp_path):
    """A produce job whose worker thread is alive, as the service itself would register it."""
    import threading

    service = _game_produce_service(tmp_path)
    _save_game_job(tmp_path)
    stop = threading.Event()
    worker = threading.Thread(target=stop.wait, daemon=True)
    worker.start()
    service._threads["game-produce-aaaaaaaa"] = worker

    def release():
        stop.set()
        worker.join(2)

    return release


def _seed_series_plan(_tmp_path):
    from services import series_plan_jobs

    return _seed_claimed_planner(
        series_plan_jobs, "_series_plan_jobs", "_series_plan_active_jobs", "_series_plan_jobs_lock", "series-plan-aaaaaaaaaaaa",
    )


def _seed_series_render(_tmp_path):
    from services import series_render_jobs

    return _seed_claimed_planner(
        series_render_jobs, "_series_render_jobs", "_series_render_active_jobs", "_series_render_jobs_lock", "series-render-aaaaaaaa",
    )


def _series_services(tmp_path):
    """The three Series job services, each behind its real router factory (which registers its busy probe)."""
    from routers.series_native_render import create_series_native_render_router
    from routers.series_produce import create_series_produce_router
    from routers.series_shot_inspector import create_series_shot_inspector_router
    from services.series_line_voice import SeriesLineVoice
    from services.series_native_render import NativeRenderDeps, SeriesNativeRender
    from services.series_produce import ProduceDeps, SeriesProduce

    def folder(workspace):
        return str(tmp_path / workspace)

    def library(_workspace):
        return {}

    def tool(_name, _args):
        return {}

    def no_loop(_loop):
        return None

    render = SeriesNativeRender(NativeRenderDeps(call=tool, workspace_dir=folder, read_library=library, read_kits=library))
    produce = SeriesProduce(ProduceDeps(call=tool, workspace_dir=folder, read_library=library))
    voices = SeriesLineVoice(render, read_library=library, read_kits=library)
    create_series_native_render_router(render, no_loop)
    create_series_produce_router(
        produce, call=tool, bind_loop=no_loop, read_library=library, read_kits=library, workspace_dir=folder,
    )
    create_series_shot_inspector_router(voices=voices, read_library=library, workspace_dir=folder, call=tool, bind_loop=no_loop)
    return {"produce": produce, "native": render, "voice": voices}


def _save_series_checkpoint(tmp_path, store_kind, status="running"):
    from services.series_jobs import SeriesJobStore

    job_id = f"{store_kind}-aaaaaaaaaaaa"
    SeriesJobStore(str(tmp_path / "film"), store_kind).save({
        "jobId": job_id, "workspace": "film", "seriesId": "s", "episodeId": "e", "status": status,
    })
    return job_id


def _seed_series_worker(store_kind):
    def seed(tmp_path):
        import threading

        service = _series_services(tmp_path)[store_kind]
        job_id = _save_series_checkpoint(tmp_path, store_kind)
        stop = threading.Event()
        worker = threading.Thread(target=stop.wait, daemon=True)
        worker.start()
        service._threads[job_id] = worker

        def release():
            stop.set()
            worker.join(2)

        return release

    return seed


def _seed_series_assembly(tmp_path):
    """An assembly started through its real route, held inside the join until released."""
    import shutil
    import threading
    import time

    from routers.series_assembly import SeriesAssemblyStartRequest
    from tests.test_series_assembly_router import _client

    entered, gate = threading.Event(), threading.Event()

    def concatenate(paths, output_path):
        entered.set()
        gate.wait(10)
        shutil.copyfile(paths[0], output_path)
        return True

    endpoints, _library = _client(tmp_path, concatenate, workspace_path=lambda workspace: str(tmp_path / workspace))
    started = endpoints["/api/v1/series/{series_id}/episodes/{episode_id}/assembly/start"](
        "series-1", "episode-1", SeriesAssemblyStartRequest(workspace="film"),
    )
    assert entered.wait(5), "the assembly worker never reached the join"

    def release():
        gate.set()
        status = endpoints["/api/v1/series/assembly/jobs/{job_id}"]
        for _ in range(200):
            if status(started["jobId"], "film")["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                break
            time.sleep(0.01)
        for thread in threading.enumerate():
            if thread.name.startswith("series-assembly-"):
                thread.join(2)

    return release


def _live_thread():
    """A started thread that stays alive until the returned ``stop`` is called."""
    import threading

    gate = threading.Event()
    worker = threading.Thread(target=gate.wait, daemon=True)
    worker.start()

    def stop():
        gate.set()
        worker.join(2)

    return worker, stop


def _seed_music_production(_tmp_path):
    """A production run in ``film``, held in the slot table the way ``production.run`` registers it."""
    from services import music_production

    worker, stop = _live_thread()
    with music_production._lock:
        music_production._threads["film/prod-aaaaaaaa"] = worker

    def release():
        stop()
        with music_production._lock:
            music_production._threads.pop("film/prod-aaaaaaaa", None)

    return release


# (kind, profile, seeder). Each seeder fills the family's real registry for workspace "film"
# and returns the function that ends that job.
BUSY_FAMILIES = [
    pytest.param("video-editor", "full", _seed_video_editor, id="video-editor"),
    pytest.param("minimax-music", "full", _seed_minimax_music, id="minimax-music"),
    pytest.param("minimax-image", "full", _seed_minimax_image, id="minimax-image"),
    pytest.param("rig", "full", _seed_rig, id="rig"),
    pytest.param("model3d", "full", _seed_model3d, id="model3d"),
    pytest.param("story-plan", "full", _seed_story_plan, id="story-plan"),
    pytest.param("comic-plan", "full", _seed_comic_plan, id="comic-plan"),
    pytest.param("director-plan", "full", _seed_director_plan, id="director-plan"),
    pytest.param("game-produce", "full", _seed_game_produce, id="game-produce"),
    pytest.param("series-plan", "full", _seed_series_plan, id="series-plan-full"),
    pytest.param("series-plan", "core", _seed_series_plan, id="series-plan-core"),
    pytest.param("series-render", "full", _seed_series_render, id="series-render"),
    pytest.param("series-produce", "full", _seed_series_worker("produce"), id="series-produce"),
    pytest.param("series-native", "full", _seed_series_worker("native"), id="series-native"),
    pytest.param("series-voice", "full", _seed_series_worker("voice"), id="series-voice"),
    pytest.param("series-assembly", "full", _seed_series_assembly, id="series-assembly-full"),
    pytest.param("series-assembly", "core", _seed_series_assembly, id="series-assembly-core"),
    pytest.param("music-production", "full", _seed_music_production, id="music-production-full"),
    pytest.param("music-production", "core", _seed_music_production, id="music-production-core"),
]


@pytest.mark.parametrize(("kind", "profile", "seed"), BUSY_FAMILIES)
def test_delete_workspace_refuses_while_a_family_job_runs_in_it(tmp_path, kind, profile, seed):
    client = _workspace_client(tmp_path, profile=profile)
    release = seed(tmp_path)
    try:
        _assert_refuses_film_then_allows_it(client, tmp_path, kind, release)
    finally:
        release()


def test_a_finished_editor_export_does_not_block_the_delete(tmp_path):
    from routers.video_editor import reset_video_editor_jobs

    client = _workspace_client(tmp_path, profile="full")
    reset_video_editor_jobs()
    try:
        for index, status in enumerate(("completed", "failed", "cancelled")):
            _put_editor_job(f"done-{index}", "film", status)
        deleted = client.delete("/api/v1/workspaces/film")
    finally:
        reset_video_editor_jobs()
    assert deleted.status_code == 200, deleted.text


def test_the_generation_queue_check_keeps_its_text_and_stays_global(tmp_path):
    client = _workspace_client(tmp_path, jobs=lambda: [{"status": "running", "workspace": "film"}])

    refused = client.delete("/api/v1/workspaces/other")

    assert refused.status_code == 409
    assert refused.json() == {"detail": LEGACY_GENERATION_TEXT}


def test_deleting_a_workspace_forgets_its_cached_task_registry(tmp_path):
    from services.task_manager import get_task_registry

    client = _workspace_client(tmp_path)
    film = tmp_path / "film"
    get_task_registry(str(film)).create(kind="x", workflow="x", title="t")

    assert client.delete("/api/v1/workspaces/film").status_code == 200
    film.mkdir()  # the same name, created again in the same process

    assert get_task_registry(str(film)).list() == []


def test_a_probe_that_cannot_answer_refuses_the_delete(tmp_path):
    from services import workspace_busy

    client = _workspace_client(tmp_path)
    with workspace_busy.isolated():
        workspace_busy.register("broken", lambda _workspace, _folder: 1 / 0)
        refused = client.delete("/api/v1/workspaces/film")

    assert refused.status_code == 409
    assert refused.json()["blocking"] == [{"kind": "broken", "jobId": "", "status": "probe_error", "workspace": "film"}]
    assert "could not be checked" in refused.json()["detail"]
    assert (tmp_path / "film").is_dir()


def test_busy_registry_filters_by_workspace_and_blocks_jobs_that_name_none():
    from services import workspace_busy

    jobs = [
        {"jobId": "a", "status": "running", "workspace": "film"},
        {"jobId": "b", "status": "queued", "workspace": "other"},
        {"job_id": "c", "status": "cancelling", "workspace": None},
        {"id": "d", "status": "waiting_resource"},
    ]
    with workspace_busy.isolated():
        workspace_busy.register("things", lambda _workspace, _folder: jobs)
        film = workspace_busy.blocking("film", "/x/film")
        other = workspace_busy.blocking("other", "/x/other")
        unrelated = workspace_busy.blocking("third", "/x/third")

    assert [item["jobId"] for item in film] == ["a", "c", "d"]
    assert [item["jobId"] for item in other] == ["b", "c", "d"]
    assert [item["jobId"] for item in unrelated] == ["c", "d"], "a job with no workspace is global (fail closed)"
    assert all(item["kind"] == "things" for item in film)


def test_a_job_that_names_its_workspace_in_another_case_still_blocks_it():
    """Windows (full server) and macOS (core) folders ignore case: a job started for "Film" writes into "film"."""
    from services import workspace_busy

    jobs = [{"jobId": "mixed", "status": "running", "workspace": "Film"}]
    with workspace_busy.isolated():
        workspace_busy.register("things", lambda _workspace, _folder: jobs)
        film = workspace_busy.blocking("film", "/x/film")
        other = workspace_busy.blocking("other", "/x/other")

    assert [item["jobId"] for item in film] == ["mixed"]
    assert other == []


def test_busy_registry_registers_replaces_and_isolates():
    from services import workspace_busy

    first = lambda _w, _d: [{"jobId": "1", "status": "running", "workspace": "film"}]  # noqa: E731
    second = lambda _w, _d: [{"jobId": "2", "status": "running", "workspace": "film"}]  # noqa: E731
    with workspace_busy.isolated():
        assert workspace_busy.registered() == ()
        workspace_busy.register("k", first)
        workspace_busy.register("k", second)  # a rebuilt router factory replaces its own probe
        assert workspace_busy.registered() == ("k",)
        assert [item["jobId"] for item in workspace_busy.blocking("film", "/x")] == ["2"]
        with pytest.raises(ValueError):
            workspace_busy.register("", first)
        with pytest.raises(ValueError):
            workspace_busy.register("k2", None)
        workspace_busy.unregister("k")
        assert workspace_busy.blocking("film", "/x") == []
    assert "k" not in workspace_busy.registered()


def test_busy_registry_counts_only_the_positive_active_statuses():
    from services import workspace_busy

    for status in ("created", "queued", "waiting", "waiting_resource", "running", "cancelling", "RUNNING "):
        assert workspace_busy.is_active(status), status
    for status in ("completed", "failed", "cancelled", "interrupted", "paused", "weird", "", None):
        assert not workspace_busy.is_active(status), status


def test_busy_message_names_each_blocker_and_stays_short():
    from services import workspace_busy

    items = [{"kind": f"k{index}", "jobId": f"j{index}", "status": "running", "workspace": "film"} for index in range(9)]
    items.append({"kind": "late", "jobId": "", "status": "probe_error", "workspace": "film"})

    text = workspace_busy.message("film", items)
    refusal = workspace_busy.refusal("film", items)

    assert text.startswith("Cannot delete workspace 'film' while work is still running in it: k0 j0 (running), k1 j1 (running)")
    assert "and 4 more" in text and "k8" not in text
    assert refusal == {"detail": text, "code": "workspace_busy", "blocking": items}
    assert workspace_busy.message("film", items[-1:]).count("late (could not be checked)") == 1


@pytest.mark.parametrize("module_name", ["rig_service", "model3d_service"])
def test_a_cancelled_job_whose_worker_process_is_still_unwinding_keeps_the_workspace_busy(tmp_path, module_name):
    import importlib

    module = importlib.import_module(f"services.{module_name}")
    client = _workspace_client(tmp_path, profile="full")
    release = _seed_job_table(module, "job-1", {"workspace": "film", "status": "cancelled"})
    try:
        with module._lock:
            module._processes["job-1"] = object()
        refused = client.delete("/api/v1/workspaces/film")
        with module._lock:
            module._processes.clear()
        allowed = client.delete("/api/v1/workspaces/film")
    finally:
        release()
    assert refused.status_code == 409, refused.text
    assert refused.json()["blocking"][0]["status"] == "cancelling"
    assert allowed.status_code == 200, allowed.text


FULL_BUSY_KINDS = {
    "video-editor", "minimax-music", "minimax-image", "rig", "series-plan", "music-production",
    "model3d", "story-plan", "comic-plan", "director-plan", "series-render",
}
CORE_BUSY_KINDS = {
    "video-editor", "minimax-music", "minimax-image", "rig", "series-plan", "music-production", "core-3d", "core-image",
}
ROUTER_BUSY_KINDS = {"game-produce", "series-produce", "series-native", "series-voice", "series-assembly"}


def test_the_busy_profiles_name_real_probes_and_core_runs_only_what_it_mounts():
    import importlib

    from routers import workspace_busy_probes as manifest

    for name, families in manifest.PROFILES.items():
        kinds = [kind for kind, _module in families]
        assert len(kinds) == len(set(kinds)), f"{name} lists a kind twice"
        for kind, module in families:
            assert callable(getattr(importlib.import_module(module), manifest.PROBE_FUNCTION)), (kind, module)
    assert {kind for kind, _module in manifest.PROFILES["full"]} == FULL_BUSY_KINDS
    assert {kind for kind, _module in manifest.PROFILES["core"]} == CORE_BUSY_KINDS
    assert set(manifest.REGISTERED_BY_THE_ROUTER) == ROUTER_BUSY_KINDS
    with pytest.raises(ValueError):
        manifest.register_profile("nonexistent")


def test_each_router_that_registers_its_own_busy_probe_does_so_by_name():
    from routers import workspace_busy_probes as manifest

    for kind, module in manifest.REGISTERED_BY_THE_ROUTER.items():
        source = (ROOT / "app" / (module.replace(".", "/") + ".py")).read_text(encoding="utf-8")
        assert f'workspace_busy.register("{kind}"' in source, (kind, module)


# Every module-level table or set that holds the live jobs or worker threads of a family, with the
# probe that covers it, or the reason it needs none. A new one fails the test below until it is
# listed here, which is the moment to decide whether a workspace delete must wait for it.
NOT_YET_PROBED = "NOT COVERED YET (wave W1 follow-up, see its report): "
JOB_REGISTRIES = {
    ("services/core_remote_3d.py", "_JOBS"): "core-3d",
    ("services/core_remote_image.py", "_JOBS"): "core-image",
    ("services/director_comic_jobs.py", "_comic_plan_jobs"): "comic-plan",
    ("services/director_comic_jobs.py", "_comic_plan_active_jobs"): "comic-plan",
    ("services/director_plan_jobs.py", "_ACTIVE_JOB_IDS"): "director-plan",
    ("services/director_pipeline.py", "_pipeline_child_jobs"): "exempt: the delete route asks director_pipeline.any_pipeline_active()",
    ("services/director_pipeline.py", "_pipeline_threads"): "exempt: the delete route asks director_pipeline.any_pipeline_active()",
    ("services/model3d_service.py", "_jobs"): "model3d",
    ("services/model3d_service.py", "_processes"): "model3d",
    ("services/music_production.py", "_threads"): "music-production",
    ("services/rig_service.py", "_jobs"): "rig",
    ("services/rig_service.py", "_processes"): "rig",
    ("services/series_plan_jobs.py", "_series_plan_jobs"): "series-plan",
    ("services/series_plan_jobs.py", "_series_plan_active_jobs"): "series-plan",
    ("services/series_render_jobs.py", "_series_render_jobs"): "series-render",
    ("services/series_render_jobs.py", "_series_render_active_jobs"): "series-render",
    ("services/story_lab_jobs.py", "_story_plan_jobs"): "story-plan",
    ("services/story_lab_jobs.py", "_story_plan_active_jobs"): "story-plan",
    ("services/story_music_jobs.py", "_minimax_music_jobs"): "minimax-music",
    ("routers/comics.py", "_minimax_image_jobs"): "minimax-image",
    ("routers/video_editor.py", "_video_editor_jobs"): "video-editor",
}


def _module_level_job_tables():
    import ast
    import re

    found = set()
    pattern = re.compile(r"(jobs|workers|batches|threads|processes|job_ids)$", re.IGNORECASE)
    for base in ("services", "routers"):
        for path in sorted((ROOT / "app" / base).rglob("*.py")):
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.Assign):
                    names, value = [t.id for t in node.targets if isinstance(t, ast.Name)], node.value
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                    names, value = [node.target.id], node.value
                else:
                    continue
                empty_table = isinstance(value, (ast.Dict, ast.Set, ast.List)) or (
                    isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in {"dict", "set", "list"}
                )
                if empty_table:
                    found.update((path.relative_to(ROOT / "app").as_posix(), name) for name in names if pattern.search(name))
    return found


def test_every_module_level_job_table_is_covered_by_a_busy_probe_or_listed_with_a_reason():
    kinds = FULL_BUSY_KINDS | CORE_BUSY_KINDS | ROUTER_BUSY_KINDS
    found = _module_level_job_tables()

    assert found - set(JOB_REGISTRIES) == set(), (
        "A new table of live jobs: give its family a workspace_busy probe (routers/workspace_busy_probes.py) "
        "or list it in JOB_REGISTRIES with the reason it needs none."
    )
    assert set(JOB_REGISTRIES) - found == set(), "Listed but gone: remove it from JOB_REGISTRIES."
    for entry, covered_by in JOB_REGISTRIES.items():
        assert covered_by in kinds or covered_by.startswith(("exempt: ", NOT_YET_PROBED)), (entry, covered_by)


def test_the_core_root_passes_the_core_busy_profile_to_the_workspace_router():
    # The full server's side of this is checked after a real boot, in tests/characterization/test_workspaces.py.
    assert 'busy_profile="core"' in (ROOT / "app" / "core_runtime.py").read_text(encoding="utf-8")


def test_a_story_plan_checkpoint_a_crash_left_as_running_does_not_block_even_after_a_poll(tmp_path):
    """A status poll after a restart caches the persisted checkpoint (status ``running``) in memory.
    Only the claim set proves a worker, so that record must not keep the workspace undeletable."""
    import json

    from services import story_lab_jobs

    client = _workspace_client(tmp_path, profile="full")
    checkpoints = tmp_path / "film" / ".story-plan-jobs"
    checkpoints.mkdir()
    job_id = "story-plan-bbbbbbbbbbbb"
    (checkpoints / f"{job_id}.json").write_text(
        json.dumps({"jobId": job_id, "workspace": "film", "status": "running"}), encoding="utf-8",
    )
    saved = (story_lab_jobs._workspace_dir, story_lab_jobs._list_workspaces)
    story_lab_jobs._workspace_dir = lambda workspace=None: str(tmp_path / (workspace or "film"))
    story_lab_jobs._list_workspaces = lambda: [{"name": "film"}]
    try:
        polled = story_lab_jobs._load_story_plan_job(job_id)
        deleted = client.delete("/api/v1/workspaces/film")
    finally:
        story_lab_jobs._workspace_dir, story_lab_jobs._list_workspaces = saved
        with story_lab_jobs._story_plan_jobs_lock:
            story_lab_jobs._story_plan_jobs.pop(job_id, None)
    assert polled["status"] == "running"
    assert deleted.status_code == 200, deleted.text


def test_a_comic_plan_without_a_claim_does_not_block(tmp_path):
    from services import director_comic_jobs as comic

    client = _workspace_client(tmp_path, profile="full")
    with comic._comic_plan_jobs_lock:
        comic._comic_plan_jobs["comic-plan-job-cccccccccccc"] = {"workspace": "film", "status": "planning"}
    try:
        deleted = client.delete("/api/v1/workspaces/film")
    finally:
        with comic._comic_plan_jobs_lock:
            comic._comic_plan_jobs.clear()
    assert deleted.status_code == 200, deleted.text


def test_a_director_plan_blocks_only_the_workspace_that_holds_its_checkpoint(tmp_path):
    client = _workspace_client(tmp_path, profile="full")
    release = _director_plan_claims(folder=tmp_path / "other")  # the claim set holds ids only
    try:
        film = client.delete("/api/v1/workspaces/film")
        other = client.delete("/api/v1/workspaces/other")
    finally:
        release()
    assert film.status_code == 200, film.text
    assert other.status_code == 409, other.text
    assert other.json()["blocking"][0] == {
        "kind": "director-plan", "jobId": other.json()["blocking"][0]["jobId"], "status": "running", "workspace": "other",
    }


def test_a_director_plan_checkpoint_without_a_claim_does_not_block(tmp_path):
    client = _workspace_client(tmp_path, profile="full")
    release = _director_plan_claims(folder=tmp_path / "film", claim=False)
    try:
        deleted = client.delete("/api/v1/workspaces/film")
    finally:
        release()
    assert deleted.status_code == 200, deleted.text


def test_a_game_produce_checkpoint_a_restart_left_as_running_does_not_block(tmp_path):
    """The record says running, no worker thread exists in this process: the restart cut it."""
    client = _workspace_client(tmp_path, profile="full")
    _game_produce_service(tmp_path)
    _save_game_job(tmp_path, status="running")

    deleted = client.delete("/api/v1/workspaces/film")

    assert deleted.status_code == 200, deleted.text


def test_game_produce_checkpoints_stay_untouched_when_the_busy_probe_reads_them(tmp_path):
    from services.game_jobs import GameJobStore

    service = _game_produce_service(tmp_path)
    _save_game_job(tmp_path, status="running")

    assert service.live_jobs(str(tmp_path / "film")) == []

    assert GameJobStore(str(tmp_path / "film")).load("game-produce-aaaaaaaa")["status"] == "running"
    assert service.jobs("film")[0]["status"] == "interrupted", "jobs() still reconciles, as before"


@pytest.mark.parametrize("store_kind", ["produce", "native", "voice"])
def test_a_series_checkpoint_without_a_live_worker_does_not_block(tmp_path, store_kind):
    """After a crash the record still says running; no thread of the service owns it."""
    client = _workspace_client(tmp_path, profile="full")
    _series_services(tmp_path)
    _save_series_checkpoint(tmp_path, store_kind, status="running")

    deleted = client.delete("/api/v1/workspaces/film")

    assert deleted.status_code == 200, deleted.text


@pytest.mark.parametrize("module_name", ["series_plan_jobs", "series_render_jobs"])
def test_a_series_plan_or_render_record_without_a_claim_does_not_block(tmp_path, module_name):
    import importlib

    module = importlib.import_module(f"services.{module_name}")
    jobs, lock = getattr(module, f"_{module_name[:-5]}_jobs"), getattr(module, f"_{module_name[:-5]}_jobs_lock")
    client = _workspace_client(tmp_path, profile="full")
    with lock:
        jobs["stale-1"] = {"jobId": "stale-1", "workspace": "film", "status": "running"}
    try:
        deleted = client.delete("/api/v1/workspaces/film")
    finally:
        with lock:
            jobs.clear()
    assert deleted.status_code == 200, deleted.text


def test_series_voice_recordings_block_a_workspace_delete_though_series_delete_ignores_them(tmp_path):
    """Owner decision (default): the ``voice`` kind counts, because its worker writes the recorded line into the folder."""
    import threading

    client = _workspace_client(tmp_path, profile="full")
    services = _series_services(tmp_path)
    job_id = _save_series_checkpoint(tmp_path, "voice")
    stop = threading.Event()
    worker = threading.Thread(target=stop.wait, daemon=True)
    worker.start()
    services["voice"]._threads[job_id] = worker
    try:
        refused = client.delete("/api/v1/workspaces/film")
    finally:
        stop.set()
        worker.join(2)
    assert refused.status_code == 409
    assert [item["kind"] for item in refused.json()["blocking"]] == ["series-voice"]


def test_a_music_production_shot_edit_blocks_and_a_finished_run_does_not(tmp_path):
    """A shot/song edit holds the production slot from a request thread; a run whose thread ended is history."""
    import threading

    from services import music_production

    client = _workspace_client(tmp_path, profile="full")
    finished = threading.Thread(target=lambda: None)
    finished.start()
    finished.join()
    edit, stop = _live_thread()
    with music_production._lock:
        music_production._threads["film/prod-done"] = finished
        music_production._edits["film/prod-edit"] = edit
    try:
        refused = client.delete("/api/v1/workspaces/film")
        with music_production._lock:
            music_production._edits.pop("film/prod-edit", None)
        allowed = client.delete("/api/v1/workspaces/film")
    finally:
        stop()
        with music_production._lock:
            music_production._threads.pop("film/prod-done", None)
            music_production._edits.pop("film/prod-edit", None)
    assert refused.status_code == 409, refused.text
    assert refused.json()["blocking"] == [
        {"kind": "music-production", "jobId": "prod-edit", "status": "running", "workspace": "film"},
    ]
    assert allowed.status_code == 200, allowed.text


def test_the_music_production_probe_does_not_load_the_production_runner(monkeypatch):
    """Core loads ``services.music_production`` (numpy and the whole production stack) only when a production runs.
    Until then no slot can be held, so the probe answers without importing it."""
    import sys

    from services import production_commands

    monkeypatch.delitem(sys.modules, "services.music_production", raising=False)

    assert production_commands.busy_jobs("film", "/x/film") == []
    assert "services.music_production" not in sys.modules
