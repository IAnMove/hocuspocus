"""Story Lab cheap reads: an empty library, and the validation and missing-job answers.

Success paths that call an LLM, analyze a real image, or translate lyrics are not recorded here.
"""
from __future__ import annotations


def test_story_lab_routes_answer_the_recorded_errors(server, golden) -> None:
    """Validation and missing-job answers for the Story Lab routes this slice moves. No model runs."""
    server.check(golden, "library empty", "GET", "/api/v1/stories/library", params={"workspace": "default"})
    server.check(golden, "analyze without images", "POST", "/api/v1/stories/assets/analyze", json={})
    server.check(
        golden, "analyze a path outside uploads", "POST", "/api/v1/stories/assets/analyze",
        json={"assets": [{"path": "/tmp/not-an-upload.png", "name": "outside.png"}]},
    )
    server.check(
        golden, "analyze too many images", "POST", "/api/v1/stories/assets/analyze",
        json={"assets": [{"path": "x.png"} for _ in range(25)]},
    )
    server.check(golden, "generate the whole story at once", "POST", "/api/v1/stories/generate", json={"scope": "all"})
    server.check(golden, "generate an unknown scope", "POST", "/api/v1/stories/generate", json={"scope": "not-a-scope"})
    server.check(
        golden, "generate one stage without a premise", "POST", "/api/v1/stories/generate",
        json={"scope": "overview"},
    )
    server.check(golden, "translate without lyrics", "POST", "/api/v1/stories/translate-lyrics", json={})
    server.check(
        golden, "translate without a language", "POST", "/api/v1/stories/translate-lyrics",
        json={"lyrics": "Line one"},
    )
    server.check(
        golden, "start an unknown scope", "POST", "/api/v1/stories/generate/start",
        json={"scope": "not-a-scope", "premise": "A harbour."},
    )
    server.check(golden, "start without a premise", "POST", "/api/v1/stories/generate/start", json={"scope": "all"})
    job = "/api/v1/stories/generate"
    server.check(golden, "status of a missing job", "GET", f"{job}/status/missing-job")
    server.check(golden, "resume a missing job", "POST", f"{job}/resume/missing-job", json={})
    server.check(golden, "cancel a missing job", "POST", f"{job}/cancel/missing-job")
