import copy
import json
import os
import shutil
import threading
import time

import pytest
from fastapi import HTTPException

from routers.series_assembly import (
    SeriesAssemblyStartRequest,
    _write_assembly_sidecar,
    create_series_assembly_router,
)
from services.asset_manifest import SCHEMA_NAME, read_asset_manifest
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
    # The stand-in clips are not media: finishing explains itself and never fails the join.
    assert asset["metadata"]["loudness"]["applied"] is False and asset["metadata"]["loudness"]["reason"]
    assert asset["metadata"]["subtitles"]["written"] is False and asset["metadata"]["subtitles"]["reason"]
    assert "Loudness unchanged" in status["message"] and "No subtitles" in status["message"]
    assets = library["seriesById"]["series-1"]["assets"].values()
    assert "thumbnailAssetId" not in episode and not [item for item in assets if item.get("isDerivedThumbnail")], "no frame, no thumbnail asset"
    joined = tmp_path / status["filename"]
    sidecar = json.loads(joined.with_suffix(".meta.json").read_text(encoding="utf-8"))
    loaded = read_asset_manifest(joined, workspace_id="default")
    assert sidecar["schema"] == SCHEMA_NAME
    assert sidecar["params"]["seriesId"] == "series-1"
    assert loaded["origin"]["tool"] == "series-assembly"
    assert loaded["origin"]["actor"] == "unknown"


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


def test_write_assembly_sidecar_publishes_canonical_manifest_without_invented_actor(tmp_path):
    output = tmp_path / "episode_series_assembly.mp4"
    output.write_bytes(b"joined")
    _write_assembly_sidecar(str(output), {
        "jobId": "series-assembly-abc",
        "workspace": "night-shift",
        "seriesId": "series-1",
        "episodeId": "episode-1",
    })
    raw = json.loads(output.with_suffix(".meta.json").read_text(encoding="utf-8"))
    loaded = read_asset_manifest(output, workspace_id="night-shift")
    assert raw["schema"] == SCHEMA_NAME
    assert raw["params"]["seriesId"] == "series-1"
    assert raw["params"]["episodeId"] == "episode-1"
    assert raw["params"]["assemblyJobId"] == "series-assembly-abc"
    assert loaded is not None
    assert loaded["origin"]["tool"] == "series-assembly"
    assert loaded["origin"]["actor"] == "unknown"
    assert loaded["origin"]["workspace_id"] == "night-shift"


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


def test_a_language_version_assembles_its_own_takes_into_its_own_cut(tmp_path):
    observed = []

    def concatenate(paths, output_path):
        observed.extend(os.path.basename(path) for path in paths)
        shutil.copyfile(paths[0], output_path)
        return True

    endpoints, library = _client(tmp_path, concatenate)
    series = library["seriesById"]["series-1"]
    episode = series["episodesById"]["episode-1"]
    for shot in episode["shots"]:
        shot["attempts"].append({"id": f"{shot['id']}-es", "status": "completed", "outputAssetIds": ["asset-2"]})
    episode["languageVersions"] = {"spanish": {"dialogue": {}, "cards": {},
                                               "approvedAttemptIds": {"shot-1": "shot-1-es", "shot-2": "shot-2-es"}}}
    start = endpoints["/api/v1/series/{series_id}/episodes/{episode_id}/assembly/start"]
    get_status = endpoints["/api/v1/series/assembly/jobs/{job_id}"]
    status = _wait_for_terminal(get_status, start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default", language="spanish"))["jobId"])
    assert status["status"] == "completed"
    assert observed == ["two.mp4", "two.mp4"], "the version's approved takes, in shot order"
    episode = library["seriesById"]["series-1"]["episodesById"]["episode-1"]
    assert episode["languageVersions"]["spanish"]["latestAssemblyAssetId"] == status["assetId"]
    assert "latestAssemblyAssetId" not in episode, "the original's cut is untouched"
    asset = library["seriesById"]["series-1"]["assets"][status["assetId"]]
    assert asset["metadata"]["language"] == "spanish"
    with pytest.raises(HTTPException) as missing:
        start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default", language="french"))
    assert missing.value.status_code == 400


def test_a_finished_cut_keeps_its_thumbnail_on_its_holder(tmp_path, monkeypatch):
    import routers.series_assembly as assembly

    def finished(output_path, *_args, **_kwargs):
        name = os.path.splitext(os.path.basename(output_path))[0] + ".thumb.jpg"
        (tmp_path / name).write_bytes(b"jpg")
        return {"subtitles": {"written": False, "reason": "stub"}, "loudness": {"applied": False, "reason": "stub"},
                "thumbnail": {"written": True, "file": name, "time": 4.2}}
    monkeypatch.setattr(assembly, "finish_episode", finished)

    def concatenate(paths, output_path):
        shutil.copyfile(paths[0], output_path)
        return True

    endpoints, library = _client(tmp_path, concatenate)
    start = endpoints["/api/v1/series/{series_id}/episodes/{episode_id}/assembly/start"]
    status = _wait_for_terminal(endpoints["/api/v1/series/assembly/jobs/{job_id}"],
                                start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))["jobId"])
    assert status["status"] == "completed", status
    series = library["seriesById"]["series-1"]
    thumbnail = series["assets"][series["episodesById"]["episode-1"]["thumbnailAssetId"]]
    assert thumbnail["kind"] == "image" and thumbnail["isDerivedThumbnail"] is True and thumbnail["uri"].endswith(".thumb.jpg")
    assert thumbnail["metadata"]["assemblyAssetId"] == status["assetId"] and thumbnail["metadata"]["time"] == 4.2


def test_an_episode_mode_assembly_keeps_each_clips_bed_and_lays_it_while_finishing(tmp_path, monkeypatch):
    import routers.series_assembly as assembly

    seen = []

    def finished(output_path, *_args, ambience=None, **_kwargs):
        seen.append(ambience)
        beds = {"applied": True, "beds": [{"file": "sfx-street.wav"}]} if ambience else None
        return {"subtitles": {"written": False, "reason": "stub"}, "loudness": {"applied": False, "reason": "stub"},
                **({"ambience": beds} if beds else {})}
    monkeypatch.setattr(assembly, "finish_episode", finished)

    def concatenate(paths, output_path):
        shutil.copyfile(paths[0], output_path)
        return True

    endpoints, library = _client(tmp_path, concatenate)
    series = library["seriesById"]["series-1"]
    shots = {shot["id"]: shot for shot in series["episodesById"]["episode-1"]["shots"]}
    shots["shot-1"]["locationId"], shots["shot-2"]["locationId"] = "street", "void"
    start = endpoints["/api/v1/series/{series_id}/episodes/{episode_id}/assembly/start"]
    get_status = endpoints["/api/v1/series/assembly/jobs/{job_id}"]
    status = _wait_for_terminal(get_status, start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))["jobId"])
    assert status["status"] == "completed" and seen == [None], "shot mode: the shots carry their ambience"

    series = library["seriesById"]["series-1"]
    series["soundDesign"] = {"ambienceMode": "episode", "ambienceByLocation": {"street": {"file": "sfx-street.wav"}}}
    status = _wait_for_terminal(get_status, start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))["jobId"])
    assert status["status"] == "completed", status
    assert seen[-1] == [{"locationId": "street", "file": "sfx-street.wav", "volume": 0.22}, {"locationId": "void"}], "in episode order"
    assert SeriesJobStore(str(tmp_path), "assembly").load(status["jobId"])["ambience"] == seen[-1], "a resume lays the same beds"
    asset = library["seriesById"]["series-1"]["assets"][status["assetId"]]
    assert asset["metadata"]["ambience"]["applied"] is True

    episode = library["seriesById"]["series-1"]["episodesById"]["episode-1"]
    for shot in episode["shots"]:
        shot["attempts"].append({"id": f"{shot['id']}-es", "status": "completed", "outputAssetIds": ["asset-2"]})
    episode["languageVersions"] = {"spanish": {"dialogue": {}, "cards": {},
                                               "approvedAttemptIds": {"shot-1": "shot-1-es", "shot-2": "shot-2-es"}}}
    request = SeriesAssemblyStartRequest(workspace="default", language="spanish")
    status = _wait_for_terminal(get_status, start("series-1", "episode-1", request)["jobId"])
    assert status["status"] == "completed" and seen[-1] == seen[-2], "a language version lies on the same beds"


def test_the_episode_score_is_kept_on_the_job_and_laid_while_finishing(tmp_path, monkeypatch):
    import routers.series_assembly as assembly

    seen = []

    def finished(output_path, *_args, score=None, **_kwargs):
        seen.append(score)
        return {"subtitles": {"written": False, "reason": "stub"}, "loudness": {"applied": False, "reason": "stub"},
                **({"score": {"applied": True, "cues": [{"file": "mus-theme.wav"}]}} if score else {})}
    monkeypatch.setattr(assembly, "finish_episode", finished)

    def concatenate(paths, output_path):
        shutil.copyfile(paths[0], output_path)
        return True

    endpoints, library = _client(tmp_path, concatenate)
    start = endpoints["/api/v1/series/{series_id}/episodes/{episode_id}/assembly/start"]
    get_status = endpoints["/api/v1/series/assembly/jobs/{job_id}"]
    status = _wait_for_terminal(get_status, start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))["jobId"])
    assert status["status"] == "completed" and seen == [None], "no score, no score step"

    episode = library["seriesById"]["series-1"]["episodesById"]["episode-1"]
    shots = {shot["id"]: shot for shot in episode["shots"]}
    shots["shot-2"]["layout2d"] = {"music": {"file": "mus-song.wav", "volume": 0.5}}
    episode["score"] = [{"fromShotId": "shot-1", "toShotId": "shot-2", "file": "mus-theme.wav", "volume": 0.2,
                         "fadeIn": 1.0, "fadeOut": 2.0, "duck": True}, {"fromShotId": "shot-9", "file": "mus-x.wav"}]
    status = _wait_for_terminal(get_status, start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))["jobId"])
    assert status["status"] == "completed", status
    assert seen[-1] == {"cues": [{"file": "mus-theme.wav", "volume": 0.2, "fadeIn": 1.0, "fadeOut": 2.0, "duck": True,
                                  "firstClip": 0, "lastClip": 1}],
                        "music": [False, True], "skipped": ["Score cue 2: the episode has no shot shot-9"]}, "in episode order"
    assert SeriesJobStore(str(tmp_path), "assembly").load(status["jobId"])["score"] == seen[-1], "a resume lays the same score"
    assert library["seriesById"]["series-1"]["assets"][status["assetId"]]["metadata"]["score"]["applied"] is True
    assert status["message"].endswith("1 score cue.")

    episode = library["seriesById"]["series-1"]["episodesById"]["episode-1"]
    for shot in episode["shots"]:
        shot["attempts"].append({"id": f"{shot['id']}-es", "status": "completed", "outputAssetIds": ["asset-2"]})
    episode["languageVersions"] = {"spanish": {"dialogue": {}, "cards": {},
                                               "approvedAttemptIds": {"shot-1": "shot-1-es", "shot-2": "shot-2-es"}}}
    request = SeriesAssemblyStartRequest(workspace="default", language="spanish")
    status = _wait_for_terminal(get_status, start("series-1", "episode-1", request)["jobId"])
    assert status["status"] == "completed" and seen[-1] == seen[-2], "a language version lies on the same score"
