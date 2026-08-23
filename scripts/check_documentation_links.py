#!/usr/bin/env python3
"""Offline documentation drift and local-link check for DOC-01."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (ROOT / "README.md", ROOT / "ui" / "README.md")
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def local_target(document: Path, raw_target: str) -> Path | None:
    target = raw_target.strip().split("#", 1)[0]
    if not target or target.startswith(("http://", "https://", "mailto:")):
        return None
    return (document.parent / target).resolve()


def main() -> int:
    errors: list[str] = []
    for document in DOCUMENTS:
        if not document.is_file():
            errors.append(f"missing documentation file: {document.relative_to(ROOT)}")
            continue
        text = document.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            target = local_target(document, match.group(1))
            if target is not None and not target.exists():
                errors.append(
                    f"{document.relative_to(ROOT)}: broken local link {match.group(1)!r}"
                )

    ui_readme = (ROOT / "ui" / "README.md").read_text(encoding="utf-8")
    for required in ("npm ci", "npm run check", "src/api/client.ts", "../README.md"):
        if required not in ui_readme:
            errors.append(f"ui/README.md: missing required documentation {required!r}")
    if "React + TypeScript + Vite" in ui_readme:
        errors.append("ui/README.md: Vite template documentation returned")

    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for required in ("curl -X POST", "import requests", "await fetch", "Blizaine/Maestro"):
        if required not in root_readme:
            errors.append(f"README.md: missing launcher/API documentation {required!r}")

    issue_config = (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(
        encoding="utf-8"
    )
    expected_discussions = "https://github.com/IAnMove/loreframe-studio/discussions"
    if expected_discussions not in issue_config:
        errors.append("issue template: Loreframe Lab Discussions URL is missing")
    if "https://github.com/Blizaine/Maestro/discussions" in issue_config:
        errors.append("issue template: stale upstream Discussions URL remains")

    if errors:
        print("documentation contract: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("documentation contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
