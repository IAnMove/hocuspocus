"""Seeded-defect coverage for independent QA evidence."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.verify_qa_evidence import main, validate


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_qa_evidence.py"
FIXTURES = ROOT / "tests" / "fixtures" / "qa_evidence"
HEAD = "b" * 40
BASE = "a" * 40


def _valid(**overrides):
    payload = json.loads(
        (FIXTURES / "valid_independent.json").read_text(encoding="utf-8")
    )
    payload.update(overrides)
    return payload


def _errors(payload, *, risk="routine", require_separation=False, **kwargs):
    return validate(
        payload,
        head=kwargs.get("head", HEAD),
        base=kwargs.get("base", BASE),
        implementer=kwargs.get("implementer", "impl-bot"),
        risk=risk,
        require_separation=require_separation,
    )


def test_valid_independent_fixture_passes():
    assert _errors(_valid()) == []


def test_missing_evidence_file_is_infrastructure(tmp_path: Path):
    missing = tmp_path / "absent.json"
    assert main([
        "--evidence", str(missing),
        "--head", HEAD,
        "--base", BASE,
        "--implementer", "impl-bot",
    ]) == 2


def test_invalid_json_is_infrastructure(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")
    assert main([
        "--evidence", str(path),
        "--head", HEAD,
        "--base", BASE,
        "--implementer", "impl-bot",
    ]) == 2


def test_stale_head_is_rejected():
    payload = _valid(tested_sha="c" * 40)
    errors = _errors(payload)
    assert any("stale" in item or "tested_sha" in item for item in errors)


def test_new_commit_invalidates_previous_head():
    errors = _errors(_valid(), head="d" * 40)
    assert any("does not match the current HEAD" in item for item in errors)


def test_implementer_self_attestation_is_rejected():
    payload = json.loads(
        (FIXTURES / "implementer_self.json").read_text(encoding="utf-8")
    )
    errors = _errors(payload, require_separation=True)
    assert any("not independent" in item or "must not be the implementer" in item for item in errors)
    assert main([
        "--evidence", str(FIXTURES / "implementer_self.json"),
        "--head", HEAD,
        "--base", BASE,
        "--implementer", "impl-bot",
        "--require-separation",
    ]) == 1


@pytest.mark.parametrize("source", ["analyze_pr", "ci_green", "bugbot_silence", "pr_comment"])
def test_heuristic_or_ci_is_not_independent(source):
    errors = _errors(_valid(source=source))
    assert any("not independent" in item for item in errors)


def test_missing_required_persistence_suites():
    errors = _errors(_valid(), risk="persistence")
    joined = " ".join(errors)
    assert "cas" in joined and "cancel" in joined and "round_trip" in joined
    assert any("adversarial_qa" in item for item in errors)


def test_persistence_cases_and_two_reviewers_pass():
    payload = _valid()
    payload["reviewers"] = [
        {"agent": "rev-a", "role": "technical_review", "session_id": "s-a"},
        {"agent": "rev-b", "role": "adversarial_qa", "session_id": "s-b"},
    ]
    payload["cases"] = [
        {"id": "cas", "requirement": "CAS conflict", "result": "pass"},
        {"id": "cancel", "requirement": "cancel mid-flight", "result": "pass"},
        {"id": "round_trip", "requirement": "reload without loss", "result": "pass"},
    ]
    assert _errors(payload, risk="persistence") == []


def test_lyrics_requires_counterexample_and_corpus():
    payload = _valid()
    payload["reviewers"] = [
        {"agent": "rev-a", "role": "technical_review", "session_id": "s-a"},
        {"agent": "rev-b", "role": "adversarial_qa", "session_id": "s-b"},
    ]
    payload["cases"] = [
        {"id": "counterexample", "requirement": "wrong-language lyric", "result": "pass"},
    ]
    errors = _errors(payload, risk="lyrics")
    assert any("corpus" in item for item in errors)


def test_open_blocking_finding_rejects():
    payload = _valid(findings=[{
        "severity": "blocking",
        "status": "open",
        "summary": "race",
    }])
    errors = _errors(payload)
    assert any("blocking" in item for item in errors)


def test_unevaluable_required_case_rejects():
    payload = _valid()
    payload["cases"] = [{
        "id": "wrapper-fail-closed",
        "requirement": "missing BASE_SHA fails closed",
        "result": "unevaluable",
    }]
    errors = _errors(payload)
    assert any("unevaluable" in item for item in errors)


def test_same_session_rejected_when_separation_required():
    payload = _valid()
    payload["reviewers"] = [{
        "agent": "review-bot",
        "role": "technical_review",
        "session_id": "session-impl",
    }]
    errors = _errors(payload, require_separation=True)
    assert any("session_id" in item for item in errors)


def test_cursor_of_other_commit_does_not_cover_head():
    payload = _valid(cursor={"head_sha": "e" * 40})
    errors = _errors(payload)
    assert any("Cursor" in item for item in errors)


def test_unknown_cost_needs_a_note():
    payload = _valid(cost={"known": False})
    errors = _errors(payload)
    assert any("cost.note" in item for item in errors)


def test_cli_accepts_valid_fixture():
    completed = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--evidence", str(FIXTURES / "valid_independent.json"),
            "--head", HEAD,
            "--base", BASE,
            "--implementer", "impl-bot",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0


def test_empty_object_is_rejected():
    errors = _errors({})
    assert any("empty" in item or "missing field" in item for item in errors)
