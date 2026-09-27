"""Model-free coverage for the CI required aggregator."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci_required import REQUIRED_JOB_NAMES, evaluate, evaluate_required, main


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_required.py"
REQUIRED = [f"{name}=success" for name in REQUIRED_JOB_NAMES]


def _pairs_with(name: str, result: str) -> list[str]:
    return [f"{item}={result if item == name else 'success'}" for item in REQUIRED_JOB_NAMES]


def test_all_success_is_ok():
    ok, failed = evaluate({
        "guard": "success",
        "ui": "success",
        "e2e": "success",
        "speech_windows": "success",
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
    assert main(_pairs_with("UI tests + lint + type-check + build", "failure")) == 1


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", ""])
def test_windows_speech_export_is_a_required_dependency(result):
    assert main(_pairs_with("Speech E2E Windows (real H.264 + AAC)", result)) == 1


@pytest.mark.parametrize("name", ["Python tests A", "Python tests B"])
@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", ""])
def test_python_shards_are_required_dependencies(name, result):
    assert main(_pairs_with(name, result)) == 1


def test_cli_cancelled_dependency_exit():
    assert main(_pairs_with("UI E2E boot (Chromium + simulated API)", "cancelled")) == 1


def test_cli_skipped_dependency_exit():
    assert main(_pairs_with("Clean-repo guard + Python checks", "skipped")) == 1


def test_cli_missing_shard_fails_closed():
    pairs = [item for item in REQUIRED if not item.startswith("Python tests A=")]
    assert main(pairs) == 1


def test_evaluate_required_fills_in_missing_jobs():
    ok, failed = evaluate_required({
        "Clean-repo guard + Python checks": "success",
        "UI tests + lint + type-check + build": "success",
        "UI E2E boot (Chromium + simulated API)": "success",
        "Speech E2E Windows (real H.264 + AAC)": "success",
    })
    assert ok is False
    assert "Python tests A=missing" in failed
    assert "Python tests B=missing" in failed


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
    assert "Python tests A=missing" in failed.stderr
    assert "Python tests B=missing" in failed.stderr
