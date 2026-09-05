"""Publisher-only coverage: the score comment is not written by the measuring job."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.publish_pr_markdown import DEFAULT_MARKER, main, publish_pr_comment


def test_refuses_markdown_without_marker(tmp_path: Path):
    path = tmp_path / "note.md"
    path.write_text("# no marker\n", encoding="utf-8")
    assert main(["--file", str(path)]) == 1


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


def test_skips_when_not_a_pull_request(tmp_path: Path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"ref": "refs/heads/development"}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", "IAnMove/hocuspocus")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert publish_pr_comment(f"{DEFAULT_MARKER}\n", marker=DEFAULT_MARKER) == "skip: not a pull_request event"
