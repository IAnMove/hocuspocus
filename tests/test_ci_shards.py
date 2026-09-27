"""Shard membership and CI wiring. No GitHub API required."""
from __future__ import annotations

from pathlib import Path

from scripts.ci_required import REQUIRED_JOB_NAMES
from scripts.select_local_tests import (
    discover_suite_files,
    grouped_paths,
    load_manifest,
    partition_errors,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts" / "ci_test_groups.json"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
AGGREGATOR = ROOT / "scripts" / "ci_required.py"


def _manifest():
    return load_manifest(MANIFEST)


def test_every_automated_test_file_is_in_exactly_one_group():
    manifest = _manifest()
    errors = partition_errors(ROOT, manifest)
    assert errors == []
    discovered = discover_suite_files(ROOT)
    grouped = grouped_paths(manifest)
    assert discovered
    assert sorted(grouped) == discovered
    assert len(grouped) == len(discovered)
    by_file = {}
    for group in manifest["groups"]:
        for path in group["paths"]:
            by_file.setdefault(path, []).append(group["id"])
    overlapped = {path: ids for path, ids in by_file.items() if len(ids) != 1}
    assert overlapped == {}


def test_shard_weights_are_duration_balanced():
    groups = _manifest()["groups"]
    assert [group["id"] for group in groups] == ["python-a", "python-b"]
    weights = [int(group["weight"]) for group in groups]
    assert min(weights) > 0
    assert max(weights) / min(weights) <= 1.25
    file_counts = [len(group["paths"]) for group in groups]
    assert abs(file_counts[0] - file_counts[1]) <= 5


def test_workflow_lists_every_shard_in_needs_and_aggregator_pairs():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    aggregator = AGGREGATOR.read_text(encoding="utf-8")
    assert "name: Python tests A" in workflow
    assert "name: Python tests B" in workflow
    assert "needs: [guard, python-tests-a, python-tests-b, ui-check, ui-e2e, ui-speech-windows]" in workflow
    assert 'Python tests A=${{ needs.python-tests-a.result }}' in workflow
    assert 'Python tests B=${{ needs.python-tests-b.result }}' in workflow
    assert 'Speech E2E Windows (real H.264 + AAC)=${{ needs.ui-speech-windows.result }}' in workflow
    for name in REQUIRED_JOB_NAMES:
        assert f'"{name}"' in aggregator
        assert f"{name}=" in workflow
    required_block = workflow[workflow.index("  ci-required:") :]
    assert "if: always()" in required_block
    assert "code-health-comment" not in required_block.split("needs:", 1)[1].split("\n", 1)[0]


def test_python_shards_do_not_weaken_required_jobs():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "skip-ci" not in workflow
    assert "skip ci" not in workflow.lower()
    a = workflow[workflow.index("  python-tests-a:") : workflow.index("  python-tests-b:")]
    b = workflow[workflow.index("  python-tests-b:") : workflow.index("  ui-check:")]
    required = workflow[workflow.index("  ci-required:") :]
    for block in (a, b, required):
        assert "continue-on-error:" not in block
    guard = workflow[workflow.index("  guard:") : workflow.index("  python-tests-a:")]
    assert "python -m pytest" not in guard
    assert "python -m compileall" in guard
    assert "--group python-a" in a
    assert "--group python-b" in b
    assert "test -s" in a
    assert "test -s" in b


def test_pip_cache_keys_include_locks_and_python_requirements():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    a = workflow[workflow.index("  python-tests-a:") : workflow.index("  python-tests-b:")]
    assert "cache: pip" in a
    assert "scripts/ci-python-requirements.txt" in a
    assert "scripts/ci-python-torch-cpu.txt" in a
    assert "app/requirements.txt" in a
    assert "app/runtime/locks/*.txt" in a
    windows = workflow[workflow.index("  ui-speech-windows:") : workflow.index("  code-health-comment:")]
    assert "cache: pip" in windows
    assert "scripts/ci-python-windows-requirements.txt" in windows
    assert "app/runtime/locks/*.txt" in windows
    assert "actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9" in workflow
    assert "actions/cache@v" not in workflow
    assert "setup-python@v" not in workflow


def test_windows_speech_and_ui_e2e_stay_required():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "name: Speech E2E Windows (real H.264 + AAC)" in workflow
    assert "name: UI E2E boot (Chromium + simulated API)" in workflow
    assert "HOCUSPOCUS_REQUIRE_SPEECH_AAC: \"1\"" in workflow
    assert "scene3d-speech.spec.ts scene3d-media-screen.spec.ts" in workflow


def test_job_display_names_match_manifest():
    manifest = _manifest()
    names = {group["id"]: group["name"] for group in manifest["groups"]}
    jobs = {group["id"]: group["job"] for group in manifest["groups"]}
    assert names["python-a"] == "Python tests A"
    assert names["python-b"] == "Python tests B"
    assert jobs["python-a"] == "python-tests-a"
    assert jobs["python-b"] == "python-tests-b"
    assert names["python-a"] in REQUIRED_JOB_NAMES
    assert names["python-b"] in REQUIRED_JOB_NAMES
