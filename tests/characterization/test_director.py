"""Director planner, pipeline and v2 plan cheap reads.

Validation errors, a missing pipeline, an unknown clip, a bad v2 plan body
and a missing plan job. A real plan calls an LLM. A real pipeline run uses
the GPU. Those paths are not recorded here.
"""
from __future__ import annotations

import json


def _save_one_clip(server, pid: str = "savedclip") -> str:
    """One saved pipeline with a single clip, so an out-of-range index fails before generation."""
    path = server.outputs / f"_director_pipeline_{pid}.json"
    path.write_text(json.dumps({
        "id": pid,
        "status": "completed",
        "clips": [{"image_prompt": "a cat", "video_prompt": "a cat walks"}],
        "clip_plans": [],
    }), encoding="utf-8")
    return pid


def test_director_routes_answer_the_recorded_errors(server, golden) -> None:
    """Validation and missing-resource answers for the Director routes this slice moves. No model runs."""
    server.check(golden, "classify without analysis", "POST", "/api/v1/director/classify-sections", json={})
    server.check(
        golden, "classify with no sections", "POST", "/api/v1/director/classify-sections",
        json={"analysis": {"sections": [], "duration": 0}},
    )
    server.check(golden, "plan prompts without clips", "POST", "/api/v1/director/plan-prompts-and-images", json={})
    server.check(
        golden, "plan prompts without a scene", "POST", "/api/v1/director/plan-prompts-and-images",
        json={"clips": [{}]},
    )
    server.check(golden, "plan dialogue without analysis", "POST", "/api/v1/director/plan-dialogue-scenes", json={})
    server.check(golden, "plan short film prompts without clips", "POST", "/api/v1/director/plan-short-film-prompts", json={})
    server.check(
        golden, "plan short film prompts without a scene", "POST", "/api/v1/director/plan-short-film-prompts",
        json={"clips": [{}]},
    )
    server.check(golden, "plan short film script without a story", "POST", "/api/v1/director/plan-short-film-script", json={})
    server.check(
        golden, "start with an unknown collection", "POST", "/api/v1/director/pipeline/start",
        json={"provenance": {"workspace_id": "no-such-collection"}},
    )

    missing = "missing"
    server.check(golden, "continue a missing pipeline", "POST", f"/api/v1/director/pipeline/{missing}/continue")
    server.check(golden, "preview a missing pipeline", "POST", f"/api/v1/director/pipeline/{missing}/generate-preview")
    server.check(golden, "patch a missing preview", "PATCH", f"/api/v1/director/pipeline/{missing}/preview", json={})
    server.check(golden, "stop a missing pipeline", "POST", f"/api/v1/director/pipeline/{missing}/stop")
    server.check(golden, "resume a missing pipeline", "POST", f"/api/v1/director/pipeline/{missing}/resume")
    server.check(golden, "repair a missing pipeline", "POST", f"/api/v1/director/pipelines/{missing}/repair")
    server.check(golden, "cancel a repair that is not running", "POST", f"/api/v1/director/pipelines/{missing}/repair/cancel")
    server.check(golden, "rejoin a missing pipeline", "POST", f"/api/v1/director/pipelines/{missing}/rejoin")
    server.check(golden, "delete a missing pipeline", "DELETE", f"/api/v1/director/pipelines/{missing}")

    pid = _save_one_clip(server)
    clip = f"/api/v1/director/pipelines/{pid}/clips/9"
    server.check(golden, "edit an unknown clip prompt", "PUT", f"{clip}/prompt", json={"video_prompt": "x"})
    server.check(golden, "tag an unknown clip", "PUT", f"{clip}/tag", json={"tag": "good"})
    server.check(golden, "select a video for an unknown clip", "PUT", f"{clip}/video-selection", json={})
    server.check(golden, "rerun an unknown clip image", "POST", f"{clip}/rerun-image", json={})
    server.check(golden, "rerun an unknown clip video", "POST", f"{clip}/rerun-video", json={})
    server.check(
        golden, "rerun an unknown segment", "POST", f"{clip}/segments/0/rerun", json={},
    )

    server.check(golden, "v2 plan with a bad body", "POST", "/api/v1/director/v2/plan", json=[])
    server.check(golden, "v2 plan jobs for an empty workspace", "GET", "/api/v1/director/v2/plan/jobs")
    server.check(golden, "v2 plan job that does not exist", "GET", "/api/v1/director/v2/plan/jobs/missing-job")
    server.check(
        golden, "resume a v2 plan job that does not exist", "POST",
        "/api/v1/director/v2/plan/jobs/missing-job/resume", json={},
    )
    server.check(
        golden, "v2 plan progress for a missing activity", "GET",
        "/api/v1/director/v2/plan/progress/missing-activity",
    )
