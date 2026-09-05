"""Provenance is separate from format validation. Fake adapter only."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.publish_qa_check import RecordingAdapter, publish
from scripts.verify_qa_evidence import validate
from scripts.verify_qa_provenance import verify_provenance

ROOT = Path(__file__).resolve().parents[1]
HEAD = "b" * 40
BASE = "a" * 40
REPO = "IAnMove/hocuspocus"
RUN = "run-123"
IMPL = "impl-bot"


def _evidence(**overrides):
    payload = json.loads(
        (ROOT / "tests/fixtures/qa_evidence/valid_independent.json").read_text(encoding="utf-8")
    )
    payload.update(overrides)
    return payload


def _envelope(evidence=None, **provenance_overrides):
    provenance = {
        "kind": "github_actions_check",
        "repository": REPO,
        "workflow_file": ".github/workflows/qa-evidence.yml",
        "run_id": RUN,
        "head_sha": HEAD,
        "base_sha": BASE,
        "producer": {"login": "qa-bot", "session_id": "qa-session"},
    }
    provenance.update(provenance_overrides)
    return {"evidence": evidence or _evidence(), "provenance": provenance}


def _errors(envelope, **kwargs):
    return verify_provenance(
        envelope,
        head=kwargs.get("head", HEAD),
        base=kwargs.get("base", BASE),
        implementer=kwargs.get("implementer", IMPL),
        repository=kwargs.get("repository", REPO),
        run_id=kwargs.get("run_id", RUN),
        artifact_exists=kwargs.get("artifact_exists", lambda path: (ROOT / path).is_file()),
    )


def test_format_valid_json_without_provenance_is_not_authenticated():
    assert validate(
        _evidence(),
        head=HEAD,
        base=BASE,
        implementer=IMPL,
        risk="routine",
        require_separation=False,
    ) == []
    errors = _errors({"evidence": _evidence()})
    assert any("missing provenance" in item for item in errors)


def test_valid_envelope_with_verified_provenance_passes():
    assert _errors(_envelope()) == []


def test_falsely_attributed_producer_is_rejected():
    errors = _errors(_envelope(producer={"login": IMPL, "session_id": "qa-session"}))
    assert any("must not be the implementer" in item for item in errors)


def test_wrong_head_sha_is_rejected():
    errors = _errors(_envelope(), head="c" * 40)
    assert any("HEAD" in item for item in errors)


def test_stale_run_id_is_rejected():
    errors = _errors(_envelope(), run_id="run-old")
    assert any("run_id" in item for item in errors)


def test_untrusted_workflow_file_is_rejected():
    errors = _errors(_envelope(workflow_file=".github/workflows/ci.yml"))
    assert any("trusted publisher workflow" in item for item in errors)


def test_missing_artifact_is_rejected():
    evidence = _evidence(artifacts=["tests/fixtures/qa_evidence/does-not-exist.json"])
    errors = _errors(_envelope(evidence=evidence))
    assert any("artifact missing" in item for item in errors)


def test_open_blocking_finding_is_rejected():
    evidence = _evidence(findings=[{"severity": "blocking", "status": "open", "summary": "race"}])
    errors = _errors(_envelope(evidence=evidence))
    assert any("blocking" in item for item in errors)


def test_publisher_missing_envelope_is_pending_not_success(tmp_path: Path):
    adapter = RecordingAdapter()
    code, summary = publish(
        envelope_path=tmp_path / "absent.json",
        head=HEAD,
        base=BASE,
        implementer=IMPL,
        repository=REPO,
        run_id=RUN,
        adapter=adapter,
    )
    assert code == 0
    assert adapter.calls[0]["conclusion"] == "neutral"
    assert "pending" in adapter.calls[0]["title"].lower() or "pending" in summary.lower()
    assert adapter.calls[0]["conclusion"] != "success"


def test_publisher_rejects_unauthenticated_evidence(tmp_path: Path):
    path = tmp_path / "plain.json"
    path.write_text(json.dumps(_evidence()), encoding="utf-8")
    adapter = RecordingAdapter()
    code, _summary = publish(
        envelope_path=path,
        head=HEAD,
        base=BASE,
        implementer=IMPL,
        repository=REPO,
        run_id=RUN,
        adapter=adapter,
    )
    assert code == 1
    assert adapter.calls[0]["conclusion"] == "failure"


def test_publisher_success_uses_adapter_not_json_role(tmp_path: Path):
    path = tmp_path / "ok.json"
    path.write_text(json.dumps(_envelope()), encoding="utf-8")
    adapter = RecordingAdapter()
    code, _summary = publish(
        envelope_path=path,
        head=HEAD,
        base=BASE,
        implementer=IMPL,
        repository=REPO,
        run_id=RUN,
        adapter=adapter,
    )
    assert code == 0
    assert adapter.calls[0]["name"] == "Independent QA"
    assert adapter.calls[0]["head_sha"] == HEAD
    assert adapter.calls[0]["conclusion"] == "success"
