"""Seeded coverage for simulated merge eligibility. Never merges."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.evaluate_merge_eligibility import REQUIRED_CHECKS, evaluate, main

HEAD = "b" * 40
BASE = "a" * 40
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_merge_eligibility.py"


def _snapshot(**overrides):
    payload = {
        "schema_version": "merge-eligibility-v1",
        "mode": "simulate",
        "pr": 1,
        "base_ref": "development",
        "base_sha": BASE,
        "head_sha": HEAD,
        "expected_head_sha": HEAD,
        "mergeable": True,
        "draft": False,
        "checks": {name: "success" for name in REQUIRED_CHECKS},
        "cursor": {"state": "reviewed_at_head", "head_sha": HEAD},
        "qa": {"status": "pass", "tested_sha": HEAD},
        "blocking_findings": [],
        "files": ["docs/development/AGENT_QA_POLICY.md"],
        "adapter": {
            "duplicate_event": False,
            "token_sufficient": True,
            "can_change_protections": False,
        },
    }
    payload.update(overrides)
    return payload


def test_three_eligible_low_risk_snapshots():
    docs = evaluate(_snapshot(pr=11, files=["docs/development/AGENT_QA_POLICY.md"]))
    tests = evaluate(_snapshot(pr=12, files=["tests/test_qa_evidence.py"]))
    template = evaluate(_snapshot(pr=13, files=[".github/pull_request_template.md"]))
    for decision in (docs, tests, template):
        assert decision["eligible"] is True
        assert decision["would_merge"] is False
        assert decision["infra"] is False
        assert decision["mode"] == "simulate"


def test_cancelled_ci_is_not_success():
    checks = {name: "success" for name in REQUIRED_CHECKS}
    checks["CI required"] = "cancelled"
    decision = evaluate(_snapshot(checks=checks))
    assert decision["eligible"] is False
    assert any("CI required=cancelled" in item for item in decision["reasons"])


def test_missing_cursor_or_stale_head_is_not_eligible():
    pending = evaluate(_snapshot(cursor={"state": "pending", "head_sha": HEAD}))
    stale = evaluate(_snapshot(cursor={"state": "reviewed_at_head", "head_sha": "c" * 40}))
    silent = evaluate(_snapshot(cursor={"state": "unavailable", "head_sha": HEAD}))
    for decision in (pending, stale, silent):
        assert decision["eligible"] is False
        assert any("Cursor must be reviewed_at_head" in item for item in decision["reasons"])


def test_head_advanced_is_not_eligible():
    decision = evaluate(_snapshot(expected_head_sha="d" * 40))
    assert decision["eligible"] is False
    assert any("HEAD advanced" in item for item in decision["reasons"])


def test_duplicate_event_does_not_merge():
    decision = evaluate(_snapshot(adapter={
        "duplicate_event": True,
        "token_sufficient": True,
        "can_change_protections": False,
    }))
    assert decision["eligible"] is False
    assert decision["would_merge"] is False
    assert any("duplicate event" in item for item in decision["reasons"])


def test_insufficient_token_is_infrastructure():
    decision = evaluate(_snapshot(adapter={
        "duplicate_event": False,
        "token_sufficient": False,
        "can_change_protections": False,
    }))
    assert decision["infra"] is True
    assert decision["eligible"] is False
    assert decision["would_merge"] is False


def test_adapter_that_can_change_protections_is_rejected():
    decision = evaluate(_snapshot(adapter={
        "duplicate_event": False,
        "token_sufficient": True,
        "can_change_protections": True,
    }))
    assert decision["eligible"] is False
    assert any("must not be able to change branch protections" in item for item in decision["reasons"])


def test_own_gate_change_is_not_eligible():
    decision = evaluate(_snapshot(files=["scripts/evaluate_merge_eligibility.py"]))
    assert decision["eligible"] is False
    assert any("merge gate itself" in item for item in decision["reasons"])


def test_product_and_workflow_paths_are_out_of_scope():
    app = evaluate(_snapshot(files=["app/services/music_submission.py"]))
    workflow = evaluate(_snapshot(files=[".github/workflows/ci.yml"]))
    for decision in (app, workflow):
        assert decision["eligible"] is False
        assert any("out of the low-risk" in item or "workflow" in item for item in decision["reasons"])


def test_execute_mode_is_never_enabled():
    decision = evaluate(_snapshot(mode="execute"))
    assert decision["eligible"] is False
    assert decision["would_merge"] is False
    assert any("execute adapter is not enabled" in item for item in decision["reasons"])


def test_missing_qa_or_blocking_findings_reject():
    qa = evaluate(_snapshot(qa={"status": "pending", "tested_sha": HEAD}))
    findings = evaluate(_snapshot(blocking_findings=["open medium"]))
    for decision in (qa, findings):
        assert decision["eligible"] is False


def test_missing_snapshot_is_infrastructure(tmp_path: Path):
    assert main(["--snapshot", str(tmp_path / "absent.json")]) == 2


def test_invalid_json_is_infrastructure(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")
    assert main(["--snapshot", str(path)]) == 2


def test_cli_eligible_and_reject(tmp_path: Path):
    ok_path = tmp_path / "ok.json"
    bad_path = tmp_path / "bad.json"
    ok_path.write_text(json.dumps(_snapshot()), encoding="utf-8")
    bad_path.write_text(json.dumps(_snapshot(draft=True)), encoding="utf-8")
    assert main(["--snapshot", str(ok_path)]) == 0
    assert main(["--snapshot", str(bad_path)]) == 1


def test_pilot_matches_policy():
    eligible = [
        _snapshot(pr=21, files=["docs/development/QA_ACCEPTANCE.md"]),
        _snapshot(pr=22, files=["tests/test_ci_required.py"]),
        _snapshot(pr=23, files=[".github/pull_request_template.md"]),
    ]
    ineligible = [
        _snapshot(pr=24, cursor={"state": "pending", "head_sha": HEAD}),
        _snapshot(pr=25, checks={**{name: "success" for name in REQUIRED_CHECKS}, "CI required": "cancelled"}),
    ]
    assert sum(1 for item in eligible if evaluate(item)["eligible"]) == 3
    assert sum(1 for item in ineligible if not evaluate(item)["eligible"]) == 2
    assert all(evaluate(item)["would_merge"] is False for item in eligible + ineligible)
