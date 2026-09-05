#!/usr/bin/env python3
"""Publish an Independent QA check from a trusted workflow.

The GitHub check identity is this Actions job (GITHUB_TOKEN), not a role
declared inside the JSON. Scripts must run from the PR base tree.
Missing evidence is pending (neutral), never success.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Protocol

try:
    from scripts.verify_qa_provenance import load_envelope, verify_provenance
except ImportError:  # python scripts/publish_qa_check.py
    from verify_qa_provenance import load_envelope, verify_provenance

CHECK_NAME = "Independent QA"


class CheckAdapter(Protocol):
    def create_check(
        self,
        *,
        name: str,
        head_sha: str,
        conclusion: str,
        title: str,
        summary: str,
    ) -> str:
        ...


class GitHubCheckAdapter:
    def __init__(self, *, repository: str, token: str) -> None:
        self.repository = repository
        self.token = token

    def create_check(
        self,
        *,
        name: str,
        head_sha: str,
        conclusion: str,
        title: str,
        summary: str,
    ) -> str:
        body = json.dumps({
            "name": name,
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": conclusion,
            "output": {"title": title, "summary": summary[:65000]},
        }).encode()
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repository}/check-runs",
            data=body,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:500]
            raise RuntimeError(f"GitHub check-run failed: {exc.code} {detail}") from exc
        return str(payload.get("id") or "")


class RecordingAdapter:
    """Test double. Does not talk to GitHub."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_check(
        self,
        *,
        name: str,
        head_sha: str,
        conclusion: str,
        title: str,
        summary: str,
    ) -> str:
        self.calls.append({
            "name": name,
            "head_sha": head_sha,
            "conclusion": conclusion,
            "title": title,
            "summary": summary,
        })
        return f"fake-{len(self.calls)}"


def publish(
    *,
    envelope_path: Path,
    head: str,
    base: str,
    implementer: str,
    repository: str,
    run_id: str,
    adapter: CheckAdapter,
    risk: str = "routine",
    require_separation: bool = False,
) -> tuple[int, str]:
    payload, infra = load_envelope(envelope_path)
    if infra:
        adapter.create_check(
            name=CHECK_NAME,
            head_sha=head,
            conclusion="neutral",
            title="Independent QA pending",
            summary=infra,
        )
        return 0, infra
    assert payload is not None
    errors = verify_provenance(
        payload,
        head=head,
        base=base,
        implementer=implementer,
        repository=repository,
        run_id=run_id,
        risk=risk,
        require_separation=require_separation,
        artifact_exists=lambda rel: Path(rel).is_file(),
    )
    if errors:
        summary = "QA provenance rejected:\n" + "\n".join(f"- {item}" for item in errors)
        adapter.create_check(
            name=CHECK_NAME,
            head_sha=head,
            conclusion="failure",
            title="Independent QA rejected",
            summary=summary,
        )
        return 1, summary
    adapter.create_check(
        name=CHECK_NAME,
        head_sha=head,
        conclusion="success",
        title="Independent QA accepted",
        summary=f"Authenticated github_actions_check for {repository}@{head}",
    )
    return 0, "accepted"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--envelope", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--implementer", required=True)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--risk", default="routine")
    parser.add_argument("--require-separation", action="store_true")
    parser.add_argument("--adapter", choices=("github", "record"), default="github")
    args = parser.parse_args(argv)
    if not args.repository or not args.run_id:
        print("repository and run-id are required", file=sys.stderr)
        return 2
    if args.adapter == "record":
        adapter: CheckAdapter = RecordingAdapter()
    else:
        if not args.token:
            print("GITHUB_TOKEN is required for the github adapter", file=sys.stderr)
            return 2
        adapter = GitHubCheckAdapter(repository=args.repository, token=args.token)
    code, summary = publish(
        envelope_path=Path(args.envelope),
        head=args.head,
        base=args.base,
        implementer=args.implementer,
        repository=args.repository,
        run_id=args.run_id,
        adapter=adapter,
        risk=args.risk,
        require_separation=args.require_separation,
    )
    print(summary)
    if args.adapter == "record":
        json.dump(getattr(adapter, "calls"), sys.stdout)
        sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
