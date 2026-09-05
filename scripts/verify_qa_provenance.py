#!/usr/bin/env python3
"""Authenticate QA evidence origin. Format checks stay in verify_qa_evidence.

A well-formed JSON is not provenance. The publisher must pass the current
GitHub Actions run identity; names inside the payload are not enough.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.verify_qa_evidence import load_evidence, validate
except ImportError:  # python scripts/verify_qa_provenance.py
    from verify_qa_evidence import load_evidence, validate

TRUSTED_WORKFLOWS = (".github/workflows/qa-evidence.yml",)
TRUSTED_KINDS = {"github_actions_check"}
FORBIDDEN_KINDS = {
    "implementer_self_attestation",
    "pr_comment",
    "analyze_pr",
    "ci_green",
    "bugbot_silence",
    "declared_in_json",
}


def verify_provenance(
    envelope: dict[str, Any],
    *,
    head: str,
    base: str,
    implementer: str,
    repository: str,
    run_id: str,
    risk: str = "routine",
    require_separation: bool = False,
    artifact_exists: Callable[[str], bool] | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(envelope, dict) or not envelope:
        return ["envelope is empty or not an object"]
    if "provenance" not in envelope:
        return ["missing provenance: format-valid evidence is not authenticated"]
    evidence = envelope.get("evidence")
    if not isinstance(evidence, dict):
        return ["envelope.evidence must be the qa-evidence-v1 object"]
    errors.extend(
        validate(
            evidence,
            head=head,
            base=base,
            implementer=implementer,
            risk=risk,
            require_separation=require_separation,
        )
    )
    provenance = envelope.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance must be an object")
        return errors
    kind = str(provenance.get("kind") or "").strip()
    if kind in FORBIDDEN_KINDS:
        errors.append(f"provenance.kind {kind!r} is not an authenticated origin")
    if kind not in TRUSTED_KINDS:
        errors.append("provenance.kind must be github_actions_check")
    if str(provenance.get("repository") or "") != repository:
        errors.append("provenance.repository does not match the publisher repository")
    workflow = str(provenance.get("workflow_file") or "").replace("\\", "/")
    if workflow not in TRUSTED_WORKFLOWS:
        errors.append("provenance.workflow_file is not a trusted publisher workflow")
    if str(provenance.get("run_id") or "") != str(run_id):
        errors.append("provenance.run_id does not match the current GitHub Actions run")
    if str(provenance.get("head_sha") or "").strip().lower() != head.lower():
        errors.append("provenance.head_sha does not match the current HEAD")
    if str(provenance.get("base_sha") or "").strip().lower() != base.lower():
        errors.append("provenance.base_sha does not match the current PR base")
    producer = provenance.get("producer") if isinstance(provenance.get("producer"), dict) else {}
    producer_login = str(producer.get("login") or "").strip()
    if not producer_login:
        errors.append("provenance.producer.login is required")
    if producer_login and implementer and producer_login == implementer:
        errors.append("provenance.producer must not be the implementer")
    artifacts = evidence.get("artifacts") if isinstance(evidence.get("artifacts"), list) else []
    if artifact_exists is not None:
        for item in artifacts:
            path = ""
            if isinstance(item, str):
                path = item
            elif isinstance(item, dict):
                path = str(item.get("path") or item.get("uri") or "")
            if path and not path.startswith(("http://", "https://")) and not artifact_exists(path):
                errors.append(f"artifact missing: {path}")
    return errors


def load_envelope(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    payload, infra = load_evidence(path)
    if infra:
        return None, infra
    return payload, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--envelope", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--implementer", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--risk", default="routine")
    parser.add_argument("--require-separation", action="store_true")
    args = parser.parse_args(argv)
    payload, infra = load_envelope(Path(args.envelope))
    if infra:
        print(infra, file=sys.stderr)
        return 2
    assert payload is not None
    errors = verify_provenance(
        payload,
        head=args.head,
        base=args.base,
        implementer=args.implementer,
        repository=args.repository,
        run_id=args.run_id,
        risk=args.risk,
        require_separation=args.require_separation,
        artifact_exists=lambda rel: Path(rel).is_file(),
    )
    if errors:
        print("QA provenance rejected:", file=sys.stderr)
        for item in errors:
            print(f"- {item}", file=sys.stderr)
        return 1
    print(f"QA provenance accepted for {args.repository}@{args.head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
