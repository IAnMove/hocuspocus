import copy
import os
import shutil
import threading
import time

import pytest
from fastapi import HTTPException

from routers.series_assembly import SeriesAssemblyStartRequest, create_series_assembly_router
from services.series_jobs import SeriesJobStore
from services.task_manager import forget_task_registry, get_task_registry


def _episode_library():
    return {
        "seriesById": {
            "series-1": {
                "id": "series-1",
                "revision": 1,
                "assets": {
                    "asset-1": {"id": "asset-1", "kind": "video", "uri": "outputs/one.mp4"},
                    "asset-2": {"id": "asset-2", "kind": "video", "uri": "outputs/two.mp4"},
                },
                "episodesById": {
                    "episode-1": {
                        "id": "episode-1",
                        "shots": [{
                            "id": "shot-2", "order": 2, "approvedAttemptId": "attempt-2",
                            "attempts": [{
                                "id": "attempt-2", "status": "completed",
                                "outputAssetIds": ["asset-2"],
                            }],
                        }, {
                            "id": "shot-1", "order": 1, "approvedAttemptId": "attempt-1",
                            "attempts": [{
                                "id": "attempt-1", "status": "completed",
                                "outputAssetIds": ["asset-1"],
                            }],
                        }],
                    },
                },
            },
        },
    }


def _client(tmp_path, concatenate, workspace_path=None):
    library = _episode_library()
    for filename in ("one.mp4", "two.mp4"):
        (tmp_path / filename).write_bytes(filename.encode())

    def read_library(_workspace):
        return copy.deepcopy(library)

    def write_library(_workspace, value):
        library.clear()
        library.update(copy.deepcopy(value))
        return copy.deepcopy(library)

    def find_series(value, series_id):
        try:
            return value["seriesById"][series_id]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Series not found") from exc

    router = create_series_assembly_router(
        resolve_workspace=lambda value: str(value or "default"),
        workspace_dir=workspace_path or (lambda _workspace: str(tmp_path)),
        list_workspaces=lambda: [{"name": "default"}],
        library_lock=threading.RLock(),
        read_library=read_library,
        write_library=write_library,
        find_series=find_series,
        asset_local_path=lambda _workspace, asset: str(
            tmp_path / os.path.basename(str(asset["uri"]))
        ),
        available_filename=lambda directory, name: os.path.join(directory, name),
        concatenate_clips=concatenate,
        iso_now=lambda: "2026-08-12T00:00:00Z",
    )
    endpoints = {route.path: route.endpoint for route in router.routes}
    return endpoints, library


def _wait_for_terminal(status_endpoint, job_id):
    for _ in range(100):
        status = status_endpoint(job_id)
        if status["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            return status
        time.sleep(0.01)
    raise AssertionError("assembly did not finish")


def test_router_joins_in_episode_order_and_persists_episode_asset(tmp_path):
    observed = []

    def concatenate(paths, output_path):
        observed.extend(os.path.basename(path) for path in paths)
        shutil.copyfile(paths[0], output_path)
        return True

    endpoints, library = _client(tmp_path, concatenate)
    start = endpoints["/api/v1/series/{series_id}/episodes/{episode_id}/assembly/start"]
    get_status = endpoints["/api/v1/series/assembly/jobs/{job_id}"]
    response = start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))
    status = _wait_for_terminal(get_status, response["jobId"])

    assert status["status"] == "completed"
    assert observed == ["one.mp4", "two.mp4"]
    episode = library["seriesById"]["series-1"]["episodesById"]["episode-1"]
    assert episode["latestAssemblyAssetId"] == status["assetId"]
    asset = library["seriesById"]["series-1"]["assets"][status["assetId"]]
    assert asset["metadata"]["orderedClipAssetIds"] == ["asset-1", "asset-2"]


def test_router_rejects_a_second_live_assembly_for_the_episode(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def concatenate(paths, output_path):
        entered.set()
        assert release.wait(timeout=2)
        shutil.copyfile(paths[0], output_path)
        return True

    endpoints, _library = _client(tmp_path, concatenate)
    start = endpoints["/api/v1/series/{series_id}/episodes/{episode_id}/assembly/start"]
    get_status = endpoints["/api/v1/series/assembly/jobs/{job_id}"]
    first = start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))
    assert entered.wait(timeout=1)
    with pytest.raises(HTTPException) as captured:
        start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))
    assert captured.value.status_code == 409
    release.set()
    assert _wait_for_terminal(get_status, first["jobId"])["status"] == "completed"


def test_assembly_publishes_canonical_activity_and_cancels_ffmpeg(tmp_path):
    entered = threading.Event()
    cancelled = threading.Event()

    def concatenate(paths, output_path, *, abort_callback):
        entered.set()
        while not abort_callback():
            time.sleep(0.005)
        cancelled.set()
        return False

    endpoints, _library = _client(tmp_path, concatenate)
    start = endpoints["/api/v1/series/{series_id}/episodes/{episode_id}/assembly/start"]
    status = endpoints["/api/v1/series/assembly/jobs/{job_id}"]
    cancel = endpoints["/api/v1/series/assembly/jobs/{job_id}/cancel"]
    response = start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))
    assert entered.wait(timeout=1)
    task = get_task_registry(str(tmp_path)).get(f"task-series-assembly-{response['jobId']}")
    assert task and task["kind"] == "assembly" and task["status"] == "running"
    cancelled_response = cancel(response["jobId"], type("Payload", (), {"workspace": "default"})())
    assert cancelled_response["status"] == "cancelling"
    assert cancelled.wait(timeout=1)
    assert _wait_for_terminal(status, response["jobId"])["status"] == "cancelled"


def test_cancelled_assembly_removes_output_created_during_cancellation(tmp_path):
    output_created = threading.Event()
    release = threading.Event()

    def concatenate(paths, output_path, *, abort_callback):
        shutil.copyfile(paths[0], output_path)
        output_created.set()
        assert release.wait(timeout=2)
        return True

    endpoints, library = _client(tmp_path, concatenate)
    start = endpoints["/api/v1/series/{series_id}/episodes/{episode_id}/assembly/start"]
    status = endpoints["/api/v1/series/assembly/jobs/{job_id}"]
    cancel = endpoints["/api/v1/series/assembly/jobs/{job_id}/cancel"]
    response = start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))

    assert output_created.wait(timeout=1)
    cancel(response["jobId"], type("Payload", (), {"workspace": "default"})())
    release.set()

    assert _wait_for_terminal(status, response["jobId"])["status"] == "cancelled"
    assert not list(tmp_path.glob("*_series_assembly.mp4"))
    assert not list(tmp_path.glob("*_series_assembly.meta.json"))
    episode = library["seriesById"]["series-1"]["episodesById"]["episode-1"]
    assert not episode.get("assemblyAssetIds")


def test_cancelled_assembly_after_meta_removes_sidecar(tmp_path):
    output_created = threading.Event()
    release = threading.Event()

    def concatenate(paths, output_path, *, abort_callback):
        shutil.copyfile(paths[0], output_path)
        output_created.set()
        assert release.wait(timeout=2)
        return True

    endpoints, library = _client(tmp_path, concatenate)
    start = endpoints["/api/v1/series/{series_id}/episodes/{episode_id}/assembly/start"]
    status = endpoints["/api/v1/series/assembly/jobs/{job_id}"]
    cancel = endpoints["/api/v1/series/assembly/jobs/{job_id}/cancel"]
    response = start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))

    assert output_created.wait(timeout=1)
    cancel(response["jobId"], type("Payload", (), {"workspace": "default"})())
    release.set()

    assert _wait_for_terminal(status, response["jobId"])["status"] == "cancelled"
    assert not list(tmp_path.glob("*.meta.json"))
    episode = library["seriesById"]["series-1"]["episodesById"]["episode-1"]
    assert not episode.get("assemblyAssetIds")


def test_assembly_status_is_confined_to_the_requested_workspace(tmp_path):
    endpoints, _library = _client(
        tmp_path, lambda _paths, _output: True,
        workspace_path=lambda workspace: str(tmp_path if workspace == "default" else tmp_path / workspace),
    )
    start = endpoints["/api/v1/series/{series_id}/episodes/{episode_id}/assembly/start"]
    status = endpoints["/api/v1/series/assembly/jobs/{job_id}"]
    response = start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))
    with pytest.raises(HTTPException) as captured:
        status(response["jobId"], "other-workspace")
    assert captured.value.status_code == 404


def test_stale_checkpoint_is_interrupted_on_router_load_and_recoverable(tmp_path):
    store = SeriesJobStore(str(tmp_path), "assembly")
    stale = {
        "jobId": "series-assembly-stale",
        "taskId": "task-series-assembly-series-assembly-stale",
        "kind": "assembly", "workspace": "default", "seriesId": "series-1",
        "episodeId": "episode-1", "status": "running", "stage": "joining",
        "current": 1, "total": 2, "clips": [], "message": "Joining", "error": None,
        "createdAt": time.time() - 10, "updatedAt": time.time() - 5,
    }
    store.save(stale)
    forget_task_registry(str(tmp_path))
    endpoints, _library = _client(tmp_path, lambda _paths, _output: True)
    status = endpoints["/api/v1/series/assembly/jobs/{job_id}"]
    recovery = endpoints["/api/v1/series/assembly/recovery"]
    restored = status(stale["jobId"])
    assert restored["status"] == "interrupted"
    assert any(item["jobId"] == stale["jobId"] and item["status"] == "interrupted" for item in recovery()["jobs"])
    assert get_task_registry(str(tmp_path)).get(stale["taskId"])["status"] == "interrupted"
