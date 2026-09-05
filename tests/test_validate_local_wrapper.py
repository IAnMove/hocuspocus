"""Fake-executable coverage for local validation wrappers.

These tests never run the product suite, npm, or code_health.py. They only
check that the wrappers invoke the expected commands and fail closed.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "scripts" / "validate_local.sh"
HEALTH = ROOT / "scripts" / "check_code_health_pr_base.sh"


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _sandbox(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "app" / "services").mkdir(parents=True)
    (root / "app").mkdir(exist_ok=True)
    (root / "ui").mkdir()
    (root / "tests").mkdir()
    shutil.copy(VALIDATE, root / "scripts" / "validate_local.sh")
    os.chmod(root / "scripts" / "validate_local.sh", 0o755)
    _write_exec(root / "scripts" / "check_code_health_pr_base.sh", """#!/usr/bin/env bash
set -euo pipefail
echo "[code-health] stub HEAD=${HEAD_SHA:-} base=${BASE_SHA:-}"
echo "health $*" >> "${SANDBOX}/invocations.log"
if [[ -z "${BASE_SHA:-}" ]]; then
  echo "missing base" >&2
  exit 2
fi
if [[ "${HEALTH_FAIL:-0}" == "1" ]]; then
  echo "ratchet failed" >&2
  exit 1
fi
exit 0
""")
    bin_dir = tmp_path / "bin"
    _write_exec(bin_dir / "python", """#!/usr/bin/env bash
echo "python $*" >> "${SANDBOX}/invocations.log"
if [[ "${PYTHON_FAIL:-0}" == "1" ]]; then
  exit 1
fi
exit 0
""")
    _write_exec(bin_dir / "npm", """#!/usr/bin/env bash
echo "npm $*" >> "${SANDBOX}/invocations.log"
if [[ " $* " == *" budget "* && "${BUDGET_FAIL:-0}" == "1" ]]; then
  echo "budget exceeded" >&2
  exit 1
fi
exit 0
""")
    _write_exec(bin_dir / "git", """#!/usr/bin/env bash
echo "git $*" >> "${SANDBOX}/invocations.log"
exit 0
""")
    (tmp_path / "invocations.log").write_text("", encoding="utf-8")
    return root


def _env(tmp_path: Path, root: Path, **extra: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "PATH": f"{tmp_path / 'bin'}:{env.get('PATH', '')}",
        "PYTHON": str(tmp_path / "bin" / "python"),
        "SANDBOX": str(tmp_path),
        "HEAD_SHA": "headsha",
        "BASE_SHA": "basesha",
        "VALIDATE_LOCAL_LOG_DIR": str(tmp_path / "logs"),
    })
    env.update(extra)
    return env


def _run(root: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(root / "scripts" / "validate_local.sh"), *args],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _invocations(tmp_path: Path) -> str:
    return (tmp_path / "invocations.log").read_text(encoding="utf-8")


def test_unknown_argument_fails_closed(tmp_path: Path):
    root = _sandbox(tmp_path)
    result = _run(root, _env(tmp_path, root), "--nope")
    assert result.returncode == 2
    assert "unknown argument" in result.stderr
    assert "python" not in _invocations(tmp_path)


def test_missing_base_fails_before_long_work(tmp_path: Path):
    root = _sandbox(tmp_path)
    env = _env(tmp_path, root, BASE_SHA="", BASE_REF="origin/missing")
    result = _run(root, env)
    assert result.returncode == 2
    assert "refusing to skip the ratchet" in result.stderr
    assert "python -m pytest" not in _invocations(tmp_path)


def test_fast_mode_runs_contracts_not_full_suite(tmp_path: Path):
    root = _sandbox(tmp_path)
    result = _run(root, _env(tmp_path, root))
    log = result.stdout + result.stderr
    invoked = _invocations(tmp_path)
    assert result.returncode == 0
    assert "mode=fast (not CI-equivalent" in log
    assert "HEAD=headsha" in log
    assert "base=basesha" in log
    assert "test_tools_upscale_contract.py" in invoked
    assert "test_architecture_contracts.py" in invoked
    assert "verify_clean_repo.py" not in invoked
    assert " budget" not in invoked
    assert "fast checks passed (not CI-equivalent" in log
    assert "full checks passed (CI-equivalent" not in log


def test_full_mode_runs_required_checks_including_budget(tmp_path: Path):
    root = _sandbox(tmp_path)
    result = _run(root, _env(tmp_path, root), "--full")
    log = result.stdout + result.stderr
    invoked = _invocations(tmp_path)
    assert result.returncode == 0
    assert "mode=full (CI-equivalent" in log
    for token in (
        "verify_clean_repo.py",
        "check_dependency_contract.py",
        "check_documentation_links.py",
        "check_brand_contract.py",
        "compileall",
        "pytest -q",
        "npm test",
        "npm run lint",
        "npm run build",
        "npm run budget",
        "npm run test:e2e",
    ):
        assert token in invoked
    assert "full checks passed (CI-equivalent" in log


def test_full_never_skips_budget_failure(tmp_path: Path):
    root = _sandbox(tmp_path)
    result = _run(root, _env(tmp_path, root, BUDGET_FAIL="1"), "--full")
    assert result.returncode != 0
    assert "FAIL: ui build + budget" in result.stdout + result.stderr


def test_python_contract_failure_fails_fast_mode(tmp_path: Path):
    root = _sandbox(tmp_path)
    result = _run(root, _env(tmp_path, root, PYTHON_FAIL="1"))
    assert result.returncode != 0
    assert "FAIL: python contracts" in result.stdout + result.stderr


def test_ratchet_failure_fails_fast_mode(tmp_path: Path):
    root = _sandbox(tmp_path)
    result = _run(root, _env(tmp_path, root, HEALTH_FAIL="1"))
    assert result.returncode != 0
    assert "FAIL: code-health ratchet" in result.stdout + result.stderr


def test_health_wrapper_fails_without_base(tmp_path: Path):
    env = os.environ.copy()
    env["PYTHON"] = str(tmp_path / "bin" / "python")
    (tmp_path / "bin").mkdir()
    _write_exec(tmp_path / "bin" / "python", "#!/usr/bin/env bash\nexit 0\n")
    env["PATH"] = f"{tmp_path / 'bin'}:{env.get('PATH', '')}"
    env["BASE_SHA"] = ""
    env["BASE_REF"] = "origin/does-not-exist"
    result = subprocess.run(
        ["bash", str(HEALTH)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "cannot resolve base" in result.stderr


def test_health_wrapper_rejects_unknown_sha(tmp_path: Path):
    env = os.environ.copy()
    env["BASE_SHA"] = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    result = subprocess.run(
        ["bash", str(HEALTH)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "not a commit" in result.stderr
