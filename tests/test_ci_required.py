"""Model-free coverage for the CI required aggregator."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci_required import evaluate, main


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_required.py"
REQUIRED = [
    "Clean-repo guard + Python checks=success",
    "UI tests + lint + type-check + build=success",
    "UI E2E boot (Chromium + simulated API)=success",
]


def test_all_success_is_ok():
    ok, failed = evaluate({
        "guard": "success",
        "ui": "success",
        "e2e": "success",
    })
    assert ok is True
    assert failed == []


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", ""])
def test_non_success_is_not_ok(result):
    ok, failed = evaluate({"guard": "success", "ui": result})
    assert ok is False
    assert failed == [f"ui={result or 'missing'}"]


def test_empty_results_fail():
    ok, failed = evaluate({})
    assert ok is False
    assert failed == ["no required jobs reported"]


def test_cli_success_exit():
    assert main(REQUIRED) == 0


def test_cli_failed_dependency_exit():
    pairs = list(REQUIRED)
    pairs[1] = "UI tests + lint + type-check + build=failure"
    assert main(pairs) == 1


def test_cli_cancelled_dependency_exit():
    pairs = list(REQUIRED)
    pairs[2] = "UI E2E boot (Chromium + simulated API)=cancelled"
    assert main(pairs) == 1


def test_cli_skipped_dependency_exit():
    pairs = list(REQUIRED)
    pairs[0] = "Clean-repo guard + Python checks=skipped"
    assert main(pairs) == 1


def test_cli_invalid_pair_fails_closed():
    assert main(["not-a-pair"]) == 2


def test_script_subprocess_matches_cli():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *REQUIRED],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    failed = subprocess.run(
        [sys.executable, str(SCRIPT), "docs=skipped", "ui=success", "e2e=success"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode == 1
    assert "docs=skipped" in failed.stderr
