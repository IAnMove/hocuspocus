#!/usr/bin/env python3
"""Upsert a pull-request comment from a markdown file.

The measuring CI job stays read-only. This publisher only posts an already
generated report. The file must contain the expected HTML marker so a random
artifact cannot become the score comment.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_MARKER = "<!-- code-health-report -->"


def publish_pr_comment(markdown: str, *, marker: str) -> str:
    repository = os.environ.get("GITHUB_REPOSITORY")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not repository or not event_path:
        raise RuntimeError("GITHUB_REPOSITORY and GITHUB_EVENT_PATH are required to comment")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    number = (event.get("pull_request") or {}).get("number")
    if not number:
        return "skip: not a pull_request event"
    listed = subprocess.run(
        ["gh", "api", f"repos/{repository}/issues/{number}/comments", "--paginate"],
        capture_output=True,
        text=True,
        check=True,
    )
    comments = json.loads(listed.stdout or "[]")
    existing = next(
        (item["id"] for item in comments if marker in str(item.get("body") or "")),
        None,
    )
    payload = json.dumps({"body": markdown})
    if existing:
        subprocess.run(
            ["gh", "api", "-X", "PATCH", f"repos/{repository}/issues/comments/{existing}", "--input", "-"],
            input=payload,
            text=True,
            check=True,
            capture_output=True,
        )
        return f"updated:{existing}"
    subprocess.run(
        ["gh", "api", "-X", "POST", f"repos/{repository}/issues/{number}/comments", "--input", "-"],
        input=payload,
        text=True,
        check=True,
        capture_output=True,
    )
    return "created"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="markdown file to publish")
    parser.add_argument("--marker", default=DEFAULT_MARKER)
    args = parser.parse_args(argv)
    path = Path(args.file)
    if not path.is_file():
        print(f"skip: report file not found: {path}", file=sys.stderr)
        return 0
    markdown = path.read_text(encoding="utf-8")
    if args.marker not in markdown:
        print(f"refuse: {path} does not contain {args.marker}", file=sys.stderr)
        return 1
    markdown = markdown[markdown.index(args.marker):]
    try:
        result = publish_pr_comment(markdown, marker=args.marker)
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"WARN: could not comment on the PR: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
