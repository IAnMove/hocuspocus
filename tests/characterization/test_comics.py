"""Director comic: validation errors, a missing job, no completed plan, and the plan, text-page, story-revise and
plan-job life cycle with a fake writing provider.

A real LLM, a real process restart and the animatic render are not exercised here.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path


def test_director_comic_routes_answer_the_recorded_errors(server, golden) -> None:
    """Validation and missing-job answers for the Director comic routes this slice moves. No model runs."""
    plan = "/api/v1/director/comic/plan"
    server.check(golden, "plan without a premise", "POST", plan, json={})
    server.check(golden, "text page without a plan", "POST", "/api/v1/director/comic/text/page", json={})
    server.check(golden, "story revise without a plan", "POST", "/api/v1/director/comic/story/revise", json={})
    server.check(
        golden, "text page with a bad mode", "POST", "/api/v1/director/comic/text/page",
        json={"plan": {"pages": [{"panels": [{"id": "p1"}]}]}, "pageIndex": 0, "mode": "sing"},
    )
    server.check(
        golden, "text page translate without a language", "POST", "/api/v1/director/comic/text/page",
        json={"plan": {"pages": [{"panels": [{"id": "p1"}]}]}, "pageIndex": 0, "mode": "translate"},
    )
    server.check(
        golden, "text page index out of range", "POST", "/api/v1/director/comic/text/page",
        json={"plan": {"pages": [{"panels": [{"id": "p1"}]}]}, "pageIndex": 3, "mode": "rewrite"},
    )
    server.check(
        golden, "story revise with uneven panels", "POST", "/api/v1/director/comic/story/revise",
        json={"plan": {"pages": [{"panels": [{"id": "a"}]}, {"panels": [{"id": "b"}, {"id": "c"}]}]}},
    )
    server.check(golden, "start without a premise", "POST", f"{plan}/start", json={})
    server.check(golden, "status of a missing job", "GET", f"{plan}/status/missing-job")
    server.check(golden, "resume a missing job", "POST", f"{plan}/resume/missing-job", json={})
    server.check(golden, "recent completed with none", "GET", f"{plan}/recent/completed")


# --- The writers and the plan job life cycle, with a fake writing provider -------------------------------
# The real LLM, real images and the animatic render are not exercised here. The fake provider answers by what
# the prompt asks for, so the planner, the lettering editor, the story editor and the language repair all run.

WRITER = {"writingProvider": "ollama", "writingModel": "golden-writer", "writingBaseUrl": "http://127.0.0.1:11434"}
PLAN_ID = (r"comic-plan-[0-9a-f]{12}", "comic-plan-<PLAN>")
JOB_ID = (r"comic-plan-job-[0-9a-f]{12}", "comic-plan-job-<JOB>")
CHARACTERS = [{"id": "keeper", "name": "The Keeper", "description": "tall, grey coat", "locked": True}]


class FakeWriter:
    """Answers the comic writing prompts. ``mode`` picks the behaviour; ``calls`` counts what was asked."""

    def __init__(self) -> None:
        self.mode = "good"
        self.calls: list[str] = []
        self.prompts: list[str] = []
        self.entered = threading.Event()
        self.gate = threading.Event()

    def __call__(self, **request) -> str:
        prompt = request["prompt"]
        self.prompts.append(prompt)
        if "Create the compact story and character bible" in prompt:
            self.calls.append("bible")
            if self.mode == "block":
                self.entered.set()
                assert self.gate.wait(30), "the test never released the writer"
            if self.mode == "no-bible":
                return ""
            pages = int(re.search(r"Exact (?:page|storyboard shot) count: (\d+)", prompt).group(1))
            return json.dumps({
                "title": "Harbour", "logline": "A keeper waits.", "synopsis": "A keeper waits for a ship.",
                "styleBible": "",
                "storyStructure": [
                    {"pageNumber": number, "stage": "Setup", "goal": f"goal {number}", "turningPoint": f"turn {number}"}
                    for number in range(1, pages + 1)
                ],
                "characters": CHARACTERS,
            })
        page = re.search(r"Write (?:page|storyboard shot) (\d+) of this", prompt)
        if page:
            number = int(page.group(1))
            self.calls.append(f"page {number}")
            return json.dumps(self.page(number, int(re.search(r"exactly (\d+) panels", prompt).group(1)), prompt))
        if "Repair the reader-facing language" in prompt:
            self.calls.append("language repair")
            source = json.loads(prompt.split("Source page text: ", 1)[1])
            if self.mode != "english-stuck":
                for panel in source["panels"]:
                    panel["captions"] = [f"Texto {index}" for index, _ in enumerate(panel["captions"], 1)]
                    for index, line in enumerate(panel["dialogue"], 1):
                        line["text"] = f"La verdad {index}"
            return json.dumps(source)
        if "Translate every existing reader-facing" in prompt or "Rewrite the page's lettering" in prompt:
            self.calls.append("lettering")
            source = json.loads(prompt.split("Source page: ", 1)[1])
            if self.mode == "short-lettering":
                return json.dumps({"panels": source[:1]})
            for panel in source:
                if self.mode == "extra-line":
                    panel["captions"] = panel["captions"] + ["an extra caption"]
                else:
                    panel["captions"] = [f"{self.mode}: {line}" for line in panel["captions"]]
                    for line in panel["dialogue"]:
                        line["text"] = f"{self.mode}: {line['text']}"
                        line["bubbleType"] = "scream"
                        line["speakerId"] = "nobody"
            return json.dumps({"panels": source})
        if "Revise this complete comic script" in prompt:
            self.calls.append("revise")
            plan = json.loads(prompt.split("Existing plan: ", 1)[1])
            if self.mode == "short-plan":
                plan["pages"] = plan["pages"][:1]
            plan["logline"] = "A sharper logline."
            for page_item in plan["pages"]:
                for panel in page_item["panels"]:
                    panel["id"] = "ignored-by-the-route"
                    panel["captions"] = ["First caption", "Second caption"]
                    panel["dialogue"] = [{"text": "Talk", "bubbleType": "speech"}]
            return json.dumps(plan)
        raise AssertionError(f"the fake writer got a prompt it does not know: {prompt[:80]!r}")

    def page(self, number: int, panels: int, prompt: str) -> dict:
        if self.mode == "wrong-panels":
            panels = panels + 1
        storyboard = "Production mode: storyboard" in prompt
        english = self.mode in ("english", "english-stuck")
        light = self.mode == "english-light"
        items = []
        for index in range(1, panels + 1):
            panel = {
                "id": f"p{number}-{index}", "order": index, "narrativeRole": f"role {number}.{index}",
                "sceneDescription": f"scene {number}.{index}", "imagePrompt": f"image {number}.{index}",
                "characters": ["The Keeper", "KEEPER", "stranger"][: 1 + index % 3],
                "framing": "Wide shot", "continuityNotes": f"beat {number}.{index}",
                "captions": [], "soundEffects": [], "dialogue": [],
            }
            if storyboard:
                panel.update({"videoPrompt": f"move {number}.{index}", "durationSeconds": 2.5, "cameraMove": "pan-left"})
            elif english:
                panel["dialogue"] = [{"text": "the truth is not the world", "bubbleType": "speech"}]
            elif light:
                panel["dialogue"] = [{"text": "hola the amigo", "bubbleType": "speech"}]
            else:
                # Shortcuts a model really emits: a bare string for a list, or for one speech line.
                panel["captions"] = f"Caption {number}.{index}" if index % 2 else ["Caption", "Caption"]
                panel["dialogue"] = f"Line {number}.{index}" if index == 1 else [
                    {"text": f"Line {number}.{index}", "bubbleType": "speech"},
                    {"text": f"Line {number}.{index}b", "bubbleType": "thought"},
                ]
                panel["soundEffects"] = [f"BOOM {number}.{index}"]
            items.append(panel)
        return {"pageNumber": number, "layoutHint": "dynamic", "panels": items}


def _use_writer(monkeypatch) -> FakeWriter:
    from services import llm_service

    writer = FakeWriter()

    def no_local_model(**_request):
        raise AssertionError("the local model must not run")

    monkeypatch.setattr(llm_service, "generate_openai_compatible", writer)
    monkeypatch.setattr(llm_service, "generate_streaming", no_local_model)
    return writer


def test_director_comic_writers_with_a_fake_provider(server, golden, monkeypatch) -> None:
    """Plan, rewrite, translate and revise with a fake writing provider: the answers, the lettering rules and the
    language repair. No model runs."""
    writer = _use_writer(monkeypatch)
    plan_url, replace = "/api/v1/director/comic/plan", (PLAN_ID, JOB_ID)
    base = {"premise": "A keeper waits.", "pageCount": 2, "panelsPerPage": 3, **WRITER}

    response = server.check(
        golden, "plan two pages", "POST", plan_url, replace=replace,
        json={**base, "characters": CHARACTERS, "dialogueDensity": "medium"},
    )
    plan = response.json()["plan"]
    golden.check("plan two pages: what the writer was asked", 200, server.normalise({
        "calls": list(writer.calls),
        "page two continuity": next(
            line for line in writer.prompts[2].splitlines() if line.startswith("Continuity entering")
        ),
        "page one continuity": next(
            line for line in writer.prompts[1].splitlines() if line.startswith("Opening page")
        ),
    }))
    server.check(golden, "plan with high dialogue", "POST", plan_url, replace=replace, json={
        **base, "characters": CHARACTERS, "dialogueDensity": "high", "panelsPerPage": 4, "tone": "dry",
    })
    writer.mode, writer.calls = "english", []
    server.check(
        golden, "plan in Spanish repairs the English lines", "POST", plan_url, replace=replace,
        json={**base, "language": "Spanish", "pageCount": 1},
    )
    golden.check("plan in Spanish: what the writer was asked", 200, {"calls": list(writer.calls)})
    writer.mode, writer.calls = "english-stuck", []
    server.check(
        golden, "plan in Spanish whose repair stays in English", "POST", plan_url, replace=replace,
        json={**base, "language": "Spanish", "pageCount": 1},
    )
    golden.check("plan in Spanish whose repair stays in English: what the writer was asked", 200, {"calls": list(writer.calls)})
    # One English word per line never trips the line rule; four of them on a page trip the page rule.
    writer.mode, writer.calls = "english-light", []
    server.check(
        golden, "plan in Spanish repairs scattered English words", "POST", plan_url, replace=replace,
        json={**base, "language": "Spanish", "pageCount": 1, "panelsPerPage": 4},
    )
    golden.check("plan in Spanish with scattered English words: what the writer was asked", 200, {"calls": list(writer.calls)})
    writer.mode = "good"
    server.check(
        golden, "plan as a storyboard", "POST", plan_url, replace=replace,
        json={**base, "productionMode": "storyboard", "storyboardAspect": "portrait", "storyboardQuality": "final"},
    )
    writer.mode = "wrong-panels"
    server.check(golden, "plan whose pages stay invalid", "POST", plan_url, replace=replace, json={**base, "pageCount": 1})
    writer.mode = "no-bible"
    server.check(golden, "plan whose bible comes back empty", "POST", plan_url, replace=replace, json=base)

    writer.mode = "rewrite"
    text_page = "/api/v1/director/comic/text/page"
    server.check(golden, "rewrite a page", "POST", text_page, json={
        "plan": plan, "pageIndex": 1, "mode": "rewrite", "instruction": "shorter", "dialogueDensity": "low", **WRITER,
    })
    writer.mode = "translate"
    server.check(golden, "translate a page", "POST", text_page, json={
        "plan": plan, "pageIndex": 0, "mode": "translate", "targetLanguage": "French",
        "glossary": [{"source": "Keeper", "translation": "Gardien"}], **WRITER,
    })
    writer.mode = "extra-line"
    server.check(golden, "translate that changes the text blocks", "POST", text_page, json={
        "plan": plan, "pageIndex": 0, "mode": "translate", "targetLanguage": "French", **WRITER,
    })
    writer.mode = "short-lettering"
    server.check(golden, "rewrite that loses a panel", "POST", text_page, json={
        "plan": plan, "pageIndex": 0, "mode": "rewrite", **WRITER,
    })

    writer.mode = "good"
    revise = "/api/v1/director/comic/story/revise"
    server.check(golden, "revise a story", "POST", revise, replace=replace, json={
        "plan": plan, "instruction": "more tension", "dialogueDensity": "medium", **WRITER,
    })
    server.check(golden, "revise a storyboard", "POST", revise, replace=replace, json={
        "plan": plan, "productionMode": "storyboard", **WRITER,
    })
    writer.mode = "short-plan"
    server.check(golden, "revise that loses a page", "POST", revise, replace=replace, json={"plan": plan, **WRITER})


def _wait_for(check, what: str) -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        if check():
            return
        time.sleep(0.02)
    raise AssertionError(f"never saw: {what}")


def test_director_comic_plan_job_lifecycle_with_a_fake_provider(server, golden, monkeypatch) -> None:
    """Start, poll, resume, recover and reload comic plan jobs; the writing provider is a fake. No model runs."""
    launch = sys.modules["_launch_runtime"]
    writer = _use_writer(monkeypatch)
    plan_url, replace = "/api/v1/director/comic/plan", (PLAN_ID, JOB_ID)
    body = {"premise": "A keeper waits.", "pageCount": 2, "panelsPerPage": 2, "characters": CHARACTERS, **WRITER}
    jobs: list[str] = []

    def start() -> str:
        response = server.check(
            golden, f"lifecycle start {len(jobs) + 1}", "POST", f"{plan_url}/start", replace=replace, json=body,
        )
        jobs.append(response.json()["jobId"])
        return jobs[-1]

    def settle(job: str, *states: str) -> None:
        _wait_for(
            lambda: server.client.get(f"{plan_url}/status/{job}").json().get("status") in states
            and job not in launch._comic_plan_active_jobs,
            f"{job} in {states}",
        )

    def status(case: str, job: str) -> None:
        server.check(golden, case, "GET", f"{plan_url}/status/{job}", replace=replace)

    def activity(case: str) -> list[dict]:
        tasks = server.client.get("/api/v1/tasks", params={"workspace": "default", "status": "all"}).json()["tasks"]
        rows = sorted(
            (
                {key: task.get(key) for key in ("kind", "title", "status", "phase", "message", "error", "resumable")}
                for task in tasks if (task.get("metadata") or {}).get("adapter") == "comic-plan"
            ),
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
        golden.check(case, 200, server.normalise(rows, replace=replace))
        return tasks

    def task_of(job: str, tasks: list[dict]) -> str:
        return next(task["id"] for task in tasks if task.get("backend_job_id") == job)

    try:
        job = start()
        settle(job, "completed", "failed")
        status("lifecycle completed job", job)
        golden.check("lifecycle what the writer was asked", 200, {"calls": list(writer.calls)})
        tasks = activity("lifecycle activity after a completed job")
        assert (Path(launch._workspace_dir("default")) / ".comic-plan-checkpoints" / f"{job}.json").is_file()
        server.check(golden, "lifecycle recent completed", "GET", f"{plan_url}/recent/completed", replace=replace)
        # A job the process forgot comes back from its checkpoint.
        launch._comic_plan_jobs.clear()
        status("lifecycle completed job reloaded from its checkpoint", job)
        launch._comic_plan_jobs.clear()
        server.check(
            golden, "lifecycle recent completed from the checkpoints", "GET", f"{plan_url}/recent/completed",
            replace=replace,
        )

        # Resuming a finished job re-runs it from its saved pages: the writer is not asked again.
        writer.calls.clear()
        server.check(golden, "lifecycle resume a completed job", "POST", f"{plan_url}/resume/{job}", replace=replace, json={})
        settle(job, "completed", "failed")
        status("lifecycle resumed completed job", job)
        golden.check("lifecycle what the writer was asked after the resume", 200, {"calls": list(writer.calls)})

        writer.mode, writer.calls = "block", []
        job = start()
        assert writer.entered.wait(30)
        status("lifecycle running job", job)
        activity("lifecycle activity while a job runs")
        server.check(
            golden, "lifecycle resume while the worker is still active", "POST", f"{plan_url}/resume/{job}",
            replace=replace, json={},
        )
        tasks = server.client.get("/api/v1/tasks", params={"workspace": "default", "status": "all"}).json()["tasks"]
        server.check(
            golden, "lifecycle cancel through the Activity controller", "POST",
            f"/api/v1/tasks/{task_of(job, tasks)}/cancel", replace=replace,
        )
        writer.gate.set()
        settle(job, "completed", "failed")
        status("lifecycle blocked job once released", job)
        golden.check("lifecycle what the writer was asked after the block", 200, {"calls": list(writer.calls)})

        writer.mode = "no-bible"
        job = start()
        settle(job, "failed", "completed")
        status("lifecycle failed job", job)
        tasks = activity("lifecycle activity after a failed job")
        writer.mode, writer.calls = "good", []
        # Only the resume's own answer: the task snapshot next to it races with the worker that just started.
        response = server.client.post(f"/api/v1/tasks/{task_of(job, tasks)}/resume")
        golden.check(
            "lifecycle resume a failed job through the Activity controller", response.status_code,
            server.normalise(response.json()["result"], replace=replace),
        )
        settle(job, "completed", "failed")
        status("lifecycle resumed failed job", job)
        activity("lifecycle activity after a resumed job")

        # A page that stays invalid fails the job after three tries; the resume keeps the saved bible.
        writer.mode, writer.calls = "wrong-panels", []
        job = start()
        settle(job, "failed", "completed")
        status("lifecycle job with an invalid page", job)
        golden.check("lifecycle what the writer was asked for the invalid page", 200, {"calls": list(writer.calls)})
        writer.mode, writer.calls = "good", []
        server.check(golden, "lifecycle resume the invalid page", "POST", f"{plan_url}/resume/{job}", replace=replace, json={})
        settle(job, "completed", "failed")
        status("lifecycle resumed invalid page", job)
        golden.check("lifecycle what the writer was asked after the invalid page", 200, {"calls": list(writer.calls)})
        # Several jobs are completed now: the newest one is recovered, from memory and from the checkpoints.
        newest = server.client.get(f"{plan_url}/recent/completed")
        assert newest.json()["jobId"] == jobs[-1], "recent/completed must return the newest completed job"
        launch._comic_plan_jobs.clear()
        from_disk = server.client.get(f"{plan_url}/recent/completed")
        assert from_disk.json()["jobId"] == jobs[-1], "recent/completed from the checkpoints must return the newest job"
        golden.check(
            "lifecycle recent completed with several jobs", from_disk.status_code,
            server.normalise(from_disk.json(), replace=replace),
        )
    finally:
        writer.gate.set()
        _wait_for(
            lambda: not any(
                thread.name.startswith("comic-plan-") and thread.is_alive() for thread in threading.enumerate()
            ),
            "the comic plan workers to stop",
        )
        launch._comic_plan_jobs.clear()


def test_director_comic_state_is_one_instance_and_the_bind_is_live(full_server, monkeypatch) -> None:
    """The moved modules share the launch objects. Not recorded on the old code: it names the new modules."""
    import services.comic_animatic as animatic
    import services.comic_helpers as helpers
    import services.director_comic_jobs as plan_jobs
    import services.story_lab_schema as story_schema
    import routers.director_comic as plan_router
    from tests.support.full_server import _route_contexts

    launch = sys.modules["_launch_runtime"]
    # One job dictionary, one lock and one set of running plans, whoever reads them.
    for name in ("_comic_plan_jobs", "_comic_plan_jobs_lock", "_comic_plan_active_jobs"):
        assert getattr(launch, name) is getattr(plan_jobs, name) is getattr(plan_router, name), name
    # The job worker runs the handler the route serves, and the planner reads the server's own helpers.
    assert plan_jobs.director_comic_plan is plan_router.director_comic_plan
    assert helpers.wgp is plan_jobs.wgp is launch.wgp
    for name in ("_ensure_llm_loaded", "_workspace_dir", "_effective_llm_routing"):
        assert getattr(plan_jobs, name) is getattr(launch, name), name
    assert plan_router._ensure_llm_loaded is launch._ensure_llm_loaded
    assert plan_router._get_active_workspace is launch._get_active_workspace
    assert launch._comic_writing_llm is helpers._comic_writing_llm
    assert launch.resume_director_comic_plan is plan_router.resume_director_comic_plan
    # The Story Lab storyboard check calls the comic page check.
    assert story_schema._comic_page_problem is helpers._comic_page_problem is launch._comic_page_problem
    # The animatic worker reaches the video editor's own objects and is the one the comics router runs.
    for name in (
        "_resolve_model3d_input_path", "_VIDEO_EDITOR_FFMPEG_LANE", "_VIDEO_EDITOR_TERMINAL",
        "_finish_video_editor_cancelled", "_remove_video_editor_output_bundle", "_video_editor_cancel_requested",
        "_video_editor_job_snapshot", "_video_editor_job_update",
    ):
        assert getattr(animatic, name) is getattr(launch, name), name
    assert launch._run_comic_animatic is animatic._run_comic_animatic
    start = next(
        route.endpoint for route in _route_contexts(full_server.api)
        if getattr(route.endpoint, "__name__", "") == "start_comic_animatic"
    )
    mounted = dict(zip(start.__code__.co_freevars, (cell.cell_contents for cell in start.__closure__)))
    assert mounted["run_comic_animatic"] is animatic._run_comic_animatic
    # The Activity publisher is looked up on the publishers module when called. The resume reset
    # is looked up on the sync module when called.
    import services.canonical_task_publishers as task_publishers
    import services.canonical_task_sync as task_sync
    monkeypatch.setattr(task_publishers, "_publish_generic_legacy_task", lambda record, adapter: ("published", adapter))
    assert plan_jobs._publish_generic_legacy_task({}, "comic-plan") == ("published", "comic-plan")
    assert plan_router._publish_generic_legacy_task({}, "comic-plan") == ("published", "comic-plan")
    monkeypatch.setattr(task_sync, "_reset_canonical_task_for_resume", lambda workspace, task_id: (workspace, task_id))
    assert plan_router._reset_canonical_task_for_resume("film", "task-1") == ("film", "task-1")
