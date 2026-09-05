#!/usr/bin/env python3
"""Simulate whether a PR would be eligible to merge. Never merges.

Stdlib only. A missing or invalid snapshot is infrastructure (exit 2).
Policy rejects are exit 1. Exit 0 means the snapshot would be eligible in
simulation. `would_merge` is always false in this delivery: execute mode and
GitHub merge are not implemented and must not be enabled here.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "merge-eligibility-v1"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_CHECKS = (
    "Clean-repo guard + Python checks",
    "UI tests + lint + type-check + build",
    "UI E2E boot (Chromium + simulated API)",
    "CI required",
)
ALLOWED_BASE_REFS = {"development", "main"}
CURSOR_OK = "reviewed_at_head"
GATE_PATHS = {
    "scripts/evaluate_merge_eligibility.py",
    "scripts/ci_required.py",
    "scripts/verify_qa_evidence.py",
    "docs/development/MERGE_ELIGIBILITY.md",
}
OUT_OF_SCOPE_PREFIXES = (
    ".github/workflows/",
    "app/",
    "ui/src/",
    "outputs/",
)
OUT_OF_SCOPE_NAMES = {
    "pinokio.js",
    "pinokio.json",
    "install.js",
    "start.js",
    "update.js",
    "reset.js",
    "torch.js",
}
REQUIRED_TOP = (
    "schema_version",
    "mode",
    "pr",
    "base_ref",
    "base_sha",
    "head_sha",
    "expected_head_sha",
    "mergeable",
    "draft",
    "checks",
    "cursor",
    "qa",
    "blocking_findings",
    "files",
    "adapter",
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


def _out_of_scope(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    if normalized in GATE_PATHS:
        return f"{normalized} changes the merge gate itself"
    name = normalized.rsplit("/", 1)[-1]
    if name in OUT_OF_SCOPE_NAMES:
        return f"{normalized} is a launcher or install script"
    for prefix in OUT_OF_SCOPE_PREFIXES:
        if normalized.startswith(prefix):
            return f"{normalized} is out of the low-risk simulate scope"
    return None


def evaluate(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a decision. Never contacts GitHub. Never merges."""
    errors: list[str] = []
    reasons: list[str] = []
    if not isinstance(snapshot, dict) or not snapshot:
        return {
            "ok": False,
            "infra": True,
            "eligible": False,
            "would_merge": False,
            "reasons": ["snapshot is empty or not an object"],
        }
    missing = [key for key in REQUIRED_TOP if key not in snapshot]
    if missing:
        return {
            "ok": False,
            "infra": True,
            "eligible": False,
            "would_merge": False,
            "reasons": [f"missing field {key}" for key in missing],
        }
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")

    mode = str(snapshot.get("mode") or "").strip()
    if mode not in {"simulate", "execute"}:
        errors.append("mode must be simulate or execute")

    head = _sha(snapshot.get("head_sha"), "head_sha", errors)
    expected = _sha(snapshot.get("expected_head_sha"), "expected_head_sha", errors)
    base = _sha(snapshot.get("base_sha"), "base_sha", errors)
    base_ref = str(snapshot.get("base_ref") or "").strip()
    if base_ref not in ALLOWED_BASE_REFS:
        reasons.append(f"base_ref {base_ref!r} is not development or main")

    if snapshot.get("pr") in (None, ""):
        errors.append("pr is required")

    adapter = _as_dict(snapshot.get("adapter"), "adapter", errors)
    checks = _as_dict(snapshot.get("checks"), "checks", errors)
    cursor = _as_dict(snapshot.get("cursor"), "cursor", errors)
    qa = _as_dict(snapshot.get("qa"), "qa", errors)
    findings = _as_list(snapshot.get("blocking_findings"), "blocking_findings", errors)
    files = _as_list(snapshot.get("files"), "files", errors)

    if errors:
        return {
            "ok": False,
            "infra": True,
            "eligible": False,
            "would_merge": False,
            "reasons": errors,
            "head_sha": head,
            "base_sha": base,
            "mode": mode,
        }

    if adapter.get("token_sufficient") is False:
        return {
            "ok": False,
            "infra": True,
            "eligible": False,
            "would_merge": False,
            "reasons": ["adapter token is insufficient"],
            "head_sha": head,
            "base_sha": base,
            "mode": mode,
        }
    if adapter.get("can_change_protections"):
        reasons.append("adapter must not be able to change branch protections")
    if adapter.get("duplicate_event"):
        reasons.append("duplicate event: no merge action")

    if mode == "execute":
        reasons.append("execute adapter is not enabled; activation needs separate authorization")

    if snapshot.get("draft") is True:
        reasons.append("draft PRs are not eligible")
    if snapshot.get("mergeable") is not True:
        reasons.append("PR is not mergeable")
    if head and expected and head != expected:
        reasons.append("head_sha does not match expected_head_sha; HEAD advanced")

    for name in REQUIRED_CHECKS:
        value = str(checks.get(name) or "missing").strip().lower()
        if value != "success":
            reasons.append(f"required check {name}={value} (cancelled/skipped/missing are not success)")

    cursor_state = str(cursor.get("state") or "").strip()
    cursor_sha = str(cursor.get("head_sha") or "").strip().lower()
    if cursor_state != CURSOR_OK or (head and cursor_sha and cursor_sha != head):
        reasons.append(
            "Cursor must be reviewed_at_head for the current HEAD "
            "(stale, pending, unavailable and silence do not count)"
        )

    qa_status = str(qa.get("status") or "").strip()
    qa_sha = str(qa.get("tested_sha") or "").strip().lower()
    if qa_status != "pass" or (head and qa_sha and qa_sha != head):
        reasons.append("independent QA evidence must pass on the current HEAD")

    open_findings = [item for item in findings if str(item or "").strip()]
    if open_findings:
        reasons.append("blocking findings are open: " + ", ".join(str(item) for item in open_findings))

    if not files:
        reasons.append("files list is empty; fail closed")
    for path in files:
        if not isinstance(path, str) or not path.strip():
            reasons.append("files entries must be non-empty paths")
            continue
        detail = _out_of_scope(path.strip())
        if detail:
            reasons.append(detail)

    policy_eligible = not reasons
    return {
        "ok": True,
        "infra": False,
        "eligible": policy_eligible,
        "would_merge": False,
        "reasons": reasons or ["simulate: policy eligible; merge not performed"],
        "head_sha": head,
        "base_sha": base,
        "mode": mode,
        "pr": snapshot.get("pr"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="JSON snapshot of one PR")
    args = parser.parse_args(argv)
    path = Path(args.snapshot)
    if not path.is_file():
        print(f"snapshot not found: {path}", file=sys.stderr)
        return 2
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"snapshot is not readable JSON: {exc}", file=sys.stderr)
        return 2
    decision = evaluate(payload)
    json.dump(decision, sys.stdout, indent=2)
    sys.stdout.write("\n")
    if decision.get("infra"):
        return 2
    return 0 if decision.get("eligible") else 1


if __name__ == "__main__":
    raise SystemExit(main())
