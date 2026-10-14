import copy
import threading

import pytest
from fastapi import HTTPException

from services.series_jobs import SeriesJobStore
from services.series_lifecycle import (
    ACTIVE_SERIES_JOB_STATUSES,
    ActiveSeriesJobsError,
    list_active_series_jobs,
    list_active_workspace_series_jobs,
    require_no_active_series_jobs,
    require_no_active_workspace_series_jobs,
)


def _save_job(tmp_path, kind: str, status: str, *, job_id: str | None = None, episode_id: str = "episode-1"):
    identifier = job_id or f"{kind}-{status}"
    SeriesJobStore(str(tmp_path), kind).save({
        "jobId": identifier,
        "kind": kind,
        "workspace": "default",
        "seriesId": "series-1",
        "episodeId": episode_id,
        "status": status,
        "stage": status,
        "message": f"{kind} is {status}",
        "createdAt": 1,
        "updatedAt": 1,
        "request": {"secret": "must not be exposed"},
    })
    return identifier


@pytest.mark.parametrize("kind", ["planning", "render", "assembly"])
@pytest.mark.parametrize("status", sorted(ACTIVE_SERIES_JOB_STATUSES))
def test_every_active_job_kind_blocks_episode_deletion(tmp_path, kind, status):
    job_id = _save_job(tmp_path, kind, status)

    with pytest.raises(ActiveSeriesJobsError) as captured:
        require_no_active_series_jobs(
            str(tmp_path), "default", "series-1", episode_id="episode-1",
        )

    detail = captured.value.detail()
    assert detail["code"] == "series_jobs_active"
    assert detail["activeJobs"] == [{
        "jobId": job_id,
        "kind": kind,
        "status": status,
        "stage": status,
        "seriesId": "series-1",
        "episodeId": "episode-1",
        "message": f"{kind} is {status}",
    }]
    assert "secret" not in str(detail)


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "interrupted"])
def test_terminal_jobs_allow_deletion_and_leave_outputs_untouched(tmp_path, status):
    _save_job(tmp_path, "assembly", status)
    output = tmp_path / "approved.mp4"
    output.write_bytes(b"approved")

    require_no_active_series_jobs(
        str(tmp_path), "default", "series-1", episode_id="episode-1",
    )

    assert output.read_bytes() == b"approved"
    assert SeriesJobStore(str(tmp_path), "assembly").list()[0]["status"] == status


def test_series_scope_includes_canon_and_all_episodes_while_episode_scope_is_exact(tmp_path):
    _save_job(tmp_path, "planning", "running", job_id="canon", episode_id="")
    _save_job(tmp_path, "render", "queued", job_id="episode-2", episode_id="episode-2")
    _save_job(tmp_path, "assembly", "running", job_id="other-series", episode_id="episode-1")
    assembly = SeriesJobStore(str(tmp_path), "assembly").load("other-series")
    assembly["seriesId"] = "series-2"
    SeriesJobStore(str(tmp_path), "assembly").save(assembly)

    assert [job["jobId"] for job in list_active_series_jobs(
        str(tmp_path), "default", "series-1",
    )] == ["canon", "episode-2"]
    assert list_active_series_jobs(
        str(tmp_path), "default", "series-1", episode_id="episode-1",
    ) == []
    assert [job["jobId"] for job in list_active_series_jobs(
        str(tmp_path), "default", "series-1", episode_id="episode-2",
    )] == ["episode-2"]


def test_series_delete_checks_central_lifecycle_before_mutating_library(monkeypatch):
    import routers.series_library as series_library

    library = {"seriesById": {"series-1": {"id": "series-1"}}, "seriesOrder": ["series-1"]}
    writes = []
    checked = []
    monkeypatch.setattr(series_library, "_series_library_workspace", lambda value: value or "default")
    monkeypatch.setattr(series_library, "_series_library_lock", threading.RLock())
    monkeypatch.setattr(series_library, "_read_series_workspace", lambda _workspace: copy.deepcopy(library))
    monkeypatch.setattr(series_library, "_series_project_or_404", lambda current, series_id: current["seriesById"][series_id])
    monkeypatch.setattr(
        series_library, "_require_series_deletion_ready",
        lambda workspace, series_id: checked.append((workspace, series_id)),
    )
    monkeypatch.setattr(series_library, "_write_series_workspace", lambda _workspace, value: writes.append(copy.deepcopy(value)))

    result = series_library.delete_series_project_endpoint("series-1", "default")

    assert checked == [("default", "series-1")]
    assert writes[0]["seriesById"] == {}
    assert result["outputsPreserved"] is True


def test_episode_delete_propagates_structured_active_job_conflict_without_writing(monkeypatch):
    import routers.series_library as series_library

    library = {
        "seriesById": {"series-1": {
            "id": "series-1",
            "revision": 1,
            "episodesById": {"episode-1": {"id": "episode-1"}},
            "seasons": [{"episodeOrder": ["episode-1"]}],
        }},
    }
    writes = []

    def blocked(_workspace, _series_id, _episode_id):
        raise HTTPException(status_code=409, detail={
            "code": "series_jobs_active",
            "activeJobs": [{"jobId": "assembly-1", "kind": "assembly"}],
        })

    monkeypatch.setattr(series_library, "_series_library_workspace", lambda value: value or "default")
    monkeypatch.setattr(series_library, "_series_library_lock", threading.RLock())
    monkeypatch.setattr(series_library, "_read_series_workspace", lambda _workspace: copy.deepcopy(library))
    monkeypatch.setattr(series_library, "_series_project_or_404", lambda current, series_id: current["seriesById"][series_id])
    monkeypatch.setattr(series_library, "_require_series_deletion_ready", blocked)
    monkeypatch.setattr(series_library, "_write_series_workspace", lambda _workspace, value: writes.append(value))
    monkeypatch.setattr(series_library, "_series_iso_now", lambda: "2026-08-16T00:00:00Z")

    with pytest.raises(HTTPException) as captured:
        series_library.delete_series_episode_endpoint("series-1", "episode-1", "default")

    assert captured.value.status_code == 409
    assert captured.value.detail["activeJobs"][0]["jobId"] == "assembly-1"
    assert writes == []


def test_workspace_scan_includes_every_series_and_kind(tmp_path):
    _save_job(tmp_path, "planning", "running", job_id="canon", episode_id="")
    _save_job(tmp_path, "produce", "queued", job_id="produce-1", episode_id="episode-1")
    _save_job(tmp_path, "voice", "cancelling", job_id="voice-1", episode_id="episode-1")
    other = SeriesJobStore(str(tmp_path), "assembly").save({
        "jobId": "other-series",
        "workspace": "default",
        "seriesId": "series-2",
        "episodeId": "episode-9",
        "status": "running",
    })

    found = [job["jobId"] for job in list_active_workspace_series_jobs(str(tmp_path))]

    assert found == ["other-series", "canon", "produce-1", "voice-1"]
    assert other["seriesId"] == "series-2"


def test_workspace_delete_refuses_an_active_series_job_and_keeps_the_folder(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.workspace_outputs import create_workspace_router

    show = tmp_path / "show"
    show.mkdir()
    (show / "library.json").write_text("keep", encoding="utf-8")
    _save_job(show, "planning", "running", job_id="plan-show")

    app = FastAPI()
    app.include_router(create_workspace_router(
        list_workspaces=lambda: ["show"],
        get_active_workspace=lambda: "default",
        persist_active=lambda name, apply_save_paths=True: str(tmp_path / name),
        workspace_dir=lambda name: str(tmp_path / name),
        generation_idle=lambda: True,
        jobs=lambda: [],
        safe_join=lambda _base, name: str((tmp_path / name).resolve()) if name == "show" else None,
        save_path=lambda: str(tmp_path),
    ))
    deleted = TestClient(app).delete("/api/v1/workspaces/show")

    assert deleted.status_code == 409, deleted.text
    assert deleted.json()["detail"]["code"] == "series_jobs_active"
    assert deleted.json()["detail"]["activeJobs"][0]["jobId"] == "plan-show"
    assert (show / "library.json").read_text(encoding="utf-8") == "keep"


def test_workspace_delete_proceeds_when_series_jobs_are_terminal(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.workspace_outputs import create_workspace_router

    show = tmp_path / "show"
    show.mkdir()
    (show / "library.json").write_text("gone", encoding="utf-8")
    _save_job(show, "planning", "completed", job_id="plan-done")
    require_no_active_workspace_series_jobs(str(show))

    app = FastAPI()
    app.include_router(create_workspace_router(
        list_workspaces=lambda: ["show"],
        get_active_workspace=lambda: "default",
        persist_active=lambda name, apply_save_paths=True: str(tmp_path / name),
        workspace_dir=lambda name: str(tmp_path / name),
        generation_idle=lambda: True,
        jobs=lambda: [],
        safe_join=lambda _base, name: str((tmp_path / name).resolve()) if name == "show" else None,
        save_path=lambda: str(tmp_path),
    ))
    deleted = TestClient(app).delete("/api/v1/workspaces/show")

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["dir_removed"] is True
    assert not show.exists()
