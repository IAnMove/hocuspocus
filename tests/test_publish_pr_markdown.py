"""Publisher-only coverage: the score comment is not written by the measuring job."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.publish_pr_markdown import DEFAULT_MARKER, main, publish_pr_comment


def test_refuses_markdown_without_marker(tmp_path: Path):
    path = tmp_path / "note.md"
    path.write_text("# no marker\n", encoding="utf-8")
    assert main(["--file", str(path)]) == 0


def test_missing_file_is_skip(tmp_path: Path):
    assert main(["--file", str(tmp_path / "absent.md")]) == 0


def test_creates_then_updates_existing_comment(tmp_path: Path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 151}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", "IAnMove/hocuspocus")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    calls: list[list[str]] = []
    state = {"listed": 0}

    def run(argv, **kwargs):
        class Result:
            stdout = "[]"
            returncode = 0
        calls.append(list(argv))
        if "--paginate" in argv:
            state["listed"] += 1
            if state["listed"] == 1:
                Result.stdout = "[]"
            else:
                Result.stdout = json.dumps([
                    {"id": 77, "body": f"{DEFAULT_MARKER}\nscore"}
                ])
        return Result()

    monkeypatch.setattr("scripts.publish_pr_markdown.subprocess.run", run)
    markdown = f"{DEFAULT_MARKER}\n## Code health\n**Quality score: 49.9/100**\n"
    assert publish_pr_comment(markdown, marker=DEFAULT_MARKER) == "created"
    assert publish_pr_comment(markdown, marker=DEFAULT_MARKER).startswith("updated:")
    assert any("-X" in call and "PATCH" in call for call in calls)
    assert any("-X" in call and "POST" in call for call in calls)


def test_cli_strips_helper_logs_before_marker(tmp_path: Path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 152}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", "IAnMove/hocuspocus")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    report = tmp_path / "code-health.md"
    report.write_text(
        "[code-health] fetching missing base abc\n"
        f"{DEFAULT_MARKER}\n## Code health\n**Quality score: 50.1/100**\n",
        encoding="utf-8",
    )
    posted: list[str] = []

    def run(argv, **kwargs):
        class Result:
            stdout = "[]"
            returncode = 0
        if kwargs.get("input"):
            posted.append(kwargs["input"])
        return Result()

    monkeypatch.setattr("scripts.publish_pr_markdown.subprocess.run", run)
    assert main(["--file", str(report)]) == 0
    assert posted
    body = json.loads(posted[0])["body"]
    assert body.startswith(DEFAULT_MARKER)
    assert "fetching missing base" not in body


def test_api_failure_does_not_fail_the_job(tmp_path: Path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 152}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", "IAnMove/hocuspocus")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    report = tmp_path / "code-health.md"
    report.write_text(f"{DEFAULT_MARKER}\n## Code health\n", encoding="utf-8")

    def run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(403, ["gh", "api"])

    monkeypatch.setattr("scripts.publish_pr_markdown.subprocess.run", run)
    assert main(["--file", str(report)]) == 0


def test_skips_when_not_a_pull_request(tmp_path: Path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"ref": "refs/heads/development"}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", "IAnMove/hocuspocus")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert publish_pr_comment(f"{DEFAULT_MARKER}\n", marker=DEFAULT_MARKER) == "skip: not a pull_request event"
