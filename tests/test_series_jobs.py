from pathlib import Path

from services.series_jobs import SeriesJobStore


def test_render_queue_survives_store_recreation(tmp_path):
    first = SeriesJobStore(str(tmp_path), "render")
    first.save({
        "jobId": "series-render-1", "status": "running", "createdAt": 1,
        "updatedAt": 2, "outputAssetIds": [], "providerTaskId": "remote-1",
    })
    second = SeriesJobStore(str(tmp_path), "render")
    loaded = second.load("series-render-1")
    assert loaded["providerTaskId"] == "remote-1"
    assert second.recoverable()[0]["jobId"] == "series-render-1"


def test_discard_removes_checkpoint_not_output(tmp_path):
    output = Path(tmp_path) / "approved.mp4"
    output.write_bytes(b"approved")
    store = SeriesJobStore(str(tmp_path), "render")
    store.save({
        "jobId": "series-render-2", "status": "queued", "createdAt": 1,
        "updatedAt": 1, "outputAssetIds": ["approved.mp4"],
    })
    assert store.discard("series-render-2") is True
    assert store.load("series-render-2") is None
    assert output.read_bytes() == b"approved"


def test_planning_and_render_namespaces_are_isolated(tmp_path):
    planning = SeriesJobStore(str(tmp_path), "planning")
    render = SeriesJobStore(str(tmp_path), "render")
    planning.save({"jobId": "same", "status": "completed", "createdAt": 1, "updatedAt": 1})
    render.save({"jobId": "same", "status": "failed", "createdAt": 1, "updatedAt": 2})
    assert planning.load("same")["status"] == "completed"
    assert render.load("same")["status"] == "failed"
