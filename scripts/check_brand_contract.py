#!/usr/bin/env python3
"""Guard visible HocusPocus branding without renaming legacy contracts."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def without_js_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))


def main() -> int:
    errors: list[str] = []

    ui_root = ROOT / "ui" / "src"
    for path in ui_root.rglob("*"):
        if path.suffix not in {".ts", ".tsx", ".css"}:
            continue
        code = without_js_comments(path.read_text(encoding="utf-8"))
        if re.search(r"\bMaestro\b", code):
            errors.append(f"visible legacy brand remains in {path.relative_to(ROOT)}")

    required = {
        ROOT / "pinokio.js": (
            'title: "HocusPocus · Creation Lab"',
            "forked from Maestro",
        ),
        ROOT / "ui" / "index.html": (
            "<title>HocusPocus · Creation Lab</title>",
            "HocusPocus UI failed to load",
        ),
        ROOT / "app" / "_launch_runtime.py": (
            'FastAPI(title="HocusPocus Lab API"',
            "HocusPocus Lab UI:",
            "[HocusPocus Lab] React UI serving",
        ),
        ROOT / "README.md": (
            "# HocusPocus · Creation Lab",
            "Blizaine/Maestro",
        ),
    }
    for path, snippets in required.items():
        text = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in text:
                errors.append(f"{path.relative_to(ROOT)}: missing {snippet!r}")

    old_visible = {
        ROOT / "update.js": (
            "Maestro has uncommitted changes",
            "Already up to date. Maestro",
        ),
        ROOT / "app" / "_launch_runtime.py": (
            'FastAPI(title="Maestro API"',
            "  Maestro UI:",
            "[Maestro] React UI serving",
            'FastAPI(title="Loreframe Lab API"',
            "Loreframe Lab UI:",
            "[Loreframe Lab] React UI serving",
        ),
        ROOT / "pinokio.js": (
            'title: "Loreframe Lab · Experimental"',
        ),
        ROOT / "ui" / "index.html": (
            "<title>Loreframe Lab · Experimental</title>",
            "Loreframe Lab UI failed to load",
        ),
        ROOT / "README.md": (
            "# Loreframe Lab",
        ),
    }
    for path, snippets in old_visible.items():
        text = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet in text:
                errors.append(f"{path.relative_to(ROOT)}: visible legacy string {snippet!r}")

    # These names are persisted/API/subprocess contracts. BRAND-01 must never
    # turn a display-name change into a destructive data migration.
    compatibility = {
        ROOT / "ui" / "src" / "features" / "video-editor" / "editorDraft.ts":
            "maestro-video-editor-draft-v1",
        ROOT / "ui" / "src" / "features" / "stories" / "types.ts":
            "| 'maestro'",
        ROOT / "app" / "services" / "task_manager.py":
            ".maestro-tasks-v1.sqlite3",
        ROOT / "app" / "services" / "rigging" / "rig_worker_unirig.py":
            "MAESTRO_EVENT",
    }
    for path, snippet in compatibility.items():
        if snippet not in path.read_text(encoding="utf-8"):
            errors.append(f"{path.relative_to(ROOT)}: compatibility contract {snippet!r} changed")

    if errors:
        print("brand contract: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("brand contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
