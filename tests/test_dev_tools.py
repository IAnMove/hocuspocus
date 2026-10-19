"""Unit tests for the developer tools. Merge weights are stubbed. No git merge."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.dev.architecture_map import composition_line_count, main as map_main, render
from scripts.dev.gates_lib import failure_details, format_summary, gate_exit_code
from scripts.dev.merge_prep_lib import (
    BalanceError,
    apply_weights,
    format_merge_summary,
    resolve_changelog,
    resolve_test_groups,
)


ROOT = Path(__file__).resolve().parents[1]
SENTENCE = (
    "Merge of branch with abcdef123 (2026-10-16): "
    "pytest --collect-only per group gives python-a 10 and python-b 10."
)


def _manifest(python_a: list[str], python_b: list[str], rules: list[dict] | None = None) -> dict:
    return {
        "version": 1,
        "weight_note": "seed 2026-10-01 --collect-only",
        "groups": [
            {"id": "python-a", "job": "python-tests-a", "name": "Python tests A", "weight": 1, "paths": list(python_a)},
            {"id": "python-b", "job": "python-tests-b", "name": "Python tests B", "weight": 1, "paths": list(python_b)},
        ],
        "path_rules": rules if rules is not None else [{"prefix": "app/x.py", "paths": ["tests/test_a.py"]}],
    }


def test_changelog_keeps_the_branch_paragraph_then_the_ref():
    ours = "# H\n\n## [Unreleased]\n\n**Branch.**\n\nstill the branch.\n\n## [1.0]\n\nOld.\n"
    theirs = "# H\n\n## [Unreleased]\n\n**Ref.**\n\nstill the ref.\n\n## [1.0]\n\nOld.\n"
    merged = resolve_changelog(ours, theirs)
    assert merged.index("**Branch.**") < merged.index("**Ref.**")
    assert "still the branch." in merged
    assert "still the ref." in merged
    assert merged.count("## [1.0]") == 1
    assert merged.count("Old.") == 1
    assert resolve_changelog(merged, theirs) == merged


def test_changelog_drops_a_duplicated_paragraph():
    ours = "Head\n\n**Same.**\n\nTail\n"
    theirs = "Head\n\n**Same.**\n\n**Extra.**\n\nTail\n"
    merged = resolve_changelog(ours, theirs)
    assert merged.count("**Same.**") == 1
    assert merged.index("**Same.**") < merged.index("**Extra.**")
    assert merged.endswith("Tail\n")


def test_groups_readd_without_reordering_and_append_new_rules():
    base = _manifest(["tests/test_a.py"], ["tests/test_b.py"])
    ours = _manifest(
        ["tests/test_a.py", "tests/test_new.py"],
        ["tests/test_b.py"],
        [
            {"prefix": "app/x.py", "paths": ["tests/test_a.py"]},
            {"prefix": "app/y.py", "paths": ["tests/test_new.py"]},
        ],
    )
    theirs = _manifest(["tests/test_a.py", "tests/test_ref.py"], ["tests/test_b.py", "tests/test_c.py"])
    merged = resolve_test_groups(base, ours, theirs, ["tests/test_new.py"])
    assert merged["groups"][0]["paths"] == ["tests/test_a.py", "tests/test_ref.py", "tests/test_new.py"]
    assert merged["groups"][1]["paths"] == ["tests/test_b.py", "tests/test_c.py"]
    assert [rule["prefix"] for rule in merged["path_rules"]] == ["app/x.py", "app/y.py"]
    assert merged["path_rules"][0]["paths"] == ["tests/test_a.py"]


def test_an_unassigned_new_test_goes_to_the_smaller_group():
    base = _manifest(["tests/test_a.py"], ["tests/test_b.py"])
    ours = _manifest(["tests/test_a.py"], ["tests/test_b.py"])
    theirs = _manifest(["tests/test_a.py", "tests/test_ref.py"], ["tests/test_b.py"])
    merged = resolve_test_groups(base, ours, theirs, ["tests/test_fresh.py"])
    assert merged["groups"][1]["paths"][-1] == "tests/test_fresh.py"
    assert merged["groups"][0]["paths"].count("tests/test_fresh.py") == 0


def test_weights_are_stubbed_and_the_note_is_not_repeated():
    manifest = _manifest(["tests/test_a.py"], ["tests/test_b.py"])
    weighted = apply_weights(manifest, {"python-a": 10, "python-b": 10}, SENTENCE)
    assert weighted["groups"][0]["weight"] == 10
    assert weighted["groups"][1]["weight"] == 10
    assert weighted["weight_note"].count(SENTENCE) == 1
    again = apply_weights(weighted, {"python-a": 10, "python-b": 10}, SENTENCE)
    assert again["weight_note"].count(SENTENCE) == 1


def test_weight_ratio_and_file_count_gap_fail():
    manifest = _manifest(["tests/test_a.py"], ["tests/test_b.py"])
    apply_weights(manifest, {"python-a": 125, "python-b": 100}, SENTENCE)
    with pytest.raises(BalanceError, match="weight ratio"):
        apply_weights(manifest, {"python-a": 126, "python-b": 100}, SENTENCE)
    five = _manifest(["tests/test_a.py"] * 6, ["tests/test_b.py"])
    apply_weights(five, {"python-a": 10, "python-b": 10}, SENTENCE)
    six = _manifest(["tests/test_a.py"] * 7, ["tests/test_b.py"])
    with pytest.raises(BalanceError, match="file-count gap"):
        apply_weights(six, {"python-a": 10, "python-b": 10}, SENTENCE)


def test_merge_summary_is_at_most_fifteen_lines():
    text = format_merge_summary([f"row {index}" for index in range(20)] + ["", "  "])
    assert len(text.splitlines()) == 15
    assert text.endswith("\n")


def test_gate_summary_lists_failures_and_stays_within_thirty_lines():
    results = [
        {"name": f"gate-{index}", "status": "PASS", "seconds": 0.2, "details": [], "log": f".dev-gates/gate-{index}.log"}
        for index in range(8)
    ]
    results.append({"name": "characterization", "status": "SKIP", "seconds": 0.0, "details": [], "log": ""})
    results.append({
        "name": "contract-tests",
        "status": "FAIL",
        "seconds": 3.5,
        "details": [f"tests/test_dev_tools.py::test_case_{index}" for index in range(5)],
        "log": ".dev-gates/contract-tests.log",
    })
    text = format_summary(results)
    assert len(text.splitlines()) <= 30
    assert "FAIL contract-tests (3.5s)" in text
    assert "SKIP characterization (0.0s)" in text
    assert "tests/test_dev_tools.py::test_case_0" in text
    assert "log: .dev-gates/contract-tests.log" in text
    assert gate_exit_code(results) == 1
    assert gate_exit_code([{"status": "PASS"}, {"status": "SKIP"}]) == 0


def test_a_long_failure_list_is_cut_to_thirty_lines():
    results = [
        {
            "name": f"bad-{index}",
            "status": "FAIL",
            "seconds": 1,
            "details": [f"tests/test_x.py::test_{index}_{case}" for case in range(5)],
            "log": f".dev-gates/bad-{index}.log",
        }
        for index in range(25)
    ]
    lines = format_summary(results).splitlines()
    assert len(lines) <= 30
    assert any(line.startswith("log:") for line in lines)


def test_failure_details_prefer_node_ids_then_the_first_error_line():
    log = "====\nFAILED tests/a.py::test_one - AssertionError: no\nFAILED tests/a.py::test_two\n"
    assert failure_details(log, limit=5) == ["tests/a.py::test_one", "tests/a.py::test_two"]
    assert failure_details("====\narchitecture fixtures are stale: route_table.json\n") == [
        "architecture fixtures are stale: route_table.json"
    ]


def test_architecture_map_is_deterministic_and_compact():
    first = render(ROOT)
    second = render(ROOT)
    assert first == second
    assert len(first.splitlines()) <= 400
    assert composition_line_count() <= 25
    assert "/mnt/" not in first
    assert "/home/" not in first
    assert "## Routers" in first
    assert "## UI slices" in first
    # Whether the committed docs/ARCHITECTURE_MAP.md is current is deliberately not a CI check:
    # it would fail every PR that adds a module or moves a line count. Refresh it with the script.


def test_architecture_check_detects_staleness_on_a_temp_copy(tmp_path: Path):
    target = tmp_path / "ARCHITECTURE_MAP.md"
    target.write_text(render(ROOT), encoding="utf-8")
    assert map_main(["--check", "--output", str(target), "--root", str(ROOT)]) == 0
    target.write_text(target.read_text(encoding="utf-8") + "stale line\n", encoding="utf-8")
    assert map_main(["--check", "--output", str(target), "--root", str(ROOT)]) == 1
