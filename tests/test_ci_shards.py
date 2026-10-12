"""Shard membership and CI wiring. No GitHub API required."""
from __future__ import annotations

import ast
import re
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
CORE_LOCK = ROOT / "app" / "runtime" / "locks" / "linux-core.txt"
# Pins these files share with the production core lock must not drift: CI
# would otherwise test FastAPI/Starlette/NumPy versions no user runs.
PINNED_WITH_CORE = (
    ROOT / "scripts" / "ci-python-requirements.txt",
    ROOT / "scripts" / "ci-production-browser-requirements.txt",
    ROOT / "app" / "runtime" / "requirements-core.txt",
)
# Tests that run ui/ scripts through tsx skip without ui/node_modules, so
# exactly one Python shard installs the UI dependencies and owns all of them.
# Any mention of node_modules marks such a test (this module excluded).
NODE_MARKER = "node_modules"


def _manifest():
    return load_manifest(MANIFEST)


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _job(workflow: str, job_id: str) -> str:
    """One job block of the workflow, from its key to the next job key."""
    match = re.search(rf"^  {re.escape(job_id)}:\n.*?(?=^  [a-z][a-z0-9-]*:\n|\Z)", workflow, re.S | re.M)
    assert match, job_id
    return match.group(0)


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if "==" in line and not line.startswith("-"):
            name, version = line.split("==", 1)
            pins[name.strip().lower().replace("_", "-")] = version.strip()
    return pins


def _static_collection(path: Path) -> int:
    """Test functions pytest collects, read from the source: no imports, no parametrize expansion."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    count = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            count += node.name.startswith("test")
        elif isinstance(node, ast.ClassDef) and (
            node.name.startswith("Test") or any("TestCase" in ast.dump(base) for base in node.bases)
        ):
            count += sum(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test")
                         for item in node.body)
    return count


def _node_dependent_tests() -> list[str]:
    own = Path(__file__).resolve()
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").glob("test_*.py")
        if path.resolve() != own and NODE_MARKER in path.read_text(encoding="utf-8")
    )


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
    manifest = _manifest()
    groups = manifest["groups"]
    assert [group["id"] for group in groups] == ["python-a", "python-b"]
    weights = [int(group["weight"]) for group in groups]
    assert min(weights) > 0
    assert max(weights) / min(weights) <= 1.25
    file_counts = [len(group["paths"]) for group in groups]
    assert abs(file_counts[0] - file_counts[1]) <= 5
    # The committed weights are a pytest --collect-only snapshot. Check the
    # balance against the tree itself too, so adding tests to one shard shows
    # up here instead of as a slow CI job.
    collected = [sum(_static_collection(ROOT / path) for path in group["paths"]) for group in groups]
    assert min(collected) > 0
    assert max(collected) / min(collected) <= 1.25
    note = manifest["weight_note"]
    assert re.search(r"\b20\d\d-\d\d-\d\d\b", note), "weight_note must date the collection"
    assert "--collect-only" in note


def test_ci_pins_follow_the_production_core_lock():
    lock = _pins(CORE_LOCK)
    assert {"fastapi", "starlette", "requests", "numpy", "pydantic", "uvicorn", "pillow"} <= set(lock)
    drift = {}
    for path in PINNED_WITH_CORE:
        for name, version in _pins(path).items():
            if name in lock and lock[name] != version:
                drift[f"{path.relative_to(ROOT).as_posix()}:{name}"] = (version, lock[name])
    assert drift == {}
    ci = _pins(PINNED_WITH_CORE[0])
    assert {"fastapi", "starlette", "requests", "numpy"} <= set(ci)


def test_node_dependent_python_tests_share_the_shard_that_installs_ui_deps():
    manifest = _manifest()
    owner = {path: group for group in manifest["groups"] for path in group["paths"]}
    node_tests = _node_dependent_tests()
    assert "tests/test_video2d_compile.py" in node_tests
    assert "tests/test_world3d_templates.py" in node_tests
    groups = {owner[path]["id"] for path in node_tests}
    assert len(groups) == 1, f"ui/node_modules tests span shards: {sorted(groups)}"
    workflow = _workflow()
    node_job = _job(workflow, owner[node_tests[0]]["job"])
    assert "actions/setup-node@" in node_job
    assert "npm ci --prefix ui --ignore-scripts" in node_job
    assert node_job.index("npm ci --prefix ui") < node_job.index("python -m pytest")
    for group in manifest["groups"]:
        if group["id"] not in groups:
            assert "npm ci" not in _job(workflow, group["job"])


def test_ui_e2e_runs_as_three_shards_that_ci_required_waits_for():
    workflow = _workflow()
    e2e = _job(workflow, "ui-e2e")
    assert "name: UI E2E boot (Chromium + simulated API) ${{ matrix.shard }}/3" in e2e
    assert "fail-fast: false" in e2e
    assert "shard: [1, 2, 3]" in e2e
    assert "npm run test:e2e -- --shard=${{ matrix.shard }}/3" in e2e
    assert e2e.count("npm run test:e2e:production") == 1
    assert "if: ${{ matrix.shard == 1 }}" in e2e
    assert "name: ui-e2e-artifacts-${{ matrix.shard }}" in e2e
    assert "continue-on-error:" not in e2e
    required = _job(workflow, "ci-required")
    assert "ui-e2e" in required.split("needs:", 1)[1].split("\n", 1)[0]
    assert "${{ needs.ui-e2e.result }}" in required


def test_windows_job_sets_up_node_before_its_first_node_step():
    windows = _job(_workflow(), "ui-speech-windows")
    # test_launcher_compatibility.py runs node scripts/check_runtime_profiles.cjs inside pytest.
    assert windows.index("actions/setup-node@") < windows.index("python -m pytest")


def test_workflow_lists_every_shard_in_needs_and_aggregator_pairs():
    workflow = _workflow()
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
    workflow = _workflow()
    assert "skip-ci" not in workflow
    assert "skip ci" not in workflow.lower()
    a = _job(workflow, "python-tests-a")
    b = _job(workflow, "python-tests-b")
    required = _job(workflow, "ci-required")
    for block in (a, b, required):
        assert "continue-on-error:" not in block
    guard = _job(workflow, "guard")
    assert "python -m pytest" not in guard
    assert "python -m compileall" in guard
    assert "--group python-a" in a
    assert "--group python-b" in b
    assert "test -s" in a
    assert "test -s" in b


def test_pip_cache_keys_include_locks_and_python_requirements():
    workflow = _workflow()
    a = _job(workflow, "python-tests-a")
    assert "cache: pip" in a
    assert "scripts/ci-python-requirements.txt" in a
    assert "scripts/ci-python-torch-cpu.txt" in a
    assert "app/requirements.txt" in a
    assert "app/runtime/locks/*.txt" in a
    windows = _job(workflow, "ui-speech-windows")
    assert "cache: pip" in windows
    assert "scripts/ci-python-windows-requirements.txt" in windows
    assert "app/runtime/locks/*.txt" in windows
    assert "actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9" in workflow
    assert "actions/cache@v" not in workflow
    assert "setup-python@v" not in workflow


def test_windows_speech_and_ui_e2e_stay_required():
    workflow = _workflow()
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
