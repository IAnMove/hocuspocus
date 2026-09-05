#!/usr/bin/env python3
"""Validate independent agent review/QA evidence for one commit.

Stdlib only. A missing file, unreadable JSON or schema break is
infrastructure (exit 2), not a pass. Policy rejects are exit 1.
Implementer-written JSON, CI green, Analyze and Bugbot silence never
count as independent review.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "qa-evidence-v1"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VALID_RESULTS = {"pass", "fail", "unevaluable"}
VALID_ROLES = {"technical_review", "adversarial_qa"}
INDEPENDENT_SOURCES = {"independent_agent_run", "coordinator_verified"}
FORBIDDEN_INDEPENDENT_SOURCES = {
    "implementer_self_attestation",
    "pr_comment",
    "analyze_pr",
    "ci_green",
    "bugbot_silence",
}
HIGH_RISK = {"persistence", "lyrics", "concurrency", "permissions"}
REQUIRED_CASES = {
    "routine": (),
    "persistence": ("cas", "cancel", "round_trip"),
    "lyrics": ("counterexample", "corpus"),
    "concurrency": ("race_or_lock",),
    "permissions": ("denied_path",),
}
REQUIRED_TOP = (
    "schema_version",
    "repo",
    "pr",
    "base_sha",
    "head_sha",
    "tested_sha",
    "requirement_version",
    "recorded_at",
    "implementer",
    "reviewers",
    "source",
    "cases",
    "findings",
    "artifacts",
    "cost",
)


def _as_dict(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return {}
    return value


def _as_list(value: Any, label: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return []
    return value


def _sha(value: Any, label: str, errors: list[str]) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        errors.append(f"{label} must be a 40-character lowercase git SHA")
        return ""
    return text


def validate(
    evidence: dict[str, Any],
    *,
    head: str,
    base: str,
    implementer: str,
    risk: str,
    require_separation: bool,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(evidence, dict) or not evidence:
        return ["evidence is empty or not an object"]
    for key in REQUIRED_TOP:
        if key not in evidence:
            errors.append(f"missing field {key}")
    if errors:
        return errors
    if evidence.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not str(evidence.get("repo") or "").strip():
        errors.append("repo is required")
    if evidence.get("pr") in (None, ""):
        errors.append("pr is required")
    head_sha = _sha(evidence.get("head_sha"), "head_sha", errors)
    tested = _sha(evidence.get("tested_sha"), "tested_sha", errors)
    base_sha = _sha(evidence.get("base_sha"), "base_sha", errors)
    expected_head = _sha(head, "--head", errors)
    expected_base = _sha(base, "--base", errors)
    if head_sha and tested and head_sha != tested:
        errors.append("tested_sha must equal head_sha; stale evidence is rejected")
    if head_sha and expected_head and head_sha != expected_head:
        errors.append("evidence head_sha does not match the current HEAD")
    if base_sha and expected_base and base_sha != expected_base:
        errors.append("evidence base_sha does not match the current PR base")
    if not str(evidence.get("requirement_version") or "").strip():
        errors.append("requirement_version is required")
    if not str(evidence.get("recorded_at") or "").strip():
        errors.append("recorded_at is required")

    impl = _as_dict(evidence.get("implementer"), "implementer", errors)
    impl_login = str(impl.get("login") or "").strip()
    impl_session = str(impl.get("session_id") or "").strip()
    if implementer and impl_login and impl_login != implementer:
        errors.append("implementer.login does not match --implementer")
    if not impl_login:
        errors.append("implementer.login is required")
    if not impl_session:
        errors.append("implementer.session_id is required")

    source = str(evidence.get("source") or "").strip()
    if source in FORBIDDEN_INDEPENDENT_SOURCES:
        errors.append(
            f"source {source!r} is not independent review "
            "(CI, Analyze, Bugbot silence, PR comments and self-attestation do not count)"
        )
    if source not in INDEPENDENT_SOURCES:
        errors.append(
            "independent evidence source must be independent_agent_run or coordinator_verified"
        )

    if risk in HIGH_RISK:
        require_separation = True
    reviewers = _as_list(evidence.get("reviewers"), "reviewers", errors)
    roles: set[str] = set()
    agents: set[str] = set()
    sessions: set[str] = set()
    for index, item in enumerate(reviewers):
        row = _as_dict(item, f"reviewers[{index}]", errors)
        agent = str(row.get("agent") or "").strip()
        role = str(row.get("role") or "").strip()
        session = str(row.get("session_id") or "").strip()
        if not agent:
            errors.append(f"reviewers[{index}].agent is required")
        if role not in VALID_ROLES:
            errors.append(f"reviewers[{index}].role must be technical_review or adversarial_qa")
        if not session:
            errors.append(f"reviewers[{index}].session_id is required")
        if agent and impl_login and agent == impl_login:
            errors.append("reviewer agent must not be the implementer")
        if require_separation and session and impl_session and session == impl_session:
            errors.append("reviewer session_id must differ from the implementer when separation is required")
        if role in VALID_ROLES:
            roles.add(role)
        if agent:
            agents.add(agent)
        if session:
            sessions.add(session)
    if "technical_review" not in roles:
        errors.append("technical_review reviewer is required")
    if risk in HIGH_RISK:
        if "adversarial_qa" not in roles:
            errors.append(f"{risk} risk requires a separate adversarial_qa reviewer")
        if len(agents) < 2:
            errors.append(f"{risk} risk requires two different reviewer agents")
        if len(sessions) < 2:
            errors.append(f"{risk} risk requires two different reviewer sessions")

    cases = _as_list(evidence.get("cases"), "cases", errors)
    seen_ids: set[str] = set()
    if risk == "routine" and not cases:
        errors.append("routine risk requires at least one executed case")
    for index, item in enumerate(cases):
        row = _as_dict(item, f"cases[{index}]", errors)
        case_id = str(row.get("id") or "").strip()
        result = str(row.get("result") or "").strip()
        if not case_id:
            errors.append(f"cases[{index}].id is required")
        if result not in VALID_RESULTS:
            errors.append(f"cases[{index}].result must be pass, fail or unevaluable")
        if result in {"fail", "unevaluable"}:
            errors.append(f"case {case_id or index} result {result} is not acceptance")
        if case_id:
            seen_ids.add(case_id)
    for required in REQUIRED_CASES.get(risk, ()):
        if required not in seen_ids:
            errors.append(f"missing required {risk} case {required}")

    findings = _as_list(evidence.get("findings"), "findings", errors)
    for index, item in enumerate(findings):
        row = _as_dict(item, f"findings[{index}]", errors)
        severity = str(row.get("severity") or "").strip()
        status = str(row.get("status") or "").strip()
        if severity == "blocking" and status != "resolved":
            errors.append("open blocking findings reject the evidence")

    artifacts = _as_list(evidence.get("artifacts"), "artifacts", errors)
    if artifacts is not None and not isinstance(evidence.get("artifacts"), list):
        errors.append("artifacts must be an array")

    cost = _as_dict(evidence.get("cost"), "cost", errors)
    if "cost" in evidence:
        if "known" not in cost:
            errors.append("cost.known is required (true or false; never invent counts)")
        if cost.get("known") is False and not str(cost.get("note") or "").strip():
            errors.append("cost.note is required when cost is not known")

    cursor = evidence.get("cursor")
    if cursor is not None:
        row = _as_dict(cursor, "cursor", errors)
        cursor_sha = str(row.get("head_sha") or "").strip().lower()
        if cursor_sha and expected_head and cursor_sha != expected_head:
            errors.append("Cursor review of another commit does not cover this HEAD")

    return errors


def load_evidence(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, f"QA pending: evidence file not found: {path}"
    try:
        text = path.read_text(encoding="utf-8")
        payload = json.loads(text)
    except (OSError, UnicodeError) as exc:
        return None, f"cannot read evidence file: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"evidence is not valid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "evidence JSON must be an object"
    return payload, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, help="path to evidence JSON")
    parser.add_argument("--head", required=True, help="current HEAD SHA")
    parser.add_argument("--base", required=True, help="current PR base SHA")
    parser.add_argument("--implementer", required=True, help="implementer login")
    parser.add_argument(
        "--risk",
        default="routine",
        choices=sorted(REQUIRED_CASES),
        help="risk class that selects required cases and reviewer separation",
    )
    parser.add_argument(
        "--require-separation",
        action="store_true",
        help="reject the same session for implementer and reviewer",
    )
    args = parser.parse_args(argv)
    payload, infra = load_evidence(Path(args.evidence))
    if infra:
        print(infra, file=sys.stderr)
        return 2
    assert payload is not None
    errors = validate(
        payload,
        head=args.head,
        base=args.base,
        implementer=args.implementer,
        risk=args.risk,
        require_separation=args.require_separation,
    )
    if errors:
        print("QA evidence rejected:", file=sys.stderr)
        for item in errors:
            print(f"- {item}", file=sys.stderr)
        return 1
    print(
        f"QA evidence accepted for {payload.get('repo')}@{payload.get('tested_sha')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
