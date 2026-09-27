"""Fail-closed coverage for the local pytest selector. No GitHub required."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.select_local_tests import (
    ManifestError,
    check_partition,
    discover_suite_files,
    full_suite_paths,
    group_paths,
    load_manifest,
    main,
    select_paths,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "select_local_tests.py"
MANIFEST = ROOT / "scripts" / "ci_test_groups.json"


def _write_manifest(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_unknown_path_runs_union_of_all_groups():
    manifest = load_manifest(MANIFEST)
    selected, reason, unknown = select_paths(
        ["app/services/definitely-not-mapped.py"],
        ROOT,
        manifest,
    )
    assert reason == "unknown-path"
    assert unknown == ["app/services/definitely-not-mapped.py"]
    assert selected == full_suite_paths(ROOT, manifest)
    assert selected
    assert set(selected) == set(discover_suite_files(ROOT))


def test_known_test_file_is_mapped_to_itself():
    manifest = load_manifest(MANIFEST)
    selected, reason, unknown = select_paths(
        ["tests/test_ci_required.py"],
        ROOT,
        manifest,
    )
    assert reason == "mapped"
    assert unknown == []
    assert selected == ["tests/test_ci_required.py"]


def test_path_rule_maps_source_to_declared_tests():
    manifest = load_manifest(MANIFEST)
    selected, reason, unknown = select_paths(
        ["scripts/ci_required.py"],
        ROOT,
        manifest,
    )
    assert reason == "mapped"
    assert unknown == []
    assert selected == ["tests/test_ci_required.py"]


def test_empty_input_runs_full_suite_not_empty():
    manifest = load_manifest(MANIFEST)
    selected, reason, unknown = select_paths([], ROOT, manifest)
    assert reason == "empty-input"
    assert unknown == []
    assert selected
    assert selected == full_suite_paths(ROOT, manifest)


def test_known_plus_unknown_does_not_omit():
    manifest = load_manifest(MANIFEST)
    selected, reason, unknown = select_paths(
        ["tests/test_ci_required.py", "ui/src/not-a-python-mapping.tsx"],
        ROOT,
        manifest,
    )
    assert reason == "unknown-path"
    assert "ui/src/not-a-python-mapping.tsx" in unknown
    assert set(selected) == set(discover_suite_files(ROOT))


def test_broken_partition_falls_back_to_tests_directory():
    manifest = {
        "groups": [
            {
                "id": "python-a",
                "job": "python-tests-a",
                "name": "Python tests A",
                "paths": ["tests/test_ci_required.py"],
            }
        ],
        "path_rules": [],
    }
    selected, reason, unknown = select_paths(["mystery.py"], ROOT, manifest)
    assert reason == "unknown-path"
    assert selected == ["tests"]
    assert unknown == ["mystery.py"]


def test_group_selection_assigns_ungrouped_files_to_the_first_shard(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_one.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    (root / "tests" / "test_two.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    (root / "tests" / "test_three.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    manifest = {
        "groups": [
            {
                "id": "python-a",
                "job": "python-tests-a",
                "name": "Python tests A",
                "paths": ["tests/test_one.py"],
            },
            {
                "id": "python-b",
                "job": "python-tests-b",
                "name": "Python tests B",
                "paths": ["tests/test_three.py"],
            },
        ]
    }
    assert group_paths("python-a", root, manifest) == ["tests/test_one.py", "tests/test_two.py"]
    assert group_paths("python-b", root, manifest) == ["tests/test_three.py"]
    try:
        check_partition(root, manifest)
    except ManifestError as exc:
        assert "missing from groups" in str(exc)
        assert "tests/test_two.py" in str(exc)
    else:
        raise AssertionError("stale manifest must still fail --check-partition")


def test_missing_manifest_is_not_an_empty_suite(tmp_path: Path):
    missing = tmp_path / "absent.json"
    code = main(["--manifest", str(missing), "tests/test_ci_required.py"])
    assert code == 2


def test_cli_unknown_path_prints_full_suite():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "app/unknown_module.py"],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert completed.returncode == 0
    lines = [line for line in completed.stdout.splitlines() if line]
    assert lines
    assert "unknown path" in completed.stderr
    assert "running full suite" in completed.stderr
    assert "tests/test_ci_required.py" in lines
    assert set(lines) == set(discover_suite_files(ROOT))


def test_cli_group_is_non_empty_and_disjoint():
    a = subprocess.run(
        [sys.executable, str(SCRIPT), "--group", "python-a"],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    b = subprocess.run(
        [sys.executable, str(SCRIPT), "--group", "python-b"],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert a.returncode == 0
    assert b.returncode == 0
    paths_a = set(a.stdout.split())
    paths_b = set(b.stdout.split())
    assert paths_a
    assert paths_b
    assert paths_a.isdisjoint(paths_b)
    assert paths_a | paths_b == set(discover_suite_files(ROOT))


def test_cli_refuses_unknown_group():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--group", "python-z"],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "unknown group" in completed.stderr
