"""Model-free regressions for Comic planner restart/resume ownership."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
import threading


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"


def _function(name: str):
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            selected = copy.deepcopy(node)
            selected.decorator_list = []
            return selected
    raise AssertionError(f"Function {name!r} not found")


def _load(name: str, namespace: dict):
    module = ast.Module(body=[_function(name)], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(LAUNCH), "exec"), namespace)
    return namespace[name]


def test_stale_planning_checkpoint_resumes_when_no_worker_survived_restart():
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

    resume = _load("resume_director_comic_plan", {
        "_comic_plan_jobs_lock": threading.Lock(),
        "_comic_plan_active_jobs": active,
        "get_director_comic_plan_status": lambda _job_id: dict(job),
        "_reset_canonical_task_for_resume": lambda workspace, task_id: resets.append(
            (workspace, task_id)
        ),
        "_comic_plan_job_update": update,
        "_start_comic_plan_worker": start,
    })

    response = resume(job_id)

    assert response["status"] == "queued"
    assert job["status"] == "queued"
    assert job["finishedAt"] is None
    assert resets == [("default", f"task-comic-plan-{job_id}")]
    assert len(starts) == 1


def test_live_comic_worker_is_not_started_twice():
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
    resume = _load("resume_director_comic_plan", {
        "_comic_plan_jobs_lock": threading.Lock(),
        "_comic_plan_active_jobs": active,
        "get_director_comic_plan_status": lambda _job_id: dict(job),
        "_reset_canonical_task_for_resume": lambda *_args: resets.append("reset"),
        "_comic_plan_job_update": lambda *_args, **_kwargs: None,
        "_start_comic_plan_worker": lambda *_args, **_kwargs: starts.append("start"),
    })

    response = resume(job_id)

    assert response["status"] == "planning"
    assert response["message"] == "Still planning"
    assert starts == []
    assert resets == []


def test_worker_claim_is_atomic_before_thread_start():
    started: list[object] = []

    class DeferredThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            started.append(self)

    namespace = {
        "threading": type("Threading", (), {"Thread": DeferredThread}),
        "_comic_plan_jobs_lock": threading.Lock(),
        "_comic_plan_active_jobs": set(),
        "_run_comic_plan_job": lambda *_args: None,
    }
    launch = _load("_start_comic_plan_worker", namespace)

    assert launch("comic-plan-job-111111111111", {}, thread_name="first") is True
    assert launch("comic-plan-job-111111111111", {}, thread_name="second") is False
    assert len(started) == 1


# --- The writers do not invent a tone (glass wall 5) --------------------------------------------------
# An empty tone leaves the "Tone:" line out of the prompt. It used to default to "Cinematic".


class _PromptCaptured(RuntimeError):
    """Raised by the fake provider call once it has seen the prompt."""


def _writer_namespace(prompts: list[str], **extra) -> dict:
    from fastapi import HTTPException

    def capture(*, prompt: str, **_kwargs):
        prompts.append(prompt)
        raise _PromptCaptured("prompt captured")

    return {
        "HTTPException": HTTPException, "copy": copy, "json": __import__("json"),
        "_comic_writing_llm": lambda _body: {"provider": "stub"},
        "_ensure_llm_loaded": lambda: None,
        "_generate_comic_director_json": capture,
        **extra,
    }


def _story_writer_prompt(project: dict, body: dict | None = None) -> str:
    prompts: list[str] = []
    write = _load("_generate_story_lab_stage", _writer_namespace(
        prompts,
        _story_project_prompt_context=lambda _project, _scope: "",
        _story_lab_schema=lambda _scope, _project_type: {},
    ))
    try:
        write({"premise": "A lighthouse keeper hears the sea", "project": project, **(body or {})}, "overview")
    except Exception:
        pass  # the fake provider call ends the run; only the prompt matters
    assert len(prompts) == 1
    return prompts[0]


def _comic_planner_prompt(body: dict) -> str:
    prompts: list[str] = []
    plan = _load("director_comic_plan", _writer_namespace(
        prompts, _COMIC_BIBLE_SCHEMA={"properties": {"storyStructure": {}}},
    ))
    try:
        plan({"premise": "A fox learns to whistle", "pageCount": 1, **body})
    except Exception:
        pass  # the fake provider call ends the run; only the prompt matters
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
