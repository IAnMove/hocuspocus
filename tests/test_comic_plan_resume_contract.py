"""Model-free regressions for Comic planner restart/resume ownership."""

from __future__ import annotations

import threading


def test_stale_planning_checkpoint_resumes_when_no_worker_survived_restart():
    import routers.director_comic as routes

    job_id = "comic-plan-job-123456abcdef"
    job = {
        "jobId": job_id,
        "status": "planning",
        "message": "Planning before restart",
        "workspace": "default",
        "taskId": f"task-comic-plan-{job_id}",
        "request": {"premise": "A recovered story", "workspace": "default"},
    }
    active: set[str] = set()
    resets: list[tuple[str, str]] = []
    starts: list[tuple[str, dict, str]] = []

    def update(_job_id: str, **patch):
        assert _job_id == job_id
        job.update(patch)

    def start(_job_id: str, body: dict, *, thread_name: str) -> bool:
        starts.append((_job_id, dict(body), thread_name))
        active.add(_job_id)
        return True

    originals = {
        "_comic_plan_jobs_lock": routes._comic_plan_jobs_lock,
        "_comic_plan_active_jobs": routes._comic_plan_active_jobs,
        "get_director_comic_plan_status": routes.get_director_comic_plan_status,
        "_reset_canonical_task_for_resume": routes._reset_canonical_task_for_resume,
        "_comic_plan_job_update": routes._comic_plan_job_update,
        "_start_comic_plan_worker": routes._start_comic_plan_worker,
    }
    routes._comic_plan_jobs_lock = threading.Lock()
    routes._comic_plan_active_jobs = active
    routes.get_director_comic_plan_status = lambda _job_id: dict(job)
    routes._reset_canonical_task_for_resume = lambda workspace, task_id: resets.append(
        (workspace, task_id)
    )
    routes._comic_plan_job_update = update
    routes._start_comic_plan_worker = start
    try:
        response = routes.resume_director_comic_plan(job_id)
    finally:
        for name, value in originals.items():
            setattr(routes, name, value)

    assert response["status"] == "queued"
    assert job["status"] == "queued"
    assert job["finishedAt"] is None
    assert resets == [("default", f"task-comic-plan-{job_id}")]
    assert len(starts) == 1


def test_live_comic_worker_is_not_started_twice():
    import routers.director_comic as routes

    job_id = "comic-plan-job-fedcba654321"
    active = {job_id}
    starts: list[str] = []
    resets: list[str] = []
    job = {
        "jobId": job_id,
        "status": "planning",
        "message": "Still planning",
        "request": {"premise": "A live story"},
    }
    originals = {
        "_comic_plan_jobs_lock": routes._comic_plan_jobs_lock,
        "_comic_plan_active_jobs": routes._comic_plan_active_jobs,
        "get_director_comic_plan_status": routes.get_director_comic_plan_status,
        "_reset_canonical_task_for_resume": routes._reset_canonical_task_for_resume,
        "_comic_plan_job_update": routes._comic_plan_job_update,
        "_start_comic_plan_worker": routes._start_comic_plan_worker,
    }
    routes._comic_plan_jobs_lock = threading.Lock()
    routes._comic_plan_active_jobs = active
    routes.get_director_comic_plan_status = lambda _job_id: dict(job)
    routes._reset_canonical_task_for_resume = lambda *_args: resets.append("reset")
    routes._comic_plan_job_update = lambda *_args, **_kwargs: None
    routes._start_comic_plan_worker = lambda *_args, **_kwargs: starts.append("start")
    try:
        response = routes.resume_director_comic_plan(job_id)
    finally:
        for name, value in originals.items():
            setattr(routes, name, value)

    assert response["status"] == "planning"
    assert response["message"] == "Still planning"
    assert starts == []
    assert resets == []


def test_worker_claim_is_atomic_before_thread_start():
    import services.director_comic_jobs as jobs

    started: list[object] = []

    class DeferredThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            started.append(self)

    originals = {
        "threading": jobs.threading,
        "_comic_plan_jobs_lock": jobs._comic_plan_jobs_lock,
        "_comic_plan_active_jobs": jobs._comic_plan_active_jobs,
        "_run_comic_plan_job": jobs._run_comic_plan_job,
    }
    jobs.threading = type("Threading", (), {"Thread": DeferredThread})
    jobs._comic_plan_jobs_lock = threading.Lock()
    jobs._comic_plan_active_jobs = set()
    jobs._run_comic_plan_job = lambda *_args: None
    try:
        assert jobs._start_comic_plan_worker("comic-plan-job-111111111111", {}, thread_name="first") is True
        assert jobs._start_comic_plan_worker("comic-plan-job-111111111111", {}, thread_name="second") is False
        assert len(started) == 1
    finally:
        for name, value in originals.items():
            setattr(jobs, name, value)


# --- The writers do not invent a tone (glass wall 5) --------------------------------------------------
# An empty tone leaves the "Tone:" line out of the prompt. It used to default to "Cinematic".


class _PromptCaptured(RuntimeError):
    """Raised by the fake provider call once it has seen the prompt."""


def _story_writer_prompt(project: dict, body: dict | None = None) -> str:
    prompts: list[str] = []
    import services.story_lab_jobs as jobs

    def capture(*, prompt: str, **_kwargs):
        prompts.append(prompt)
        raise _PromptCaptured("prompt captured")

    originals = {
        "_comic_writing_llm": jobs._comic_writing_llm,
        "_ensure_llm_loaded": jobs._ensure_llm_loaded,
        "_generate_comic_director_json": jobs._generate_comic_director_json,
        "_story_project_prompt_context": jobs._story_project_prompt_context,
        "_story_lab_schema": jobs._story_lab_schema,
    }
    jobs._comic_writing_llm = lambda _body: {"provider": "stub"}
    jobs._ensure_llm_loaded = lambda: None
    jobs._generate_comic_director_json = capture
    jobs._story_project_prompt_context = lambda _project, _scope: ""
    jobs._story_lab_schema = lambda _scope, _project_type: {}
    try:
        try:
            jobs._generate_story_lab_stage(
                {"premise": "A lighthouse keeper hears the sea", "project": project, **(body or {})},
                "overview",
            )
        except Exception:
            pass  # the fake provider call ends the run; only the prompt matters
    finally:
        for name, value in originals.items():
            setattr(jobs, name, value)
    assert len(prompts) == 1
    return prompts[0]


def _comic_planner_prompt(body: dict) -> str:
    prompts: list[str] = []
    import routers.director_comic as routes

    def capture(*, prompt: str, **_kwargs):
        prompts.append(prompt)
        raise _PromptCaptured("prompt captured")

    originals = {
        "_comic_writing_llm": routes._comic_writing_llm,
        "_generate_comic_director_json": routes._generate_comic_director_json,
    }
    routes._comic_writing_llm = lambda _body: {"provider": "stub"}
    routes._generate_comic_director_json = capture
    try:
        try:
            routes.director_comic_plan({"premise": "A fox learns to whistle", "pageCount": 1, **body})
        except Exception:
            pass  # the fake provider call ends the run; only the prompt matters
    finally:
        for name, value in originals.items():
            setattr(routes, name, value)
    assert len(prompts) == 1
    return prompts[0]


def test_story_writer_prompt_has_no_tone_line_when_the_tone_is_empty():
    for project in ({}, {"tone": ""}, {"tone": "   "}):
        prompt = _story_writer_prompt(project)
        assert "Tone:" not in prompt, project
        assert "Cinematic" not in prompt, project
        # the neighbouring lines stay, one after the other, with no blank line between them
        assert "Genre: Adventure\nAudience: General\n" in prompt, project


def test_story_writer_prompt_keeps_the_tone_the_user_wrote():
    prompt = _story_writer_prompt({"tone": "Dry and observational"})
    assert "Genre: Adventure\nTone: Dry and observational\nAudience: General\n" in prompt
    # a tone sent in the request wins over the saved project
    prompt = _story_writer_prompt({"tone": "Dry"}, {"tone": "Tender"})
    assert "Tone: Tender\n" in prompt and "Tone: Dry" not in prompt


def test_comic_planner_prompt_has_no_tone_line_when_the_tone_is_empty():
    for body in ({}, {"tone": ""}, {"tone": None}):
        prompt = _comic_planner_prompt(body)
        assert "Tone:" not in prompt, body
        assert "Genre: Adventure\nAudience: General\n" in prompt, body
    prompt = _comic_planner_prompt({"tone": "Warm"})
    assert "Genre: Adventure\nTone: Warm\nAudience: General\n" in prompt


# --- The storyboard page check does not need the full server ------------------------------------------
# The Story Lab storyboard check calls the comic page check. It used to be a placeholder that the full
# server filled in at start-up, so the check failed with "'NoneType' object is not callable" anywhere else.


def test_storyboard_page_check_works_without_the_full_server():
    import subprocess
    import sys
    from pathlib import Path

    from services.comic_helpers import _comic_page_problem

    app = str(Path(__file__).resolve().parents[1] / "app")
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from services.story_lab_schema import _storyboard_page_problem; "
        "print(_storyboard_page_problem({}, 1))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, app], capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-800:]
    assert result.stdout.strip() == _comic_page_problem({}, 1) == "the panels field is not an array"


def _cancelled_story_job(monkeypatch, tmp_path, job_id: str, status: str):
    """A Story Lab job cancelled after its first stage, in the real job store; the writer and the Activity hooks are fakes."""
    import services.story_lab_jobs as jobs

    published, stages, resets = [], [], []
    monkeypatch.setattr(jobs, "_workspace_dir", lambda _workspace=None: str(tmp_path))
    monkeypatch.setattr(jobs, "_list_workspaces", lambda: [{"name": "film"}])
    monkeypatch.setattr(jobs, "_publish_generic_legacy_task", lambda job, adapter: published.append(job["status"]))
    monkeypatch.setattr(jobs, "_generate_story_lab_stage", lambda body, stage: stages.append(stage) or {stage: {"title": stage}})
    monkeypatch.setattr(jobs, "_story_plan_active_jobs", set())
    monkeypatch.setattr(jobs, "_story_plan_jobs", {})
    job = {
        "jobId": job_id, "status": status, "stage": "cancelled", "workspace": "film", "taskId": "task-story-plan-1",
        "message": "Story generation cancelled.", "finishedAt": 123.0, "cancellationAbortSupported": True,
        "completedStages": {"overview": {"overview": {"title": "kept"}}},
        "request": {"scope": "all", "premise": "A harbour.", "project": {"projectType": "quick_video"}},
    }
    jobs._story_plan_jobs[job_id] = job
    jobs._persist_story_plan_job(job)
    return jobs, published, stages, resets


def test_resuming_a_cancelled_story_generation_restarts_it_from_its_checkpoint(monkeypatch, tmp_path):
    """Owner decision 2026-10-15: a cancelled Story Lab generation is resumable, like a cancelled Series plan.
    _story_job_update used to drop the queued patch of a cancelled job, so the resume answered 200 and ran nothing."""
    import time

    import routers.story_lab as lab

    job_id = "story-plan-aaaaaaaaaaaa"
    for status in ("cancelled", "cancelling"):  # a restart in the middle of a cancel leaves "cancelling" with no worker
        jobs, published, stages, resets = _cancelled_story_job(monkeypatch, tmp_path, job_id, status)
        monkeypatch.setattr(lab, "_reset_canonical_task_for_resume", lambda *args: resets.append(args))
        answered = lab.resume_story_lab_generation(job_id, {})
        assert answered["status"] == "queued" and resets == [("film", "task-story-plan-1")]
        deadline = time.time() + 20
        while time.time() < deadline and (jobs._load_story_plan_job(job_id) or {}).get("status") != "completed":
            time.sleep(0.02)
        final = jobs._load_story_plan_job(job_id)
        assert final["status"] == "completed", (status, final.get("status"), final.get("message"))
        assert stages == ["characters", "world", "structure"], "it continues from the checkpoint, the finished stage is not redone"
        assert final["finishedAt"] and final["finishedAt"] != 123.0 and final["error"] is None
        assert "queued" in published and published[-1] == "completed", "the Activity task follows the job"
        persisted = lab.json.load(open(jobs._story_plan_checkpoint_path(job_id, "film"), encoding="utf-8"))
        assert persisted["status"] == "completed"


def test_a_late_patch_still_cannot_reopen_a_cancelled_story_generation(monkeypatch, tmp_path):
    """Only an explicit resume reopens a cancelled job; a worker's late progress write is still dropped."""
    jobs, *_ = _cancelled_story_job(monkeypatch, tmp_path, "story-plan-bbbbbbbbbbbb", "cancelled")
    kept = jobs._story_job_update("story-plan-bbbbbbbbbbbb", status="running", message="late write")
    assert kept["status"] == "cancelled" and kept["message"] == "Story generation cancelled."


def test_resuming_a_cancelled_story_generation_twice_runs_one_worker(monkeypatch, tmp_path):
    """A second Resume (a double click, a retry) while the first worker runs answers "already running" and starts no
    second worker: every stage is generated once."""
    import time

    import routers.story_lab as lab

    job_id = "story-plan-cccccccccccc"
    jobs, _published, stages, resets = _cancelled_story_job(monkeypatch, tmp_path, job_id, "cancelled")
    monkeypatch.setattr(lab, "_story_plan_active_jobs", jobs._story_plan_active_jobs)
    monkeypatch.setattr(lab, "_reset_canonical_task_for_resume", lambda *args: resets.append(args))
    entered, release = threading.Event(), threading.Event()

    def slow_stage(_body, stage):
        stages.append(stage)
        entered.set()
        assert release.wait(20), "the test never released the writer"
        return {stage: {"title": stage}}

    monkeypatch.setattr(jobs, "_generate_story_lab_stage", slow_stage)
    try:
        assert lab.resume_story_lab_generation(job_id, {})["message"] == "Story generation resumed."
        assert entered.wait(10)
        again = lab.resume_story_lab_generation(job_id, {})
        assert again["message"] == "Story generation is already running."
        workers = [t for t in threading.enumerate() if t.name.startswith("story-plan-")]
        assert len(workers) == 1, workers
    finally:
        release.set()
    deadline = time.time() + 20
    while time.time() < deadline and (jobs._load_story_plan_job(job_id) or {}).get("status") != "completed":
        time.sleep(0.02)
    assert (jobs._load_story_plan_job(job_id) or {}).get("status") == "completed"
    assert stages == ["characters", "world", "structure"], "each unfinished stage was generated exactly once"


def test_a_resume_that_lost_the_race_for_the_worker_cannot_undo_a_cancel(monkeypatch, tmp_path):
    """Resume 2 read ``cancelled`` before Resume 1 claimed the worker and a Cancel then marked the live job
    ``cancelling``: Resume 2's reopening patch must not turn that cancel back into ``queued``."""
    job_id = "story-plan-dddddddddddd"
    jobs, *_ = _cancelled_story_job(monkeypatch, tmp_path, job_id, "cancelling")
    jobs._story_plan_active_jobs.add(job_id)  # a worker is live: the cancel is addressed to it
    kept = jobs._story_job_update(job_id, reopen=True, status="queued", message="late resume")
    assert kept["status"] == "cancelling" and kept["message"] != "late resume"
    assert jobs._load_story_plan_job(job_id)["status"] == "cancelling"


def test_settling_a_cancel_does_not_overwrite_a_resume_that_already_left_cancelling(monkeypatch, tmp_path):
    """The dying worker's cancelled write applies only while the job is still cancelling. Resume after Cancel
    can queue a replacement in the window after the old worker dropped its claim; that queued job must not be
    flipped back to cancelled (and a completed replacement must not be lost)."""
    job_id = "story-plan-eeeeeeeeeeee"
    jobs, *_ = _cancelled_story_job(monkeypatch, tmp_path, job_id, "queued")
    jobs._story_plan_active_jobs.add(job_id)
    kept = jobs._story_job_update(
        job_id, settle_cancel=True, status="cancelled", message="stale settle",
    )
    assert kept["status"] == "queued" and kept["message"] != "stale settle"
    assert jobs._load_story_plan_job(job_id)["status"] == "queued"


def test_settling_a_cancel_still_writes_cancelled_while_the_job_is_cancelling(monkeypatch, tmp_path):
    job_id = "story-plan-ffffffffffff"
    jobs, *_ = _cancelled_story_job(monkeypatch, tmp_path, job_id, "cancelling")
    jobs._story_plan_active_jobs.add(job_id)
    kept = jobs._story_job_update(
        job_id, settle_cancel=True, status="cancelled", stage="cancelled",
        message="Story generation cancelled.", finishedAt=1.0,
    )
    assert kept["status"] == "cancelled" and kept["stage"] == "cancelled"
    assert jobs._load_story_plan_job(job_id)["status"] == "cancelled"


def test_resume_during_cancel_settle_is_already_running_until_cancelled_is_persisted(monkeypatch, tmp_path):
    """Cancel then Resume in one beat: the dying worker keeps its claim until ``cancelled`` is on disk,
    so Resume cannot start a replacement that the settle write would then overwrite."""
    import time

    import routers.story_lab as lab

    job_id = "story-plan-gggggggggggg"
    jobs, _published, stages, resets = _cancelled_story_job(monkeypatch, tmp_path, job_id, "cancelling")
    monkeypatch.setattr(lab, "_story_plan_active_jobs", jobs._story_plan_active_jobs)
    monkeypatch.setattr(lab, "_reset_canonical_task_for_resume", lambda *args: resets.append(args))
    entered, release = threading.Event(), threading.Event()
    real_update = jobs._story_job_update

    def gated(*args, **kwargs):
        if kwargs.get("status") == "cancelled" and kwargs.get("settle_cancel"):
            entered.set()
            assert release.wait(20), "the test never released the settle write"
        return real_update(*args, **kwargs)

    monkeypatch.setattr(jobs, "_story_job_update", gated)
    try:
        assert jobs._start_story_plan_worker(job_id)
        assert entered.wait(10), "the dying worker never reached the cancelled settle"
        assert job_id in jobs._story_plan_active_jobs
        again = lab.resume_story_lab_generation(job_id, {})
        assert again["message"] == "Story generation is already running."
        assert (jobs._load_story_plan_job(job_id) or {}).get("status") == "cancelling"
        assert stages == [] and resets == []
    finally:
        release.set()
    deadline = time.time() + 20
    while time.time() < deadline and job_id in jobs._story_plan_active_jobs:
        time.sleep(0.02)
    assert job_id not in jobs._story_plan_active_jobs
    assert (jobs._load_story_plan_job(job_id) or {}).get("status") == "cancelled"
