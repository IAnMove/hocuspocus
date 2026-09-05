"""Run the nightly wizard report parser tests in the Python CI job."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSER_TEST = ROOT / "scripts" / "tests" / "nightly_wizard_report.test.mjs"


def test_nightly_wizard_report_parser():
    node = shutil.which("node")
    assert node, "node is required to run scripts/tests/nightly_wizard_report.test.mjs"
    result = subprocess.run(
        [node, str(PARSER_TEST)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
