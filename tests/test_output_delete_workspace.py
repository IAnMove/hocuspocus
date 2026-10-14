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


def _seed_video_editor(_tmp_path):
    from routers.video_editor import _register_video_editor_job, reset_video_editor_jobs

    reset_video_editor_jobs()
    _register_video_editor_job({"job_id": "export-film", "workspace": "film", "status": "running"})
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


# (kind, profile, seeder). Each seeder fills the family's real registry for workspace "film"
# and returns the function that ends that job.
BUSY_FAMILIES = [
    pytest.param("video-editor", "full", _seed_video_editor, id="video-editor"),
    pytest.param("minimax-music", "full", _seed_minimax_music, id="minimax-music"),
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
    from routers.video_editor import _register_video_editor_job, reset_video_editor_jobs

    client = _workspace_client(tmp_path, profile="full")
    reset_video_editor_jobs()
    try:
        for index, status in enumerate(("completed", "failed", "cancelled")):
            _register_video_editor_job({"job_id": f"done-{index}", "workspace": "film", "status": status})
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
