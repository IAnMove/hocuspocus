"""The Director pipeline lifecycle and the v2 plan jobs, answered through the real routes.

A real pipeline run needs the GPU and a real plan needs an LLM, so the engine
behind the routes is faked: the pipeline functions the handlers call
(``services.director_pipeline``), the language-model calls, and the orchestrator
the v2 plan drives. Everything between the HTTP request and those fakes is the
real server: the handlers, the pipeline init, the execution-mode gate, the task
registry and the Activity controller, the plan job store, the activity
tracking. Each step records the status, the body and the calls the handler made
into the fakes, so a move that changes an argument, a status code, the order of
the calls or a side effect on the task registry fails its golden.

The pipeline engine is initialised for real (the first route that needs it does
that, once per process), so the other tests of the session keep a wired engine.
"""
from __future__ import annotations

import sys
from typing import Any

SHORT = 200


def _shorten(value: Any) -> Any:
    """Long prompts and policy texts become a marker: their wording belongs to the policy tests, not to the routes."""
    if isinstance(value, dict):
        return {key: _shorten(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_shorten(item) for item in value]
    if isinstance(value, str) and len(value) > SHORT:
        return "<long text>"
    return value


def _plan_summary(body: Any) -> Any:
    """A finished plan: its shape, not the text of its prompts (those belong to the policy tests)."""
    if isinstance(body, dict) and isinstance(body.get("clip_plans"), list):
        plans = body["clip_plans"]
        return {
            **{key: value for key, value in body.items() if key != "clip_plans"},
            "clip_plans": {
                "count": len(plans),
                "clip_indexes": [plan.get("clip_index") for plan in plans if isinstance(plan, dict)],
                "keys": sorted({key for plan in plans if isinstance(plan, dict) for key in plan}),
            },
        }
    return body


def record(server: Any, golden: Any, monkeypatch: Any) -> None:
    """Run the scenario and check every step against the golden."""
    from services import audio_analysis, execution_mode, llm_routing, llm_service
    from services import director_pipeline as pipeline
    from services.director import orchestrator, prompt_polish
    from services.director.pipeline_locks import PipelineBusyError

    calls: list[Any] = []

    def log(name: str, *args: Any, **kwargs: Any) -> None:
        calls.append([name, list(args), dict(sorted(kwargs.items()))])

    pipes = {
        "paused": {"id": "paused", "status": "paused", "phase": "paused", "workspace": "ws-a",
                   "pipeline_type": "music_video", "progress": {"current": 2, "total": 5, "message": "m"}},
        "crashed": {"id": "crashed", "status": "crashed", "phase": "crashed", "workspace": "ws-b",
                    "progress": {"current": 1, "total": 3}},
        "noworkspace": {"id": "noworkspace", "status": "failed", "error": "bad thing"},
        "failedpipe": {"id": "failedpipe", "status": "failed", "phase": "failed", "workspace": "ws-c",
                       "error": "gpu fell over"},
    }
    resumable = {"crashed", "paused", "noworkspace", "failedpipe"}

    def get_pipeline(pid):
        log("get_pipeline", pid)
        found = pipes.get(pid)
        return dict(found) if found else None

    def start_pipeline(params):
        log("start_pipeline", params)
        if params.get("fail") == "value":
            raise ValueError("bad start params")
        pipes["pipe-1"] = {"id": "pipe-1", "task_id": "task-director-pipe-1", "status": "running"}
        return "pipe-1"

    def continue_pipeline(pid, updates=None):
        log("continue_pipeline", pid, updates)
        return pid == "paused"

    def start_preview_generation(pid, clip_index, base, clip_indices=None, expected_fingerprint=None, run_type=None):
        log("start_preview_generation", pid, clip_index, base, clip_indices=clip_indices,
            expected_fingerprint=expected_fingerprint, run_type=run_type)
        if pid == "preview":
            return True, "started", "child-1"
        if pid == "running":
            return True, "already_running", "child-0"
        return False, "preview refused", None

    def update_comic_preview(pid, clips, base, **kwargs):
        log("update_comic_preview", pid, clips, base, **kwargs)
        if pid == "preview":
            pipes["preview"] = {
                "id": "preview", "status": "preview_ready", "_comic_preflight_fingerprint": "fp1",
                "_preview_approved_fingerprint": "fp1", "preview_clips": [{"i": 1}],
                "_quality_gate": {"ok": True},
            }
            return True, "preview saved"
        return False, "no such preview"

    def stop_pipeline(pid):
        log("stop_pipeline", pid)
        return pid in pipes

    def resume_pipeline(pid, base):
        log("resume_pipeline", pid, base)
        return (True, "resumed") if pid in resumable else (False, "cannot resume")

    def raising(name, result):
        """A pipeline function that fails the way the pid asks: ``busy``, ``bad``, ``boom`` or ``cancelled``."""
        def call(base, pid, *args, **kwargs):
            log(name, base, pid, *args, **kwargs)
            if pid == "busy":
                raise PipelineBusyError("busy now")
            if pid == "bad":
                raise ValueError("bad value")
            if pid == "boom":
                raise RuntimeError("boom!")
            if pid == "cancelled":
                raise pipeline.GenerationCancelledError(["x.png", "y.png"])
            return result(pid, *args, **kwargs)
        return call

    def update_clip_tag(base, pid, clip_index, tag):
        log("update_clip_tag", base, pid, clip_index, tag)
        if pid == "busy":
            raise PipelineBusyError("busy tag")
        return pid != "nopipe"

    def cancel_pipeline_repair(base, pid):
        log("cancel_pipeline_repair", base, pid)
        return {"phase": "cancelling"} if pid == "repairing" else None

    def delete_pipeline(base, pid):
        log("delete_pipeline", base, pid)
        errors = {"running": "running", "locked": "state_file_locked", "media": "media_locked", "gone": "other"}
        if pid in errors:
            return {"ok": False, "error": errors[pid]}
        return {"ok": True, "media_deleted": 3, "media_deferred": 1, "dir": str(server.outputs / pid)}

    patches = {
        "get_pipeline": get_pipeline, "start_pipeline": start_pipeline, "continue_pipeline": continue_pipeline,
        "start_preview_generation": start_preview_generation, "update_comic_preview": update_comic_preview,
        "stop_pipeline": stop_pipeline, "resume_pipeline": resume_pipeline, "update_clip_tag": update_clip_tag,
        "cancel_pipeline_repair": cancel_pipeline_repair, "delete_pipeline": delete_pipeline,
        "update_clip_prompts": raising("update_clip_prompts", lambda pid, idx, **kw: {"updated": pid, "idx": idx, **kw}),
        "select_clip_video_attempt": raising("select_clip_video_attempt", lambda pid, idx, name: {"selected": name, "idx": idx}),
        "start_pipeline_repair": raising("start_pipeline_repair", lambda pid: {"repair": "started", "pid": pid}),
        "rerun_clip_image": raising("rerun_clip_image", lambda pid, idx, prompt_override=None: {"image": pid, "idx": idx, "prompt": prompt_override}),
        "rerun_clip_video": raising("rerun_clip_video", lambda pid, idx, prompt_override=None: {"video": pid, "idx": idx, "prompt": prompt_override}),
        "rerun_h3_segment": raising("rerun_h3_segment", lambda pid, clip, seg, prompt_override=None, cascade=True: {"seg": seg, "clip": clip, "cascade": cascade, "prompt": prompt_override}),
        "rejoin_clips": raising("rejoin_clips", lambda pid: {"rejoined": pid}),
    }
    for name, fake in patches.items():
        monkeypatch.setattr(pipeline, name, fake)

    # The language-model side of the planners.
    # Only the provider the route asked for: the model, device and URL are server defaults that change on their own.
    monkeypatch.setattr(llm_routing, "_ensure_llm_loaded", lambda **kwargs: log("ensure_llm_loaded", provider=kwargs["provider"]))

    def classify_song_sections(**kwargs):
        log("classify_song_sections", **kwargs)
        if kwargs.get("lyrics") == "RAISE":
            raise RuntimeError("llm down")
        structure = [] if kwargs.get("lyrics") == "NOSTRUCT" else [{"label": "verse", "start": 0, "end": 1}]
        return {"labels": ["verse"] * len(kwargs["sections"]), "song_structure": structure}

    def plan_clip_prompts_and_images(**kwargs):
        log("plan_clip_prompts_and_images", **kwargs)
        if kwargs["scene_description"] == "RAISE":
            raise RuntimeError("planner exploded")
        return [{"clip_index": 0, "video_prompt": "a v", "image_prompt": "an i", "duration": 5}]

    def plan_short_film_from_story(**kwargs):
        log("plan_short_film_from_story", **kwargs)
        if kwargs["story_description"] == "RAISE":
            raise RuntimeError("story down")
        return {"scenes": [{"s": 1}], "raw": kwargs.get("raw_prompts")}

    monkeypatch.setattr(llm_service, "classify_song_sections", classify_song_sections)
    monkeypatch.setattr(llm_service, "structure_from_tagged_lyrics",
                        lambda hint, duration: log("structure_from_tagged_lyrics", hint, duration) or ([{"label": "chorus"}] if hint == "TAGGED" else []))
    monkeypatch.setattr(llm_service, "plan_clip_prompts_and_images", plan_clip_prompts_and_images)
    monkeypatch.setattr(llm_service, "plan_short_film_prompts",
                        lambda **kw: log("plan_short_film_prompts", **kw) or [{"clip_index": 0, "video_prompt": "sf v", "image_prompt": "sf i", "duration": 5}])
    monkeypatch.setattr(llm_service, "plan_short_film_from_story", plan_short_film_from_story)
    monkeypatch.setattr(audio_analysis, "structure_from_aligned_lyrics",
                        lambda timeline: log("structure_from_aligned_lyrics", timeline) or ([{"label": "intro"}] if timeline else []))
    monkeypatch.setattr(audio_analysis, "replace_sections_with_structure",
                        lambda analysis, structure: log("replace_sections_with_structure", structure) or {"sections": [{"replaced": len(structure)}]})
    monkeypatch.setattr(audio_analysis, "classify_sections_with_lyrics",
                        lambda analysis, labels: log("classify_sections_with_lyrics", labels) or {"sections": [{"labelled": labels}]})
    monkeypatch.setattr(audio_analysis, "plan_dialogue_scenes", lambda **kw: log("plan_dialogue_scenes", **kw) or [{"clip": 1}])

    services = server.wgp.server_config["services"]
    # The language-model provider comes from the active production profile's text section.
    routing = {"provider": "local"}
    runtime = sys.modules["_launch_runtime"]
    monkeypatch.setattr(runtime, "_active_production_profile",
                        lambda *args, **kwargs: {"text": {"provider": routing["provider"], "model": ""}})
    steps = {"count": 0}

    def step(case: str, method: str, path: str, *, summarise: bool = False, **request: Any) -> Any:
        calls.clear()
        response = server.client.request(method, path, **request)
        try:
            body = response.json()
        except ValueError:
            body = {"<text>": response.text}
        if summarise:
            body = _plan_summary(body)
        observed = _shorten(server.normalise({"body": body, "calls": list(calls)}))
        golden.check(f"lifecycle: {case}", response.status_code, observed)
        steps["count"] += 1
        return response

    base = "/api/v1/director"
    # A route that does not need the pipeline does not wake it.
    step("stop unknown pipeline", "POST", f"{base}/pipeline/nope/stop")
    step("stop known pipeline", "POST", f"{base}/pipeline/paused/stop")
    step("tag a clip", "PUT", f"{base}/pipelines/p1/clips/0/tag", json={"tag": "good"})

    # The planners.
    step("classify without analysis", "POST", f"{base}/classify-sections", json={})
    step("classify without sections", "POST", f"{base}/classify-sections", json={"analysis": {"sections": []}})
    step("classify from the timeline", "POST", f"{base}/classify-sections",
         json={"analysis": {"sections": [{"a": 1}], "lyric_timeline": [{"t": 1}]}})
    step("classify from the hint", "POST", f"{base}/classify-sections",
         json={"analysis": {"sections": [{"a": 1}], "duration": 30}, "lyrics_hint": "TAGGED"})
    step("classify without lyrics", "POST", f"{base}/classify-sections", json={"analysis": {"sections": [{"a": 1}]}})
    step("classify with the model", "POST", f"{base}/classify-sections",
         json={"analysis": {"sections": [{"a": 1}], "lyrics": "words", "duration": 12}})
    step("classify labels only", "POST", f"{base}/classify-sections",
         json={"analysis": {"sections": [{"a": 1}, {"b": 2}], "lyrics": "NOSTRUCT"}})
    step("classify when the model fails", "POST", f"{base}/classify-sections",
         json={"analysis": {"sections": [{"a": 1}], "lyrics": "RAISE"}})
    step("plan prompts and images", "POST", f"{base}/plan-prompts-and-images",
         json={"clips": [{"c": 1}], "scene_description": "scene", "bpm": 90, "lyrics": "l"})
    step("plan prompts and images for H3", "POST", f"{base}/plan-prompts-and-images",
         json={"clips": [{"c": 1}], "scene_description": "scene", "video_model": "minimax_h3_i2v",
               "h3_reference_mode": "first_frame", "h3_audio_prompt": "calm"})
    step("plan prompts and images fails", "POST", f"{base}/plan-prompts-and-images",
         json={"clips": [{"c": 1}], "scene_description": "RAISE"})
    step("plan dialogue scenes", "POST", f"{base}/plan-dialogue-scenes", json={"analysis": {"x": 1}, "pacing_bias": 2})
    step("plan short film prompts", "POST", f"{base}/plan-short-film-prompts",
         json={"clips": [{"c": 1}], "scene_description": "s", "characters": [{"n": "a"}]})
    step("plan short film prompts for H3", "POST", f"{base}/plan-short-film-prompts",
         json={"clips": [{"c": 1}], "scene_description": "s", "video_model": "minimax_h3_x"})
    step("plan a short film script", "POST", f"{base}/plan-short-film-script",
         json={"story_description": "a story", "target_duration": 20})
    monkeypatch.setitem(services, "raw_prompts", True)
    step("plan a short film script with raw prompts", "POST", f"{base}/plan-short-film-script",
         json={"story_description": "a story"})
    monkeypatch.delitem(services, "raw_prompts")
    step("plan a short film script fails", "POST", f"{base}/plan-short-film-script", json={"story_description": "RAISE"})

    # A pipeline from start to resume.
    step("start with an unknown collection", "POST", f"{base}/pipeline/start",
         json={"provenance": {"workspace_id": "nope"}})
    step("start", "POST", f"{base}/pipeline/start",
         json={"clips": [{"c": 1}], "workspace": "ws-a", "provenance": {"actor": "user"}})
    step("start in the active workspace", "POST", f"{base}/pipeline/start", json={"clips": []})
    step("start with bad parameters", "POST", f"{base}/pipeline/start", json={"fail": "value"})
    real_validate = execution_mode.validate_generation

    def refuse(workspace):
        raise execution_mode.ExecutionModeError("simulated refusal for " + str(workspace))

    monkeypatch.setattr(execution_mode, "validate_generation", refuse)
    step("start refused by the execution mode", "POST", f"{base}/pipeline/start", json={"workspace": "ws-z"})
    monkeypatch.setattr(execution_mode, "validate_generation", real_validate)
    step("continue a pipeline that is not paused", "POST", f"{base}/pipeline/nope/continue")
    step("continue a paused pipeline", "POST", f"{base}/pipeline/paused/continue")
    step("continue with new plans", "POST", f"{base}/pipeline/paused/continue", json={"clip_plans": [{"x": 1}]})
    step("preview refused", "POST", f"{base}/pipeline/nope/generate-preview", json={"clip_index": 2})
    step("preview started", "POST", f"{base}/pipeline/preview/generate-preview",
         json={"clip_index": 1, "clip_indices": [1, 2], "expected_fingerprint": "fp1", "run_type": "test"})
    step("preview already running", "POST", f"{base}/pipeline/running/generate-preview", json={})
    step("update an unknown preview", "PATCH", f"{base}/pipeline/nope/preview", json={"clips": []})
    step("update a preview", "PATCH", f"{base}/pipeline/preview/preview",
         json={"clips": [{"c": 1}], "approve_preview": True, "quality_waiver": 1, "waiver_reason": "ok", "accepted_by": "me"})
    step("stop a paused pipeline", "POST", f"{base}/pipeline/paused/stop")
    step("resume an unknown pipeline", "POST", f"{base}/pipeline/nope/resume")
    step("resume a crashed pipeline", "POST", f"{base}/pipeline/crashed/resume")
    step("resume a pipeline without a workspace", "POST", f"{base}/pipeline/noworkspace/resume")
    step("resume a paused pipeline", "POST", f"{base}/pipeline/paused/resume")
    step("resume a failed pipeline", "POST", f"{base}/pipeline/failedpipe/resume")
    step("resume a failed pipeline again", "POST", f"{base}/pipeline/failedpipe/resume")
    step("task events of the reopened task", "GET", "/api/v1/tasks/task-director-failedpipe/events?workspace=ws-c")
    step("task of a resumed pipeline", "GET", "/api/v1/tasks/task-director-crashed?workspace=ws-b")
    step("Activity retry", "POST", "/api/v1/tasks/task-director-crashed/retry?workspace=ws-b")
    step("Activity cancel", "POST", "/api/v1/tasks/task-director-paused/cancel?workspace=ws-a")
    step("Activity resume", "POST", "/api/v1/tasks/task-director-paused/resume?workspace=ws-a")

    # Edits, repair, reruns, rejoin and delete.
    clips = f"{base}/pipelines"
    step("edit a prompt", "PUT", f"{clips}/p1/clips/2/prompt",
         json={"video_prompt": "v", "image_prompt": "i", "soundtrack_drive": 1})
    step("edit a prompt while busy", "PUT", f"{clips}/busy/clips/2/prompt", json={"video_prompt": "v"})
    step("edit a prompt badly", "PUT", f"{clips}/bad/clips/2/prompt", json={})
    step("tag a clip needs work", "PUT", f"{clips}/p1/clips/2/tag", json={"tag": "needs_work"})
    step("tag a missing pipeline", "PUT", f"{clips}/nopipe/clips/2/tag", json={"tag": None})
    step("tag a busy pipeline", "PUT", f"{clips}/busy/clips/2/tag", json={"tag": "good"})
    step("select a video", "PUT", f"{clips}/p1/clips/2/video-selection", json={"filename": "v.mp4"})
    step("select a video while busy", "PUT", f"{clips}/busy/clips/2/video-selection", json={"filename": "v.mp4"})
    step("select a video badly", "PUT", f"{clips}/bad/clips/2/video-selection", json={})
    step("repair", "POST", f"{clips}/p1/repair")
    step("repair while busy", "POST", f"{clips}/busy/repair")
    step("repair badly", "POST", f"{clips}/bad/repair")
    step("repair fails", "POST", f"{clips}/boom/repair")
    step("cancel a repair that is not running", "POST", f"{clips}/p1/repair/cancel")
    step("cancel a running repair", "POST", f"{clips}/repairing/repair/cancel")
    for kind in ("rerun-image", "rerun-video"):
        step(f"{kind}", "POST", f"{clips}/p1/clips/3/{kind}", json={"prompt": "new"})
        step(f"{kind} in a workspace", "POST", f"{clips}/p1/clips/3/{kind}", json={"prompt": "new", "workspace": "ws-a"})
        step(f"{kind} while busy", "POST", f"{clips}/busy/clips/3/{kind}", json={})
        step(f"{kind} cancelled", "POST", f"{clips}/cancelled/clips/3/{kind}", json={})
        step(f"{kind} badly", "POST", f"{clips}/bad/clips/3/{kind}", json={})
        step(f"{kind} fails", "POST", f"{clips}/boom/clips/3/{kind}", json={})
    step("rerun-video with a bad shared review", "POST", f"{clips}/p1/clips/3/rerun-video",
         json={"shared_review": "nope"})
    step("rerun a segment", "POST", f"{clips}/p1/clips/1/segments/2/rerun", json={"prompt": "seg", "cascade": False})
    step("rerun a segment with the default cascade", "POST", f"{clips}/p1/clips/1/segments/2/rerun", json={})
    step("rerun a segment badly", "POST", f"{clips}/bad/clips/1/segments/2/rerun", json={})
    step("rerun a segment fails", "POST", f"{clips}/boom/clips/1/segments/2/rerun", json={})
    step("rejoin", "POST", f"{clips}/p1/rejoin")
    step("rejoin while busy", "POST", f"{clips}/busy/rejoin")
    step("rejoin badly", "POST", f"{clips}/bad/rejoin")
    step("rejoin fails", "POST", f"{clips}/boom/rejoin")
    for pid in ("p1", "running", "locked", "media", "gone"):
        step(f"delete {pid}", "DELETE", f"{clips}/{pid}")

    # The v2 plan jobs, with a fake orchestrator that checkpoints batches of two shots.
    monkeypatch.setitem(services, "director_prompt_polish", "off")
    failure = {"batch": None}
    created: list[Any] = []

    class FakePlan:
        def __init__(self, count: int, kind: str) -> None:
            self.shots = list(range(count))
            self.kind = kind

        def to_dict(self) -> dict:
            return {"kind": self.kind, "shots": [{"i": index} for index in self.shots]}

    class FakeOrchestrator:
        def __init__(self, llm_generate=None, llm_generate_streaming=None, flags=None) -> None:
            created.append(flags)
            log("orchestrator", raw_prompts=flags.raw_prompts, generate=llm_generate is llm_service.generate,
                streaming=llm_generate_streaming is llm_service.generate_streaming)

        def plan(self, skill_type, **kwargs):
            checkpoint = kwargs.get("batch_checkpoint")
            log("plan", skill_type, **{key: ("<callback>" if callable(value) else value) for key, value in kwargs.items()})
            clips = kwargs.get("clips") or []
            done = {int(plan["clip_index"]) for plan in kwargs.get("completed_shot_plans") or [] if "clip_index" in plan}
            todo = [index for index in range(1, len(clips) + 1) if index not in done]
            for number, batch in enumerate([todo[i:i + 2] for i in range(0, len(todo), 2)]):
                if checkpoint:
                    checkpoint({"event": "call_started", "indices": batch, "phase": "planning"})
                if failure["batch"] == number:
                    raise RuntimeError(f"provider stopped at batch {number}")
                if checkpoint:
                    checkpoint({"event": "batch_completed", "indices": batch,
                                "shot_plans": [{"clip_index": index, "text": f"shot {index}"} for index in batch]})
            return FakePlan(len(clips) or 2, skill_type)

        def render_plan(self, plan, prompt_type="both", has_reference=False):
            log("render_plan", prompt_type, has_reference)
            return plan

        def plan_to_clip_plans(self, rendered):
            return [{"clip_index": index, "video_prompt": f"video {index}", "image_prompt": f"image {index}", "duration": 5}
                    for index in rendered.shots]

    monkeypatch.setattr(orchestrator, "DirectorOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        prompt_polish, "polish_prompts_third_pass",
        lambda plans, video_model, image_model, nsfw, **kw: (
            log("polish_third_pass", video_model, image_model, nsfw, kw.get("characters"))
            or kw["progress_callback"](1, len(plans)) or plans
        ),
    )

    plan = f"{base}/v2/plan"
    step("v2 plan that is not an object", "POST", plan, json=[])
    step("v2 progress of an unknown activity", "GET", f"{plan}/progress/act-none")
    music = {"skill_type": "music_video", "clips": [{"c": 0}, {"c": 1}, {"c": 2}], "scene_description": "scene",
             "activity_id": "act-1", "workspace": "default", "video_model": "wan"}
    job_id = step("v2 music video plan", "POST", plan, json=music, summarise=True).json().get("plan_job_id")
    step("v2 progress after the plan", "GET", f"{plan}/progress/act-1")
    step("v2 jobs", "GET", f"{plan}/jobs")
    step("v2 job", "GET", f"{plan}/jobs/{job_id}")
    step("v2 missing job", "GET", f"{plan}/jobs/nope")
    step("v2 job of another workspace", "GET", f"{plan}/jobs/{job_id}?workspace=ws-a")
    step("v2 resume a completed job", "POST", f"{plan}/jobs/{job_id}/resume", json={"activity_id": "act-1b"}, summarise=True)
    step("v2 resume a missing job", "POST", f"{plan}/jobs/nope/resume", json={})
    failure["batch"] = 1
    long_plan = dict(music, activity_id="act-2", clips=[{"c": index} for index in range(5)])
    step("v2 music video plan that stops half way", "POST", plan, json=long_plan, summarise=True)
    listing = server.client.get(f"{plan}/jobs").json()
    failed_id = next(job["jobId"] for job in listing["jobs"] if job.get("status") == "failed")
    step("v2 jobs after the failure", "GET", f"{plan}/jobs")
    step("v2 failed job", "GET", f"{plan}/jobs/{failed_id}")
    step("v2 progress of the failed plan", "GET", f"{plan}/progress/act-2")
    failure["batch"] = None
    step("v2 resume the failed job", "POST", f"{plan}/jobs/{failed_id}/resume", json={"activity_id": "act-2b"}, summarise=True)
    step("v2 job after the resume", "GET", f"{plan}/jobs/{failed_id}")
    step("v2 resume it again", "POST", f"{plan}/jobs/{failed_id}/resume", json={}, summarise=True)
    step("v2 plan for another skill with the job id", "POST", plan,
         json={"skill_type": "short_film", "plan_job_id": failed_id}, summarise=True)
    step("v2 plan with an unknown job id", "POST", plan, json={"skill_type": "music_video", "plan_job_id": "nope"})
    step("v2 plan with the job id of another workspace", "POST", plan,
         json={"skill_type": "music_video", "plan_job_id": failed_id, "workspace": "ws-q"})
    step("v2 plan with a completed job id", "POST", plan,
         json={"skill_type": "music_video", "plan_job_id": failed_id}, summarise=True)
    step("v2 short film plan", "POST", plan,
         json={"pipeline_type": "short_film_story", "story_description": "story", "target_scenes": 3, "activity_id": "act-3"},
         summarise=True)
    step("v2 progress of the short film plan", "GET", f"{plan}/progress/act-3")
    step("v2 direct video plan for H3", "POST", plan,
         json={"skill_type": "short_film", "story_description": "s", "target_scenes": 2, "video_model": "minimax_h3_i2v",
               "h3_audio_prompt": "calm",
               "music_video_treatment": {"generation_mode": "direct_video", "direct_video_master_prompt": "a master prompt"}},
         summarise=True)
    monkeypatch.setitem(services, "director_prompt_polish", "third_pass")
    monkeypatch.setitem(services, "nsfw_mode", True)
    step("v2 third pass with NSFW on a local model", "POST", plan,
         json={"skill_type": "podcast", "characters": [{"name": "A"}], "video_model": "m1", "image_model": "i1",
               "activity_id": "act-4", "transcript": "t"}, summarise=True)
    routing["provider"] = "openai"
    step("v2 NSFW with a public provider", "POST", plan, json={"skill_type": "podcast", "transcript": "t"}, summarise=True)
    routing["provider"] = "local"
    monkeypatch.setitem(services, "raw_prompts", True)
    step("v2 raw prompts", "POST", plan, json={"skill_type": "viral_video", "scene_description": "x"}, summarise=True)
    assert created, "the fake orchestrator was never built"
    assert steps["count"] > 100
