"""Director comic cheap reads: validation errors, a missing job, and no completed plan.

A real plan, a text-page rewrite and a story revision call an LLM. Those paths are not recorded here.
"""
from __future__ import annotations


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
