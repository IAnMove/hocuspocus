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
