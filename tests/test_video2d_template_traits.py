"""app/shared/video2d_template_traits.json is what the compiled cards do: the exporter's --check fails on drift.

Needs the UI dependencies (node and tsx): the exporter compiles every card with the real TypeScript compilers.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRAITS = ROOT / "app" / "shared" / "video2d_template_traits.json"
needs_ui = pytest.mark.skipif(
    not (ROOT / "ui/node_modules/tsx/dist/loader.mjs").is_file() or shutil.which("node") is None,
    reason="UI dependencies not installed in Python-only CI",
)


@needs_ui
def test_traits_match_the_compiled_cards():
    loader = ROOT / "ui/node_modules/tsx/dist/loader.mjs"
    result = subprocess.run([shutil.which("node"), "--import", str(loader), "scripts/export-video2d-traits.mjs", "--check"],
                            cwd=ROOT / "ui", capture_output=True, text=True, timeout=180, check=False)
    assert result.returncode == 0, result.stderr
    catalog = json.loads((ROOT / "app/shared/scene_templates.json").read_text(encoding="utf-8"))["entries"]
    traits = json.loads(TRAITS.read_text(encoding="utf-8"))
    assert traits["version"] == 1 and list(traits["templates"]) == [entry["id"] for entry in catalog]
    assert result.stdout.strip() == f"ok {len(catalog)}"
