"""production.review scores an injected sheet reader and never invents yes/no.

The default vision step is not called against a model and does not load weights.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.production_review import command_catalog, command_handlers


CLOSED = (
    "words_readable",
    "duplicate_people",
    "face_consistent",
    "text_covers_face",
)
PASSING = {
    "words_readable": "yes",
    "duplicate_people": "no",
    "face_consistent": "yes",
    "text_covers_face": "no",
}
PIXELS = b"\x89PNG-secret-pixels-E3"


def _layout(tmp_path: Path, vision=None):
    workspace = tmp_path / "outputs" / "clip"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "sheet.png").write_bytes(PIXELS)

    def workspace_dir(name: str) -> str:
        if name != "clip":
            raise HTTPException(status_code=400, detail="Invalid workspace name.")
        return str(workspace)

    return command_handlers(workspace_dir, vision), workspace


def _call(handlers, payload: dict) -> dict:
    return asyncio.run(handlers["production.review"]({"version": 1, "input": payload}))


def _vision(answers, calls):
    def ask(path, questions):
        calls.append((path, tuple(questions)))
        if isinstance(answers, Exception):
            raise answers
        return dict(answers)

    return ask


def test_failed_question_retakes_the_supplied_shot(tmp_path):
    calls = []
    answers = dict(PASSING, words_readable="no")
    handlers, _workspace = _layout(tmp_path, _vision(answers, calls))
    body = _call(handlers, {
        "workspace": "clip",
        "sheet": "sheet.png",
        "shots": [{"key": "intro"}],
    })
    result = body["result"]
    assert body["operation"] == "production.review"
    assert result["verdict"] == "retake"
    assert result["retake"] == ["intro"]
    assert result["answers"] == [
        {"question": "words_readable", "value": "no"},
        {"question": "duplicate_people", "value": "no"},
        {"question": "face_consistent", "value": "yes"},
        {"question": "text_covers_face", "value": "no"},
    ]
    assert calls[0][1] == CLOSED
    assert len(calls) == 1
    assert PIXELS not in json.dumps(body).encode("utf-8")


def test_all_good_answers_are_ok_with_an_empty_retake(tmp_path):
    calls = []
    handlers, workspace = _layout(tmp_path, _vision(PASSING, calls))
    body = _call(handlers, {
        "workspace": "clip",
        "sheet": "sheet.png",
        "shots": [{"key": "intro"}],
    })
    result = body["result"]
    assert result["verdict"] == "ok"
    assert result["retake"] == []
    assert [item["value"] for item in result["answers"]] == ["yes", "no", "yes", "no"]
    stored = json.loads((workspace / result["file"]).read_text(encoding="utf-8"))
    raw = json.dumps(stored, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    assert PIXELS not in raw
    assert PIXELS not in json.dumps(body).encode("utf-8")
    assert "workspace=clip" in result["url"]


def test_missing_or_raising_backend_does_not_invent_answers(tmp_path):
    missing, _workspace = _layout(tmp_path, None)
    raised, _workspace = _layout(tmp_path, _vision(RuntimeError("vlm down"), []))
    for handlers in (missing, raised):
        result = _call(handlers, {"workspace": "clip", "sheet": "sheet.png", "shots": [{"key": "intro"}]})["result"]
        assert result["verdict"] == "unreliable"
        assert result["reason"] == "vision_unavailable"
        assert result["answers"] == []
        assert result["retake"] == []
        assert "yes" not in json.dumps(result["answers"])
        assert "no" not in json.dumps(result["answers"])


@pytest.mark.parametrize("sheet", [
    "../outside.png",
    "/tmp/outside.png",
    "/api/v1/uploads/sheet.png",
    "/api/v1/file/sheet.png?workspace=other",
    "/api/v1/file/%2e%2e/sheet.png?workspace=clip",
])
def test_path_outside_the_workspace_is_rejected(tmp_path, sheet):
    calls = []
    handlers, _workspace = _layout(tmp_path, _vision(PASSING, calls))
    with pytest.raises(HTTPException) as caught:
        _call(handlers, {"workspace": "clip", "sheet": sheet, "shots": [{"key": "intro"}]})
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "path_not_allowed"
    assert caught.value.detail["retryable"] is False
    assert calls == []


def test_a_failed_answer_still_retakes_when_another_is_unknown(tmp_path):
    answers = dict(PASSING, words_readable="no", duplicate_people="unknown")
    handlers, _workspace = _layout(tmp_path, _vision(answers, []))
    result = _call(handlers, {
        "workspace": "clip",
        "sheet": "sheet.png",
        "shots": [{"key": "intro"}],
    })["result"]
    assert result["verdict"] == "retake"
    assert result["retake"] == ["intro"]
    assert result["reason"] is None


def test_unknown_without_a_failure_is_incomplete(tmp_path):
    answers = dict(PASSING, face_consistent="unknown")
    handlers, _workspace = _layout(tmp_path, _vision(answers, []))
    result = _call(handlers, {"workspace": "clip", "sheet": "sheet.png"})["result"]
    assert result["verdict"] == "unreliable"
    assert result["reason"] == "incomplete"
    assert result["retake"] == []


def test_omitted_shots_use_only_the_montage_key_when_a_question_fails(tmp_path):
    answers = dict(PASSING, text_covers_face="yes")
    handlers, _workspace = _layout(tmp_path, _vision(answers, []))
    result = _call(handlers, {"workspace": "clip", "sheet": "sheet.png"})["result"]
    assert result["verdict"] == "retake"
    assert result["retake"] == ["montage"]


def test_file_url_inside_the_workspace_is_accepted(tmp_path):
    calls = []
    handlers, workspace = _layout(tmp_path, _vision(PASSING, calls))
    result = _call(handlers, {
        "workspace": "clip",
        "sheet": "/api/v1/file/sheet.png?workspace=clip",
        "shots": [{"key": "intro"}],
    })["result"]
    assert result["verdict"] == "ok"
    assert result["retake"] == []
    assert Path(calls[0][0]) == (workspace / "sheet.png").resolve()


def test_symlink_outside_the_workspace_is_rejected(tmp_path):
    calls = []
    handlers, workspace = _layout(tmp_path, _vision(PASSING, calls))
    outside = tmp_path / "outside.png"
    outside.write_bytes(PIXELS)
    (workspace / "link.png").symlink_to(outside)
    with pytest.raises(HTTPException) as caught:
        _call(handlers, {"workspace": "clip", "sheet": "link.png"})
    assert caught.value.detail["code"] == "path_not_allowed"
    assert calls == []


def test_catalog_is_versioned_production_review():
    operation = command_catalog()[0]
    assert operation["name"] == "production.review"
    assert operation["version"] == 1
    schema = operation["inputSchema"]
    assert schema["properties"]["version"]["const"] == 1
    assert schema["properties"]["input"]["required"] == ["workspace", "sheet"]
    assert "shots" in schema["properties"]["input"]["properties"]


def test_a_non_answer_does_not_invent_yes_or_no(tmp_path):
    handlers, _workspace = _layout(tmp_path, _vision({"words_readable": "maybe"}, []))
    result = _call(handlers, {"workspace": "clip", "sheet": "sheet.png"})["result"]
    assert result["verdict"] == "unreliable"
    assert result["reason"] == "vision_unavailable"
    assert result["answers"] == []
    assert result["retake"] == []
